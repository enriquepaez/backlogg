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

## Configuración en Render

| Env var | Valor actual | Notas |
|---|---|---|
| `SEED_TOP_N_*` | 10000 | Objetivo de catálogo por tipo (movies/series/books/games) |
| `SYNC_SLICE_SIZE` | 100 | Tramo por request de sync; >100 arriesga el timeout de ~15 min por request de Render |
| `ADMIN_API_KEY` | (secret) | Protege `/admin/*` |
| `CORS_ORIGINS` | (opcional) | Orígenes permitidos, comma-separated |
| `JWT_SECRET_KEY` | (secret) | Firma los JWT de `/auth/*`. Sin configurar, `POST /auth/register`/`login` fallan con 500 (PyJWT rechaza clave HMAC vacía) |
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

### Roadmap — env vars planificadas en Render (features 37-40)

Se configuran cuando se despliegue cada feature. Detalle en `docs/external-apis.md`.

| Env var | Feature | Notas |
|---|---|---|
| `RATE_LIMIT_AUTH` / `RATE_LIMIT_DEFAULT` | 37 | Límites de rate limiting por ventana |
| `SENTRY_DSN` | 38 | (secret) DSN de Sentry; ausente = integración off |
| `LOG_LEVEL` | 38 | Nivel de logging estructurado |

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
la instancia (`GET /health`), llama a los 4 `POST /admin/sync/{type}` en
secuencia (paralelo saturaba la instancia free) y verifica con
`GET /admin/stats` que cada `last_synced_at` es reciente (< 2 h).

```bash
# Lanzarlo manualmente
gh workflow run nightly-sync.yml

# Ver el último run
gh run list --workflow=nightly-sync.yml --limit 3
```

Cada run avanza el cursor de cada tipo en `SYNC_SLICE_SIZE` items
(tabla `sync_cursors`, compartida con el backfill).

## Backfill del catálogo

`.github/workflows/backfill-sync.yml` ejecuta `scripts/backfill_sync.py`
directamente contra Neon y las APIs externas (sin pasar por Render ni su
timeout). Procesa tramos de 500 en bucle hasta wraparound del cursor o
presupuesto de tiempo (5 h por defecto; `timeout-minutes: 350` en el job).

```bash
# Lanzar el backfill de un tipo (movie/series/book/game)
gh workflow run backfill-sync.yml -f content_type=movie -f seed_top_n=10000

# Ver los últimos runs y su estado
gh run list --workflow=backfill-sync.yml --limit 3

# Seguir el run más reciente en vivo
gh run watch

# Inspeccionar iteraciones y stop_reason de un run concreto
gh run view <run-id> --log | grep backfill
```

- `seed_top_n` **debe coincidir** con `SEED_TOP_N_*` en Render — si difiere,
  el cursor compartido haría wraparound antes de tiempo.
- El log termina con `stop_reason`: `wraparound` = objetivo alcanzado o API
  agotada; `time_budget` = relanzar el dispatch (reanuda desde el cursor).
- Un error de API externa que persiste tras los reintentos deja el **run en
  rojo** (exit 1) con el cursor intacto — relanzar cuando la API se recupere.
- Los backfills de tipos distintos pueden correr **en paralelo** (tablas y
  APIs independientes; el refresh de `catalog_search` es CONCURRENTLY).

También ejecutable en local (usa el `DATABASE_URL` del entorno/`.env`):

```bash
uv run python scripts/backfill_sync.py movie
uv run python scripts/backfill_sync.py game --slice-size 500 --time-budget-minutes 60
```

Defaults configurables por env: `BACKFILL_SLICE_SIZE` (500) y
`BACKFILL_TIME_BUDGET_MINUTES` (300).

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

Los cursores viven en la tabla `sync_cursors` (ver `docs/schema.md`).
Consulta rápida contra Neon desde el repo:

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

## CI

`.github/workflows/ci.yml` ejecuta `bash init.sh` (lint + format + suite
completa contra PostgreSQL real) en cada push/PR a `main`.
