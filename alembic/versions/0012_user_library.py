"""user_library — library_entries (per-user backlog status)

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-08

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── library_entries ───────────────────────────────────────────
    # ``status`` is a plain string constrained by a CHECK, matching how the
    # project models other enum-like columns (no PostgreSQL ENUM type).
    op.create_table(
        "library_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
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
        sa.UniqueConstraint("user_id", "item_type", "item_id", name="uq_library_entry_item"),
        sa.CheckConstraint(
            "status IN ('want', 'in_progress', 'completed', 'dropped')",
            name="ck_library_entries_status",
        ),
    )
    op.create_index("idx_library_entries_item", "library_entries", ["item_type", "item_id"])
    op.create_index("idx_library_entries_user", "library_entries", ["user_id"])

    # ── trigger — reuses trigger_set_updated_at() defined in 0001 ──
    op.execute(
        """
        CREATE TRIGGER set_updated_at_library_entries
        BEFORE UPDATE ON library_entries
        FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_library_entries ON library_entries;")
    op.drop_index("idx_library_entries_user", table_name="library_entries")
    op.drop_index("idx_library_entries_item", table_name="library_entries")
    op.drop_table("library_entries")
