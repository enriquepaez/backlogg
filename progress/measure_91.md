# Feature 91 — Medición contra producción (criterio de aceptación 1)

Ejecutada el 2026-09-07 contra producción, antes de escribir código.

## 1. En qué se van los 137 MB de `catalog_search`

| Componente | Tamaño |
|---|---|
| `search_vector` **almacenado** | **57 MB** |
| `overview` (copiado de las tablas base) | 29 MB |
| Índice GIN | 25 MB |
| `poster_url` | 5 MB |
| `slug` | 1,9 MB |
| `title` | 1,6 MB |
| Cabeceras de fila y resto de columnas | ~17 MB |

85.530 filas, 1,6 KB por ítem. Más del 60 % es duplicación de datos que ya
existen en `movies`, `series`, `books` y `games`.

## 2. La pregunta que decidía el diseño: ¿aporta algo `ts_rank`?

`backlogg/search/repository.py` ordena por `rating_external DESC NULLS LAST`,
luego `ts_rank` como desempate, luego `id` (estabilidad de paginación, issue
#14). La hipótesis de partida era que un desempate detrás del rating aporta
poco, lo que habría permitido **A1**: índice GIN de expresión, sin columna
almacenada, ahorrando ~112 MB.

**La medición dice lo contrario.** Comparando el top-20 con y sin `ts_rank`:

| Consulta | Coincidencias | Sin rating | Posiciones del top-20 que sobreviven |
|---|---|---|---|
| `king` | 1.532 | 29,2 % | **5 de 20** |
| `star wars` | 186 | 26,3 % | 6 de 20 |
| `love` | 7.290 | 23,7 % | 7 de 20 |
| `the` | **71.704** | 19,1 % | 7 de 20 |
| `war` | 4.290 | 27,7 % | 9 de 20 |
| `batman` | 146 | 8,2 % | 11 de 20 |
| `lord of the rings` | 54 | 44,4 % | 13 de 20 |

**`ts_rank` reordena entre el 35 % y el 75 % del top-20.** No es cosmético.

El mecanismo: los empates en `rating_external` son masivos. Entre el 8 % y el
44 % de las coincidencias **no tienen rating**, y todos los `NULL` empatan entre
sí — en esa franja `ts_rank` es el **único** criterio de orden.

## 3. Decisión: A2, no A1

**A1 queda descartada por rendimiento, no por tamaño.** Sin columna almacenada,
`ts_rank` obliga a recalcular `to_tsvector(title || overview)` por cada fila
candidata, y además **antes del `LIMIT`**, porque vive en el `ORDER BY`. Con
`the` devolviendo 71.704 candidatas, eso es recomputar medio corpus en cada
búsqueda.

> Nota de proceso: A1 era la recomendación escrita en la descripción de la
> feature, razonada pero **sin medir**. La medición la invalidó. Es el mismo
> patrón que en la feature 89 y la razón por la que el criterio 1 de ambas es
> medir y no implementar.

**A2 — columna `search_vector` generada `STORED` en cada tabla base, más su
índice GIN, y retirar la vista materializada.**

| | Ahora | Con A2 |
|---|---|---|
| Coste de búsqueda | 137 MB | **~82 MB** (57 vector + 25 GIN) |
| Cluster | 385 MB | **~330 MB** |
| Proyección a catálogo completo | ~488 MB (24 de margen) | **~434 MB (~78 de margen)** |
| Refresh | 137 MB transitorios | **ninguno** |

Ahorra ~55 MB en vez de los ~112 de A1, pero **mata el refresh igual**, que es
lo que bloquea la siembra (issue #28). Una columna generada se actualiza en la
propia escritura, transaccionalmente: el refresh deja de existir en vez de
hacerse más pequeño, y se cierra además la ventana en la que un ítem recién
ingerido no aparece en la búsqueda.

Lo que desaparece es la duplicación de `overview`, `title`, `poster_url` y
`slug` (~40 MB). Lo que se conserva es el tsvector, que ahora sabemos que hay
que conservar.

## 4. Descartadas, con números

- **`REFRESH` no concurrente**: sigue construyendo un heap nuevo (~109 MB) antes
  de intercambiar. Cabe hoy por los pelos, bloquea lecturas, y a catálogo
  completo vuelve a fallar. No es un arreglo.
- **Adelgazar la vista** (quitar `overview`/`title`/`poster_url` y hacer join):
  la deja en ~85 MB. Cabría hoy, pero a catálogo completo serían ~118 MB con un
  refresh de otros 118: choca otra vez. Aplaza el problema.
