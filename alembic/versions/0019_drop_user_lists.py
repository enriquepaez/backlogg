"""drop_user_lists — remove user_lists + list_items (curated lists retired)

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Product decision: the curated-lists domain (backlogg/lists/, feature
    # user_lists / 0013_user_lists.py) is retired. list_items references
    # user_lists via FK, so it must be dropped first.
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_user_lists ON user_lists;")
    op.drop_index("idx_list_items_list", table_name="list_items")
    op.drop_table("list_items")
    op.drop_index("idx_user_lists_slug", table_name="user_lists")
    op.drop_index("idx_user_lists_user", table_name="user_lists")
    op.drop_table("user_lists")


def downgrade() -> None:
    # ── user_lists ────────────────────────────────────────────────
    op.create_table(
        "user_lists",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_public",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "slug", name="uq_user_list_slug"),
    )
    op.create_index("idx_user_lists_user", "user_lists", ["user_id"])
    op.create_index("idx_user_lists_slug", "user_lists", ["slug"])

    # ── list_items ────────────────────────────────────────────────
    # Polymorphic item_type + item_id (no real FK to content tables), same
    # pattern as library_entries / user_ratings.
    op.create_table(
        "list_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("list_id", sa.BigInteger(), nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["list_id"], ["user_lists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("list_id", "item_type", "item_id", name="uq_list_item"),
    )
    op.create_index("idx_list_items_list", "list_items", ["list_id"])

    # ── trigger — reuses trigger_set_updated_at() defined in 0001 ──
    op.execute(
        """
        CREATE TRIGGER set_updated_at_user_lists
        BEFORE UPDATE ON user_lists
        FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
        """
    )
