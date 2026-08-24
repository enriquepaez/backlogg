"""admin_actions — persisted audit log for high-privilege admin actions

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Feature 63 (admin_action_audit_log). actor_id is nullable — most of the
    # audited routes are gated solely by X-API-Key (no caller identity);
    # ON DELETE SET NULL (not CASCADE) so the audit trail survives the actor's
    # account being deleted later. action/target_type are enum-like plain
    # strings constrained by a CHECK, same modelling as
    # review_reports.status / activity_events.event_type.
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "action IN ('hide_review', 'unhide_review', 'ban_user', 'unban_user', "
            "'resolve_report', 'grant_admin', 'revoke_admin')",
            name="ck_admin_actions_action",
        ),
        sa.CheckConstraint(
            "target_type IN ('review', 'user', 'report')",
            name="ck_admin_actions_target_type",
        ),
    )
    op.create_index("idx_admin_actions_created_at", "admin_actions", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_admin_actions_created_at", table_name="admin_actions")
    op.drop_table("admin_actions")
