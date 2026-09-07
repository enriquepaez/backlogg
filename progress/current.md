# Sesión actual

**Estado: sin tarea en curso.** El 2026-09-07 se cerraron **dos features
seguidas**, ambas desplegadas en producción y medidas: la **89
`credits_people_storage_redesign`** y la **91 `search_expression_index`**.

## Dónde seguir

**La siembra de producción está DESBLOQUEADA** — punto 7 de
`progress/priority_order.md`. Era lo que bloqueaban las dos features de hoy.
Retomar donde quedó: los 795 movies pendientes siguen en `seed_targets`, la fase
`load` de books es idempotente, y **series entera** (está a 0, y por eso el
catálogo de hoy no es publicable).

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
