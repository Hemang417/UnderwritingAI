import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import decode_token
from app.identity import repository
from app.identity.models import User

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not an access token")

    user = await repository.get_user_by_id(session, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")

    return user


def require_permission(permission_name: str):
    """FastAPI dependency factory gating an endpoint on a named permission.

    Per SAD Security Architecture: permission checks happen through this one
    dependency, not scattered `if role == "..."` checks scattered across
    endpoints.
    """

    async def _check(
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> User:
        granted = await repository.get_permission_names_for_user(session, user)
        if permission_name not in granted:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Missing required permission: {permission_name}"
            )
        return user

    return _check
