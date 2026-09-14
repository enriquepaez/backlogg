"""Pydantic v2 schemas for the recommendations domain (read-only).

No SQLAlchemy models here — recommendations are computed on the fly from a
user's ratings/library seeds and never persisted as a new entity. The
adaptations half (feature 92) is read straight off ``item_relations``, which
feature 79 populated; it is not persisted as a new entity either.
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class RecommendationTypeFilter(StrEnum):
    """Optional ``?type=`` filter for GET /recommendations."""

    movie = "movie"
    series = "series"
    book = "book"
    game = "game"


# ``?type=`` filter value -> stored polymorphic item_type.
TYPE_FILTER_TO_ITEM_TYPE: dict[str, str] = {
    "movie": "MOVIE",
    "series": "SERIES",
    "book": "BOOK",
    "game": "GAME",
}


class RecommendationOut(BaseModel):
    item_type: str
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None
    rating_internal: float | None
    reason: str


class RecommendationsOut(BaseModel):
    results: list[RecommendationOut]
    page: int
    limit: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "results": [
                    {
                        "item_type": "MOVIE",
                        "title": "Blade Runner 2049",
                        "slug": "blade-runner-2049",
                        "poster_url": "https://image.tmdb.org/t/p/w500/br2049.jpg",
                        "release_date": "2017-10-06",
                        "rating_external": 8.0,
                        "rating_internal": 4.5,
                        "reason": "Because you rated Dune",
                    }
                ],
                "page": 1,
                "limit": 20,
            }
        }
    )


class AdaptationDirection(StrEnum):
    """Which end of the relation the **related** item sits on.

    The value is read from the point of view of the item in the URL, because
    that is the page the caller is on:

    ``SOURCE``
        the item in the URL is *based on* the related one — "this film comes
        from this novel".
    ``DERIVED``
        the related item *comes out of* the item in the URL — "this novel got
        adapted into this series".

    Two values and not four: ``item_relations`` stores ``ADAPTATION``
    (``P144``) and ``DERIVATIVE`` (``P4969``), which Wikidata declares to be
    inverses of each other, so the raw ``relation`` says nothing on its own
    until it is combined with *which side the anchor is on*. Leaking that pair
    to the client would hand it the same join to redo — and the whole point of
    the feature is that the direction arrives resolved in the data (feature 92
    acceptance), not implied by the order or by the reader's arithmetic.
    """

    SOURCE = "SOURCE"
    DERIVED = "DERIVED"


class AdaptationOut(BaseModel):
    """One adaptation of the item in the URL, as declared by Wikidata.

    ``item_type`` is **not** optional and cannot be inferred from the page the
    caller is on: the related item may be **any of the four types, including
    the same one as the item in the URL**. ``P144`` ("based on") asserts a
    derivation, not a change of medium, so a remake or a spin-off series of
    another series is a legitimate edge — and today it is the *majority* of
    what the endpoint serves (16 of the 18 edges in the development catalog are
    ``SERIES``→``SERIES``). The response does not filter those out; see
    ``docs/api.md`` § Movies.

    That is what makes the field load-bearing rather than redundant: the page
    where a client would be most tempted to assume the type is exactly the page
    where the assumption is most often right *and* silently wrong the rest of
    the time. Issues #32, #33 and #36 were all the same failure — an
    ``item_type`` guessed instead of carried, producing a link that 404s in
    silence — so it travels next to the slug it belongs to.
    """

    item_type: str
    slug: str
    title: str
    poster_url: str | None
    direction: AdaptationDirection


class AdaptationsOut(BaseModel):
    results: list[AdaptationOut]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "results": [
                    {
                        "item_type": "BOOK",
                        "slug": "dune-1965",
                        "title": "Dune",
                        "poster_url": "https://covers.openlibrary.org/b/id/1.jpg",
                        "direction": "SOURCE",
                    },
                    {
                        "item_type": "GAME",
                        "slug": "dune-1992",
                        "title": "Dune",
                        "poster_url": None,
                        "direction": "DERIVED",
                    },
                    {
                        # Same type as the item in the URL — a remake. Not a
                        # filtered-out case: this is what most of the catalog's
                        # edges look like today.
                        "item_type": "MOVIE",
                        "slug": "dune-1984",
                        "title": "Dune",
                        "poster_url": None,
                        "direction": "SOURCE",
                    },
                ]
            }
        }
    )
