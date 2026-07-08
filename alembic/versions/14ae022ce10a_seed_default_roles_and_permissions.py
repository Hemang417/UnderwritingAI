"""seed default roles and permissions

Revision ID: 14ae022ce10a
Revises: a881941d133f
Create Date: 2026-07-07 23:33:29.746834

"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "14ae022ce10a"
down_revision: Union[str, None] = "a881941d133f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Table/column defs are declared locally (not imported from app.identity.models)
# so this migration keeps producing the same result regardless of how the ORM
# models evolve later -- migrations describe history, not the current model.
roles_table = sa.table("roles", sa.column("id", sa.UUID), sa.column("name", sa.String), sa.column("description", sa.String))
permissions_table = sa.table(
    "permissions", sa.column("id", sa.UUID), sa.column("name", sa.String), sa.column("description", sa.String)
)
role_permissions_table = sa.table(
    "role_permissions", sa.column("role_id", sa.UUID), sa.column("permission_id", sa.UUID)
)

ROLES = {
    "analyst": "Creates and edits reports, triggers data acquisition, submits for review.",
    "reviewer": "Approves or rejects reports before they reach the Investment Committee.",
    "admin": "Configures adapters, ranking weights, scenario assumptions, and manages users.",
}

PERMISSIONS = {
    "report.create": "Create a new report draft for a resolved project.",
    "report.edit_draft": "Edit report content while in Draft status.",
    "report.submit_review": "Submit a Draft report for Reviewer approval.",
    "report.approve_publish": "Approve an in-review report, publishing it immutably.",
    "report.reject": "Send an in-review report back to Draft with comments.",
    "datapoint.manual_override": "Manually correct a data point, preserving audit history.",
    "adapter.configure": "Configure data source adapters (activation, priority, legal sign-off).",
    "user.manage": "Manage users and role assignments.",
    "assumption.configure": "Configure ranking weights, scenario assumptions, and staleness thresholds.",
}

ROLE_PERMISSIONS = {
    "analyst": ["report.create", "report.edit_draft", "report.submit_review", "datapoint.manual_override"],
    "reviewer": ["report.approve_publish", "report.reject"],
    "admin": ["user.manage", "adapter.configure", "assumption.configure"],
}


def upgrade() -> None:
    role_ids = {name: uuid.uuid4() for name in ROLES}
    permission_ids = {name: uuid.uuid4() for name in PERMISSIONS}

    op.bulk_insert(
        roles_table,
        [{"id": role_ids[name], "name": name, "description": desc} for name, desc in ROLES.items()],
    )
    op.bulk_insert(
        permissions_table,
        [
            {"id": permission_ids[name], "name": name, "description": desc}
            for name, desc in PERMISSIONS.items()
        ],
    )
    op.bulk_insert(
        role_permissions_table,
        [
            {"role_id": role_ids[role_name], "permission_id": permission_ids[perm_name]}
            for role_name, perm_names in ROLE_PERMISSIONS.items()
            for perm_name in perm_names
        ],
    )


def downgrade() -> None:
    op.execute(role_permissions_table.delete())
    op.execute(permissions_table.delete())
    op.execute(roles_table.delete())
