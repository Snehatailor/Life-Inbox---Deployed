"""Replace global topics.name uniqueness with a per-owner constraint.

Revision ID: 0012_topics_per_owner_unique
Revises: 0011_multi_user_ownership

The original topics table was created with an unnamed UNIQUE(name). Ownership
was added later, but that global unique still rejects a second user's default
topic (for example Work). Uniqueness is now (owner_user_id, name).

SQLite cannot drop an unnamed table UNIQUE by catalog name, so this revision
batch-recreates topics. A naming convention gives the reflected UNIQUE(name)
the name uq_topics_name for the drop. Existing rows stay valid: names were
already globally unique, and 0011 assigned each row an owner.
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_topics_per_owner_unique"
down_revision: Optional[str] = "0011_multi_user_ownership"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None

# Applied only while reflecting the unnamed SQLite UNIQUE(name). The first
# constrained column is "name", so the reflected constraint is uq_topics_name.
_SQLITE_REFLECT_NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
_SQLITE_GLOBAL_NAME_UNIQUE = "uq_topics_name"
_PER_OWNER_UNIQUE = "uq_topics_name_owner"


def _column_set(constraint: dict) -> set[str]:
    return set(constraint.get("column_names") or [])


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    uniques = inspector.get_unique_constraints("topics")
    global_name_uniques = [
        constraint
        for constraint in uniques
        if list(constraint.get("column_names") or []) == ["name"]
    ]
    has_per_owner = any(
        _column_set(constraint) == {"owner_user_id", "name"}
        for constraint in uniques
    )
    if not global_name_uniques and has_per_owner:
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "topics",
            naming_convention=_SQLITE_REFLECT_NAMING,
            table_kwargs={"sqlite_autoincrement": True},
        ) as batch:
            for constraint in global_name_uniques:
                batch.drop_constraint(
                    constraint["name"] or _SQLITE_GLOBAL_NAME_UNIQUE,
                    type_="unique",
                )
            if not has_per_owner:
                batch.create_unique_constraint(
                    _PER_OWNER_UNIQUE,
                    ["owner_user_id", "name"],
                )
        return

    # Postgres names UNIQUE(name) in the catalog (typically topics_name_key).
    # Dropping the constraint also drops its backing index. Do not drop that
    # index again; a cached reflection would still list it and fail the upgrade.
    for constraint in global_name_uniques:
        name = constraint.get("name")
        if not name:
            raise RuntimeError(
                "Refusing to rebuild topics: UNIQUE(name) has no name to drop"
            )
        op.drop_constraint(name, "topics", type_="unique")

    if not has_per_owner:
        op.create_unique_constraint(
            _PER_OWNER_UNIQUE,
            "topics",
            ["owner_user_id", "name"],
        )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade is disabled to avoid collapsing per-owner topic names"
    )
