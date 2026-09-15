from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class CreditOut(BaseModel):
    person_name: str
    person_slug: str
    profile_url: str | None
    role: str
    character_name: str | None
    billing_order: int | None

    model_config = ConfigDict(from_attributes=True)


class SimilarReasonKind(StrEnum):
    """Why a "more like this" result is in the list — as an *enumerated fact*.

    The four ``/similar`` endpoints answer with a mix of layers (the semantic
    index of feature 75, and the legacy per-type paths it falls back to), and
    the acceptance list of feature 80 asks each result to carry a readable
    reason.  It is carried as **structured data and never as a formed
    sentence**: FE-69 has to render this in Spanish *and* English, and a string
    assembled in the backend is untranslatable on arrival — the frontend would
    have to parse English prose back into meaning, or ship a second copy of the
    rule that produced it.

    Direct precedent, and a recent one: ``AdaptationDirection`` in feature 92,
    which the web app turns into copy with next-intl.  Same shape, same reason.

    ``SEMANTIC`` and ``SEMANTIC_CROSS_TYPE`` are split rather than being one
    kind plus a comparison the client does between two ``item_type`` fields.
    They are two different *claims*: "another film about this" and "there is a
    novel about this too", and the second is the one this product exists to
    make.  Handing over the raw pair would push the decision of which sentence
    to write back onto whoever renders it.
    """

    #: Nearest neighbour in the embedding space, same type as the anchor item.
    SEMANTIC = "SEMANTIC"
    #: Nearest neighbour in the embedding space, **a different type** from the
    #: anchor item: the cross-media bridge — a book next to a film.
    SEMANTIC_CROSS_TYPE = "SEMANTIC_CROSS_TYPE"
    #: Shares an author with the anchor item (books fallback, feature 19/46).
    SHARED_AUTHOR = "SHARED_AUTHOR"
    #: Shares genres with the anchor item (books fallback, second tier).
    SHARED_GENRE = "SHARED_GENRE"
    #: Came from the source's own related-items API (TMDB recommendations,
    #: IGDB ``similar_games``) — the path an item with no vector falls back to.
    EXTERNAL = "EXTERNAL"


class SimilarReason(BaseModel):
    """The structured reason attached to one ``/similar`` result.

    ``score`` is the cosine **similarity** in ``[0, 1]`` and is only present
    for the semantic kinds; the legacy paths have no comparable number and say
    ``null`` instead of inventing one.  ``source`` names the external provider
    for ``EXTERNAL`` (``TMDB`` / ``IGDB``) and is ``null`` everywhere else.
    """

    kind: SimilarReasonKind
    score: float | None = None
    source: str | None = None

    model_config = ConfigDict(from_attributes=True)


class SimilarItemBase(BaseModel):
    """One "more like this" result, shared by the four ``/similar`` endpoints.

    The four per-type schemas (``SimilarMovieOut`` and friends) are now empty
    subclasses of this: they kept their names so every existing consumer and
    the generated ``packages/api-client`` keep compiling, but the fields live
    in one place because the response is genuinely the same response.

    ``item_type`` is the field that makes that legal.  Before feature 80 the
    type of a result was **implicit** — it was whatever the page was about —
    and ``apps/web`` builds each link as ``/{type-of-the-page}/{slug}``.  The
    semantic ranker can return a book among films, so the type has to travel in
    the data or the link is silently wrong: exactly the failure of issues #32,
    #33 and #36.  It is filled in on *every* path, including the legacy ones
    where it is constant, so no consumer has to know which path answered.
    """

    item_type: str
    title: str
    slug: str
    poster_url: str | None
    release_date: date | None
    rating_external: float | None
    rating_internal: float | None
    reason: SimilarReason

    model_config = ConfigDict(from_attributes=True)
