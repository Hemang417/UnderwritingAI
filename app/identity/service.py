from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.identity import repository
from app.identity.models import User
from app.identity.schemas import TokenResponse


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


async def register_user(
    session: AsyncSession, *, email: str, full_name: str, password: str
) -> User:
    existing = await repository.get_user_by_email(session, email)
    if existing is not None:
        raise EmailAlreadyRegisteredError(email)

    return await repository.create_user_with_local_credential(
        session,
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
    )


async def authenticate(session: AsyncSession, *, email: str, password: str) -> TokenResponse:
    user = await repository.get_user_by_email(session, email)
    if user is None or not user.is_active:
        raise InvalidCredentialsError(email)

    identity = await repository.get_local_identity(session, user)
    if identity is None or identity.password_hash is None:
        raise InvalidCredentialsError(email)

    if not verify_password(password, identity.password_hash):
        raise InvalidCredentialsError(email)

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


def user_role_names(user: User) -> list[str]:
    return [ur.role.name for ur in user.user_roles]
