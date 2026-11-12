"""Imported calendar busy blocks, used to suggest free time slots.

Revision ID: 0015_busy_blocks
Revises: 0014_item_domain
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_busy_blocks"
down_revision: Optional[str] = "0014_item_domain"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    op.create_table(
        "busy_blocks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("starts_at", sa.Text(), nullable=False),
        sa.Column("ends_at", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_busy_blocks_owner_start", "busy_blocks", ["owner_user_id", "starts_at"])


def downgrade() -> None:
    op.drop_index("ix_busy_blocks_owner_start", table_name="busy_blocks")
    op.drop_table("busy_blocks")
