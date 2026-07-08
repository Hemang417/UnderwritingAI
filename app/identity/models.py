import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class AuthProvider(enum.StrEnum):
    LOCAL = "local"
    AZURE_AD = "azure_ad"
    GOOGLE = "google"


# Plain many-to-many join, no extra columns needed -- unlike UserRole below,
# which reserves scope_type/scope_id for future multi-office authority.
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", PGUUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", PGUUID(as_uuid=True), ForeignKey("permissions.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    auth_identities: Mapped[list["AuthIdentity"]] = relationship(back_populates="user")
    user_roles: Mapped[list["UserRole"]] = relationship(back_populates="user")


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permissions, back_populates="roles"
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    roles: Mapped[list["Role"]] = relationship(secondary=role_permissions, back_populates="permissions")


class UserRole(Base):
    """User<->Role membership.

    A real mapped class (not a plain join table) because it carries a
    reserved, currently-unused scope_type/scope_id pair: "multiple offices"
    is a named scale driver for this platform, so office-scoped authority is
    a plausible near-term need and cheaper to reserve now than to migrate in
    later.
    """

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", "scope_type", "scope_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    role_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("roles.id"))
    scope_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="user_roles")
    role: Mapped["Role"] = relationship()


class AuthIdentity(Base):
    """Supports local and SSO identities simultaneously for the same User.

    provider='local' rows carry a password_hash; SSO providers instead carry
    an external_subject_id from the IdP. RBAC/audit are keyed off User.id,
    never off which identity a user authenticated with.
    """

    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "external_subject_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    provider: Mapped[AuthProvider] = mapped_column(Enum(AuthProvider, name="auth_provider"))
    external_subject_id: Mapped[str | None] = mapped_column(String(320), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="auth_identities")


class AuditLogEntry(Base):
    """Append-only. Never updated or deleted by application code."""

    __tablename__ = "audit_log_entries"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(100))
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
