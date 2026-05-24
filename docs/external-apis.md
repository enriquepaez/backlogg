# External APIs

## TMDB (Movies & Series)

- **Auth**: API key via header `Authorization: Bearer <TMDB_API_KEY>`
- **Base URL**: `https://api.themoviedb.org/3`
- **Rate limits**: generous free tier, no hard concerns for seed/sync workloads
- **Key endpoints used**:
  - `GET /movie/popular` — seed top-N movies
  - `GET /movie/{tmdb_id}` — movie detail
  - `GET /search/movie?query=` — on-demand fallback search
  - `GET /tv/popular` — seed top-N series
  - `GET /tv/{tmdb_id}` — series detail
  - `GET /search/tv?query=` — on-demand fallback
  - `GET /movie/{tmdb_id}/credits` — cast & crew for credits sync
  - `GET /person/{person_id}` — person detail

- **Slug strategy**: TMDB provides its own `slug` field. Use it directly.
- **external_ids source value**: `TMDB`

## Open Library (Books)

- **Auth**: none required
- **Base URL**: `https://openlibrary.org`
- **Rate limits**: none enforced — suitable for batch sync
- **Key endpoints used**:
  - `GET /search.json?q=&limit=` — seed and on-demand fallback
  - `GET /works/{olid}.json` — work detail (modeled at work level, not edition)

- **Slug strategy**: Open Library uses `/works/OL123W` format. Strip prefix, use `OL123W`
  as slug or derive from title.
- **Coverage note**: strong on classics and public domain; modern titles may have
  incomplete metadata (missing cover, publication date).
- **external_ids source value**: `OPEN_LIBRARY`

## IGDB (Games)

- **Auth**: Twitch client credentials OAuth2. Request token from
  `https://id.twitch.tv/oauth2/token`. Token expires — client must renew automatically.
- **Base URL**: `https://api.igdb.com/v4`
- **Required headers**: `Client-ID: <TWITCH_CLIENT_ID>`, `Authorization: Bearer <access_token>`
- **Query language**: IGDB uses a custom query language (not REST params):
  ```
  POST /games
  Body: fields name,slug,summary,cover.*,first_release_date,rating,rating_count,game_type,platforms.*;
        sort rating desc;
        limit 500;
  ```
- **Rate limits**: 4 requests/second on free tier. Use batching.
- **Key endpoints used**:
  - `POST /games` — seed and on-demand fallback
  - `POST /covers` — cover art
  - `POST /companies` — developer/publisher for company_credits
  - `POST /involved_companies` — join between games and companies

- **Slug strategy**: IGDB provides `slug` field directly.
- **Coverage note**: director data is sparse — only sync when available.
- **external_ids source value**: `IGDB`

## Environment variables

| Variable               | Used by       | Description                                      |
|------------------------|---------------|--------------------------------------------------|
| `DATABASE_URL`         | SQLAlchemy    | PostgreSQL connection string (Neon in production)|
| `TEST_DATABASE_URL`    | pytest        | PostgreSQL DB de test (separada de la de dev)    |
| `TMDB_API_KEY`         | TMDB client   | Bearer token for TMDB API                        |
| `TWITCH_CLIENT_ID`     | IGDB client   | Twitch app client ID                             |
| `TWITCH_CLIENT_SECRET` | IGDB client   | Twitch app client secret                         |
| `SEED_TOP_N_MOVIES`    | Sync job      | How many movies to seed (default: 100)           |
| `SEED_TOP_N_SERIES`    | Sync job      | How many series to seed (default: 100)           |
| `SEED_TOP_N_BOOKS`     | Sync job      | How many books to seed (default: 100)            |
| `SEED_TOP_N_GAMES`     | Sync job      | How many games to seed (default: 100)            |
| `SYNC_CRON`            | APScheduler   | Cron expression for nightly sync (default: `0 2 * * *`) |
