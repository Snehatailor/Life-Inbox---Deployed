"""Remember whether a person chose a task's priority (so it is never auto-raised).

Revision ID: 0018_priority_source
Revises: 0017_task_domain
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018_priority_source"
down_revision: Optional[str] = "0017_task_domain"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("priority_source", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("priority_source")
