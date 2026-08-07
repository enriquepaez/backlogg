from pydantic import BaseModel, ConfigDict


class FollowUserOut(BaseModel):
    """Public shape of a user inside a followers/following list."""

    username: str
    display_name: str | None
    avatar_url: str | None

    model_config = ConfigDict(from_attributes=True)


class FollowListOut(BaseModel):
    items: list[FollowUserOut]
    total: int
    page: int
    limit: int
