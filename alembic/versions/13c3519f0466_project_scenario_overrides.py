"""project scenario overrides

Revision ID: 13c3519f0466
Revises: c1cda87132cb
Create Date: 2026-07-14 23:28:56.893483

"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "13c3519f0466"
down_revision: Union[str, None] = "c1cda87132cb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

scenario_type_enum = postgresql.ENUM(name="scenario_type", create_type=False)

roles_table = sa.table("roles", sa.column("id", sa.UUID), sa.column("name", sa.String))
permissions_table = sa.table(
    "permissions", sa.column("id", sa.UUID), sa.column("name", sa.String), sa.column("description", sa.String)
)
role_permissions_table = sa.table(
    "role_permissions", sa.column("role_id", sa.UUID), sa.column("permission_id", sa.UUID)
)

NEW_PERMISSIONS = {
    "scenario.override": (
        "analyst",
        "Propose a project-specific deviation from a firm-wide scenario assumption set.",
    ),
    "scenario.review_override": (
        "reviewer",
        "Approve or reject a proposed project-specific scenario override.",
    ),
}


def upgrade() -> None:
    op.create_table(
        "project_scenario_overrides",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("canonical_project_id", sa.UUID(), nullable=False),
        sa.Column("scenario_type", scenario_type_enum, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("adjustments", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("submitted_by", sa.UUID(), nullable=False),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["canonical_project_id"], ["canonical_projects.id"]),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("scenario_results", sa.Column("project_override_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_scenario_results_project_override_id",
        "scenario_results",
        "project_scenario_overrides",
        ["project_override_id"],
        ["id"],
    )

    bind = op.get_bind()
    for permission_name, (role_name, description) in NEW_PERMISSIONS.items():
        role_id = bind.execute(sa.select(roles_table.c.id).where(roles_table.c.name == role_name)).scalar_one()
        permission_id = uuid.uuid4()
        op.bulk_insert(
            permissions_table, [{"id": permission_id, "name": permission_name, "description": description}]
        )
        op.bulk_insert(role_permissions_table, [{"role_id": role_id, "permission_id": permission_id}])


def downgrade() -> None:
    bind = op.get_bind()
    for permission_name in NEW_PERMISSIONS:
        bind.execute(
            role_permissions_table.delete().where(
                role_permissions_table.c.permission_id.in_(
                    sa.select(permissions_table.c.id).where(permissions_table.c.name == permission_name)
                )
            )
        )
        bind.execute(permissions_table.delete().where(permissions_table.c.name == permission_name))

    op.drop_constraint("fk_scenario_results_project_override_id", "scenario_results", type_="foreignkey")
    op.drop_column("scenario_results", "project_override_id")
    op.drop_table("project_scenario_overrides")
