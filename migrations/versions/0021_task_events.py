"""Remember task snoozes, reopens and completions (for the Procrastination Radar).

Revision ID: 0021_task_events
Revises: 0020_slot_set_at
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021_task_events"
down_revision: Optional[str] = "0020_slot_set_at"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "task_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_task_events_owner_task", "task_events", ["owner_user_id", "task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_events_owner_task", table_name="task_events")
    op.drop_table("task_events")
