import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.discovery import service
from app.discovery.models import CanonicalProject
from app.discovery.repository import get_project_by_id
from app.discovery.schemas import (
    CandidateOut,
    ConfirmRequest,
    ConfirmResponse,
    LiveResolveRequest,
    ProjectOut,
    SearchRequest,
    SearchResponse,
)
from app.discovery.scoring import ScoredCandidate
from app.identity.dependencies import get_current_user
from app.identity.models import User

router = APIRouter(tags=["discovery"])


def _project_out(project: CanonicalProject) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        project_name=project.project_name,
        developer=project.developer.name,
        locality=project.locality,
        city=project.city,
        state=project.state,
        rera_registration_number=project.rera_registration_number,
        status=project.status,
    )


def _candidate_out(candidate: ScoredCandidate) -> CandidateOut:
    base = _project_out(candidate.project)
    return CandidateOut(**base.model_dump(), confidence_score=candidate.composite_score)


@router.post("/search", response_model=SearchResponse)
async def search_projects(
    body: SearchRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SearchResponse:
    try:
        outcome = await service.search(
            session,
            user_id=user.id,
            raw_text=body.raw_text,
            city_hint=body.city_hint,
            force_refresh=body.force_refresh,
        )
    except service.RankingConfigMissingError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "No active ranking configuration") from exc

    return SearchResponse(
        status=outcome.status,
        search_query_id=outcome.search_query_id,
        mapping_id=outcome.mapping_id,
        project=_project_out(outcome.project) if outcome.project else None,
        candidates=[_candidate_out(c) for c in outcome.candidates] if outcome.candidates else None,
        auto_confirmed=outcome.auto_confirmed,
    )


@router.post("/search/{search_query_id}/confirm", response_model=ConfirmResponse)
async def confirm_candidate(
    search_query_id: uuid.UUID,
    body: ConfirmRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ConfirmResponse:
    try:
        project, mapping_id = await service.confirm(
            session,
            user_id=user.id,
            search_query_id=search_query_id,
            canonical_project_id=body.canonical_project_id,
        )
    except service.SearchQueryNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Search query not found") from exc
    except service.NotACandidateError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That project was not among this search's candidates"
        ) from exc

    return ConfirmResponse(project=_project_out(project), mapping_id=mapping_id)


@router.post("/search/mappings/{mapping_id}/reuse", response_model=ConfirmResponse)
async def reuse_previous_mapping(
    mapping_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> ConfirmResponse:
    try:
        project, mapping_id = await service.reuse_mapping(session, mapping_id=mapping_id)
    except service.ConfirmedMappingNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Confirmed mapping not found") from exc

    return ConfirmResponse(project=_project_out(project), mapping_id=mapping_id)


@router.post("/search/live-maharera", response_model=ProjectOut)
async def search_live_maharera(
    body: LiveResolveRequest,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> ProjectOut:
    """Looks a project up live on MAHARERA's own public API and creates a
    new CanonicalProject from what's found -- the actual "add a project
    not already in the database" capability. Slow (a live external call)
    and depends on a human-obtained JWT being configured; never triggered
    implicitly by the normal /search endpoint.
    """
    try:
        project = await service.resolve_via_live_maharera(session, project_name=body.project_name)
    except service.LiveResolveInputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except service.LiveResolveNotFoundError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No matching project found on MAHARERA for '{exc}'"
        ) from exc
    except service.LiveResolveSourceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return _project_out(project)


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> ProjectOut:
    project = await get_project_by_id(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return _project_out(project)
