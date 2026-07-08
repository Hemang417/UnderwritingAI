import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery import repository
from app.discovery.models import CandidateMatch, CanonicalProject
from app.discovery.scoring import CompositeRanker, ScoredCandidate, SearchInput, normalize_text

MAX_CANDIDATES_SHOWN = 5


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
