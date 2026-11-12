"""Add Task Quest columns and the point_events ledger.

Revision ID: 0013_task_quest_points
Revises: 0012_topics_per_owner_unique
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_task_quest_points"
down_revision: Optional[str] = "0012_topics_per_owner_unique"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("completed_at", sa.Text(), nullable=True))
        batch.add_column(sa.Column("points_awarded", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("binned_at", sa.Text(), nullable=True))

    op.create_table(
        "point_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("day", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_point_events_owner_day", "point_events", ["owner_user_id", "day"])


def downgrade() -> None:
    op.drop_index("ix_point_events_owner_day", table_name="point_events")
    op.drop_table("point_events")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("binned_at")
        batch.drop_column("points_awarded")
        batch.drop_column("completed_at")
