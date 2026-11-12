"""Add a person-chosen domain to inbox items.

Revision ID: 0014_item_domain
Revises: 0013_task_quest_points
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_item_domain"
down_revision: Optional[str] = "0013_task_quest_points"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    with op.batch_alter_table("inbox_items") as batch:
        batch.add_column(sa.Column("domain", sa.Text(), nullable=True))
        batch.add_column(sa.Column("domain_source", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("inbox_items") as batch:
        batch.drop_column("domain_source")
        batch.drop_column("domain")
