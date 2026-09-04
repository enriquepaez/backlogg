"""Slug generation shared by every ingestion path.

Historically the same ``_slugify`` body lived copy-pasted in five modules
(``movies``/``series`` TMDB adapters, the Open Library adapter, the IGDB
adapter and ``admin/service.py``).  Issue #18 had to be fixed in all of them
at once, so they were unified here.

``shared/`` never imports from a domain package (``docs/architecture.md``),
and this module keeps that property: stdlib only.

**Issue #18 — the non-Latin fallback.**  ``slugify`` folds to ASCII, so a
title or a name written entirely in CJK, Cyrillic, Arabic, Greek, Hebrew…
folds to the empty string.  That was not cosmetic:

* people upsert on ``uq_people_slug``, so *every* non-Latin person collapsed
  into a single ``slug = ''`` row, each name overwriting the previous one and
  stealing the other's credits;
* items build ``f"{slug_base}-{year}"``, so every non-Latin title of a given
  year collapsed into ``-2025`` and the upsert-by-slug merged unrelated works.

When the fold comes back empty we therefore derive the slug from the external
id instead (``tmdb-1234567``, ``open-library-ol123w``, ``igdb-4567``): unique
by construction per ``(item_type, source)``, deterministic, stable across
renames and free of any new dependency.  Transliteration was rejected on
purpose — it collapses distinct identities (``张伟`` and ``章伟`` both give
``zhang-wei``), which would turn "lost credit" into "credit silently
attributed to somebody else".  The display name stays in ``people.name`` /
``<item>.title``, untouched and in its original script.
"""

import re
import unicodedata

__all__ = [
    "external_id_slug",
    "slug_with_external_fallback",
    "slugify",
    "titled_slug",
]


def slugify(text: str) -> str:
    """Fold *text* to a lowercase ASCII slug.

    Byte-for-byte the rule the five former ``_slugify`` copies applied, so
    every slug already stored in the catalog keeps coming out identical.
    Returns ``""`` when nothing survives the ASCII fold — callers that have an
    external id at hand should use ``slug_with_external_fallback`` instead.
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


def external_id_slug(source: str, external_id: str | int | None) -> str:
    """Build the identity-based slug for *source* / *external_id*.

    ``("TMDB", 1234567)`` -> ``tmdb-1234567``,
    ``("OPEN_LIBRARY", "OL123W")`` -> ``open-library-ol123w``,
    ``("IGDB", 4567)`` -> ``igdb-4567``.

    Returns ``""`` when either half is missing: a payload with no external id
    carries no identity to fall back to, and the caller's own validation
    (``bulk_load`` drops such credits) must keep seeing an empty slug.
    """
    if not source or external_id is None or external_id == "":
        return ""
    # ``_`` survives ``\w`` in slugify, so normalise it before folding —
    # OPEN_LIBRARY must read ``open-library``, not ``open_library``.
    source_part = slugify(str(source).replace("_", "-"))
    id_part = slugify(str(external_id))
    if not source_part or not id_part:
        return ""
    return f"{source_part}-{id_part}"


def slug_with_external_fallback(text: str, source: str, external_id: str | int | None) -> str:
    """``slugify(text)``, or the external-id slug when the fold is empty.

    The one entry point for every name/title that has an external identity.
    Latin input is unaffected (same slug as before issue #18); input that folds
    to nothing gets a unique, stable slug instead of ``""``.

    Only the **empty** fold triggers the fallback, not the ambiguous one: if
    anything survives, it wins (``宮崎駿 Jr`` -> ``jr``).  Two mixed-script
    names can therefore still collide, exactly like two Latin homonyms do
    (issue #24) — that is a different problem and it is still open.
    """
    return slugify(text) or external_id_slug(source, external_id)


def titled_slug(
    title: str, year: str | int | None, source: str, external_id: str | int | None
) -> str:
    """Slug for a catalog item: ``<title>-<year>``, with the issue #18 fallback.

    When the title folds to something, behaviour is exactly what the adapters
    did before: append ``-{year}`` if there is a year, otherwise just the fold.
    When it folds to nothing the slug is the external-id slug **with no year
    suffix** — the external id is already unique, and pasting the year on top
    would only make the URL longer without adding anything.

    Can still return ``""``, and deliberately does not raise: when the title
    folds to nothing *and* there is no external id there is nothing left to
    build a slug out of.  Inventing one would be worse than saying so — such
    an item cannot be linked in ``external_ids`` either, so it is unpersistable
    by definition.  The two item write frontiers reject it and count it:
    ``bulk_load_items`` (``rejected``) and
    ``scheduler.jobs._write_items_individually`` (``errors``).
    """
    base = slugify(title)
    if not base:
        return external_id_slug(source, external_id)
    return f"{base}-{year}" if year else base
