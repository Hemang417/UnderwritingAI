import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AdapterPermanentError, AdapterTransientError
from app.adapters.maha_rera import LiveMahaRERAAdapter
from app.discovery import repository
from app.discovery.models import CandidateMatch, CanonicalProject
from app.discovery.scoring import CompositeRanker, ScoredCandidate, SearchInput, normalize_text

MAX_CANDIDATES_SHOWN = 5

# Best-effort mapping from MAHARERA's own status vocabulary to this
# platform's (under_construction/nearing_completion/completed -- the same
# values FieldCatalog's RISK_PARAMS.status_risk_scores keys off). MAHARERA's
# exact live strings are unconfirmed until tested against real data; falls
# back to "under_construction" (the most conservative -- highest risk
# weight) for anything unrecognized, logged rather than silently guessed.
_STATUS_MAP = {
    "new project": "under_construction",
    "ongoing project": "under_construction",
    "project completed": "completed",
}


class RankingConfigMissingError(Exception):
    """No active RankingConfig row exists -- a setup/seeding error, not a
    normal search outcome."""


class SearchQueryNotFoundError(Exception):
    pass


class NotACandidateError(Exception):
    """Raised when a confirm request names a project that wasn't actually
    among the scored candidates for that search query."""


class ConfirmedMappingNotFoundError(Exception):
    pass


class LiveResolveInputError(Exception):
    """No project_name was given."""


class LiveResolveNotFoundError(Exception):
    """MAHARERA's search returned no matching project."""


class LiveResolveSourceError(Exception):
    """The live MAHARERA adapter failed (auth, network, or the site
    itself) -- distinct from "not found," which is a normal outcome."""


@dataclass
class SearchOutcome:
    status: Literal["previous_mapping", "resolved", "needs_confirmation", "no_match"]
    search_query_id: uuid.UUID | None = None
    mapping_id: uuid.UUID | None = None
    project: CanonicalProject | None = None
    candidates: list[ScoredCandidate] | None = None
    auto_confirmed: bool | None = None


def _normalize_city(city_hint: str | None) -> str | None:
    return normalize_text(city_hint) if city_hint else None


async def search(
    session: AsyncSession, *, user_id: uuid.UUID, raw_text: str, city_hint: str | None, force_refresh: bool
) -> SearchOutcome:
    normalized_text = normalize_text(raw_text)
    normalized_city = _normalize_city(city_hint)

    if not force_refresh:
        mapping = await repository.get_confirmed_mapping(session, normalized_text, normalized_city)
        if mapping is not None:
            project = await repository.get_project_by_id(session, mapping.canonical_project_id)
            return SearchOutcome(status="previous_mapping", mapping_id=mapping.id, project=project)

    config = await repository.get_active_ranking_config(session)
    if config is None:
        raise RankingConfigMissingError

    search_query = await repository.create_search_query(
        session,
        user_id=user_id,
        raw_text=raw_text,
        normalized_text=normalized_text,
        city_hint=normalized_city,
    )

    projects = await repository.list_projects(session)
    historical_hits = await repository.get_historical_hit_counts(session)
    ranker = CompositeRanker(weights=config.weights)
    scored = ranker.rank(
        projects, SearchInput(normalized_text=normalized_text, city_hint=normalized_city), historical_hits
    )

    candidate_rows = [
        CandidateMatch(
            search_query_id=search_query.id,
            canonical_project_id=result.project.id,
            score_exact_name=result.scores["exact_name"],
            score_fuzzy_name=result.scores["fuzzy_name"],
            score_city=result.scores["city"],
            score_historical_selection=result.scores["historical_selection"],
            composite_score=result.composite_score,
        )
        for result in scored
    ]
    persisted_rows = await repository.bulk_create_candidate_matches(session, candidate_rows)
    row_by_project_id = {row.canonical_project_id: row for row in persisted_rows}

    if not scored:
        await session.commit()
        return SearchOutcome(status="no_match", search_query_id=search_query.id)

    top = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None
    separation = top.composite_score - runner_up.composite_score if runner_up else top.composite_score

    # Auto-proceed only when the top candidate clears a high bar AND is
    # clearly separated from the runner-up -- anything less ambiguous still
    # goes to the analyst per PRD "never automatically choose one" unless
    # confidence is genuinely unambiguous.
    if top.composite_score >= config.auto_proceed_threshold and separation >= config.separation_margin:
        chosen_row = row_by_project_id[top.project.id]
        await repository.mark_candidate_chosen(session, chosen_row)
        await repository.upsert_confirmed_mapping(
            session,
            normalized_text=normalized_text,
            city_hint=normalized_city,
            canonical_project_id=top.project.id,
            confidence=top.composite_score,
            confirmed_by=user_id,
        )
        await session.commit()
        return SearchOutcome(
            status="resolved", search_query_id=search_query.id, project=top.project, auto_confirmed=True
        )

    shown = [c for c in scored if c.composite_score >= config.show_threshold][:MAX_CANDIDATES_SHOWN]
    for candidate in shown:
        row_by_project_id[candidate.project.id].shown = True
    await session.commit()
    if shown:
        return SearchOutcome(status="needs_confirmation", search_query_id=search_query.id, candidates=shown)

    return SearchOutcome(status="no_match", search_query_id=search_query.id)


async def confirm(
    session: AsyncSession, *, user_id: uuid.UUID, search_query_id: uuid.UUID, canonical_project_id: uuid.UUID
) -> tuple[CanonicalProject, uuid.UUID]:
    search_query = await repository.get_search_query_by_id(session, search_query_id)
    if search_query is None:
        raise SearchQueryNotFoundError

    candidate_matches = await repository.get_candidate_matches_for_query(session, search_query_id)
    match = next(
        (c for c in candidate_matches if c.canonical_project_id == canonical_project_id and c.shown),
        None,
    )
    if match is None:
        raise NotACandidateError

    await repository.mark_candidate_chosen(session, match)
    mapping = await repository.upsert_confirmed_mapping(
        session,
        normalized_text=search_query.normalized_text,
        city_hint=search_query.city_hint,
        canonical_project_id=canonical_project_id,
        confidence=match.composite_score,
        confirmed_by=user_id,
    )
    await session.commit()
    project = await repository.get_project_by_id(session, canonical_project_id)
    return project, mapping.id


async def reuse_mapping(
    session: AsyncSession, *, mapping_id: uuid.UUID
) -> tuple[CanonicalProject, uuid.UUID]:
    mapping = await repository.get_confirmed_mapping_by_id(session, mapping_id)
    if mapping is None:
        raise ConfirmedMappingNotFoundError

    mapping = await repository.touch_confirmed_mapping(session, mapping)
    await session.commit()
    project = await repository.get_project_by_id(session, mapping.canonical_project_id)
    return project, mapping.id


async def resolve_via_live_maharera(session: AsyncSession, *, project_name: str) -> CanonicalProject:
    """The actual "add a project not already in the database" pathway:
    looks the project up live on MAHARERA's own public API and creates a
    new CanonicalProject from what it finds. Only reachable through an
    explicit endpoint (never a silent fallback inside normal /search) since
    it's slow, depends on a human-obtained JWT, and hits a live external
    system -- see app/adapters/maha_rera_live.py.

    Search is by project_name only -- MAHARERA's live search has no
    reliable way to look up a project by RERA registration number alone
    (confirmed in practice, not just in theory: a bounded scan of the
    unfiltered project list essentially never reaches an arbitrary
    project), so that path isn't offered here.

    If the resolved RERA number already exists locally, returns the
    existing project rather than creating a duplicate.
    """
    project_name = (project_name or "").strip()
    if not project_name:
        raise LiveResolveInputError("Provide a project_name")

    adapter = LiveMahaRERAAdapter()
    try:
        stubs = await adapter.search_project({"project_name": project_name})
    except (AdapterPermanentError, AdapterTransientError) as exc:
        raise LiveResolveSourceError(str(exc)) from exc

    if not stubs:
        raise LiveResolveNotFoundError(project_name)

    stub = stubs[0]  # best-effort: take MAHARERA's top match

    existing = await repository.get_project_by_rera_number(session, stub["registration_number"])
    if existing is not None:
        return existing

    try:
        identity = await adapter.fetch_identity_by_project_id(stub["project_id"])
    except (AdapterPermanentError, AdapterTransientError) as exc:
        raise LiveResolveSourceError(str(exc)) from exc

    developer_name = identity.get("developer_name") or stub["developer_name"] or "Unknown Developer"
    developer = await repository.get_or_create_developer(session, developer_name)

    status_name = (identity.get("status_name") or "").strip().lower()
    status = _STATUS_MAP.get(status_name, "under_construction")

    project = await repository.create_project(
        session,
        CanonicalProject(
            developer_id=developer.id,
            state="Maharashtra",  # MAHARERA is Maharashtra-only, matching this platform's MVP scope
            rera_registration_number=identity.get("registration_number") or stub["registration_number"],
            project_name=identity.get("project_name") or stub["project_name"],
            locality=identity.get("taluka") or identity.get("village") or identity.get("district") or "",
            city=identity.get("district") or stub["district"] or "",
            status=status,
            maharera_project_id=stub["project_id"],
        ),
    )
    await session.commit()
    return project
