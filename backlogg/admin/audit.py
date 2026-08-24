"""Common helper to record a row in the admin action audit log (feature 63).

Every route that performs a high-privilege admin/moderation action calls
``record_admin_action`` right before its own ``db.commit()``, so the audit
row lands in the *same* transaction as the state change it describes — a
rolled-back action never leaves a trail, and a committed one always does.

Call sites today:
- ``backlogg.moderation.service.set_review_hidden`` — hide/unhide review.
- ``backlogg.moderation.service.set_user_banned`` — ban/unban user.
- ``backlogg.reports.service.resolve_report`` — resolve report.
- ``backlogg.admin.service.set_user_admin_role`` — grant/revoke-admin.

``actor_id`` is the caller's user id when the route has a Bearer-authenticated
identity (grant/revoke-admin only, see ``backlogg.admin.roles``); every other
audited route is gated solely by the shared X-API-Key secret, with no caller
identity to record, so ``actor_id`` is ``None`` there.

Never pass secret material (the X-API-Key value, access/refresh tokens, etc.)
as ``target_id`` or through any other field here — this table is a durable,
queryable log, not a place for anything sensitive.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.admin import repository as admin_repo

ACTION_HIDE_REVIEW = "hide_review"
ACTION_UNHIDE_REVIEW = "unhide_review"
ACTION_BAN_USER = "ban_user"
ACTION_UNBAN_USER = "unban_user"
ACTION_RESOLVE_REPORT = "resolve_report"
ACTION_GRANT_ADMIN = "grant_admin"
ACTION_REVOKE_ADMIN = "revoke_admin"

TARGET_REVIEW = "review"
TARGET_USER = "user"
TARGET_REPORT = "report"


async def record_admin_action(
    db: AsyncSession, *, actor_id: int | None, action: str, target_type: str, target_id: int
) -> None:
    """Add one ``admin_actions`` row to the current session.

    Does not commit — the caller commits together with the state change this
    action describes (see the module docstring for why that matters).
    """
    await admin_repo.insert_admin_action(
        db, actor_id=actor_id, action=action, target_type=target_type, target_id=target_id
    )
