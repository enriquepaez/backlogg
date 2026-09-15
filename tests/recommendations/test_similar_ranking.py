"""Feature 80 — the ranker, as rules rather than as end-to-end behaviour.

``backlogg/recommendations/ranking.py`` is pure on purpose and it is tested
here the same way: no database, no vectors, no catalog.  The reason is not
speed.  A cross-type quota asserted only through the HTTP endpoint passes or
fails depending on which neighbours the development catalog happens to hold
that week, so it would prove the fixture rather than the rule — and the rule is
what feature 80 calls non-negotiable.

What earns a test here:

- the **quota** actually reserves slots, is bounded by what exists, and is
  **off at zero** — which is the value this feature merges with, so "0 behaves
  exactly like no quota at all" is the property that keeps ``main``
  deployable;
- the quota changes **who** is on the page and never the **order** of the page;
- **diversification** demotes a repeated saga or author and never *drops* it,
  because a list that is genuinely all one franchise must still come back full;
- ``franchise_key`` says ``None`` far more often than it says a key.  The
  catalog has no franchise column, so the signal is a heuristic over titles,
  and inventing a saga demotes a good unrelated result — a worse error than
  missing one.
"""

from datetime import date

from backlogg.recommendations.ranking import (
    Candidate,
    apply_cross_type_quota,
    diversify,
    franchise_key,
    group_keys,
    rank_similar,
)


def _candidate(
    item_type: str,
    item_id: int,
    score: float,
    *,
    title: str | None = None,
    creator_ids: frozenset[int] = frozenset(),
) -> Candidate:
    return Candidate(
        item_type=item_type,
        item_id=item_id,
        title=title if title is not None else f"{item_type.title()} {item_id}",
        slug=f"{item_type.lower()}-{item_id}",
        poster_url=None,
        release_date=date(2000, 1, 1),
        rating_external=None,
        rating_internal=None,
        score=score,
        creator_ids=creator_ids,
    )


# ── franchise_key: conservative by design ─────────────────────────────────────


def test_franchise_key_groups_a_subtitled_saga():
    assert franchise_key("The Lord of the Rings: The Return of the King") == "lord of the rings"
    assert franchise_key("The Lord of the Rings: The Fellowship of the Ring") == (
        "lord of the rings"
    )


def test_franchise_key_groups_numbered_sequels_arabic_and_roman():
    assert franchise_key("Mass Effect 2") == "mass effect"
    assert franchise_key("Rocky IV") == "rocky"
    assert franchise_key("The Witcher 3") == franchise_key("The Witcher: Wild Hunt") == "witcher"


def test_franchise_key_is_none_for_a_standalone_title():
    """The default answer. Anything else would group unrelated items."""
    for title in ("Arrival", "Blade Runner", "Spirited Away", ""):
        assert franchise_key(title) is None, title


def test_franchise_key_refuses_a_residue_too_short_to_mean_anything():
    """ "IT: Chapter Two" must not put every two-letter title in one saga."""
    assert franchise_key("IT: Chapter Two") is None


def test_group_keys_namespaces_creators_apart_from_franchises():
    """A person id and a franchise string can never collide."""
    candidate = _candidate("MOVIE", 1, 0.9, title="Saga: One", creator_ids=frozenset({7}))
    assert group_keys(candidate) == {("creator", 7), ("franchise", "saga")}


# ── Cross-type quota ──────────────────────────────────────────────────────────


def _mixed_pool() -> list[Candidate]:
    """Twelve films ahead of three books — the shape cosine actually returns."""
    movies = [_candidate("MOVIE", i, 0.99 - i * 0.01) for i in range(12)]
    books = [_candidate("BOOK", 100 + i, 0.50 - i * 0.01) for i in range(3)]
    return movies + books


def test_quota_zero_is_plain_truncation():
    """The value feature 80 merges with: the same path, nothing reserved.

    This is the assertion that says ``main`` stays deployable — at 0 the
    endpoint cannot hand the web app a book to link as ``/movies/{slug}``.
    """
    ranked = _mixed_pool()
    selected = apply_cross_type_quota("MOVIE", ranked, limit=10, quota=0)
    assert [c.item_type for c in selected] == ["MOVIE"] * 10
    assert selected == ranked[:10]


def test_quota_reserves_slots_for_other_types():
    ranked = _mixed_pool()
    selected = apply_cross_type_quota("MOVIE", ranked, limit=10, quota=3)
    assert len(selected) == 10
    assert sum(1 for c in selected if c.item_type != "MOVIE") == 3
    # The three best of the other types, not any three.
    assert [c.item_id for c in selected if c.item_type == "BOOK"] == [100, 101, 102]


def test_quota_does_not_reorder_the_page():
    """Promotion decides who is on the page, never where they read.

    A cross-type item pinned to the top would be the ranker overruling its own
    scores; it appears exactly where its score puts it.
    """
    ranked = _mixed_pool()
    selected = apply_cross_type_quota("MOVIE", ranked, limit=10, quota=3)
    positions = [ranked.index(c) for c in selected]
    assert positions == sorted(positions)
    assert [c.item_type for c in selected] == ["MOVIE"] * 7 + ["BOOK"] * 3


def test_quota_is_bounded_by_what_exists():
    """Two embedded books cannot be made into three."""
    ranked = [_candidate("MOVIE", i, 0.9 - i * 0.01) for i in range(12)]
    ranked += [_candidate("BOOK", 100, 0.5), _candidate("BOOK", 101, 0.4)]
    selected = apply_cross_type_quota("MOVIE", ranked, limit=10, quota=3)
    assert len(selected) == 10
    assert sum(1 for c in selected if c.item_type == "BOOK") == 2


def test_quota_larger_than_the_page_saturates_instead_of_failing():
    """A misconfigured quota fills the page with other types; it never raises."""
    ranked = [_candidate("MOVIE", i, 0.9) for i in range(10)]
    ranked += [_candidate("BOOK", 100 + i, 0.5) for i in range(10)]
    selected = apply_cross_type_quota("MOVIE", ranked, limit=5, quota=50)
    assert len(selected) == 5
    assert all(c.item_type == "BOOK" for c in selected)


# ── Diversification ───────────────────────────────────────────────────────────


def _saga_pool() -> list[Candidate]:
    saga = [
        _candidate("MOVIE", i, 0.99 - i * 0.01, title=f"Saga Aurora: Chapter {i}") for i in range(5)
    ]
    others = [
        _candidate("MOVIE", 50, 0.90, title="Arrival"),
        _candidate("MOVIE", 51, 0.89, title="Stalker"),
    ]
    return saga + others


def test_diversify_demotes_a_repeated_franchise():
    """Ten results from one saga are not ten recommendations."""
    ordered = diversify(_saga_pool(), penalty=0.25)
    titles = [c.title for c in ordered]
    assert titles[0] == "Saga Aurora: Chapter 0"  # the best one keeps its slot
    assert titles[1:3] == ["Arrival", "Stalker"]  # lower cosine, promoted anyway


def test_diversify_with_no_penalty_is_raw_cosine_order():
    """The control: without the penalty the saga sweeps the top, as cosine says."""
    ordered = diversify(_saga_pool(), penalty=0.0)
    assert [c.item_id for c in ordered] == [0, 1, 2, 3, 4, 50, 51]


def test_diversify_demotes_a_repeated_creator():
    """Same author, unrelated titles — the signal that comes from credits."""
    pool = [
        _candidate("BOOK", 1, 0.99, title="Nostromo", creator_ids=frozenset({7})),
        _candidate("BOOK", 2, 0.98, title="Victory", creator_ids=frozenset({7})),
        _candidate("BOOK", 3, 0.80, title="Pale Fire", creator_ids=frozenset({9})),
    ]
    ordered = diversify(pool, penalty=0.25)
    assert [c.item_id for c in ordered] == [1, 3, 2]


def test_diversify_demotes_but_never_drops():
    """A list that really is all one saga still comes back full."""
    pool = [_candidate("GAME", i, 0.9 - i * 0.01, title=f"Saga: Part {i}") for i in range(6)]
    ordered = diversify(pool, penalty=0.5)
    assert sorted(c.item_id for c in ordered) == list(range(6))


# ── Composition ───────────────────────────────────────────────────────────────


def test_rank_similar_diversifies_before_applying_the_quota():
    """The quota picks the best *diverse* neighbour of another type.

    Order matters: if the quota ran first it would reserve slots out of the raw
    cosine order, and a saga's second entry could take the cross-type slot from
    a better, unrelated one.
    """
    pool = [
        _candidate("MOVIE", i, 0.99 - i * 0.01, title=f"Saga Aurora: Chapter {i}")
        for i in range(10)
    ]
    pool += [
        _candidate("BOOK", 100, 0.60, title="Saga Aurora: The Novel"),
        _candidate("BOOK", 101, 0.55, title="An Unrelated Novel"),
    ]
    ranked = rank_similar("MOVIE", pool, limit=10, quota=1, penalty=0.25)
    books = [c for c in ranked if c.item_type == "BOOK"]
    assert len(books) >= 1
    # The unrelated novel beats the saga's own novelisation once the franchise
    # penalty has been applied, even though its raw cosine is lower.
    assert books[0].item_id == 101


def test_rank_similar_on_an_empty_pool_is_empty():
    assert rank_similar("MOVIE", [], limit=10, quota=3, penalty=0.25) == []
