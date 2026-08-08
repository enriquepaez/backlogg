"""account_recovery — users.email_verified + account_tokens (one-time tokens)

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-08

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── users.email_verified ──────────────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    # ── account_tokens ────────────────────────────────────────────
    # Single-use, expiring tokens for email verification and password reset.
    # Only the sha256 hash of the opaque token is stored — never the plaintext.
    # ``purpose`` is a plain string constrained by a CHECK, matching how the
    # project models other enum-like columns (no PostgreSQL ENUM type).
    op.create_table(
        "account_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_account_tokens_token_hash"),
        sa.CheckConstraint(
            "purpose IN ('email_verify', 'password_reset')",
            name="ck_account_tokens_purpose",
        ),
    )
    op.create_index("idx_account_tokens_user_id", "account_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_account_tokens_user_id", table_name="account_tokens")
    op.drop_table("account_tokens")
    op.drop_column("users", "email_verified")
