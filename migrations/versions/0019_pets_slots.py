"""Pets, the coin shop, and saved time slots on tasks.

Revision ID: 0019_pets_slots
Revises: 0018_priority_source
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019_pets_slots"
down_revision: Optional[str] = "0018_priority_source"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("slot_start", sa.Text(), nullable=True))
        batch.add_column(sa.Column("slot_end", sa.Text(), nullable=True))

    op.create_table(
        "shop_purchases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("owner_user_id", "item_id", name="uq_shop_owner_item"),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "pet_settings",
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("active_pet", sa.Text(), nullable=False, server_default="cat"),
        sa.Column("pet_name", sa.Text(), nullable=True),
        sa.Column("in_page", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("pet_settings")
    op.drop_table("shop_purchases")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("slot_end")
        batch.drop_column("slot_start")
