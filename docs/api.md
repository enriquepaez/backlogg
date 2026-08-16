# API Design

## Conventions

- **Versionado**: toda la superficie de negocio se sirve bajo el prefijo `/v1`
  (p.ej. `/v1/movies`, `/v1/auth/login`, `/v1/admin/reports`). Es un corte
  limpio: no se mantienen alias en la raíz. Los endpoints operativos `/health` y
  `/metrics` quedan **sin versionar** (son de ops, no de la API de negocio).
- **URL identifiers**: slugs (not numeric IDs). Example: `/v1/movies/the-godfather`
- **Pagination**: offset/limit. Parameters: `page` (1-based) and `limit` (default 20, max 100)
- **Content-Type**: `application/json`
- **Admin auth**: los endpoints `/v1/admin/*` requieren el header `X-API-Key`
  (ver sección Admin).
- **User auth**: `POST /v1/auth/login` devuelve un par de tokens: un
  `access_token` (JWT corto) y un `refresh_token` (opaco, rotatorio). Los
  endpoints protegidos esperan `Authorization: Bearer <access_token>` y
  devuelven `401` si falta, es inválido o expiró. El access token caduca pronto;
  se renueva con `POST /v1/auth/refresh` (rota el par) y se invalida con
  `POST /v1/auth/logout` (ver sección Auth & Users). El resto de la API es pública.
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
GET /v1/search?q=&type=&page=&limit=
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

El fallback externo está **rate-limited por IP** (`RATE_LIMIT_SEARCH_FALLBACK`):
superar el límite devuelve `429` con header `Retry-After` **sin** llamar a las
APIs externas. Las consultas servidas desde el catálogo local no consumen cupo.

### List endpoints (los 4 tipos)

```
GET /v1/movies | /v1/series | /v1/books | /v1/games
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
GET /v1/movies/{slug}
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
GET /v1/movies/{slug}/similar
→ 200  Hasta 10 películas similares (TMDB recommendations)
→ 404  Slug no encontrado
```

Response: `{"results": [...]}` — cada item: `title`, `slug`, `poster_url`,
`release_date`, `rating_external`. Los items nuevos se persisten en la DB local.

### Series

```
GET /v1/series/{slug}
→ 200  Series detail
→ 404  Not found
```

Response fields: `id`, `title`, `original_title`, `slug`, `overview`, `first_air_date`,
`last_air_date`, `number_of_seasons`, `number_of_episodes`, `status`, `original_language`,
`poster_url`, `backdrop_url`, `rating_external`, `rating_count_external`, `rating_internal`,
`rating_count_internal`, `genres[]`, `credits[]`, `viewer_status` (ver Movies)

```
GET /v1/series/{slug}/similar
→ 200  Hasta 10 series similares (mismo contrato que /v1/movies/{slug}/similar)
→ 404  Slug no encontrado
```

### Books

```
GET /v1/books/{slug}
→ 200  Book detail
→ 404  Not found
```

Response fields: `id`, `title`, `original_title`, `slug`, `overview`, `first_publish_date`,
`original_language`, `poster_url`, `rating_external`, `rating_count_external`,
`rating_internal`, `rating_count_internal`, `genres[]`, `credits[]`, `viewer_status`
(ver Movies). El autor se expone como credit con `role: "AUTHOR"`.

```
GET /v1/books/{slug}/similar
→ 200  Hasta 10 libros similares, calculados 100% en local (sin API externa)
→ 404  Slug no encontrado
```

Response: `{"results": [...]}` — mismo contrato que `/v1/movies/{slug}/similar`:
cada item incluye `title`, `slug`, `poster_url`, `release_date`
(`first_publish_date` del libro), `rating_external`. **A diferencia de
`GET /v1/recommendations`, no incluye un campo `reason`.**

Ranking: prioriza libros que comparten autor con el libro base (vía
`people`/`credits` con `role: "AUTHOR"`, feature 19) sobre el resto; para
completar hasta 10 resultados (o si no hay coincidencia de autor) usa
solapamiento de género, con `rating_external` descendente como desempate
en ambos niveles. El propio libro nunca aparece en sus resultados. No se
hace ninguna llamada a Open Library ni se crean `external_ids` nuevos — el
ranking se calcula enteramente desde datos ya persistidos localmente (ver
investigación en `feature_list.json`, feature 46).

### Games

```
GET /v1/games/{slug}
→ 200  Game detail
→ 404  Not found
```

Response fields: `id`, `title`, `original_title`, `slug`, `overview`, `release_date`,
`game_type`, `original_language`, `poster_url`, `backdrop_url`, `rating_external`,
`rating_count_external`, `rating_internal`, `rating_count_internal`, `genres[]`,
`platforms[]`, `credits[]`, `viewer_status` (ver Movies)

```
GET /v1/games/{slug}/similar
→ 200  Hasta 10 juegos similares (campo similar_games de IGDB — relaciones
       curadas, no solapamiento de género)
→ 404  Slug no encontrado
```

Response: `{"results": [...]}` — mismo contrato que `/v1/movies/{slug}/similar`
y `/v1/series/{slug}/similar`: cada item incluye `title`, `slug`, `poster_url`,
`release_date`, `rating_external`. Los juegos nuevos se persisten en la DB local.

**`credits[]`** (en detail de movies, series, books y games): cada credit incluye
`person_name`, `person_slug`, `profile_url`, `role`, `character_name`,
`billing_order`, ordenados por `billing_order` ascendente. Array vacío si no hay.

### Auth & Users

```
POST /v1/auth/register
→ 201  Cuenta creada
→ 409  username o email ya en uso
→ 422  validación de payload (username/email/password fuera de formato o longitud)
→ 429  demasiadas peticiones desde la misma IP (header Retry-After)
```

Body: `{"username": string, "email": string, "password": string (min 8),
"display_name": string | null}`. `username` solo admite `[a-zA-Z0-9_-]`,
3-50 caracteres — es el identificador en las URLs (`/v1/users/{username}`),
no hay slug ni id numérico expuestos.

Response (`UserMeOut`, incluye email — solo se devuelve así en register/login/me):
`username`, `email`, `display_name`, `bio`, `avatar_url`, `email_verified`.

```
POST /v1/auth/login
→ 200  Login correcto
→ 401  Credenciales inválidas
→ 429  demasiadas peticiones desde la misma IP (header Retry-After)
```

`POST /v1/auth/login` y `POST /v1/auth/register` están rate-limited por IP
(`RATE_LIMIT_AUTH`). Al exceder el límite responden `429` con header
`Retry-After` (segundos) y un body genérico que no filtra IP ni límites.

Body: `{"username": string, "password": string}`.
Response: `{"access_token": string, "refresh_token": string, "token_type": "bearer"}`.
El `access_token` es un JWT corto (`JWT_EXPIRE_MINUTES`, 15 por defecto); el
`refresh_token` es un valor opaco rotatorio (`REFRESH_EXPIRE_DAYS`, 30 por
defecto). El `refresh_token` solo se devuelve en esta respuesta y en la de
`/v1/auth/refresh` — guárdalo, no vuelve a mostrarse.

```
POST /v1/auth/refresh
→ 200  Par de tokens rotado
→ 401  refresh inválido, expirado o revocado (incluye reuse)
```

Body: `{"refresh_token": string}`. No requiere `Authorization`.
Response: `{"access_token": string, "refresh_token": string, "token_type": "bearer"}`.
Rota el refresh: revoca el presentado y emite uno nuevo junto a un access nuevo.
Reusar un refresh ya rotado/revocado devuelve `401` y revoca todos los refresh
activos del usuario como defensa ante robo de token.

```
POST /v1/auth/logout
→ 204  Sesión cerrada (refresh revocado)
→ 401  Sin token / access token inválido o expirado
```

Requiere `Authorization: Bearer <access_token>`.
Body: `{"refresh_token": string}`. Revoca el refresh indicado. Idempotente:
revocar dos veces (o un token desconocido) no falla, siempre `204`.

#### Recuperación de cuenta (verificación de email + reset de password)

El correo se envía a través de una interfaz `EmailSender`: implementación SMTP
(stdlib `smtplib`) cuando `SMTP_HOST` está configurado, y un fallback que
**loguea el enlace** (sin enviar) cuando no lo está — la app funciona en ambos
casos. Los enlaces se construyen con `APP_BASE_URL`. Todos los tokens son **de
un solo uso** y **caducan**; reusar un token consumido/expirado/desconocido
devuelve `400`.

```
POST /v1/auth/verify/request
→ 202  Email de verificación enviado (o logueado en dev)
→ 401  Sin token / access token inválido o expirado
```

Requiere `Authorization: Bearer <access_token>`. Genera un token de
verificación para el usuario autenticado y le envía el enlace. Sin body.
Response: `{"detail": string}`.

```
POST /v1/auth/verify/confirm
→ 200  Email verificado (users.email_verified = true)
→ 400  Token inválido, expirado o ya usado
```

Body: `{"token": string}` (el token del enlace). No requiere `Authorization`.
Response: `{"detail": string}`.

```
POST /v1/auth/password/forgot
→ 202  Siempre (exista o no el email — sin enumeración)
```

Body: `{"email": string}`. No requiere `Authorization`. Si el email está
registrado, genera un token de reset y envía el enlace; si no, no hace nada.
La respuesta es **idéntica** en ambos casos para no revelar qué emails existen.
Un fallo del proveedor de email no altera la respuesta. Response: `{"detail": string}`.

```
POST /v1/auth/password/reset
→ 200  Password cambiada; se revocan los refresh activos del usuario
→ 400  Token inválido, expirado o ya usado
```

Body: `{"token": string, "new_password": string (min 8)}`. No requiere
`Authorization`. Consume el token de reset, cambia el `password_hash` y revoca
todos los refresh tokens activos del usuario (fuerza re-login). Response:
`{"detail": string}`.

```
GET /v1/users/me
→ 200  Perfil propio (incluye email)
→ 401  Sin token / token inválido o expirado
```

```
PATCH /v1/users/me
→ 200  Perfil actualizado
→ 401  Sin token
```

Body (reemplazo parcial, todos los campos opcionales):
`{"display_name": string | null, "bio": string | null, "avatar_url": string | null}`.

```
DELETE /v1/users/me
→ 204  Cuenta borrada
→ 401  Sin token / token inválido o expirado
```

Borra la cuenta del usuario autenticado (higiene GDPR). El borrado elimina en
cascada (DB `ON DELETE CASCADE`) todos sus datos asociados: ratings,
review_likes, follows (en ambos sentidos), biblioteca, notificaciones
(como recipient y como actor) y tokens (refresh + account). Tras el borrado se
recomputan `rating_internal`/`rating_count_internal` de los items que el usuario
había puntuado, y el `username`/`email` quedan libres para re-registro. Los
refresh tokens quedan invalidados (un `/v1/auth/refresh` posterior devuelve 401).

```
GET /v1/users/{username}
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
POST /v1/users/{username}/follow
→ 204  Ahora sigues a {username} (idempotente: seguir dos veces no falla)
→ 401  Sin token
→ 404  Username no encontrado
→ 422  No puedes seguirte a ti mismo
```

```
DELETE /v1/users/{username}/follow
→ 204  Dejas de seguir a {username} (idempotente: no falla si no seguías)
→ 401  Sin token
→ 404  Username no encontrado
```

```
GET /v1/users/{username}/followers?page=&limit=
→ 200  Lista paginada, pública, de usuarios que siguen a {username}
→ 404  Username no encontrado
```

```
GET /v1/users/{username}/following?page=&limit=
→ 200  Lista paginada, pública, de usuarios a los que {username} sigue
→ 404  Username no encontrado
```

Response (ambos listados): `{"items": [...], "total": , "page": , "limit": }`
— cada item: `username`, `display_name`, `avatar_url`. Orden: más reciente
primero.

Un follow nuevo genera una notificación `new_follower` para el usuario seguido
(ver Notifications). No se notifica en un re-follow idempotente.

### Ratings & reviews

Mismo contrato en los 4 tipos de contenido — sustituir `{type}` por
`movies`, `series`, `books` o `games`.

```
PUT /v1/{type}/{slug}/rating
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
`review_text`, `like_count`, `liked_by_viewer`, `created_at`, `updated_at`.

```
DELETE /v1/{type}/{slug}/rating
→ 204  Rating propia eliminada; agregados recalculados
→ 401  Sin token
→ 404  El usuario no tiene rating para ese item
```

```
GET /v1/{type}/{slug}/ratings?page=&limit=
→ 200  Lista paginada, pública, más reciente primero
→ 404  Slug no encontrado
```

Response: `{"items": [...], "total": , "page": , "limit": }` — cada item
tiene el mismo shape que la respuesta de `PUT .../rating`, incluyendo
`like_count` y `liked_by_viewer`. `liked_by_viewer` es `true` si el caller
autenticado ya dio like a esa review, `false` si no (o si el caller es
anónimo — el endpoint sigue siendo público, sin auth requerida). Resuelto en
una sola query por el backend (sin N+1).

```
POST /v1/ratings/{id}/like
DELETE /v1/ratings/{id}/like
→ 204  Auth requerida, idempotente (dar/quitar like dos veces no falla)
→ 401  Sin token
→ 404  Rating no encontrada
```

`{id}` es el id numérico de la rating (no tiene slug propio). Un like nuevo
genera una notificación `review_like` para el autor de la review (ver
Notifications); no se notifica un self-like ni un re-like idempotente, y el
unlike nunca notifica.

```
GET /v1/users/{username}/reviews?page=&limit=
→ 200  Público, paginado, cross-type (UNION ALL de movies/series/books/games)
→ 404  Username no encontrado
```

Response: `{"items": [...], "total": , "page": , "limit": }` — cada item:
`id`, `item` (`item_type`, `title`, `slug`, `poster_url`), `score`,
`review_text`, `created_at`, `updated_at`. Incluye entradas con y sin
`review_text`.

### Review reports (moderación)

Un usuario marca una review (una fila de `user_ratings`) como problemática; los
admin la triagean desde una cola. Rutas en raíz (se versionarán en la feature 45).

```
POST /v1/reviews/{id}/report
→ 201  Reporte creado (primera vez)
→ 200  Ya existía un reporte del mismo usuario para esa review (idempotente)
→ 401  Sin token
→ 404  Review (rating) no encontrada
```

`{id}` es el id numérico de la review (= `user_ratings.id`). Body opcional:
`{"reason": string | null}` (máx. 300 chars). Idempotente por
`(reporter, review)`: reportar dos veces la misma review devuelve el reporte
existente **sin** sobrescribir el `reason` original. Response: `id`,
`reporter_id`, `rating_id`, `reason`, `status` (`open`/`resolved`),
`created_at`, `resolved_at`.

```
GET /v1/admin/reports?status=&page=&limit=
→ 200  Cola paginada, más reciente primero (requiere X-API-Key)
→ 401  X-API-Key ausente o incorrecta
```

Filtro opcional `status` ∈ {`open`, `resolved`}. Response:
`{"items": [...], "total": , "page": , "limit": }` — cada item con el mismo
shape que la respuesta de `POST /v1/reviews/{id}/report`.

```
POST /v1/admin/reports/{id}/resolve
→ 200  Reporte marcado como resuelto (idempotente; requiere X-API-Key)
→ 401  X-API-Key ausente o incorrecta
→ 404  Reporte no encontrado
```

Marca `status = 'resolved'` y sella `resolved_at`. Response: el reporte
actualizado (mismo shape que arriba).

### Content moderation (admin)

Acciones de moderación del admin sobre reviews y usuarios. Todas requieren el
header `X-API-Key`. Rutas en raíz (se versionarán en la feature 45).

**Condición de visibilidad (reutilizable).** Una review es visible sólo cuando
`is_hidden = false` **y** su autor no está baneado (`users.is_banned = false`).
Una review no visible se excluye de `GET /v1/{tipo}/{slug}/ratings`, del feed y de
`GET /v1/users/{username}/reviews`, y **no cuenta** para
`rating_internal`/`rating_count_internal`.

```
POST /v1/admin/reviews/{id}/hide
POST /v1/admin/reviews/{id}/unhide
→ 200  Review oculta / restaurada (idempotente; requiere X-API-Key)
→ 401  X-API-Key ausente o incorrecta
→ 404  Review (rating) no encontrada
```

`{id}` es el id numérico de la review (= `user_ratings.id`). Tras cambiar
`is_hidden` se recomputan los agregados del item afectado excluyendo las reviews
no visibles. Response: `{"id": , "is_hidden": bool}`.

```
POST /v1/admin/users/{username}/ban
POST /v1/admin/users/{username}/unban
→ 200  Usuario baneado / desbaneado (idempotente; requiere X-API-Key)
→ 401  X-API-Key ausente o incorrecta
→ 404  Usuario no encontrado
```

Marca `users.is_banned`. Un usuario baneado **no puede hacer login ni refresh**
(ambos devuelven `401` genérico, sin revelar el baneo — coherente con la política
de no-enumeración) y **todas sus reviews quedan ocultas** (excluidas de las mismas
superficies que una review oculta). Al banear/desbanear se recomputan los agregados
de **todos** los items que el usuario había puntuado. Response:
`{"username": , "is_banned": bool}`.

### Feed (activity feed)

```
GET /v1/feed?tab=following|popular&page=&limit=
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

### Notifications

Notificaciones sociales del usuario autenticado, generadas como efecto lateral
de eventos sociales: `new_follower` (alguien te sigue) y `review_like` (alguien
da like a una de tus reviews). Sin mensajería directa (fuera de scope). La
generación es best-effort: si falla, no rompe el follow/like que la originó.

```
GET /v1/notifications?page=&limit=
→ 200  Notificaciones del caller, paginadas, reverse-chronological
→ 401  Sin token
```

Response: `{"items": [...], "total": , "page": , "limit": }` — cada entrada:
`id`, `type` (`new_follower` | `review_like`), `actor` (`username`,
`display_name`, `avatar_url`), `target` (`target_type`, `target_id`, `item_type`,
`slug`), `is_read`, `created_at`.

`target` es polimórfico: para `new_follower` los cuatro campos son `null` (no
hay target — se enlaza al perfil del actor). Para `review_like`,
`target_type="review"` y `target_id` = id de `user_ratings`; además
`item_type` (`MOVIE`/`SERIES`/`BOOK`/`GAME`, mayúscula — misma convención que
`/v1/feed`) y `slug` resuelven el item puntuado por esa review, para poder
enlazar directo a `/{item_type}/{slug}` sin una consulta adicional (no existe
`GET /v1/ratings/{id}`). Si la review referenciada está oculta por moderación
(`is_hidden`), el target sigue resolviéndose igual: el enlace es al item, no a
la review, así que la moderación de la review no afecta la notificación.

```
GET /v1/notifications/unread_count
→ 200  {"unread_count": }  número de notificaciones no leídas del caller
→ 401  Sin token
```

```
POST /v1/notifications/read
→ 204  Marca notificaciones del caller como leídas (idempotente)
→ 401  Sin token
```

Body opcional: `{"ids": [int, ...]}`. Sin body (o `ids` omitido/`null`) marca
**todas** las no leídas del caller; con `ids` marca solo esas. Siempre limitado
a las notificaciones del propio caller.

```
DELETE /v1/notifications/{notification_id}
→ 204  Notificación propia eliminada
→ 401  Sin token
→ 404  No existe o no pertenece al caller
```

`{notification_id}` es el id numérico de la notificación. Igual que
`DELETE /v1/{type}/{slug}/rating`, no se distingue "no existe" de "es de
otro usuario" — ambos casos devuelven 404, sin filtrar información.

### Recommendations (personalizadas)

Sugerencias personalizadas para el usuario autenticado, calculadas al vuelo
(dominio de solo lectura — sin tabla ni entidad nueva) a partir de sus
"semillas": items con rating `score >= 4` y/o en su library con status
`completed`/`want`.

```
GET /v1/recommendations?type=&page=&limit=
→ 200  Recomendaciones paginadas, cross-type
→ 401  Sin token
→ 422  type inválido (no está entre movie/series/book/game)
```

Auth requerida. Filtro opcional `type` (`movie`/`series`/`book`/`game`); si se
indica, solo se generan recomendaciones de ese tipo. `page` (≥1, default 1) y
`limit` (1–100, default 20).

Cómo se generan los candidatos:
- **Movies/series:** primero candidatos locales por solapamiento de género con
  las semillas; solo si no se alcanzan suficientes candidatos locales se hace
  fan-out externo reutilizando las recomendaciones de TMDB (feature 16,
  `get_similar_movies`/`get_similar_series`). No se dispara fan-out externo
  cuando ya hay suficientes candidatos locales.
- **Books/games:** solapamiento por género (sin API externa de similares).
- **Sin semillas:** fallback a populares/trending locales (por `rating_external`
  desc); lista no vacía cuando hay catálogo.

Se excluyen los items que el usuario ya ha puntuado o tiene en su library.

Response: `{"results": [...], "page": , "limit": }` — cada resultado:
`item_type`, `title`, `slug`, `poster_url`, `release_date`, `rating_external` y
`reason` (motivo legible, p.ej. `"Because you rated <title>"`,
`"Because <title> is in your library"`, `"Popular right now"`).

### Library (backlog por usuario)

Cada usuario mantiene una lista de pendientes/en curso/terminados/abandonados a
través de los 4 tipos. Estados válidos: `want`, `in_progress`, `completed`,
`dropped`.

```
PUT /v1/{type}/{slug}/library      ({type} = movies | series | books | games)
→ 200  Upsert del estado del caller para el item
→ 401  Sin token
→ 404  Slug no encontrado
→ 422  status inválido (no está entre los cuatro permitidos)
```

Body: `{"status": "want"}`. Response (`LibraryStatusOut`): `item_type`, `slug`,
`status`, `created_at`, `updated_at`. Llamar dos veces reemplaza el estado
(upsert por `(user, item_type, item_id)`).

```
DELETE /v1/{type}/{slug}/library
→ 204  Entrada propia eliminada
→ 401  Sin token
→ 404  El caller no tiene entrada para ese item (o slug no encontrado)
```

```
GET /v1/users/{username}/library?status=&type=&page=&limit=
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

### People

```
GET /v1/people/{slug}
→ 200  Person detail
→ 404  Not found
```

Response fields: `id`, `name`, `slug`, `profile_url`, `credits[]`
(each credit: `item_type`, `item_id`, `item_slug`, `item_title`, `role`,
`character_name`, `billing_order`)

### Genres

```
GET /v1/genres?type=movie|series|book|game
→ 200  Géneros con conteo de items asociados
→ 422  type inválido
```

Sin `type` devuelve los géneros de todos los tipos. Response:
`{"genres": [...]}` — cada género: `name`, `slug`, `item_type`, `count`
(número real de items asociados).

### Trending

```
GET /v1/trending?type=movie|series&period=day|week
→ 200  Hasta 20 items trending (TMDB Trending API)
→ 422  type o period inválidos
```

Sin `type` devuelve mix de movies y series. `period` default: `week`.
Response: `{"results": [...]}` — cada item: `item_type`, `title`, `slug`,
`poster_url`, `release_date`, `rating_external`. Los items nuevos se
persisten en la DB local.

### Admin (sync trigger)

```
POST /v1/admin/sync/{type}   type ∈ {movie, series, book, game}
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
GET /v1/admin/stats
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

## Metrics

```
GET /metrics
→ 200  (Content-Type: text/plain; version=0.0.4; charset=utf-8)
```

Operational metrics in the Prometheus text exposition format (v0.0.4). No
authentication: the endpoint exposes only aggregate operational data and never
any PII or secret. Serialised in-process by hand (no `prometheus-client`
dependency), consistent with the stdlib-only observability layer.

Exposed metric families:

- `http_requests_total{method,path,status}` — counter of HTTP requests. The
  `path` label is always the **route template** (`/v1/movies/{slug}`), never the
  concrete URL, so slugs/usernames/ids/query strings never become labels and the
  series count stays bounded. Unmatched URLs (404 with no route) fold into
  `path="__unmatched__"`.
- `http_request_duration_seconds{method,path}` — request-latency histogram with
  cumulative `_bucket{le=...}` series plus `_sum` and `_count`.
- `backlogg_syncs_total{type}` — content sync jobs executed, by content type
  (`movie`/`series`/`book`/`game`).
- `backlogg_external_fanout_total{source}` — external API fan-outs during the
  `/v1/search` fallback, by source (`movie`/`series`/`book`/`game`).

`/metrics` is excluded from its own request instrumentation so scrape traffic
does not dominate the counters.

Example excerpt:
```
# HELP http_requests_total Total HTTP requests by method, route template and status.
# TYPE http_requests_total counter
http_requests_total{method="GET",path="/health",status="200"} 3
# HELP http_request_duration_seconds HTTP request latency in seconds by method and route template.
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{method="GET",path="/health",le="0.005"} 3
http_request_duration_seconds_bucket{method="GET",path="/health",le="+Inf"} 3
http_request_duration_seconds_sum{method="GET",path="/health"} 0.004
http_request_duration_seconds_count{method="GET",path="/health"} 3
```

## On-demand fallback

When `GET /v1/{type}/{slug}` finds no local result, the service layer:
1. Queries the external API by slug/title
2. Persists the item to the local DB
3. Returns the item as if it had been found locally

If the item is not found in the external API either, returns `404`.

## Out of scope

- Direct messaging between users.
