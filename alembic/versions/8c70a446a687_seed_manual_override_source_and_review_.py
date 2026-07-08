"""seed manual override source and review permission

Revision ID: 8c70a446a687
Revises: 77efabe20895
Create Date: 2026-07-08 23:40:12.616763

"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

source_type_enum = postgresql.ENUM(name="source_type", create_type=False)

# revision identifiers, used by Alembic.
revision: str = "8c70a446a687"
down_revision: Union[str, None] = "77efabe20895"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

data_sources_table = sa.table(
    "data_sources",
    sa.column("id", sa.UUID),
    sa.column("name", sa.String),
    sa.column("source_type", source_type_enum),
    sa.column("adapter_key", sa.String),
    sa.column("jurisdiction", sa.String),
    sa.column("base_confidence", sa.Float),
    sa.column("is_active", sa.Boolean),
    sa.column("legal_review_signed_off", sa.Boolean),
)
field_catalog_table = sa.table(
    "field_catalog", sa.column("field_name", sa.String), sa.column("requires_override_review", sa.Boolean)
)
roles_table = sa.table("roles", sa.column("id", sa.UUID), sa.column("name", sa.String))
permissions_table = sa.table(
    "permissions", sa.column("id", sa.UUID), sa.column("name", sa.String), sa.column("description", sa.String)
)
role_permissions_table = sa.table(
    "role_permissions", sa.column("role_id", sa.UUID), sa.column("permission_id", sa.UUID)
)

# RERA-registered facts require a Reviewer's recorded sign-off when
# manually overridden; a soft market figure (pricing) doesn't.
CRITICAL_FIELDS = ["unit_count", "possession_date"]


def upgrade() -> None:
    bind = op.get_bind()

    manual_override_source_id = uuid.uuid4()
    op.bulk_insert(
        data_sources_table,
        [
            {
                "id": manual_override_source_id,
                "name": "Manual Override",
                "source_type": "MANUAL_OVERRIDE",
                "adapter_key": "manual_override",
                "jurisdiction": None,
                "base_confidence": 100.0,
                "is_active": True,
                "legal_review_signed_off": True,
            }
        ],
    )

    for field_name in CRITICAL_FIELDS:
        bind.execute(
            field_catalog_table.update()
            .where(field_catalog_table.c.field_name == field_name)
            .values(requires_override_review=True)
        )

    reviewer_role_id = bind.execute(
        sa.select(roles_table.c.id).where(roles_table.c.name == "reviewer")
    ).scalar_one()

    permission_id = uuid.uuid4()
    op.bulk_insert(
        permissions_table,
        [
            {
                "id": permission_id,
                "name": "datapoint.review_override",
                "description": "Record sign-off on a manual data override for a critical field.",
            }
        ],
    )
    op.bulk_insert(
        role_permissions_table, [{"role_id": reviewer_role_id, "permission_id": permission_id}]
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        role_permissions_table.delete().where(
            role_permissions_table.c.permission_id.in_(
                sa.select(permissions_table.c.id).where(
                    permissions_table.c.name == "datapoint.review_override"
                )
            )
        )
    )
    bind.execute(permissions_table.delete().where(permissions_table.c.name == "datapoint.review_override"))
    bind.execute(
        field_catalog_table.update()
        .where(field_catalog_table.c.field_name.in_(CRITICAL_FIELDS))
        .values(requires_override_review=False)
    )
    bind.execute(data_sources_table.delete().where(data_sources_table.c.adapter_key == "manual_override"))
