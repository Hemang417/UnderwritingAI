"""report lifecycle: review, publish, edit overlay, pdf

Revision ID: f16487e5b1d3
Revises: 3f5c4a0404ae
Create Date: 2026-07-15 00:47:28.807303

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f16487e5b1d3"
down_revision: Union[str, None] = "3f5c4a0404ae"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Native enum stores .name (uppercase), not .value -- must match the
    # ReportVersionStatus member names, not their lowercase string values.
    op.execute("ALTER TYPE report_version_status ADD VALUE 'IN_REVIEW'")
    op.execute("ALTER TYPE report_version_status ADD VALUE 'PUBLISHED'")
    op.execute("ALTER TYPE report_version_status ADD VALUE 'SUPERSEDED'")

    op.add_column("report_versions", sa.Column("reviewed_by", sa.UUID(), nullable=True))
    op.add_column("report_versions", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("report_versions", sa.Column("review_comments", sa.Text(), nullable=True))
    op.add_column("report_versions", sa.Column("published_by", sa.UUID(), nullable=True))
    op.add_column("report_versions", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("report_versions", sa.Column("supersedes_version_id", sa.UUID(), nullable=True))
    op.add_column("report_versions", sa.Column("pdf_storage_key", sa.String(length=500), nullable=True))
    op.create_foreign_key(
        "fk_report_versions_reviewed_by", "report_versions", "users", ["reviewed_by"], ["id"]
    )
    op.create_foreign_key(
        "fk_report_versions_published_by", "report_versions", "users", ["published_by"], ["id"]
    )
    op.create_foreign_key(
        "fk_report_versions_supersedes_version_id",
        "report_versions",
        "report_versions",
        ["supersedes_version_id"],
        ["id"],
    )

    op.add_column("report_sections", sa.Column("edited_text", sa.Text(), nullable=True))
    op.add_column("report_sections", sa.Column("edited_by", sa.UUID(), nullable=True))
    op.add_column("report_sections", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "report_sections",
        sa.Column(
            "edited_guardrail_status",
            sa.Enum("PASSED", "FAILED", name="guardrail_status", create_type=False),
            nullable=True,
        ),
    )
    op.add_column("report_sections", sa.Column("edited_guardrail_report", sa.JSON(), nullable=True))
    op.add_column("report_sections", sa.Column("guardrail_acknowledged_by", sa.UUID(), nullable=True))
    op.add_column("report_sections", sa.Column("guardrail_acknowledgment_note", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_report_sections_edited_by", "report_sections", "users", ["edited_by"], ["id"]
    )
    op.create_foreign_key(
        "fk_report_sections_guardrail_acknowledged_by",
        "report_sections",
        "users",
        ["guardrail_acknowledged_by"],
        ["id"],
    )
    # The DB-level publish-immutability trigger (ADR-010) references the
    # 'PUBLISHED' enum value added above in a WHEN clause -- Postgres
    # forbids using a new enum value in the same transaction that added it
    # ("UnsafeNewEnumValueUsageError"), so the trigger is a separate
    # migration that runs after this one commits.


def downgrade() -> None:
    op.drop_constraint("fk_report_sections_guardrail_acknowledged_by", "report_sections", type_="foreignkey")
    op.drop_constraint("fk_report_sections_edited_by", "report_sections", type_="foreignkey")
    op.drop_column("report_sections", "guardrail_acknowledgment_note")
    op.drop_column("report_sections", "guardrail_acknowledged_by")
    op.drop_column("report_sections", "edited_guardrail_report")
    op.drop_column("report_sections", "edited_guardrail_status")
    op.drop_column("report_sections", "edited_at")
    op.drop_column("report_sections", "edited_by")
    op.drop_column("report_sections", "edited_text")

    op.drop_constraint("fk_report_versions_supersedes_version_id", "report_versions", type_="foreignkey")
    op.drop_constraint("fk_report_versions_published_by", "report_versions", type_="foreignkey")
    op.drop_constraint("fk_report_versions_reviewed_by", "report_versions", type_="foreignkey")
    op.drop_column("report_versions", "pdf_storage_key")
    op.drop_column("report_versions", "supersedes_version_id")
    op.drop_column("report_versions", "published_at")
    op.drop_column("report_versions", "published_by")
    op.drop_column("report_versions", "review_comments")
    op.drop_column("report_versions", "reviewed_at")
    op.drop_column("report_versions", "reviewed_by")

    # Postgres has no DROP VALUE for enums -- IN_REVIEW/PUBLISHED/SUPERSEDED
    # remain valid (but now unused) report_version_status values after a
    # downgrade. Documented limitation, not silently worked around.
