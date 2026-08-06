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

    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 10080


settings = Settings()
