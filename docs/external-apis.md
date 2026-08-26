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
  - `GET /search.json?q=*:*&sort=readinglog&offset=&limit=` — seed/nightly sync popular books
  - `GET /search.json?title=&limit=` — on-demand fallback search
  - `GET /works/{olid}.json` — work detail (modeled at work level, not edition)

- **Popular-books strategy**: the sync uses `search.json` with a Solr match-all query
  (`q=*:*`, 43M+ works indexed) sorted by `readinglog` — the count of users who shelved
  the work as want-to-read/reading/read — with native `offset`/`limit` pagination
  (verified up to offset 9900). Do **not** use:
  - `/trending/weekly.json` — capped at a few hundred entries, catalog cannot grow
  - `sort=rating` — surfaces obscure books with very few ratings
  - `sort=edition_count` — does not exist (returns HTTP 500)

  Request the field set `key,title,author_name,first_publish_year,cover_i,subject,isbn`
  (the shape `book_to_dict` consumes).
- **Slug strategy**: Open Library uses `/works/OL123W` format. Strip prefix, use `OL123W`
  as slug or derive from title.
- **Coverage note**: strong on classics and public domain; modern titles may have
  incomplete metadata (missing cover, publication date).
- **external_ids source value**: `OPEN_LIBRARY`
- **"Similar books" investigation (2026-08-16)**: no free/no-auth external API
  covers a "similar books" use case at the volume this project needs. Open
  Library exposes no related-works/recommendations endpoint. Google Books
  caps free usage at 100 requests/day (unworkable for on-demand fallback at
  catalog scale). Dedicated "find similar books" services require a paid API
  key. Conclusion: `GET /books/{slug}/similar` (feature 46) is computed
  entirely from local data (same author via `credits`, then genre overlap,
  then `rating_external`) instead of a new external dependency.
- **"Trending" investigation (2026-08-26, feature 68)**: Open Library has no
  "trending this week/day" endpoint (`/trending/weekly.json` exists but is
  capped at a few hundred entries and unrelated to what the catalog needs —
  see the popular-books note above, same reasoning applies). `GET
  /trending?type=book` is therefore computed entirely from local data: the
  same `rating_internal DESC NULLS LAST, rating_external DESC NULLS LAST`
  order already used by `GET /books` (feature 66), over items already
  persisted — no Open Library call happens for this endpoint. `period` is
  accepted but has no effect (no time-windowed signal exists to apply it to).

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
  - `POST /games` — seed and on-demand fallback. The single-game detail query
    (`get_game_by_slug`) also requests `similar_games.*` — IGDB's own curated
    "similar games" relation (id, name, slug, ...), used by
    `GET /games/{slug}/similar` (feature 45) instead of a local genre-overlap
    heuristic.
  - **Category allowlist** (feature 65): `get_top_games`'s query filters
    `game_type = (0,1,2,4,6,7,8,9)` — the 8 allowed IGDB categories, defined
    once in `backlogg/games/constants.py`. The other three ingestion paths
    (`get_game_by_slug`/`get_similar_games` in `backlogg/games/service.py`
    and `_ingest_games` in `backlogg/search/service.py`) cannot filter at the
    IGDB query level (single-slug lookups, or IGDB's free-text `search`
    endpoint has no `where` clause) so they check the mapped `game_type`
    against the same allowlist after `game_to_dict` and skip persisting
    (`upsert_game`) anything outside it. See `docs/schema.md`'s "Category
    allowlist" note for the full list and the excluded categories.
  - `POST /covers` — cover art
  - `POST /companies` — developer/publisher for company_credits
  - `POST /involved_companies` — join between games and companies

- **Slug strategy**: IGDB provides `slug` field directly.
- **Coverage note**: director data is sparse — only sync when available.
- **external_ids source value**: `IGDB`
- **"Trending" investigation (2026-08-26, feature 68)**: IGDB has no
  "trending this week/day" endpoint. `GET /trending?type=game` is therefore
  computed entirely from local data — same heuristic as `type=book` (see
  Open Library's "Trending" note above): `rating_internal DESC NULLS LAST,
  rating_external DESC NULLS LAST` order already used by `GET /games`
  (feature 66), over items already persisted. No IGDB call happens for this
  endpoint, and `period` is accepted but has no effect.

## SMTP (Email) — feature 36 `account_recovery`

- **Transporte**: SMTP genérico vía la stdlib (`smtplib` +
  `email.message.EmailMessage`), sin dependencias externas.
- **Uso**: emails transaccionales de verificación de cuenta y reset de password.
- **Flujo**: `smtplib.SMTP(host, port)` → `starttls()` si `SMTP_STARTTLS` →
  `login(user, pass)` si hay credenciales → `send_message` (text + HTML
  alternativo). Envío síncrono ejecutado en un thread (`asyncio.to_thread`).
- **Aislamiento**: detrás de una interfaz `EmailSender`. Con `SMTP_HOST`
  presente envía vía SMTP; sin él, un fallback loguea el enlace y no envía —
  así dev y CI arrancan sin servidor de correo.
- **Pruebas**: Gmail con App Password (2FA; `smtp.gmail.com:587` STARTTLS;
  remitente = tu gmail; ~500 envíos/día). Producción con dominio propio: solo
  cambian las variables `SMTP_*`.
- **Seguridad**: `SMTP_PASSWORD` es secret — nunca en logs ni en respuestas de error.

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
| `SYNC_SLICE_SIZE`      | Sync job      | Max items per sync run and type (default: 200)   |

### Roadmap — variables planificadas (features 35-40)

Aún no leídas por el código; se añaden cuando se implemente cada feature.

| Variable                              | Feature | Description                                                        |
|---------------------------------------|---------|-------------------------------------------------------------------|
| `SMTP_HOST`                           | 36      | Host SMTP; vacío → `EmailSender` cae a log (no envía)             |
| `SMTP_PORT`                           | 36      | Puerto SMTP (default 587, STARTTLS)                               |
| `SMTP_USERNAME` / `SMTP_PASSWORD`     | 36      | Credenciales SMTP; `SMTP_PASSWORD` es secret (nunca en logs)      |
| `SMTP_FROM_EMAIL`                     | 36      | Dirección remitente del email                                    |
| `SMTP_STARTTLS`                       | 36      | Usar STARTTLS antes del login/envío (default true)               |
| `APP_BASE_URL`                        | 36      | Base para construir los enlaces de verificación/reset             |
| `REFRESH_EXPIRE_DAYS`                 | 35      | Vida del refresh token (el access `JWT_EXPIRE_MINUTES` pasa a corto)|
| `RATE_LIMIT_AUTH` / `RATE_LIMIT_DEFAULT` | 37   | Límites de peticiones por ventana (auth y general)                |
| `SENTRY_DSN`                          | 38      | DSN de Sentry; ausente = integración desactivada, sin overhead    |
| `LOG_LEVEL`                           | 38      | Nivel del logging estructurado (default `INFO`)                   |
