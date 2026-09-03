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
| `SEED_TOP_N_BOOKS` / `SEED_TOP_N_GAMES` | 10000 | Objetivo de catálogo de los tipos con cursor |
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
| `DATABASE_URL` (`postgresql+asyncpg://...`) | backfill-sync.yml |
| `TMDB_API_KEY` | backfill-sync.yml |
| `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` | backfill-sync.yml |

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

- **`book` y `game`**: avanzan el cursor de su tipo en `SYNC_SLICE_SIZE` items
  (tabla `sync_cursors`, compartida con el backfill).
- **`movie` y `series`**: toman `SYNC_SLICE_SIZE_<TIPO>` targets pendientes de
  `seed_targets` (los que aún no tienen fila en `external_ids`) y, si no quedan,
  rellenan la rebanada con los ítems de `last_synced_at` más antiguo. No hay
  cursor: el campo `offset` de la respuesta es siempre `0` para estos dos tipos.

### Targets retirados (`stuck`)

Un target puede ser **imposible de enlazar**, por dos motivos independientes:
TMDB responde 404 a un id enumerado, o el par `(source, external_id)` ya está
reclamado por otro tipo de ítem (`uq_external_id` es único globalmente y TMDB
numera movies y series por separado — ver `docs/schema.md`).

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
`unlinkable` (colisión de id, que es el defecto de esquema preexistente).

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

## Backfill del catálogo

`.github/workflows/backfill-sync.yml` ejecuta `scripts/backfill_sync.py`
directamente contra Neon y las APIs externas (sin pasar por Render ni su
timeout). Procesa tramos de 500 en bucle hasta wraparound del cursor o
presupuesto de tiempo (5 h por defecto; `timeout-minutes: 350` en el job).

```bash
# Sembrar la lista objetivo de TMDB (movie/series) — hacerlo ANTES del primer
# hydrate de esos dos tipos
gh workflow run backfill-sync.yml -f content_type=movie -f mode=enumerate

# Hidratar: bajar los ítems que la lista objetivo pide y el catálogo no tiene
gh workflow run backfill-sync.yml -f content_type=movie -f mode=hydrate

# Tipos con cursor (book/game): seed_top_n debe coincidir con Render
gh workflow run backfill-sync.yml -f content_type=book -f mode=hydrate -f seed_top_n=10000

# Ver los últimos runs y su estado
gh run list --workflow=backfill-sync.yml --limit 3

# Seguir el run más reciente en vivo
gh run watch

# Inspeccionar iteraciones y stop_reason de un run concreto
gh run view <run-id> --log | grep backfill
```

- `seed_top_n` **debe coincidir** con `SEED_TOP_N_*` en Render — si difiere,
  el cursor compartido haría wraparound antes de tiempo. Aplica **solo a
  `book` y `game`**: `SEED_TOP_N_MOVIES`/`_SERIES` son inertes desde la
  feature 86.
- El log termina con `stop_reason`: `wraparound` = objetivo alcanzado o API
  agotada (book/game); `exhausted` = el catálogo ya tiene todos los targets
  enumerados **trabajables** (movie/series; los retirados se reportan aparte en
  `stuck`); `time_budget` = relanzar el dispatch (reanuda desde el cursor o
  recalculando la diferencia contra el catálogo).
- Un error de API externa que persiste tras los reintentos deja el **run en
  rojo** (exit 1) con el cursor intacto — relanzar cuando la API se recupere.
- Los backfills de tipos distintos pueden correr **en paralelo** (tablas y
  APIs independientes; el refresh de `catalog_search` es CONCURRENTLY).

También ejecutable en local (usa el `DATABASE_URL` del entorno/`.env`):

```bash
uv run python scripts/seed_tmdb_targets.py movie          # enumeración
uv run python scripts/backfill_sync.py movie              # hidratación
uv run python scripts/backfill_sync.py game --slice-size 500 --time-budget-minutes 60
```

Defaults configurables por env: `BACKFILL_SLICE_SIZE` (500) y
`BACKFILL_TIME_BUDGET_MINUTES` (300).

### Enumeración de la lista objetivo de TMDB (`mode=enumerate`)

`scripts/seed_tmdb_targets.py` **solo enumera**: recorre `/discover` con
`vote_count.gte`, troceando por año de estreno, y escribe la lista objetivo en
`seed_targets`. No pide ningún detalle y no escribe ninguna fila de catálogo.

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
- Solo `movie` y `series`. Books usa dumps de Open Library y games una única
  query a IGDB; el workflow rechaza esos tipos en este modo.

### Los tres modos: `enumerate`, `hydrate` y `credits`

El workflow tiene un input `mode`. Resuelven problemas distintos y **no** se
sustituyen entre sí:

| | `enumerate` (movie/series) | `hydrate` (por defecto) | `credits` (`--only-missing-credits`) |
|---|---|---|---|
| Lista de trabajo | `/discover` por año bajo `vote_count.gte` | movie/series: targets de `seed_targets` sin fila en `external_ids`; book/game: listado de populares por offset | query local: ítems del catálogo **sin ninguna fila en `credits`**, unida a `external_ids` |
| Estado entre runs | la propia tabla `seed_targets` | movie/series: ninguno (diferencia en vivo); book/game: cursor en `sync_cursors` | ninguno; recalcula el hueco en cada run |
| Llamadas HTTP por ítem | 0 (20 ítems por petición de lista) | **una**: `/{tipo}/{id}?append_to_response=credits,external_ids` | **una**: `/movie/{id}/credits`, `/tv/{id}?append_to_response=credits` o el work detail de Open Library |
| Escribe la fila del ítem | **no**: solo la lista objetivo | sí (upsert completo) | **no**: la fila ya existe, solo faltan sus credits |
| Condición de parada | ventanas agotadas | `pending == 0` (movie/series; los targets retirados no cuentan), wraparound del cursor (book/game) o `--time-budget-minutes` | lista de huecos agotada o `--time-budget-minutes` |
| Para qué sirve | decidir **qué** quiere el catálogo | bajar lo que falta | cerrar agujeros de credits (issue #15) |
| `book`/`game` | **rechazados** | soportados | `game` **rechazado** |

**Cuándo usar cada uno.** Si el catálogo de movies/series está vacío o el
umbral ha cambiado, `enumerate` primero y `hydrate` después. Si faltan
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
- El modo `credits` **no** refresca `catalog_search`: la vista no expone
  credits, así que no hay nada que refrescar.

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
