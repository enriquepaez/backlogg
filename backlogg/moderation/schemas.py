from pydantic import BaseModel


class ReviewModerationOut(BaseModel):
    """Result of a hide/unhide action on a review (a ``user_ratings`` row)."""

    id: int
    is_hidden: bool


class UserModerationOut(BaseModel):
    """Result of a ban/unban action on a user."""

    username: str
    is_banned: bool
