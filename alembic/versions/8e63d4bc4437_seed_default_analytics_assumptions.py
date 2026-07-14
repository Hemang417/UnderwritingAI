"""seed default analytics assumptions

Revision ID: 8e63d4bc4437
Revises: acd6d9d84c26
Create Date: 2026-07-14 22:26:43.665154

"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8e63d4bc4437"
down_revision: Union[str, None] = "acd6d9d84c26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

engine_type_enum = postgresql.ENUM(name="engine_type", create_type=False)

assumption_sets_table = sa.table(
    "analytics_assumption_sets",
    sa.column("id", sa.UUID),
    sa.column("engine_type", engine_type_enum),
    sa.column("version", sa.Integer),
    sa.column("parameters", sa.JSON),
    sa.column("is_active", sa.Boolean),
)

# Illustrative MVP defaults, not underwriting-team-calibrated figures --
# every value here is meant to be tuned by inserting a new version, per
# ADR (assumptions are config, never hardcoded in engine code).
HORIZONS_YEARS = [1, 3, 5, 7, 10]

PRICING_PARAMS = {
    "annual_appreciation_rate_pct": 8.0,
    "annual_inflation_rate_pct": 5.5,
    "developer_premium_pct": 0.0,
    "infrastructure_impact_pct": 0.0,
    "horizons_years": HORIZONS_YEARS,
}

SALES_VELOCITY_PARAMS = {
    "monthly_absorption_rate_pct": 2.0,
    "sell_through_threshold_pct": 5.0,
    "horizons_years": HORIZONS_YEARS,
}

FINANCIAL_PARAMS = {
    "discount_rate_pct": 12.0,
    "average_unit_size_sqft": 650.0,
    "horizons_years": HORIZONS_YEARS,
}

RISK_PARAMS = {
    "category_weights": {
        "construction": 0.20,
        "developer": 0.15,
        "market": 0.15,
        "demand": 0.15,
        "execution": 0.10,
        "pricing": 0.15,
        "regulatory": 0.10,
    },
    "default_score_no_data": 50.0,
    "status_risk_scores": {
        "under_construction": 70.0,
        "nearing_completion": 40.0,
        "completed": 10.0,
    },
    "stale_pricing_penalty": 20.0,
    "low_confidence_pricing_threshold": 70.0,
    "low_confidence_pricing_penalty": 15.0,
}

ASSUMPTION_SETS = [
    ("PRICING", PRICING_PARAMS),
    ("SALES_VELOCITY", SALES_VELOCITY_PARAMS),
    ("FINANCIAL", FINANCIAL_PARAMS),
    ("RISK", RISK_PARAMS),
]


def upgrade() -> None:
    op.bulk_insert(
        assumption_sets_table,
        [
            {
                "id": uuid.uuid4(),
                "engine_type": engine_type,
                "version": 1,
                "parameters": parameters,
                "is_active": True,
            }
            for engine_type, parameters in ASSUMPTION_SETS
        ],
    )


def downgrade() -> None:
    op.execute(assumption_sets_table.delete())
