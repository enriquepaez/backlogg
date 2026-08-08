from datetime import date

from pydantic import BaseModel, ConfigDict


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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "results": [
                    {
                        "id": 1,
                        "item_type": "MOVIE",
                        "slug": "dune-2021",
                        "title": "Dune",
                        "overview": "Paul Atreides unites with the Fremen of Arrakis.",
                        "poster_url": "https://image.tmdb.org/t/p/w500/dune.jpg",
                        "release_date": "2021-10-22",
                        "rating_external": 7.8,
                    }
                ],
                "total": 42,
                "page": 1,
                "limit": 20,
            }
        }
    )
