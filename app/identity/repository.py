import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.identity.models import (
    AuthIdentity,
    AuthProvider,
    Permission,
    Role,
    User,
    UserRole,
    role_permissions,
)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    stmt = (
        select(User)
        .where(User.email == email)
        .options(
            selectinload(User.auth_identities),
            selectinload(User.user_roles).selectinload(UserRole.role),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    stmt = (
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.user_roles).selectinload(UserRole.role))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_local_identity(session: AsyncSession, user: User) -> AuthIdentity | None:
    for identity in user.auth_identities:
        if identity.provider == AuthProvider.LOCAL:
            return identity
    return None


async def get_role_by_name(session: AsyncSession, name: str) -> Role | None:
    stmt = select(Role).where(Role.name == name)
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_user_with_local_credential(
    session: AsyncSession,
    *,
    email: str,
    full_name: str,
    password_hash: str,
    default_role_name: str = "analyst",
) -> User:
    user = User(email=email, full_name=full_name)
    session.add(user)
    await session.flush()  # populate user.id before dependent inserts

    session.add(AuthIdentity(user_id=user.id, provider=AuthProvider.LOCAL, password_hash=password_hash))

    role = await get_role_by_name(session, default_role_name)
    if role is not None:
        session.add(UserRole(user_id=user.id, role_id=role.id))

    await session.commit()
    return await get_user_by_id(session, user.id)


async def get_permission_names_for_user(session: AsyncSession, user: User) -> set[str]:
    role_ids = [ur.role_id for ur in user.user_roles]
    if not role_ids:
        return set()

    stmt = (
        select(Permission.name)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id.in_(role_ids))
    )
    return set((await session.execute(stmt)).scalars().all())
