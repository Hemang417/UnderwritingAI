"""scenario assumption sets and results

Revision ID: 34af1d1b2126
Revises: 8e63d4bc4437
Create Date: 2026-07-14 23:07:40.664756

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '34af1d1b2126'
down_revision: Union[str, None] = '8e63d4bc4437'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scenario_assumption_sets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('scenario_type', sa.Enum('BEAR', 'BASE', 'BULL', 'CUSTOM', name='scenario_type'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('adjustments', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'scenario_results',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('canonical_project_id', sa.UUID(), nullable=False),
        sa.Column('scenario_assumption_set_id', sa.UUID(), nullable=False),
        sa.Column('base_forecast_run_ids', sa.JSON(), nullable=False),
        sa.Column('output', sa.JSON(), nullable=True),
        # forecast_run_status already exists (created by the M5 forecast_runs
        # migration) -- create_type=False avoids a duplicate CREATE TYPE here.
        sa.Column(
            'status',
            postgresql.ENUM(
                'SUCCESS', 'FAILED', 'INSUFFICIENT_DATA', name='forecast_run_status', create_type=False
            ),
            nullable=False,
        ),
        sa.Column('error_detail', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['canonical_project_id'], ['canonical_projects.id']),
        sa.ForeignKeyConstraint(['scenario_assumption_set_id'], ['scenario_assumption_sets.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('scenario_results')
    op.drop_table('scenario_assumption_sets')
    op.execute('DROP TYPE IF EXISTS scenario_type')
