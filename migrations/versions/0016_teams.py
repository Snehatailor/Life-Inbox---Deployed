"""Teams with an invite code and an opt-in weekly leaderboard.

Revision ID: 0016_teams
Revises: 0015_busy_blocks
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_teams"
down_revision: Optional[str] = "0015_busy_blocks"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("invite_code", sa.Text(), nullable=False, unique=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "team_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "team_id",
            sa.Integer(),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("share_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("joined_at", sa.Text(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_team_members_team", "team_members", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_team_members_team", table_name="team_members")
    op.drop_table("team_members")
    op.drop_table("teams")
