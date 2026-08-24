"""Admin action audit log — persisted trail of high-privilege admin actions.

Feature 63 (admin_action_audit_log). Every route that performs a moderation or
role-management action (hide/unhide review, ban/unban user, resolve report,
grant/revoke-admin) calls ``backlogg.admin.audit.record_admin_action`` in the
same DB transaction as its own state change (see each call site), so the
audit row and the change it describes commit atomically — a rolled-back
action never leaves an audit trail, and a committed one always does.

``actor_id`` is nullable: every one of these routes except grant/revoke-admin
is gated solely by the shared X-API-Key secret (no caller identity), so
``actor_id`` is NULL for them. grant-admin/revoke-admin are the only actions
with a caller identity (a Bearer-authenticated superadmin, see
``backlogg.admin.roles``) — those set it. ``ON DELETE SET NULL`` (rather than
CASCADE) keeps the audit row — never sensitive data, just who/what/when — even
if that admin's account is later deleted.
"""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backlogg.core.database import Base

__all__ = ["AdminAction"]


class AdminAction(Base):
    __tablename__ = "admin_actions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Plain string constrained by a CHECK, no PostgreSQL ENUM type — same
    # modelling as review_reports.status / activity_events.event_type.
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    # Polymorphic target_type + target_id (same pattern as user_ratings.item_type
    # / notifications.target_type), no real FK — target_id points at a
    # user_ratings.id ("review"), users.id ("user") or review_reports.id
    # ("report") row depending on target_type.
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "action IN ('hide_review', 'unhide_review', 'ban_user', 'unban_user', "
            "'resolve_report', 'grant_admin', 'revoke_admin')",
            name="ck_admin_actions_action",
        ),
        CheckConstraint(
            "target_type IN ('review', 'user', 'report')",
            name="ck_admin_actions_target_type",
        ),
        Index("idx_admin_actions_created_at", "created_at"),
    )
