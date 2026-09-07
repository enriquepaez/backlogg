# Sesión actual

**Estado: sin tarea en curso.** El 2026-09-07 fue una sesión larga que terminó
con **el catálogo de producción sembrado y publicable por primera vez**.

## El catálogo, hoy

| Tipo | Ítems | |
|---|---|---|
| movies | 57.024 | de 57.166 targets |
| **series** | **10.873** | de 10.880 — **estaba a 0** |
| books | 19.159 | |
| games | 10.000 | **topados**: los 31.958 reales esperan a la feature 90 |
| **Total** | **97.056** | |

**Cluster de Neon: 392 MB de 512, con 120 MB de holgura.**

Cobertura de credits, que es lo que cerró la feature 74 y el issue #15:
movies **99,8 %** de grafo y 98,6 % de reparto · series **82,6 %** y 96,1 % ·
books **~100 %**. (El 82,6 % de series no es un hueco de ingesta: muchas series
pequeñas o extranjeras no declaran creador en TMDB.)

## Qué se cerró hoy

- **Feature 89** `credits_people_storage_redesign` — grafo de personas de 266 a
  114 MB.
- **Feature 91** `search_expression_index` — retirada `catalog_search`, y con
  ella el `REFRESH` que bloqueaba la siembra (issue #28).
- **Feature 81** `trending_local` — hecha en sesión paralela; desbloqueó FE-68.
- **Siembra de producción** — punto 7 de `priority_order.md`.
- **Feature 74** e **issue #15**, juntos, con la cobertura medida arriba. Eso
  **desbloquea FE-65**.

## Qué está ejecutable ahora

| | |
|---|---|
| **FE-65** `credits_source_author_writer_display` | `pending` — desbloqueada hoy |
| **FE-68** `trending_period_books_games` | `pending` — desbloqueada por la 81 |
| **Feature 90** `igdb_targets_seeding` | quita el tope de games: +21.958 ítems, ~53 MB. Caben en los 120 de holgura |
| **Issue #23** | ya dimensionado, **toca decidirlo** (ver abajo) |

## El issue #23 pide una decisión, y ya tiene los números

La siembra perdió **149 targets de 68.046 (0,22 %)**: movies 142 (0,25 %),
series 7 (0,064 %). La cola decía que se decidiría «cuando la siembra lo
dimensione», y ya está dimensionado.

**Mecanismo, confirmado con un caso**: el target TMDB 812 (*Aladdín* 1992,
12.231 votos) produce el slug `aladdin-1992`, que ya ocupa el movie 263 con TMDB
343693. El ítem existente ya tiene su fila de TMDB y `uq_item_source` prohíbe
una segunda, así que el 812 nunca se enlaza. **El slug hace de identidad cuando
no puede** — mismo fondo que los issues #18 y #24.

Tres cosas que no estaban en el issue y ahora sí:
1. **`skipped_links` reporta 0** en este camino: la instrumentación del issue #22
   no lo ve. Es un hueco propio.
2. **No hay huérfanos**: los 57.024 movies tienen su `external_id`. Es ausencia,
   no corrupción.
3. **Hay efecto de calidad**: gana el primero, así que a veces el slug lo ocupa
   la entrada con menos votos y la popular queda fuera.

Los 149 **no están perdidos**: siguen en `seed_targets` con `attempts=3`,
reabribles cuando haya arreglo.

## Cómo se lanza la siembra (por si hay que repetirla)

```bash
gh workflow run backfill-sync.yml -f content_type=<movie|series> -f mode=hydrate
gh run list --workflow=backfill-sync.yml
```

`seed_top_n` es inerte para movie y series desde la feature 86. Lo pendiente se
calcula por diferencia contra `external_ids`, así que converge por construcción
y da igual cómo muriera un run anterior.

## Tres cosas de Neon que costaron caro

**1. El techo de 512 MB es por CLUSTER, no por base.** Medir con
`pg_database_size('neondb')` es el denominador equivocado; las bases del sistema
cuestan ~22 MB permanentes. Consulta correcta:

```sql
SELECT pg_size_pretty(sum(pg_database_size(datname))) FROM pg_database;
```

**2. La métrica «Storage» del dashboard no es el tamaño vivo.**

**3. Un `DROP` dentro de la transacción de una migración no libera nada** —
Postgres desenlaza los ficheros en el `COMMIT`. Si una migración necesita sitio,
el `DROP` va **commiteado antes**, y antes del merge, porque Render aplica la
migración al desplegar. Saltárselo hizo fallar el despliegue de la 91 tres veces.

## Credenciales

La `DATABASE_URL` de producción **no está en `.env`** (esa apunta al contenedor
local). Hay que pedírsela al usuario. Va con prefijo `postgresql+asyncpg://`:
**`psql` no lo entiende**, hay que quitarle el `+asyncpg`.
