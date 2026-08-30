"""Shared Open Library Solr fragments for the book seeding query (feature 73).

The nightly seed used to ask Open Library for ``q=*:*&sort=readinglog``, i.e.
"whatever most users shelved". That signal is dominated by loose serialized
comic instalments, video-game tie-ins and half-empty records — *Batman and
Robin Vol. 1*, *Ultimate Spider-Man Vol. 6*, *Encyclopaedia Eorzea Volume III*,
*Ferno the Fire Dragon (Beast Quest #1)* — which is the noise feature 73
removes.

What it must **not** remove is a whole class of books: essays, non-fiction and
self-help (*Atomic Habits*, *Sapiens*) are legitimate catalog for a reading
backlog app, and so are graphic novels with an identity of their own
(*Watchmen*, *Maus*, *Persepolis*, *Heartstopper*). The discriminant is
therefore **notoriety, not classification**: ``edition_count`` separates the
loose instalment (0-3 editions) from the canonical work (11-66) where no
DDC/LCC clause can, because a comics-only signature is not queryable in Solr
at all (measured; see ``docs/external-apis.md``).

Two levers build the query, and they live in two different places:

- **Language codes** (this module): structural, not tunable. The ``eng``/
  ``spa`` MARC codes are what makes the two seed streams disjoint; they are
  not numbers an operator retunes, so they are constants.
- **Thresholds** (``backlogg.core.config.Settings``): ``BOOKS_SEED_MIN_*`` and
  ``BOOKS_SEED_ES_EVERY_N`` are numbers an operator may legitimately want to
  retune per environment, so they are env vars.

This module is the single source of truth for the language fragments. Its only
call site is the seed query builder:
- ``backlogg/books/adapters/open_library.py`` (``build_seed_query``, consumed
  by ``_fetch_popular_page`` / ``get_popular_books``)

Deliberately **not** applied to ``search_book``: the on-demand fallback and
the search fan-out resolve a user-typed title, and filtering them by notoriety
would make legitimate lookups (a recent essay, a niche graphic novel) return
nothing.

Solr syntax rules the seed query must respect (each one measured live against
``https://openlibrary.org/search.json``; breaking them yields 0 results or
silently ignores the filter):

- ``AND``/``OR``/``NOT`` in UPPERCASE — lowercase ``and``/``or`` returns 0.
- Range bounds unquoted — ``readinglog_count:"[20 TO *]"`` is parsed as text
  and the filter is ignored.
- Parentheses around every ``OR`` — without them precedence breaks.
- ``lcc`` does not support prefix wildcards at all: values are normalized to
  ``XX-NNNN.NNNNNNNN`` and the hyphen breaks the parse, so ``lcc:PN-67*``
  returns 0 and, escaped, a *longer* prefix returns *more* documents. This is
  why no classification clause survives in the seed query.
"""

# MARC language codes used by Open Library's ``language`` field.
BOOK_LANGUAGE_EN = "eng"
BOOK_LANGUAGE_ES = "spa"
