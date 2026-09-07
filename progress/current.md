# Sesión actual

**Estado: sin tarea en curso.** El 2026-09-07 se cerraron **dos features
seguidas**, ambas desplegadas en producción y medidas: la **89
`credits_people_storage_redesign`** y la **91 `search_expression_index`**.

## Dos cosas en marcha en paralelo (2026-09-07)

**1. La siembra de producción** — la ejecuta el usuario a mano. Todo lo que hace
falta está en «Runbook de la siembra» aquí abajo.

**2. La feature 81 `trending_local`** — el usuario la está haciendo **en otra
conversación**. ⚠️ **No la cojas.** Si empiezas sesión nueva y necesitas tarea,
salta a la 79 o pregunta.

---

# Runbook de la siembra (punto 7 de `priority_order.md`)

## Qué falta, medido contra producción el 2026-09-07

| Tipo | Estado |
|---|---|
| **SERIES** | **10.880 pendientes** — están todas: `series` tiene 0 filas |
| **MOVIE** | **795 pendientes** de 57.166 |
| BOOK | 19.159 cargados; la fase `load` del dump es idempotente |
| GAME | 10.000 de 31.958, **topados** hasta la feature 90 |

Consulta para recalcular lo pendiente en cualquier momento (converge por
construcción: es la diferencia contra `external_ids`, así que da igual cómo
muriera un run anterior):

```sql
SELECT st.item_type, count(*) AS pendientes
FROM seed_targets st
WHERE NOT EXISTS (SELECT 1 FROM external_ids e
                  WHERE e.item_type=st.item_type AND e.source=st.source
                    AND e.external_id=st.external_id)
GROUP BY 1 ORDER BY 1;
```

## Cómo se lanza

Por **GitHub Actions**, no por Render (que corta a los ~15 min por petición):

```bash
gh workflow run backfill-sync.yml -f content_type=movie  -f mode=hydrate
gh workflow run backfill-sync.yml -f content_type=series -f mode=hydrate

gh run list --workflow=backfill-sync.yml
gh run watch
```

`seed_top_n` es **inerte** para movie y series desde la feature 86 (solo aplica
a book y game, que siguen con cursor). No hace falta pasarlo.

**Movies primero, aunque sea lo pequeño**: es un test de humo. La ingesta ahora
escribe en `item_cast` y calcula `search_vector` en cada `INSERT` — dos caminos
que las migraciones `0037` y `0038` estrenaron hoy y que **nunca se han
ejercitado contra producción a escala**. 795 ítems son ~40 min; 10.880 series
son ~9 h. Mejor descubrir un fallo en 40 minutos.

**Series necesitará dos despachos**: el script se para solo a los 300 min
(`BACKFILL_TIME_BUDGET`). El segundo retoma donde quedó.

## Qué verificar entre tanda y tanda

**1. Que los caminos nuevos se pueblan** (lo que estrena esta siembra):

```sql
SELECT count(*) FROM item_cast WHERE item_type = 2;          -- 2 = SERIES
SELECT count(*) FROM series WHERE search_vector IS NOT NULL;  -- debe igualar count(*)
```

**2. `skipped_links`**, el panel de instrumentos del issue #22. Viaja en el
resumen del job y sale como `::warning::` en el workflow. **Si sube, hay enlaces
perdiéndose en silencio** — es el mecanismo que encadenó los issues #7, #15 y #20.

**3. El disco, contra el CLUSTER y no contra `neondb`:**

```sql
SELECT pg_size_pretty(sum(pg_database_size(datname))) AS cluster,
       pg_size_pretty(512*1024*1024 - sum(pg_database_size(datname))::bigint) AS holgura
FROM pg_database;
```

Punto de partida: **343 MB, 169 de holgura**. Coste estimado de lo que falta:
**~53 MB** (795 movies + 10.880 series a ~4,5 KB/ítem todo incluido). Debería
acabar en ~396 MB.

⚠️ Ese 4,5 KB/ítem está **extrapolado de movies**, no medido para series, y el
**reparto de series suele ser más largo** que el de cine, así que `item_cast`
puede salir más caro. Hay margen para absorberlo, pero conviene medir tras la
primera tanda de series en vez de esperar al final.

## Qué se cierra cuando la siembra termine

- **Feature 74** `credits_source_author_role` (hoy `blocked`) y **issue #15**, que
  se cierran **juntos**: el criterio 9 de la 74 es «issue #15 verificado para
  movies, series **y** books», y series estaba a 0.
- Con la 74 en `done` se desbloquea **FE-65** en el frontend.
- Quedan pendientes de decisión los issues **#20** y **#18**, que siguen `open` a
  propósito esperando a medirse contra la siembra real.

## Lo que liberaron las dos features

| | Antes | Después |
|---|---|---|
| Grafo de personas (89) | 266 MB | **114 MB** |
| `catalog_search` (91) | 137 MB | **0** |
| **Cluster** | **515 MB** ❌ | **343 MB** |
| **Holgura** | 0 (rechazaba un INSERT) | **169 MB** |

La 89 movió el reparto a `item_cast` (JSONB) dejando en `credits` solo el grafo;
la 91 retiró la vista materializada y puso un índice GIN sobre una columna
generada en cada tabla base. Detalle en `progress/measure_89.md` y
`progress/measure_91.md`.

## Tres cosas de Neon que costaron caro y no se deducen del código

**1. El techo de 512 MB es por CLUSTER, no por base.** `neon.max_cluster_size`
suma todas las bases. Medir con `pg_database_size('neondb')` es el denominador
equivocado — por eso parecía haber 28 MB de margen mientras producción rechazaba
un `INSERT` de una fila. Las bases del sistema cuestan **~22 MB permanentes**.
Consulta correcta:

```sql
SELECT pg_size_pretty(sum(pg_database_size(datname))) FROM pg_database;
```

**2. La métrica «Storage» del dashboard no es el tamaño vivo.** Marcaba
0,54 / 0,5 GB con el cluster ya en 400 MB y las escrituras funcionando.

**3. Un `DROP` dentro de la transacción de una migración no libera nada.**
Postgres desenlaza los ficheros en el `COMMIT`. Si hace falta espacio para que
una migración quepa, el `DROP` tiene que ir **commiteado antes**, como sentencia
propia — y antes del merge, porque Render aplica la migración al desplegar.
Saltarse ese paso hizo fallar el despliegue de la 91 tres veces.

## Una trampa que ya mordió una vez

**`catalog_search` se redefinió en tres migraciones (`0006` → `0028` → `0031`).**
Al recrearla a mano durante el despliegue de la 89 se usó el DDL de la `0028` sin
comprobar cuál era la última: la vista quedó sin `rating_internal` y `/v1/search`
estuvo roto ~1 h. Ya no aplica —la 91 retiró la vista— pero la lección sí: al
recrear algo a mano desde una migración, **la definición buena es la última**.

## La feature 74 está en `blocked` a propósito

Su código está mergeado desde el PR #197. Su criterio 9 depende de la siembra.
La 74 y el issue #15 se cierran **juntos** cuando la siembra esté hecha y medida.
Pasó de `in_progress` a `blocked` el 2026-09-07: describe mejor la situación
—nadie trabaja en ella— y `init.sh` solo admite una feature en `in_progress`.

## Credenciales

La `DATABASE_URL` de producción **no está en `.env`** (esa apunta al contenedor
local). Hay que pedírsela al usuario. Va con prefijo `postgresql+asyncpg://`:
**`psql` no lo entiende**, hay que quitarle el `+asyncpg`.
