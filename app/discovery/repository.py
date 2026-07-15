import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.discovery.models import (
    CandidateMatch,
    CanonicalProject,
    ConfirmedMapping,
    Developer,
    RankingConfig,
    SearchQuery,
)


async def get_active_ranking_config(session: AsyncSession) -> RankingConfig | None:
    stmt = (
        select(RankingConfig)
        .where(RankingConfig.is_active.is_(True))
        .order_by(RankingConfig.version.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def get_confirmed_mapping(
    session: AsyncSession, normalized_text: str, city_hint: str | None
) -> ConfirmedMapping | None:
    stmt = select(ConfirmedMapping).where(
        ConfirmedMapping.normalized_search_string == normalized_text,
        ConfirmedMapping.city_hint == city_hint,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_confirmed_mapping_by_id(
    session: AsyncSession, mapping_id: uuid.UUID
) -> ConfirmedMapping | None:
    return await session.get(ConfirmedMapping, mapping_id)


async def list_projects(session: AsyncSession) -> list[CanonicalProject]:
    """Every seeded/onboarded project, eager-loaded for scoring.

    M1 scores every known project against every search (small seeded set).
    At real scale this needs a cheap pre-filter (e.g. Postgres trigram
    similarity) before per-candidate scoring -- flagged here, not solved,
    since it isn't a real problem until the project count is large.
    """
    stmt = select(CanonicalProject).options(selectinload(CanonicalProject.developer))
    return list((await session.execute(stmt)).scalars().all())


async def get_project_by_id(session: AsyncSession, project_id: uuid.UUID) -> CanonicalProject | None:
    stmt = (
        select(CanonicalProject)
        .where(CanonicalProject.id == project_id)
        .options(selectinload(CanonicalProject.developer))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_project_by_rera_number(
    session: AsyncSession, rera_registration_number: str
) -> CanonicalProject | None:
    stmt = (
        select(CanonicalProject)
        .where(CanonicalProject.rera_registration_number == rera_registration_number)
        .options(selectinload(CanonicalProject.developer))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_or_create_developer(session: AsyncSession, name: str) -> Developer:
    normalized = name.strip()
    stmt = select(Developer).where(Developer.name == normalized)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing
    developer = Developer(name=normalized)
    session.add(developer)
    await session.flush()
    return developer


async def create_project(session: AsyncSession, project: CanonicalProject) -> CanonicalProject:
    session.add(project)
    await session.flush()
    await session.refresh(project, attribute_names=["developer"])
    return project


async def get_historical_hit_counts(session: AsyncSession) -> dict[uuid.UUID, int]:
    stmt = select(ConfirmedMapping.canonical_project_id, func.sum(ConfirmedMapping.hit_count)).group_by(
        ConfirmedMapping.canonical_project_id
    )
    return {project_id: int(total) for project_id, total in (await session.execute(stmt)).all()}


async def create_search_query(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    raw_text: str,
    normalized_text: str,
    city_hint: str | None,
) -> SearchQuery:
    query = SearchQuery(
        user_id=user_id, raw_text=raw_text, normalized_text=normalized_text, city_hint=city_hint
    )
    session.add(query)
    await session.flush()
    return query


async def get_search_query_by_id(session: AsyncSession, search_query_id: uuid.UUID) -> SearchQuery | None:
    return await session.get(SearchQuery, search_query_id)


async def bulk_create_candidate_matches(
    session: AsyncSession, rows: list[CandidateMatch]
) -> list[CandidateMatch]:
    session.add_all(rows)
    await session.flush()
    return rows


async def get_candidate_matches_for_query(
    session: AsyncSession, search_query_id: uuid.UUID
) -> list[CandidateMatch]:
    stmt = select(CandidateMatch).where(CandidateMatch.search_query_id == search_query_id)
    return list((await session.execute(stmt)).scalars().all())


async def mark_candidate_chosen(session: AsyncSession, candidate_match: CandidateMatch) -> None:
    candidate_match.chosen = True
    await session.flush()


async def upsert_confirmed_mapping(
    session: AsyncSession,
    *,
    normalized_text: str,
    city_hint: str | None,
    canonical_project_id: uuid.UUID,
    confidence: float,
    confirmed_by: uuid.UUID,
) -> ConfirmedMapping:
    existing = await get_confirmed_mapping(session, normalized_text, city_hint)
    now = datetime.now(UTC)
    if existing is not None:
        existing.canonical_project_id = canonical_project_id
        existing.confidence_at_confirmation = confidence
        existing.confirmed_by = confirmed_by
        existing.confirmed_at = now
        existing.hit_count += 1
        existing.last_used_at = now
        await session.flush()
        return existing

    mapping = ConfirmedMapping(
        normalized_search_string=normalized_text,
        city_hint=city_hint,
        canonical_project_id=canonical_project_id,
        confidence_at_confirmation=confidence,
        confirmed_by=confirmed_by,
        hit_count=1,
    )
    session.add(mapping)
    await session.flush()
    return mapping


async def touch_confirmed_mapping(session: AsyncSession, mapping: ConfirmedMapping) -> ConfirmedMapping:
    mapping.hit_count += 1
    mapping.last_used_at = datetime.now(UTC)
    await session.flush()
    return mapping
