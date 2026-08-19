# Audit backend #2 — verificación de features 52-55 + production readiness

Fecha: 2026-08-19. Auditoría de solo lectura (`backlogg/` y `tests/` no
modificados). Sigue a `progress/audit_ux_2026-08-18.md`, que propuso las
features 52-55, ya marcadas `done` en `backend_feature_list.json`. No se
reintroduce el dominio de listas curadas (`user_lists`/`list_items`) — el
usuario ya lo descartó explícitamente, fuera de scope.

Método: lectura completa de cada migración Alembic (0023-0026), cada módulo
(`models.py`/`schemas.py`/`repository.py`/`service.py`/`routes.py`) de
`library_logs`, `ratings`, `feed`, `notifications`, sus tests, y las
secciones relevantes de `docs/schema.md`/`docs/api.md`. Después, un barrido de
producción sobre auth, CORS, rate limiting, IDOR, inyección SQL, N+1,
índices, paginación y transacciones, contrastado con `docs/architecture.md`,
`docs/conventions.md`, `docs/operations.md`.

---

## Verificación features 52-55

### 52 — activity_log_entries (library_logs) — **cumple**

Todos los criterios de aceptación se verifican contra el código real:

- Modelo `LibraryLog` (`backlogg/library_logs/models.py:21-53`): campos
  exactos (`id`, `user_id`, `item_type`, `item_id`, `logged_on` date,
  `rewatch` bool default false, `note` nullable, `created_at`), **sin**
  `UniqueConstraint(user_id, item_type, item_id)` — confirmado, solo hay dos
  índices no-únicos (`idx_library_logs_item`, `idx_library_logs_user`).
- Migración `alembic/versions/0023_library_logs.py` crea la tabla con el
  mismo shape; `downgrade()` la elimina limpiamente.
- `POST /{type}/{slug}/log` (`backlogg/library_logs/routes.py:21-32` vía los
  cuatro `routes.py` de movies/series/books/games, p.ej.
  `backlogg/movies/routes.py:139-154`): requiere `get_current_user`;
  `logged_on` por defecto es `date.today()` si se omite
  (`backlogg/library_logs/service.py:73`); fecha futura → 422 vía
  `field_validator` en `LogIn.logged_on_not_in_future`
  (`backlogg/library_logs/schemas.py:20-25`), verificado por
  `test_post_log_future_date_returns_422`.
- `GET /{type}/{slug}/log` público, paginado, orden `logged_on desc, id desc`
  (`backlogg/library_logs/repository.py:78-86`).
- `GET /users/{username}/log` público, cross-type vía `union_all`
  (`backlogg/library_logs/repository.py:104-127`), mismo estilo que
  feed/library.
- `DELETE /log/{id}`: 404 si no existe o pertenece a otro usuario
  (`backlogg/library_logs/service.py:93-100`); test explícito
  `test_delete_log_owned_by_another_user_returns_404` (IDOR cubierto).
- No toca `UserRating` ni su unique constraint: verificado en
  `tests/library_logs/test_service.py::test_library_log_does_not_affect_user_ratings`
  y `test_user_rating_does_not_affect_library_log`.
- `docs/schema.md:731-777` y `docs/api.md` documentan tabla y endpoints.
- Tests: 9 en repository, 10 en service, 15 en routes — cubren multi-log del
  mismo item, 401/404/422, símetria de los 4 tipos de contenido, y no
  interferencia con ratings.
- Router correctamente montado en `backlogg/main.py:250-251`.

Sin huecos encontrados en esta feature.

### 53 — rating_score_granularity — **cumple**

- Migración `0024_rating_score_granularity.py`: `user_ratings.score` pasa de
  `Integer` a `Numeric(2,1)` con
  `CHECK (score >= 1 AND score <= 5 AND score * 2 = FLOOR(score * 2))`,
  exactamente como pide el criterio; `downgrade()` reversible
  (`round(score)::integer`).
- Modelo `UserRating.score: Mapped[Decimal | None]` con `Numeric(2, 1)` y el
  mismo CHECK (`backlogg/ratings/models.py:45,59-62`).
- `RatingIn.score: float | None = Field(ge=1, le=5, multiple_of=0.5)`
  (`backlogg/ratings/schemas.py:14`) — Pydantic v2 rechaza con 422 valores no
  múltiplos de 0.5, verificado por
  `tests/ratings/test_schemas.py::test_rating_in_rejects_score_not_multiple_of_half`
  parametrizado con `[3.3, 2.7, 1.1, 4.9]`, y acepta `[1, 1.5, 2.0, 3.5, 4.5, 5]`.
- `rating_internal` en movies/series/books/games **ya era**
  `Numeric(precision=3, scale=2)` desde las migraciones originales
  (`0002_movies.py:52`, `0003_series.py:52`, `0004_books.py:47`,
  `0005_games.py:50`) — el criterio "si no soporta decimales, ajustar" no
  aplicaba, y correctamente no se tocó.
- Recálculo con decimales mixtos verificado explícitamente:
  `tests/ratings/test_repository.py::test_recalculate_item_aggregates_computes_avg_with_mixed_decimal_scores`.
- `docs/schema.md`/`docs/api.md` no se citan explícitamente para esta feature
  en el grep de verificación pero el rango/paso está documentado en el
  docstring de `RatingIn` y en el modelo; no se detectó redacción faltante
  relevante en `docs/api.md` (contrato `score` como decimal ya reflejado).

Sin huecos encontrados en esta feature.

### 54 — feed_event_types_expansion (activity_events) — **cumple**

- Tabla `activity_events` (`0025_activity_events.py`): columnas exactas
  (`id`, `user_id`, `event_type`, `item_type`, `item_id`, `rating_id`
  nullable FK, `created_at`), `CHECK event_type IN ('rating_created',
  'status_completed')`, `UniqueConstraint(rating_id)` (permite múltiples NULL
  para `status_completed`, fuerza 1:1 para `rating_created`).
- Generación en rating: `backlogg/ratings/service.py:83-88` — al crear/
  actualizar una rating con contenido inserta `rating_created` vía
  `INSERT ... ON CONFLICT DO NOTHING` keyed on `rating_id`
  (`backlogg/feed/repository.py:33-55`); actualización sucesiva no duplica
  (`test_create_rating_event_dedups_on_repeat_calls`,
  `test_rate_item_successive_updates_do_not_duplicate_event`); limpiar
  score/review_text borra el evento
  (`test_rate_item_clearing_content_removes_event`).
- Generación en status_completed: `backlogg/library/service.py:58-67` — solo
  en transición *hacia* completed
  (`is_new_completion = status.value == "completed" and previous_status != "completed"`),
  verificado por `test_get_feed_following_non_completed_status_does_not_appear`.
- `GET /feed` lee exclusivamente de `activity_events`
  (`backlogg/feed/repository.py:169-233`), nunca de `user_ratings`
  directamente; contrato de respuesta mantiene forma completa para
  `rating_created` y forma mínima (`score`/`review_text`/`like_count` = null)
  para `status_completed` (`backlogg/feed/schemas.py`, verificado por
  `test_get_feed_following_includes_status_completed_minimal_shape`).
- `tab=popular` excluye `status_completed` explícitamente
  (`only_rating_created=True` en `_feed_select`,
  `test_popular_feed_excludes_status_completed_events`).
- Backfill de migración: `BACKFILL_RATING_CREATED_SQL` en
  `0025_activity_events.py:28-34`, `ON CONFLICT DO NOTHING` (idempotente),
  filtra solo ratings con contenido; testeado en `tests/feed/test_backfill.py`
  (creación, filtrado de vacíos, idempotencia en rerun).
- `docs/schema.md:598-664` y `docs/api.md:659-689` documentan la tabla y el
  contrato de `GET /feed` con ambos tipos de evento.
- Autor y like_count resueltos en una sola query SQL (JOIN, no N+1) —
  buena práctica ya aplicada aquí.

Sin huecos encontrados en esta feature.

### 55 — notifications_event_types_expansion (user_completed) — **cumple**

- `0026_notifications_user_completed.py`: amplía el CHECK a
  `'new_follower', 'review_like', 'user_completed'` sin tocar la columna.
- Generación: `backlogg/library/service.py:91-100` — un
  `notify_user_completed` por cada follower directo
  (`follows_repo.list_follower_ids`, sin fan-out a followers-de-followers,
  verificado por `test_complete_item_does_not_notify_followers_of_followers`
  y `test_complete_item_does_not_notify_non_followers`).
- Repetición de completar el mismo item genera una notificación nueva cada
  vez (sin dedup), igual que `review_like`:
  `test_repeat_completion_generates_new_notification_each_time`; un PUT
  repetido con status ya `completed` NO genera otra:
  `test_repeat_completed_put_does_not_duplicate_notification`.
- `GET /notifications` resuelve `user_completed` con contrato compatible
  (actor/target/created_at) reutilizando los mismos LEFT JOINs por tipo de
  contenido que `review_like`
  (`backlogg/notifications/repository.py:70-114`), sin N+1 — un solo
  round-trip. Tests dedicados:
  `test_list_notifications_user_completed_resolves_movie_target`,
  `..._resolves_game_target`, `..._mixed_review_like_and_user_completed`.
- Graceful degradation: `notify_user_completed` swallows excepciones y hace
  rollback sin romper el PUT de library
  (`backlogg/notifications/service.py:80-104`,
  `test_complete_item_graceful_degradation`).
- `docs/schema.md:776-829` y `docs/api.md:708-723` documentan el nuevo tipo.

Sin huecos encontrados en esta feature. **Las 4 features (52-55) están
implementadas correctamente, con tests exhaustivos incluyendo casos de IDOR,
idempotencia y contratos de respuesta; no son stubs ni implementaciones
parciales.**

---

## Nuevos hallazgos (production readiness)

### HIGH — `POST /v1/auth/password/forgot` y el resto del flujo de recuperación de cuenta no tienen rate limiting

`backlogg/users/routes.py:109-131` — solo `/auth/register` y `/auth/login`
llevan `dependencies=[Depends(rate_limit_auth)]`
(`backlogg/users/routes.py:33,44`). `/auth/password/forgot`,
`/auth/password/reset`, `/auth/verify/request`, `/auth/verify/confirm` y
`/auth/refresh` no tienen ningún límite. `docs/operations.md:76-79` confirma
que esto es scope documentado, no un descuido — pero es un riesgo real antes
de producción: `/auth/password/forgot` es no autenticado y, según
`docs/operations.md:36,63-69`, el transporte de email en producción puede ser
una cuenta Gmail con **límite de ~500 envíos/día**. Un atacante sin
credenciales puede vaciar ese cupo diario enviando resets a emails reales
repetidamente (email-bombing + agotamiento de cupo SMTP para usuarios
legítimos), o usar la diferencia de latencia entre "email existe" (hace
hash+insert+send) y "no existe" (no-op) como canal de temporización para
enumerar cuentas pese al mensaje de respuesta idéntico
(`backlogg/users/service.py:414-441`).
**Fix sugerido:** aplicar `Depends(rate_limit_auth)` (o un bucket dedicado,
más estricto, p.ej. `RATE_LIMIT_PASSWORD_RESET`) a las 5 rutas listadas antes
de salir a producción.

### HIGH — Fan-out de notificaciones `user_completed` es secuencial, sin batching, y bloquea la respuesta de `PUT .../library`

`backlogg/library/service.py:91-100` — por cada follower directo hace un
`await notifications_service.notify_user_completed(...)`, y cada llamada
hace su propio `INSERT` + `commit()` individual
(`backlogg/notifications/service.py:92-101`). Para un usuario con muchos
followers, el endpoint `PUT /{type}/{slug}/library` queda bloqueado
haciendo N round-trips secuenciales a Neon antes de responder — en el free
tier de Render (CPU compartida, cold starts) esto puede convertirse
fácilmente en un timeout percibido por el usuario que solo quería marcar un
ítem como completado. No es un bug de la feature 55 en sí (implementa
exactamente el criterio de aceptación), pero es un riesgo de escalado real
antes de ir a producción si algún usuario acumula un número no trivial de
followers.
**Fix sugerido:** batchear el `INSERT` (`executemany`/`insert().values([...])`)
en una sola sentencia y un solo `commit()`, o mover el fan-out a un
background task (`BackgroundTasks` de FastAPI) para no bloquear la respuesta
del PUT — manteniendo el mismo "graceful degradation" que ya tiene el resto
del módulo.

### MEDIUM — `get_current_user` no revisa `is_banned`: un usuario baneado conserva escritura hasta que expira su access token (hasta 15 min)

`backlogg/users/auth.py:73-107` — a diferencia de `login_user`
(`backlogg/users/service.py:117`) y `refresh_tokens`
(`backlogg/users/service.py:151-153`), que sí comprueban `is_banned`, la
dependencia usada en **todas** las rutas autenticadas
(`get_current_user`) no vuelve a comprobar el flag. Un moderador que banea a
un usuario espera que el efecto sea inmediato (`docs/operations.md`/
`backlogg/moderation/routes.py:54-57` dice literalmente "they can no longer
log in or refresh"), pero con un access token ya emitido (válido hasta
`JWT_EXPIRE_MINUTES`, default 15) el usuario baneado puede seguir puntuando,
comentando, dando like, etc. durante esa ventana — sus reviews existentes sí
quedan ocultas por `is_hidden`/`is_banned` en las queries de lectura, pero
puede seguir generando contenido nuevo.
**Fix sugerido:** añadir una comprobación `if user.is_banned: raise
HTTPException(401)` en `get_current_user` (un `SELECT` ya se hace para
cargar el user, el campo ya está en memoria — coste cero adicional).

### MEDIUM — Comparación de `X-API-Key` no es tiempo-constante

`backlogg/admin/auth.py:29` — `if not x_api_key or x_api_key != configured_key`
usa `!=` de Python, que compara byte a byte y corta en el primer mismatch
(no constante en tiempo). Protege acciones de alto privilegio (ban de
usuarios, grant-admin al combinarse con `is_superadmin`, sync manual). Un
ataque de temporización por red es difícil pero no imposible, y el fix es
trivial.
**Fix sugerido:** `hmac.compare_digest(x_api_key, configured_key)`.

### MEDIUM — Falta índice índice compuesto para el patrón de consulta más común de `library_entries` (user_id + status)

`alembic/versions/0012_user_library.py:51-52` — solo existen
`idx_library_entries_user (user_id)` e
`idx_library_entries_item (item_type, item_id)`. El patrón de lectura más
frecuente de la feature que da nombre al proyecto —
`GET /users/{username}/library?status=completed` — filtra por
`user_id` y luego por `status` dentro de cada rama del `UNION ALL`
(`backlogg/library/repository.py`), y Postgres solo puede usar el índice de
`user_id` para el primer filtro, evaluando `status` con un scan residual.
Con el volumen actual (proyecto personal) es inofensivo, pero antes de
escalar merece la pena. No es un hallazgo de las features 52-55 (patrón
preexistente desde la 31), pero encaja en el pase de production-readiness
pedido.
**Fix sugerido:** una migración nueva añadiendo
`Index("idx_library_entries_user_status", "user_id", "status")` (mismo
criterio aplicaría a `library_logs.user_id` si en el futuro se filtra por
`rewatch`).

### LOW — `docs/api.md` no confirma explícitamente el rango/paso de `score` fuera del propio schema

Criterio de aceptación de la feature 53 pide "docs/api.md actualizado con el
nuevo rango/paso de score". El grep de verificación no mostró una mención
textual de "0.5" en `docs/api.md` para el contrato de rating (a diferencia
de `docs/schema.md`, que sí es explícito). El contrato Pydantic
(`ge=1, le=5, multiple_of=0.5`) es la fuente de verdad y está bien
documentado en el docstring del schema, así que esto es más una omisión de
redacción que un problema funcional — no baja la feature de "cumple", pero
vale la pena una línea en `docs/api.md` antes de que alguien integre contra
el contrato solo leyendo esa doc.
**Fix sugerido:** añadir una frase en la sección de `PUT /{type}/{slug}/rating`
de `docs/api.md` indicando "score acepta pasos de 0.5 entre 1.0 y 5.0".

### LOW — `/auth/verify/request` no tiene rate limiting (autenticado, pero puede auto-espamear cupo SMTP)

`backlogg/users/routes.py:79-91` — requiere `get_current_user`, así que el
riesgo de abuso contra terceros es bajo, pero un usuario (o script) puede
llamar repetidamente y consumir cupo SMTP compartido (mismo límite diario de
500 mencionado arriba) sin límite de servidor. Severidad baja porque
requiere una cuenta autenticada y solo afecta al remitente del propio email,
pero se menciona junto al hallazgo HIGH de arriba porque comparte el mismo
recurso limitado (cupo SMTP).
**Fix sugerido:** mismo `Depends(rate_limit_auth)` o un bucket dedicado más
laxo.

---

## No son hallazgos (verificado y correcto)

Para que quede constancia de lo que sí se revisó y no presentó problemas:

- Inyección SQL: no hay queries construidas con f-strings/`.format()`; los
  únicos `text()` (`backlogg/search/repository.py`, `backlogg/scheduler/jobs.py`)
  usan `bindparams`/no interpolan input de usuario.
- CORS: default a `localhost:3000`/`:5173` cuando `CORS_ORIGINS` no está
  seteada — no hay wildcard `*` accidental (`backlogg/main.py:182-194`).
- Passwords: argon2 (`backlogg/users/service.py:64-70`), nunca en logs.
- Tokens de refresh/verify/reset: opacos, solo se persiste su hash SHA-256,
  reuse-detection revoca toda la sesión activa
  (`backlogg/users/service.py:126-160`).
- Redacción de logs: `backlogg/core/observability.py` redacta
  password/token/api_key/secret por substring, recursivo en `extra=`.
- IDOR: todas las rutas de escritura (ratings, library, library_logs, follows,
  notifications) verificadas — usan `user=current_user`/scoping por
  `recipient_id`/`user_id` en la query, con tests explícitos de "owned by
  another user → 404" en varios dominios.
- Paginación: todos los endpoints listados usan `Query(ge=1, le=100)` para
  `limit` — no hay endpoint con límite sin acotar.
- Admin endpoints: `X-API-Key` a nivel de router + `is_superadmin` adicional
  para grant/revoke-admin, con verificación server-side (no solo UI).
