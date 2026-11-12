"""Remember which rows "Load demo data" created, so they can be removed exactly.

Revision ID: 0023_demo_data_marker
Revises: 0022_reconcile_merged_branches
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0023_demo_data_marker"
down_revision: Optional[str] = "0022_reconcile_merged_branches"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("user_settings")}
    if "demo_data_json" not in columns:
        with op.batch_alter_table("user_settings") as batch:
            batch.add_column(sa.Column("demo_data_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_column("demo_data_json")
