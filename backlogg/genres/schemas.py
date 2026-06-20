from enum import StrEnum

from pydantic import BaseModel


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
