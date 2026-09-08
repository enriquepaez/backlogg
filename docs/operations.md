# Operaciones — Runbook de producción

Comandos y procedimientos para operar backlogg en producción. Para el
contrato de la API ver `docs/api.md`; para verificar trabajo de desarrollo,
`docs/verification.md`.

## Topología de producción

- **Render** (free tier) — sirve la API. La instancia **duerme sin tráfico**:
  la primera petición tras un rato inactiva tarda ~50 s (cold start).
- **Neon** — PostgreSQL de producción.
- **GitHub Actions** — ejecuta el sync nocturno y el backfill. No hay
  schedulers embebidos en el proceso (la instancia dormida nunca los
  dispararía).

## ⛔ El `.env` local es intocable

El `.env` de desarrollo pertenece al usuario: contiene secretos reales, está en
`.gitignore` y **no es recuperable desde el repo** si se sobrescribe. Ningún
agente ni script debe generarlo, copiarlo ni sobrescribirlo
(`cp .env.example .env`, `>`/`>>`, `rm`, `mv`, etc. sobre `.env` están
prohibidos). Las plantillas se editan **solo** en `.env.example`. Para ejecutar
algo que necesite variables de entorno en local, cárgalas del `.env` existente
(`set -a; source .env; set +a`) sin reescribirlo.

## Configuración en Render

| Env var | Valor actual | Notas |
|---|---|---|
| ~~`SEED_TOP_N_GAMES`~~ | — | **Retirada en la feature 90.** Games se enumera a `seed_targets` (`scripts/seed_igdb_targets.py`) y se hidrata por diferencia, así que no hay cursor ni objetivo de wraparound. Mientras existió topó el catálogo de juegos en 10.000 sobre los ~31.988 que pasan el filtro. Se puede **borrar de Render**: el código la ignora (`extra="ignore"`) |
| `SEED_TOP_N_BOOKS` | 10000 | **Inerte para la siembra desde la feature 87** (`mode=dump` selecciona por los umbrales `BOOKS_SEED_MIN_*`, sin corte por número de ítems). Sigue viva para el camino por cursor: `sync_books` y `backfill_sync.py book`. ⚠️ Ahí 10.000 **se queda corto**: el filtro de la feature 73 entrega 18.874 obras, así que el cursor da la vuelta antes de recorrerlas todas. Si se usa ese camino, subirla a ≥ 18.874 (con `mode=dump` da igual) |
| `SEED_TOP_N_MOVIES` / `SEED_TOP_N_SERIES` | 10000 | **Inertes desde la feature 86.** El catálogo de movies/series lo define `TMDB_SEED_MIN_VOTES_*`, no un número de ítems. Se dejan puestas para que la config de Render y la del workflow de backfill sigan siendo idénticas |
| `TMDB_SEED_MIN_VOTES_MOVIES` / `_SERIES` | 25 | Umbral `vote_count` que **define** el catálogo de TMDB: 57.135 movies y 10.880 series |
| `TMDB_SEED_START_YEAR` / `_END_YEAR` | 1874 / (vacío) | Rango de años que trocea la enumeración `/discover`. Vacío = año actual + 1 |
| `TMDB_SEED_CONCURRENCY` | 8 | Peticiones TMDB en vuelo (`Semaphore`) en enumeración e hidratación; ≈32 req/s frente al límite de ~50 |
| `TMDB_SEED_MAX_ATTEMPTS` | 3 | Pasadas concluyentes que recibe un target antes de retirarse como no enlazable. Es lo que hace que `pending` converja a 0 y que la rotación de refresco llegue a ejecutarse |
| `SYNC_SLICE_SIZE` | 100 | Tramo por request de sync; >100 arriesga el timeout de ~15 min por request de Render |
| `SYNC_SLICE_SIZE_MOVIES` | ~350 | Override por tipo. Movies necesita ~318/noche para cubrir 57.135 ítems dentro de la ventana de caché de 6 meses de TMDB; con la ruta de escritura por lotes (feature 84) cabe de sobra en los ~15 min de Render |
| `SYNC_SLICE_SIZE_SERIES` | ~100 | Ídem; series necesita ~61/noche |
| `ADMIN_API_KEY` | (secret) | Protege `/v1/admin/*` |
| `CORS_ORIGINS` | (opcional) | Orígenes permitidos, comma-separated |
| `JWT_SECRET_KEY` | (secret) | Firma los JWT de `/v1/auth/*`. Sin configurar, `POST /v1/auth/register`/`login` fallan con 500 (PyJWT rechaza clave HMAC vacía) |
| `REFRESH_EXPIRE_DAYS` | 30 | Vida del refresh token; `JWT_EXPIRE_MINUTES` es el access corto (15) |
| `SMTP_HOST` | (config) | Host SMTP. **Vacío → `EmailSender` loguea el enlace en vez de enviar** (dev) |
| `SMTP_PORT` | 587 | Puerto SMTP (STARTTLS estándar) |
| `SMTP_USERNAME` | (config) | Usuario SMTP (opcional; si vacío no se hace `login`) |
| `SMTP_PASSWORD` | (secret) | Password/app-password SMTP. Nunca aparece en logs ni en respuestas de error |
| `SMTP_FROM_EMAIL` | (config) | Remitente del email. Default `no-reply@backlogg.local` |
| `SMTP_STARTTLS` | true | Usar STARTTLS antes del login/envío |
| `APP_BASE_URL` | (config) | Base pública para los enlaces de verificación/reset (`/verify-email?token=…`, `/reset-password?token=…`) |
| `EMAIL_VERIFY_EXPIRE_HOURS` | 24 | Caducidad del token de verificación de email |
| `PASSWORD_RESET_EXPIRE_HOURS` | 1 | Caducidad del token de reset de password |
| `RATE_LIMIT_AUTH` | 10/60 | Límite por IP de `POST /v1/auth/login` y `/v1/auth/register`. Formato `count/segundos` |
| `RATE_LIMIT_SEARCH_FALLBACK` | 20/60 | Límite por IP del fan-out externo de `/v1/search` (feature 17) |
| `RATE_LIMIT_DEFAULT` | 120/60 | Bucket general reutilizable por la interfaz de rate limiting |
| `LOG_LEVEL` | INFO | Nivel del logging estructurado JSON (DEBUG/INFO/WARNING/ERROR) |
| `SENTRY_DSN` | (secret) | DSN de Sentry. **Vacío → integración off** (no se importa `sentry-sdk`, sin overhead) |
| `R2_ENDPOINT_URL` | (config) | Endpoint S3-compatible del storage de avatares (Supabase Storage en prod). **Vacío → se construye desde `R2_ACCOUNT_ID`** (Cloudflare R2 real); relleno se usa tal cual |
| `R2_ACCOUNT_ID` | (config) | Solo necesario si `R2_ENDPOINT_URL` está vacío (Cloudflare R2 real) |
| `R2_ACCESS_KEY_ID` | (secret) | Access key S3 del proveedor de storage |
| `R2_SECRET_ACCESS_KEY` | (secret) | Secret key S3. Nunca aparece en logs ni en respuestas de error |
| `R2_BUCKET_NAME` | (config) | Bucket donde se guardan los avatares |
| `R2_PUBLIC_BASE_URL` | (config) | Base pública desde la que se sirven los avatares subidos |

Las variables del **incremental** (`TMDB_INCREMENTAL_*`, `TMDB_PROMOTION_YEARS`,
`IGDB_INCREMENTAL_*`) no están en esta tabla a propósito: el incremental nunca
corre dentro del servidor, sino en GitHub Actions contra Neon. Están
documentadas en la sección *Incremental del catálogo*.

El envío de email usa SMTP genérico de la stdlib (`smtplib`), sin dependencias
externas. `SMTP_PASSWORD` es un secreto: configúralo en Render como
*environment secret*. La app nunca lo escribe en logs ni lo incluye en
respuestas de error; un fallo de envío se registra con un mensaje genérico y el
endpoint responde igual (sin revelar si el email existe).

**Pruebas con Gmail (App Password):** requiere 2FA activado en la cuenta;
genera una *App Password* (16 caracteres) en la config de seguridad de Google.
Config: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_STARTTLS=true`,
`SMTP_USERNAME=<tu-gmail>`, `SMTP_PASSWORD=<app-password>`,
`SMTP_FROM_EMAIL=<tu-gmail>` (Gmail obliga a que el remitente sea tu propia
cuenta). Límite ~500 envíos/día. Para producción con dominio propio, basta con
cambiar las variables `SMTP_*` — el código no cambia.

## Configuración del frontend (`apps/web`)

No se despliega en Render (solo la API). Sea cual sea el hosting elegido,
las env vars de `apps/web/.env.example` deben fijarse ahí explícitamente —
todas caen a un default silencioso de desarrollo si se dejan vacías:

| Env var | Default si falta | Efecto en producción |
|---|---|---|
| `API_INTERNAL_URL` | `http://localhost:8000` | El frontend no llega a la API real |
| `SITE_URL` | `http://localhost:3000` | `metadataBase`/OG/canonical apuntan a localhost |
| `ADMIN_API_KEY` | (vacío) | Sección admin del frontend responde 503 (debe igualar el `ADMIN_API_KEY` del backend) |
| `AVATAR_PUBLIC_BASE_URL` | (vacío) | Avatares no se optimizan vía `next/image` (no rompe, solo se sirven sin optimizar) |

Y en el backend, `CORS_ORIGINS` (ver tabla arriba) debe incluir el origen
real de este despliegue del frontend, o las peticiones desde producción
serán bloqueadas por CORS.

### Rate limiting (feature 37)

Límites por IP en endpoints sensibles, configurables por env con formato
`count/segundos`:

- `RATE_LIMIT_AUTH` (`10/60`) — los 7 endpoints de `backlogg/users/routes.py`
  que dependen de `rate_limit_auth`: `POST /v1/auth/register`, `/login`,
  `/logout`, `/verify-email` (request + confirm) y `/forgot-password`/
  `/reset-password` (feature 56, recuperación de cuenta incluida desde
  audit2).
- `RATE_LIMIT_SEARCH_FALLBACK` (`20/60`) — fan-out externo de `/v1/search` (solo
  cuando no hay resultados locales; las consultas servidas localmente no
  consumen cupo).
- `RATE_LIMIT_DEFAULT` (`120/60`) — bucket general reutilizable por la interfaz.

Al exceder el límite la API responde `429` con header `Retry-After` (segundos) y
un body genérico (`"Too many requests. Please try again later."`) que **no filtra
la IP, los límites ni ningún estado interno**. El contador es in-process
(suficiente para una instancia de Render) tras una interfaz reemplazable: mover a
Redis solo requiere cambiar la factory `get_rate_limiter()`, sin tocar call
sites. El cliente detrás del proxy de Render se identifica por el primer hop de
`X-Forwarded-For`.

**Dónde cambiar los límites:**

- **En producción/entorno** — sobrescribe la env var correspondiente
  (`RATE_LIMIT_AUTH`, `RATE_LIMIT_SEARCH_FALLBACK`, `RATE_LIMIT_DEFAULT`) en
  Render o en tu `.env` (ver `.env.example`). No requiere redeploy de código.
- **Los defaults** viven en `backlogg/core/config.py` (clase `Settings`).
- **La lógica** (parser `count/segundos`, ventana deslizante, `Retry-After`,
  factory) está aislada en `backlogg/core/rate_limit.py`; el wiring está en
  `backlogg/users/routes.py` (auth) y `backlogg/search/service.py` (fallback).

### Observability (feature 38)

Logging estructurado en JSON con correlación por request ID e integración
opcional de Sentry. La lógica vive en `backlogg/core/observability.py`; el wiring
(configuración del logging, middleware y exception handler global) está en
`backlogg/main.py`. Los defaults de env viven en `backlogg/core/config.py`.

**Formato de log JSON.** Cada línea de log es un objeto JSON con un esquema
estable:

```json
{"timestamp": "2026-08-08T12:00:00+0000", "level": "INFO",
 "logger": "backlogg.request", "message": "request.completed",
 "request_id": "3f1c…", "method": "GET", "path": "/health",
 "status": 200, "duration_ms": 1.42}
```

- Campos base siempre presentes: `timestamp`, `level`, `logger`, `message`,
  `request_id`. Cualquier campo pasado vía `extra=` se añade tras redactarse.
- El nivel raíz se controla con `LOG_LEVEL`.
- Cada petición registra una línea `request.completed` con `method`, `path`,
  `status` y `duration_ms`.

**Request ID.** `RequestIDMiddleware` lee el header `X-Request-ID` entrante (o
genera un `uuid4`), lo propaga vía un `ContextVar` a **todos** los logs de esa
petición y lo devuelve en el header `X-Request-ID` de la respuesta. Las
excepciones no controladas las captura un `@app.exception_handler(Exception)`
global que las loguea correlacionadas con el request ID y responde `500` con un
body genérico (`{"detail": "Internal server error"}`) sin filtrar internals.

**Política de redacción.** El formatter nunca emite el valor de campos sensibles
(`password`, `api_key`, `token`, `authorization`, `x-api-key`, `refresh_token`,
`smtp_password`, `secret` — match por substring case-insensitive). Se aplica
tanto a los campos `extra` (recursivo en dicts/listas) como, best-effort, a los
pares `clave=valor` embebidos en el texto del mensaje. El valor se sustituye por
`***REDACTED***`.

**Sentry.** `init_sentry()` importa `sentry_sdk` de forma **perezosa** y solo
cuando `SENTRY_DSN` está presente; sin DSN no se importa nada (cero overhead). Si
el DSN está configurado pero el paquete no está instalado, se loguea un warning y
la app continúa sin error tracking.

### Avatar storage (feature 51 + refinamiento storage_s3_generalize)

`POST /v1/users/me/avatar` sube la imagen a un storage S3-compatible
configurable — no está atado a Cloudflare R2. `R2_ENDPOINT_URL` selecciona
el proveedor: vacío construye el endpoint real de R2 desde `R2_ACCOUNT_ID`;
relleno se usa tal cual y sirve para cualquier S3-compatible (MinIO en dev,
Supabase Storage en prod). Sin las credenciales completas, el endpoint
responde `503` de forma controlada (sin filtrar configuración) en vez de
fallar; ver `backlogg/users/service.py::_require_r2_configured`.

**Dev local — MinIO (Docker, sin cuenta):**

```bash
docker compose up -d minio minio-init   # arranca MinIO + crea el bucket "avatars" (público, idempotente)
```

Añade a tu `.env` (bloque comentado ya presente en `.env.example`):

```
R2_ENDPOINT_URL=http://localhost:9000
R2_ACCESS_KEY_ID=minioadmin
R2_SECRET_ACCESS_KEY=minioadmin123
R2_BUCKET_NAME=avatars
R2_PUBLIC_BASE_URL=http://localhost:9000/avatars
```

Consola web de MinIO (inspección manual del bucket): http://localhost:9001
(mismas credenciales `minioadmin`/`minioadmin123`).

> Se usa la imagen oficial `minio/minio`, no `bitnami/minio`: Bitnami dejó de
> publicar imágenes gratuitas actualizadas en 2026 (movidas detrás de una
> suscripción de pago). `minio-init` (imagen `minio/mc`) crea el bucket y lo
> hace público al arrancar porque la imagen oficial no tiene el equivalente
> del `MINIO_DEFAULT_BUCKETS` de Bitnami.

**Producción — Supabase Storage (free tier, sin tarjeta):**

1. Crea un proyecto gratis en [supabase.com](https://supabase.com) (no pide
   tarjeta).
2. **Storage → New bucket** → créalo público (ej. `avatars`).
3. **Project Settings → Storage → S3 Connection** → copia el endpoint S3,
   con forma `https://<project-ref>.supabase.co/storage/v1/s3`.
4. **Project Settings → Storage → Access Keys** (S3 Access Keys) → crea una
   key nueva → copia `Access Key ID` y `Secret Access Key` (la secret no se
   vuelve a mostrar).
5. Configura en Render:
   ```
   R2_ENDPOINT_URL=https://<project-ref>.supabase.co/storage/v1/s3
   R2_ACCESS_KEY_ID=<access key id>
   R2_SECRET_ACCESS_KEY=<secret access key>      # environment secret
   R2_BUCKET_NAME=<nombre-del-bucket>
   R2_PUBLIC_BASE_URL=https://<project-ref>.supabase.co/storage/v1/object/public/<bucket>
   ```
   `R2_ACCOUNT_ID` no hace falta con `R2_ENDPOINT_URL` configurado.

Si en el futuro se prefiere Cloudflare R2 real, basta con dejar
`R2_ENDPOINT_URL` vacío y rellenar `R2_ACCOUNT_ID` — el resto del código no
cambia.

## Secrets de GitHub Actions

| Secret | Usado por |
|---|---|
| `RENDER_API_URL` | nightly-sync.yml |
| `ADMIN_API_KEY` | nightly-sync.yml |
| `DATABASE_URL` (`postgresql+asyncpg://...`) | backfill-sync.yml, incremental-sync.yml |
| `TMDB_API_KEY` | backfill-sync.yml, incremental-sync.yml |
| `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` | backfill-sync.yml, incremental-sync.yml |

Añadir/rotar con `gh secret set <NOMBRE>` (valor interactivo, nunca en chat/logs).

## Sync nocturno

`.github/workflows/nightly-sync.yml` — cron `0 2 * * *` UTC. Hace wake-up de
la instancia (`GET /health`), llama a los 4 `POST /v1/admin/sync/{type}` en
secuencia (paralelo saturaba la instancia free) y verifica con
`GET /v1/admin/stats` que cada `last_synced_at` es reciente (< 2 h).

```bash
# Lanzarlo manualmente
gh workflow run nightly-sync.yml

# Ver el último run
gh run list --workflow=nightly-sync.yml --limit 3
```

Qué procesa cada run depende del tipo (feature 86):

- **`book`**: avanza el cursor de su tipo en `SYNC_SLICE_SIZE` items (tabla
  `sync_cursors`, compartida con el backfill). Es el **único** que queda por
  cursor desde la feature 90.
- **`movie`, `series` y `game`**: toman `SYNC_SLICE_SIZE_<TIPO>` targets
  pendientes de `seed_targets` (los que aún no tienen fila en `external_ids`)
  y, si no quedan, rellenan la rebanada con los ítems de `last_synced_at` más
  antiguo. No hay cursor: el campo `offset` de la respuesta es siempre `0` para
  estos tres tipos. `game` hidrata en bloques de hasta 500 ids por petición
  (`where id = (...)`), frente a una petición por ítem en TMDB.

**Desde la feature 88 el nocturno es también la red de seguridad.** La
frescura del catálogo la lleva ahora el incremental de las 09:00 UTC (sección
*Incremental del catálogo*), que pregunta a cada fuente qué ha cambiado. La
rotación por `last_synced_at` de `movie`/`series` **no se retira**: es lo único
que puede cubrir los días que `/movie/changes` y `/tv/changes` ya no conservan
(su historial es de 14 días y no más). Cambia de papel, no de existencia.

**El nocturno ya no refresca nada.** Hasta la feature 91 cada job terminaba con
`REFRESH MATERIALIZED VIEW CONCURRENTLY catalog_search`, y ese paso es
justamente el que dejó de caber en el techo de Neon (issue #28): construía una
copia completa de la vista —137 MB— antes de intercambiarla. La vista ya no
existe; `search_vector` es una columna generada `STORED` en `movies`, `series`,
`books` y `games`, que Postgres rellena dentro de la misma sentencia que
escribe la fila. Consecuencias operativas:

- No hay paso de refresco que pueda fallar, tardar o quedarse a medias, ni en
  el nocturno ni en el backfill ni en la siembra de dumps.
- **Desaparece la ventana de obsolescencia**: antes un ítem recién sincronizado
  no aparecía en `/v1/search` hasta el siguiente refresco. Ahora es visible en
  cuanto commitea la rebanada.
- Si en un log antiguo ves `failed to refresh catalog_search`, es anterior a
  esta feature.

### Despliegue de la migración `0038` — el orden importa

Es la migración que retira `catalog_search` y añade las cuatro columnas
generadas. **Añadir una columna generada `STORED` reescribe la tabla**: durante
la reescritura Postgres tiene en disco el heap viejo y el nuevo a la vez, y no
suelta el viejo hasta el `COMMIT`. `alembic/env.py` envuelve todo el `upgrade`
en **una** transacción, así que el `DROP MATERIALIZED VIEW` que abre la
migración **no libera nada mientras esta corre**.

Medido en la DB de dev (60.000 películas, vista de 25 MB, base de 62 MB):

| Momento | `DROP` dentro del `BEGIN` | `DROP` commiteado antes |
|---|---|---|
| inicio | 62 MB | 62 MB |
| tras el `DROP` | **62 MB** | 36 MB |
| pico, a mitad del `ALTER` | **93 MB** | **67 MB** |
| tras el `COMMIT` | 40 MB | 40 MB |

Mismo estado final; 26 MB de diferencia en el pico — exactamente el tamaño de
la vista. Proyectado a producción (385 MB, vista de 137 MB, tablas de contenido
~90 MB): **~557 MB si la vista se dropea dentro de la migración (no cabe en los
512) frente a ~420 MB si se dropea antes**.

```bash
# 1. Medir. El techo de Neon es por CLUSTER, no por base.
psql "$DATABASE_URL" -c "SELECT pg_size_pretty(sum(pg_database_size(datname))) FROM pg_database;"

# 2. Dropear la vista como sentencia propia, COMMITEADA, antes de desplegar.
#    A partir de aquí /v1/search devuelve 500 hasta que el paso 3 termine:
#    el código que sigue en Render consulta la vista. En free tier son minutos.
psql "$DATABASE_URL" -c "DROP MATERIALIZED VIEW catalog_search;"

# 3. Desplegar main. Render aplica 0038 (su DROP ... IF EXISTS ya es no-op).

# 4. Estadísticas para la nueva columna — el planner las necesita para elegir
#    el índice GIN. La reescritura deja ficheros nuevos, así que NO hace falta
#    VACUUM FULL (al contrario que en la feature 89).
psql "$DATABASE_URL" -c "ANALYZE movies, series, books, games;"

# 5. Volver a medir y comprobar el ahorro (~55 MB esperados).
```

Si el paso 3 aun así no cabe, los cuatro `ALTER TABLE ... ADD COLUMN
search_vector ... STORED` + sus `CREATE INDEX ... USING GIN` se pueden aplicar a
mano **uno por tabla, cada uno en su propia transacción** (la más pequeña
primero) y luego `alembic stamp 0038`. Eso baja el pico al de una sola
reescritura en vez de cuatro. El DDL exacto está en
`alembic/versions/0038_search_expression_index.py`.

Vuelta atrás: `alembic downgrade 0037` recrea la vista y sus tres índices
(incluido el único, sin el cual `REFRESH ... CONCURRENTLY` se niega a correr).
Necesita el mismo margen en sentido inverso, porque reconstruye los 137 MB de
la vista **mientras** las cuatro columnas generadas siguen existiendo.

#### Si el despliegue aborta después del `DROP` manual

Es el escenario realista, no el raro: entre el paso 2 y el paso 3 hay una
ventana en la que **`/v1/search` devuelve 500 y la migración no está aplicada**.
La migración corre en una sola transacción, así que si falta a mitad se
deshace entera: no hay estado intermedio. El único estado persistente es «la
vista no está».

Lo primero es saber en cuál de los dos casos estás:

```bash
psql "$DATABASE_URL" -c "SELECT version_num FROM alembic_version;"
```

- **Devuelve `0038`** → la migración sí entró y lo que falló es el arranque de
  la app. La vuelta atrás es `alembic downgrade 0037`, que recrea la vista por
  ti (ojo al margen: reconstruye 137 MB con las columnas generadas todavía
  puestas).
- **Devuelve `0037`** → la migración no entró. La DB está en el esquema
  anterior **menos la vista**, y ninguna herramienta te la va a devolver: el
  `downgrade` de la `0038` no se puede invocar desde `0037`. Hay que recrearla
  a mano.

**Antes de recrearla, decide.** Recrear la vista cuesta los 137 MB y deja el
cluster otra vez en 385 MB, es decir, de vuelta en el estado en el que la
migración *no cabe*: habría que volver a dropearla antes del siguiente intento.
Así que:

- Si el arreglo es de minutos (un fallo de build, una variable mal puesta),
  **no la recrees**: corrige y relanza el despliegue. `/v1/search` sigue caído
  ese rato y nada más se rompe (ver el apartado siguiente).
- Recréala solo si la vuelta va a durar horas o días y no puedes tener la
  búsqueda caída tanto tiempo.

DDL de recuperación — es el de la migración `0031`, que es la definición
vigente si la `0038` no entró. `CREATE MATERIALIZED VIEW` puebla la vista al
crearla (`WITH DATA` es el defecto), así que **no** hace falta ningún `REFRESH`
después:

```bash
psql "$DATABASE_URL" <<'SQL'
CREATE MATERIALIZED VIEW catalog_search AS
SELECT id, 'MOVIE' AS item_type, slug, title, overview, poster_url,
       release_date, rating_external, rating_internal,
       to_tsvector('simple', title || ' ' || regexp_replace(title, '[^a-zA-Z0-9\s]', '', 'g') || ' ' || COALESCE(overview, '')) AS search_vector
FROM movies
UNION ALL
SELECT id, 'SERIES', slug, title, overview, poster_url,
       first_air_date, rating_external, rating_internal,
       to_tsvector('simple', title || ' ' || regexp_replace(title, '[^a-zA-Z0-9\s]', '', 'g') || ' ' || COALESCE(overview, ''))
FROM series
UNION ALL
SELECT id, 'BOOK', slug, title, overview, poster_url,
       first_publish_date, rating_external, rating_internal,
       to_tsvector('simple', title || ' ' || regexp_replace(title, '[^a-zA-Z0-9\s]', '', 'g') || ' ' || COALESCE(overview, ''))
FROM books
UNION ALL
SELECT id, 'GAME', slug, title, overview, poster_url,
       release_date, rating_external, rating_internal,
       to_tsvector('simple', title || ' ' || regexp_replace(title, '[^a-zA-Z0-9\s]', '', 'g') || ' ' || COALESCE(overview, ''))
FROM games;

CREATE INDEX idx_catalog_search_vector ON catalog_search USING GIN (search_vector);
CREATE INDEX idx_catalog_search_type ON catalog_search (item_type);
-- Obligatorio: sin este índice único, REFRESH ... CONCURRENTLY se niega a
-- correr (migración 0007, feature 40).
CREATE UNIQUE INDEX uq_catalog_search_type_id ON catalog_search (item_type, id);
SQL
```

#### Qué pasa si el nocturno dispara en esa ventana

Entre el `DROP` manual y el despliegue, el código que corre en Render sigue
siendo el viejo: termina cada job con `REFRESH MATERIALIZED VIEW CONCURRENTLY
catalog_search` sobre una vista que ya no existe.

**No revienta el job.** La llamada está envuelta en su propio `try/except` que
solo loguea, y es la **última** sentencia del bloque de sesión en los tres
sitios (`sync_movies`/`sync_series`, `sync_books`, `sync_games`): lo que
escribió la rebanada ya está commiteado antes —`session.commit()` en la ruta de
`seed_targets`, y `_persist_cursor` commitea en las de books/games—, y después
del refresco solo se leen contadores en memoria. Lo mismo vale para el
`backfill_sync.py` (reusa los mismos jobs) y para el fan-out de `/v1/search`.

Consecuencia real: el job sincroniza y avanza su cursor con normalidad,
`POST /v1/admin/sync/{type}` devuelve 200 con sus contadores de siempre, la
verificación de `GET /v1/admin/stats` del workflow (`last_synced_at` < 2 h)
pasa, y en el log aparece una línea

```
failed to refresh catalog_search ... UndefinedTableError: relation "catalog_search" does not exist
```

que es ruido: ese refresco no iba a servir para nada de todos modos. **Lo único
que está roto en esa ventana es `/v1/search`**, y lo está desde el instante del
`DROP`, dispare o no el nocturno.

Aun así, para no mezclar señales al leer los logs del despliegue, conviene
elegir la ventana: el cron es `0 2 * * *` **UTC**
(`.github/workflows/nightly-sync.yml`), y el sync no corre in-process —lo
dispara GitHub Actions, porque en el free tier de Render APScheduler no
llegaría a ejecutarse—, así que basta con **hacer el `DROP` justo después de un
run nocturno**: eso da ~24 h de margen para desplegar sin que el cron se cruce.
Si hay que desplegar cerca de las 02:00 UTC, se puede desactivar el schedule
temporalmente (`gh workflow disable nightly-sync.yml`) y volver a activarlo
(`gh workflow enable nightly-sync.yml`) tras el paso 4.

### Targets retirados (`stuck`)

Un target puede ser **imposible de enlazar**, por dos motivos independientes:
TMDB responde 404 a un id enumerado, o el detalle se descarga bien y el ítem
aun así no consigue fila en `external_ids` (típicamente una colisión de slug:
dos ids de TMDB con el mismo título y año comparten una sola fila y solo uno
conserva su enlace — ver `docs/schema.md`).

> Antes de la migración `0036` (issue #20) `uq_external_id` no incluía
> `item_type`, así que un id de persona de TMDB bloqueaba la película o serie
> con el mismo número: era la causa masiva de `unlinkable`. La `0036` la
> arregla y **reabre** los targets afectados (`attempts = 0` en todo target sin
> enlazar que no sea 404), así que el primer `hydrate` posterior verá `pending`
> subir y `unlinkable` bajar. Eso es lo esperado y no hay que hacer nada.
> **Pero solo cubre lo que tenga fila en `seed_targets`** — ver el apartado
> siguiente antes de dar el catálogo por reparado.

### Ítems sin enlace que la `0036` **no** repara

La reparación de la migración se apoya en `seed_targets`, que es lo único que
recuerda qué ids quería el catálogo. Un ítem que entró por otra vía —el cursor
de `/popular`, el fan-out de búsqueda, `/similar`— **no tiene fila ahí**, así que
si perdió su enlace por el defecto del issue #20 se queda como estaba: fila en
`series`/`movies`/`books`, ninguna en `external_ids`.

Y no se autocura solo: `get_stale_catalog_external_ids` hace INNER JOIN contra
`external_ids`, así que la rotación de refresco **nunca visita** esos ítems, y
`get_credit_gaps` los descarta en `skipped_no_external_id`. Quedan congelados:
sin re-sync, sin créditos y sin volver a intentarlo.

Ojo con producción: `seed_targets` solo se puebla ejecutando la enumeración de
la feature 86, que estaba bloqueada por este mismo issue. Si allí la tabla está
vacía, el `UPDATE` de la `0036` actualiza **0 filas** y todo lo que se perdió
sigue perdido.

Medido en la DB de dev, ya en `0036`: 12 series sin enlace de 1.132 y 1 libro de
389 (movies y games, 0). Solo las 7 de 2022 tienen fila en `seed_targets`; las
otras 5 (`supernatural-2005`, `sesame-street-1969`, `kamen-rider-1971`,
`the-secret-life-of-the-american-teenager-2008`,
`operation-safed-sagar…-2026`) y `the-hobbit-1937` no. Es el 42% del residuo
observable.

Para medirlo, por tipo:

```sql
SELECT count(*) FROM series s WHERE NOT EXISTS (
  SELECT 1 FROM external_ids e WHERE e.item_type='SERIES' AND e.item_id=s.id);
```

(igual para `movies`/`MOVIE`, `books`/`BOOK`, `games`/`GAME`; y cambiando el
`count(*)` por `s.slug` se obtiene la lista.)

El id externo de esas filas **no es recuperable desde la base de datos**: nunca
llegó a escribirse. Recuperarlas exige un script que las vuelva a resolver por
título contra la fuente, o volver a enumerarlas. No existe todavía: hoy hay que
contarlas a mano con la consulta de arriba.

> **Estado 2026-09-04.** Esto dejó de ser un problema a resolver: producción no
> tiene datos reales y se borrará para sembrar desde cero con el esquema ya
> arreglado, con lo que estos huérfanos no llegan a existir (issue #21, cerrado
> por esa vía). Lo que sigue vigente es la limitación de fondo — un ítem que
> pierda su enlace no tiene camino de vuelta — y por eso se ataca por el otro
> lado: haciendo visible la pérdida en el momento en que ocurre (issue #22).

### Volver atrás de la `0036` — no se puede, y hay que saberlo antes de desplegar

La `0036` es una **puerta de un solo sentido** en cuanto la tabla contiene el
primer par `(source, external_id)` compartido entre dos `item_type`. Las dos
vías de vuelta atrás fallan, por motivos distintos:

- **Revertir el esquema** (`alembic downgrade`) no puede reconstruir el índice
  global: Postgres rechaza el `ALTER TABLE` nombrando el par duplicado. Es
  deliberado y está explicado en el docstring de la migración.
- **Revertir solo el código**, dejando el esquema nuevo, es *peor*: el
  `upsert_external_id` anterior a la `0036` resuelve por `(source, external_id)`
  sin `item_type` y termina en `scalar_one_or_none()`, que con dos filas lanza
  `MultipleResultsFound`. Verificado contra la DB de dev. Eso rompe el sync de
  los cuatro tipos y el fan-out de búsqueda: una caída, no un fallo silencioso.

La ventana en la que el rollback todavía es seguro va desde el despliegue hasta
el **primer sync que escriba un par cruzado**. A partir de ahí la única salida es
hacia delante: un fix nuevo, no una reversión. (Hoy el riesgo es nulo porque no
hay datos reales que perder; esta nota importa cuando los haya.)

Esos targets se **retiran** de la lista de trabajo: el 404 se sella la primera
vez que se observa, y el que resuelve bien pero no enlaza se retira tras
`TMDB_SEED_MAX_ATTEMPTS` pasadas concluyentes (default 3; una petición fallida
no cuenta, así que una caída de TMDB no retira nada sano).

**Por qué importa**: `pending` tiene que poder llegar a 0. La rotación de
refresco solo se dispara cuando no queda nada pendiente, y el bucle del backfill
solo termina cuando no queda nada pendiente. Sin la retirada, un suelo
permanente de targets atascados desactivaría la rotación —y con ella la ventana
de caché de 6 meses de TMDB— y dejaría el backfill girando sin progresar.

El residuo se reporta aparte, en `stuck`. Si crece de forma sostenida, mirar el
desglose: `gone` (404 en TMDB, normal en pequeñas cantidades) frente a
`unlinkable` (el detalle se descarga bien y el ítem sigue sin fila en
`external_ids`; desde la `0036` lo típico es una colisión de slug entre dos ids
de TMDB con el mismo título y año).

El progreso de movies/series se lee en la línea final del log del job
(`N targets still pending, M stuck: G gone, U unlinkable`) o directamente contra
la base de datos:

```bash
psql "$DATABASE_URL" -c "
SELECT st.item_type,
       COUNT(*) AS targets,
       COUNT(*) FILTER (WHERE ei.id IS NULL
                          AND st.unreachable_at IS NULL
                          AND st.attempts < 3)          AS pendientes,
       COUNT(*) FILTER (WHERE ei.id IS NULL
                          AND st.unreachable_at IS NOT NULL) AS gone,
       COUNT(*) FILTER (WHERE ei.id IS NULL
                          AND st.unreachable_at IS NULL
                          AND st.attempts >= 3)         AS unlinkable
FROM seed_targets st
LEFT JOIN external_ids ei
  ON ei.item_type = st.item_type
 AND ei.source = st.source
 AND ei.external_id = st.external_id
GROUP BY st.item_type ORDER BY st.item_type;
"
```

(El `3` es `TMDB_SEED_MAX_ATTEMPTS`; ajústalo si lo cambias en Render.)

## ⚠️ La `DATABASE_URL` de producción no está en `.env`

Cuesta un rato descubrirlo y lleva a apuntar sin querer a la base equivocada.

- **`.env` (local)** → el contenedor Docker `backlogg-db`. Es la DB de
  desarrollo. Un `psql "$DATABASE_URL"` desde el repo va **ahí**, no a Neon.
- **Producción** → solo en el dashboard de **Neon** y en las variables de
  **Render** (`render.yaml` la declara con `sync: false`, así que no vive en el
  repo). También está en el secret `DATABASE_URL` de GitHub Actions, pero los
  secrets de GitHub son de **solo escritura**: `gh secret list` da el nombre y la
  fecha, nunca el valor.

Dos trampas al usarla a mano:

1. Está guardada con el prefijo **`postgresql+asyncpg://`**, que es el dialecto
   de SQLAlchemy. `psql` responde `invalid connection option`. Hay que quitarle
   el `+asyncpg`.
2. Antes de ejecutar nada destructivo, comprueba contra qué base estás:

   ```bash
   psql "postgresql://…" -c "SELECT current_database(), count(*) FROM movies;"
   ```

   Si el número se parece al de tu catálogo de dev, es dev.

## Backfill del catálogo

`.github/workflows/backfill-sync.yml` ejecuta `scripts/backfill_sync.py`
directamente contra Neon y las APIs externas (sin pasar por Render ni su
timeout). Procesa tramos de 500 en bucle hasta wraparound del cursor o
presupuesto de tiempo (5 h por defecto; `timeout-minutes: 350` en el job).

```bash
# Sembrar la lista objetivo (movie/series por TMDB, game por IGDB) — hacerlo
# ANTES del primer hydrate de esos tres tipos
gh workflow run backfill-sync.yml -f content_type=movie -f mode=enumerate
gh workflow run backfill-sync.yml -f content_type=game  -f mode=enumerate

# Hidratar: bajar los ítems que la lista objetivo pide y el catálogo no tiene
gh workflow run backfill-sync.yml -f content_type=movie -f mode=hydrate
gh workflow run backfill-sync.yml -f content_type=game  -f mode=hydrate

# El único tipo con cursor (book): seed_top_n debe coincidir con Render
gh workflow run backfill-sync.yml -f content_type=book -f mode=hydrate -f seed_top_n=10000

# Ver los últimos runs y su estado
gh run list --workflow=backfill-sync.yml --limit 3

# Seguir el run más reciente en vivo
gh run watch

# Inspeccionar iteraciones y stop_reason de un run concreto
gh run view <run-id> --log | grep backfill
```

- `seed_top_n` **debe coincidir** con `SEED_TOP_N_BOOKS` en Render — si
  difiere, el cursor compartido haría wraparound antes de tiempo. Aplica **solo
  a `book`**: `SEED_TOP_N_MOVIES`/`_SERIES` son inertes desde la feature 86 y
  `SEED_TOP_N_GAMES` **ya no existe** desde la 90, así que pasarlo con
  `content_type=game` no hace nada (y ya no hay nada que descuadrar).
- El log termina con `stop_reason`: `wraparound` = objetivo alcanzado o API
  agotada (solo `book`); `exhausted` = el catálogo ya tiene todos los targets
  enumerados **trabajables** (movie/series/game; los retirados se reportan
  aparte en `stuck`); `time_budget` = relanzar el dispatch (reanuda desde el
  cursor o recalculando la diferencia contra el catálogo).
- Un error de API externa que persiste tras los reintentos deja el **run en
  rojo** (exit 1) con el cursor intacto — relanzar cuando la API se recupere.
- Los backfills de tipos distintos pueden correr **en paralelo**: tablas y
  APIs independientes, y desde la feature 91 tampoco hay ningún refresco de
  vista que serializar.

También ejecutable en local (usa el `DATABASE_URL` del entorno/`.env`):

```bash
uv run python scripts/seed_tmdb_targets.py movie          # enumeración TMDB
uv run python scripts/backfill_sync.py movie              # hidratación
uv run python scripts/seed_igdb_targets.py                # enumeración IGDB
uv run python scripts/backfill_sync.py game --slice-size 500 --time-budget-minutes 60
```

Defaults configurables por env: `BACKFILL_SLICE_SIZE` (500) y
`BACKFILL_TIME_BUDGET_MINUTES` (300).

### Enumeración de la lista objetivo (`mode=enumerate`)

Dos scripts, una tabla. Ambos **solo enumeran**: escriben `seed_targets` y no
piden ningún detalle ni escriben ninguna fila de catálogo.

- `scripts/seed_tmdb_targets.py <movie|series>` — recorre `/discover` con
  `vote_count.gte`, troceando por año de estreno.
- `scripts/seed_igdb_targets.py` — recorre IGDB por **keyset** (`id > N`,
  `sort id asc`) bajo la allowlist de `game_type` + `rating > 0` (feature 90).

```bash
uv run python scripts/seed_tmdb_targets.py movie
uv run python scripts/seed_tmdb_targets.py series --min-votes 50
uv run python scripts/seed_tmdb_targets.py movie --start-year 2000 --end-year 2026
```

- Coste: ~2.900 peticiones para movies y ~600 para series a ~32 req/s →
  **~2 minutos**. Barato y repetible.
- **Idempotente**: los targets se upsertan por `(item_type, source,
  external_id)` conservando su contador de intentos, así que re-enumerar solo
  añade lo que ha cruzado el umbral y refresca `vote_count`/`release_year`.
  Cada página se persiste según llega: un run interrumpido conserva lo hecho.
- Cuándo relanzarla: antes de la primera siembra, al cambiar
  `TMDB_SEED_MIN_VOTES_*`, y periódicamente para el barrido de promoción
  (ítems que estaban por debajo del umbral y lo han cruzado —
  `docs/seeding-plan.md` §6).
- **Exit code 2** = alguna ventana chocó con el tope de 500 páginas de TMDB
  incluso tras el troceo mensual. La lista enumerada está **incompleta**: hay
  que subir el umbral o añadir un nivel de troceo más fino antes de fiarse de
  ella. El log dice qué ventanas.
- Solo `movie`, `series` y `game`. Books tiene su **propio modo**
  (`mode=dump`, abajo) y el workflow lo rechaza aquí.

#### Games (`scripts/seed_igdb_targets.py`, feature 90)

```bash
uv run python scripts/seed_igdb_targets.py
uv run python scripts/seed_igdb_targets.py --start-after 100000   # reanudar
```

- **Coste medido, no estimado** (QA del 2026-09-09 contra IGDB y la DB reales):
  la enumeración entera son **64 páginas, 32.000 targets y 52 s** (el suelo
  teórico a 4 req/s son 16 s; el resto es latencia y el commit por página). La
  hidratación de esos 32.000 targets fueron **90 s, 0 errores y 0
  `skipped_links`**, y dejó **32.740 filas en `games`** —el conteo incluye lo
  que ya había entrado por búsqueda, on-demand e incremental—, **solo con tipos
  de la allowlist**. 31.988 juegos pasaban el filtro el 2026-09-08 y 32.000 el
  2026-09-09: el conjunto crece solo, unas decenas por día. 337.291 pasan solo
  la allowlist, y ese es el ruido que `rating > 0` excluye.
- **Cadencia recomendada: semanal**, y como mínimo mensual. Es una recomendación
  y no un `schedule:` porque hoy la lanza el operador (automatizarla es el
  **issue #34**). El razonamiento: dos minutos y medio de reloj, 128 peticiones
  en total e idempotente es tan barato que no hace falta apurar, y la
  contrapartida de espaciarla sí se nota — este script es la **única** vía por
  la que un juego que gana su primera valoración entra al catálogo, así que el
  retraso de la promoción es exactamente el hueco entre dos ejecuciones. Semanal
  deja ese hueco en 7 días y no compite con nada: sobre una lista ya sembrada la
  enumeración solo añade el delta (decenas de targets), que el nocturno absorbe
  en su siguiente pasada sin desplazar a la rotación de refresco. Ejecutarla
  **siempre** además, sin esperar a la fecha, en dos casos: antes de la primera
  siembra y después de tocar el filtro (`ALLOWED_GAME_CATEGORY_IDS` o el umbral
  `rating > 0`), porque ahí el delta no son decenas sino el catálogo entero.
- **Keyset y no offset**, aunque el offset de IGDB funcione hasta el final (no
  hay tope de 500 páginas como en TMDB): `rating > 0` cambia sin que nadie
  publique nada — basta con que alguien vote — y un offset sobre un conjunto
  que se mueve se salta ítems en silencio. Es el mismo motivo por el que se
  retiró el recorrido de `/popular` (`docs/seeding-plan.md` §1).
- Idempotente igual que el de TMDB, y **es también la vía de promoción**: un
  juego que no tenía valoración cuando se sembró y ahora la tiene entra
  re-lanzando este script. El nocturno ya no recorre ningún ranking. La
  diferencia con TMDB no es el mecanismo sino el disparador: el barrido de
  promoción de movies/series corre solo, como carril del incremental diario
  (`_incremental_promotion`); el de games lo lanza una persona. Issue #34.
- La allowlist de `game_type` se comprueba **dos veces**: en el `where` de la
  enumeración y otra vez sobre el payload al hidratar (`sync_games`). Un target
  enumerado como `MAIN_GAME` y reclasificado a `BUNDLE` antes de hidratarse no
  se escribe, y el log lo dice. Si la reclasificación le ocurre a un juego que
  **ya está en el catálogo**, se refresca igual y no se retira: hay bibliotecas,
  ratings y reseñas apuntando a esa fila, y borrarla sería un efecto colateral
  de un refresco nocturno. El log lo avisa (`reclassified`) para que el
  operador lo vea y decida.
- **Exit code 2** = el recorrido se atascó (una página devolvió un id que no
  supera el cursor, imposible con `sort id asc`). La lista está incompleta.

### Siembra de libros desde los dumps de Open Library (`mode=dump`)

`scripts/seed_openlibrary_books.py` siembra **todo** el catálogo de libros desde
los dumps mensuales de Open Library. A diferencia del enumerador de TMDB, este
script sí escribe las filas del catálogo: el dump trae todos los campos, así que
no queda ninguna petición de detalle por ítem que planificar — **cero** llamadas
HTTP por libro y por autor, frente a las dos que hacía la siembra por
`search.json`.

```bash
# Todo el pipeline desde Actions
gh workflow run backfill-sync.yml -f content_type=book -f mode=dump

# Una sola fase (p. ej. repetir solo la escritura, que es idempotente)
gh workflow run backfill-sync.yml -f content_type=book -f mode=dump -f dump_phase=load

# En local
uv run python scripts/seed_openlibrary_books.py
uv run python scripts/seed_openlibrary_books.py --phase editions --force
```

**Las cinco fases y su coste.** Medido el 2026-09-04 contra los dumps reales
(`ol_dump_2026-08-31`) desde una línea doméstica hacia archive.org.

⚠️ **El run es limitado por ancho de banda, y el ancho de banda de archive.org
varía muchísimo**: la misma pasada de editions se midió en **35 min** a las
15:00 y en **~100 min** a las 19:00 del mismo día, con el mismo código y la
misma línea (6,3 MB/s de pico medido con una descarga de 200 MB). Planifica con
el número alto, no con el bajo. Los tamaños de dump son además un **suelo**:
crecen todos los meses.

| Fase | Dump que descarga | Líneas leídas | Tiempo | Pico de RSS | Artefacto que deja |
|---|---|---|---|---|---|
| 1 `reading-log` | 0,12 GB | 12.838.026 | **61 s** | **444 MB** | `readinglog_counts.tsv.gz` — 399.259 obras, **1,4 MB** |
| 2 `editions` | **12,59 GB** | 56.728.501 | 35-125 min | **574 MB** | `selected_works.jsonl.gz` — **19.221 obras elegidas**, **1,7 MB** |
| 3 `works` | 4,06 GB | 41.591.088 | ~14 min | < fase 2 | `work_records.jsonl.gz` |
| 4 `authors` | 0,78 GB | 15.412.139 | ~3 min | < fase 2 | `author_names.tsv.gz` |
| 5 `load` | — | — | minutos | acotado por `BULK_LOAD_BATCH_SIZE` | ninguno: es un upsert idempotente |
| **Total** | **~17,5 GB transferidos** | | **~1-2,5 h** | **574 MB** | **~3 MB tras las dos primeras fases** |

Las fases 1 y 2 están medidas con el código de esta rama contra el dump
`2026-08-31` (`resource.getrusage`, pasada completa). Las fases 3 y 4 llevan el
tiempo medido de una pasada equivalente sobre los mismos ficheros; su memoria es
trivialmente menor porque trabajan sobre las 19.221 obras elegidas, no sobre las
399.259 de la whitelist.

**Contraste que importa**: la fase 2 selecciona **19.221** obras aplicando el
filtro de la feature 73 sobre el dump; `search.json` daba **18.874** con el mismo
filtro sobre un índice un mes más nuevo. **+1,8 %**: el catálogo que sale de los
dumps es el mismo que salía de Solr.

**Disco: el pico es el `--work-dir`, no el dump.** Un runner de GitHub Actions
tiene ~14 GB libres y el dump de editions solo ya son 12,59 GB, así que el
pipeline **no escribe ni un byte de dump a disco**: cada fase es `httpx.stream`
+ `gzip` sobre el socket. Lo único que toca el disco son los artefactos:
**3,1 MB medidos** tras las dos primeras fases, y del orden de 10 MB al acabar
las cuatro. Los 17,5 GB son tráfico de red, no almacenamiento.

**Memoria: 574 MB de pico, medidos.** Está en la fase 2 y lo acota la whitelist
de la fase 1: se agregan solo las 399.259 obras con `readinglog_count >= 5`, no
los 41.591.088 registros de obra del corpus ni los 56.728.501 de edición. De
esas 399.259, **392.466 tienen al menos una edición** y solo 19.221 pasan el
filtro, así que las fases 3-5 trabajan sobre dos órdenes de magnitud menos y su
memoria es irrelevante. Sobra sitio de largo en los 16 GB de un runner.

**Reanudable por fases.** Cada fase se salta si su artefacto ya está en el
`--work-dir` (`--force` lo rehace), y los artefactos se escriben a `.tmp` +
`rename`, así que un run muerto a medias nunca deja un artefacto truncado del
que fiarse. La fase 5 no necesita artefacto porque es un upsert: repetirla es
seguro por construcción.

En Actions el `--work-dir` se guarda **siempre** en la caché del repo al
terminar el job (falle o no), pero **solo se restaura si pides `-f
resume=true`**:

```bash
# Run normal: siempre empieza del dump del mes en curso
gh workflow run backfill-sync.yml -f content_type=book -f mode=dump

# Continuar el run anterior que murió en la fase 3 (no vuelve a bajar los 12,59 GB)
gh workflow run backfill-sync.yml -f content_type=book -f mode=dump -f resume=true
```

⚠️ Restaurar es opt-in **a propósito**. Si la caché se restaurase siempre, un
`mode=dump` normal lanzado con la caché del mes pasado todavía viva se saltaría
las cuatro fases y **resembraría el catálogo de un dump viejo sin decir nada**.
Con `resume=true` la decisión es del operador y está escrita en el dispatch.
Ojo también: si un run resumido termina y el mes ha cambiado, mezclarías dos
dumps — para eso está `-f force_phase=true`, que rehace la fase pedida.

- **Exit code 2** = el run terminó **degradado**: 0 libros escritos, filas
  rechazadas por el cargador, credits rechazados o `external_ids` que no se
  pudieron enlazar. Un catálogo parcial no se reporta como run verde.
- **Cuándo relanzarlo**: cuando Open Library publica un dump nuevo (mensual). El
  incremental fino entre dumps es la feature 88.
- **archive.org corta conexiones.** En el run medido, la fase 3 murió a los 4 s
  con `ConnectError: Connection reset by peer` justo después de dos horas
  descargando editions. El pipeline reintenta hasta 3 veces **mientras no haya
  entregado ninguna línea** (abrir el stream es gratis de repetir); un corte a
  media descarga **no** se reintenta, porque gzip no tiene punto de rebobinado y
  releer duplicaría el dump. Ese caso se arregla relanzando con `-f resume=true`:
  vuelve a hacer solo la fase que se cayó.
- Esto **no** sustituye al sync nocturno de libros: `sync_books` sigue sobre
  `search.json` con su cursor, igual que antes. Esta feature cambia la
  **siembra**, no el camino de la petición.

### Los cuatro modos: `enumerate`, `dump`, `hydrate` y `credits`

El workflow tiene un input `mode`. Resuelven problemas distintos y **no** se
sustituyen entre sí:

| | `enumerate` (movie/series/game) | `dump` (book) | `hydrate` (por defecto) | `credits` (`--only-missing-credits`) |
|---|---|---|---|---|
| Lista de trabajo | movie/series: `/discover` por año bajo `vote_count.gte`; game: keyset de IGDB bajo la allowlist de `game_type` + `rating > 0` | los dumps mensuales enteros, filtrados por los umbrales `BOOKS_SEED_MIN_*` | movie/series/game: targets de `seed_targets` sin fila en `external_ids`; book: listado de populares por offset | query local: ítems del catálogo **sin ninguna fila en `credits` ni en `item_cast`** (feature 89: «tiene personas» vive en dos tablas), unida a `external_ids` |
| Estado entre runs | la propia tabla `seed_targets` | un artefacto por fase en `--work-dir` (en Actions, la caché del repo) | movie/series/game: ninguno (diferencia en vivo); book: cursor en `sync_cursors` | ninguno; recalcula el hueco en cada run |
| Llamadas HTTP por ítem | 0 (20 ítems por petición en TMDB, 500 en IGDB) | **0**: cuatro descargas para todo el catálogo | **una** en TMDB (`/{tipo}/{id}?append_to_response=credits,external_ids`); **1/500** en IGDB (`where id = (...)`) | **una**: `/movie/{id}/credits`, `/tv/{id}?append_to_response=credits` o el work detail de Open Library |
| Escribe la fila del ítem | **no**: solo la lista objetivo | sí (upsert completo, con géneros y credits de autoría) | sí (upsert completo) | **no**: la fila ya existe, solo faltan sus credits |
| Condición de parada | ventanas agotadas (TMDB) / filtro agotado (IGDB) | las cuatro pasadas terminan | `pending == 0` (movie/series/game; los targets retirados no cuentan), wraparound del cursor (book) o `--time-budget-minutes` | lista de huecos agotada o `--time-budget-minutes` |
| Para qué sirve | decidir **qué** quiere el catálogo | sembrar el catálogo de libros entero | bajar lo que falta | cerrar agujeros de credits (issue #15) |
| Tipos que acepta | `movie`, `series`, `game` | **solo `book`** | los cuatro | todos menos `game` |

**Dos formas de sembrar, no cuatro** (feature 90). Aunque el workflow tenga
cuatro *modos*, las maneras de llenar el catálogo son dos: **lista objetivo**
(`enumerate` + `hydrate`) para movies, series y games, y **dumps mensuales**
(`dump`) para books. `credits` no siembra nada — repara un hueco de un catálogo
que ya existe.

**Cuándo usar cada uno.** Si el catálogo de movies/series/games está vacío o el
filtro ha cambiado, `enumerate` primero y `hydrate` después. Si el que está
vacío es el de **libros**, `dump`: siembra el catálogo entero de una vez y sin
tocar `search.json` (`hydrate` sobre `book` sigue existiendo, pero es el camino
lento por cursor y su tope es `SEED_TOP_N_BOOKS`). Si faltan
*ítems*, `hydrate`. Si los ítems están pero les faltan *credits*, `credits`:
`hydrate` no cierra ese hueco (issue #15) — con la lista objetivo ya
hidratada, `pending` es 0 y el run termina de inmediato sin tocar los ítems
incompletos.

```bash
# Cerrar el hueco de credits de series desde Actions
gh workflow run backfill-sync.yml -f content_type=series -f mode=credits

# En local
uv run python scripts/backfill_sync.py series --only-missing-credits
uv run python scripts/backfill_sync.py movie --only-missing-credits --recheck
```

Resumen final del modo `credits` (una línea de log al terminar):
`considered`, `processed`, `with credits`, `stamped without credits`,
`credits written`, `people_errors`, `skipped (no external id)`, `elapsed`.
`stop_reason` es `exhausted` (hueco cerrado) o `time_budget` (relanzar; el
siguiente run recalcula el hueco restante).

- **`credits_synced_at`** (columna en `movies`/`series`/`books`) marca los
  ítems cuyos credits **ya se consultaron con éxito**, tengan o no credits.
  Sin ese marcador, un ítem que legítimamente no tiene credits en TMDB
  (`cast`/`crew` vacíos) volvería a intentarse en cada run para siempre. Un
  fetch que **falla** no sella nada y suma a `people_errors`: se reintenta en
  el siguiente run.
- **`--recheck`** ignora el marcador y vuelve a barrer también los ítems ya
  sellados. Úsalo solo si sospechas que la fuente ha añadido credits desde el
  último barrido, o tras arreglar un bug de mapeo; en operación normal
  **no** hace falta y multiplica el coste del run.
- **`game` está fuera**: los juegos no tienen ingestión de credits de
  personas (solo company credits, que viajan dentro del propio payload del
  ítem). El CLI y el workflow rechazan el combo con un error explícito en vez
  de ejecutar un run vacío.
- **`skipped_no_external_id`**: ítems sin `external_ids` de la fuente que
  toca. No se pueden trabajar (no hay id que pedir) y no rompen el run; si el
  número es alto, el problema está en la ingestión, no en el backfill.
- Ningún modo refresca nada: la vista `catalog_search` desapareció en la
  feature 91 y la búsqueda lee `search_vector` directamente de las cuatro
  tablas de contenido.

### Cobertura de credits: medir antes y después

```bash
psql "$DATABASE_URL" -c "
SELECT 'MOVIE' AS item_type, COUNT(*) AS total,
       COUNT(*) FILTER (WHERE c.item_id IS NULL) AS sin_credits,
       COUNT(*) FILTER (WHERE m.credits_synced_at IS NOT NULL) AS sellados
FROM movies m
LEFT JOIN (SELECT DISTINCT item_type, item_id FROM credits) c
       ON c.item_type = 'MOVIE' AND c.item_id = m.id
UNION ALL
SELECT 'SERIES', COUNT(*),
       COUNT(*) FILTER (WHERE c.item_id IS NULL),
       COUNT(*) FILTER (WHERE s.credits_synced_at IS NOT NULL)
FROM series s
LEFT JOIN (SELECT DISTINCT item_type, item_id FROM credits) c
       ON c.item_type = 'SERIES' AND c.item_id = s.id
UNION ALL
SELECT 'BOOK', COUNT(*),
       COUNT(*) FILTER (WHERE c.item_id IS NULL),
       COUNT(*) FILTER (WHERE b.credits_synced_at IS NOT NULL)
FROM books b
LEFT JOIN (SELECT DISTINCT item_type, item_id FROM credits) c
       ON c.item_type = 'BOOK' AND c.item_id = b.id;
"
```

Un hueco que no baja tras un run `exhausted` con `people_errors = 0` y
`skipped_no_external_id = 0` significa que esos ítems **no tienen credits en
la fuente**: quedan sellados y ya no vuelven a entrar en la lista.

## Incremental del catálogo

Feature 88. Es lo que impide que el catálogo se congele el día de la siembra:
sin él no entran estrenos y no promocionan los ítems que cruzan
`vote_count >= 25` a posteriori. **No es un barrido**: le pregunta a cada
fuente qué ha cambiado desde la última vez y escribe solo eso.

### Cómo se dispara

`.github/workflows/incremental-sync.yml`, cron **`0 9 * * *`** (diario, 09:00
UTC), más `workflow_dispatch`. Corre `scripts/incremental_sync.py` **directo
contra Neon**, no contra Render: el fichero diario de IDs de TMDB son 28 MB gz
y una edición de dump de Open Library son 17,5 GB, y la instancia free duerme y
corta a ~15 min. **No hay endpoint admin para esto** y por eso `bruno/` no lo
recoge.

Por qué a las 09:00 y no en el nocturno de las 02:00: TMDB publica el fichero
del día **~08:00 UTC**, así que un run a las 02:00 recibiría un 404 y
reprocesaría el de ayer. Por qué **diario**: las dos vías de TMDB tienen
granularidad de día, y correr a diario deja 13 días de margen antes de que la
retención de 14 días de `/changes` muerda.

```bash
# Lanzarlo manualmente (las cuatro fuentes)
gh workflow run incremental-sync.yml

# Una sola fuente
gh workflow run incremental-sync.yml -f source=game

# Re-diffear una edición de dump que la marca ya cubre (idempotente, no gratis)
gh workflow run incremental-sync.yml -f source=book -f force_book=true

# Ver los últimos runs / seguir el más reciente
gh run list --workflow=incremental-sync.yml --limit 5
gh run watch "$(gh run list --workflow=incremental-sync.yml --limit 1 --json databaseId -q '.[0].databaseId')"

# En local (usa la DATABASE_URL del entorno; NO toca .env)
uv run python scripts/incremental_sync.py --source movie
uv run python scripts/incremental_sync.py --skip book
```

**Códigos de salida**: `0` limpio · `2` **degradado** (una fuente falló o hubo
ítems rechazados; el workflow lo convierte en una anotación de *warning*, no en
un job rojo, porque un incremental parcial sigue siendo mejor que ninguno y la
marca de la fuente caída **no avanzó**) · `1` el run no se pudo hacer (job
rojo).

### Qué corre cada fuente

| Fuente | Carriles | Marca de agua (`sync_watermarks`) |
|---|---|---|
| `movie` / `series` | alta inmediata por fecha (fichero diario de IDs) · barrido de promoción (`/discover`) · re-hidratación (`/changes`) | `TMDB/DAILY_ID_EXPORT/{MOVIE,SERIES}` y `TMDB/CHANGES/{MOVIE,SERIES}` |
| `game` | `where created_at > X` (altas, con la allowlist de `game_type`) · `where updated_at > X` (refresco de lo ya catalogado) | `IGDB/CREATED_AT/GAME` y `IGDB/UPDATED_AT/GAME` |
| `book` | diff del dump mensual contra el catálogo; **no descarga nada** si la edición publicada es la ya diffeada | `OPEN_LIBRARY/MONTHLY_DUMP/BOOK` |

Una fuente que falla **no aborta las demás** (C19), y su marca no avanza, así
que el run siguiente vuelve a cubrir ese tramo.

### Variables

Todas son de **entorno del workflow / del script**, no de Render: el servidor
nunca ejecuta el incremental in-process.

| Env var | Default | Notas |
|---|---|---|
| `TMDB_INCREMENTAL_MAX_AGE_DAYS` | 90 | Días hacia atrás que la puerta de estreno admite un ID nuevo. Ancho para que un run caído dos semanas siga recogiendo lo que perdió |
| `TMDB_INCREMENTAL_HORIZON_DAYS` | 180 | Días hacia adelante. Más allá es un anuncio, no un estreno |
| `TMDB_INCREMENTAL_MAX_EXPORT_GAP_DAYS` | 7 | Atraso máximo del fichero base antes de **re-baselinear** en vez de difear. Difear contra un fichero de hace un mes cuesta N veces las peticiones de detalle |
| `TMDB_PROMOTION_YEARS` | 10 | Años recientes que re-enumera el barrido de promoción. **Ventanas planificadas == este número**, salvo que `TMDB_SEED_START_YEAR` recorte el rango por abajo. El `windows` del resumen puede salir **mayor**: una ventana anual que supere las 500 páginas de `/discover` se parte en sus doce meses y cada mes cuenta como ventana |
| `IGDB_INCREMENTAL_LOOKBACK_DAYS` | 7 | Ventana del arranque en frío sin marca. Evita `created_at > 0`, que es la base entera de IGDB |
| `IGDB_INCREMENTAL_MAX_ITEMS` | 2000 | Techo por carril y por run. Tocarlo no pierde nada: el orden es ascendente y la marca avanza al último visto |

Secrets que consume el workflow: `DATABASE_URL`, `TMDB_API_KEY`,
`TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` (los mismos de `backfill-sync.yml`).

### Qué mirar

1. **Que corrió**: `last_run_at` de cada fila de `sync_watermarks` (query
   abajo). Es la señal de frescura; `cursor_value` es otra cosa.
2. **Que la puerta no rechaza todo**: en el log del carril de estrenos,
   `gate_reasons`. Un run con `admitted: 0` y `gate_reasons` repartido es una
   puerta trabajando; uno con todo en `no_release_date` es un payload que
   cambió de forma.
3. **`uncovered_days` en el carril de `/changes`**: si aparece, hubo días que
   TMDB ya no puede responder (ver abajo).
4. **`truncated_windows` en el carril de `/changes`**: un día concreto declaró
   más de 500 páginas y `/changes` no admite granularidad menor que el día, así
   que se recorrieron las 500 primeras y **el resto de ese día no se cubrió**.
   `truncated_labels` dice cuáles. La marca de agua se queda en el día anterior
   (no se finge cobertura) y el carril para ahí: esos ítems los refresca el
   barrido nocturno. Con ~73 páginas/día en movies esto no debería salir nunca;
   si sale, TMDB creció 6,8× o el tope cambió.
5. **`skipped_links`** (issue #22): filas escritas cuya terna
   `(item_type, source, external_id)` ya pertenecía a otro ítem — invisibles
   para toda búsqueda por id a partir de ahí.
6. **`saturated: true`** en un carril de IGDB: tocó el techo de
   `IGDB_INCREMENTAL_MAX_ITEMS`. No se perdió nada, pero si sale varios días
   seguidos hay un atraso real que conviene subir de techo.
7. **Carril de libros**: `skipped: true` con `reason: edition_already_diffed`
   es lo **normal** 29 días de cada 30. Lo anómalo es que un mes entero no
   aparezca nunca un run que lo diffee.

### Estado de las marcas de agua

```bash
bash -c 'set -a; source .env; set +a; uv run python -c "
import asyncio
from sqlalchemy import text
from backlogg.core.database import async_session_factory, engine
async def m():
    async with async_session_factory() as s:
        rows = (await s.execute(text(\"SELECT source, kind, item_type, cursor_value, last_run_at FROM sync_watermarks ORDER BY source, kind, item_type\"))).all()
        for r in rows:
            print(r)
    await engine.dispose()
asyncio.run(m())"'
```

Se esperan **siete filas** (dos por cada tipo de TMDB, dos de IGDB, una de
Open Library). Una fila **ausente** significa «ese mecanismo no ha corrido
nunca» y es distinto de una fila con `cursor_value` NULL, que significa «corrió
y no produjo corte utilizable».

### Si lleva días sin correr

Cada mecanismo se degrada distinto, y la diferencia importa:

| Mecanismo | Aguanta | Qué pasa al pasarse |
|---|---|---|
| `/movie/changes`, `/tv/changes` | **14 días** | El historial anterior **ya no existe** en el endpoint. `plan_change_windows` pide solo lo que TMDB puede responder y devuelve el resto en `uncovered_start`/`uncovered_end` con un `WARNING`. **No se finge cobertura**. Ojo al volumen: `/changes` tiene el **mismo tope de 500 páginas** que `/discover` y movies produce ~73 páginas/día (medido 2026-09-08: 746 páginas en 13 días), así que la ventana de recuperación se trocea sola hasta caber |
| Fichero diario de IDs | 3 meses de retención, pero el script corta a `TMDB_INCREMENTAL_MAX_EXPORT_GAP_DAYS` (7) | **Re-baselinea**: graba el fichero de hoy como línea base, reporta `rebaseline_reason` y `skipped_days`, y no admite nada de ese tramo |
| IGDB | sin límite | La query sigue respondiendo por antigua que sea la marca; solo puede tocar el techo de `IGDB_INCREMENTAL_MAX_ITEMS` y tardar varios runs en ponerse al día |
| Dump de Open Library | un mes | Se diffea la edición publicada; las intermedias no existen (el alias `latest` solo apunta a una) |

**Qué hacer**:

1. Lanzar el incremental a mano (`gh workflow run incremental-sync.yml`) y
   dejar que cada carril se ponga al día por su cuenta. Es idempotente.
2. Si el carril de `/changes` reportó `uncovered_days`, esos días **no se
   recuperan por esa vía**. La conducta definida es dejar que los cubra el
   **barrido nocturno por `last_synced_at`** (sección *Sync nocturno*), que la
   feature 88 mantiene en pie precisamente como red de seguridad. Si el hueco
   es grande y urge, un `backfill-sync.yml` en `mode=hydrate` fuerza el
   refresco de golpe.
3. Si lo que se perdió son **estrenos** (re-baseline del fichero diario), no
   hace falta nada extra: entran por el barrido de promoción en cuanto ganen
   sus primeros votos. Para forzarlo antes,
   `backfill-sync.yml` en `mode=enumerate`.
4. Si el carril de libros lleva más de un mes sin diffear, un run normal basta:
   la marca está atrás y la edición publicada es nueva, así que hará la pasada
   completa (~2 h). El work dir se cachea por edición, de modo que un run que
   muera a mitad se reanuda sin volver a bajar los 12,59 GB de ediciones.

## Endpoints admin

```bash
# Sync manual de un tipo (bloquea hasta terminar; la instancia puede tardar ~50s en despertar)
curl -X POST "$RENDER_API_URL/admin/sync/movie" \
  -H "X-API-Key: $ADMIN_API_KEY" --max-time 1800

# Estado del catálogo: counts y last_synced_at por tipo
curl "$RENDER_API_URL/admin/stats" -H "X-API-Key: $ADMIN_API_KEY"
```

Header ausente/incorrecto → `401`; `ADMIN_API_KEY` sin configurar en el
servicio → `503`.

## Estado de los cursores de sync

Los cursores viven en la tabla `sync_cursors` (ver `docs/schema.md`). Desde la
feature 86 **solo `BOOK` y `GAME` los usan**: las filas `MOVIE`/`SERIES` que
haya quedado son vestigiales y no las lee ni las escribe nadie (el progreso de
esos dos tipos se mide con la consulta de `seed_targets` de la sección «Sync
nocturno»). Consulta rápida contra Neon desde el repo:

```bash
bash -c 'set -a; source .env; set +a; uv run python -c "
import asyncio
from sqlalchemy import text
from backlogg.core.database import async_session_factory, engine
async def m():
    async with async_session_factory() as s:
        for r in (await s.execute(text(\"SELECT item_type, next_offset, updated_at FROM sync_cursors ORDER BY item_type\"))).all():
            print(r)
    await engine.dispose()
asyncio.run(m())"'
```

Las **marcas de agua** del incremental (feature 88) son otra tabla y otra
pregunta: `sync_watermarks` guarda un *corte temporal* por mecanismo, no un
offset. Su consulta está en la sección *Incremental del catálogo*.

## Métricas (Prometheus)

`GET /metrics` expone métricas operativas en formato de exposición Prometheus
(v0.0.4), sin auth y sin PII. No hay dependencia externa: el registro es
in-process y stdlib-only (mismo criterio que la capa de observabilidad).

```bash
curl "$RENDER_API_URL/metrics"
```

Series expuestas: `http_requests_total{method,path,status}`,
`http_request_duration_seconds` (histograma con `_bucket`/`_sum`/`_count`),
`backlogg_syncs_total{type}` y `backlogg_external_fanout_total{source}`. El label
`path` usa siempre la **plantilla de ruta** (`/v1/movies/{slug}`), nunca la URL con
valores reales, para no filtrar identificadores ni disparar la cardinalidad.
No requiere ningún setting nuevo; el endpoint está siempre activo y `/metrics`
se excluye de su propia instrumentación. Ver `docs/api.md` para el detalle.

## CI

`.github/workflows/ci.yml` ejecuta `bash init.sh` (lint + format + suite
completa contra PostgreSQL real) en cada push/PR a `main`.
