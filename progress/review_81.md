# Review — feature 81: trending_local

**Veredicto:** APPROVED
**Ronda:** 2.ª (la 1.ª fue `CHANGES_REQUESTED`; el rastro se conserva abajo)

El bloqueante está arreglado, y arreglado bien: no solo desaparece el doble
conteo, sino que **no se ha sobrecorregido** — que era el riesgo real de este
parche, porque un fallo simétrico no infla nada, silencia señal. Lo he vuelto a
sondear contra la DB con las mismas sondas de la primera ronda más tres nuevas.
Las tres correcciones baratas están hechas, y una de ellas (el split de pesos)
salió mejor que el nit que la pidió. El diff no se fue de alcance.

> Estado: el trabajo sigue **sin commitear** (`HEAD == main`, todo en working
> tree; `backlogg/trending/repository.py`, `progress/impl_81.md` y este archivo
> como untracked).

---

## 1. El bloqueante — RESUELTO y verificado contra la DB

**Qué se pedía (ronda 1):** una sola acción del usuario sumaba dos veces.
`PUT /v1/{type}/{slug}/rating {}` en T0 y `PUT {"score": 4}` en T1 → la segunda
petición creaba el `rating_created` **y** dejaba `updated_at > created_at`, así
que contribución 1 la contaba (3,0) y contribución 3 la contaba otra vez (1,0).

**Qué se ha hecho:** `backlogg/trending/repository.py:206-221`. La contribución
3 ahora hace `outerjoin(aliased(ActivityEvent), event.rating_id == UserRating.id)`
y añade `(event_of_rating.id.is_(None)) | (UserRating.updated_at >
event_of_rating.created_at)` (línea 219). El discriminante pasa de «editado
después de la **fila**» a «editado después de su **evento**». Es la condición
correcta y es la que yo señalé.

**Verificación (5 sondas contra la DB de test, no lectura de código):**

| Sonda | Escenario | Resultado |
|---|---|---|
| A | Caso bloqueante con filas fabricadas: `created_at = now-5h`, `updated_at = now-1h`, evento en `now-1h` | **1 gesto, peso 3,0000** (antes: 2 y 4,0) |
| B | Caso legítimo: evento en T0, edición en T1 | **2 gestos**, score `3.74602` == esperado exacto `3.0·2^(-5h/42h) + 1.0·2^(-1h/42h)` |
| C | Mismo caso que A pero **conducido por el servicio de producción** `rate_item(RatingIn())` → `rate_item(RatingIn(score=4))` | tras `PUT {}`: `events=0`; tras `PUT {score:4}`: `events=1` y **1 gesto** |
| D | Segundo evento para el mismo rating | rechazado por `uq_activity_events_rating_id` → el `LEFT JOIN` devuelve ≤1 fila |
| E | 5 usuarios × (`PUT {}` + `PUT {score}`) vía servicio | **5 gestos** (antes habrían sido 10) con `TRENDING_MIN_ACTIVITY = 5` |

Sobre cada punto que se me pidió comprobar:

- **La secuencia ahora suma 1 gesto y peso 3,0.** Sonda A, exacto: deshaciendo
  el decaimiento de 1 h el peso da `3.0000`, no `4.0`. Sonda C lo repite sin
  fabricar nada, llamando a `rate_item` como lo hace la ruta.
- **El caso legítimo NO se ha roto.** Sonda B: sigue dando 2 gestos, y el score
  coincide con el valor decaído esperado hasta `1e-6`, así que ni el conteo ni
  los pesos se han movido. La sobrecorrección era el riesgo serio aquí y no se
  ha producido.
- **El `LEFT JOIN` no multiplica filas.** No lo acepto por argumento: sonda D
  intenta insertar un segundo `ActivityEvent` con el mismo `rating_id` dentro de
  un savepoint y Postgres lo rechaza por `uq_activity_events_rating_id`. Además
  la condición de join es `event.rating_id == UserRating.id` y `rating_id` es
  NULL en todos los `status_completed`, así que esos nunca entran en el join
  (NULL nunca iguala). Cota real: ≤1 fila por rating.
- **El umbral cuenta los gestos correctos.** Sonda E: 5 usuarios haciendo el
  camino patológico completo dan exactamente 5 gestos. Con el código anterior
  habrían dado 10, cruzando el umbral con la mitad de actividad real. Esto era
  la mitad del daño del bug y estaba sin cuantificar; ahora está cerrado.

**Nota de por qué el `>` estricto es correcto y no frágil.** La sonda C imprime
`rating.updated_at == event.created_at -> True`: `rate_item` hace el UPDATE del
rating y el INSERT del evento en la **misma** transacción y hace un solo
`commit` (`backlogg/ratings/service.py:88`), y tanto el trigger
`set_updated_at_user_ratings` como el `server_default` de
`activity_events.created_at` usan `now()`, que en Postgres es el timestamp de
**transacción**. Los dos timestamps salen idénticos, así que `>` estricto
excluye ese caso por construcción, no por margen de tiempo. Y en el caso
legítimo el evento es de una transacción anterior, luego estrictamente menor.
El discriminante es exacto en los dos lados.

---

## 2. Los tests nuevos — hacen lo que dicen

**`test_giving_content_to_an_empty_rating_is_one_gesture_not_two`
(`tests/test_trending.py:919-964`).**

- **Falla de verdad contra el código anterior.** Verificado quitando la línea
  219 de `repository.py` y ejecutando: `assert 2 == 1` en
  `tests/test_trending.py:964`. Restaurado después, y `TestNoDoubleCounting`
  vuelve a 8/8 en verde.
- **No esquiva el caso por construcción**, que era el defecto de los dos
  vecinos. El evento se crea en el `now()` de la transacción y `updated_at`
  también, así que **ambos timestamps caen dentro de la ventana de 7 días** — es
  justo el solapamiento que `test_a_re_rating_adds_exactly_one_gesture` evita
  poniendo el evento a 30 días y que
  `test_a_fresh_rating_is_not_also_counted_as_a_re_rating` evita con
  `updated_at == created_at`.
- Usa los escritores de producción (`upsert_rating` con `score=None`, luego
  `upsert_rating` con `score=4` + `create_rating_event`), no filas a mano. Lo
  único fabricado es el back-date de `created_at`, inevitable porque toda la
  suite corre en una transacción, y está explicado en el propio test.
- Incluye `assert rating.updated_at > rating.created_at` **antes** del assert de
  gestos. Eso es lo que impide que el test se vuelva vacuo si alguien cambia la
  forma de la fila: pin explícito de que la fila sigue teniendo la forma que
  antes duplicaba.

**`test_an_edit_after_a_rating_that_already_had_its_event_counts_twice`
(`tests/test_trending.py:966-994`).** Cubre lo que dice cubrir: retrasa a T0
tanto `rating.created_at` **como** `event.created_at` y deja `updated_at` en
`now()`, de modo que la edición es posterior al evento y los dos timestamps
están dentro de la ventana. Espera 2. Verificado que **pasa en las dos
versiones** (con y sin la línea 219), que es exactamente su papel: no prueba el
fix, vigila que el fix no se pase de largo. Un test que también fallase antes no
serviría de guarda.

Cobertura de `TestNoDoubleCounting`: 6 → **8** tests. Las seis aristas de la
partición original siguen verdes.

---

## 3. Las tres correcciones baratas — hechas

**a) `progress/impl_81.md` §5.6 — corregida, no borrada.** Conserva la
afirmación original entre comillas, la marca como falsa con un bloque
«**Corrección (2.ª pasada)**», explica por qué (los `.bru` solo asertan
`res.status: eq 200` y `res.body.results: isArray`, y ni el archivo ni la
aserción cambiaron) y remite a `TestPeriod` como la prueba real. Es la forma
correcta de arreglar un informe: queda el rastro.

**b) `ACTIVITY_WEIGHTS` partido — y los pesos NO se han movido.** Comprobado
programáticamente, no leyendo la tabla:

```
old = {rating_created:3.0, status_completed:2.0, want:1.0, in_progress:1.5, dropped:0.5, rating_updated:1.0}
new = {**EVENT_WEIGHTS, **INTENT_WEIGHTS, 'rating_updated': RATING_EDIT_WEIGHT}
IDENTICAL: True
```

Y la sonda B confirma el mismo resultado por el otro extremo: el score decaído
sale idéntico al valor analítico con 3,0 y 1,0. Ningún número se movió en
silencio.

Además el split quedó **mejor que el nit que lo pidió**, porque ahora las claves
están atadas a las constantes reales del dominio, cosa que la tabla única no
permitía:

```
EVENT_WEIGHTS.keys()  == ACTIVITY_EVENT_TYPES                    -> True
INTENT_WEIGHTS.keys() == LIBRARY_STATUSES - {'completed'}        -> True
'rating_updated' no aparece en ninguno de los dos dicts          -> True
```

`RATING_EDIT_WEIGHT` queda como escalar suelto, que es lo honesto: no
corresponde a ninguna columna. Sin referencias colgando a `ACTIVITY_WEIGHTS` en
código (`grep` solo la encuentra en los dos informes, donde toca).

**c) `docs/external-apis.md` en inglés.** Las dos inserciones de las notas de
Open Library (líneas ~530-535) e IGDB (~676-681) están reescritas en inglés,
consistentes con el texto que las rodea.

---

## 4. `docs/api.md` ya no afirma nada falso al usuario

Era el punto que más me importaba de los tres, por ser contrato público. Está
bien resuelto:

- La fila de la tabla pasó de «Re-valoración · solo `updated_at > created_at`» a
  «**Edición de rating** · solo ediciones **posteriores al propio evento** de la
  fila». La condición documentada es ahora la que el SQL ejecuta.
- Se añadió un párrafo entero que explica el caso `PUT {}` → `PUT {"score": 4}`,
  dice explícitamente que comparar solo esas dos columnas contaría la acción dos
  veces (3,0 + 1,0), y documenta el discriminante correcto: `updated_at >
  evento.created_at` (o fila sin evento).

El mismo argumento corregido aparece en el docstring de módulo
(`repository.py:18-60`, que ahora incluye el tercer hecho del modelo y reconoce
explícitamente que la primera pasada lo tenía mal) y en `impl_81.md` §2. Los
tres sitios coinciden entre sí y con el código.

---

## 5. Alcance — no se ha ido

La 2.ª pasada tocó exactamente cinco archivos, todos en la lista pedida:
`backlogg/trending/repository.py`, `tests/test_trending.py`, `docs/api.md`,
`docs/external-apis.md` y `progress/impl_81.md`.

Verificado por conteo de líneas del diff contra `main`, que es idéntico al de la
1.ª ronda en todo lo demás: `service.py` 429, `router.py` 10, `config.py` 9,
`.env.example` 11, `main.py` 5, los dos adapters 15 cada uno,
`backend_feature_list.json` 2, `recommendations-plan.md` 16, los tres tests
compartidos 4/74/14. Ni un archivo nuevo respecto a la ronda anterior.

Los aplazados siguen **sin tocar**, como se acordó:

- `is_banned` no aparece en `backlogg/trending/` (punto 2 → issue tuyo).
- `CACHE_TTL_TRENDING: int = 900` intacto en `config.py:214`.
- `backlogg/library/service.py`, `ratings/service.py` y `feed/` fuera del diff
  → el toggle `completed → dropped → completed` (punto 5) y el `COUNT(*)`
  desperdiciado del fallback (punto 6) siguen como estaban.

> **Aclaración sobre `issues_list.json`.** Aparece como modificado en el working
> tree, pero **no es trabajo del implementer**: es el leader registrando la
> deuda como issues **29** (usuarios baneados), **30** (toggle
> `completed → dropped → completed`) y **31** (`COUNT(*)` desperdiciado).
> Revisado: los tres describen correctamente lo que reporté y no tocan
> `backlogg/` ni `tests/`. No cuenta como salida de alcance de la 2.ª pasada.
>
> Un detalle para que no se pierda: `CACHE_TTL_TRENDING = 900` (punto 1) **no
> tiene issue propio**; solo se menciona dentro de las notas del issue 31, que
> lo trata como acoplado («si el TTL baja, este issue sube de severidad»). Si la
> intención era registrarlo aparte, falta. No bloquea nada.

---

## 6. Sin regresión en lo que ya di por bueno

Suite completa en verde y los 8 tests de `TestNoDoubleCounting` re-ejecutados
tras restaurar el archivo. Sigue verificado de la ronda 1, y sin cambios en el
código que lo sostiene: casing en mayúsculas coherente entre escritores y
lectores; fallback delegando en los cuatro `list_*` con el orden canónico de la
66 y el tiempo en el `WHERE`; relajación solo con resultado totalmente vacío;
cero llamadas externas (fijado en la frontera de transporte, no mockeando un
adapter); adapters retirados sin llamantes huérfanos; `period` con efecto real y
no tautológico para los cuatro tipos; umbral por tipo; contrato de
`TrendingItemOut` y `PeriodEnum` intactos; 2 consultas por tipo sin N+1;
`is_hidden` excluido por los dos lados; decaimiento exponencial con constante
nombrada; `.env` sin tocar; issue #18 sin pérdida de cobertura.

Tests: **1497 → 1499** (+2, los dos nuevos de `TestNoDoubleCounting`).
`tests/test_trending.py`: 40 → 42.

---

## Checkpoints

- C1: [x] — `bash init.sh` exit **0**, ejecutado por mí.
- C2: [x] — sin `print()` en código nuevo.
- C3: [x] — sin TODO/FIXME/XXX.
- C4: [x] — `ruff check` + `ruff format --check` limpios (317 files).
- C5: [x] — 1499 passed, 1 warning (SAWarning preexistente en `main`, ajeno).
- C6: [x] — `select()`, `aliased()`, `AsyncSession`; sin `db.query()`.
- C7: [x] — N/A, sin cambios de esquema.
- C8: [x] — N/A, ídem.
- C9: [x] — `router.py:26`, `async` + `Depends(get_db)`.
- C10: [x] — `response_model=TrendingOut`, Pydantic v2.
- C11: [x] — sin ids en URL; cada resultado expone `slug`.
- C12: [x] — N/A, es un listado.
- C13: [x] — happy path cubierto, 42 tests en el módulo.
- C14: [x] — `service.py:206` convierte a `date` explícitamente.
- C15: [x] — los tests nuevos no escriben `external_ids`.
- C16 / C17: [x] — N/A, no hay on-demand externo.
- C18 / C19: [x] — N/A, no hay scheduler.
- C20: [x] — `router.py` sin lógica.
- C21: [x] — `service.py` sin queries; todo el SQL del dominio vive en `trending/repository.py`.
- C22: [x] — mapeo a `TrendingItemOut`, nunca ORM.

Los 7 criterios de aceptación de la entrada 81 quedan cubiertos, y el requisito
de no-duplicación de `progress/current.md` §«Trampa a evitar» está ahora
satisfecho **y probado por un test que falla sin el fix**.

---

## Nit menor (no bloquea, no requiere acción)

En `docs/external-apis.md:722` la línea añadida a la sección TheTVDB
(`Feature 81 is done: /trending calls no external API at all, not even TMDB.`)
está en inglés dentro de una viñeta en español. Las dos inserciones que yo
señalé sí quedaron consistentes; en esta tercera la mezcla se ha invertido. El
documento es bilingüe de origen (notas de adaptador en inglés, narrativa en
español), así que es cosmético. Lo dejo anotado por si el leader lo une a algún
paso de documentación.

---

## Rastro de la ronda 1 (`CHANGES_REQUESTED`)

**Bloqueante reportado:** doble conteo de una sola acción en
`repository.py` contribución 3, alcanzable por API pública
(`PUT {}` → `PUT {"score": 4}`); demostrado con sonda contra DB
(`total_gestures == 2`, peso 4,0 en vez de 3,0), afectando también al umbral.
Causa: el argumento de disjunción `(1) ∩ (3) = ∅` asumía que el evento se
escribe al crear la fila, cuando `backlogg/ratings/service.py:82` lo condiciona
al contenido. Sin test que cubriera el solapamiento: los dos que lo rozaban lo
esquivaban por construcción. Se pidieron tres cosas: la condición contra el
timestamp del evento, el test que falla sin ella, y corregir el argumento falso
en los tres sitios donde aparecía. → **Las tres hechas y verificadas.**

**Deuda registrada como issues por el leader (no tocada, correctamente):**
usuarios baneados empujando trending (existe ya
`ratings/repository.py:32 visible_review_filters()`, que empaqueta las dos
exclusiones); `CACHE_TTL_TRENDING = 900` con 15 min de lag; toggle
`completed → dropped → completed` inflando el umbral; `COUNT(*)` desperdiciado
en el fallback.

**Nits pedidos:** informe §5.6 corregido (no borrado), split de
`ACTIVITY_WEIGHTS` sin mover pesos, inserciones de `docs/external-apis.md` en
inglés. → **Los tres hechos.**

---

## Output de `bash init.sh` (ronda 2, ejecutado por el reviewer)

Exit code **0**.

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
...........................................................              [100%]
=============================== warnings summary ===============================
tests/shared/test_models.py::test_credit_primary_key_constraint
  <sys>:0: SAWarning: New instance <Credit at 0x7f3fd452b0d0> with identity key (<class 'backlogg.shared.models.Credit'>, (99001, 39, 'MOVIE', 'DIRECTOR'), None) conflicts with persistent instance <Credit at 0x7f3fd85d1650>

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1499 passed, 1 warning in 35.56s
[OK]    Todos los tests pasan

── 6. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```
