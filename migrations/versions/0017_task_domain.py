"""Add a person-chosen domain to tasks (Sections are domains).

Revision ID: 0017_task_domain
Revises: 0016_teams
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_task_domain"
down_revision: Optional[str] = "0016_teams"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("domain", sa.Text(), nullable=True))
        batch.add_column(sa.Column("domain_source", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("domain_source")
        batch.drop_column("domain")
