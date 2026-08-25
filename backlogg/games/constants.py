"""Shared game-category constants (IGDB ``category``/local ``game_type``).

IGDB returns 14 "game" categories in its raw ``game_type`` field. Only a
subset of those represents catalog-worthy content — the rest (bundles, mods,
ports, forks, packs, updates, "expanded" re-releases) pollutes rankings with
non-games outranking actual games (Issue #14: a DLC outranked an 8.6-rated
game). Feature 65 (``game_category_allowlist``, product decision
2026-08-25) restricts every ingestion path to the 8 categories below.

This is the single source of truth for that allowlist — every IGDB
ingestion path (seed/nightly sync, on-demand fallback by slug, similar-games,
and the search fan-out) filters through the constants defined here instead
of repeating the category list. See:
- ``backlogg/games/adapters/igdb.py`` (``get_top_games``'s IGDB query filter)
- ``backlogg/games/service.py`` (``get_game``, ``get_similar_games``)
- ``backlogg/search/service.py`` (``_ingest_games``)
"""

# IGDB's numeric ``category`` field (requested as ``game_type`` in this
# codebase's IGDB queries) -> the descriptive string persisted locally on
# ``games.game_type``.
GAME_TYPE_MAP: dict[int, str] = {
    0: "MAIN_GAME",
    1: "DLC_ADDON",
    2: "EXPANSION",
    3: "BUNDLE",
    4: "STANDALONE_EXPANSION",
    5: "MOD",
    6: "EPISODE",
    7: "SEASON",
    8: "REMAKE",
    9: "REMASTER",
    10: "EXPANDED_GAME",
    11: "PORT",
    12: "FORK",
    13: "PACK",
    14: "UPDATE",
}

# Categories allowed for ingestion. Excluded: BUNDLE(3), MOD(5),
# EXPANDED_GAME(10), PORT(11), FORK(12), PACK(13), UPDATE(14).
ALLOWED_GAME_CATEGORY_IDS: frozenset[int] = frozenset({0, 1, 2, 4, 6, 7, 8, 9})

# Same allowlist expressed as the local ``game_type`` string, for call sites
# that only have the already-mapped string (post ``game_to_dict``) at hand.
ALLOWED_GAME_TYPES: frozenset[str] = frozenset(
    GAME_TYPE_MAP[category_id] for category_id in ALLOWED_GAME_CATEGORY_IDS
)
