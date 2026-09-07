# Feature 89 — Runbook de despliegue (verificado contra Neon el 2026-09-07)

> La migración `0037` **no cabe en producción tal cual**. Esto no es un defecto
> de la implementación: es una consecuencia de que la base esté al 94,5 % de su
> techo. Hay que hacer sitio **antes** de mergear a `main`, porque Render aplica
> la migración al desplegar.

## Estado verificado de partida

| Dato | Valor | Cómo se comprobó |
|---|---|---|
| Tamaño de la base | **484 MB** | `pg_database_size` |
| Techo del plan | 512 MB | free tier de Neon |
| **Margen** | **28 MB** | |
| Bloat recuperable | **ninguno** | `n_dead_tup`: 59 en `credits`, 1 en `people`, 1.537 en `external_ids`; autovacuum corrió el 2026-09-07 |
| `catalog_search` | 105 MB, `relkind = 'm'` | vista materializada, dato derivado |

**Un `VACUUM` normal no da espacio.** Esa puerta está cerrada: la comprobé
antes de proponer nada más caro.

## El pico, y por qué no cabe

Todo `0037` corre en una transacción (`alembic/env.py` envuelve la corrida
entera), así que **nada vuelve al filesystem hasta el commit**. Durante la
migración conviven:

```
credits viejo (136 MB)
  + item_cast nuevo (~36 MB)
  + credits nuevo (~30 MB)
  + los 3 índices del credits nuevo (~12-15 MB)
  + temp table _f89_cast_only_people con su índice (~10 MB)
  + tuplas muertas y WAL de los dos DELETE (~250.000 filas)
```

**Pico real: +80-90 MB sobre los 484 de partida, es decir ~565-575 MB.**

⚠️ Esta cifra corrige tanto el §8.1 de `progress/impl_89.md` como la primera
versión de este runbook, que decían +60-70 MB. La corrección es del reviewer
(`progress/review_89.md` §2) y es acertada: ambos contábamos solo las tres
tablas grandes y omitíamos los índices del `credits` nuevo, la temp table —que
vive durante todo el tramo caro— y el WAL de los DELETE.

**No cambia la conclusión** (no cabía en 28 MB de ninguna manera), pero sí
cuánto hay que liberar: con `catalog_search` sobra; con una palanca de 70 MB
no habría bastado.

Partir la migración en varias transacciones bajaría el pico, pero deja la base
a medias si falla a mitad — sobre una migración que borra 175.306 personas de
forma irreversible, es peor negocio. La palanca correcta es hacer sitio.

## Secuencia

Cada paso lleva el tamaño esperado de la base al terminarlo.

| # | Paso | Dónde | Base después |
|---|---|---|---|
| 0 | Punto de partida | — | 484 MB |
| 1 | `DROP MATERIALIZED VIEW catalog_search;` | psql contra Neon | **379 MB** |
| 2 | Merge del PR → Render despliega y aplica `0037` | automático | **309 MB** (pico **~464**) |
| 3 | `VACUUM FULL people;` | psql | **268 MB** |
| 4 | `VACUUM FULL external_ids;` | psql | **229 MB** |
| 5 | Recrear `catalog_search` + sus 3 índices + `REFRESH` | psql | **~334 MB** |

El DDL del paso 5 es el de `alembic/versions/0028_catalog_search_punctuation_normalization.py`
(su `upgrade` la recrea entera: la vista, `idx_catalog_search_vector`,
`idx_catalog_search_type` y `uq_catalog_search_type_id`). **0028 es la
definición vigente, no 0006.** El índice único hace falta para poder refrescar
`CONCURRENTLY` después.

**Pico del paso 2: ~464 MB** (379 + 85), con **~48 MB de holgura**. Cabe.

**Resultado: ~334 MB, ~178 MB de margen** para retomar la siembra. Encaja con la
proyección de `progress/measure_89.md` §7 (catálogo completo con A+B ≈ 444 MB).

## Lo que se rompe mientras tanto, y por qué se acepta

Entre los pasos 1 y 5 **la búsqueda no funciona**: `catalog_search` es lo que
sirve `/search`. Se acepta porque el catálogo de hoy **no es publicable de todos
modos** — series está a 0, falta un tipo de contenido entero — y porque prod
duerme en el free tier de Render sin tráfico real. Si esto se hiciera con
usuarios encima, la secuencia tendría que ser otra.

Los pasos 3 y 4 bloquean sus tablas (`VACUUM FULL` toma `ACCESS EXCLUSIVE`).
Con la app dormida, irrelevante.

## ⚠️ El riesgo que no he podido medir

**No sé si el «project size» que Neon compara contra los 512 MB es el mismo
número que devuelve `pg_database_size`.** Neon factura almacenamiento contando
también el historial/WAL de su ventana de retención, y esta operación genera
mucho WAL: reescribe 710.772 filas, borra 175.306 personas y hace dos
`VACUUM FULL`. Si el historial cuenta, el techo efectivo llega antes que en la
tabla de arriba.

**Antes del paso 2, mirar en el dashboard de Neon la cifra de storage y
compararla con los 484 MB de `pg_database_size`.** Si difieren mucho, el margen
real es menor y hay que rehacer los números. No es una objeción teórica: el
error original que motivó esta feature fue literalmente
`project size limit (512 MB) has been exceeded`, y nadie ha confirmado sobre qué
magnitud se calcula.

## Antes de todo esto

**Rotar la contraseña de producción**, pendiente desde el 2026-09-07 y ahora
otra vez escrita en el historial de conversación. Este runbook es el último
momento limpio para hacerlo: una vez arranque la siembra, rotarla a mitad deja
el workflow de GitHub Actions sin autenticar. Al rotarla hay que actualizar el
secret `DATABASE_URL` de GitHub Actions y la variable de Render.
