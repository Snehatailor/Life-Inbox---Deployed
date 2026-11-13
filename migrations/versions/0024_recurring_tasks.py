"""Recurring tasks: a repeat rule and a link to the next copy.

Revision ID: 0024_recurring_tasks
Revises: 0023_demo_data_marker
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0024_recurring_tasks"
down_revision: Optional[str] = "0023_demo_data_marker"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("tasks")}
    with op.batch_alter_table("tasks") as batch:
        if "repeat_rule" not in columns:
            batch.add_column(sa.Column("repeat_rule", sa.Text(), nullable=True))
        if "next_task_id" not in columns:
            batch.add_column(sa.Column("next_task_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("next_task_id")
        batch.drop_column("repeat_rule")
