# Harness Flow — Flujo completo de una feature

> Documento de referencia. Describe exactamente qué ocurre, en qué orden
> y qué archivo toca cada agente desde el momento en que el usuario dice
> "empieza la feature X" hasta el merge.
>
> Útil para comparar con el flujo real durante la implementación y detectar
> desviaciones.

---

## Visión general

```
Usuario
  │
  │ "empieza la feature N"
  ▼
Leader (Claude principal)
  │
  ├─ 1. Arranque y validación
  ├─ 2. Planificación → escribe progress/current.md
  ├─ 3. Lanza Implementer ──────────────────────────────────────────┐
  │                                                                  │
  │         Implementer                                             │
  │           ├─ Lee plan                                           │
  │           ├─ Marca in_progress                                  │
  │           ├─ Implementa + tests                                 │
  │           ├─ bash init.sh (bucle hasta verde)                   │
  │           └─ Escribe progress/impl_N.md → "done -> ..."        │
  │                                                                  │
  ├─ 4. Lanza Reviewer ◄────────────────────────────────────────────┘
  │
  │         Reviewer
  │           ├─ Lee impl_N.md + código
  │           ├─ bash init.sh
  │           ├─ Recorre CHECKPOINTS.md
  │           └─ Escribe progress/review_N.md → "APPROVED" | "CHANGES_REQUESTED"
  │
  ├─ [Si CHANGES_REQUESTED] → vuelve al paso 3 con feedback
  │
  ├─ 5. Finaliza (APPROVED)
  │     ├─ Marca done en backend_feature_list.json
  │     ├─ Escribe línea en progress/history.md
  │     └─ Limpia archivos temporales de progress/
  │
  ├─ 6. Manual QA → checklist al usuario
  │     └─ Espera confirmación explícita
  │
  └─ 7. Ship (con aprobación) → commit + push + PR
```

---

## Fase 0 — Trigger

**Actor:** Usuario  
**Acción:** Dice algo como _"empieza la feature 1"_, _"arranca"_ o _"siguiente feature"_.

El leader entra en acción. No espera instrucciones más detalladas — tiene toda
la información necesaria en `backend_feature_list.json` y `progress/current.md`.

---

## Fase 1 — Arranque del leader

**Actor:** Leader (Claude principal, actuando según `CLAUDE.md` + `leader.md`)

### Pasos en orden

1. **Lee `AGENTS.md`** — para orientarse en la estructura del repo.

2. **Lee `backend_feature_list.json`** — identifica qué feature corresponde:
   - Si el usuario nombró una feature concreta → la usa.
   - Si no → elige la de menor `id` cuyo `status == "pending"` y cuyos
     `depends_on` están todos en `"done"`.

3. **Lee `progress/current.md`** — comprueba si hay trabajo previo inacabado
   o bloqueado. Si lo hay, lo reporta al usuario antes de avanzar.

4. **Ejecuta `bash init.sh`** — si falla en cualquier paso, **para** y reporta
   el error. No avanza hasta tener el entorno verde.

5. **Crea la rama** `feat/<feature_name>` desde `main`:
   ```bash
   git checkout main
   git checkout -b feat/shared_models
   ```

### Archivos leídos en esta fase
- `AGENTS.md`, `backend_feature_list.json`, `progress/current.md`

### Archivos modificados en esta fase
- Ninguno todavía.

### Posibles bloqueos
- `init.sh` falla → el leader para y reporta el error concreto.
- `progress/current.md` tiene trabajo inacabado → el leader lo reporta
  y pregunta al usuario qué hacer antes de continuar.

---

## Fase 2 — Planificación

**Actor:** Leader

Antes de lanzar el implementer, el leader escribe el plan en
`progress/current.md`. **No avanza al paso siguiente hasta que este archivo
esté escrito.**

### Contenido del plan (progress/current.md)
```markdown
**Feature en curso:** 1 — shared_models
**Inicio:** 2026-05-24 10:30
**Estado:** in_progress

## Plan

1. Crear pyproject.toml con dependencias (fastapi, sqlalchemy, alembic, pydantic, ...)
2. Crear backlogg/core/database.py — AsyncEngine + get_db dependency
3. Crear backlogg/core/config.py — Settings con pydantic-settings
4. Crear backlogg/shared/models.py — Person, Credit (SQLAlchemy 2.0)
5. Crear backlogg/shared/external_ids.py — utilidad polimórfica
6. Crear alembic/ con alembic.ini y env.py
7. Crear migración 001_shared_models.py — crea external_ids, people, credits
8. Crear tests/test_shared_models.py
9. bash init.sh → verde

## Notas / Bloqueos

-
```

### Archivos modificados en esta fase
- `progress/current.md`

---

## Fase 3 — Implementación (subagente)

**Actor:** Implementer (subagente lanzado por el leader con `subagent_type: "implementer"`)

El leader lanza el implementer con una instrucción concisa que incluye:
- El ID y nombre de la feature
- La ruta del plan: `progress/current.md`
- La instrucción de responder solo con `done -> progress/impl_1.md` o `blocked`

### Protocolo interno del implementer

**Paso 1 — Lee contexto**
- `AGENTS.md`
- `docs/architecture.md`
- `docs/conventions.md`
- `progress/current.md` (el plan escrito por el leader)

**Paso 2 — Marca la feature `in_progress`**  
Edita `backend_feature_list.json`:
```json
"status": "in_progress"
```
> Esto bloquea que `init.sh` acepte otra feature simultánea.

**Paso 3 — Lee migraciones existentes**  
Antes de escribir ninguna migración, lee **todos** los archivos en
`alembic/versions/` (si existen). Regla dura: no recrear tablas ya creadas.

**Paso 4 — Implementa, archivo a archivo**  
Scope exacto = criterios de `acceptance` de la feature. Nada más.

Para la feature 1 (`shared_models`), los archivos creados serían:
```
pyproject.toml                          ← setup del proyecto
alembic.ini                             ← configuración Alembic
alembic/env.py                          ← integración SQLAlchemy async
alembic/script.py.mako                  ← plantilla de migración
alembic/versions/001_shared_models.py   ← external_ids + people + credits
backlogg/__init__.py
backlogg/core/__init__.py
backlogg/core/config.py                 ← Settings (pydantic-settings)
backlogg/core/database.py               ← AsyncEngine, get_db
backlogg/shared/__init__.py
backlogg/shared/models.py               ← Person, Credit (SA 2.0)
backlogg/shared/external_ids.py         ← utilidad polimórfica
tests/__init__.py
tests/conftest.py                       ← fixtures: engine, sesión, migraciones
tests/test_shared_models.py             ← tests de los modelos
```

**Paso 5 — Escribe tests junto al código**  
Regla dura: cada archivo de código nuevo tiene su test antes de avanzar
al siguiente archivo.

**Paso 6 — Bucle de verificación**
```bash
bash init.sh
```
- Si falla → el implementer vuelve al paso 4, corrige y reintenta.
- Si pasa → avanza al paso 7.

**Paso 7 — Escribe el informe**  
Crea `progress/impl_1.md` con exactamente:
```markdown
# Implementación — feature 1: shared_models

## Archivos creados / modificados
- pyproject.toml (creado)
- alembic/versions/001_shared_models.py (creado)
- backlogg/shared/models.py (creado)
- backlogg/shared/external_ids.py (creado)
- backlogg/core/database.py (creado)
- backlogg/core/config.py (creado)
- tests/conftest.py (creado)
- tests/test_shared_models.py (creado)
- backend_feature_list.json (modificado: status → in_progress)

## Resumen
[descripción de decisiones de diseño]

## Output de bash init.sh
[output completo pegado aquí]
```

**Paso 8 — Responde al leader**
```
done -> progress/impl_1.md
```
o, si hay un bloqueo irresolvible:
```
blocked -> ver progress/current.md
```

### Archivos leídos por el implementer
- `AGENTS.md`, `docs/architecture.md`, `docs/conventions.md`
- `progress/current.md`
- `alembic/versions/*` (todos, si existen)

### Archivos escritos por el implementer
- Código fuente en `backlogg/`, tests en `tests/`, migraciones en `alembic/`
- `backend_feature_list.json` (status → in_progress)
- `progress/impl_<id>.md`

### Posibles bloqueos
- `bash init.sh` no pasa después de N intentos → escribe `blocked` en
  `progress/current.md` y termina con `blocked -> ver progress/current.md`.
- Un cambio necesario toca otra feature → para y reporta.

---

## Fase 4 — Revisión (subagente)

**Actor:** Reviewer (subagente lanzado por el leader cuando existe `progress/impl_1.md`)

El leader verifica que `progress/impl_1.md` existe antes de lanzar el reviewer.

### Protocolo interno del reviewer

**Paso 1 — Lee el informe**
- `progress/impl_1.md` — lista de archivos modificados y decisiones

**Paso 2 — Lee los archivos modificados**  
Uno a uno, todos los que aparecen en el informe.

**Paso 3 — Lee el marco de calidad**
- `docs/architecture.md`
- `docs/conventions.md`
- `CHECKPOINTS.md`

**Paso 4 — Ejecuta `bash init.sh`**  
Si falla → rechazo inmediato. No sigue leyendo checkpoints.

**Paso 5 — Recorre CHECKPOINTS.md**  
Para cada checkpoint aplica o descarta según la feature:

| Checkpoint | Aplica a |
|---|---|
| C1–C5 | Todas las features |
| C6–C8 | Features con modelos o migraciones |
| C9–C13 | Features con endpoints |
| C14–C15 | Features que consumen APIs externas |
| C16–C17 | Features con on-demand fallback |
| C18–C19 | Solo feat 8 (scheduler) |
| C20–C22 | Features con routes + service + repository |

**Paso 6 — Escribe el veredicto en `progress/review_1.md`**
```markdown
# Review — feature 1: shared_models

**Veredicto:** APPROVED

## Checkpoints
- C1: [x] — init.sh termina con exit 0
- C2: [x] — sin print() de debug
- C3: [x] — sin TODOs sin contexto
- C4: [x] — ruff check pasa
- C5: [x] — pytest pasa (3 tests)
- C6: [x] — SQLAlchemy 2.0 con Mapped[] y mapped_column()
- C7: [x] — migración no recrea tablas previas (no hay previas)
- C8: [x] — upgrade() y downgrade() implementados
- C9-C22: N/A — no hay endpoints en esta feature

## Output de init.sh
[output completo]
```

**Paso 7 — Responde al leader con una sola línea**
```
APPROVED -> ver progress/review_1.md
```
o
```
CHANGES_REQUESTED -> ver progress/review_1.md
```

### Archivos leídos por el reviewer
- `progress/impl_<id>.md`
- Todos los archivos modificados listados en el informe
- `docs/architecture.md`, `docs/conventions.md`, `CHECKPOINTS.md`

### Archivos escritos por el reviewer
- `progress/review_<id>.md`

### El reviewer NUNCA
- Edita código del implementer
- Aprueba con init.sh en rojo
- Aprueba con tests en rojo
- Da feedback genérico (siempre cita archivo y línea)

---

## Fase 5 — Ciclo de correcciones (si CHANGES_REQUESTED)

**Actor:** Leader + Implementer (ronda adicional)

Si el reviewer devuelve `CHANGES_REQUESTED`:

1. El leader lee `progress/review_1.md` y extrae la lista de cambios requeridos.
2. Actualiza `progress/current.md` añadiendo los cambios solicitados como
   nuevas tareas al plan.
3. Re-lanza el implementer con el contexto del review.
4. El implementer lee `progress/review_1.md`, corrige los problemas citados,
   vuelve a ejecutar `bash init.sh` y sobreescribe `progress/impl_1.md`.
5. El leader vuelve a lanzar el reviewer (Fase 4).

Este ciclo se repite hasta obtener `APPROVED`.

### Archivos modificados en este ciclo
- Código corregido en `backlogg/` y `tests/`
- `progress/current.md` (actualizado con tareas de corrección)
- `progress/impl_<id>.md` (sobreescrito con nuevo informe)
- `progress/review_<id>.md` (sobreescrito con nuevo veredicto)

---

## Fase 6 — Finalización (tras APPROVED)

**Actor:** Leader

1. **Marca la feature como `done`** en `backend_feature_list.json`:
   ```json
   "status": "done"
   ```

2. **Añade una línea a `progress/history.md`**:
   ```
   2026-05-24 | feat 1: shared_models | Person, Credit, external_ids + migración inicial. 3 tests.
   ```

3. **Limpia archivos temporales de `progress/`**:
   - Vacía `progress/current.md` (vuelve a la plantilla)
   - Elimina `progress/impl_1.md`
   - Elimina `progress/review_1.md`

### Archivos modificados en esta fase
- `backend_feature_list.json` (status → done)
- `progress/history.md` (append de una línea)
- `progress/current.md` (vaciado)
- `progress/impl_<id>.md` (eliminado)
- `progress/review_<id>.md` (eliminado)

---

## Fase 7 — Manual QA

**Actor:** Leader → Usuario

El leader presenta al usuario una checklist concreta y ejecutable. No es
genérica — usa los datos reales de la feature implementada.

### Formato de la checklist (ejemplo feat 1)

```
## Manual QA — feature 1: shared_models

Antes de hacer el commit, confirma que:

### 1. Tablas creadas correctamente
```bash
psql $DATABASE_URL -c "\dt"
# Esperado: external_ids, people, credits aparecen en la lista

psql $DATABASE_URL -c "\d people"
# Esperado: columnas id, name, slug, profile_url, last_synced_at, created_at, updated_at

psql $DATABASE_URL -c "\d external_ids"
# Esperado: columnas id, item_type, item_id, source, external_id, created_at
#           constraints: uq_external_id (source, external_id), uq_item_source (item_type, item_id, source)
```

### 2. Migración reversible
```bash
alembic downgrade -1
# Esperado: tablas external_ids, people, credits desaparecen

alembic upgrade head
# Esperado: tablas vuelven a aparecer
```

### 3. Tests pasan
```bash
uv run pytest tests/test_shared_models.py -v
# Esperado: todos en verde
```
```

El leader **espera confirmación explícita** del usuario antes de avanzar
al Ship. No hace commit ni push hasta recibir un "todo correcto" o similar.

---

## Fase 8 — Ship

**Actor:** Leader, **solo con aprobación explícita del usuario**

```bash
# 1. Commit
git add .
git commit -m "feat(shared): Person, Credit, external_ids + migración inicial (closes #10)"

# 2. Push
git push -u origin feat/shared_models

# 3. Pull Request
gh pr create \
  --title "feat(shared): Person, Credit, external_ids + migración inicial" \
  --body "Closes #10

## Cambios
- Modelo Person (backlogg/shared/models.py)
- Modelo Credit (backlogg/shared/models.py)
- Utilidad external_ids (backlogg/shared/external_ids.py)
- Migración 001_shared_models (external_ids, people, credits)
- Tests de modelos (3 tests)

🤖 Generated with [Claude Code](https://claude.com/claude-code)" \
  --base main
```

### Formato del commit message
```
feat(<dominio>): <descripción corta> (closes #<issue>)
```

Ejemplos por feature:
| Feature | Commit |
|---|---|
| 1 | `feat(shared): Person, Credit, external_ids + migración (closes #10)` |
| 2 | `feat(movies): Movie model, TMDB adapter, GET /movies/{slug} (closes #2)` |
| 3 | `feat(series): Series model, TMDB adapter, GET /series/{slug} (closes #3)` |
| 7 | `feat(search): vista catalog_search, GET /search (closes #7)` |

### El leader NUNCA hace commit/push/PR sin estas condiciones
1. El reviewer ha emitido `APPROVED`
2. El usuario ha confirmado el Manual QA
3. El usuario ha dado aprobación explícita para el Ship

---

## Fase 9 — Hook de cierre de sesión

**Actor:** `.claude/settings.json` (ejecutado automáticamente por el harness)

Al terminar la sesión (Stop), el harness ejecuta:
```bash
bash init.sh > /tmp/backlogg_init.log 2>&1 \
  && echo '[harness] init.sh OK' \
  || (echo '[harness] init.sh FALLÓ — revisa /tmp/backlogg_init.log' \
      && tail -20 /tmp/backlogg_init.log)
```

Si `init.sh` falla en el cierre, el mensaje aparece en el terminal del usuario
como advertencia antes de que la sesión se cierre.

---

## Resumen de archivos por fase

| Fase | Archivos leídos | Archivos escritos |
|---|---|---|
| 1 — Arranque | AGENTS.md, backend_feature_list.json, progress/current.md | — |
| 2 — Plan | docs/*, backend_feature_list.json | progress/current.md |
| 3 — Implementación | AGENTS.md, docs/architecture.md, docs/conventions.md, progress/current.md, alembic/versions/* | backlogg/**, tests/**, alembic/**, backend_feature_list.json (in_progress), progress/impl_N.md |
| 4 — Revisión | progress/impl_N.md, backlogg/**, docs/architecture.md, docs/conventions.md, CHECKPOINTS.md | progress/review_N.md |
| 5 — Correcciones | progress/review_N.md | backlogg/**, progress/current.md, progress/impl_N.md |
| 6 — Finalización | progress/review_N.md | backend_feature_list.json (done), progress/history.md, ~~progress/impl_N.md~~, ~~progress/review_N.md~~ |
| 7 — QA | — | — (checklist al usuario) |
| 8 — Ship | — | git commit + push + PR |
| 9 — Hook cierre | — | /tmp/backlogg_init.log |

---

## Qué puede salir mal y dónde

| Problema | Fase | Señal | Respuesta |
|---|---|---|---|
| init.sh falla al arrancar | 1 | `[FAIL]` en terminal | Leader para y reporta. No avanza. |
| Trabajo inacabado en current.md | 1 | Estado != vacío | Leader reporta al usuario antes de continuar. |
| Implementer no puede pasar init.sh | 3 | Loop sin convergencia | Escribe `blocked` en current.md, responde `blocked -> ...` |
| Implementer toca otra feature | 3 | Cambio fuera del scope | Para y reporta al leader. |
| Reviewer encuentra checkpoints en rojo | 4 | `CHANGES_REQUESTED` | Leader relanza implementer con el feedback. |
| Reviewer encuentra init.sh en rojo | 4 | Rechazo inmediato | Implementer debe corregir antes de nueva revisión. |
| Usuario no confirma QA | 7 | Sin respuesta afirmativa | Leader no avanza al Ship. Espera indefinidamente. |
