"""Add an optional password hash to users for email + password sign-in.

Revision ID: 0013_user_password_hash
Revises: 0012_topics_per_owner_unique
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_user_password_hash"
down_revision: Optional[str] = "0012_topics_per_owner_unique"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "password_hash" not in columns:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("password_hash", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("password_hash")
