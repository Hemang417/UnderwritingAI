import dataclasses
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import service as analytics_service
from app.core.storage import ObjectStorage
from app.discovery.models import CanonicalProject
from app.llm import guardrail
from app.llm.base import LLMProvider, PromptSpec
from app.reporting import repository
from app.reporting.assembly import SECTION_JSON_SLICERS, SECTION_NAMES, assemble_report_json
from app.reporting.gating import check_completeness
from app.reporting.models import GuardrailStatus, Report, ReportSection, ReportVersion, ReportVersionStatus
from app.reporting.pdf import render_report_pdf
from app.reporting.prompts import SECTION_SYSTEM_INSTRUCTIONS, TEMPLATE_VERSION
from app.scenario import service as scenario_service

_NON_TERMINAL_STATUSES = (
    ReportVersionStatus.GENERATING,
    ReportVersionStatus.DRAFT,
    ReportVersionStatus.FAILED,
    ReportVersionStatus.IN_REVIEW,
)

# SAD S12 / ADR-009: "bounded (~2 attempts)" corrective regeneration --
# up to 2 additional LLM calls beyond the first, each with the unmatched
# claims named explicitly in the corrective prompt.
MAX_REGENERATION_ATTEMPTS = 2


class CompletenessGateBlockedError(Exception):
    """ADR-015: required fields are missing/stale and the caller didn't
    explicitly opt to proceed anyway. Carries the exact issue list so the
    API can surface it without a second round-trip."""

    def __init__(self, issues):
        self.issues = issues
        super().__init__(f"{len(issues)} field(s) missing or stale")


class ReportVersionNotFoundError(Exception):
    pass


class SectionNotFoundError(Exception):
    pass


class SectionNotEditableError(Exception):
    """Sections are only editable while their ReportVersion is in Draft --
    once submitted or published, content is frozen for review/audit."""


class GuardrailAlreadyPassedError(Exception):
    """Acknowledgment only makes sense for a section whose *effective*
    (edited, if any) guardrail status is currently FAILED."""


class InvalidTransitionError(Exception):
    """ADR-010: transitions are validated server-side; an invalid one is
    rejected loudly, never silently coerced into whatever's convenient."""


class UnacknowledgedGuardrailFailureError(Exception):
    """Blocks submit-for-review while any section's effective guardrail
    status is FAILED and hasn't been explicitly acknowledged (SAD S12's
    logged human-acknowledged exception path, applied at the gate)."""

    def __init__(self, section_names: list[str]):
        self.section_names = section_names
        super().__init__(f"{len(section_names)} section(s) have unacknowledged guardrail failures")


@dataclass
class SectionGenerationResult:
    section_name: str
    guardrail_status: GuardrailStatus
    attempt_count: int


async def _generate_section_with_guardrail(
    llm_provider: LLMProvider, prompt_spec: PromptSpec, reference_set: guardrail.ReferenceSet
) -> tuple[str, guardrail.GuardrailResult, int]:
    response = await llm_provider.generate(prompt_spec)
    text = response.text
    result = guardrail.validate(text, reference_set)
    attempt = 1

    while not result.passed and attempt <= MAX_REGENERATION_ATTEMPTS:
        attempt += 1
        unmatched_desc = ", ".join(f"'{u['raw_text']}'" for u in result.unmatched)
        corrective_spec = dataclasses.replace(
            prompt_spec,
            system_instruction=(
                prompt_spec.system_instruction
                + f"\n\nYour previous draft included these numbers/dates that could not be verified "
                f"against the source data: {unmatched_desc}. Remove or correct them -- only use "
                "values that appear in the provided JSON."
            ),
        )
        response = await llm_provider.generate(corrective_spec)
        text = response.text
        result = guardrail.validate(text, reference_set)

    return text, result, attempt


async def generate_report(
    session: AsyncSession,
    *,
    project: CanonicalProject,
    requested_by: uuid.UUID,
    llm_provider: LLMProvider,
    force_override: bool = False,
) -> ReportVersion:
    """Report generation. Mirrors the SAD S5.2 flow: gate -> engines ->
    scenarios -> assemble+freeze JSON -> per-section generate+guardrail ->
    Draft or Failed. Regeneration always creates a new version (PRD S14) --
    if the report's current version was never published, it's marked
    SUPERSEDED; if it *was* published, it is never touched (ADR-010) and
    the new version simply records a forward supersedes_version_id pointer.
    """
    issues = await check_completeness(session, project.id)
    if issues and not force_override:
        raise CompletenessGateBlockedError(issues)

    report = await repository.get_report_by_project_id(session, project.id)
    if report is None:
        report = await repository.create_report(session, Report(canonical_project_id=project.id))

    # Fresh engine + scenario runs, not whatever happens to already exist --
    # a report always reflects the current state of the world at generation
    # time (M5/M6 each persist their own versioned, reproducible history).
    await analytics_service.run_all_engines(session, project=project)
    await scenario_service.run_all_scenarios(session, project=project)

    generated_json = await assemble_report_json(session, project=project)
    reference_set = guardrail.build_reference_set(generated_json)

    previous_version = await repository.get_latest_report_version(session, report.id)
    if previous_version is not None and previous_version.status in _NON_TERMINAL_STATUSES:
        previous_version.status = ReportVersionStatus.SUPERSEDED

    version = await repository.create_report_version(
        session,
        ReportVersion(
            report_id=report.id,
            version_number=(previous_version.version_number + 1) if previous_version else 1,
            status=ReportVersionStatus.GENERATING,
            generated_json=generated_json,
            llm_provider=llm_provider.provider_name,
            completeness_issues=[i.to_dict() for i in issues],
            completeness_overridden=bool(issues) and force_override,
            created_by=requested_by,
            supersedes_version_id=previous_version.id if previous_version else None,
        ),
    )

    all_passed = True
    for section_name in SECTION_NAMES:
        json_slice = SECTION_JSON_SLICERS[section_name](generated_json)
        prompt_spec = PromptSpec(
            section_name=section_name,
            system_instruction=SECTION_SYSTEM_INSTRUCTIONS[section_name],
            json_slice=json_slice,
            template_version=TEMPLATE_VERSION,
        )
        text, result, attempt_count = await _generate_section_with_guardrail(
            llm_provider, prompt_spec, reference_set
        )
        section_status = GuardrailStatus.PASSED if result.passed else GuardrailStatus.FAILED
        all_passed = all_passed and result.passed

        await repository.create_report_section(
            session,
            ReportSection(
                report_version_id=version.id,
                section_name=section_name,
                template_version=TEMPLATE_VERSION,
                generated_text=text,
                guardrail_status=section_status,
                guardrail_report={"matched": result.matched, "unmatched": result.unmatched},
                attempt_count=attempt_count,
            ),
        )

    version.guardrail_status = GuardrailStatus.PASSED if all_passed else GuardrailStatus.FAILED
    version.status = ReportVersionStatus.DRAFT if all_passed else ReportVersionStatus.FAILED
    report.current_version_id = version.id

    await session.commit()
    return await repository.get_report_version_by_id(session, version.id)


async def edit_section(
    session: AsyncSession, *, section_id: uuid.UUID, new_text: str, edited_by: uuid.UUID
) -> ReportSection:
    """SAD S5.2 "Analyst edits (overlay preserves original text)": lands in
    `edited_text`, never touches `generated_text`. Re-runs the guardrail
    against the edit using the same frozen generated_json the original
    generation checked against -- an edit is held to the identical
    traceability standard as LLM output, not a lesser one. A fresh edit
    clears any prior acknowledgment: it must be re-earned, not inherited.
    """
    section = await repository.get_report_section_by_id(session, section_id)
    if section is None:
        raise SectionNotFoundError(section_id)

    version = await repository.get_report_version_by_id(session, section.report_version_id)
    if version is None or version.status != ReportVersionStatus.DRAFT:
        raise SectionNotEditableError(
            "Sections can only be edited while the report version is in Draft status"
        )

    reference_set = guardrail.build_reference_set(version.generated_json)
    result = guardrail.validate(new_text, reference_set)

    section.edited_text = new_text
    section.edited_by = edited_by
    section.edited_at = datetime.now(UTC)
    section.edited_guardrail_status = GuardrailStatus.PASSED if result.passed else GuardrailStatus.FAILED
    section.edited_guardrail_report = {"matched": result.matched, "unmatched": result.unmatched}
    section.guardrail_acknowledged_by = None
    section.guardrail_acknowledgment_note = None

    await session.commit()
    return section


async def acknowledge_section_guardrail_failure(
    session: AsyncSession, *, section_id: uuid.UUID, acknowledged_by: uuid.UUID, note: str
) -> ReportSection:
    """SAD S12's logged human-acknowledged exception path -- lets an
    analyst's edit proceed to submission despite a guardrail failure (e.g.
    an intentional approximate qualitative figure), on record: who, when,
    why. Only meaningful while the failure is still current."""
    section = await repository.get_report_section_by_id(session, section_id)
    if section is None:
        raise SectionNotFoundError(section_id)

    if section.effective_guardrail_status != GuardrailStatus.FAILED:
        raise GuardrailAlreadyPassedError("This section's guardrail already passed -- nothing to acknowledge")

    section.guardrail_acknowledged_by = acknowledged_by
    section.guardrail_acknowledgment_note = note
    await session.commit()
    return section


async def submit_for_review(session: AsyncSession, *, version_id: uuid.UUID) -> ReportVersion:
    version = await repository.get_report_version_by_id(session, version_id)
    if version is None:
        raise ReportVersionNotFoundError(version_id)
    if version.status != ReportVersionStatus.DRAFT:
        raise InvalidTransitionError(f"Cannot submit a version with status '{version.status}' for review")

    unacknowledged = [
        s.section_name
        for s in version.sections
        if s.effective_guardrail_status == GuardrailStatus.FAILED and s.guardrail_acknowledged_by is None
    ]
    if unacknowledged:
        raise UnacknowledgedGuardrailFailureError(unacknowledged)

    version.status = ReportVersionStatus.IN_REVIEW
    await session.commit()
    return version


async def decide_review(
    session: AsyncSession,
    *,
    version_id: uuid.UUID,
    reviewed_by: uuid.UUID,
    approved: bool,
    comments: str | None,
    project: CanonicalProject,
    storage: ObjectStorage,
) -> ReportVersion:
    """SAD S5.2: approve -> Published (immutable, DB-enforced) + PDF
    render; reject -> back to Draft with comments, the Reviewer never
    edits content directly (PRD S14's two-person control)."""
    version = await repository.get_report_version_by_id(session, version_id)
    if version is None:
        raise ReportVersionNotFoundError(version_id)
    if version.status != ReportVersionStatus.IN_REVIEW:
        raise InvalidTransitionError(f"Cannot review a version with status '{version.status}'")

    version.reviewed_by = reviewed_by
    version.reviewed_at = datetime.now(UTC)
    version.review_comments = comments

    if approved:
        pdf_bytes = render_report_pdf(
            project=project, version_number=version.version_number, sections=version.sections
        )
        storage_key = f"{project.id}/{version.id}.pdf"
        storage.save(storage_key, pdf_bytes)

        version.status = ReportVersionStatus.PUBLISHED
        version.published_by = reviewed_by
        version.published_at = datetime.now(UTC)
        version.pdf_storage_key = storage_key

        report = await repository.get_report_by_id(session, version.report_id)
        report.current_version_id = version.id
    else:
        version.status = ReportVersionStatus.DRAFT

    await session.commit()
    return version
