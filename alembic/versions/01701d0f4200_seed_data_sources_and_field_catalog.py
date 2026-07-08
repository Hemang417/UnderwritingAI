"""seed data sources and field catalog

Revision ID: 01701d0f4200
Revises: b762954c8571
Create Date: 2026-07-08 22:46:15.276992

"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "01701d0f4200"
down_revision: Union[str, None] = "b762954c8571"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Native Postgres enum types created by the prior migration -- asyncpg
# requires the insert values be cast to these types explicitly rather than
# treated as plain varchar, hence referencing them here instead of sa.String.
source_type_enum = postgresql.ENUM(name="source_type", create_type=False)
value_type_enum = postgresql.ENUM(name="data_point_value_type", create_type=False)

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
    "field_catalog",
    sa.column("field_name", sa.String),
    sa.column("value_type", value_type_enum),
    sa.column("unit", sa.String),
    sa.column("source_priority", sa.JSON),
    sa.column("staleness_threshold_days", sa.Integer),
)

# legal_review_signed_off=True here reflects sign-off on using *synthetic
# fixture data* standing in for these sources (no live scraping occurs --
# see ARD). Swapping either adapter to a real network client is a separate,
# explicit step that requires an actual legal review before this flag (or
# the adapter_key) changes.
# base_confidence: a government filing is trusted more than a developer's
# own marketing site by default.
DATA_SOURCES = [
    ("MahaRERA", "RERA", "maha_rera", "Maharashtra", 95.0),
    ("Developer Website", "DEVELOPER_SITE", "developer_site", None, 80.0),
]

FIELD_CATALOG = [
    ("unit_count", "NUMERIC", None, ["rera", "developer_site"], 180),
    ("possession_date", "DATE", None, ["rera", "developer_site"], 365),
    ("current_price_per_sqft", "NUMERIC", "INR/sqft", ["developer_site", "rera"], 30),
]


def upgrade() -> None:
    op.bulk_insert(
        data_sources_table,
        [
            {
                "id": uuid.uuid4(),
                "name": name,
                "source_type": source_type,
                "adapter_key": adapter_key,
                "jurisdiction": jurisdiction,
                "base_confidence": base_confidence,
                "is_active": True,
                "legal_review_signed_off": True,
            }
            for name, source_type, adapter_key, jurisdiction, base_confidence in DATA_SOURCES
        ],
    )
    op.bulk_insert(
        field_catalog_table,
        [
            {
                "field_name": field_name,
                "value_type": value_type,
                "unit": unit,
                "source_priority": source_priority,
                "staleness_threshold_days": staleness_days,
            }
            for field_name, value_type, unit, source_priority, staleness_days in FIELD_CATALOG
        ],
    )


def downgrade() -> None:
    op.execute(field_catalog_table.delete())
    op.execute(data_sources_table.delete())
