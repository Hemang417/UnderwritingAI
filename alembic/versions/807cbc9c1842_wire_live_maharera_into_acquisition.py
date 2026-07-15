"""wire live maharera into acquisition

Revision ID: 807cbc9c1842
Revises: fb6c16e56730
Create Date: 2026-07-15 14:44:57.533841

"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '807cbc9c1842'
down_revision: Union[str, None] = 'fb6c16e56730'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

source_type_enum = postgresql.ENUM(name="source_type", create_type=False)

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

# legal_review_signed_off=True here is NOT the same sign-off as the
# fixture-backed "maha_rera" row (that one covers synthetic data only, per
# its own migration's comment) -- this is real live scraping. It reflects
# the user's own explicit, informed decision earlier in this project to
# proceed with live MAHARERA access (site has no robots.txt, ToS checked,
# CAPTCHA solved by a human every time -- see app/adapters/maha_rera_live.py
# and app/adapters/maha_rera_session.py). Only ever reached for projects
# that were themselves discovered live (CanonicalProject.maharera_project_id
# is set) -- never for the seeded fixture projects.
LIVE_MAHARERA_SOURCE_ID = uuid.uuid4()


def upgrade() -> None:
    op.add_column(
        "canonical_projects",
        sa.Column("maharera_project_id", sa.String(length=50), nullable=True),
    )
    op.bulk_insert(
        data_sources_table,
        [
            {
                "id": LIVE_MAHARERA_SOURCE_ID,
                "name": "MahaRERA (Live)",
                "source_type": "RERA",
                "adapter_key": "maha_rera_live",
                "jurisdiction": "Maharashtra",
                "base_confidence": 95.0,
                "is_active": True,
                "legal_review_signed_off": True,
            }
        ],
    )


def downgrade() -> None:
    op.execute(data_sources_table.delete().where(data_sources_table.c.adapter_key == "maha_rera_live"))
    op.drop_column("canonical_projects", "maharera_project_id")
