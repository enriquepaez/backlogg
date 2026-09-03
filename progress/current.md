# Sesión actual

**Tarea:** issue #20 — `uq_external_id` es único sobre `(source, external_id)` sin
`item_type`; los ids de TMDB de personas bloquean el enlace de movies/series.
**Tipo:** bugfix (no está en `backend_feature_list.json`) → el reviewer devuelve
veredicto solo como texto, sin archivo `progress/review_*.md`.
**Rama:** `fix/uq_external_id_item_type`
**Inicio:** 2026-09-04
**Por qué ahora:** `progress/priority_order.md` lo inserta como prerrequisito del
bloque A, antes de la feature 87. Bloquea la siembra real contra producción.

## Plan

1. **Esquema** — `UNIQUE (item_type, source, external_id)` sustituye a
   `UNIQUE (source, external_id)`. Migración 0036 con `upgrade`/`downgrade`.
   El `downgrade` tiene que ser honesto: al reapretar la restricción global
   puede fallar si ya existen pares legítimos duplicados entre tipos.
2. **Lectores** — auditar todo lo que resuelve por `(source, external_id)` sin
   `item_type` y añadirlo:
   - `upsert_external_id` (pre-check "first claim wins") — `backlogg/shared/external_ids.py`
   - `_upsert_external_ids` (pre-check por lotes) — `backlogg/shared/bulk_load.py:630`
   - Ya correctos (filtran por tipo), verificar y no tocar: `_resolve_people`
     (bulk_load:675), `people/repository.py:112`, `_unlinked_targets_stmt`
     (scheduler/repository.py:301).
3. **Reparación de datos** — los ítems perdidos no tienen fila que arreglar: les
   falta. La reparación es reabrir sus `seed_targets` retirados como
   `unlinkable` (`attempts >= TMDB_SEED_MAX_ATTEMPTS`, `unreachable_at IS NULL`,
   sin fila en `external_ids`) poniendo `attempts = 0`, para que la hidratación
   normal los vuelva a coger y ahora sí los enlace.
4. **Documentación** — la restricción global está descrita como comportamiento
   esperado en muchos sitios (`docs/schema.md`, `backlogg/shared/models.py`,
   `scheduler/jobs.py`, `scheduler/repository.py`, `core/config.py`,
   `alembic/versions/0035_seed_targets.py`, tests). Actualizar todos: hoy
   documentan una limitación que deja de existir.
5. **Tests** — `tests/shared/test_models.py:125` afirma hoy lo contrario de lo
   que queremos; invertirlo. Añadir el caso que reproduce el issue: mismo
   `(source, external_id)` para un PERSON y una SERIES, ambos enlazan.

## Estado

- [x] Rama creada
- [x] `bash init.sh` verde (1213 tests)
- [x] implementer → `progress/impl_issue-20.md`
- [x] reviewer → CHANGES_REQUESTED (4 hallazgos, todos de texto) → corregidos
- [x] QA manual del leader → ver más abajo
- [ ] confirmación del usuario → commit + push + PR

## QA manual del leader — 2026-09-04, contra la DB de dev y TMDB reales

```
restricción            -> uq_external_id = UNIQUE (item_type, source, external_id)
reparación 0036        -> reabre exactamente los 7 targets del issue, attempts=0
                          (los otros 745 de 2022, intactos)
diagnóstico original   -> confirmado: los 7 ids estaban reclamados por filas PERSON
hidratación real       -> sync_series(slice_size=10): synced=10 errors=0
                          people_errors=0 pending=0 stuck=0 refreshed=3 en 1,4 s
enlace                 -> los 7 ids tienen ya fila SERIES conviviendo con la PERSON
duplicados             -> 0: series sigue en 1.132 filas, 0 slugs duplicados
residuo                -> 12 -> 5 series + 1 libro (issue #21, no alcanzable)
downgrade              -> falla ruidosamente nombrando (TMDB, 130567), sin DELETE
                          silencioso, y hace ROLLBACK atómico: queda en 0036
init.sh                -> verde, 1220 tests, a la primera
```

El `downgrade` que falla **no es un defecto**: es el contrato documentado en el
docstring de la `0036`. Consecuencia operativa a tener presente: una vez la
siembra enlace ítems que comparten id entre tipos, **esta migración deja de ser
reversible** sin decidir a mano qué filas sacrificar.

## Derivado — issue #21 (medium), registrado

La reparación de la `0036` solo alcanza a los ítems con fila en `seed_targets`.
Los que entraron por `/popular`, búsqueda o `/similar` no tienen target que
reabrir, y su id externo no es recuperable de la DB porque nunca se escribió.
Quedan congelados: la rotación de refresco no los visita (INNER JOIN en
`get_stale_catalog_external_ids`) y `get_credit_gaps` los descarta. En
producción es previsiblemente peor: si `seed_targets` está vacía, el `UPDATE`
de la `0036` tocará 0 filas.
