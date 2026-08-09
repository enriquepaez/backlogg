from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backlogg.core.database import Base

# Purposes for one-time account-recovery tokens (``account_tokens.purpose``).
# Stored as a plain string + CHECK constraint, matching how the project models
# other enum-like columns (library_entries.status, games.game_type).
TOKEN_PURPOSE_EMAIL_VERIFY = "email_verify"
TOKEN_PURPOSE_PASSWORD_RESET = "password_reset"
TOKEN_PURPOSES = (TOKEN_PURPOSE_EMAIL_VERIFY, TOKEN_PURPOSE_PASSWORD_RESET)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Per-user moderation flag. A banned user cannot log in or refresh, and all
    # of their reviews become invisible on the same surfaces as a hidden review.
    is_banned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RefreshToken(Base):
    """A persisted, rotating refresh token.

    Only the sha256 hash of the opaque token is stored — the plaintext value
    is returned to the client exactly once (in the HTTP response) and never
    persisted or logged. Rotation revokes the used token and issues a new one;
    presenting an already-revoked token is treated as reuse.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AccountToken(Base):
    """A single-use, expiring token for email verification and password reset.

    The token itself is an opaque random value (``secrets.token_urlsafe``, not a
    JWT); only its **sha256 hash** is stored — the plaintext is embedded in the
    email link exactly once and never persisted or logged. Consumption stamps
    ``consumed_at`` so a token can only ever be used a single time; expired or
    already-consumed tokens are rejected.
    """

    __tablename__ = "account_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "purpose IN ('email_verify', 'password_reset')",
            name="ck_account_tokens_purpose",
        ),
        Index("idx_account_tokens_user_id", "user_id"),
    )
