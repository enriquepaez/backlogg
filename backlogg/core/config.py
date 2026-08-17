from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://localhost/backlogg"
    TEST_DATABASE_URL: str = "postgresql+asyncpg://localhost/backlogg_test"

    TMDB_API_KEY: str = ""
    TWITCH_CLIENT_ID: str = ""
    TWITCH_CLIENT_SECRET: str = ""

    SEED_TOP_N_MOVIES: int = 100
    SEED_TOP_N_SERIES: int = 100
    SEED_TOP_N_BOOKS: int = 100
    SEED_TOP_N_GAMES: int = 100

    SYNC_SLICE_SIZE: int = 200

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
