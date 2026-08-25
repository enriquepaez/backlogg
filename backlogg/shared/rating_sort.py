"""Shared rating sort-key helper (feature 66 — rating_display_internal_only).

Used wherever a list of items must be ordered by rating outside of a SQL
``ORDER BY`` clause — e.g. "similar items" results whose relative order
comes from an external API (IGDB ``similar_games``, TMDB recommendations)
rather than a local query. Mirrors the SQL pattern used across catalog
listings: ``rating_internal DESC NULLS LAST`` decides the order the user
sees; ``rating_external DESC NULLS LAST`` is only an internal tie-break for
items that don't have a community rating yet (or are tied), never surfaced
as "the reason" for the order.
"""


def rating_desc_sort_key(
    rating_internal: float | None, rating_external: float | None
) -> tuple[int, float, int, float]:
    """Sort key for descending ``rating_internal``, ``rating_external`` tie-break.

    ``None`` sorts last for both fields (SQL ``NULLS LAST`` equivalent).
    Use with ``sorted(items, key=lambda i: rating_desc_sort_key(...))`` —
    the key already encodes descending order via negation, so the default
    ascending sort produces the desired highest-first order. Python's sort
    is stable, so items with equal keys (e.g. both ratings ``None``) keep
    their original relative order.
    """
    return (
        0 if rating_internal is not None else 1,
        -rating_internal if rating_internal is not None else 0.0,
        0 if rating_external is not None else 1,
        -rating_external if rating_external is not None else 0.0,
    )
