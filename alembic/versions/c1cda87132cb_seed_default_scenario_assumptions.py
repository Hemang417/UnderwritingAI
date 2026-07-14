"""seed default scenario assumptions

Revision ID: c1cda87132cb
Revises: 34af1d1b2126
Create Date: 2026-07-14 23:08:05.414933

"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c1cda87132cb"
down_revision: Union[str, None] = "34af1d1b2126"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

scenario_type_enum = postgresql.ENUM(name="scenario_type", create_type=False)

scenario_assumption_sets_table = sa.table(
    "scenario_assumption_sets",
    sa.column("id", sa.UUID),
    sa.column("scenario_type", scenario_type_enum),
    sa.column("version", sa.Integer),
    sa.column("name", sa.String),
    sa.column("adjustments", sa.JSON),
    sa.column("is_active", sa.Boolean),
)

# Illustrative MVP defaults, not underwriting-team-calibrated figures --
# every value here is meant to be tuned by inserting a new version, per
# ADR (assumptions are config, never hardcoded in engine code). Keys map
# 1:1 to app.scenario.adjusters; an adjuster ignores any key it doesn't
# recognize, so BASE deliberately ships with no deltas at all -- it's the
# identity scenario, reproducing the un-adjusted base forecast.
BEAR_ADJUSTMENTS = {
    "pricing_growth_delta_pct": -4.0,
    "inflation_delta_pct": 1.5,
    "sales_velocity_multiplier": 0.6,
    "interest_rate_delta_pct": 2.5,
    "construction_delay_risk_pts": 20.0,
    "developer_execution_risk_pts": 15.0,
    "demand_risk_pts": 15.0,
    "supply_risk_pts": 10.0,
}

BASE_ADJUSTMENTS: dict = {}

BULL_ADJUSTMENTS = {
    "pricing_growth_delta_pct": 3.0,
    "inflation_delta_pct": -0.5,
    "sales_velocity_multiplier": 1.3,
    "interest_rate_delta_pct": -1.0,
    "construction_delay_risk_pts": -10.0,
    "developer_execution_risk_pts": -10.0,
    "demand_risk_pts": -10.0,
    "supply_risk_pts": -5.0,
}

SCENARIO_ASSUMPTION_SETS = [
    ("BEAR", "Bear Case", BEAR_ADJUSTMENTS),
    ("BASE", "Base Case", BASE_ADJUSTMENTS),
    ("BULL", "Bull Case", BULL_ADJUSTMENTS),
]


def upgrade() -> None:
    op.bulk_insert(
        scenario_assumption_sets_table,
        [
            {
                "id": uuid.uuid4(),
                "scenario_type": scenario_type,
                "version": 1,
                "name": name,
                "adjustments": adjustments,
                "is_active": True,
            }
            for scenario_type, name, adjustments in SCENARIO_ASSUMPTION_SETS
        ],
    )


def downgrade() -> None:
    op.execute(scenario_assumption_sets_table.delete())
