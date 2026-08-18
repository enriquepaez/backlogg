from datetime import datetime
from typing import Literal

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
    event_type: Literal["rating_created", "status_completed"]
    author: FeedAuthorOut
    item: FeedItemOut
    score: float | None
    review_text: str | None
    like_count: int | None
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
                        "event_type": "rating_created",
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
                    },
                    {
                        "id": 513,
                        "event_type": "status_completed",
                        "author": {
                            "username": "alice",
                            "display_name": "Alice",
                            "avatar_url": "https://cdn.example.com/a/alice.png",
                        },
                        "item": {
                            "item_type": "GAME",
                            "title": "Hades",
                            "slug": "hades",
                            "poster_url": "https://images.igdb.com/hades.jpg",
                        },
                        "score": None,
                        "review_text": None,
                        "like_count": None,
                        "created_at": "2026-05-25T20:11:00Z",
                    },
                ],
                "total": 34,
                "page": 1,
                "limit": 20,
            }
        }
    )
