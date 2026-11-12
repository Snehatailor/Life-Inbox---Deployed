"""Remember when a task's time slot was saved (so a reminder set minutes ahead isn't pre-announced).

Revision ID: 0020_slot_set_at
Revises: 0019_pets_slots
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020_slot_set_at"
down_revision: Optional[str] = "0019_pets_slots"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("slot_set_at", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("slot_set_at")
