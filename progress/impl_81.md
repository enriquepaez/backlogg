# Informe de implementación — Feature 81 `trending_local`

Rama `feat/trending_local`. `bash init.sh` en verde: **1497 tests** (1482 al
arrancar), 0 errores de lint/format, sin warnings nuevos.

---

## 1. Archivos creados o modificados

### Creados

| Archivo | Qué es |
|---|---|
| `backlogg/trending/repository.py` (206 líneas) | Capa de acceso a datos del dominio. Agrega las tres tablas de actividad en un score decaído por item y resuelve ids → filas de catálogo en lote. |

### Modificados

| Archivo | Cambio |
|---|---|
| `backlogg/trending/service.py` | Reescrito (336 → 329 líneas). Sin adapters, sin `asyncio`, sin ingesta. Ventanas, vidas medias, umbral por tipo, fallback y mezcla. |
| `backlogg/trending/router.py` | Solo la `description` de OpenAPI (el contrato del endpoint no cambia). |
| `backlogg/core/config.py` | Nueva `TRENDING_MIN_ACTIVITY: int = 5`, junto a `CACHE_TTL_TRENDING`. |
| `.env.example` | Bloque `TRENDING_MIN_ACTIVITY` documentado. **El `.env` del usuario no se ha tocado** (`git status` lo confirma: solo aparece `.env.example`). |
| `backlogg/main.py` | Descripción del tag `trending` (decía «from the TMDB Trending API»). |
| `backlogg/movies/adapters/tmdb.py` | Retirado `get_trending_movies`. |
| `backlogg/series/adapters/tmdb.py` | Retirado `get_trending_series`. |
| `docs/api.md` §Trending | Reescrita. |
| `docs/external-apis.md` | Notas «Trending investigation» de Open Library e IGDB + nota de TheTVDB. |
| `docs/recommendations-plan.md` | Nota «Hecho (feature 81)» con los dos matices frente a lo que el plan preveía. |
| `tests/test_trending.py` | Reescrito (971 → 936 líneas, 40 tests). |
| `tests/test_response_caching.py` | `test_trending_listing_is_public` ya no mockea TMDB. |
| `tests/shared/test_slug_non_latin_fallback.py` | Retirados los dos tests de predicción de slug de `_ingest_trending_*` (las funciones ya no existen); los otros dos sitios de predicción siguen cubiertos. |
| `tests/shared/test_external_id_identity.py` | Comentario que citaba `trending` como puerta de escritura al catálogo. |

Sin migración Alembic: la feature no toca el esquema. Leí `alembic/versions/`
para confirmarlo (las tres tablas de actividad existen desde `0010`, `0012` y
`0025`, con sus índices `idx_*_item` por `(item_type, item_id)` y los triggers
`set_updated_at_*` de `0001`).

---

## 2. La descomposición anti-duplicación, y por qué es correcta

Es el punto que más condiciona el diseño, así que lo justifico entero. Está
también en el docstring de módulo de `backlogg/trending/repository.py`, que es
donde va a leerlo quien toque esto dentro de un año.

### El problema

`activity_events` no es una tercera fuente: es un **espejo parcial** de las otras
dos.

- `rating_created` ⇔ una fila de `user_ratings`. Uno como mucho por rating
  (`uq_activity_events_rating_id`), y `create_rating_event` es
  `ON CONFLICT DO NOTHING` sobre esa constraint.
- `status_completed` ⇔ una transición de `library_entries` a `completed`.
  `library/service.py` solo lo inserta si `previous_status != "completed"`.

Sumar las tres tablas enteras multiplica por ~3 el peso de un mismo gesto: quien
puntúa una película aparecería en `user_ratings` **y** en `activity_events`, y
quien la marca completada en `library_entries` **y** en `activity_events`.

### La partición

Dos hechos del modelo hacen que exista un recorte **disjunto y exhaustivo**:

1. `want` / `in_progress` / `dropped` **nunca** generan evento.
2. Una re-valoración **no** genera un segundo evento, pero sí es engagement
   fresco.

De ahí salen tres contribuciones que no se solapan:

| # | Contribución | Tabla | Recorte | Peso |
|---|---|---|---|---|
| 1 | Rating/review creado | `activity_events` `rating_created` | — | 3,0 |
| 1 | Item completado | `activity_events` `status_completed` | — | 2,0 |
| 2 | Intención de backlog | `library_entries` | `status IN ('want','in_progress','dropped')` | 1,0 / 1,5 / 0,5 |
| 3 | Re-valoración | `user_ratings` | `updated_at > created_at` | 1,0 |

**Por qué es disjunta**, contribución a contribución:

- **(1) ∩ (2) = ∅.** El único estado de `library_entries` que produce evento es
  `completed`, y (2) lo excluye explícitamente. La completitud se cuenta una vez
  y desde el evento, no desde la tabla.
- **(1) ∩ (3) = ∅**, con **dos** condiciones, no una. Ver la corrección de la
  segunda pasada más abajo: el argumento original solo tenía la primera y era
  **falso**.
  1. `updated_at > created_at` excluye la fila recién insertada (`created_at` y
     `updated_at` comparten `server_default=func.now()`, y el trigger
     `set_updated_at_user_ratings` es `BEFORE UPDATE`, así que un INSERT no lo
     dispara: son estrictamente iguales).
  2. `evento IS NULL OR updated_at > evento.created_at` excluye la edición que
     **creó** el evento. `rate_item` solo escribe el evento cuando el rating
     tiene contenido, así que `PUT {}` seguido de `PUT {"score": 4}` produce una
     fila cuyo evento nació en la segunda llamada: esa llamada ya la cuenta la
     contribución 1. Sin esta condición, una sola acción sumaba 3,0 + 1,0.
- **(2) ∩ (3) = ∅.** Son tablas distintas y gestos distintos.
- **Exhaustiva**: los cuatro gestos que el producto sabe registrar hoy —crear
  valoración, editar valoración, mover en el backlog, completar— caen cada uno
  en exactamente una fila.

**Cobertura de tests**: la clase `TestNoDoubleCounting` en `tests/test_trending.py`
comprueba las seis aristas. Deliberadamente pasa por los helpers de escritura de
**producción** (`upsert_rating` + `create_rating_event`, `upsert_library_entry` +
`create_status_completed_event`, las mismas dos llamadas que hacen
`ratings/service.py` y `library/service.py`) en vez de insertar filas a mano:
fabricar las filas a mano fabricaría también el solapamiento que el test existe
para detectar. Los casos:

- `test_a_rating_counts_once_not_twice` → 1, no 2.
- `test_a_completion_counts_once_not_twice` → 1, no 2.
- `test_rating_plus_completion_by_the_same_user_counts_twice` → 2. La red
  contra el fallo opuesto: dedupe que se convierte en infracontaje.
- `test_backlog_intent_counts_because_it_emits_no_event` → 3 (`want`,
  `in_progress`, `dropped`).
- `test_a_re_rating_adds_exactly_one_gesture` → 1.
- `test_a_fresh_rating_is_not_also_counted_as_a_re_rating` → 1.
- `test_giving_content_to_an_empty_rating_is_one_gesture_not_two` → 1. **Añadido
  en la 2.ª pasada**: evento y edición de la misma fila, los dos dentro de la
  ventana. Es el caso que fallaba.
- `test_an_edit_after_a_rating_that_already_had_its_event_counts_twice` → 2. La
  red contra la sobrecorrección: una edición realmente posterior al evento sigue
  siendo un gesto propio.

### Exclusiones obligatorias

- **`is_hidden`**: cubierto por los dos lados. En (1) hay un `LEFT JOIN` a
  `user_ratings` por `rating_id` con
  `rating_id IS NULL OR is_hidden = false` — el `OR` es lo que deja pasar los
  `status_completed`, que llevan `rating_id` NULL. En (3), `is_hidden = false`
  directo. Test: `test_hidden_review_does_not_push_an_item` — seis reviews
  ocultas con sus seis eventos dan `total_gestures == 0`.
- **Decaimiento explícito**: `0.5 ** (edad / vida_media)`, en SQL vía
  `power(0.5, extract(epoch from (now - ts)) / half_life)`. Constante nombrada
  (`DECAY_HALF_LIVES`), no un `ORDER BY created_at` disfrazado. Dos tests:
  `test_fresh_small_activity_beats_old_large_activity` (5 gestos de hace 6 días
  pierden contra 1 gesto de hace 1 minuto, que es exactamente el escenario que
  pide el brief) y `test_one_half_life_halves_the_contribution`, que verifica la
  propiedad algebraica: mover `now` una vida media exacta divide el score entre 2
  (`rel=1e-6`).

---

## 3. Decisiones de diseño

### 3.1 `period` gobierna tres ventanas

| | `day` | `week` |
|---|---|---|
| Ventana de actividad | 1 día | 7 días |
| Vida media del decaimiento | 6 h | 42 h |
| Ventana de estreno del fallback | 90 días | 365 días |

La vida media es un cuarto de la ventana en ambos casos, para que el cuarto más
reciente domine siempre: eso es lo que hace que «trending» signifique
*acelerando* y no simplemente *popular*. `test_decay_half_life_is_shorter_than_its_window`
guarda la propiedad, y `test_periods_cover_exactly_the_two_supported_values`
guarda que el enum no crece (FE-68 está construido contra `day`/`week`).

### 3.2 El fallback no reinventa el orden

`_list_recent_catalog` delega en `list_movies` / `list_series` / `list_books` /
`list_games` con `sort=*SortEnum.rating_desc` y
`filters=CatalogSearchFilters(date_from=cutoff)`. **Encajó sin deformar ningún
contrato**: `filters.date_from` ya existía desde la feature 50 y cada repositorio
ya lo enlaza a su propia columna de fecha (`build_catalog_filter_clauses`
recibe `date_col=Movie.release_date` / `Series.first_air_date` /
`Book.first_publish_date` / `Game.release_date`). Cero SQL nuevo para el
fallback, cero SQL crudo en `service.py`.

El tiempo va en el `WHERE` y el orden es el canónico de la 66. Cuatro tests
—uno por tipo— demuestran que `period` cambia el resultado:
`TestPeriod.test_period_narrows_the_{movie,series,book,game}_release_window`.
Ese es el punto de la feature y la deuda de la 68.

### 3.3 El borde de ventana vacía: se relaja, no se devuelve hueco

**Decisión: si la ventana deja cero resultados para un tipo, se retira la ventana
y se sirve el orden canónico sobre todo el catálogo.**

Razones:

1. Un hueco silencioso es peor para el llamante que un ítem algo más antiguo.
   FE-68 pinta bloques por tipo; un bloque vacío parece un fallo, no una
   respuesta.
2. Para **books** el caso vacío no es raro, es el normal:
   `first_publish_date` es la fecha de **publicación original**, así que un
   catálogo entero de clásicos tiene cero «estrenos» en 90 días. Lo mismo con
   ítems de fecha `NULL`, que nunca satisfacen `fecha >= cutoff`.
3. Solo se relaja con resultado **totalmente** vacío. Un resultado parcial (3 de
   5 posibles) se respeta tal cual: si se rellenara, `period` dejaría de notarse
   y volveríamos a la deuda de la 68. La ventana es un filtro real mientras
   filtre algo.

Coste: una segunda consulta al repositorio, y solo en el caso vacío.

Tests: `test_empty_release_window_relaxes_instead_of_returning_a_hole` (libro de
1927 con `period=day`) y
`test_item_without_a_release_date_is_only_reachable_after_relaxing` (juego con
`release_date=NULL`).

### 3.4 Umbral por tipo

`TRENDING_MIN_ACTIVITY` (default **5**). Cada tipo cuenta sus propios gestos en
su ventana y decide por separado; en el mix sin `type`, cada bloque de 5 decide
el suyo. Se compara contra el **número de gestos**, no contra el score decaído:
el umbral responde a «¿hay señal?», que es una pregunta de volumen, y un score
decaído haría que el mismo volumen cruzara o no el umbral según la hora del día.

El total se calcula con `sum(count(*)) OVER ()` sobre el agregado, de forma que
truncar a los `limit` mejores no lo distorsione y todo siga siendo **una sola
consulta**.

Tests: `test_threshold_is_evaluated_per_type_in_the_same_response` (BOOK con 6
gestos sirve local mientras GAME con 1 cae al fallback, en la misma respuesta) y
`test_threshold_is_configurable` (mismo dataset, resultado distinto con 99 y con
2).

Default 5 y no 1: con 1 gesto, un solo clic reordenaría el home entero. Y no 20:
con la comunidad arrancando, un umbral alto haría el trending local inalcanzable
y la feature invisible.

### 3.5 Número de consultas

Por tipo: **2** en el camino local (1 agregado + 1 resolución `id IN (...)` en
lote) y **2** en el fallback (las que ya hacía `list_*`: count + select), más 1 si
hay que relajar la ventana. Nunca una consulta por ítem. El mix sin `type` son 4
bloques secuenciales sobre la misma sesión (igual que antes: la sesión no admite
concurrencia).

### 3.6 Casing de `item_type` — verificado, no asumido

Comprobado en `ratings/repository.py::ITEM_MODELS` y en las rutas que alimentan
las tres tablas: el valor persistido es **mayúsculas** (`MOVIE`/`SERIES`/`BOOK`/
`GAME`). El servicio traduce el `?type=` en minúsculas con `TYPE_TO_ITEM_TYPE`.
Como las tres tablas son polimórficas sin FK, un casing equivocado no habría
fallado: habría devuelto cero filas para siempre. Por eso el repositorio se usa
con la misma constante que usan feed y library, y no con un literal nuevo.

### 3.7 Ítem con actividad cuyo registro de catálogo ya no existe

Se descarta, no revienta: `get_items_by_ids` devuelve un dict y el servicio filtra
`if item_id in rows`. Test:
`test_activity_on_a_deleted_catalog_row_is_dropped_not_fatal` (actividad sobre el
id 987654321, que no existe → 200 y solo el ítem vivo).

---

## 4. Qué se ha retirado de los adapters

`get_trending_movies` (`backlogg/movies/adapters/tmdb.py`) y
`get_trending_series` (`backlogg/series/adapters/tmdb.py`) **quedaron sin ningún
llamante** tras la reescritura. Comprobado con `grep` sobre todo el repo:
`scheduler/jobs.py`, `backlogg/main.py`, `scripts/` y `.github/workflows/` no los
mencionan; los únicos usos vivos eran `trending/service.py` y sus tests. Retirados
los dos métodos.

Retirado también del camino de trending, como estaba decidido:
`_ingest_trending_movie`, `_ingest_trending_series`, `_collect_movies`,
`_collect_series`, las instancias de módulo `_movies_tmdb` / `_series_tmdb` y los
imports de `_persist_movie_people` / `_persist_series_people` /
`_persist_series_creators` / `upsert_external_id` / `titled_slug`. Esas cuatro
funciones de persistencia **siguen existiendo y en uso** en sus dominios (GET
on-demand, fan-out de búsqueda, `/similar`, sync nocturno); lo que desaparece es
la llamada desde trending.

Consecuencia aceptada: `/trending` ya no descubre ni ingesta ítems nuevos.
`test_trending_makes_no_external_calls` la fija en el sitio correcto —la frontera
de transporte, reventando `httpx.AsyncClient.__init__`— en vez de mockear un
adapter con nombre, para que siga valiendo si alguien reintroduce un fan-out por
otro cliente. `test_tmdb_adapters_no_longer_expose_trending` impide que los
métodos vuelvan sin llamante.

---

## 5. Cosas encontradas y **no** tocadas

1. **`CACHE_TTL_TRENDING = 900` s ha dejado de tener el sentido que tenía.** Los
   900 s pagaban un fan-out a TMDB con ingesta de ítems: minutos de trabajo. Hoy
   el cómputo son dos consultas indexadas por tipo sobre tablas que estarán
   vacías o casi. El coste del TTL cambió de signo: ya no ahorra latencia cara,
   **añade hasta 15 minutos de retardo** entre el gesto de un usuario y su efecto
   en el home — justo lo que hace que un trending propio se sienta vivo frente al
   de TMDB. Sugerencia para una feature aparte: 60-120 s. **No lo he cambiado**,
   por indicación explícita del brief.
2. **Usuarios baneados sí empujan trending.** `feed/repository.py` excluye
   `User.is_banned` de sus listados; el ranking de trending no lo hace. El
   razonamiento («la actividad de una cuenta baneada no debería empujar nada»)
   es el mismo que el de `is_hidden`, pero el brief fijó exactamente dos
   exclusiones obligatorias y esta no era una, así que la dejo fuera de scope y
   la reporto. Costaría un `JOIN users` en cada una de las tres contribuciones.
3. **Sin índice sobre `activity_events.created_at`.** Los índices existentes son
   `idx_activity_events_item (item_type, item_id)` y
   `idx_activity_events_user (user_id, created_at)`. Las consultas nuevas filtran
   por `(item_type, created_at)`. Con el volumen actual (0 filas) no justifica una
   migración; si la comunidad crece, un índice
   `(item_type, created_at)` es la optimización obvia. Mismo comentario para
   `library_entries.updated_at` y `user_ratings.updated_at`.
4. **Des-ocultar una review cuenta como re-valoración.** Un admin que pone
   `is_hidden = false` dispara el trigger `set_updated_at_user_ratings`, así que la
   fila pasa a cumplir `updated_at > created_at` y aporta 1,0. Es un gesto de
   moderación, no de usuario. Efecto de un solo gesto y transitorio (decae);
   distinguirlo exigiría una columna `hidden_at` o un registro de moderación, que
   es esquema nuevo. Documentado aquí, no corregido.
5. **`now()` de Postgres es el timestamp de transacción.** No es un bug, pero
   condiciona los tests: toda la suite corre en **una** transacción, así que un
   UPDATE por ORM no puede producir `updated_at > created_at` como sí lo produce
   una segunda petición HTTP en producción. Por eso los tests que necesitan una
   edad concreta insertan las filas de actividad con timestamps explícitos, y solo
   los de no-duplicación usan los helpers reales. Está explicado en un comentario
   dentro de `tests/test_trending.py` para que no se lea como una comodidad.
6. **`bruno/Trending/`: verificado, sin cambios necesarios.** Los 8 `.bru` (mix
   default, los cuatro `type`, `period=day`, `period=week`, tipo inválido 422)
   siguen siendo correctos —forma de respuesta y códigos idénticos— y no hay
   huérfanos: no se ha añadido ni quitado ningún endpoint. **Corrección (2.ª
   pasada):** una versión anterior de este informe afirmaba que los dos `.bru` de
   `period` «han pasado de ser tautológicos a ejercitar de verdad la feature».
   Era falso, y el reviewer tenía razón: `Trending — period day.bru` y
   `— period week.bru` solo asertan `res.status: eq 200` y
   `res.body.results: isArray`; no comparan las dos respuestas entre sí ni miran
   contenido, y ni el archivo ni la aserción cambiaron. Eran smoke tests y lo
   siguen siendo. Que `period` ahora tenga efecto real lo demuestran los tests de
   `TestPeriod`, no Bruno. Hacer que Bruno lo ejercite es trabajo nuevo.

---

## 6. Output completo de `bash init.sh`

```
── 1. Verificando entorno ─────────────────────────────
[OK]    python3 -> Python 3.14.7
[OK]    uv -> uv 0.11.16 (x86_64-unknown-linux-gnu)

── 2. Verificando archivos base del harness ────────────
[OK]    Existe AGENTS.md
[OK]    Existe backend_feature_list.json
[OK]    Existe progress/current.md
[OK]    Existe docs/architecture.md
[OK]    Existe docs/conventions.md
[OK]    Existe docs/verification.md
[OK]    Existe docs/schema.md
[OK]    Existe docs/api.md
[OK]    Existe docs/external-apis.md
[OK]    Existe CHECKPOINTS.md

── 3. Validando backend_feature_list.json ──────────────────────
[OK]    backend_feature_list.json válido (90 features)

── 4. Lint (ruff) ──────────────────────────────────────
warning: The `tool.uv.dev-dependencies` field (used in `pyproject.toml`) is deprecated and will be removed in a future release; use `dependency-groups.dev` instead
All checks passed!
[OK]    ruff check pasa
warning: The `tool.uv.dev-dependencies` field (used in `pyproject.toml`) is deprecated and will be removed in a future release; use `dependency-groups.dev` instead
317 files already formatted
[OK]    ruff format pasa

── 5. Tests (pytest) ───────────────────────────────────
warning: The `tool.uv.dev-dependencies` field (used in `pyproject.toml`) is deprecated and will be removed in a future release; use `dependency-groups.dev` instead
........................................................................ [  4%]
........................................................................ [  9%]
........................................................................ [ 14%]
........................................................................ [ 19%]
........................................................................ [ 24%]
........................................................................ [ 28%]
........................................................................ [ 33%]
........................................................................ [ 38%]
........................................................................ [ 43%]
........................................................................ [ 48%]
........................................................................ [ 52%]
........................................................................ [ 57%]
........................................................................ [ 62%]
........................................................................ [ 67%]
........................................................................ [ 72%]
........................................................................ [ 76%]
........................................................................ [ 81%]
........................................................................ [ 86%]
........................................................................ [ 91%]
........................................................................ [ 96%]
.........................................................                [100%]
=============================== warnings summary ===============================
tests/shared/test_models.py::test_credit_primary_key_constraint
  <sys>:0: SAWarning: New instance <Credit at 0x7fd462f714d0> with identity key (<class 'backlogg.shared.models.Credit'>, (99001, 39, 'MOVIE', 'DIRECTOR'), None) conflicts with persistent instance <Credit at 0x7fd462f713d0>

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1497 passed, 1 warning in 40.27s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

El único warning (`SAWarning` en `tests/shared/test_models.py`) es preexistente
en `main` y ajeno a esta feature.

---

## 7. Criterios de aceptación

| # | Criterio | Dónde |
|---|---|---|
| 1 | Trending desde actividad local con decaimiento temporal, sin llamadas externas | `trending/repository.py::activity_scores`; `test_trending_makes_no_external_calls`, `TestDecay` |
| 2 | `period` con efecto real para los cuatro tipos | `TestPeriod` (4 tests de ventana de estreno + 1 de ventana de actividad) |
| 3 | Fallback documentado y probado | `docs/api.md` §Trending; `TestFallback` (7 tests) |
| 4 | Umbral de actividad configurable por env | `TRENDING_MIN_ACTIVITY` en `config.py` + `.env.example`; `TestThreshold` |
| 5 | `docs/api.md` actualizado: `period` deja de ser un parámetro sin efecto | §Trending reescrita; la «Limitación conocida» eliminada |
| 6 | Tests: con actividad, sin actividad, distintos `period` | `TestLocalActivity`, `TestFallback`, `TestPeriod` |
| 7 | `bash init.sh` en verde | §6 |

La feature **no** se marca como `done`: eso lo hace el leader tras el reviewer.

---

## 8. Segunda pasada — respuesta a `progress/review_81.md`

Veredicto recibido: **CHANGES_REQUESTED**, un bloqueante. El reviewer tenía
razón y lo había verificado contra la DB, no deducido. Arreglado.

### 8.1 BLOQUEANTE — una acción contada dos veces

**El fallo.** Mi argumento de disjunción `(1) ∩ (3) = ∅` asumía que el evento
`rating_created` nace en el mismo instante que la fila de `user_ratings`. Es
falso: `backlogg/ratings/service.py:82` condiciona la escritura del evento a que
el rating **tenga contenido**, y `RatingIn` admite `score` y `review_text` a
`None`, así que `PUT {}` es válido. Secuencia real:

1. `PUT {}` en T0 → fila en `user_ratings`, **sin** evento.
2. `PUT {"score": 4}` en T1 → **una sola acción** que crea el `rating_created`
   (contribución 1, peso 3,0) **y** deja `updated_at (T1) > created_at (T0)`,
   que mi contribución 3 volvía a contar (peso 1,0).

Un gesto contado como dos: peso 4,0 donde debe haber 3,0, y el contador que
alimenta `TRENDING_MIN_ACTIVITY` inflado. Es exactamente el requisito de
no-duplicación que se me fijó, y me lo salté por no leer la condición del
escritor: di por bueno que «crear fila» y «crear evento» eran el mismo momento.

**El arreglo** (`backlogg/trending/repository.py`, contribución 3). `LEFT JOIN`
a `ActivityEvent` por `rating_id`, con la condición que propuso el reviewer:

```
UserRating.updated_at > UserRating.created_at          # no es una fila recién creada
AND (event.id IS NULL OR UserRating.updated_at > event.created_at)   # ni la edición que creó el evento
```

Las dos condiciones son necesarias y ninguna implica a la otra. El
discriminante correcto no es «¿se editó después de nacer la fila?» sino «¿se
editó después de que naciera su evento?».

**El join no multiplica filas**: `uq_activity_events_rating_id` garantiza como
mucho un evento por `rating_id`. Es el mismo argumento que ya valía para el
`LEFT JOIN` de la contribución 1, que el reviewer verificó.

**El caso legítimo se preserva.** «Puntué en T0 (evento en T0), volví en T1 y
edité la review» → `updated_at (T1) > event.created_at (T0)` → sigue contando 2
gestos. Lo fija un test propio, para que el arreglo no se convierta en
infracontaje.

### 8.2 El test nuevo, y la confirmación de que falla contra el código anterior

Dos tests añadidos a `TestNoDoubleCounting`:

| Test | Espera |
|---|---|
| `test_giving_content_to_an_empty_rating_is_one_gesture_not_two` | 1 gesto |
| `test_an_edit_after_a_rating_that_already_had_its_event_counts_twice` | 2 gestos |

El primero es el caso que faltaba: evento y edición de la **misma fila**, los dos
**dentro** de la ventana. Mis dos tests anteriores lo esquivaban por
construcción (uno ponía el evento a 30 días, fuera de la ventana; el otro usaba
`updated_at == created_at`), tal y como señaló el reviewer.

Construido con los escritores de **producción** (`upsert_rating` sin contenido →
sin evento; después `upsert_rating` con contenido + `create_rating_event`), y
con un único retoque: retrasar `created_at`. Como el trigger
`set_updated_at_user_ratings` re-sella `updated_at` a `now()` por su cuenta, eso
reproduce exactamente la forma que deja el paso 2 — necesario porque `now()` de
Postgres es el timestamp de **transacción** y toda la suite corre en una sola.

**Confirmación de que falla contra el código anterior** (requisito explícito).
Quitando la línea de la condición nueva y volviéndola a poner:

```
$ python3 -c "...remove the event-timestamp condition..."
>>> fix temporarily reverted (condition line removed)
$ uv run pytest tests/test_trending.py -k "TestNoDoubleCounting" -q
E       assert 2 == 1
tests/test_trending.py:964: AssertionError
=========================== short test summary info ============================
FAILED tests/test_trending.py::TestNoDoubleCounting::test_giving_content_to_an_empty_rating_is_one_gesture_not_two
1 failed, 7 passed, 34 deselected in 0.82s

$ # fix restored
$ uv run pytest tests/test_trending.py -k "TestNoDoubleCounting" -q
8 passed, 34 deselected in 0.78s
```

`assert 2 == 1` — el doble conteo, medido. El test de sobrecorrección
(`...counts_twice`) pasa en las dos versiones, que es justo lo que debe hacer un
guard: no cambia de color con el arreglo, solo impediría pasarse de frenada.

### 8.3 Las tres correcciones baratas

4. **`progress/impl_81.md` §5.6 corregido.** La frase «los dos `.bru` de
   `period` han pasado de ser tautológicos a ejercitar de verdad la feature» era
   falsa: ni el archivo ni la aserción cambiaron, y siguen asertando solo
   `res.status: eq 200` y `res.body.results: isArray`. Reescrita, dejando la
   corrección visible en vez de borrarla. Que `period` tenga efecto real lo
   demuestra `TestPeriod`, no Bruno.
5. **`ACTIVITY_WEIGHTS` separada en tres.** Mezclaba tres tipos de clave y solo
   dos eran valores de columna. Ahora: `EVENT_WEIGHTS` (claves =
   `activity_events.event_type`), `INTENT_WEIGHTS` (claves =
   `library_entries.status`, y solo las tres que no emiten evento) y
   `RATING_EDIT_WEIGHT` (una constante suelta, porque no corresponde a ninguna
   columna). Desaparece la clave inventada `"rating_updated"`, que no era un
   `event_type` válido. `_weight_case` recibe ahora el dict en vez de una tupla
   de claves, lo que además elimina la duplicación entre `_INTENT_STATUSES` y la
   tabla de pesos.
6. **`docs/external-apis.md` pasado a inglés.** Mis tres inserciones (notas de
   Open Library, IGDB y TheTVDB) cambiaban a español a mitad de párrafo en un
   archivo escrito en inglés. Traducidas. (Las líneas 101 y 539 siguen en
   español, pero son contenido preexistente y ajeno a esta feature.)

### 8.4 Documentación corregida

El argumento de disjunción falso estaba en tres sitios, y en los tres se ha
corregido **dejando constancia del error** en vez de reescribir la historia:

- **`backlogg/trending/repository.py`**, docstring de módulo: la tabla pasa de
  «Re-rating / `updated_at > created_at`» a «Rating edit / edited *after* its
  own event», con un tercer hecho añadido a la lista (el evento se escribe
  cuando el rating tiene contenido, no cuando nace la fila) y un párrafo que
  explica por qué la segunda mitad de la condición no es redundante.
- **`docs/api.md` §Trending**: fila de la tabla de pesos corregida y párrafo
  nuevo con la secuencia `PUT {}` → `PUT {"score": 4}`.
- **`progress/impl_81.md` §2**: el punto `(1) ∩ (3) = ∅` ahora enumera las dos
  condiciones y señala que el argumento original era falso.

### 8.5 Fuera de alcance, como se me indicó

No he tocado nada de: usuarios baneados (punto 2 del review), toggle
`completed → dropped → completed` (punto 5), `COUNT(*)` desperdiciado en el
fallback (punto 6) ni `CACHE_TTL_TRENDING` (punto 3). Quedan como issues del
leader.

### 8.6 Verificación

`bash init.sh` en verde. **1499 tests** (1497 en la primera pasada, +2 nuevos),
`ruff check` y `ruff format --check` limpios sobre 317 archivos, y el mismo
único `SAWarning` preexistente de `tests/shared/test_models.py`, ajeno a esta
feature. Sin warnings nuevos.

```
── 5. Tests (pytest) ───────────────────────────────────
...........................................................              [100%]
=============================== warnings summary ===============================
tests/shared/test_models.py::test_credit_primary_key_constraint
  <sys>:0: SAWarning: New instance <Credit at 0x7f90ac493c50> with identity key (<class 'backlogg.shared.models.Credit'>, (99001, 39, 'MOVIE', 'DIRECTOR'), None) conflicts with persistent instance <Credit at 0x7f90a6c2ca50>

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1499 passed, 1 warning in 34.42s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Archivos tocados en esta segunda pasada: `backlogg/trending/repository.py`,
`tests/test_trending.py`, `docs/api.md`, `docs/external-apis.md`,
`progress/impl_81.md`. `.env` sigue intacto.
