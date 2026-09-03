# Database Schema

PostgreSQL. Migrations managed with Alembic. All timestamps are `TIMESTAMPTZ`.

## Item tables

### `movies`

```sql
CREATE TABLE movies (
    id                      BIGSERIAL PRIMARY KEY,
    title                   VARCHAR(500) NOT NULL,
    original_title          VARCHAR(500),
    slug                    VARCHAR(255) NOT NULL UNIQUE,
    overview                TEXT,
    release_date            DATE,
    runtime                 INTEGER,                  -- minutes
    original_language       VARCHAR(10),              -- ISO 639-1
    poster_url              VARCHAR(1000),
    backdrop_url            VARCHAR(1000),
    budget                  BIGINT,                   -- USD
    revenue                 BIGINT,                   -- USD
    status                  VARCHAR(50),              -- RELEASED, IN_PRODUCTION, ...
    rating_external         NUMERIC(3,1),
    rating_count_external   INTEGER,
    rating_internal         NUMERIC(3,2),             -- v2: aggregated from user_ratings
    rating_count_internal   INTEGER NOT NULL DEFAULT 0,
    locked_fields           TEXT[] NOT NULL DEFAULT '{}', -- admin-edited columns, see below
    last_synced_at          TIMESTAMPTZ NOT NULL,
    credits_synced_at       TIMESTAMPTZ,              -- feature 85, see below
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_movies_release_date ON movies (release_date);
CREATE INDEX idx_movies_last_synced_at ON movies (last_synced_at);
```

### `series`

```sql
CREATE TABLE series (
    id                      BIGSERIAL PRIMARY KEY,
    title                   VARCHAR(500) NOT NULL,
    original_title          VARCHAR(500),
    slug                    VARCHAR(255) NOT NULL UNIQUE,
    overview                TEXT,
    first_air_date          DATE,
    last_air_date           DATE,
    number_of_seasons       INTEGER,
    number_of_episodes      INTEGER,
    status                  VARCHAR(50),              -- RETURNING, ENDED, CANCELED, ...
    original_language       VARCHAR(10),
    poster_url              VARCHAR(1000),
    backdrop_url            VARCHAR(1000),
    rating_external         NUMERIC(3,1),
    rating_count_external   INTEGER,
    rating_internal         NUMERIC(3,2),
    rating_count_internal   INTEGER NOT NULL DEFAULT 0,
    locked_fields           TEXT[] NOT NULL DEFAULT '{}', -- admin-edited columns, see below
    last_synced_at          TIMESTAMPTZ NOT NULL,
    credits_synced_at       TIMESTAMPTZ,              -- feature 85, see below
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_series_first_air_date ON series (first_air_date);
CREATE INDEX idx_series_last_synced_at ON series (last_synced_at);
```

### `books`

Modeled at **work** level (not edition). Page count and publisher are out of
MVP scope — they require remodeling at edition level (separate
investigation). `isbn` (feature 71 — `book_isbn_field`) is the exception:
Open Library already returns it in the same `search.json` call used to
populate the other work-level fields, so it costs no extra request.
Authorship is modeled via `credits` with role `AUTHOR`, supporting co-authorship.

```sql
CREATE TABLE books (
    id                      BIGSERIAL PRIMARY KEY,
    title                   VARCHAR(500) NOT NULL,
    original_title          VARCHAR(500),
    slug                    VARCHAR(255) NOT NULL UNIQUE,
    overview                TEXT,
    first_publish_date      DATE,
    original_language       VARCHAR(10),
    poster_url              VARCHAR(1000),            -- cover image
    isbn                    VARCHAR(20),              -- first ISBN reported by Open Library for this work; see note below
    rating_external         NUMERIC(3,1),
    rating_count_external   INTEGER,
    rating_internal         NUMERIC(3,2),
    rating_count_internal   INTEGER NOT NULL DEFAULT 0,
    locked_fields           TEXT[] NOT NULL DEFAULT '{}', -- admin-edited columns, see below
    last_synced_at          TIMESTAMPTZ NOT NULL,
    credits_synced_at       TIMESTAMPTZ,              -- feature 85, see below
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_books_first_publish_date ON books (first_publish_date);
CREATE INDEX idx_books_last_synced_at ON books (last_synced_at);
```

**`isbn`** (feature 71): Open Library's `search.json` returns `isbn` as a
list — a work can have several editions/ISBNs. `book_to_dict`
(`backlogg/books/adapters/open_library.py`) persists the **first** entry
as-is, with no ISBN-13/ISBN-10 preference — `search.json` already orders
`isbn` by edition relevance for the matched work, so the first entry is a
reasonable canonical pick without an extra priority pass.

### `games`

```sql
CREATE TABLE games (
    id                      BIGSERIAL PRIMARY KEY,
    title                   VARCHAR(500) NOT NULL,
    original_title          VARCHAR(500),
    slug                    VARCHAR(255) NOT NULL UNIQUE,
    overview                TEXT,
    release_date            DATE,
    game_type               VARCHAR(30) NOT NULL,     -- MAIN_GAME, DLC_ADDON, EXPANSION, ... (see allowlist note below)
    original_language       VARCHAR(10),
    poster_url              VARCHAR(1000),
    backdrop_url            VARCHAR(1000),
    rating_external         NUMERIC(3,1),
    rating_count_external   INTEGER,
    rating_internal         NUMERIC(3,2),
    rating_count_internal   INTEGER NOT NULL DEFAULT 0,
    locked_fields           TEXT[] NOT NULL DEFAULT '{}', -- admin-edited columns, see below
    last_synced_at          TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_games_release_date ON games (release_date);
CREATE INDEX idx_games_game_type ON games (game_type);
CREATE INDEX idx_games_last_synced_at ON games (last_synced_at);
```

**Category allowlist** (feature 65 — `game_category_allowlist`, product
decision 2026-08-25): IGDB's raw `game_type`/`category` field has 14 values;
only 8 are ingested — `MAIN_GAME`, `DLC_ADDON`, `EXPANSION`,
`STANDALONE_EXPANSION`, `EPISODE`, `SEASON`, `REMAKE`, `REMASTER`. Excluded:
`BUNDLE`, `MOD`, `EXPANDED_GAME`, `PORT`, `FORK`, `PACK`, `UPDATE`. The
allowlist is defined once in `backlogg/games/constants.py` and enforced by
every ingestion path (seed/nightly sync, on-demand fallback by slug,
similar-games, search fan-out). Rows persisted before this feature shipped
that fall outside the allowlist are **not** purged automatically — see
`progress/history.md` (feature 65) for the documented row counts and the
decision on whether/when to purge them.

### `credits_synced_at` (feature 85 — backfill_credits_targeted)

Present on `movies`, `series` and `books` (not on `games`: games have no
people-credit ingestion, only company credits).

The targeted credits backfill (`scripts/backfill_sync.py <type>
--only-missing-credits`) builds its work list with `LEFT JOIN credits ...
WHERE NULL`. That predicate alone cannot tell "credits never fetched" from
"this item genuinely has no credits at the source" (a TMDB entry with empty
`cast`/`crew`, an Open Library work with no resolvable author), so those
items would be re-fetched on every run forever.

- Written **only** by the targeted backfill, after a *successful* credits
  fetch — whether or not the fetch produced any row. The nightly/ranking
  sync does not touch it: items it fills drop out of the work list through
  the `LEFT JOIN` anyway.
- A **failed** fetch leaves it NULL on purpose, so the next run retries it.
- `NULL` = never looked up. The work list filters
  `no rows in credits AND credits_synced_at IS NULL`; `--recheck` ignores
  the second half and forces a full re-sweep.

### `locked_fields` (feature 49 — catalog_manual_edit)

Present on all four item tables above (`movies`, `series`, `books`, `games`).
Movies/series/books/games are read-only by default — only the nightly sync
(`backlogg/scheduler/jobs.py`) writes to them. `locked_fields` is a
per-**column** lock, not a per-**item** lock: it holds the names of the
columns an admin has manually corrected via
`PATCH /v1/admin/{type}/{slug}` (see `docs/api.md`).

- Written to only by the admin edit endpoint (`backlogg/admin/service.py` ->
  `<domain>.repository.admin_update_*`), which appends every field touched
  in the request and removes any field named in `unlock_fields`.
- Read by `upsert_movie`/`upsert_series`/`upsert_book`/`upsert_game` (each
  domain's `repository.py`) on every sync run: a column listed here is
  excluded from the `INSERT ... ON CONFLICT DO UPDATE` `SET` clause via a
  `CASE` expression that keeps the target row's own value instead of the
  proposed sync value. `"genres"` is a valid entry even though it is not a
  real column (it is a many-to-many relation) — when present, the genre
  re-sync block is skipped entirely for that item.
- Never touched by anything else: a fresh row from the sync always starts
  with `'{}'` (the column default).

## External IDs

Maps local items to their IDs in external sources. One item can have IDs in multiple sources.

```sql
CREATE TABLE external_ids (
    id              BIGSERIAL PRIMARY KEY,
    item_type       VARCHAR(20) NOT NULL,            -- MOVIE, SERIES, BOOK, GAME, PERSON, COMPANY
    item_id         BIGINT NOT NULL,
    source          VARCHAR(20) NOT NULL,            -- TMDB, IGDB, OPEN_LIBRARY, IMDB, ...
    external_id     VARCHAR(100) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_external_id UNIQUE (item_type, source, external_id),
    CONSTRAINT uq_item_source UNIQUE (item_type, item_id, source)
);

CREATE INDEX idx_external_ids_item ON external_ids (item_type, item_id);
```

No real FK to item tables — polymorphic reference, integrity enforced by application code.

`uq_external_id` incluye `item_type` **a propósito**: TMDB numera películas,
series y personas en secuencias independientes que se solapan, así que el id
110531 puede ser a la vez una serie y un actor. Hasta la migración `0036` la
restricción era `UNIQUE (source, external_id)` y el primero que reclamaba un
número dejaba a los demás tipos sin poder enlazarse nunca — en silencio, porque
ambas rutas de escritura hacen un pre-check y **saltan** el par ya reclamado
(issue #20: 7 de 752 series de 2022 perdidas en dev, todas bloqueadas por filas
`item_type='PERSON'`). Todo lector que resuelva un ítem por su id externo tiene
que filtrar también por `item_type`; si no, puede devolver la fila de otro tipo.

Lo que **sigue** prohibido es que dos ítems del **mismo** tipo compartan
`(source, external_id)`: eso es un id duplicado de verdad y el pre-check
conserva ahí su semántica de "gana el primero que lo reclamó".

## Genres

Separate genre tables per content type (taxonomies are too heterogeneous to share).

```sql
-- Same pattern for series_genres, book_genres, game_genres
CREATE TABLE movie_genres (
    id      BIGSERIAL PRIMARY KEY,
    name    VARCHAR(100) NOT NULL UNIQUE,
    slug    VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE movie_genres_join (
    movie_id    BIGINT NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    genre_id    BIGINT NOT NULL REFERENCES movie_genres(id) ON DELETE CASCADE,
    PRIMARY KEY (movie_id, genre_id)
);

CREATE INDEX idx_movie_genres_join_genre ON movie_genres_join (genre_id);
```

### `book_genres` — vocabulario controlado (feature 72)

A diferencia de movies/series/games, cuyos géneros vienen ya normalizados de
TMDB/IGDB, los de libros **no** son las etiquetas que devuelve la fuente. Hasta
la feature 72 se derivaban del campo `subject` de Open Library, una folksonomía
sin control (~40 etiquetas por obra) que produjo 510 filas distintas con solo
370 libros ingeridos, 397 de ellas usadas una sola vez ("Triathlon",
"Concentration camps", "Country homes").

Desde la feature 72, `book_genres` solo contiene etiquetas de un **vocabulario
controlado y cerrado** definido en el adaptador
(`_CONTROLLED_GENRES`, `backlogg/books/adapters/open_library.py`): ~32 entradas
del tipo Fiction, Poetry, Drama, Essays, Literature, Children's & Young Adult,
Philosophy, Psychology, History, Science, Technology, Cooking… Se derivan, por
orden de precedencia, de `lcc` (Library of Congress) → `ddc` (Dewey) →
`subject_facet` filtrado contra ese mismo vocabulario. `lcc` decide siempre la
disciplina; el único punto donde se lee `ddc` además de `lcc` es la **forma
literaria** dentro de las clases de literatura (`PS` + `813.54` → Fiction +
Literature), porque LCC clasifica la literatura por procedencia y lengua y
nunca codifica la forma. Detalle del mapeo y su justificación en
`docs/external-apis.md`.

Consecuencias operativas:

- Es un **eje grueso** (ficción vs ensayo, literatura vs psicología vs
  historia), no género de lector: DDC/LCC clasifican por disciplina y
  procedencia. Fantasía/terror/romance es trabajo de las features 76-78.
- Resultado medido en dev sobre los 100 libros de la siembra: **15 etiquetas
  distintas, 96 de 100 libros con género**, frente a las 510 etiquetas (397 de
  ellas usadas una sola vez) que producía la folksonomía con 370 libros.
- Un libro puede quedarse **sin filas en `book_genres_join`** cuando no trae
  ninguna de las tres señales; es un resultado aceptado, no un fallo.
- Son datos **derivados y regenerables** por reingesta
  (`scripts/backfill_sync.py book`). La migración
  `0033_books_controlled_genres_purge` los purgó por eso, preservando los
  libros con `genres` en `locked_fields` (edición manual de admin, feature 49),
  que `upsert_book` no reescribe.

## Platforms (games only)

```sql
CREATE TABLE game_platforms (
    id      BIGSERIAL PRIMARY KEY,
    name    VARCHAR(100) NOT NULL UNIQUE,
    slug    VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE game_platforms_join (
    game_id      BIGINT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    platform_id  BIGINT NOT NULL REFERENCES game_platforms(id) ON DELETE CASCADE,
    PRIMARY KEY (game_id, platform_id)
);
```

## People & Credits

### `people`

```sql
CREATE TABLE people (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(255) NOT NULL UNIQUE,
    profile_url     VARCHAR(1000),
    last_synced_at  TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_people_name ON people USING GIN (to_tsvector('simple', name));
CREATE INDEX idx_people_last_synced_at ON people (last_synced_at);
```

### `credits`

Polymorphic join between people and items. One person can have multiple credits
on the same item with different roles.

```sql
CREATE TABLE credits (
    id              BIGSERIAL PRIMARY KEY,
    item_type       VARCHAR(20) NOT NULL,           -- MOVIE, SERIES, BOOK, GAME
    item_id         BIGINT NOT NULL,
    person_id       BIGINT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    role            VARCHAR(50) NOT NULL,           -- DIRECTOR, ACTOR, CREATOR, AUTHOR, SOURCE_AUTHOR, WRITER
    character_name  VARCHAR(255),                   -- ACTOR only
    billing_order   INTEGER,                        -- 0 = top-billed
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_credit UNIQUE (item_type, item_id, person_id, role)
);

CREATE INDEX idx_credits_person ON credits (person_id);
CREATE INDEX idx_credits_item ON credits (item_type, item_id);
CREATE INDEX idx_credits_role ON credits (role);
```

Supported roles by domain:

| Domain  | Roles                                        | Notes                                      |
|---------|----------------------------------------------|--------------------------------------------|
| Movies  | DIRECTOR, ACTOR, SOURCE_AUTHOR, WRITER       | Actors limited to top 10 by billing_order  |
| Series  | CREATOR, ACTOR, SOURCE_AUTHOR, WRITER        | Actors limited to top 10                   |
| Books   | AUTHOR                                       | Supports co-authorship                     |
| Games   | *(none)*                                     | See note below — no person credits at all  |

### Games have no person credits — by decision (2026-09-04)

`credits` carries **no `GAME` rows at all**, and no ingestion path writes any.
Measured against the dev database on 2026-09-04: 500 `BOOK`, 5.618 `MOVIE`,
8.675 `SERIES`, **0 `GAME`** — with 465 games in the catalog.

This table used to promise a `DIRECTOR` role for games "only when IGDB provides
it". That was an intention from the start of the project that was never built,
and the qualifier was wrong on the facts: **IGDB v4 exposes no person credits at
all**. Its endpoints are `/games`, `/covers`, `/companies` and
`/involved_companies` — every one of them about companies, not people. Nothing
was ever going to arrive "when IGDB provides it".

Building it would have meant a different source (Wikidata's P57/P178/P58/P86, or
MobyGames) for a datum that is thin in nearly every source, whose only real
payoff is the cross-type bridge game ↔ film by shared director — a product bet,
not a requirement. **The decision was to drop it rather than carry it**, so this
document now matches what the code does.

What games *do* have is **company credits** (`DEVELOPER`, `PUBLISHER`), in the
separate `company_credits` table, populated from IGDB's `involved_companies`.
That is a different table with different semantics and it is unaffected.

### `SOURCE_AUTHOR` vs `WRITER` (movies and series)

Both come from the `Writing` department of TMDB's `/credits`, but they are **not**
interchangeable and the department alone is not a usable filter — TMDB tells them
apart by `job`, and the same department also carries animation storyboard jobs
(`Story Artist`, `Head of Story`, `Story Supervisor`), which must never be
persisted as credits. Ingestion filters by an explicit `job` allowlist:

| Role            | TMDB jobs                                                                                  | Purpose |
|-----------------|--------------------------------------------------------------------------------------------|---------|
| `SOURCE_AUTHOR` | `Novel`, `Book`, `Short Story`, `Comic Book`, `Graphic Novel`, `Theatre Play`, `Original Story`, `Characters` | Author of the **source work**. This is the book → film cross-type bridge: same `people` row as the book's `AUTHOR` credit |
| `WRITER`        | `Screenplay`, `Writer`, `Teleplay`, `Adaptation`, `Dialogue`                                 | Screenwriter. Detail-page data only (Credits section), not a recommendation signal |

`Story` and `Screenstory` are deliberately excluded from `SOURCE_AUTHOR`: in TMDB
they mean "screen story" — original material written for the screen, not a prior work.

Caveat: translators are credited with `job: "Book"` (e.g. *The Witcher* credits
Danusia Stok and David French alongside Sapkowski) and the `job` does not tell them
apart. Cross-type queries filter this by requiring the person to also hold an
`AUTHOR` credit on a book in the catalog.

## Companies

Studios, publishers, developers. Separate from people (no biography, have founding date / HQ / website).

```sql
CREATE TABLE companies (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(255) NOT NULL UNIQUE,
    logo_url        VARCHAR(1000),
    last_synced_at  TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_companies_name ON companies USING GIN (to_tsvector('simple', name));

CREATE TABLE company_credits (
    id          BIGSERIAL PRIMARY KEY,
    item_type   VARCHAR(20) NOT NULL,               -- GAME in MVP; MOVIE, SERIES in v2
    item_id     BIGINT NOT NULL,
    company_id  BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    role        VARCHAR(50) NOT NULL,               -- DEVELOPER, PUBLISHER
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_company_credit UNIQUE (item_type, item_id, company_id, role)
);

CREATE INDEX idx_company_credits_company ON company_credits (company_id);
CREATE INDEX idx_company_credits_item ON company_credits (item_type, item_id);
```

Read via `backlogg.games.repository.get_company_credits_for_item` (feature 67 —
same join pattern as `credits`/`people`'s `get_credits_for_item`), exposed as
`companies[]` in `GET /v1/games/{slug}` (see `docs/api.md`). MOVIE/SERIES
rows are still reserved for v2 and have no reader yet.

## Search

Materialized view used for cross-type full-text search.

`search_vector` indexes the title twice: once as-is, once with all
punctuation stripped (spaces preserved as word separators) so a query typed
without punctuation (`Spiderman`) still matches a punctuated title
(`Spider-Man`) — the `simple` dictionary never generates that concatenated
lexeme on its own. `overview` is left unnormalized.

`rating_internal` (feature 69, `rating_internal_list_exposure`) is included in
every sub-query alongside `rating_external` — it is a plain passthrough of the
base table's own `rating_internal` column, not a new computation.

```sql
CREATE MATERIALIZED VIEW catalog_search AS
SELECT
    id,
    'MOVIE'         AS item_type,
    slug,
    title,
    overview,
    poster_url,
    release_date,
    rating_external,
    rating_internal,
    to_tsvector('simple', title || ' ' || regexp_replace(title, '[^a-zA-Z0-9\s]', '', 'g') || ' ' || COALESCE(overview, '')) AS search_vector
FROM movies
UNION ALL
SELECT id, 'SERIES', slug, title, overview, poster_url, first_air_date, rating_external, rating_internal,
    to_tsvector('simple', title || ' ' || regexp_replace(title, '[^a-zA-Z0-9\s]', '', 'g') || ' ' || COALESCE(overview, ''))
FROM series
UNION ALL
SELECT id, 'BOOK', slug, title, overview, poster_url, first_publish_date, rating_external, rating_internal,
    to_tsvector('simple', title || ' ' || regexp_replace(title, '[^a-zA-Z0-9\s]', '', 'g') || ' ' || COALESCE(overview, ''))
FROM books
UNION ALL
SELECT id, 'GAME', slug, title, overview, poster_url, release_date, rating_external, rating_internal,
    to_tsvector('simple', title || ' ' || regexp_replace(title, '[^a-zA-Z0-9\s]', '', 'g') || ' ' || COALESCE(overview, ''))
FROM games;

CREATE INDEX idx_catalog_search_vector ON catalog_search USING GIN (search_vector);
CREATE INDEX idx_catalog_search_type ON catalog_search (item_type);
CREATE UNIQUE INDEX uq_catalog_search_type_id ON catalog_search (item_type, id);
```

Refreshed after each sync job completes:
```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY catalog_search;
```

## Shared trigger

Applied to all tables with `updated_at`:

```sql
CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply to: movies, series, books, games, people, companies, seed_targets
CREATE TRIGGER set_updated_at_movies BEFORE UPDATE ON movies
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
```

## Sync cursors

Persisted per-type offset for slice-based nightly sync. Each sync run
processes up to `SYNC_SLICE_SIZE` items starting at `next_offset` and then
advances the cursor, wrapping back to 0 when `SEED_TOP_N_*` is reached or
the external API returns fewer items than requested.

```sql
CREATE TABLE sync_cursors (
    item_type   TEXT PRIMARY KEY,           -- MOVIE | SERIES | BOOK | GAME
    next_offset INTEGER NOT NULL DEFAULT 0, -- where the next run starts fetching
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`updated_at` is refreshed by the application on every cursor upsert
(no trigger — the row is only written by the sync jobs).

> ⚠️ **Desde la feature 86 solo `BOOK` y `GAME` usan esta tabla.** Movies y
> series pasaron a la lista objetivo de `seed_targets` (abajo): no hay offset
> que avanzar porque no hay ranking que recorrer. Las filas `MOVIE`/`SERIES`
> que ya existan **se conservan** y simplemente dejan de leerse y escribirse —
> borrarlas dejaría un `downgrade` de la migración 0035 apuntando a un catálogo
> que el código anterior no sabría reanudar.

## Seed targets (feature 86)

La lista objetivo de TMDB: **qué ítems quiere el catálogo**, enumerada por
`/discover` bajo el umbral de calidad antes de hidratar ninguno. Separa la
*enumeración* (~3.600 peticiones baratas) de la *hidratación* (una petición de
detalle por ítem), que es lo que permite reanudar, ordenar y auditar la
segunda de forma independiente de la primera.

```sql
CREATE TABLE seed_targets (
    id              BIGSERIAL PRIMARY KEY,
    item_type       VARCHAR(20)  NOT NULL,   -- MOVIE | SERIES
    source          VARCHAR(20)  NOT NULL,   -- TMDB
    external_id     VARCHAR(100) NOT NULL,   -- id del ítem en la fuente
    vote_count      INTEGER,                 -- observado al enumerar
    release_year    INTEGER,                 -- observado al enumerar
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    unreachable_at  TIMESTAMPTZ,             -- 404 en la fuente
    discovered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_seed_target UNIQUE (item_type, source, external_id)
);

CREATE INDEX idx_seed_targets_work_order
    ON seed_targets (item_type, source, attempts);
```

**Cómo se reanuda.** No hay marcador de progreso. Lo pendiente es una
*diferencia contra el catálogo*, calculada en vivo:

```sql
SELECT st.external_id
FROM seed_targets st
LEFT JOIN external_ids ei
  ON ei.item_type = st.item_type
 AND ei.source     = st.source
 AND ei.external_id = st.external_id
WHERE st.item_type = 'MOVIE' AND st.source = 'TMDB' AND ei.id IS NULL
  AND st.unreachable_at IS NULL
  AND st.attempts < :max_attempts
ORDER BY st.attempts ASC, st.vote_count DESC NULLS LAST, st.id ASC
LIMIT :slice_size;
```

Un run que muera a mitad no deja nada que arreglar: la consulta describe
exactamente el trabajo restante, muera como muera.

**Por qué `attempts` y `unreachable_at`.** Hay targets que **nunca** podrán
enlazarse, por dos motivos sin relación entre sí:

- **404 en la fuente**: el id se enumeró pero TMDB ya no lo sirve.
- **Resuelve bien y aun así no se enlaza**: el detalle se descarga sin error
  pero el ítem no acaba con fila en `external_ids`. El caso realista es la
  colisión de slug: `slug` es único, así que dos ids de TMDB cuyo título y año
  generan el mismo slug comparten **una sola fila**, y solo uno de los dos
  conserva su enlace (`uq_item_source` admite un id por ítem y fuente). Lo
  mismo pasa si el payload se rechaza por validación.

  Antes de la migración `0036` había una tercera causa, y era la masiva: la
  restricción no incluía `item_type`, así que una fila `PERSON` con el id de
  TMDB de una serie la dejaba sin enlazar para siempre (issue #20). Esa ya no
  existe. Ojo con el matiz: cuando la colisión es *dentro* del mismo tipo, el
  target **sí** encuentra fila en el join y se cuenta como hecho aunque apunte
  a otro `item_id`; lo que llega a `unlinkable` es solo lo que no consigue
  ninguna fila.

Dejarlos en el conjunto pendiente le pondría a `pending` un **suelo permanente
> 0**, y de que `pending` llegue a 0 dependen las dos garantías del diseño: la
rotación de refresco (que solo actúa cuando no queda nada pendiente) y la
terminación del bucle de backfill. Así que se **retiran** de la lista de
trabajo: `unreachable_at` sella el 404 la primera vez que se observa (respuesta
definitiva), y `attempts` cuenta pasadas **concluyentes** —una petición fallida
no cuenta, así que una caída de TMDB no retira un target sano— con retirada al
llegar a `TMDB_SEED_MAX_ATTEMPTS`.

El residuo no se esconde: se cuenta aparte y se reporta como `stuck` (desglosado
en `gone` y `unlinkable`) en el resultado del job y en su log. El orden por
`attempts` se conserva para que, antes de retirarse, un target problemático
vaya detrás de todo lo no intentado en vez de acampar a la cabeza de la cola.

> El defecto de fondo —`uq_external_id` único sobre `(source, external_id)` sin
> incluir `item_type`— quedó arreglado en la migración `0036` (issue #20). La
> maquinaria de retirada **no** sobra por ello: sigue haciendo falta para el
> 404 y para el ítem que resuelve bien y aun así no consigue enlace.

**Por qué `vote_count`/`release_year`.** Son gratis (viajan en el payload de
`/discover`) y dan a la hidratación un orden por notoriedad, así que una
siembra interrumpida deja dentro lo mejor del catálogo y no una rebanada
arbitraria.

**Rotación de refresco.** Cuando no queda nada pendiente **trabajable** —lo que
es alcanzable gracias a la retirada de arriba—, la rebanada nocturna se llena
con los ítems del catálogo de `last_synced_at` más antiguo
(`get_stale_catalog_external_ids`). Es lo que sustituye —mejorándola— a la
cobertura que el cursor de `/popular` daba por efecto colateral, y lo que
mantiene el catálogo dentro de la ventana de caché de 6 meses de TMDB.

`updated_at` sí tiene trigger (`set_updated_at_seed_targets`, reutilizando
`trigger_set_updated_at()` de la migración 0001).

## Users

```sql
CREATE TABLE users (
    id              BIGSERIAL PRIMARY KEY,
    username        VARCHAR(50) NOT NULL UNIQUE,   -- URL identifier, no separate slug
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,         -- argon2, never plaintext
    display_name    VARCHAR(255),
    bio             TEXT,
    avatar_url      VARCHAR(1000),
    email_verified  BOOLEAN NOT NULL DEFAULT false, -- set true via /auth/verify/confirm
    is_banned       BOOLEAN NOT NULL DEFAULT false, -- content moderation (admin)
    is_admin        BOOLEAN NOT NULL DEFAULT false, -- admin role flag
    is_superadmin   BOOLEAN NOT NULL DEFAULT false, -- superadmin role flag
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`username` doubles as the URL identifier (`/users/{username}`) — no numeric
id or separate slug is exposed. Auth uses a short-lived access token (JWT)
plus a persisted, rotating refresh token (`refresh_tokens`, below);
see `docs/api.md` for the endpoint contracts. `email_verified` starts `false`
and flips to `true` when the user confirms an email-verification token
(`account_tokens`, below).

`is_banned` is a content-moderation flag flipped by admins via
`POST /admin/users/{username}/ban` / `/unban`. A banned user cannot log in or
refresh (both `401`), and **all** of their reviews become invisible on the same
surfaces as a hidden review (see `user_ratings.is_hidden` below): they are
excluded from listings, the feed and the rating aggregates.

`is_admin` is an admin-role flag. There is **no API endpoint** to set it —
it is flipped by hand in the database by an operator, deliberately, to avoid
creating a privilege-escalation surface. It is exposed only on `UserMeOut`
(`GET /v1/users/me`, own profile), never on the public `UserOut`. It is
consumed by the frontend (`apps/web`, `/admin` section) to decide which
authenticated users are allowed to see the admin section — a plain session
is not enough.

To grant it locally (dev DB, Docker container `backlogg-db`): make sure
migration `0020` has been applied first (the dev DB does not migrate itself —
`ERROR: column "is_admin" of relation "users" does not exist` means this step
was skipped), then run the `UPDATE`:

```bash
uv run alembic upgrade head
docker exec -it backlogg-db psql -U postgres -d backlogg \
  -c "UPDATE users SET is_admin = true WHERE username = '<username>';"
```

In production, run the equivalent `UPDATE` directly against the Neon
database (e.g. via its SQL console or `psql <connection-string>`) — there is
no CLI script for this, on purpose. After granting it, the affected user
must log out and back in (or wait for their access token to rotate) for
`GET /v1/users/me` to reflect the new value.

`is_superadmin` is a second, higher-privilege role flag, same rules as
`is_admin`: **no API endpoint** sets it either — it is flipped by hand in the
DB by an operator, the same way as above (`UPDATE users SET is_superadmin =
true WHERE username = '<username>';`). It is exposed only on `UserMeOut`,
never on the public `UserOut`. A superadmin is the only role allowed to grant
or revoke **other users'** `is_admin` flag, via
`POST /v1/admin/users/{username}/grant-admin` and `/revoke-admin`. These two
endpoints are a deliberate deviation from the rest of `/v1/admin/*`: on top
of the shared `X-API-Key` header they also require the caller's own
`Authorization: Bearer` token and check `is_superadmin` on that authenticated
caller server-side — `403` if the caller is not a superadmin, even with a
correct `X-API-Key` and even if the caller is a regular `is_admin`. Both
endpoints are idempotent and `404` if the target username does not exist.

**Self-revocation is allowed on purpose.** A superadmin can grant/revoke
`is_admin` on themselves or on another superadmin. This is safe because these
endpoints only ever flip `is_admin`, never `is_superadmin` — which stays
100% DB-only, with zero API surface — so a superadmin can never lose their
superadmin status through this API. The only possible side effect is losing
access to the frontend `/admin` dashboard (gated by `is_admin`), which is
recoverable the same way it was granted: by hand in the DB.

### `refresh_tokens`

One row per issued refresh token. The token itself is an opaque random value
(`secrets.token_urlsafe`, not a JWT); only its **sha256 hash** is stored — the
plaintext is returned to the client once (in the HTTP response) and never
persisted or logged. Rotation on `POST /auth/refresh` revokes the used token
(`revoked_at`) and inserts a new row; presenting an already-revoked token is
treated as **reuse** and revokes every still-active token for that user.

```sql
CREATE TABLE refresh_tokens (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(64) NOT NULL UNIQUE,   -- sha256 hex, never plaintext
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,                    -- NULL while active
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens (user_id);
```

Access token lifetime is `JWT_EXPIRE_MINUTES` (short, 15 by default); refresh
token lifetime is `REFRESH_EXPIRE_DAYS` (30 by default).

### `account_tokens`

One row per issued account-recovery token, covering **both** email
verification and password reset (distinguished by `purpose`). Like refresh
tokens, the value is an opaque random string (`secrets.token_urlsafe`) and only
its **sha256 hash** is stored — the plaintext lives only in the email link and
is never persisted or logged. Tokens are **single-use** (`consumed_at` is
stamped on first use) and **expiring** (`expires_at`); a token that is unknown,
already consumed, expired, or presented for the wrong `purpose` is rejected with
`400`.

```sql
CREATE TABLE account_tokens (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(64) NOT NULL UNIQUE,   -- sha256 hex, never plaintext
    purpose     VARCHAR(20) NOT NULL,          -- 'email_verify' | 'password_reset'
    expires_at  TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,                    -- NULL until first (and only) use
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_account_tokens_purpose
        CHECK (purpose IN ('email_verify', 'password_reset'))
);
CREATE INDEX idx_account_tokens_user_id ON account_tokens (user_id);
```

Token lifetimes are configurable: `EMAIL_VERIFY_EXPIRE_HOURS` (24 by default)
and `PASSWORD_RESET_EXPIRE_HOURS` (1 by default). A password reset also revokes
every still-active `refresh_tokens` row for the user (forces re-login).

## Ratings & reviews

### `user_ratings`

One row per (user, item): an optional 1-5 `score` (half-star steps — 1.0,
1.5, 2.0, ..., 5.0) and/or optional `review_text` — either can be null, but
the row exists once a user has rated and/or reviewed an item (upsert on
repeat calls). Polymorphic `item_type` + `item_id`, same pattern as
`credits`/`external_ids`; no real FK to movies/series/books/games.

```sql
CREATE TABLE user_ratings (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_type       VARCHAR(20) NOT NULL,     -- MOVIE, SERIES, BOOK, GAME
    item_id         BIGINT NOT NULL,
    score           NUMERIC(2,1),             -- 1.0-5.0 in 0.5 steps, nullable (text-only review)
    review_text     TEXT,
    is_hidden       BOOLEAN NOT NULL DEFAULT false, -- content moderation (admin)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_user_rating_item UNIQUE (user_id, item_type, item_id),
    CONSTRAINT ck_user_ratings_score_range CHECK (
        score IS NULL OR (score >= 1 AND score <= 5 AND score * 2 = FLOOR(score * 2))
    )
);

CREATE INDEX idx_user_ratings_item ON user_ratings (item_type, item_id);
CREATE INDEX idx_user_ratings_user ON user_ratings (user_id);
```

`is_hidden` is a per-review content-moderation flag flipped by admins via
`POST /admin/reviews/{id}/hide` / `/unhide`. It is one half of the reusable
**"visible review"** condition applied consistently across the codebase
(`backlogg/ratings/repository.py::visible_review_filters`): a review is visible
only when `is_hidden = false` **and** its author is **not banned**
(`users.is_banned = false`, which is why those queries JOIN `users`). Non-visible
reviews are excluded from `GET /{type}/{slug}/ratings`, `GET /users/{username}/reviews`,
the feed and the rating aggregates.

After every create/update/delete of a `user_ratings` row — and after every
hide/unhide or ban/unban moderation action — the application recalculates and
persists `rating_internal` (`AVG(score)` over **visible** reviews, ignoring nulls)
and `rating_count_internal` (`COUNT(score)` over visible reviews) on the affected
movies/series/books/games row (`backlogg/ratings/repository.py`,
`recalculate_item_aggregates` — same cross-domain write precedent as
`backlogg/admin/repository.py`).

### `review_likes`

One like per (user, rating).

```sql
CREATE TABLE review_likes (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating_id   BIGINT NOT NULL REFERENCES user_ratings(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_review_like UNIQUE (user_id, rating_id)
);

CREATE INDEX idx_review_likes_rating ON review_likes (rating_id);
CREATE INDEX idx_review_likes_user ON review_likes (user_id);
```

### `review_reports`

A user's report flagging a review (a `user_ratings` row) as problematic, plus
the admin moderation queue. One report per `(reporter_id, rating_id)` pair
(`uq_review_report_pair`) makes reporting idempotent — reporting the same review
twice never creates a second row. Both FKs cascade on delete, so a report
disappears when either the reporter's account or the reported review is removed.
`reason` is a short optional free-text note. `status` is an enum-like plain
string constrained by a CHECK to `open`/`resolved` (same modelling as
`account_tokens.purpose`); it starts `open` and flips to `resolved` (with
`resolved_at` set) when an admin clears it via `POST /admin/reports/{id}/resolve`.

```sql
CREATE TABLE review_reports (
    id           BIGSERIAL PRIMARY KEY,
    reporter_id  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating_id    BIGINT NOT NULL REFERENCES user_ratings(id) ON DELETE CASCADE,
    reason       VARCHAR(300),
    status       VARCHAR(20) NOT NULL DEFAULT 'open',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at  TIMESTAMPTZ,

    CONSTRAINT uq_review_report_pair UNIQUE (reporter_id, rating_id),
    CONSTRAINT ck_review_reports_status CHECK (status IN ('open', 'resolved'))
);

CREATE INDEX idx_review_reports_status ON review_reports (status);
```

## Feed events

### `activity_events`

Feature 54. A generic table of feed-worthy facts, one row per event.
`backlogg/feed/repository.py` reads exclusively from this table (a UNION ALL
across the four content types, same style as `genres`/`user_ratings`) instead
of joining `user_ratings` directly, so a future event type only needs a new
writer, not a change to the feed's read model. `event_type` is a plain string
constrained by a CHECK to `rating_created`/`status_completed` — no PostgreSQL
ENUM type, same modelling as `library_entries.status`/`user_ratings.score`.
Polymorphic `item_type` + `item_id` (same pattern as `user_ratings`/
`library_entries`), no real FK to the content tables.

```sql
CREATE TABLE activity_events (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_type  VARCHAR(20) NOT NULL,   -- 'rating_created' | 'status_completed'
    item_type   VARCHAR(20) NOT NULL,   -- 'MOVIE' | 'SERIES' | 'BOOK' | 'GAME'
    item_id     BIGINT NOT NULL,
    rating_id   BIGINT REFERENCES user_ratings(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_activity_events_rating_id UNIQUE (rating_id),
    CONSTRAINT ck_activity_events_type
        CHECK (event_type IN ('rating_created', 'status_completed'))
);

CREATE INDEX idx_activity_events_user ON activity_events (user_id, created_at);
CREATE INDEX idx_activity_events_item ON activity_events (item_type, item_id);
```

Two event types today, both generated by the write-side services (not by a
trigger):

- **`rating_created`** — `backlogg/ratings/service.py::rate_item` inserts one
  when a rating is created/updated with a non-null `score` and/or
  `review_text` (`rating_id` set). `uq_activity_events_rating_id` (Postgres
  unique constraints allow multiple NULLs, so this only constrains
  `rating_created` rows) plus `INSERT ... ON CONFLICT DO NOTHING` is what
  makes generation idempotent — updating the same rating again never
  duplicates the event. If a later update clears both `score` and
  `review_text` back to null, the event is deleted (the rating row itself
  survives — it's an upsert). Deleting the rating outright cascades to its
  event via `ON DELETE CASCADE`, no extra code needed.
- **`status_completed`** — `backlogg/library/service.py::set_library_status`
  inserts one, with `rating_id` left NULL, only on a transition *into*
  `completed` (the previous status, read before the upsert, was something
  else). Repeating an already-`completed` PUT does not insert another row,
  but a later `completed → dropped → completed` cycle does insert a second
  one — each transition into `completed` is its own narrative fact, unlike
  `rating_created` there is no one-event-per-item dedup key. Every other
  transition (`want`/`in_progress`/`dropped`) never generates an event.

**Backfill.** Migration `0025_activity_events.py` backfills `rating_created`
events for every pre-existing `user_ratings` row that already has a `score`
and/or `review_text`, so `GET /feed?tab=following` isn't emptied overnight for
users who had reviews before this migration shipped.

**Read side / `GET /feed`.** `rating_created` rows are LEFT JOINed to
`user_ratings` (via `rating_id`) to resolve `score`/`review_text`/like count;
`status_completed` rows have no `rating_id`, so those columns resolve to NULL
for them — the feed response's minimal shape for `status_completed` (`author`,
`item`, `created_at` only) falls straight out of the join, no special-casing
needed downstream. Visibility reuses the "visible review" rule (`is_hidden` +
author not banned) for `rating_created` rows; `status_completed` rows only
check the author isn't banned (they have no `is_hidden` concept). `tab=popular`
ranks strictly by `like_count`, so `status_completed` rows (which have no
likes) are excluded from that tab entirely rather than surfaced with an
always-zero `like_count` that would make "popular" a meaningless ordering —
they still appear in `tab=following`.

## Follows

### `follows`

A unidirectional follow relationship between two users (no approval).
`follower_id` follows `followed_id`. One row per ordered pair; a user cannot
follow themselves (enforced in `backlogg/follows/service.py`, returns 422).
Following and unfollowing are both idempotent.

```sql
CREATE TABLE follows (
    id           BIGSERIAL PRIMARY KEY,
    follower_id  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    followed_id  BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_follow_pair UNIQUE (follower_id, followed_id)
);

CREATE INDEX idx_follows_follower ON follows (follower_id);
CREATE INDEX idx_follows_followed ON follows (followed_id);
```

The public profile (`GET /users/{username}`) derives `follower_count`
(`COUNT` where `followed_id = user`) and `following_count` (`COUNT` where
`follower_id = user`) from this table via `backlogg/follows/repository.py`.

## Library

### `library_entries`

One row per (user, item): the user's backlog status for a movie/series/book/
game. Polymorphic `item_type` + `item_id` (same pattern as `user_ratings`),
no real FK to the content tables. `status` is a plain string constrained by a
CHECK to `want`/`in_progress`/`completed`/`dropped` — no PostgreSQL ENUM type,
matching how the project models other enum-like columns. Setting the status is
an upsert on `(user_id, item_type, item_id)`.

```sql
CREATE TABLE library_entries (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_type   VARCHAR(20) NOT NULL,   -- 'MOVIE' | 'SERIES' | 'BOOK' | 'GAME'
    item_id     BIGINT NOT NULL,
    status      VARCHAR(20) NOT NULL,   -- 'want' | 'in_progress' | 'completed' | 'dropped'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_library_entry_item UNIQUE (user_id, item_type, item_id),
    CONSTRAINT ck_library_entries_status
        CHECK (status IN ('want', 'in_progress', 'completed', 'dropped'))
);

CREATE INDEX idx_library_entries_item ON library_entries (item_type, item_id);
CREATE INDEX idx_library_entries_user ON library_entries (user_id);
CREATE INDEX idx_library_entries_user_status ON library_entries (user_id, status);
```

`updated_at` is refreshed by the shared `trigger_set_updated_at()` trigger
(defined in migration 0001). The public profile (`GET /users/{username}`)
derives `library_counts` (`COUNT` grouped by `status`, zero-filled) from this
table, and `GET /{type}/{slug}` derives the caller's `viewer_status` from it.
`idx_library_entries_user_status` (migration 0027) covers the hottest read
path, `GET /users/{username}/library?status=...`, which filters by `user_id`
and then `status` within each branch of the repository's `UNION ALL` —
flagged by production audit2 (2026-08-19) as uncovered by the existing
single-column indexes.

## Notifications

### `notifications`

Social notifications for a recipient user, generated as a side effect of social
events by `backlogg/notifications/service.py`:

- `new_follower` — someone followed the recipient (no target).
- `review_like` — someone liked one of the recipient's reviews
  (`target_type = 'review'`, `target_id` = the `user_ratings.id`).
- `user_completed` (feature 55) — a followed user completed an item, i.e. a
  `status_completed` `activity_events` row (feature 54) was inserted for them.
  Fanned out to each of that user's **direct** followers only (no fan-out to
  followers-of-followers), one notification per follower per occurrence — same
  as `review_like`, repeated completions (`completed → dropped → completed`)
  each generate a new notification, no historical dedup. `target_type` = the
  item's `item_type` uppercase (`'MOVIE'`/`'SERIES'`/`'BOOK'`/`'GAME'`),
  `target_id` = the item's id — a direct reference to the content row, unlike
  `review_like` there is no rating involved. Generated by
  `backlogg/library/service.py::set_library_status`, right after the
  `status_completed` event, one call to
  `notifications/service.py::notify_user_completed` per direct follower
  (`backlogg/follows/repository.py::list_follower_ids`).

`actor_id` is who triggered the event, `recipient_id` is who receives it. Both
FK to `users` with `ON DELETE CASCADE`. Generation is deliberately best-effort:
the source operation (the follow / the like / the status_completed
transition) is committed first and any failure creating the notification is
swallowed, so it can never break that source operation.

```sql
CREATE TABLE notifications (
    id           BIGSERIAL PRIMARY KEY,
    recipient_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    actor_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type         VARCHAR(30) NOT NULL,   -- 'new_follower' | 'review_like' | 'user_completed'
    target_type  VARCHAR(20),            -- 'review' | 'MOVIE'/'SERIES'/'BOOK'/'GAME' (NULL for new_follower)
    target_id    BIGINT,                 -- user_ratings.id, or the item id (NULL for new_follower)
    is_read      BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_notifications_type
        CHECK (type IN ('new_follower', 'review_like', 'user_completed'))
);

-- Recipient feed: newest first.
CREATE INDEX idx_notifications_recipient_created
    ON notifications (recipient_id, created_at DESC);
```

**Read side / `GET /notifications`.** `backlogg/notifications/repository.py`
resolves the target item for both flavors that carry one in the same query,
reusing the same four (one per content model) `LEFT JOIN`s: for `review_like`
it hops through `user_ratings` first (`target_type='review'` →
`user_ratings.id` → `user_ratings.item_type`/`item_id`); for `user_completed`
it joins directly on `target_type`/`target_id` since `target_type` already IS
the item type. Each join's `ON` clause simply `OR`s the two match conditions,
so `slug`/`item_type` COALESCE out in one round-trip regardless of target
flavor.

## Admin action audit log

### `admin_actions`

Feature 63. A persisted, queryable trail of high-privilege admin/moderation
actions — before this table, the only record of "who banned this user and
when" was the ephemeral stdout JSON log line, with no retention guarantee on
Render and no way to query it after the fact. `backlogg/admin/audit.py`'s
`record_admin_action` is the single write path, called from the same DB
transaction as the state change it describes, right before that transaction's
`db.commit()` — so an audit row and the action it records always commit (or
roll back) together.

`actor_id` is nullable and FKs to `users` with `ON DELETE SET NULL` (not
CASCADE — the audit trail must survive the actor's account being deleted
later). Most audited routes are gated solely by the shared `X-API-Key` secret
with no caller identity, so `actor_id` is `NULL` for them; only
grant-admin/revoke-admin (`POST /v1/admin/users/{username}/grant-admin` /
`/revoke-admin`) also require a Bearer-authenticated `is_superadmin` caller
(feature 47), so those two set `actor_id` to that caller's `users.id`. `action`
and `target_type` are enum-like plain strings constrained by a CHECK — same
modelling as `review_reports.status`/`activity_events.event_type` — no
PostgreSQL ENUM type. `target_id` is a polymorphic reference (same pattern as
`user_ratings.item_type`/`item_id`, see "Notes on polymorphic references"
below): a `user_ratings.id` when `target_type = 'review'`, a `users.id` when
`'user'`, a `review_reports.id` when `'report'` — no real FK, so a target row
being deleted later never blocks or cascades into this table.

```sql
CREATE TABLE admin_actions (
    id          BIGSERIAL PRIMARY KEY,
    actor_id    BIGINT REFERENCES users(id) ON DELETE SET NULL,
    action      VARCHAR(30) NOT NULL,
    target_type VARCHAR(20) NOT NULL,
    target_id   BIGINT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_admin_actions_action
        CHECK (action IN ('hide_review', 'unhide_review', 'ban_user', 'unban_user',
                           'resolve_report', 'grant_admin', 'revoke_admin')),
    CONSTRAINT ck_admin_actions_target_type
        CHECK (target_type IN ('review', 'user', 'report'))
);

CREATE INDEX idx_admin_actions_created_at ON admin_actions (created_at);
```

Populated from four call sites, one `record_admin_action` call per action,
every invocation (including idempotent repeats — hiding an already-hidden
review still writes a row, since each call to the admin action is itself
worth auditing):

- `backlogg/moderation/service.py::set_review_hidden` — `hide_review` /
  `unhide_review`, `target_type='review'`, `target_id` = the `user_ratings.id`.
- `backlogg/moderation/service.py::set_user_banned` — `ban_user` /
  `unban_user`, `target_type='user'`, `target_id` = the banned/unbanned
  `users.id`.
- `backlogg/reports/service.py::resolve_report` — `resolve_report`,
  `target_type='report'`, `target_id` = the `review_reports.id`.
- `backlogg/admin/service.py::set_user_admin_role` — `grant_admin` /
  `revoke_admin`, `target_type='user'`, `target_id` = the target `users.id`,
  `actor_id` = the calling superadmin's `users.id`.

**Read side / `GET /v1/admin/actions`.** Paginated, `created_at DESC, id DESC`
(newest first, stable tiebreak within the same timestamp), same `X-API-Key`
gate as the rest of `/v1/admin/*`. Never persists or returns secret material
(the `X-API-Key` value, access/refresh tokens) — only the actor id, the action
name and the target being acted on.

## Notes on polymorphic references

`external_ids`, `credits`, `company_credits`, `user_ratings`, `library_entries`,
`activity_events`, `notifications` (target_type/target_id),
`admin_actions` (target_type/target_id) use polymorphic references
(`item_type`/`target_type` + `item_id`/`target_id`) with no real FK.
Referential integrity is enforced at the application layer, typically in the
use case that persists the item.
