# Feature 91 — Runbook de despliegue

> Verificado contra Neon el 2026-09-07 por el leader. Punto de partida: cluster
> **385 MB de 512**, holgura **127 MB**.

## Por qué el orden importa (y por qué mi primera idea era falsa)

El brief original pedía dropear `catalog_search` **dentro** de la migración para
hacer sitio. **No sirve**: Postgres desenlaza los ficheros en el `COMMIT`, así
que dentro de la transacción el `DROP` libera cero. El implementer lo midió
abriendo una transacción y consultando `pg_database_size` desde dentro.

Añadir una columna generada `STORED` **reescribe la tabla**, así que durante el
`ALTER` conviven la copia vieja y la nueva. Y como todo el `upgrade` va en una
transacción, nada se devuelve hasta el final.

### Pico calculado con cifras reales de producción

| Tabla | Heap hoy | Ítems | Parte del tsvector | Copia nueva |
|---|---|---|---|---|
| `movies` | 33 MB | 56.371 (66 %) | ~38 MB | ~71 MB |
| `books` | 13 MB | 19.159 (22 %) | ~13 MB | ~26 MB |
| `games` | 7,3 MB | 10.000 (12 %) | ~7 MB | ~14 MB |
| `series` | 8 KB | 0 | — | — |

| Escenario | Pico | ¿Cabe? |
|---|---|---|
| Sin dropear la vista antes | ~530 MB | ❌ |
| **Con la vista dropeada y commiteada antes** | **~394 MB** | ✅ ~118 MB de holgura |

## Secuencia

```fish
set -x PROD "postgresql://neondb_owner:LA_PASSWORD@ep-tiny-fog-a4uypa8b.us-east-1.aws.neon.tech/neondb?sslmode=require"
```

### Paso 1 — foto del antes (criterio 9)

```fish
psql $PROD -c "SELECT pg_size_pretty(sum(pg_database_size(datname))) FROM pg_database;"
```
Esperado: **385 MB**.

### Paso 2 — dropear la vista, como sentencia propia y COMMITEADA

```fish
psql $PROD -c "DROP MATERIALIZED VIEW catalog_search;"
psql $PROD -c "SELECT pg_size_pretty(sum(pg_database_size(datname))) FROM pg_database;"
```
Esperado: **248 MB**.

> A partir de aquí `/v1/search` da 500 hasta que el despliegue termine. Es
> aceptable: el catálogo no es publicable (series a 0) y prod duerme.
>
> **Si el despliegue abortara aquí**, la búsqueda se recupera recreando la vista
> con el DDL de la migración **`0031`** —que es la vigente si la `0038` no
> entró— y sus tres índices.

### Paso 3 — mergear la PR

Render aplica `0038`. Pico esperado ~394 MB de 512.

### Paso 4 — confirmar

```fish
psql $PROD -c "SELECT version_num FROM alembic_version;"                      # 0038
psql $PROD -c "SELECT to_regclass('public.catalog_search');"                  # NULL
psql $PROD -c "SELECT count(*) FROM movies WHERE search_vector IS NOT NULL;"  # 56.371
```

### Paso 5 — `ANALYZE` y medir (criterio 9)

```fish
psql $PROD -c "ANALYZE movies, series, books, games;"
psql $PROD -c "SELECT pg_size_pretty(sum(pg_database_size(datname))) AS cluster,
                      pg_size_pretty(512*1024*1024 - sum(pg_database_size(datname))::bigint) AS holgura
               FROM pg_database;"
```
Esperado: **~330 MB**, ~182 MB de holgura.

### Paso 6 — comprobar la búsqueda

```fish
curl -s "https://TU-URL-DE-RENDER/v1/search?q=batman&limit=5"
```
Cold start de ~50 s en el free tier.

## Riesgo residual

**El nocturno viejo entre los pasos 2 y 3.** Mientras la vista no existe pero el
código desplegado sigue siendo el anterior, un sync nocturno intentaría
refrescar una vista inexistente. El sync real corre por **GitHub Actions**, no
in-process (`docs/operations.md`), así que la ventana es controlable: no hagas
el paso 2 justo antes de la hora del cron.

## Plan B

Si el pico no cupiera, los cuatro `ALTER` a mano, **uno por transacción**,
seguidos de `alembic stamp 0038`. Detalle en el docstring de la migración.
