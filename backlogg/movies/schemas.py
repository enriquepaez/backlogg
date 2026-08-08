from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from backlogg.shared.schemas import CreditOut


class GenreOut(BaseModel):
    id: int
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class SimilarMovieOut(BaseModel):
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None

    model_config = ConfigDict(from_attributes=True)


class SimilarMoviesOut(BaseModel):
    results: list[SimilarMovieOut]


class MovieOut(BaseModel):
    id: int
    title: str
    original_title: str | None
    slug: str
    overview: str | None
    release_date: date | None
    runtime: int | None
    original_language: str | None
    poster_url: str | None
    backdrop_url: str | None
    budget: int | None
    revenue: int | None
    status: str | None
    rating_external: float | None
    rating_count_external: int | None
    rating_internal: float | None
    rating_count_internal: int
    genres: list[GenreOut]
    credits: list[CreditOut] = []
    viewer_status: str | None = None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "title": "Dune",
                "original_title": "Dune",
                "slug": "dune-2021",
                "overview": "Paul Atreides unites with the Fremen of Arrakis.",
                "release_date": "2021-10-22",
                "runtime": 155,
                "original_language": "en",
                "poster_url": "https://image.tmdb.org/t/p/w500/dune.jpg",
                "backdrop_url": "https://image.tmdb.org/t/p/w780/dune-bd.jpg",
                "budget": 165000000,
                "revenue": 401800000,
                "status": "Released",
                "rating_external": 7.8,
                "rating_count_external": 9231,
                "rating_internal": 4.2,
                "rating_count_internal": 87,
                "genres": [{"id": 3, "name": "Science Fiction", "slug": "science-fiction"}],
                "credits": [
                    {
                        "person_name": "Timothée Chalamet",
                        "person_slug": "timothee-chalamet",
                        "profile_url": "https://image.tmdb.org/t/p/w185/tc.jpg",
                        "role": "cast",
                        "character_name": "Paul Atreides",
                        "billing_order": 0,
                    }
                ],
                "viewer_status": "want",
            }
        },
    )


class MovieSortEnum(StrEnum):
    rating_desc = "rating_desc"
    rating_asc = "rating_asc"
    date_desc = "date_desc"
    date_asc = "date_asc"
    title_asc = "title_asc"


class MovieListItemOut(BaseModel):
    id: int
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None
    genres: list[str]

    model_config = ConfigDict(from_attributes=True)


class MovieListOut(BaseModel):
    items: list[MovieListItemOut]
    total: int
    page: int
    limit: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": 1,
                        "title": "Dune",
                        "slug": "dune-2021",
                        "poster_url": "https://image.tmdb.org/t/p/w500/dune.jpg",
                        "release_date": "2021-10-22",
                        "rating_external": 7.8,
                        "genres": ["science-fiction", "adventure"],
                    }
                ],
                "total": 847,
                "page": 1,
                "limit": 20,
            }
        }
    )
