from datetime import date

from pydantic import BaseModel


class SearchResultItem(BaseModel):
    id: int
    item_type: str
    slug: str
    title: str | None
    overview: str | None
    poster_url: str | None
    release_date: date | None
    rating_external: float | None


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    total: int
    page: int
    limit: int
