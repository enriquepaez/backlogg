# Audit backend #3 — verificación de features 56-60 + production readiness ampliado

Fecha: 2026-08-24. Auditoría de solo lectura (`backlogg/`, `tests/`, `alembic/` no
modificados). Sigue a `progress/audit2_backend_2026-08-19.md`, que propuso las
features 56-60, ya marcadas `done` en `backend_feature_list.json`. No se
reintroduce el dominio de listas curadas — sigue fuera de scope.

Método: lectura completa del código real de cada feature (modelos, migraciones,
routes, services, tests) contrastado con su `acceptance`, más un pase de
production-readiness deliberadamente más amplio que el de audit2 (que se
centró en auth/CORS/rate limiting/IDOR/SQLi/N+1/índices/paginación/
transacciones): observabilidad, scheduler/sync, caché, moderación/admin,
exportación/borrado de datos, dependencias, config de despliegue y
consistencia docs↔código.

---

## Verificación features 56-60

Las 5 features cumplen genuinamente sus criterios de aceptación, verificado
contra el código real (no solo el flag `done`):

- **56 auth_recovery_rate_limiting** — las 5 rutas (`/auth/refresh`,
  `/auth/verify/request`, `/auth/verify/confirm`, `/auth/password/forgot`,
  `/auth/password/reset`) llevan `Depends(rate_limit_auth)`
  (`backlogg/users/routes.py:55,87,105,125,142`), mismo bucket que login/
  register, 429 con `Retry-After`. Test dedicado por ruta en
  `tests/users/test_rate_limit.py`.
- **57 notification_fanout_batching** — el bucle secuencial se reemplazó por
  un único `INSERT ... FROM SELECT`
  (`backlogg/notifications/repository.py:58-82`), un solo round-trip sea
  cual sea el número de followers. Test de regresión que cuenta llamadas a
  `db.execute` con 2 vs 25 followers (`tests/notifications/test_service.py:348-360`).
- **58 banned_user_immediate_revocation** — `get_current_user` rechaza con
  401 sin query extra (`backlogg/users/auth.py:104-108`). Tests explícitos
  en `tests/moderation/test_routes.py:244` y `tests/users/test_service.py:115`.
  Nota menor no bloqueante: `get_current_user_optional` no repite la
  comprobación, pero es solo-lectura y no otorga capacidad de escritura.
- **59 admin_key_constant_time_compare** — `hmac.compare_digest`
  (`backlogg/admin/auth.py:29,34`), test dedicado, tests preexistentes en
  verde.
- **60 library_entries_composite_index** — índice `(user_id, status)` vía
  migración reversible (`alembic/versions/0027_library_entries_composite_index.py`),
  reflejado en el modelo y en `docs/schema.md:722-731`.

Sin huecos en ninguna de las 5. El test de la 57 mide el número de queries,
no solo el resultado final — verificación real, no superficial.

---

## Nuevos hallazgos (production readiness)

### MEDIUM — El re-upload y el borrado de cuenta dejan huérfano el objeto R2 del avatar anterior

`backlogg/users/service.py:251-278` (`upload_avatar`) genera una key nueva
por cada subida y sobrescribe `avatar_url`, pero nunca borra el objeto R2 de
la key anterior (a diferencia de `delete_avatar:296-299`, que sí lo hace).
`delete_current_user:310-326` (borrado de cuenta) tampoco borra el avatar en
R2 antes de eliminar la fila del usuario — el cascade de Postgres borra la
fila, pero el objeto binario queda huérfano para siempre, sin ninguna
referencia en la DB que permita limpiarlo después. → **backend feature 61**
(`avatar_r2_orphan_cleanup`, pending).

### MEDIUM — El patrón "N recomputes secuenciales" que motivó la feature 57 sigue presente en ban/unban y en borrado de cuenta

`backlogg/moderation/service.py:37-54` (`set_user_banned`) y
`backlogg/users/service.py:310-325` (`delete_current_user`) recorren
`rated_items` en un bucle secuencial llamando a
`recalculate_item_aggregates` (SELECT + escritura) por item — mismo riesgo
de escalado (Render free tier) que llevó a batchear el fan-out de
notificaciones en la 57, sin corregir aquí. → **backend feature 62**
(`rating_aggregate_recalc_batching`, pending).

### MEDIUM — No hay auditoría persistida de acciones admin/moderación

Las acciones de alto privilegio (hide/unhide review, ban/unban, resolve
report, sync manual, grant/revoke-admin) están gateadas por `X-API-Key`/
`is_superadmin`, pero ninguna se persiste — el único rastro es el log JSON
efímero de stdout, no consultable ni con garantías de retención en Render.
→ **backend feature 63** (`admin_action_audit_log`, pending).

### LOW — `render.yaml` no declara buena parte de las variables de entorno que la app realmente necesita

Solo declara `DATABASE_URL`, `TMDB_API_KEY`, `TWITCH_CLIENT_ID/SECRET`,
`JWT_SECRET_KEY`. Faltan `ADMIN_API_KEY`, `CORS_ORIGINS`, 6 `SMTP_*`, 6
`R2_*`, `SENTRY_DSN` — todas con default silencioso, así que un deploy
nuevo desde el Blueprint no fallaría, pero moderación/sync manual, email
real y avatares quedarían apagados en silencio. No se convierte en feature
formal (es un cambio de configuración de una línea por variable, sin código
ni tests) — recomendado como ajuste directo de `render.yaml` cuando el
usuario lo pida.

### LOW — Documentación de rate limiting desactualizada tras la 56

`docs/operations.md:45,76` y `docs/api.md:275-276` siguen describiendo el
bucket de rate limit como si cubriera solo login/register, y los bloques de
`/auth/verify/*`, `/auth/password/*` y `/auth/refresh` en `docs/api.md` no
mencionan el `429`/`Retry-After` que ya devuelven. No baja ninguna feature
de "cumple" (el criterio de la 56 solo pedía actualizar docs si se añadía
un bucket *nuevo*, y se reusó uno existente), pero el texto actual es
incompleto. Ajuste de redacción, no se convierte en feature formal.

### LOW — Un par de endpoints "caros" siguen sin rate limiting propio

`POST /admin/sync/{type}` y `GET /recommendations` no tienen límite propio
más allá de X-API-Key/auth. Bajo impacto (no son vectores de abuso
anónimo); se deja como nota, no como feature — aplicar solo si se detecta
abuso real.

### LOW — No hay endpoint de exportación de datos, solo de borrado

`delete_current_user` cubre el derecho de supresión, pero no existe
portabilidad (`GET /users/me/export` o equivalente). Aceptable para un
proyecto personal sin usuarios sujetos a RGPD real; se deja como nota de
backlog futuro, no como feature ahora.

---

## No son hallazgos (verificado y correcto)

- **Observabilidad**: `backlogg/core/observability.py` redacta secretos
  recursivamente, correla logs por `request_id`, y un exception handler
  global captura cualquier excepción no controlada sin fugar detalles.
  `sentry-sdk[fastapi]` está realmente instalado y se inicializa si
  `SENTRY_DSN` está presente — no es un stub.
- **Métricas**: registro Prometheus propio con `path` siempre como plantilla
  de ruta, sin PII en labels.
- **Scheduler/nightly sync**: vive en GitHub Actions (no APScheduler
  in-process), con reintento si `errors > 0`, upserts idempotentes, y un
  job `verify` final. Cada fase envuelta en try/except independiente — un
  fallo puntual no aborta el resto.
- **Caché**: capa TTL in-process para `/trending`/`/genres`, más middleware
  HTTP de `Cache-Control`/`ETag` con reglas correctas `public` vs
  `private, no-store`.
- **TODO/FIXME/print()**: ninguno encontrado en `backlogg/`.
- **Dependencias**: `pyjwt` 2.13.0 y `python-multipart` 0.0.32 están por
  encima de los fixes de CVEs conocidas hasta el corte de conocimiento del
  agente auditor. Resto de dependencias en versiones recientes.
- **Dockerfile/entrypoint/render.yaml**: build multi-stage, usuario
  no-root, sin secretos hardcodeados, migraciones antes de levantar
  uvicorn, healthcheck declarado.
- **Moderación**: hide/unhide y ban/unban idempotentes, con 404 si no
  existen.
- **Avatar upload**: validación de `content_type` y tamaño máximo bien
  resuelta (413/422).
- **Índices y paginación**: `Query(ge=1, le=100)` consistente en los
  endpoints admin nuevos, sin listados sin cota.

---

## Verificación final

`bash init.sh` ejecutado al cierre: **950 tests pasan, ruff limpio, entorno
en verde** — sin ninguna modificación de este audit sobre el repo.
