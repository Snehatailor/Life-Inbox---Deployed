"""Reconcile databases created on either branch before they were merged.

The Task Quest branch (0013_task_quest_points ... 0021_task_events) and the
accounts/settings branch (0013_user_password_hash, 0014_user_settings) both
started from 0012. They now run as one chain:

    0012 -> 0013_user_password_hash -> 0014_user_settings
         -> 0013_task_quest_points -> ... -> 0021_task_events -> 0022 (this)

A database that was already at 0021_task_events on the Task Quest branch never
ran the two accounts/settings revisions. This revision adds what they would
have added, only when it is missing, so every database ends up the same.

Revision ID: 0022_reconcile_merged_branches
Revises: 0021_task_events
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0022_reconcile_merged_branches"
down_revision: Optional[str] = "0021_task_events"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "password_hash" not in user_columns:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("password_hash", sa.Text(), nullable=True))

    if "user_settings" not in inspector.get_table_names():
        op.create_table(
            "user_settings",
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("ai_provider", sa.Text(), nullable=True),
            sa.Column("ai_base_url", sa.Text(), nullable=True),
            sa.Column("ai_model", sa.Text(), nullable=True),
            sa.Column("ai_api_key_enc", sa.Text(), nullable=True),
            sa.Column("google_calendar_token_enc", sa.Text(), nullable=True),
            sa.Column("google_calendar_email", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )


def downgrade() -> None:
    # Nothing to undo: the columns belong to 0013/0014 on the merged chain.
    pass
