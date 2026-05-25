# API Design

## Conventions

- **URL identifiers**: slugs (not numeric IDs). Example: `/movies/the-godfather`
- **Pagination**: offset/limit. Parameters: `page` (1-based) and `limit` (default 20, max 100)
- **Content-Type**: `application/json`

## Endpoints

### Health

```
GET /health
→ 200 {"status": "ok"}
```

### Search (cross-type)

```
GET /search?q=&type=&page=&limit=
```

| Param   | Required | Description |
|---------|----------|-------------|
| `q`     | Yes      | Search query. Returns 422 if empty. |
| `type`  | No       | Filter by content type: `movie`, `series`, `book`, `game` |
| `page`  | No       | Page number, 1-based (default: 1) |
| `limit` | No       | Results per page (default: 20, max: 100) |

Response:
```json
{
  "results": [
    {
      "id": 1,
      "item_type": "MOVIE",
      "title": "Dune",
      "overview": "...",
      "poster_url": "https://...",
      "release_date": "2021-10-22",
      "rating_external": 7.8
    }
  ],
  "total": 42,
  "page": 1,
  "limit": 20
}
```

### Movies

```
GET /movies/{slug}
→ 200  Movie detail
→ 404  Not found in DB or external API
```

Response fields: `id`, `title`, `original_title`, `slug`, `overview`, `release_date`,
`runtime`, `original_language`, `poster_url`, `backdrop_url`, `budget`, `revenue`,
`status`, `rating_external`, `rating_count_external`, `genres[]`

### Series

```
GET /series/{slug}
→ 200  Series detail
→ 404  Not found
```

Response fields: `id`, `title`, `original_title`, `slug`, `overview`, `first_air_date`,
`last_air_date`, `number_of_seasons`, `number_of_episodes`, `status`, `original_language`,
`poster_url`, `backdrop_url`, `rating_external`, `rating_count_external`, `genres[]`

### Books

```
GET /books/{slug}
→ 200  Book detail
→ 404  Not found
```

Response fields: `id`, `title`, `original_title`, `slug`, `overview`, `first_publish_date`,
`original_language`, `poster_url`, `rating_external`, `rating_count_external`, `genres[]`

### Games

```
GET /games/{slug}
→ 200  Game detail
→ 404  Not found
```

Response fields: `id`, `title`, `original_title`, `slug`, `overview`, `release_date`,
`game_type`, `original_language`, `poster_url`, `backdrop_url`, `rating_external`,
`rating_count_external`, `genres[]`, `platforms[]`

### People

```
GET /people/{slug}
→ 200  Person detail
→ 404  Not found
```

Response fields: `id`, `name`, `slug`, `profile_url`, `credits[]`
(each credit: `item_type`, `item_id`, `item_slug`, `item_title`, `role`,
`character_name`, `billing_order`)

### Admin (sync trigger)

```
POST /admin/sync/{type}   type ∈ {movie, series, book, game}
→ 200  Sync completed
```

El endpoint **bloquea hasta que el sync termina** y devuelve el resultado real.
Usar `--max-time 600` en curl para evitar timeout de cliente.

Response:
```json
{
  "type": "movie",
  "synced": 94,
  "errors": 6,
  "duration_s": 87
}
```

- `synced` — número de items insertados/actualizados correctamente.
- `errors` — número de items que fallaron (logged en servidor).
- `duration_s` — segundos que tardó el sync.

Not authenticated in MVP — for internal/testing use only.

### Admin stats

```
GET /admin/stats
→ 200
```

Response:
```json
{
  "movies":  { "count": 847, "last_synced_at": "2026-05-25T02:03:12Z" },
  "series":  { "count": 312, "last_synced_at": "2026-05-25T02:04:01Z" },
  "books":   { "count": 520, "last_synced_at": "2026-05-25T02:05:44Z" },
  "games":   { "count": 198, "last_synced_at": "2026-05-25T02:06:33Z" }
}
```

- `count` — número de filas en la tabla correspondiente.
- `last_synced_at` — `MAX(last_synced_at)` de la tabla; `null` si no hay datos.

Not authenticated in MVP — for internal/testing use only.

## On-demand fallback

When `GET /{type}/{slug}` finds no local result, the service layer:
1. Queries the external API by slug/title
2. Persists the item to the local DB
3. Returns the item as if it had been found locally

If the item is not found in the external API either, returns `404`.

## Out of scope in MVP

- Auth endpoints (`POST /auth/login`, `POST /auth/register`)
- User list endpoints (`GET /users/{id}/lists`, `POST /lists`, etc.)
- Rating endpoints
- `GET /movies` (list all) — search covers this use case
