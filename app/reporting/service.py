import dataclasses
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import service as analytics_service
from app.discovery.models import CanonicalProject
from app.llm import guardrail
from app.llm.base import LLMProvider, PromptSpec
from app.reporting import repository
from app.reporting.assembly import SECTION_JSON_SLICERS, SECTION_NAMES, assemble_report_json
from app.reporting.gating import check_completeness
from app.reporting.models import GuardrailStatus, Report, ReportSection, ReportVersion, ReportVersionStatus
from app.reporting.prompts import SECTION_SYSTEM_INSTRUCTIONS, TEMPLATE_VERSION
from app.scenario import service as scenario_service

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
    """Report generation, Draft-only per the M7 roadmap entry (submit for
    review / publish / PDF are M8). Mirrors the SAD S5.2 flow: gate ->
    engines -> scenarios -> assemble+freeze JSON -> per-section
    generate+guardrail -> Draft or Failed.
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
