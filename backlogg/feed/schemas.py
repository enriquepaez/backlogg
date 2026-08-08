from datetime import datetime

from pydantic import BaseModel, ConfigDict


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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": 512,
                        "author": {
                            "username": "alice",
                            "display_name": "Alice",
                            "avatar_url": "https://cdn.example.com/a/alice.png",
                        },
                        "item": {
                            "item_type": "MOVIE",
                            "title": "Dune",
                            "slug": "dune-2021",
                            "poster_url": "https://image.tmdb.org/t/p/w500/dune.jpg",
                        },
                        "score": 5,
                        "review_text": "A stunning adaptation.",
                        "like_count": 12,
                        "created_at": "2026-05-25T18:04:11Z",
                    }
                ],
                "total": 34,
                "page": 1,
                "limit": 20,
            }
        }
    )
