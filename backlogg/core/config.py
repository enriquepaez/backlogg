from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://localhost/backlogg"
    TEST_DATABASE_URL: str = "postgresql+asyncpg://localhost/backlogg_test"

    TMDB_API_KEY: str = ""
    TWITCH_CLIENT_ID: str = ""
    TWITCH_CLIENT_SECRET: str = ""

    # Ranking-walk target per type: how many items of the external API's
    # popular listing one full cursor cycle covers before wrapping to 0.
    #
    # ⚠️ Since feature 86 SEED_TOP_N_MOVIES and SEED_TOP_N_SERIES are INERT.
    # Movies and series are no longer enumerated by walking /movie/popular and
    # /tv/popular: their catalog is defined by a *quality threshold*
    # (TMDB_SEED_MIN_VOTES_*) and enumerated with /discover into the
    # ``seed_targets`` table, so there is no item-count cutoff left to
    # configure and no cursor left to wrap. They are kept (rather than
    # deleted) because they are still set as environment variables on Render
    # and in .github/workflows/backfill-sync.yml, and removing a name that
    # deployments export would break nothing but read as an accident.
    #
    # ⚠️ Since feature 87 SEED_TOP_N_BOOKS is inert for the *seeding* path too:
    # scripts/seed_openlibrary_books.py selects the book catalog from the
    # monthly Open Library dumps by the BOOKS_SEED_MIN_* thresholds below, with
    # no item-count cutoff. It stays live for the *cursor* path — sync_books
    # and scripts/backfill_sync.py book still page search.json and wrap on it.
    # SEED_TOP_N_GAMES is fully live: games are unchanged.
    # See docs/seeding-plan.md §3 and docs/operations.md.
    SEED_TOP_N_MOVIES: int = 100
    SEED_TOP_N_SERIES: int = 100
    SEED_TOP_N_BOOKS: int = 100
    SEED_TOP_N_GAMES: int = 100

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
    # fetch actually resolved (item written, or 404): a network failure leaves
    # the counter alone and is retried for free, so a TMDB outage can never
    # retire a healthy target.
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

    # Quality thresholds for the Open Library book catalog (feature 73). The
    # language fragments live in backlogg/books/constants.py — only the
    # tunable numbers are env vars. Defaults are the calibrated values
    # documented in docs/external-apis.md: they select 17.015 English +
    # 1.859 Spanish works = 18.874, which IS the size of the book catalog.
    #
    # ⚠️ That is 189x the default SEED_TOP_N_BOOKS of 100 but *below* any
    # realistic target, so the old wording here ("comfortably above
    # SEED_TOP_N_BOOKS") was only ever true against the default and is gone.
    # Since feature 87 SEED_TOP_N_BOOKS is INERT for the seeding path: books
    # are seeded from the monthly dumps by scripts/seed_openlibrary_books.py,
    # which selects by these thresholds and has no item-count cutoff and no
    # cursor to wrap — exactly what happened to SEED_TOP_N_MOVIES/_SERIES in
    # feature 86. It is still LIVE for the cursor path: sync_books (the
    # nightly job) and scripts/backfill_sync.py book still walk search.json
    # by offset and use it as their wraparound target.
    #
    # These same thresholds drive both paths, so the two agree on which works
    # belong in the catalog; only the transport differs. One caveat for the
    # cursor path: production sets SEED_TOP_N_BOOKS to 10.000, which is *below*
    # the 18.874 the filter actually yields, so the cursor wraps before covering
    # the catalog. Irrelevant to the dump path, flagged in docs/operations.md.
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
    # BOOKS_SEED_ES_EVERY_N interleaves one Spanish work every N slots of the
    # global cursor (10 ≈ the 1.858/18.817 share of the pool), so Spanish
    # titles show up from the very first slice instead of after the English
    # stream runs out.
    BOOKS_SEED_MIN_READINGLOG: int = 20
    BOOKS_SEED_MIN_READINGLOG_ES: int = 5
    BOOKS_SEED_MIN_PAGES: int = 100
    BOOKS_SEED_MIN_EDITIONS: int = 10
    BOOKS_SEED_MIN_EDITIONS_ES: int = 2
    BOOKS_SEED_ES_EVERY_N: int = 10

    # Nightly slice size. SYNC_SLICE_SIZE is the global fallback; the four
    # per-type overrides exist because the types have genuinely different
    # needs (feature 84, docs/seeding-plan.md §2.3): TMDB forbids caching its
    # data for more than 6 months, so 57.135 movies have to be re-synced every
    # 180 days = ~318/night, while series only need ~61. Resolution order in
    # _read_slice is: explicit argument -> per-type setting -> global.
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


settings = Settings()
