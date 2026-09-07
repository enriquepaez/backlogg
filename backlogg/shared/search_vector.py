"""The one definition of the catalog's full-text vector.

Feature 91.  Cross-type search used to live in the ``catalog_search``
materialized view, which stored the ``tsvector`` of all four content tables in
a fifth copy of the catalog.  That copy weighed 137 MB and — worse — every
ingestion had to run ``REFRESH MATERIALIZED VIEW CONCURRENTLY``, which builds
a *complete second copy* before swapping it in.  With 127 MB free on Neon's
512 MB ceiling, the refresh no longer fit, and that is what blocked the
seeding (issue #28).

Now each of ``movies``, ``series``, ``books`` and ``games`` carries its own
``search_vector`` as a ``GENERATED ALWAYS AS (...) STORED`` column with a GIN
index over it.  A generated column is recomputed by Postgres inside the very
statement that writes the row, transactionally: the refresh does not get
smaller, it **stops existing**, and the window in which a freshly ingested
item was not yet searchable closes with it.

Why this expression is legal in a generated column
--------------------------------------------------

Postgres only accepts ``IMMUTABLE`` expressions there.  All three functions
used below qualify: ``to_tsvector(regconfig, text)`` — the **two-argument**
form, the one-argument form is ``STABLE`` because it reads
``default_text_search_config`` — plus ``regexp_replace`` and ``COALESCE``.

Why the title is indexed twice
------------------------------

Once verbatim and once with all punctuation stripped (spaces preserved as word
separators).  Postgres' ``simple`` dictionary tokenizes ``Spider-Man`` into the
punctuated lexeme and its two halves, but never into ``spiderman``, so a query
typed without punctuation never matched a punctuated title (issue #13,
migration ``0028``).  ``overview`` is deliberately left unnormalized: the
reported bug was about titles.

Why one constant and not four copies
------------------------------------

The expression has to be **identical** on the four tables.  If they drift,
search silently starts behaving differently depending on the content type —
a bug with no error message and no failing test unless someone thinks to
compare types.  The four ORM models and migration ``0038`` all read this
constant, so drift is impossible by construction.

.. warning::

   This constant is **frozen**, in the same sense that ``shared/codes.py`` is
   append-only: migration ``0038`` imports it (the precedent is ``0037``
   importing ``shared/codes.py``), so editing the string here would silently
   rewrite what that already-applied migration means.  Changing the expression
   requires a **new** migration that drops and re-adds the four columns, and
   ``0038`` must be pinned to a frozen copy of the old text at that point.
"""

#: SQL for the ``search_vector`` generated column of ``movies``, ``series``,
#: ``books`` and ``games``.  Column names only — no table qualifier — so the
#: same text is valid in all four ``ALTER TABLE`` statements.
SEARCH_VECTOR_SQL = (
    "to_tsvector('simple', "
    "title || ' ' || regexp_replace(title, '[^a-zA-Z0-9\\s]', '', 'g') || "
    "' ' || COALESCE(overview, ''))"
)

#: Text search configuration used for both indexing and querying.  ``simple``
#: means no stemming and no stopword removal, so ``the`` is a searchable
#: lexeme; the query side (``plainto_tsquery``) must use the same one or
#: nothing would ever match.
SEARCH_TS_CONFIG = "simple"
