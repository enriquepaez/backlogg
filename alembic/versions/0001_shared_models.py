"""shared_models — external_ids, people, credits

Revision ID: 0001
Revises:
Create Date: 2026-05-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── external_ids ──────────────────────────────────────────────
    op.create_table(
        "external_ids",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        # Superseded by migration 0036, which adds item_type to this key
        # (issue #20). Left as it was: this file records history, not the
        # current shape of the table.
        sa.UniqueConstraint("source", "external_id", name="uq_external_id"),
        sa.UniqueConstraint("item_type", "item_id", "source", name="uq_item_source"),
    )
    op.create_index("idx_external_ids_item", "external_ids", ["item_type", "item_id"])

    # ── people ────────────────────────────────────────────────────
    op.create_table(
        "people",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("profile_url", sa.String(length=1000), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_people_slug"),
    )
    op.create_index(
        "idx_people_name",
        "people",
        [sa.text("to_tsvector('simple', name)")],
        postgresql_using="gin",
    )
    op.create_index("idx_people_last_synced_at", "people", ["last_synced_at"])

    # ── updated_at trigger function ───────────────────────────────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trigger_set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ── trigger for people ────────────────────────────────────────
    op.execute(
        """
        CREATE TRIGGER set_updated_at_people
        BEFORE UPDATE ON people
        FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
        """
    )

    # ── credits ───────────────────────────────────────────────────
    op.create_table(
        "credits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("person_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("character_name", sa.String(length=255), nullable=True),
        sa.Column("billing_order", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_type", "item_id", "person_id", "role", name="uq_credit"),
    )
    op.create_index("idx_credits_person", "credits", ["person_id"])
    op.create_index("idx_credits_item", "credits", ["item_type", "item_id"])
    op.create_index("idx_credits_role", "credits", ["role"])


def downgrade() -> None:
    op.drop_table("credits")
    op.execute("DROP TRIGGER IF EXISTS set_updated_at_people ON people;")
    op.drop_table("people")
    op.execute("DROP FUNCTION IF EXISTS trigger_set_updated_at();")
    op.drop_table("external_ids")
