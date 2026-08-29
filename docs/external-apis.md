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
- **Clasificación y calidad de catálogo (investigación 2026-08-29)**: los dos
  problemas observados en producción —géneros basura y catálogo basura— **no
  requieren cambiar de proveedor**. Ambos se resuelven dentro de Open Library.

  **Géneros.** El adaptador pide hoy solo `subject`, que es el peor campo
  disponible: una folksonomía sin control, con **media de 40 subjects por
  obra** (de ahí las 510 etiquetas distintas con solo 370 libros ingeridos, 397
  de ellas usadas una sola vez). `search.json` expone además tres campos que el
  adaptador no pide. Cobertura medida sobre las 200 obras más estanteadas:

  | Campo | Cobertura | Naturaleza |
  |---|---|---|
  | `lcc` (Library of Congress) | 89 % | Taxonomía controlada y jerárquica |
  | `ddc` (Dewey Decimal) | 78 % | Taxonomía controlada y jerárquica |
  | `subject_facet` | 99 % | Más limpio que `subject`, aún folksonómico |
  | `subject` (el que se usa hoy) | 99 % | Sin control, ~40 por obra |

  Subjects en formato BISAC (`BUSINESS & ECONOMICS / ...`): solo **17 %** — no
  sirven como taxonomía de respaldo.

  **Uso recomendado, y su límite.** DDC y LCC clasifican por **disciplina y
  procedencia, no por género tal y como lo entiende un lector**: `813.6` es
  "ficción estadounidense contemporánea", así que *It Ends With Us* y *It* de
  Stephen King comparten clasificación. Por tanto:
  - `ddc`/`lcc` → eje **grueso y limpio** (ficción vs ensayo, literatura vs
    psicología vs historia). Excelente para descartar ruido y para filtrar.
  - Género de cara al lector (fantasía, terror, romance) → `subject_facet`
    normalizado + mapeo manual de la cabeza + embeddings para la cola
    (ver `docs/recommendations-plan.md`).

  Adoptar `ddc`/`lcc` permite además **eliminar `_is_clean_genre`**
  (`backlogg/books/adapters/open_library.py`), la heurística de longitud,
  paréntesis y comas que hoy intenta arreglar aguas abajo un problema que se
  resuelve en el origen eligiendo otro campo.

  **Calidad del catálogo.** `q=*:*&sort=readinglog` devuelve lo que más gente
  estantea en Open Library, que es autoayuda y BookTok — *Atomic Habits*,
  *The 48 Laws of Power*, *It Ends With Us*. No es un fallo de la API: es lo
  que esa señal mide. La query Solr admite filtros que lo corrigen. Verificado
  en vivo:

  ```
  q=ddc:8* AND language:eng AND readinglog_count:[2000 TO *]&sort=readinglog
  → Harry Potter, A Game of Thrones, It, The Alchemist, The Love Hypothesis
  ```

  Palancas disponibles: `ddc:8*` (solo literatura), `language`,
  `readinglog_count`, `ratings_count`, `first_publish_year`,
  `number_of_pages_median` (descarta folletos). Es el equivalente para libros
  del **category allowlist de `game_type`** (feature 65) en juegos.

  Pendiente de calibrar: el filtro estricto del ejemplo devuelve solo 97
  resultados. Hay que ajustar umbrales para alcanzar `SEED_TOP_N_BOOKS` sin
  reintroducir ruido, e incluir castellano además de inglés (la app es
  bilingüe). Es trabajo de calibración, no de arquitectura.

- **Alternativas evaluadas y descartadas (2026-08-29)**: Open Library sigue
  siendo la fuente correcta, y es además la única de las cuatro verticales sin
  problema de licencia comercial (CC0).

  | Fuente | Por qué se descarta |
  |---|---|
  | Google Books | 1.000 peticiones/día: un backfill de 10.000 libros son 10 días de cuota. Sus términos advierten de que no es un sustituto de servicios comerciales |
  | ISBNdb | 15–300 $/mes, y es **centrado en ISBN/ediciones**, no en obras: choca con el modelo work-level del catálogo. Reintroduce una dependencia de pago justo cuando la migración busca lo contrario |
  | Hardcover | GraphQL gratis, pero es **un competidor directo** (tracker de libros) y parte de sus datos vienen de Open Library y Google Books. Frágil como backbone |
  | BookBrainz | CC0 y bien modelado, pero cobertura demasiado pequeña |
  | Goodreads | API retirada en 2020 |
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

## TheTVDB v4 (Movies & Series) — DESTINO de la migración, features 72-74

> Aún **no implementado**. Sustituye a TMDB. Referencia recogida el 2026-08-29
> del swagger oficial (`thetvdb/v4-api`, `docs/swagger.yml`) y de
> `thetvdb.com/api-information`.

- **Por qué**: TMDB prohíbe el uso comercial bajo licencia gratuita
  (149 $/mes desde el primer euro). TheTVDB escala por facturación propia:
  **gratis por debajo de 50.000 $/año**, 1.000 $/año hasta 250 k$,
  10.000 $/año hasta 1 M$.
- **Modalidad de clave**: pedir la **licenciada**. La alternativa
  ("user-supported") exige que cada usuario final mantenga una suscripción de
  12 $/año — inviable para un producto de consumo.
- **Base URL**: `https://api4.thetvdb.com/v4`
- **Auth**: `POST /login` devuelve un JWT que **dura un mes**. El cliente debe
  renovarlo solo (mismo patrón que el cliente Twitch/IGDB actual en
  `backlogg/games/adapters/igdb.py`).
- **Atribución obligatoria**: enlace directo a TheTVDB.com visible para el
  usuario que ve los metadatos.

- **Endpoints relevantes**:
  - `GET /movies/{id}` · `GET /movies/{id}/extended` (créditos, artwork)
  - `GET /movies/slug/{slug}` · `GET /movies/{id}/translations/{language}`
  - `GET /series/{id}` · `/extended` · `/artworks` · `/slug/{slug}` ·
    `/translations/{language}` · `/episodes/{season-type}`
  - `GET /search`, `GET /search/remoteid/{remoteId}`, `GET /genres`,
    `GET /people/{id}`, `GET /updates`

- **⚠️ No existe endpoint de "similar" ni de "trending".** Ambos se sustituyen
  por cálculo local — features 85 y 86, ver `docs/recommendations-plan.md`.

- **⚠️ No existe feed de popularidad paginado** (el problema caro de la
  migración, feature 74). Las dos únicas vías, ambas con pegas:

  | Vía | Ordena por popularidad | Pagina | Pega |
  |---|---|---|---|
  | `GET /movies?page=N` · `GET /series?page=N` | ❌ (orden de id) | ✅ | Hay que recorrer la base entera y rankear localmente por `score` |
  | `GET /movies/filter` · `GET /series/filter` | ✅ (`sort=score`) | ❌ | `country` **y** `lang` son obligatorios: obliga a fan-out por pares país/idioma |

  El campo `score` está presente en casi todas las entidades y, según el propio
  swagger, «se usa para insinuar popularidad relativa a efectos de ordenación»,
  sin garantías sobre su significado exacto.

- **Otros límites**: `GET /search` está limitado a 5.000 resultados máximo.
- **Slugs**: TheTVDB expone slug propio (`/movies/slug/{slug}`), pero el
  catálogo **genera los suyos** con `_slugify(titulo)-año` en el adaptador.
  Mantenerlo así: es lo que permite que las URLs sobrevivan al cambio de
  fuente sin perder posicionamiento.
- **external_ids source value**: `THETVDB`

## RAWG (Games) — DESTINO de la migración, feature 75

> Aún **no implementado**. Sustituye a IGDB, que solo es gratis para uso no
> comercial bajo el Twitch Developer Services Agreement.

- **Base URL**: `https://api.rawg.io/api` · **Auth**: `key` como query param.
- **Cuota gratuita con uso comercial permitido**: 20.000 peticiones/mes,
  siempre que el proyecto tenga menos de 100.000 usuarios activos o 500.000
  páginas vistas al mes. Planes Business (50.000) y Enterprise por encima.
- **Atribución obligatoria**: enlace activo a RAWG **desde cada página** donde
  se usen sus datos. Más estricto que TMDB, que se conformaba con el "acerca
  de" — condiciona el diseño de la ficha de juego.
- **Sin ventana de caducidad de caché** en sus términos (a diferencia de los
  6 meses de TMDB).

- **Presupuesto de peticiones — la clave del diseño**: `GET /games` devuelve
  **40 ítems por página** (`page_size` máximo) con ordenación por popularidad
  (`ordering=-added` o `-rating`). Sembrar 10.000 juegos cuesta **250
  peticiones, no 10.000**.

  | Campo del modelo `Game` | ¿En el listado? |
  |---|---|
  | title, slug, release_date | ✅ |
  | poster_url (`background_image`) | ✅ |
  | rating_external, rating_count_external | ✅ |
  | genres, platforms | ✅ |
  | **overview** (`description`) | ❌ solo en `GET /games/{id}` |
  | **companies** (developers/publishers) | ❌ solo en `GET /games/{id}` |

  Los dos campos que faltan se resuelven con el **fallback on-demand** que ya
  existe en `backlogg/games/service.py`: una petición por ficha, la primera vez
  que alguien la abre, pagada una sola vez.

- **⚠️ No hay equivalente a `game_type` de IGDB**, así que el *category
  allowlist* de la feature 65 (`backlogg/games/constants.py`) no se puede
  portar tal cual. Sustituirlo por otro filtro de calidad (umbral de
  `ratings_count` o `added`).
- **external_ids source value**: `RAWG`

- **Alternativas descartadas**: Giant Bomb (solo uso no comercial, revocan la
  clave), MobyGames (de pago y con límites de ritmo muy bajos: 720
  peticiones/hora en el tier no comercial).

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
