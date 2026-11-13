"""Per-user settings: AI provider and Google Calendar connection.

Secrets (API key, OAuth tokens) are stored encrypted by the app.

Revision ID: 0014_user_settings
Revises: 0013_user_password_hash
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_user_settings"
down_revision: Optional[str] = "0013_user_password_hash"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "user_settings" in inspector.get_table_names():
        return
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
    op.drop_table("user_settings")
