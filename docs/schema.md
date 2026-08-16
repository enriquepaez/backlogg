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
    last_synced_at          TIMESTAMPTZ NOT NULL,
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
    last_synced_at          TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_series_first_air_date ON series (first_air_date);
CREATE INDEX idx_series_last_synced_at ON series (last_synced_at);
```

### `books`

Modeled at **work** level (not edition). ISBN, page count, publisher are out of MVP scope.
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
    rating_external         NUMERIC(3,1),
    rating_count_external   INTEGER,
    rating_internal         NUMERIC(3,2),
    rating_count_internal   INTEGER NOT NULL DEFAULT 0,
    last_synced_at          TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_books_first_publish_date ON books (first_publish_date);
CREATE INDEX idx_books_last_synced_at ON books (last_synced_at);
```

### `games`

```sql
CREATE TABLE games (
    id                      BIGSERIAL PRIMARY KEY,
    title                   VARCHAR(500) NOT NULL,
    original_title          VARCHAR(500),
    slug                    VARCHAR(255) NOT NULL UNIQUE,
    overview                TEXT,
    release_date            DATE,
    game_type               VARCHAR(30) NOT NULL,     -- MAIN_GAME, DLC, EXPANSION, ...
    original_language       VARCHAR(10),
    poster_url              VARCHAR(1000),
    backdrop_url            VARCHAR(1000),
    rating_external         NUMERIC(3,1),
    rating_count_external   INTEGER,
    rating_internal         NUMERIC(3,2),
    rating_count_internal   INTEGER NOT NULL DEFAULT 0,
    last_synced_at          TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_games_release_date ON games (release_date);
CREATE INDEX idx_games_game_type ON games (game_type);
CREATE INDEX idx_games_last_synced_at ON games (last_synced_at);
```

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

    CONSTRAINT uq_external_id UNIQUE (source, external_id),
    CONSTRAINT uq_item_source UNIQUE (item_type, item_id, source)
);

CREATE INDEX idx_external_ids_item ON external_ids (item_type, item_id);
```

No real FK to item tables — polymorphic reference, integrity enforced by application code.

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
    role            VARCHAR(50) NOT NULL,           -- DIRECTOR, ACTOR, CREATOR, AUTHOR
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

| Domain  | Roles             | Notes                                      |
|---------|-------------------|--------------------------------------------|
| Movies  | DIRECTOR, ACTOR   | Actors limited to top 10 by billing_order  |
| Series  | CREATOR, ACTOR    | Actors limited to top 10                   |
| Books   | AUTHOR            | Supports co-authorship                     |
| Games   | DIRECTOR          | Only when IGDB provides it                 |

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

## Search

Materialized view used for cross-type full-text search.

```sql
CREATE MATERIALIZED VIEW catalog_search AS
SELECT
    id,
    'MOVIE'         AS item_type,
    title,
    overview,
    poster_url,
    release_date,
    rating_external,
    to_tsvector('simple', title || ' ' || COALESCE(overview, '')) AS search_vector
FROM movies
UNION ALL
SELECT id, 'SERIES', title, overview, poster_url, first_air_date, rating_external,
    to_tsvector('simple', title || ' ' || COALESCE(overview, ''))
FROM series
UNION ALL
SELECT id, 'BOOK', title, overview, poster_url, first_publish_date, rating_external,
    to_tsvector('simple', title || ' ' || COALESCE(overview, ''))
FROM books
UNION ALL
SELECT id, 'GAME', title, overview, poster_url, release_date, rating_external,
    to_tsvector('simple', title || ' ' || COALESCE(overview, ''))
FROM games;

CREATE INDEX idx_catalog_search_vector ON catalog_search USING GIN (search_vector);
CREATE INDEX idx_catalog_search_type ON catalog_search (item_type);
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

-- Apply to: movies, series, books, games, people, companies
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

One row per (user, item): an optional 1-5 `score` and/or optional
`review_text` — either can be null, but the row exists once a user has
rated and/or reviewed an item (upsert on repeat calls). Polymorphic
`item_type` + `item_id`, same pattern as `credits`/`external_ids`; no real
FK to movies/series/books/games.

```sql
CREATE TABLE user_ratings (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_type       VARCHAR(20) NOT NULL,     -- MOVIE, SERIES, BOOK, GAME
    item_id         BIGINT NOT NULL,
    score           INTEGER,                  -- 1-5, nullable (text-only review)
    review_text     TEXT,
    is_hidden       BOOLEAN NOT NULL DEFAULT false, -- content moderation (admin)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_user_rating_item UNIQUE (user_id, item_type, item_id),
    CONSTRAINT ck_user_ratings_score_range CHECK (score IS NULL OR (score >= 1 AND score <= 5))
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
```

`updated_at` is refreshed by the shared `trigger_set_updated_at()` trigger
(defined in migration 0001). The public profile (`GET /users/{username}`)
derives `library_counts` (`COUNT` grouped by `status`, zero-filled) from this
table, and `GET /{type}/{slug}` derives the caller's `viewer_status` from it.

## Notifications

### `notifications`

Social notifications for a recipient user, generated as a side effect of social
events by `backlogg/notifications/service.py`:

- `new_follower` — someone followed the recipient (no target).
- `review_like` — someone liked one of the recipient's reviews
  (`target_type = 'review'`, `target_id` = the `user_ratings.id`).

`actor_id` is who triggered the event, `recipient_id` is who receives it. Both
FK to `users` with `ON DELETE CASCADE`. Generation is deliberately best-effort:
the source operation (the follow / the like) is committed first and any failure
creating the notification is swallowed, so it can never break the follow/like.

```sql
CREATE TABLE notifications (
    id           BIGSERIAL PRIMARY KEY,
    recipient_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    actor_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type         VARCHAR(30) NOT NULL,   -- 'new_follower' | 'review_like'
    target_type  VARCHAR(20),            -- e.g. 'review' (NULL for new_follower)
    target_id    BIGINT,                 -- e.g. user_ratings.id (NULL for new_follower)
    is_read      BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_notifications_type CHECK (type IN ('new_follower', 'review_like'))
);

-- Recipient feed: newest first.
CREATE INDEX idx_notifications_recipient_created
    ON notifications (recipient_id, created_at DESC);
```

## Notes on polymorphic references

`external_ids`, `credits`, `company_credits`, `user_ratings`, `library_entries`,
`notifications` (target_type/target_id) use polymorphic references
(`item_type`/`target_type` + `item_id`/`target_id`) with no real FK. Referential
integrity is enforced at the application layer, typically in the use case that
persists the item.
