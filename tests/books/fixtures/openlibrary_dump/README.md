# Fragmento real de los dumps de Open Library (feature 87)

Todas las líneas de estos `.tsv` son **líneas verbatim** del dump mensual
`ol_dump_2026-08-31` de Open Library, extraídas el 2026-09-04 recorriendo los
dumps enteros en streaming (`openlibrary.org/data/ol_dump_<name>_latest.txt.gz`,
que redirige a `archive.org/download/ol_dump_2026-08-31/`) y filtrando por las
claves de interés. No están reescritas, ni reserializadas, ni recortadas por
campos: es exactamente el texto que el pipeline se encuentra en producción,
incluidos los escapes `\uXXXX`, el orden de claves del JSON y las notaciones
`ddc`/`lcc` **sin normalizar**.

`search_docs.json` es lo otro: los documentos que `search.json` (el índice Solr
de Open Library) devuelve **para esas mismas obras**, pedidos en vivo el
2026-09-04 con el field set de `_OL_SEARCH_FIELDS` más los cuatro campos del
filtro de la feature 73. Es el **oráculo** de los tests: el camino de dumps se
compara contra lo que produce el camino de `search.json`, nunca contra
literales escritos a mano.

Este es el primer fixture en fichero de toda la suite (el resto son `FakeClient`
con dicts inline). Va en fichero porque el objeto bajo prueba **es el formato**:
una línea de dump reescrita a mano dejaría de probar lo único que importa aquí
—que los parsers tragan el texto real— y probaría que sabemos escribir el
ejemplo que ya sabemos parsear.

## Las cinco obras y por qué están

| OLID | Obra | Qué demuestra |
|---|---|---|
| `OL24178205W` | The Love Hypothesis | Inglés que **pasa** el filtro. Tiene `ddc` (`813.6`) y `lcc` → géneros por la ruta principal |
| `OL18108064W` | Can't Hurt Me | Inglés que pasa. **Sin `ddc`** y con `lcc` de varias clases (`GV`, `V`) → voto de clase dominante |
| `OL17508740W` | The Summer I Turned Pretty Trilogy | Inglés que pasa. **Sin `ddc` ni `lcc`** → tercera fuente, `subject_facet` |
| `OL24456878W` | Psicología oscura | **Castellano** que pasa (2 ediciones, 205 páginas). Sin clasificación **ni** subjects → 0 géneros, que es la respuesta honesta |
| `OL8960135W` | Ultramarathon Man | Inglés que **no** pasa: 19 estanterías contra un suelo de 20. 11 ediciones y 295 páginas, así que el veredicto lo decide solo la notoriedad |

## Fichero a fichero

- **`reading_log.tsv`** (167 líneas). Formato propio de 4 columnas
  `work_key \t edition_key \t shelf \t date` (con `\N` cuando no hay edición),
  no el TSV de 5 columnas de los otros tres.
  - De las cinco obras de arriba lleva **las 25 primeras filas reales de cada
    una**, salvo `OL8960135W`, de la que lleva **sus 19 filas completas** — su
    recuento real en el dump es 19 y es lo que lo deja por debajo del umbral
    inglés. Truncar a 25 las demás es deliberado: sus recuentos reales son
    miles (9.031, 8.028, 3.670, 1.050) y meterlos enteros serían 22.000 líneas
    para no probar nada nuevo. 25 las coloca del mismo lado del umbral que el
    dump entero, que es lo que el test comprueba.
  - Y **todas** las filas de cuatro obras de contorno, con sus recuentos reales
    exactos: `OL4619760W` (4), `OL5920528W` (5), `OL983047W` (19) y
    `OL27714493W` (20). Clavan el suelo de la whitelist (5) y el umbral inglés
    (20) donde de verdad están. `OL27714493W` es además una de las obras que se
    contrastaron contra Solr: 20 en el dump, 20 en Solr.
- **`editions.tsv`** (51 líneas). Las **49 ediciones completas** de las cinco
  obras (13 + 12 + 11 + 11 + 2, que son exactamente los `edition_count` que
  devuelve `search.json`) más 2 ediciones reales de relleno. Están enteras a
  propósito: `edition_count`, la mediana de páginas, la unión de idiomas y el
  voto de clase dominante de `lcc` solo se pueden comparar contra `search.json`
  si el fragmento tiene todas las ediciones que Solr agregó.
  - Las 2 de relleno (`OL10000798M`, `OL10002736M`) apuntan a obras que **no
    están en la whitelist** y además **no tienen `languages`**: son los dos
    casos de descarte que el pipeline tiene que atravesar sin romperse.
- **`works.tsv`** (6 líneas). Las 5 obras más `OL10458677W`, un registro real
  cuyo JSON lleva a la vez escapes `\uXXXX` y comillas escapadas — la prueba de
  que `split("\t", 4)` es seguro sobre el texto real. Esa sexta obra tampoco
  está en la whitelist.
- **`authors.tsv`** (4 líneas). Los autores de cuatro de las cinco obras.
  **Falta a propósito `OL2144245A`** (Steven Turner, autor de *Psicología
  oscura*): es el caso "el autor no está en el dump de authors", que tiene que
  degradar a un libro con un credit menos, nunca a un libro perdido.
- **`search_docs.json`**. Los docs de `search.json` de las cinco obras.

## Qué puede envejecer

Los dumps son mensuales y Solr está vivo, así que `search_docs.json` y las
líneas de dump se irán separando (sobre todo en `readinglog_count`, que crece a
diario). No importa: **los dos lados están congelados aquí**, así que los tests
son deterministas. Si algún día hay que refrescar el fragmento, hay que
refrescar **los dos** en la misma sesión, o la comparación deja de significar
nada.
