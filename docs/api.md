# API Design

## Conventions

- **URL identifiers**: slugs (not numeric IDs). Example: `/movies/the-godfather`
- **Pagination**: offset/limit. Parameters: `page` (1-based) and `limit` (default 20, max 100)
- **Content-Type**: `application/json`
- **Admin auth**: los endpoints `/admin/*` requieren el header `X-API-Key`
  (ver sección Admin).
- **User auth**: `POST /auth/login` devuelve un JWT (`access_token`). Los
  endpoints que lo requieren esperan `Authorization: Bearer <token>` y
  devuelven `401` si falta, es inválido o expiró (ver sección Auth & Users).
  El resto de la API es pública.
- **CORS y security headers**: orígenes permitidos vía `CORS_ORIGINS`
  (comma-separated; sin configurar permite `localhost:3000` y `localhost:5173`).
  Todas las respuestas llevan `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY` y `Referrer-Policy: strict-origin-when-cross-origin`.

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

**External fallback**: si la consulta devuelve 0 resultados locales, el
servicio hace fan-out en paralelo a las APIs externas (TMDB, Open Library,
IGDB — solo la correspondiente si se filtra por `type`), ingesta los top hits
y re-consulta la vista local antes de responder. Un fallo en una API externa
no aborta las demás ni devuelve error al cliente.

### List endpoints (los 4 tipos)

```
GET /movies | /series | /books | /games
→ 200  Lista paginada (solo items ya en DB, sin fallback externo)
```

| Param   | Required | Description |
|---------|----------|-------------|
| `genre` | No       | Filtro por slug de género (p.ej. `action`) |
| `sort`  | No       | `rating_desc` (default), `rating_asc`, `date_desc`, `date_asc`, `title_asc` |
| `page`  | No       | Página, 1-based (default: 1) |
| `limit` | No       | Items por página (default: 20, max: 100) |

`date_*` ordena por `release_date` (movies/games), `first_air_date` (series)
o `first_publish_date` (books).

Response:
```json
{
  "items": [
    {
      "id": 1,
      "title": "Dune",
      "slug": "dune-2021",
      "poster_url": "https://...",
      "release_date": "2021-10-22",
      "rating_external": 7.8,
      "genres": ["science-fiction", "adventure"]
    }
  ],
  "total": 847,
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
`status`, `rating_external`, `rating_count_external`, `rating_internal`,
`rating_count_internal`, `genres[]`, `credits[]`, `viewer_status`

`viewer_status` es el estado de biblioteca del caller autenticado para este
item (`want`/`in_progress`/`completed`/`dropped`) o `null` si no está
autenticado o no tiene entrada. Auth **opcional**: sin token la respuesta es
idéntica salvo `viewer_status: null`.

```
GET /movies/{slug}/similar
→ 200  Hasta 10 películas similares (TMDB recommendations)
→ 404  Slug no encontrado
```

Response: `{"results": [...]}` — cada item: `title`, `slug`, `poster_url`,
`release_date`, `rating_external`. Los items nuevos se persisten en la DB local.

### Series

```
GET /series/{slug}
→ 200  Series detail
→ 404  Not found
```

Response fields: `id`, `title`, `original_title`, `slug`, `overview`, `first_air_date`,
`last_air_date`, `number_of_seasons`, `number_of_episodes`, `status`, `original_language`,
`poster_url`, `backdrop_url`, `rating_external`, `rating_count_external`, `rating_internal`,
`rating_count_internal`, `genres[]`, `credits[]`, `viewer_status` (ver Movies)

```
GET /series/{slug}/similar
→ 200  Hasta 10 series similares (mismo contrato que /movies/{slug}/similar)
→ 404  Slug no encontrado
```

### Books

```
GET /books/{slug}
→ 200  Book detail
→ 404  Not found
```

Response fields: `id`, `title`, `original_title`, `slug`, `overview`, `first_publish_date`,
`original_language`, `poster_url`, `rating_external`, `rating_count_external`,
`rating_internal`, `rating_count_internal`, `genres[]`, `viewer_status` (ver Movies)

### Games

```
GET /games/{slug}
→ 200  Game detail
→ 404  Not found
```

Response fields: `id`, `title`, `original_title`, `slug`, `overview`, `release_date`,
`game_type`, `original_language`, `poster_url`, `backdrop_url`, `rating_external`,
`rating_count_external`, `rating_internal`, `rating_count_internal`, `genres[]`,
`platforms[]`, `credits[]`, `viewer_status` (ver Movies)

**`credits[]`** (en detail de movies, series y games): cada credit incluye
`person_name`, `person_slug`, `profile_url`, `role`, `character_name`,
`billing_order`, ordenados por `billing_order` ascendente. Array vacío si no hay.

### Auth & Users

```
POST /auth/register
→ 201  Cuenta creada
→ 409  username o email ya en uso
→ 422  validación de payload (username/email/password fuera de formato o longitud)
```

Body: `{"username": string, "email": string, "password": string (min 8),
"display_name": string | null}`. `username` solo admite `[a-zA-Z0-9_-]`,
3-50 caracteres — es el identificador en las URLs (`/users/{username}`),
no hay slug ni id numérico expuestos.

Response (`UserMeOut`, incluye email — solo se devuelve así en register/login/me):
`username`, `email`, `display_name`, `bio`, `avatar_url`.

```
POST /auth/login
→ 200  Login correcto
→ 401  Credenciales inválidas
```

Body: `{"username": string, "password": string}`.
Response: `{"access_token": string, "token_type": "bearer"}`.

```
GET /users/me
→ 200  Perfil propio (incluye email)
→ 401  Sin token / token inválido o expirado
```

```
PATCH /users/me
→ 200  Perfil actualizado
→ 401  Sin token
```

Body (reemplazo parcial, todos los campos opcionales):
`{"display_name": string | null, "bio": string | null, "avatar_url": string | null}`.

```
GET /users/{username}
→ 200  Perfil público (sin email)
→ 404  Username no encontrado
```

Response (`UserOut`, público): `username`, `display_name`, `bio`,
`avatar_url`, `follower_count`, `following_count`, `library_counts`.

`library_counts` es un objeto `{want, in_progress, completed, dropped}` con el
número de entradas de biblioteca del usuario por estado (zero-filled).

### Follows

Relación unidireccional sin aprobación entre usuarios.

```
POST /users/{username}/follow
→ 204  Ahora sigues a {username} (idempotente: seguir dos veces no falla)
→ 401  Sin token
→ 404  Username no encontrado
→ 422  No puedes seguirte a ti mismo
```

```
DELETE /users/{username}/follow
→ 204  Dejas de seguir a {username} (idempotente: no falla si no seguías)
→ 401  Sin token
→ 404  Username no encontrado
```

```
GET /users/{username}/followers?page=&limit=
→ 200  Lista paginada, pública, de usuarios que siguen a {username}
→ 404  Username no encontrado
```

```
GET /users/{username}/following?page=&limit=
→ 200  Lista paginada, pública, de usuarios a los que {username} sigue
→ 404  Username no encontrado
```

Response (ambos listados): `{"items": [...], "total": , "page": , "limit": }`
— cada item: `username`, `display_name`, `avatar_url`. Orden: más reciente
primero.

### Ratings & reviews

Mismo contrato en los 4 tipos de contenido — sustituir `{type}` por
`movies`, `series`, `books` o `games`.

```
PUT /{type}/{slug}/rating
→ 200  Upsert de la puntuación/review del usuario autenticado
→ 401  Sin token
→ 404  Slug no encontrado
→ 422  score fuera de 1-5
```

Body: `{"score": 1-5 | null, "review_text": string | null}` — reemplazo
completo (PUT), no parcial: omitir un campo lo deja en `null`. Tras cada
upsert se recalculan `rating_internal` (AVG) y `rating_count_internal`
(COUNT) del item.

Response: `id`, `user` (`username`, `display_name`, `avatar_url`), `score`,
`review_text`, `like_count`, `created_at`, `updated_at`.

```
DELETE /{type}/{slug}/rating
→ 204  Rating propia eliminada; agregados recalculados
→ 401  Sin token
→ 404  El usuario no tiene rating para ese item
```

```
GET /{type}/{slug}/ratings?page=&limit=
→ 200  Lista paginada, pública, más reciente primero
→ 404  Slug no encontrado
```

Response: `{"items": [...], "total": , "page": , "limit": }` — cada item
tiene el mismo shape que la respuesta de `PUT .../rating`, incluyendo
`like_count`.

```
POST /ratings/{id}/like
DELETE /ratings/{id}/like
→ 204  Auth requerida, idempotente (dar/quitar like dos veces no falla)
→ 401  Sin token
→ 404  Rating no encontrada
```

`{id}` es el id numérico de la rating (no tiene slug propio).

```
GET /users/{username}/reviews?page=&limit=
→ 200  Público, paginado, cross-type (UNION ALL de movies/series/books/games)
→ 404  Username no encontrado
```

Response: `{"items": [...], "total": , "page": , "limit": }` — cada item:
`id`, `item` (`item_type`, `title`, `slug`, `poster_url`), `score`,
`review_text`, `created_at`, `updated_at`. Incluye entradas con y sin
`review_text`.

### Feed (activity feed)

```
GET /feed?tab=following|popular&page=&limit=
→ 200  Feed paginado, cross-type (UNION ALL de movies/series/books/games)
→ 401  Sin token
→ 422  tab distinto de following/popular
```

Auth requerida en ambas pestañas. `tab` por defecto `following`.

- `tab=following`: reviews de los usuarios que el caller sigue, orden
  reverse-chronological. Caller sin follows → lista vacía (no es error).
- `tab=popular`: reviews de los últimos 30 días ordenadas por `like_count`
  desc y, a igualdad, por `created_at` desc.

Response: `{"items": [...], "total": , "page": , "limit": }` — cada entrada:
`id`, `author` (`username`, `display_name`, `avatar_url`), `item` (`item_type`,
`title`, `slug`, `poster_url`), `score`, `review_text`, `like_count`,
`created_at`.

### Library (backlog por usuario)

Cada usuario mantiene una lista de pendientes/en curso/terminados/abandonados a
través de los 4 tipos. Estados válidos: `want`, `in_progress`, `completed`,
`dropped`.

```
PUT /{type}/{slug}/library      ({type} = movies | series | books | games)
→ 200  Upsert del estado del caller para el item
→ 401  Sin token
→ 404  Slug no encontrado
→ 422  status inválido (no está entre los cuatro permitidos)
```

Body: `{"status": "want"}`. Response (`LibraryStatusOut`): `item_type`, `slug`,
`status`, `created_at`, `updated_at`. Llamar dos veces reemplaza el estado
(upsert por `(user, item_type, item_id)`).

```
DELETE /{type}/{slug}/library
→ 204  Entrada propia eliminada
→ 401  Sin token
→ 404  El caller no tiene entrada para ese item (o slug no encontrado)
```

```
GET /users/{username}/library?status=&type=&page=&limit=
→ 200  Biblioteca paginada, cross-type (UNION ALL de movies/series/books/games)
→ 404  Username no encontrado
```

Público (sin auth). Filtros opcionales: `status` (uno de los cuatro estados) y
`type` (`movie`/`series`/`book`/`game`); valores inválidos → 422. Orden
reverse-chronological por `created_at`.

Response: `{"items": [...], "total": , "page": , "limit": }` — cada entrada:
`item` (`item_type`, `title`, `slug`, `poster_url`, `release_date`,
`rating_external`) y `status`, `created_at`, `updated_at`. `release_date` usa
`first_air_date` para series y `first_publish_date` para libros.

### Lists (colecciones curadas)

Listas nombradas creadas por usuarios (p.ej. "Mejor sci-fi") con items
cross-type ordenados y visibilidad público/privado. El `slug` se deriva del
título al crear la lista y no cambia. Aunque la unicidad en DB es por
`(user_id, slug)`, el `slug` se resuelve de forma **globalmente única**
(sufijo `-2`, `-3`, … en caso de colisión) para que `/lists/{slug}` apunte a
una sola lista — esto permite distinguir 404 (no existe) de 403 (existe pero no
es tuya).

```
POST /lists
→ 201  Lista creada (slug derivado del título)
→ 401  Sin token
```

Body (`ListCreate`): `title` (obligatorio), `description` (opcional),
`is_public` (opcional, default `true`). Response (`UserListOut`): `slug`,
`title`, `description`, `is_public`, `item_count`, `created_at`, `updated_at`,
`items[]`.

```
GET /lists/{slug}
→ 200  Detalle con items resueltos cross-type en orden (por position)
→ 404  No existe, o es privada y el caller no es el owner
```

Auth opcional. Las listas privadas solo las ve su owner; para el resto se
oculta su existencia con 404. Cada item de `items[]`: `item_type`, `title`,
`slug`, `poster_url`, `release_date`, `rating_external`, `position`.

```
PATCH /lists/{slug}      (auth, solo owner)
→ 200  Actualiza title/description/is_public (el slug no cambia)
→ 401  Sin token
→ 403  No es el owner
→ 404  No existe
```

```
DELETE /lists/{slug}     (auth, solo owner)
→ 204  Lista eliminada (cascada sobre sus list_items)
→ 401 / 403 / 404
```

```
POST   /lists/{slug}/items     (auth, solo owner)
DELETE /lists/{slug}/items     (auth, solo owner)
→ 200  Devuelve el detalle de la lista actualizado
→ 401 / 403
→ 404  El item (item_type + slug) no existe en el catálogo
```

Body (`ListItemRef`): `{"item_type": "movie|series|book|game", "slug": "..."}`.
Añadir es idempotente y coloca el item al final (`position` = max+1); quitar es
idempotente (no falla si el item no estaba) y re-empaqueta las posiciones.

```
PUT /lists/{slug}/items/order   (auth, solo owner)
→ 200  Reordena los items; devuelve el detalle
→ 401 / 403 / 404
→ 422  El conjunto enviado no coincide exactamente con los items de la lista
```

Body (`ListReorder`): `{"items": [{"item_type": "...", "slug": "..."}, ...]}`
con el orden deseado. Debe contener exactamente los items actuales de la lista.

```
GET /users/{username}/lists
→ 200  Listas del usuario (públicas siempre; privadas solo si el caller es owner)
→ 404  Username no encontrado
```

Auth opcional. Response (`UserListsOut`): `{"lists": [...], "total": }` — cada
entrada (`UserListSummary`): `slug`, `title`, `description`, `is_public`,
`item_count`, `created_at`, `updated_at`.

### People

```
GET /people/{slug}
→ 200  Person detail
→ 404  Not found
```

Response fields: `id`, `name`, `slug`, `profile_url`, `credits[]`
(each credit: `item_type`, `item_id`, `item_slug`, `item_title`, `role`,
`character_name`, `billing_order`)

### Genres

```
GET /genres?type=movie|series|book|game
→ 200  Géneros con conteo de items asociados
→ 422  type inválido
```

Sin `type` devuelve los géneros de todos los tipos. Response:
`{"genres": [...]}` — cada género: `name`, `slug`, `item_type`, `count`
(número real de items asociados).

### Trending

```
GET /trending?type=movie|series&period=day|week
→ 200  Hasta 20 items trending (TMDB Trending API)
→ 422  type o period inválidos
```

Sin `type` devuelve mix de movies y series. `period` default: `week`.
Response: `{"results": [...]}` — cada item: `item_type`, `title`, `slug`,
`poster_url`, `release_date`, `rating_external`. Los items nuevos se
persisten en la DB local.

### Admin (sync trigger)

```
POST /admin/sync/{type}   type ∈ {movie, series, book, game}
→ 200  Sync completed
```

El endpoint **bloquea hasta que el sync termina** y devuelve el resultado real.
Usar `--max-time 600` en curl para evitar timeout de cliente.

Cada ejecución procesa un **tramo** de hasta `SYNC_SLICE_SIZE` items del
listado popular, empezando en el offset persistido en `sync_cursors` para el
tipo. El cursor avanza al terminar y vuelve a 0 al alcanzar `SEED_TOP_N_*`
o cuando la API externa devuelve menos items de los pedidos.

Response:
```json
{
  "type": "movie",
  "synced": 94,
  "errors": 6,
  "offset": 200,
  "duration_s": 87
}
```

- `synced` — número de items insertados/actualizados correctamente.
- `errors` — número de items que fallaron (logged en servidor).
- `offset` — offset (0-based) del tramo procesado en esta ejecución.
- `duration_s` — segundos que tardó el sync.

**Auth**: requiere el header `X-API-Key` con el valor de la env var
`ADMIN_API_KEY`. Header ausente o incorrecto → `401`; `ADMIN_API_KEY` sin
configurar → `503`.

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

**Auth**: misma protección `X-API-Key` que el sync trigger (`401`/`503`).

## On-demand fallback

When `GET /{type}/{slug}` finds no local result, the service layer:
1. Queries the external API by slug/title
2. Persists the item to the local DB
3. Returns the item as if it had been found locally

If the item is not found in the external API either, returns `404`.

## Out of scope

- Direct messaging between users.
