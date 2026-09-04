# Sesión actual

**Tarea:** issue #18 — los nombres (y los títulos) en alfabetos no latinos
slugifican a cadena vacía. Los credits se pierden y los ítems colisionan.
**Tipo:** bugfix (no está en `backend_feature_list.json`) → el reviewer devuelve
veredicto **solo como texto**, sin archivo `progress/review_*.md`.
**Rama:** `fix/non_latin_slug_fallback`
**Inicio:** 2026-09-04
**Por qué ahora:** punto **3.3** de `progress/priority_order.md`, el último antes
de la siembra. Si no se arregla, el catálogo nuevo nace con el agujero horneado
en 118.850 ítems y repararlo exigiría re-hidratarlo entero.

## Decisión de producto (tomada por el usuario, 2026-09-04): **opción B**

Cuando el fold a ASCII deja el slug vacío, **derivarlo del id externo** —
`tmdb-1234567`, `open-library-ol123w`, `igdb-4567` — en vez de transliterar.

Por qué B y no transliterar (`unidecode`/`anyascii`/`pypinyin`):

- La transliteración **empeora el issue #24**: colapsa identidades distintas
  (`张伟` y `章伟` → `zhang-wei`), y `upsert_person` resuelve la colisión de slug
  con `ON CONFLICT DO UPDATE`, así que dos personas se funden en una fila y una
  pierde su `external_id`. Cambia «perder el credit» por «atribuirlo a otra
  persona», que es peor porque no se ve.
- El id externo es **único por construcción** por `(item_type, source)`: cero
  colisiones, determinista, estable ante renombrados y ante cambios de versión
  de una librería de transliteración.
- Sin dependencia nueva (y sin el asunto de licencia: `Unidecode` es GPL).
- El coste —slug opaco— es hoy casi nulo: `apps/web` **no tiene ninguna ruta de
  persona**, solo pinta nombres en la sección Credits. El nombre para mostrar
  sigue en `people.name`/`title`, intacto y en su alfabeto original.

La transliteración se puede añadir después **encima** de un slug ya único y
estable, sin riesgo de pérdida de datos, cuando haya una razón concreta (una
página de persona en el frontend, por ejemplo).

## Alcance: personas **y** ítems

El issue está redactado solo sobre personas, pero el sondeo del leader
(2026-09-04, DB de dev) encuentra la misma causa raíz en los títulos, y ahí es
peor, porque el slug de ítem **sí** es la URL pública (`/[locale]/[type]/[slug]`):

```
movies id=137  '仙逆剧场版 弑仙之战'          -> slug ''
series id=459  '初次尝鲜'                     -> slug '-2025'
books  id=404  '人間失格'                     -> slug '-1948'
books  id=435  'Преступление и наказание'     -> slug '-1866'
people id=1148 'Фёдор Достоевский'            -> slug ''
```

El `-2025` sale de `slug = f"{slug_base}-{year}"` (`movies/adapters/tmdb.py:261`
y equivalentes) con `slug_base` vacío. **Es un imán de colisiones**: todos los
ítems de título no latino del mismo año caen en el mismo slug y el upsert por
slug los funde en una sola fila. Sobre 118.850 ítems eso no es un slug feo, es
catálogo que desaparece.

Va en esta rama por ser **la misma causa y el mismo helper**: separarlo obligaría
a tocar dos veces las cinco copias de `_slugify`.

## Plan

1. **Helper compartido** — hoy `_slugify` está duplicado en cinco módulos
   (`movies/adapters/tmdb.py`, `series/adapters/tmdb.py`,
   `books/adapters/open_library.py`, `games/adapters/igdb.py`,
   `admin/service.py`). Unificar en `backlogg/shared/` con dos funciones:
   el fold actual y `slug_with_external_fallback(text, source, external_id)`,
   que devuelve `slugify(source)-slugify(external_id)` cuando el fold queda
   vacío. `shared/` no puede importar de los dominios (`docs/architecture.md`).
2. **Personas** — aplicarlo donde se construye el `BulkPerson`
   (`_tmdb_person_row` en movies y series, `collect_series_creators`,
   `collect_book_authors`) y en el camino per-item (`people/repository.py`).
   Ahí ya están `source` y `external_id` a mano.
3. **Ítems** — aplicarlo al `slug_base` de los cuatro adaptadores **antes** de
   pegar el año. Regla: si el fold queda vacío, el slug es el del id externo
   **sin sufijo de año** (el id ya es único; añadir el año solo lo alarga).
4. **Validación que hoy descarta credits** — la ruta por lotes valida
   `person.slug` y tira el credit contando `people_errors`. Con el fallback ya
   no debería dispararse nunca por esta causa; **no quitar la validación**
   (sigue protegiendo de payloads realmente incompletos), pero verificar que
   deja de saltar.
5. **Datos existentes** — producción se borra y se siembra, así que **no hace
   falta migración de reparación**. Las 5 filas degeneradas de la DB de dev se
   corrigen solas al re-hidratar. Si el implementer ve razón para una migración
   de datos, que la argumente antes de escribirla.
6. **Documentación** — `docs/conventions.md` (regla de slug), `docs/schema.md`
   (qué garantiza el slug y qué no), `docs/seeding-plan.md` si menciona la
   pérdida de credits por este motivo.
7. **Tests** — nombre CJK, cirílico, árabe y mixto; título CJK con y sin año;
   dos personas distintas de alfabeto no latino **no** colapsan; dos ítems del
   mismo año **no** colapsan; un nombre latino normal produce exactamente el
   mismo slug que hoy (no regresión sobre el catálogo ya sembrado); y la ruta
   por lotes deja de contar `people_errors` por esta causa.

## Fuera de scope (deliberado)

- **Transliterar.** Decisión tomada: no ahora.
- **Issue #24** (colisión de slug entre dos personas con nombre latino idéntico).
  Esta rama lo reduce pero no lo cierra: dos personas homónimas en alfabeto
  latino siguen colapsando. Es un problema de identidad de `people`, no de
  alfabeto.
- **Issue #23** (renombrado → fila duplicada huérfana). Emparentado —el slug
  haciendo de identidad— pero es otra decisión.

## Estado

- [x] Rama creada
- [x] `bash init.sh` verde (1241 tests)
- [x] implementer → `progress/impl_issue-18.md` (ronda 2 tras CHANGES_REQUESTED; init.sh verde, 1322 tests)
- [x] reviewer → **CHANGES_REQUESTED** en la ronda 1, 3 hallazgos (veredicto solo
      como texto). Los tres cerrados en la ronda 2
- [x] segunda pasada → **la hizo el leader**: el agente reviewer se cayó por
      límite de sesión nada más arrancarla. Verificación propia abajo
- [x] QA manual del leader
- [ ] confirmación del usuario → commit + push + PR

## Hallazgos del reviewer (ronda 1) y cierre

| # | Sev. | Cierre |
|---|---|---|
| 1 | media | **Bloqueante.** Los cuatro sitios de predicción de slug no tenían test: revertidos a la fórmula pre-fix, la suite seguía verde. Cerrado con 4 tests que comparan la predicción contra lo que **genera el adaptador**, no contra un literal |
| 2 | baja | `docs/schema.md` prometía que ningún nombre no latino colapsa. Falso en alfabetos mezclados (`宮崎駿 Jr` → `jr`). Corregido, y estaba repetido en dos sitios más |
| 3 | baja | `titled_slug` podía devolver `""`. Resuelto por la vía (a): el ítem se **descarta y se cuenta** en las dos fronteras de escritura |

## Verificación del leader de la ronda 2 — 2026-09-04

Hecha por mí porque el reviewer no pudo. Reproducidas sus mutaciones:

```
predicción, sitio a sitio (revertido cada uno a la fórmula pre-fix)
  trending_movie   -> 1 failed, 3 passed   (falla exactamente su test)
  trending_series  -> 1 failed, 3 passed
  similar_movies   -> 1 failed, 3 passed
  similar_series   -> 1 failed, 3 passed
  mapeo 1:1 confirmado; archivos restaurados, md5 OK

guardas de slug vacío (`if not slug:` -> `if False:` en las dos fronteras)
  -> 2 failed (bulk_load_items y _write_items_individually)
  archivos restaurados, md5 OK

contenido de los tests de predicción
  -> expected = TMDBClient().movie_to_dict(dict(detail))["slug"], spy sobre
     get_*_by_slug, y segunda pasada con assert_awaited_once(): la predicción
     tiene que acertar sobre la fila que escribió la primera. Sin literales

init.sh -> verde, 1322 tests
```

### Precisión sobre el argumento del punto 3

El informe dice que un `raise` en `titled_slug` convertiría en 500 «`search` y
`trending`». **No es exacto**: los dos capturan `Exception` (y `search` usa
además `return_exceptions=True`), así que degradarían, no reventarían. El camino
que sí daría 500 es el on-demand de ficha (`movies/service.py:228`, que llama a
`movie_to_dict` sin protección y propaga al endpoint). La decisión de no lanzar
**se sostiene igual** por ese camino, y `docs/conventions.md` está bien escrito
—dice «los caminos on-demand», no nombra search ni trending—, así que no hay
nada que corregir: queda anotado para que nadie reutilice el argumento tal cual.

## QA manual del leader — contra la DB de dev y TMDB reales

```
adaptador real, payload real de TMDB
  series CJK 305977             -> slug 'tmdb-305977'  (antes, '-<año>')
  dos títulos CJK del mismo año -> 'tmdb-111' != 'tmdb-222'
  título latino                 -> 'fight-club-1999', idéntico a hoy

filas degeneradas de dev, sin tocar todavía:
  movies 137  '仙逆剧场版 弑仙之战'        slug ''
  series 459  '初次尝鲜'                   slug '-2025'
  books  404  '人間失格'                   slug '-1948'
  books  435  'Преступление и наказание'   slug '-1866'
  people 1148 'Фёдор Достоевский'          slug ''
```

Un caso que preparé mal y que conviene dejar escrito: quise comprobar el
fallback con la película 137 (`tmdb 1599191`) y **TMDB sirve hoy su título en
inglés** («Renegade Immortal: Battle of the Immortal Slayer»), así que el fold no
queda vacío, el fallback ni se activa y el slug nuevo es legible. No es un fallo:
el caso se demuestra con la serie 305977, donde TMDB sí sirve el título en CJK.
Y deja una lección para la siembra: **qué ítems caen en el fallback depende del
idioma que sirva la fuente ese día**, así que el volumen real solo se sabrá
midiéndolo durante la carga.

### Limpieza de las 5 filas de dev — hecha (autorizada por el usuario, 2026-09-04)

Las 5 filas degeneradas de dev **no se reparan re-sincronizando**: `slug` está en
`_NEVER_UPDATED` y `upsert_movie` conflicta por `slug`, así que un re-sync
**inserta una segunda fila** con el slug nuevo, y esa fila nace sin enlace en
`external_ids` (aparecería en `skipped_links`, issue #22). Lo honesto es
borrarlas antes de volver a sincronizar dev, y el usuario lo autorizó.

Antes de borrar se auditó qué colgaba de ellas: **solo catálogo, nada de
usuario** — cero `library_entries`, `ratings`, `reviews` y `list_items`. Borrado
en una transacción única:

```
movies  137          -> 1 credit,  1 external_id
series  459          -> 2 credits, 1 external_id
books   404 y 435    -> 2 credits, 2 external_ids, 3 joins de género
people  1148         -> 1 external_id (sus 2 credits ya caían con los ítems)

verificación: 0 slugs degenerados en las cuatro tablas
              movies 574 · series 1131 · books 387 · people 11721
```

Extra que no estaba previsto y sí hacía falta: `catalog_search` es una **vista
materializada**, así que las 4 filas borradas seguían apareciendo en búsqueda.
`REFRESH MATERIALIZED VIEW CONCURRENTLY catalog_search` → 4 huérfanas → 0.

Producción no necesita nada de esto: se borra y se siembra.
