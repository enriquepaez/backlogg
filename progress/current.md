# Sesión actual

**Estado: sin tarea en curso.** La feature **89 `credits_people_storage_redesign`
está `done`** (2026-09-07), desplegada en producción y medida. Lo que sigue es lo
que una sesión nueva necesita y no se deduce del código ni de git.

## Qué se hizo y qué liberó

| Tabla | Antes | Después |
|---|---|---|
| `credits` | 136 MB | **27 MB** |
| `external_ids` | 74 MB | **32 MB** |
| `people` | 56 MB | **15 MB** |
| `item_cast` | — | **40 MB** |
| **Grafo de personas** | **266 MB** | **114 MB** (−152, −57 %) |

Cluster de Neon: 515 → **385 MB**. `item_cast` recibió los **517.600** credits
ACTOR íntegros: cero pérdida. Detalle en `progress/measure_89.md` (medición,
decisión y §12 con el después) y `progress/deploy_89.md` (despliegue).

## ⛔ La siembra sigue bloqueada, ahora por el issue #28

**No la retomes sin resolverlo.** `REFRESH MATERIALIZED VIEW CONCURRENTLY`
construye una copia completa de `catalog_search` antes de intercambiarla: la
vista pesa **137 MB** y el cluster tiene **127 MB** libres, así que **hoy no
cabe**. Lo ejecuta el nocturno en `backlogg/scheduler/jobs.py:153` y también
`backlogg/search/repository.py:20`. A catálogo completo la vista rondaría los
191 MB, y el refresh otro tanto.

Ojo al dato que lo destapó: **la vista que se midió en 105 MB estaba obsoleta**
—sus estadísticas decían 66.363 filas con 85.530 ítems en el catálogo, porque no
se refrescó tras morir la siembra—. Los 137 MB son su tamaño real, 1,6 KB por
ítem. Con eso la proyección a catálogo completo sube a **~488 MB de 512: ~24 MB
de margen**, no los 68 que se estimaron al planificar la 89.

## Dos cosas que hay que saber de Neon, y que costaron dos intentos

**1. El techo de 512 MB es por CLUSTER, no por base.** `neon.max_cluster_size`
mide la suma de todas las bases. Toda la feature 89 se planificó contra
`pg_database_size('neondb')`, que es el denominador equivocado; por eso había
«28 MB de margen» mientras producción rechazaba un `INSERT` de una fila. Las
bases del sistema (`postgres`, `template0`, `template1`) cuestan **~22 MB
permanentes** que hay que descontar de los 512.

**Esto explica también el fallo original de la siembra**, que nunca cuadró: murió
por «512 MB excedidos» con `neondb` en ~472 MB.

**2. La métrica «Storage» del dashboard no es el tamaño vivo.** Marcaba
0,54 / 0,5 GB con el cluster ya en 400 MB y las escrituras funcionando. Para
saber si algo cabe, mide con SQL:
`SELECT pg_size_pretty(sum(pg_database_size(datname))) FROM pg_database;`

Se borró además una base **`backlogg_test` dentro de producción** (alembic 0010,
58 filas, 9,4 MB): residuo de los primeros días que estaba consumiendo techo.

## La feature 74 sigue en `in_progress` a propósito

Su código está mergeado desde el PR #197. Su criterio 9 depende de la siembra,
que sigue bloqueada. La 74 y el issue #15 se cierran **juntos** cuando la siembra
esté hecha y medida.

## Credenciales

La `DATABASE_URL` de producción **no está en `.env`** (esa apunta al contenedor
local). Vive en Neon, en Render y en el secret de GitHub Actions, que es de solo
escritura. Hay que pedírsela al usuario. Va guardada con prefijo
`postgresql+asyncpg://`: **`psql` no lo entiende**, hay que quitarle el `+asyncpg`.

⚠️ **Pendiente de rotar** — quedó expuesta en el historial de conversación del
2026-09-07. Al rotarla, actualizar el secret de GitHub Actions y la variable de
Render. Hacerlo **antes** de arrancar la siembra: a mitad deja el workflow sin
autenticar.
