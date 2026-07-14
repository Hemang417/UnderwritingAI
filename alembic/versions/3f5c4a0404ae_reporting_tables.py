"""reporting tables

Revision ID: 3f5c4a0404ae
Revises: 13c3519f0466
Create Date: 2026-07-14 23:51:52.322624

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3f5c4a0404ae"
down_revision: Union[str, None] = "13c3519f0466"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # reports.current_version_id -> report_versions.id is circular with
    # report_versions.report_id -> reports.id, so the FK is added via
    # create_foreign_key once both tables exist, not inline here.
    op.create_table(
        "reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("canonical_project_id", sa.UUID(), nullable=False),
        sa.Column("current_version_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["canonical_project_id"], ["canonical_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_project_id"),
    )
    op.create_table(
        "report_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("GENERATING", "DRAFT", "FAILED", name="report_version_status"),
            nullable=False,
        ),
        sa.Column("generated_json", sa.JSON(), nullable=True),
        sa.Column("llm_provider", sa.String(length=50), nullable=False),
        sa.Column(
            "guardrail_status", sa.Enum("PASSED", "FAILED", name="guardrail_status"), nullable=True
        ),
        sa.Column("completeness_issues", sa.JSON(), nullable=False),
        sa.Column("completeness_overridden", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "report_sections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("report_version_id", sa.UUID(), nullable=False),
        sa.Column("section_name", sa.String(length=100), nullable=False),
        sa.Column("template_version", sa.String(length=20), nullable=False),
        sa.Column("generated_text", sa.Text(), nullable=False),
        sa.Column(
            "guardrail_status", sa.Enum("PASSED", "FAILED", name="guardrail_status", create_type=False),
            nullable=False,
        ),
        sa.Column("guardrail_report", sa.JSON(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["report_version_id"], ["report_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_foreign_key(
        "fk_reports_current_version_id", "reports", "report_versions", ["current_version_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_reports_current_version_id", "reports", type_="foreignkey")
    op.drop_table("report_sections")
    op.drop_table("report_versions")
    op.drop_table("reports")
    op.execute("DROP TYPE IF EXISTS report_version_status")
    op.execute("DROP TYPE IF EXISTS guardrail_status")
