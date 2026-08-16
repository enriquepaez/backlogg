from pydantic import BaseModel, ConfigDict, Field

from backlogg.library.schemas import LibraryCounts


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)


class UserLogin(BaseModel):
    username: str
    password: str


class UserUpdate(BaseModel):
    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None


class UserOut(BaseModel):
    """Public profile — no email, no password_hash."""

    username: str
    display_name: str | None
    bio: str | None
    avatar_url: str | None
    follower_count: int
    following_count: int
    library_counts: LibraryCounts

    model_config = ConfigDict(from_attributes=True)


class UserMeOut(BaseModel):
    """Own profile — includes email, unlike the public UserOut."""

    username: str
    email: str
    display_name: str | None
    bio: str | None
    avatar_url: str | None
    email_verified: bool = False
    is_admin: bool = False
    is_superadmin: bool = False

    model_config = ConfigDict(from_attributes=True)


class TokenPairOut(BaseModel):
    """Access token (short-lived JWT) + rotating refresh token (opaque)."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


# ── Account recovery (email verification + password reset) ─────────────────────


class MessageOut(BaseModel):
    """Generic acknowledgement response for recovery endpoints."""

    detail: str


class VerifyConfirmRequest(BaseModel):
    token: str


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=255)
