from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RatingIn(BaseModel):
    """Request body for PUT /{type}/{slug}/rating — full replace (upsert)."""

    score: int | None = Field(default=None, ge=1, le=5)
    review_text: str | None = Field(default=None, max_length=10000)


class RatingAuthorOut(BaseModel):
    username: str
    display_name: str | None
    avatar_url: str | None

    model_config = ConfigDict(from_attributes=True)


class RatingOut(BaseModel):
    id: int
    user: RatingAuthorOut
    score: int | None
    review_text: str | None
    like_count: int
    created_at: datetime
    updated_at: datetime


class RatingListOut(BaseModel):
    items: list[RatingOut]
    total: int
    page: int
    limit: int


class UserReviewItemOut(BaseModel):
    item_type: str
    title: str
    slug: str
    poster_url: str | None


class UserReviewOut(BaseModel):
    id: int
    item: UserReviewItemOut
    score: int | None
    review_text: str | None
    created_at: datetime
    updated_at: datetime


class UserReviewListOut(BaseModel):
    items: list[UserReviewOut]
    total: int
    page: int
    limit: int
