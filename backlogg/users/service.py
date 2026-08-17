import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.config import settings
from backlogg.core.email import EmailSender
from backlogg.follows import repository as follows_repo
from backlogg.library import repository as library_repo
from backlogg.library.schemas import LibraryCounts
from backlogg.ratings import repository as ratings_repo
from backlogg.users import repository as repo
from backlogg.users.adapters.r2_storage import R2StorageAdapter
from backlogg.users.auth import (
    create_access_token,
    generate_opaque_token,
    generate_refresh_token,
    hash_opaque_token,
    hash_refresh_token,
)
from backlogg.users.models import (
    TOKEN_PURPOSE_EMAIL_VERIFY,
    TOKEN_PURPOSE_PASSWORD_RESET,
    AccountToken,
    User,
)
from backlogg.users.schemas import (
    ForgotPasswordRequest,
    LogoutRequest,
    MessageOut,
    RefreshRequest,
    ResetPasswordRequest,
    TokenPairOut,
    UserCreate,
    UserLogin,
    UserMeOut,
    UserOut,
    UserUpdate,
    VerifyConfirmRequest,
)

logger = logging.getLogger(__name__)

_ph = PasswordHasher()

# ── Avatar upload (feature 51) ──────────────────────────────────────────────
#
# Business rules, not operational parameters — kept as constants here rather
# than in core/config.py, matching the acceptance criteria of feature 51.
_MAX_AVATAR_SIZE_BYTES = 5 * 1024 * 1024  # 5MB
_ALLOWED_AVATAR_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

_r2 = R2StorageAdapter()


def hash_password(password: str) -> str:
    """Hash a plaintext password with argon2. Never log or persist the plaintext."""
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored argon2 hash."""
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


async def register_user(db: AsyncSession, payload: UserCreate) -> UserMeOut:
    """Create a new user account. Raises 409 if username/email is already taken."""
    if await repo.get_user_by_username(db, payload.username) is not None:
        raise HTTPException(status_code=409, detail="Username already taken")
    if await repo.get_user_by_email(db, payload.email) is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = await repo.create_user(
        db,
        {
            "username": payload.username,
            "email": payload.email,
            "password_hash": hash_password(payload.password),
            "display_name": payload.display_name,
        },
    )
    await db.commit()
    return UserMeOut.model_validate(user)


async def _issue_refresh_token(db: AsyncSession, user_id: int) -> str:
    """Generate an opaque refresh token, persist only its hash, return the plaintext.

    The plaintext is returned to the caller for the HTTP response only; it is
    never persisted or logged.
    """
    plaintext = generate_refresh_token()
    expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_EXPIRE_DAYS)
    await repo.create_refresh_token(db, user_id, hash_refresh_token(plaintext), expires_at)
    return plaintext


async def login_user(db: AsyncSession, payload: UserLogin) -> TokenPairOut:
    """Validate credentials and issue an access + refresh token pair.

    Raises 401 on any credential mismatch. A banned user is rejected with the
    same generic 401 even when the password is correct — the response never
    reveals that the account exists or that it is banned (no enumeration).
    """
    user = await repo.get_user_by_username(db, payload.username)
    if user is None or not verify_password(payload.password, user.password_hash) or user.is_banned:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    access_token = create_access_token(user.id)
    refresh_token = await _issue_refresh_token(db, user.id)
    await db.commit()
    return TokenPairOut(access_token=access_token, refresh_token=refresh_token)


async def refresh_tokens(db: AsyncSession, payload: RefreshRequest) -> TokenPairOut:
    """Rotate a refresh token: validate, revoke the used one, issue a new pair.

    Raises 401 if the token is unknown, expired, or already revoked. Presenting
    an already-revoked token is treated as reuse: as a defense, every still-active
    refresh token for that user is revoked.
    """
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = await repo.get_refresh_token_by_hash(db, token_hash)
    now = datetime.now(UTC)

    if stored is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if stored.revoked_at is not None:
        # Reuse detected: revoke the whole active set for this user.
        await repo.revoke_all_active_for_user(db, stored.user_id, now)
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if stored.expires_at <= now:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # A banned user cannot refresh: reject with the same generic 401 (the token
    # stays revoked/unrotated) so a ban immediately locks the session out.
    owner = await repo.get_user_by_id(db, stored.user_id)
    if owner is None or owner.is_banned:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Rotate: revoke the presented token and issue a fresh pair.
    await repo.revoke_refresh_token(db, stored, now)
    access_token = create_access_token(stored.user_id)
    refresh_token = await _issue_refresh_token(db, stored.user_id)
    await db.commit()
    return TokenPairOut(access_token=access_token, refresh_token=refresh_token)


async def logout_user(db: AsyncSession, user: User, payload: LogoutRequest) -> None:
    """Revoke the presented refresh token. Idempotent — revoking twice is a no-op.

    Only revokes a token that belongs to the authenticated user; unknown or
    foreign tokens are silently ignored so logout never leaks token existence.
    """
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = await repo.get_refresh_token_by_hash(db, token_hash)
    if stored is not None and stored.user_id == user.id:
        await repo.revoke_refresh_token(db, stored, datetime.now(UTC))
    await db.commit()


def get_current_user_profile(user: User) -> UserMeOut:
    """Convert the authenticated User (loaded by the auth dependency) to UserMeOut."""
    return UserMeOut.model_validate(user)


async def get_user_profile(db: AsyncSession, username: str) -> UserOut:
    """Return the public profile for a username, or raise HTTP 404.

    Includes follower_count/following_count from the follows domain.
    """
    user = await repo.get_user_by_username(db, username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    follower_count = await follows_repo.count_followers(db, user.id)
    following_count = await follows_repo.count_following(db, user.id)
    library_counts = await library_repo.count_by_status(db, user.id)
    return UserOut(
        username=user.username,
        display_name=user.display_name,
        bio=user.bio,
        avatar_url=user.avatar_url,
        follower_count=follower_count,
        following_count=following_count,
        library_counts=LibraryCounts(**library_counts),
    )


async def update_current_user(db: AsyncSession, user: User, payload: UserUpdate) -> UserMeOut:
    """Update the authenticated user's display_name/bio/avatar_url."""
    data = payload.model_dump(exclude_unset=True)
    updated = await repo.update_user(db, user, data)
    await db.commit()
    return UserMeOut.model_validate(updated)


def _require_r2_configured() -> None:
    """Raise a controlled 503 if avatar storage is not fully configured.

    Mirrors the ``ADMIN_API_KEY`` pattern (backlogg/admin/auth.py): a missing
    operational dependency is a service-availability problem, not a client
    error, and the response never includes any credential value.

    An explicit ``R2_ENDPOINT_URL`` (MinIO in dev, Supabase Storage or real R2
    in prod) makes ``R2_ACCOUNT_ID`` unnecessary — the endpoint is used as-is
    instead of being built from it (see
    ``backlogg.users.adapters.r2_storage``). When no endpoint override is set,
    ``R2_ACCOUNT_ID`` is still required to build the real R2 endpoint.
    """
    if not (
        (settings.R2_ENDPOINT_URL or settings.R2_ACCOUNT_ID)
        and settings.R2_ACCESS_KEY_ID
        and settings.R2_SECRET_ACCESS_KEY
        and settings.R2_BUCKET_NAME
        and settings.R2_PUBLIC_BASE_URL
    ):
        raise HTTPException(status_code=503, detail="Avatar storage is not configured.")


def _extract_r2_key(avatar_url: str) -> str | None:
    """Return the R2 object key encoded in ``avatar_url``, or None if it isn't ours.

    ``avatar_url`` can also hold an arbitrary external URL pasted through
    ``PATCH /v1/users/me`` (feature 27) — only URLs under
    ``R2_PUBLIC_BASE_URL`` map to an object this adapter is allowed to delete.
    """
    base = settings.R2_PUBLIC_BASE_URL.rstrip("/")
    if not base:
        return None
    prefix = f"{base}/"
    if avatar_url.startswith(prefix):
        return avatar_url[len(prefix) :]
    return None


async def upload_avatar(db: AsyncSession, user: User, file: UploadFile) -> UserMeOut:
    """Validate, upload to R2 and persist the authenticated user's avatar.

    Overwrites any previous ``avatar_url`` (whether set by a prior upload or
    pasted via ``PATCH /v1/users/me``) with the freshly uploaded object's
    public URL.

    Raises:
        HTTPException 422: ``file.content_type`` is not one of image/jpeg,
            image/png or image/webp.
        HTTPException 413: the file exceeds ``_MAX_AVATAR_SIZE_BYTES`` (5MB).
        HTTPException 503: R2 is not configured (see ``_require_r2_configured``).
    """
    ext = _ALLOWED_AVATAR_CONTENT_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(status_code=422, detail="Unsupported image type")

    # Read at most one byte beyond the limit so an oversized upload never gets
    # buffered fully into memory just to be rejected.
    content = await file.read(_MAX_AVATAR_SIZE_BYTES + 1)
    if len(content) > _MAX_AVATAR_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds the 5MB size limit")

    _require_r2_configured()

    key = f"avatars/{user.id}/{uuid4()}.{ext}"
    public_url = await _r2.upload(key=key, content=content, content_type=file.content_type)

    updated = await repo.update_user(db, user, {"avatar_url": public_url})
    await db.commit()
    return UserMeOut.model_validate(updated)


async def delete_avatar(db: AsyncSession, user: User) -> None:
    """Delete the current avatar (if any) and clear ``avatar_url``.

    Idempotent: a no-op when ``avatar_url`` is already null. Best-effort on
    the storage side — deleting the R2 object is skipped (and logged) rather
    than failing the request when the URL isn't one of ours or R2 is
    unreachable/unconfigured, so the user-facing state (no avatar) is always
    reached.
    """
    if user.avatar_url is None:
        return

    key = _extract_r2_key(user.avatar_url)
    if key is not None:
        try:
            await _r2.delete(key=key)
        except Exception:  # noqa: BLE001 - storage failure must not block the delete
            logger.warning(
                "Failed to delete avatar object from R2 (key=%s); clearing avatar_url anyway",
                key,
            )

    await repo.update_user(db, user, {"avatar_url": None})
    await db.commit()


async def delete_current_user(db: AsyncSession, user: User) -> None:
    """Permanently delete the authenticated user's account (GDPR erasure).

    All rows referencing ``users.id`` (ratings, review_likes, follows, library,
    notifications, refresh/account tokens) are removed by DB-level
    ``ON DELETE CASCADE``. The cascade does not, however, recompute the catalog
    aggregates of items the user had rated, so we first capture those items,
    delete the user (flushing the cascade), and only then recalculate
    ``rating_internal``/``rating_count_internal`` for each — the recompute now
    reads ``user_ratings`` with the user's rows already gone. The final commit
    persists both the deletion and the refreshed aggregates atomically.
    """
    rated_items = await ratings_repo.get_distinct_rated_items_for_user(db, user.id)
    await repo.delete_user(db, user)
    for item_type, item_id in rated_items:
        await ratings_repo.recalculate_item_aggregates(db, item_type, item_id)
    await db.commit()


# ── Account recovery (email verification + password reset) ─────────────────────


async def _issue_account_token(db: AsyncSession, user_id: int, purpose: str, ttl: timedelta) -> str:
    """Generate an opaque single-use token, persist only its hash, return plaintext.

    The plaintext is embedded in the email link for the HTTP flow only; it is
    never persisted or logged.
    """
    plaintext = generate_opaque_token()
    expires_at = datetime.now(UTC) + ttl
    await repo.create_account_token(db, user_id, hash_opaque_token(plaintext), purpose, expires_at)
    return plaintext


async def _consume_valid_token(db: AsyncSession, token_str: str, purpose: str) -> AccountToken:
    """Validate and consume a single-use token, or raise 400.

    A token is valid only if it exists, matches ``purpose``, is not already
    consumed, and has not expired. Consumption stamps ``consumed_at`` so the
    same token can never be reused (a second attempt raises 400).
    """
    stored = await repo.get_account_token_by_hash(db, hash_opaque_token(token_str))
    now = datetime.now(UTC)
    if (
        stored is None
        or stored.purpose != purpose
        or stored.consumed_at is not None
        or stored.expires_at <= now
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    await repo.consume_account_token(db, stored, now)
    return stored


async def _send_email_safe(
    sender: EmailSender, *, to: str, subject: str, html: str, text: str
) -> None:
    """Send an email, swallowing provider failures.

    A mail-server outage must never break the endpoint response nor reveal
    whether an email exists, so any exception is logged (without the recipient
    or any credentials) and the flow continues.
    """
    try:
        await sender.send(to=to, subject=subject, html=html, text=text)
    except Exception:  # noqa: BLE001 - provider failure must never break the flow
        logger.warning("Failed to send account email (subject=%r); continuing", subject)


def _link(path: str, token: str) -> str:
    return f"{settings.APP_BASE_URL.rstrip('/')}/{path}?token={token}"


async def request_email_verification(
    db: AsyncSession, user: User, sender: EmailSender
) -> MessageOut:
    """Issue an email-verification token for the authenticated user and email it."""
    token = await _issue_account_token(
        db,
        user.id,
        TOKEN_PURPOSE_EMAIL_VERIFY,
        timedelta(hours=settings.EMAIL_VERIFY_EXPIRE_HOURS),
    )
    await db.commit()

    link = _link("verify-email", token)
    await _send_email_safe(
        sender,
        to=user.email,
        subject="Verify your Backlogg email",
        html=f'<p>Confirm your email address:</p><p><a href="{link}">{link}</a></p>',
        text=f"Confirm your email address: {link}",
    )
    return MessageOut(detail="Verification email sent")


async def confirm_email_verification(db: AsyncSession, payload: VerifyConfirmRequest) -> MessageOut:
    """Consume a verification token and mark the user's email as verified."""
    token = await _consume_valid_token(db, payload.token, TOKEN_PURPOSE_EMAIL_VERIFY)
    await repo.set_email_verified(db, token.user_id)
    await db.commit()
    return MessageOut(detail="Email verified")


async def request_password_reset(
    db: AsyncSession, payload: ForgotPasswordRequest, sender: EmailSender
) -> MessageOut:
    """Start a password reset. Always returns the same message (no enumeration).

    If the email maps to a user, a reset token is issued and emailed; if it does
    not, nothing happens — but the response is identical so callers cannot probe
    which emails are registered.
    """
    user = await repo.get_user_by_email(db, payload.email)
    if user is not None:
        token = await _issue_account_token(
            db,
            user.id,
            TOKEN_PURPOSE_PASSWORD_RESET,
            timedelta(hours=settings.PASSWORD_RESET_EXPIRE_HOURS),
        )
        await db.commit()

        link = _link("reset-password", token)
        await _send_email_safe(
            sender,
            to=user.email,
            subject="Reset your Backlogg password",
            html=f'<p>Reset your password:</p><p><a href="{link}">{link}</a></p>',
            text=f"Reset your password: {link}",
        )
    return MessageOut(detail="If that email is registered, a reset link has been sent")


async def reset_password(db: AsyncSession, payload: ResetPasswordRequest) -> MessageOut:
    """Consume a reset token, set the new password and revoke active sessions.

    Revoking every still-active refresh token (feature 35) forces re-login on
    all devices after a password reset.
    """
    token = await _consume_valid_token(db, payload.token, TOKEN_PURPOSE_PASSWORD_RESET)
    await repo.set_password_hash(db, token.user_id, hash_password(payload.new_password))
    await repo.revoke_all_active_for_user(db, token.user_id, datetime.now(UTC))
    await db.commit()
    return MessageOut(detail="Password has been reset")
