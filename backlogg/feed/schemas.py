from datetime import datetime

from pydantic import BaseModel


class FeedAuthorOut(BaseModel):
    username: str
    display_name: str | None
    avatar_url: str | None


class FeedItemOut(BaseModel):
    item_type: str
    title: str
    slug: str
    poster_url: str | None


class FeedEntryOut(BaseModel):
    id: int
    author: FeedAuthorOut
    item: FeedItemOut
    score: int | None
    review_text: str | None
    like_count: int
    created_at: datetime


class FeedListOut(BaseModel):
    items: list[FeedEntryOut]
    total: int
    page: int
    limit: int
