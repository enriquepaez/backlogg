# Sesión actual

**Tarea:** issue #22 — los dos caminos de escritura de `external_ids` saltan un
enlace ya reclamado sin contador ni log. Instrumentar la pérdida silenciosa
antes de la siembra de producción.
**Tipo:** bugfix/observabilidad (no está en `backend_feature_list.json`) → el
reviewer devuelve veredicto **solo como texto**, sin archivo `progress/review_*.md`.
**Rama:** `fix/external_ids_skipped_link_observability`
**Inicio:** 2026-09-04
**Por qué ahora:** punto **3.2** de `progress/priority_order.md`. Es el panel de
instrumentos de la siembra: sin él, un fallo sistemático durante una carga de
118.850 ítems que dura horas se descubre cuando ya está horneado. Mismo
mecanismo que encadenó los issues #7 → #15 → #20.

## Decisión de diseño (tomada por el leader, el implementer la sigue)

**Colector por `contextvar`, no cambio de firma.** `upsert_external_id` tiene 11
llamadores en `backlogg/` (movies, series, books, games, trending, people,
jobs), y ninguno de ellos está en el camino que reporta: entre el helper y el
`dict` que devuelve el sync hay servicios intermedios (`upsert_movie_from_tmdb`
y compañía). Devolver `(row, skipped)` obligaría a enhebrar el dato por todas
esas firmas para nada — solo lo consume el job.

Contrato:

- `backlogg/shared/external_ids.py` expone un acumulador activable con un
  context manager (p. ej. `collect_link_skips()`), guardado en un `ContextVar`.
  Fuera de un bloque activo, registrar un salto es **no-op**: los servicios
  normales (búsqueda, ficha, `/similar`) no pagan nada ni fallan.
- El acumulador cuenta y guarda el detalle mínimo del salto:
  `(item_type, source, external_id, item_id que se intentaba enlazar,
  item_id que ya lo tiene)`.
- `ContextVar` es task-local: dos jobs concurrentes no se mezclan los contadores.

## Plan

1. **Colector** — `backlogg/shared/external_ids.py`: `ContextVar`, acumulador y
   context manager. Sin dependencias del scheduler (`shared/` no importa de
   `scheduler/`, `docs/architecture.md`).

2. **Camino per-item** — `upsert_external_id`: el pre-check ya distingue la fila
   existente; falta distinguir **por qué**. Si `existing_row.item_id == item_id`
   es idempotencia (misma persona en cast y crew) y **no** se cuenta. Si difiere,
   es el salto del issue: `logger.warning` nombrando terna, ítem pretendiente y
   reclamante actual, y `+1` en el acumulador.

3. **Camino batch** — `_upsert_external_ids` (`backlogg/shared/bulk_load.py`):
   hoy el `SELECT` de `claimed` trae solo la terna, así que no puede separar
   idempotencia de robo de enlace. Añadir `item_id` a ese `SELECT` y aplicar la
   misma regla que el punto 2, una línea de log por salto (o agregada si el
   volumen lo pide) y `+N` en el acumulador. **Sin consulta extra**: es la misma
   query con una columna más.

4. **Propagación al sync** — envolver el trabajo de `_run_tmdb_slice`,
   `sync_books`, `sync_games` y `sync_missing_credits` en el colector y añadir
   `skipped_links` al `dict` de retorno y a la línea de log de cierre, igual que
   `people_errors`. Añadir `skipped_links: int = 0` a `SyncResponse`
   (`backlogg/admin/schemas.py`) — con default, mismo criterio que
   `people_errors`, para los jobs que no lo devuelvan.

5. **Documentación** — `docs/api.md` (contrato del endpoint de sync),
   `docs/seeding-plan.md` (qué mirar mientras corre la siembra) y el docstring de
   cabecera de `scheduler/jobs.py`, que hoy enumera las claves del retorno.
   `bruno/`: no hay endpoint nuevo, pero si algún `.bru` fija el cuerpo esperado
   del sync, actualizarlo.

6. **Tests** — per-item: idempotente no cuenta, robo de enlace sí; batch: lo
   mismo dentro de un lote y contra fila preexistente; integración: un job de
   sync devuelve `skipped_links > 0` cuando el enlace está reclamado; y el
   no-op fuera del colector.

## Fuera de scope (deliberado)

`_unlinked_targets_stmt` (`backlogg/scheduler/repository.py`) da por convergido
un `seed_target` si existe **alguna** fila con su terna, sin mirar a qué
`item_id` apunta — el agravante que el issue #22 documenta. Arreglarlo obliga a
decidir **qué `item_id` es el dueño legítimo**, que es una decisión de datos, no
de instrumentación. Se queda fuera de esta rama; si al terminar sigue sin issue
propio, se registra en `issues_list.json`.

## Estado

- [x] Rama creada
- [x] `bash init.sh` verde (1220 tests)
- [x] implementer → `progress/impl_issue-22.md`
- [x] reviewer → **APPROVED** con 4 hallazgos, ninguno bloqueante (veredicto solo
      como texto, es un bugfix). H1 y H4 devueltos al implementer y cerrados
      (§9 del informe); H2 y H3 gestionados por el leader (ver abajo)
- [x] QA manual del leader → ver más abajo
- [ ] confirmación del usuario → commit + push + PR

## Hallazgos del reviewer y qué se hizo con cada uno

| # | Sev. | Destino |
|---|---|---|
| H1 | media-baja | Cerrado por el implementer. El guard intra-lote ya tiene dos tests que lo fijan a `item_id`, verificados por mutación en ambas direcciones. Hallazgo añadido: **ningún caller de producción alcanza hoy esa rama** (`bulk_load_items` deduplica por slug, `_resolve_people` por `(source, external_id)`), así que la única cobertura honesta es atacar `_upsert_external_ids` directamente |
| H2 | baja | **Issue #24 nuevo.** Falso negativo real: la colisión de slug en `_resolve_people` pierde un id externo de persona por la deduplicación `by_item`, y el contador no lo ve |
| H3 | baja | **Hecho en esta rama por decisión del usuario.** `.github/workflows/nightly-sync.yml` emite ahora un `::warning::` por `skipped_links` en los cuatro tipos, análogo al de `people_errors` |
| H4 | nit | Cerrado por el implementer (`MAX_TRACKED_LINK_SKIPS` en `__all__`, aserción de log anclada con `\b`) |

## Issues registrados desde esta rama

- **#23** (medium) — un ítem renombrado en la fuente deja una fila duplicada
  huérfana que nunca podrá tener `external_id`. **Confirmado con datos reales en
  la QA de abajo**, no es teórico.
- **#24** (low) — H2 del reviewer.
- **#25** (medium) — `_unlinked_targets_stmt` no comprueba `item_id`. Es el
  «fuera de scope» que el plan de esta rama dejó anotado.

## QA manual del leader — 2026-09-04, contra la DB de dev y TMDB reales

```
init.sh                 -> verde, 1241 tests, a la primera
guard sin mutantes      -> bulk_load.py:643 = `elif incumbent[1] != row[1]`
migraciones             -> ninguna nueva (0036 sigue siendo head)

camino per-item (DB real)
  idempotencia          -> no cuenta
  robo de enlace        -> count=1, detalle con pretendiente y reclamante
  gana el primero       -> las 3 llamadas devuelven el incumbente
  pretendiente          -> 0 filas en external_ids
  fuera del colector    -> no falla, loguea igual, no cuenta
  log real              -> "link skipped — MOVIE (TMDB, 99000022) wanted by
                           item_id=1359 is already claimed by item_id=1358"

job real (sync_series slice_size=5, TMDB en vivo)
  dict devuelto         -> synced=5 errors=0 people_errors=0 skipped_links=1
  línea de cierre       -> incluye "1 skipped_links"
```

**El tramo real encontró un salto a la primera, con solo 5 ítems.** Y el caso es
exactamente el issue #23: la serie de TMDB 284753 se renombró —de «Operation
Safed Sagar: The Highest Air Force Mission» a «... The Untold Story of the Kargil
War»—, el slug nuevo creó `series.id=1265` y el enlace se quedó en
`series.id=4`. Antes de esta rama, ese tramo habría reportado `errors: 0` y nadie
se habría enterado. Sigue habiendo 5 series sin enlace de 1.132.

Efecto secundario de la QA, benigno: la fila duplicada 1265 de la DB de dev
quedó con `last_synced_at` refrescado. Las filas de prueba del test per-item
(`qa-issue22-*`) se borraron al terminar.
