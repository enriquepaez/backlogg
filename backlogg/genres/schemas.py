from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ItemTypeEnum(StrEnum):
    movie = "movie"
    series = "series"
    book = "book"
    game = "game"


class GenreWithCountOut(BaseModel):
    name: str
    slug: str
    item_type: str
    count: int


class GenreListOut(BaseModel):
    genres: list[GenreWithCountOut]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "genres": [
                    {
                        "name": "Science Fiction",
                        "slug": "science-fiction",
                        "item_type": "movie",
                        "count": 128,
                    },
                    {
                        "name": "Adventure",
                        "slug": "adventure",
                        "item_type": "movie",
                        "count": 96,
                    },
                ]
            }
        }
    )
