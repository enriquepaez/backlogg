# Feature 89 — Despliegue (estado real, 2026-09-07)

> **Los pasos 1 y 2 ya están ejecutados.** Este archivo documenta lo que se
> hizo, por qué, y lo que queda. La primera versión de este runbook estaba
> equivocada en su premisa; la corrección es el contenido más importante de aquí.

## ⚠️ La corrección: Neon mide el CLUSTER, no la base

`neon.max_cluster_size = 512MB` limita el **cluster entero**, no la base
`neondb`. Toda la feature —incluidas las proyecciones de
`progress/measure_89.md` §7— se dimensionó contra `pg_database_size('neondb')`,
que es **el denominador equivocado**.

El síntoma que lo destapó: con `neondb` en 484 MB y 28 MB de margen aparente,
producción **rechazaba un `INSERT` de una sola fila** con el mismo error que
mató la siembra:

```
ERROR: could not extend file because project size limit (512 MB) has been exceeded
HINT:  ... internally by neon.max_cluster_size GUC
```

El reparto real del cluster el 2026-09-07:

| Base | Tamaño |
|---|---|
| `neondb` | 484 MB |
| **`backlogg_test`** | **9.440 kB** |
| `postgres` | 7.656 kB |
| `template1` | 7.328 kB |
| `template0` | 7.320 kB |
| **Total** | **515 MB** ❌ |

**Esto explica también el fallo original de la siembra**, que nunca cuadró:
murió por «512 MB excedidos» con `neondb` en ~472 MB porque faltaban por contar
los ~31 MB de las otras bases.

**Consecuencia permanente**: las tres bases del sistema ocupan **~22 MB que no
se pueden eliminar** y hay que descontarlos del techo. El presupuesto real para
`neondb` no es 512 MB, es **~490 MB**.

## Lo ejecutado el 2026-09-07

### Paso 1 — `DROP DATABASE backlogg_test` ✅

Una base de tests dentro de producción, en **alembic `0010`** (el proyecto va
por la 0036) y con **58 filas** en total: 24 tablas prácticamente vacías
ocupando 9,4 MB de esquema e índices. Residuo de los primeros días.

Cluster 515 → **505 MB**. **Las escrituras volvieron**, verificado insertando
1.000 filas en una tabla de prueba y borrándola.

### Paso 2 — `DROP MATERIALIZED VIEW catalog_search` ✅

105 MB de dato derivado, reconstruible desde el DDL de la migración `0028`
(que es la definición vigente — **no la 0006**).

Cluster 505 → **400 MB**, con **112 MB de holgura**. La migración `0037` pica
~85 MB, así que cabe con ~27 MB de sobra.

> Se hizo **después** del paso 1 y no antes, a propósito: recrear esta vista
> exige escribir 105 MB. Dropearla mientras las escrituras estaban bloqueadas
> habría dejado la búsqueda caída **y sin forma de reconstruirla**.

**Mientras tanto `/search` devuelve error.** Se acepta porque el catálogo no es
publicable de todos modos (series a 0) y prod duerme sin tráfico.

## Lo que queda

### Paso 3 — mergear la PR #202

Render aplica `0037` al desplegar. Pico esperado: ~485 MB de 512.

### Paso 4 — confirmar que entró

```
SELECT version_num FROM alembic_version;          -- 0037
SELECT count(*) FROM item_cast;                   -- ~55.590
SELECT role, count(*) FROM credits GROUP BY role; -- ningun 1 (ACTOR)
```

**No sigas al paso 5 si esto no cuadra.**

### Paso 5 — recuperar el espacio, en este orden

`DELETE` marca tuplas muertas pero no encoge el archivo. Sin esto el ahorro
medido cae del −70 % al −19 %.

```
VACUUM FULL people;
VACUUM FULL external_ids;
```

### Paso 6 — recrear `catalog_search`

DDL completo en `alembic/versions/0028_catalog_search_punctuation_normalization.py`
(`_create_view` + los tres índices). `CREATE MATERIALIZED VIEW` ya la puebla; el
índice único `uq_catalog_search_type_id` es obligatorio para poder refrescar
`CONCURRENTLY` en el futuro.

### Paso 7 — medir (criterios de aceptación 10 y 11)

**Contra el cluster, no contra `neondb`:**

```
SELECT pg_size_pretty(sum(pg_database_size(datname))) FROM pg_database;
```

## Proyección corregida

| | Antes (mal) | Corregido |
|---|---|---|
| Denominador | `neondb` | cluster entero |
| Presupuesto para datos | 512 MB | **~490 MB** (512 − 22 de bases del sistema) |
| Catálogo completo con A+B | ~444 MB | ~444 MB |
| **Margen** | ~68 MB | **~46 MB** |

**La conclusión de la feature no cambia** —A+B sigue siendo lo único que cabe, y
cabe— pero con menos holgura de la anunciada. Y el aviso de
`measure_89.md` §10 sigue vigente: `catalog_search` proyecta a ~146 MB y es la
siguiente pared.

## Pendiente

**Rotar la contraseña de producción**, expuesta en el historial de conversación.
Al rotarla, actualizar el secret `DATABASE_URL` de GitHub Actions y la variable
de Render. Hacerlo **antes** de arrancar la siembra: a mitad deja el workflow
sin autenticar.
