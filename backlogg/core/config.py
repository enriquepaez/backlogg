from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://localhost/backlogg"
    TEST_DATABASE_URL: str = "postgresql+asyncpg://localhost/backlogg_test"

    TMDB_API_KEY: str = ""
    TWITCH_CLIENT_ID: str = ""
    TWITCH_CLIENT_SECRET: str = ""

    # TMDB catalog definition (feature 86, docs/seeding-plan.md §1 and §3).
    # The catalog is defined by a vote_count threshold, not by a number of
    # items: popularity rank is a measure of *recent interest*, and 30% of the
    # movies ranked 20.000-40.000 still have >=50 votes, so cutting by rank
    # throws away thousands of legitimately known titles while letting in
    # regional theatre recordings. 25 is the value agreed with the user and it
    # yields 57.135 movies and 10.880 series (exact total_results measured
    # against /discover on 2026-09-02). Per type because the two catalogs have
    # very different sizes and could need independent recalibration; measured
    # alternatives are tabulated in docs/seeding-plan.md §2.1.
    TMDB_SEED_MIN_VOTES_MOVIES: int = 25
    TMDB_SEED_MIN_VOTES_SERIES: int = 25

    # Release-year range the /discover enumeration slices over. 1874 is the
    # oldest release year TMDB carries; the end of the range defaults to the
    # current year plus one (there are already-dated future releases in TMDB)
    # when TMDB_SEED_END_YEAR is left unset.
    TMDB_SEED_START_YEAR: int = 1874
    TMDB_SEED_END_YEAR: int | None = None

    # Fan-out width for the TMDB seeding calls (enumeration pages and item
    # hydration alike), as asyncio.gather + Semaphore. TMDB documents ~50
    # req/s and docs/seeding-plan.md §4 says to stay at 30-40: with the ~250 ms
    # round trip TMDB averages, 8 in-flight requests land at ~32 req/s.
    TMDB_SEED_CONCURRENCY: int = 8

    # How many *conclusive* hydration passes a seed target gets before it is
    # retired from the work list as unlinkable.  A pass counts only when the
    # fetch actually resolved (item written, or the source reporting the id
    # gone): a network failure leaves the counter alone and is retried for
    # free, so an outage can never retire a healthy target.
    #
    # The TMDB_ prefix is historical: since feature 90 this single knob governs
    # every target-driven type, games included. It was deliberately not renamed
    # because it is exported on Render, and a renamed variable does not fail —
    # it silently falls back to the default.
    #
    # This exists because a target can be *permanently* unlinkable through no
    # fault of the seeding: the detail request resolves and the item still ends
    # up with no ``external_ids`` row — two TMDB ids whose title and year
    # slugify to the same value share a single row and only one of them keeps
    # its link, for instance.  (Until migration 0036 there was a far more
    # common shape: ``uq_external_id`` had no ``item_type``, so a PERSON id
    # blocked the movie or series holding the same number — issue #20.)
    # Without retirement those targets
    # would sit in the pending set forever, occupying a slot of every nightly
    # slice, keeping ``pending`` permanently above 0 — which would silently
    # disable the ``last_synced_at`` refresh rotation (and with it TMDB's
    # 6-month cache-window obligation) and stop the backfill loop from ever
    # terminating.  Retired targets are not forgotten: they are reported
    # separately as ``stuck``.  3 rather than 1 so an unforeseen transient
    # costs three slice slots once instead of a target forever.
    TMDB_SEED_MAX_ATTEMPTS: int = 3

    # ── TMDB incremental updates (feature 88, docs/seeding-plan.md §6) ───────
    #
    # The release gate for ids that arrive from the daily id export. They have
    # no vote_count yet — that is the whole reason this route exists — so the
    # bar is the release date instead: an item is admitted when it is a recent
    # or imminent release, not when it is merely a new *id*. TMDB creates
    # around a thousand ids a day and most of them are catalogue backfill of
    # old, obscure titles; those keep entering the way they always have, through
    # the vote_count threshold, once they earn an audience.
    #
    # 90 days back: wide enough that a run down for a fortnight still catches
    # everything it missed (the export files themselves are only kept 3 months),
    # narrow enough that "recently released" is still true.
    TMDB_INCREMENTAL_MAX_AGE_DAYS: int = 90
    # 180 days ahead: TMDB carries dated announcements years out, and a film
    # dated 2031 is not a release, it is a plan. Half a year is roughly the
    # marketing window in which an upcoming title is worth having on a page.
    TMDB_INCREMENTAL_HORIZON_DAYS: int = 180

    # How stale the last processed export may be before the "what appeared"
    # diff is abandoned for this run and the baseline is reset to today's file.
    # The diff needs *two* files; with a gap of N days the older one still
    # exists (retention is 3 months) but the diff then covers N days of
    # appearances at once, which is N times the detail requests. Seven days is
    # the point where re-baselining and letting the promotion sweep pick up the
    # stragglers is cheaper than a run that takes hours. Reported, never silent.
    TMDB_INCREMENTAL_MAX_EXPORT_GAP_DAYS: int = 7

    # How many recent release years the promotion sweep re-enumerates through
    # /discover. This is the route for items that were below the threshold when
    # the catalog was seeded and have crossed it since — without it a 2019 film
    # that gains traction in 2027 would never enter. Ten years rather than two
    # or three because that is the timescale on which a film actually
    # accumulates its first 25 votes; older than that, the full enumeration
    # (scripts/seed_tmdb_targets.py) is still the tool.
    TMDB_PROMOTION_YEARS: int = 10

    # ── IGDB incremental updates (feature 88, docs/seeding-plan.md §6) ───────
    #
    # IGDB needs no export file and no changes endpoint: `where created_at > X`
    # and `where updated_at > X` answer both questions in its own query
    # language. What it does need is a bound on the first run and a bound per
    # run, because "> 0" would be the whole database.
    #
    # Cold start: with no watermark, ask for the last week instead of
    # everything. Bounded, immediately useful, and it converges on the second
    # run — unlike TMDB's daily export, whose diff needs two files and
    # therefore cannot admit anything at all on its first pass.
    IGDB_INCREMENTAL_LOOKBACK_DAYS: int = 7
    # Ceiling per lane per run. IGDB caps a response at 500 games and allows
    # 4 req/s, so 2.000 games is four requests and about a second of throttle.
    # Hitting the ceiling is not a loss: the query is sorted ascending and the
    # watermark advances to the newest record actually seen, so the next run
    # starts exactly where this one stopped.
    IGDB_INCREMENTAL_MAX_ITEMS: int = 2000

    # Wikidata SPARQL volcado (feature 79). Wall-clock ceiling per pass, in
    # minutes. The endpoint is free and CC0 but slow and politely rate-limited
    # (1 req/s here), so a cold anchor pass over the whole catalog is hours of
    # wall clock. The job stops itself on its own terms instead of being killed
    # by the Actions timeout: the cursor, the counters and the coverage report
    # survive, and the next dispatch continues where it stopped. 0 disables it.
    WIKIDATA_SYNC_TIME_BUDGET_MINUTES: float = 300.0

    # ── Semantic layer: embeddings + pgvector (feature 75) ───────────────────
    #
    # The model runs on the GitHub Actions runner, never on Render and never on
    # the request path (backlogg/recommendations/adapters/local_embedder.py).
    # It is a *local* model on purpose: an embeddings API costs money and this
    # project runs on free tiers, while a runner has CPU, RAM and disk to spare
    # for free.
    #
    # intfloat/multilingual-e5-small: MIT, 100+ languages, 384 native
    # dimensions and — the deciding factor over
    # paraphrase-multilingual-MiniLM-L12-v2, which is otherwise the canonical
    # symmetric-similarity model at this size — a 512-token window instead of
    # 128. Synopses routinely run past 128 tokens, and truncating there would
    # cut most of them mid-plot.
    EMBEDDING_MODEL: str = "intfloat/multilingual-e5-small"
    # E5 models are trained with a task prefix and degrade measurably without
    # one. "query: " on *both* sides is what the model card prescribes for
    # symmetric similarity, which is exactly what /similar is.
    EMBEDDING_TEXT_PREFIX: str = "query: "
    # 384 is the model's native dimensionality. It is an env var because the
    # acceptance list asks for it, not because it is routinely tuned: the
    # migration bakes this number into the halfvec column, so changing it after
    # migrating needs an ALTER (docs/operations.md). Never truncate a
    # non-Matryoshka model to save disk — shrink EMBEDDING_MAX_ITEMS instead,
    # which costs coverage rather than quality (progress/history.md, 75).
    EMBEDDING_DIM: int = 384

    # The hard cap on how many items carry a vector, and the reason this
    # feature is "a subset" and not "the catalog". Neon free is 512 MB per
    # project and the full catalog is projected at 444-488 MB (issue #28), so
    # the headroom is ~80-120 MB.
    #
    # MEASURED (2026-09-15, 35.215 real rows): 2.262 bytes per item, so 40.000
    # items cost 86-90 MB. That fits — but AT THE BOTTOM of the headroom, not
    # with room to spare, and the planning estimate it replaces (~67 MB) was
    # 30% low. So this default is a starting point, not a safe value
    # everywhere: measure the real headroom before the first generation in
    # production and size the cap to it. The pre-check, the rule of thumb and
    # the full breakdown are in docs/operations.md § "Disco: la restricción que
    # manda, medida". 100.000 items do not fit in any format.
    #
    # Overrunning does not fail a test. It fails the nightly sync the day Neon
    # refuses a write — hence the ERROR the job logs past 120 MB.
    EMBEDDING_MAX_ITEMS: int = 40000
    # Per-type overrides. Left at None the cap is split **equally** between the
    # four types, with any share a type cannot fill handed back to the others
    # (backlogg/recommendations/embeddings.py::allocate_quotas). Equal and not
    # proportional to catalog size: feature 80's cross-type quota needs depth
    # in every type, and a proportional split would give movies half the budget
    # and the smallest type almost nothing — the exact failure this cap is
    # supposed to avoid.
    EMBEDDING_MAX_ITEMS_MOVIES: int | None = None
    EMBEDDING_MAX_ITEMS_SERIES: int | None = None
    EMBEDDING_MAX_ITEMS_BOOKS: int | None = None
    EMBEDDING_MAX_ITEMS_GAMES: int | None = None

    # How many items are serialised, embedded and upserted per transaction.
    # Bigger batches amortise the model's fixed per-call cost; smaller ones
    # lose less work when a run is cut short. 256 is roughly one second of CPU
    # inference on a runner.
    EMBEDDING_BATCH_SIZE: int = 256
    # Wall-clock ceiling for the whole run, in minutes, same contract as the
    # Wikidata job: the run stops itself instead of being killed by the Actions
    # timeout, and because unchanged items are skipped, the next dispatch
    # resumes where this one stopped. 0 disables it.
    EMBEDDING_TIME_BUDGET_MINUTES: float = 300.0

    # ── The /similar ranker (feature 80) ─────────────────────────────────────
    #
    # THE SWITCH THAT DECIDES WHETHER /similar IS CROSS-TYPE AT ALL.
    #
    # > 0: how many of the 10 results are RESERVED for a type other than the
    #      item in the URL. The plan asks for 3
    #      (docs/recommendations-plan.md § El ranker) because cosine on its own
    #      returns the anchor's own type almost every time: items of one type
    #      share vocabulary ("season", "player", "novel") and that dominates
    #      the metric, so without a reserved quota the cross-media bridge this
    #      product is built on rarely reaches the user.
    #
    #   0: the endpoint NEVER returns an item of another type. Not "reserves
    #      nothing" — never: the query itself is narrowed to the anchor's own
    #      type (recommendations/similar.py::_neighbours).
    #
    # That second line is the whole point of the default and it had to be made
    # true rather than assumed. Reserving zero slots is NOT the same as
    # returning none: an unfiltered cosine top-N hands back the other types
    # whenever they genuinely win, and measured on the real development catalog
    # that was 63% of the rows of a film's page — including 7 of the 10
    # neighbours of The Return of the King.
    #
    # Why 0 ships: apps/web/src/components/item-similar.tsx links every result
    # to /{type-of-the-page}/{slug}, so ONE book among films is a 404 in
    # production — the exact shape of issues #32, #33 and #36 — and Render
    # deploys main on merge. The behaviour is implemented and tested at any
    # value; what is deferred is switching it on. FE-67 raises this to 3 in the
    # same PR that renders the type badge. See docs/api.md § Movies.
    SIMILAR_CROSS_TYPE_QUOTA: int = 0
    # How much a candidate is demoted for each group (same creator, same
    # franchise) already taken above it: score *= (1 - penalty) per repetition.
    # 0.25 lets a saga keep the top slot it earned and then yield the next ones
    # — ten entries of one franchise are not ten recommendations. 0 disables
    # the re-rank and leaves raw cosine order.
    SIMILAR_DIVERSITY_PENALTY: float = 0.25
    # How many neighbours are pulled from the HNSW index per result served.
    # The index walk is cheap and the ranker needs room to demote duplicates
    # and to reach a fourth type; over-fetching is also what makes a *filtered*
    # ANN query (item_types=...) come back full instead of short.
    SIMILAR_CANDIDATE_MULTIPLIER: int = 6
    # pgvector's HNSW candidate window (hnsw.ef_search) for the queries that
    # are NARROWED BY TYPE. It is not touched on any other read.
    #
    # Both narrowed queries pass it, in both directions:
    #   - quota = 0 → the main query is narrowed to the anchor's OWN type;
    #   - quota > 0 → the second query is narrowed to the OTHER THREE types.
    #
    # It is here because item_types is a POST-FILTER: when the planner uses the
    # HNSW index it produces ef_search candidates and only then is the type
    # kept, so if the wanted type is a small share of the index the answer is
    # not "fewer rows", it is NO ROWS.
    #
    # MEASURED on the development catalog — 35.215 vectors, of which 33.062 are
    # games, 1.157 series, 605 movies and 391 books — asking for 60 neighbours:
    #
    #   non-GAME neighbours of a game — the quota>0 path, 6% of the index:
    #     ef_search=40 (pgvector default) →  0 rows,  28 ms
    #     ef_search=200                   →  0 rows,   4 ms
    #     ef_search=400                   →  1 row,    6 ms
    #     ef_search=800                   → 60 rows,   4 ms
    #     ef_search=1000 (pgvector max)   → 60 rows,   3 ms
    #
    #   GAME neighbours of a game — the quota=0 path on the majority type:
    #     ef_search=40 (pgvector default) → 39 rows,   4 ms
    #     ef_search=200                   → 60 rows,   9 ms
    #     ef_search=1000                  → 60 rows,  15 ms
    #
    # The curve is a cliff, not a slope, so the value sits at the ceiling:
    # widening the window costs a few milliseconds inside one index, while
    # landing under the cliff costs the whole cross-type feature.
    #
    # The quota=0 path on a MINORITY type never needs it, and that is a
    # property of the planner rather than of this value: narrowing to MOVIE
    # (1,7% of the index) or BOOK (1,1%) is selective enough that Postgres
    # drops the HNSW index and answers from the b-tree of uq_item_embedding
    # with an exact top-N sort — 60/60 rows in ~3 ms at any ef_search,
    # verified with EXPLAIN ANALYZE. Exact beats approximate on a few hundred
    # rows. The setting is passed anyway: which plan wins depends on the row
    # counts of the day, and the cost of being wrong is a half-empty carousel.
    #
    # In production the split is far less skewed — EMBEDDING_MAX_ITEMS_* gives
    # each type an equal quota — so this is sized for the worst case, not the
    # expected one.
    SIMILAR_FILTERED_EF_SEARCH: int = 1000

    # Quality thresholds for the Open Library book catalog (feature 73). The
    # language fragments live in backlogg/books/constants.py — only the
    # tunable numbers are env vars. Defaults are the calibrated values
    # documented in docs/external-apis.md: they select 17.015 English +
    # 1.859 Spanish works = 18.874, which IS the size of the book catalog.
    # There is no item-count cutoff anywhere on the book path: the thresholds
    # below are the whole definition of which works belong in the catalog, and
    # scripts/seed_openlibrary_books.py applies them to the monthly dumps
    # (backlogg/books/adapters/openlibrary_dump.py::select_language).
    #
    # BOOKS_SEED_MIN_READINGLOG applies to the English stream and
    # BOOKS_SEED_MIN_READINGLOG_ES to the Spanish one: the shelving signal is
    # ~10x weaker in Spanish, so a shared threshold would seed zero Spanish
    # works. BOOKS_SEED_MIN_EDITIONS / _ES are the notoriety filter: how many
    # editions the work has been published in. It is what separates a loose
    # comic instalment (Ultimate Spider-Man Vol. 6, 3 editions) from a
    # canonical graphic novel (Bone 11, Death Note 12, Watchmen 43) — no
    # classification clause can, and none is queryable in Solr anyway. The
    # Spanish floor is 2 and not 3 on purpose: Reina roja has exactly 2.
    BOOKS_SEED_MIN_READINGLOG: int = 20
    BOOKS_SEED_MIN_READINGLOG_ES: int = 5
    BOOKS_SEED_MIN_PAGES: int = 100
    BOOKS_SEED_MIN_EDITIONS: int = 10
    BOOKS_SEED_MIN_EDITIONS_ES: int = 2

    # Nightly slice size. SYNC_SLICE_SIZE is the global fallback; the four
    # per-type overrides exist because the types have genuinely different
    # needs (feature 84, docs/seeding-plan.md §2.3): TMDB forbids caching its
    # data for more than 6 months, so 57.135 movies have to be re-synced every
    # 180 days = ~318/night, while series only need ~61. Resolution order in
    # _resolve_slice_size is: explicit argument -> per-type setting -> global.
    # All four default to None so this release changes nothing in production;
    # raising them is a configuration decision for the seeding features.
    SYNC_SLICE_SIZE: int = 200
    SYNC_SLICE_SIZE_MOVIES: int | None = None
    SYNC_SLICE_SIZE_SERIES: int | None = None
    SYNC_SLICE_SIZE_BOOKS: int | None = None
    SYNC_SLICE_SIZE_GAMES: int | None = None

    # How many items one batch of the bulk write path (feature 84) covers.
    # Each batch is a single transaction: bigger means fewer round trips,
    # smaller means less work lost if a batch has to fall back to the
    # per-item route.
    BULK_LOAD_BATCH_SIZE: int = 500

    SYNC_CRON: str = "0 3 * * *"

    ADMIN_API_KEY: str = ""

    # S3-compatible object storage, used to store user avatar uploads. When
    # neither R2_ENDPOINT_URL nor R2_ACCOUNT_ID (or any of the other R2_* vars)
    # is set, the avatar upload/delete endpoints return a controlled 503
    # instead of failing with an unconfigured client. R2_PUBLIC_BASE_URL has
    # no trailing slash.
    #
    # R2_ENDPOINT_URL overrides the endpoint the boto3 client points at. Left
    # empty, it defaults to real Cloudflare R2 built from R2_ACCOUNT_ID. Set
    # it to point at MinIO in dev (http://localhost:9000) or Supabase Storage
    # in prod (https://<project-ref>.supabase.co/storage/v1/s3) — any
    # S3-compatible provider. See backlogg/users/adapters/r2_storage.py.
    R2_ENDPOINT_URL: str = ""
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = ""
    R2_PUBLIC_BASE_URL: str = ""

    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    # Short-lived access token (minutes). Long-lived sessions are handled by
    # the persisted, rotating refresh token instead of a long-lived JWT.
    JWT_EXPIRE_MINUTES: int = 15
    REFRESH_EXPIRE_DAYS: int = 30

    # Account recovery (email verification + password reset).
    # When SMTP_HOST is empty the EmailSender falls back to logging the link
    # instead of sending — the app still boots and works in dev.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "no-reply@backlogg.local"
    SMTP_STARTTLS: bool = True
    APP_BASE_URL: str = "http://localhost:8000"

    # One-time recovery token lifetimes.
    EMAIL_VERIFY_EXPIRE_HOURS: int = 24
    PASSWORD_RESET_EXPIRE_HOURS: int = 1

    # Rate limiting. Format is "count/seconds" (e.g. "10/60" = 10 hits per 60s).
    # Defaults are deliberately generous so normal traffic and the test suite
    # never trip them by accumulation.
    RATE_LIMIT_AUTH: str = "10/60"
    RATE_LIMIT_DEFAULT: str = "120/60"
    RATE_LIMIT_SEARCH_FALLBACK: str = "20/60"

    # Observability. Structured JSON logging at LOG_LEVEL; Sentry is only
    # initialised when SENTRY_DSN is non-empty (absent = off, zero overhead).
    LOG_LEVEL: str = "INFO"
    SENTRY_DSN: str = ""

    # Response caching. Cache-Control max-age (seconds) emitted for public,
    # shared-cacheable reads: detail reads and catalog listings. Plus the TTL of
    # the in-process response cache backing the expensive /trending and /genres
    # reads. The cache lives behind a swappable interface (core/cache.py) so it
    # can move to Redis later without touching any call site.
    CACHE_CONTROL_DETAIL_MAX_AGE: int = 300
    CACHE_CONTROL_LISTING_MAX_AGE: int = 60
    CACHE_TTL_TRENDING: int = 900
    CACHE_TTL_GENRES: int = 300

    # Trending (feature 81). /trending ranks by the platform's own recent
    # activity, so each content type needs a minimum amount of it before the
    # ranking means anything. The threshold is applied **per item type**, not
    # globally: a type with fewer than this many activity gestures inside the
    # period's window falls back to the catalog's canonical order restricted to
    # recent releases. Low on purpose — the point is to stop ranking off a
    # single click, not to wait for a crowd.
    TRENDING_MIN_ACTIVITY: int = 5

    # Second half of the same gate (issue #35). The gesture count alone is a
    # proxy for "there is a community here", and it is a good one only when the
    # community exists: a single account rating five different items crosses
    # TRENDING_MIN_ACTIVITY on its own, with five perfectly legitimate
    # gestures, and then owns the whole type. So the local signal also needs a
    # minimum number of **distinct people** behind it, counted over the same
    # de-duplicated, moderation-filtered gestures that feed the score. Both
    # conditions must hold; either one failing falls the type back to the
    # catalog. Also per type.
    TRENDING_MIN_USERS: int = 3


settings = Settings()
