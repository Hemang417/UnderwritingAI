from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.identity import service
from app.identity.dependencies import get_current_user, require_permission
from app.identity.models import User
from app.identity.schemas import LoginRequest, TokenResponse, UserOut, UserRegisterRequest

auth_router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(tags=["users"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])


@auth_router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: UserRegisterRequest, session: AsyncSession = Depends(get_session)) -> User:
    try:
        user = await service.register_user(
            session, email=body.email, full_name=body.full_name, password=body.password
        )
    except service.EmailAlreadyRegisteredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from exc

    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        roles=service.user_role_names(user),
    )


@auth_router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    try:
        return await service.authenticate(session, email=body.email, password=body.password)
    except service.InvalidCredentialsError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password") from exc


@users_router.get("/me", response_model=UserOut)
async def read_current_user(user: User = Depends(get_current_user)) -> User:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        roles=service.user_role_names(user),
    )


@admin_router.get("/ping")
async def admin_ping(user: User = Depends(require_permission("user.manage"))) -> dict:
    """Proves permission-gated access: only roles granted user.manage reach this."""
    return {"message": "pong", "acknowledged_by": user.email}
