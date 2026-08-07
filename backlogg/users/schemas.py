from pydantic import BaseModel, ConfigDict, Field


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

    model_config = ConfigDict(from_attributes=True)


class UserMeOut(BaseModel):
    """Own profile — includes email, unlike the public UserOut."""

    username: str
    email: str
    display_name: str | None
    bio: str | None
    avatar_url: str | None

    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
