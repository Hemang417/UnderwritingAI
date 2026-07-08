"""seed discovery fixtures and default ranking config

Revision ID: 6cd1d4e6aaaf
Revises: 1a634df3f7be
Create Date: 2026-07-08 22:07:31.853288

"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6cd1d4e6aaaf"
down_revision: Union[str, None] = "1a634df3f7be"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

developers_table = sa.table("developers", sa.column("id", sa.UUID), sa.column("name", sa.String))
projects_table = sa.table(
    "canonical_projects",
    sa.column("id", sa.UUID),
    sa.column("developer_id", sa.UUID),
    sa.column("state", sa.String),
    sa.column("rera_registration_number", sa.String),
    sa.column("project_name", sa.String),
    sa.column("locality", sa.String),
    sa.column("city", sa.String),
    sa.column("status", sa.String),
)
ranking_configs_table = sa.table(
    "ranking_configs",
    sa.column("id", sa.UUID),
    sa.column("version", sa.Integer),
    sa.column("weights", sa.JSON),
    sa.column("auto_proceed_threshold", sa.Float),
    sa.column("show_threshold", sa.Float),
    sa.column("separation_margin", sa.Float),
    sa.column("is_active", sa.Boolean),
)

# Deliberately includes near-duplicate names ("Green Valley Residency" vs
# "Green Valley Heights", two different developers/states/cities) so M1's
# ambiguity/confirmation flow has a real case to exercise, not just clean
# exact matches.
DEVELOPERS = ["Lodha Group", "Godrej Properties", "Prestige Group", "Sobha Ltd", "Oberoi Realty"]

PROJECTS = [
    ("Lodha Group", "Maharashtra", "P51900001234", "Lodha Park", "Worli", "Mumbai", "under_construction"),
    ("Lodha Group", "Maharashtra", "P51900004444", "Lodha Bellissimo", "Mahalaxmi", "Mumbai", "completed"),
    ("Godrej Properties", "Maharashtra", "P52100005678", "Godrej Park Avenue", "Baner", "Pune", "under_construction"),
    ("Prestige Group", "Karnataka", "PRM/KA/RERA/1251/2020", "Green Valley Residency", "Whitefield", "Bengaluru", "under_construction"),
    ("Sobha Ltd", "Maharashtra", "P52100009999", "Green Valley Heights", "Hinjewadi", "Pune", "nearing_completion"),
    ("Oberoi Realty", "Maharashtra", "P51800004321", "Oberoi Springs", "Andheri", "Mumbai", "completed"),
]


def upgrade() -> None:
    developer_ids = {name: uuid.uuid4() for name in DEVELOPERS}

    op.bulk_insert(
        developers_table,
        [{"id": developer_ids[name], "name": name} for name in DEVELOPERS],
    )
    op.bulk_insert(
        projects_table,
        [
            {
                "id": uuid.uuid4(),
                "developer_id": developer_ids[developer_name],
                "state": state,
                "rera_registration_number": rera,
                "project_name": project_name,
                "locality": locality,
                "city": city,
                "status": status,
            }
            for developer_name, state, rera, project_name, locality, city, status in PROJECTS
        ],
    )
    op.bulk_insert(
        ranking_configs_table,
        [
            {
                "id": uuid.uuid4(),
                "version": 1,
                "weights": {
                    "exact_name": 20,
                    "fuzzy_name": 45,
                    "city": 30,
                    "historical_selection": 5,
                },
                "auto_proceed_threshold": 90,
                "show_threshold": 40,
                "separation_margin": 15,
                "is_active": True,
            }
        ],
    )


def downgrade() -> None:
    op.execute(ranking_configs_table.delete())
    op.execute(projects_table.delete())
    op.execute(developers_table.delete())
