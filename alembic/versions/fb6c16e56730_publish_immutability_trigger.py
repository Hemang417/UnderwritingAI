"""publish immutability trigger

Revision ID: fb6c16e56730
Revises: f16487e5b1d3
Create Date: 2026-07-15 00:49:26.662534

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "fb6c16e56730"
down_revision: Union[str, None] = "f16487e5b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ADR-010: DB-level publish immutability, zero exceptions. Made
    # workable without ever needing to update a published row (e.g. to mark
    # it "superseded") by using ReportVersion.supersedes_version_id as a
    # forward pointer set once on the *new* row instead -- see the model
    # docstring. Any UPDATE whatsoever against a row whose OLD status was
    # already 'PUBLISHED' is unconditionally rejected. Split into its own
    # migration because the WHEN clause below uses the 'PUBLISHED' enum
    # value added in the prior migration, and Postgres forbids using a new
    # enum value within the same transaction that added it.
    op.execute(
        """
        CREATE FUNCTION prevent_published_report_version_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'report_versions row % is published and immutable', OLD.id;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_report_versions_immutable
        BEFORE UPDATE ON report_versions
        FOR EACH ROW
        WHEN (OLD.status = 'PUBLISHED')
        EXECUTE FUNCTION prevent_published_report_version_update()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_report_versions_immutable ON report_versions")
    op.execute("DROP FUNCTION IF EXISTS prevent_published_report_version_update()")
