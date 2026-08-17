# AGENTS.md — Mapa de navegación para agentes de IA

> Este archivo es el **punto de entrada** para cualquier agente que trabaje en
> este repositorio. Es un **mapa**, no una biblia de reglas. Lee solo lo que
> necesites cuando lo necesites.

---

## 1. Antes de empezar (obligatorio)

1. Ejecuta `bash init.sh` y verifica que termina sin errores. Si falla, **para**
   y resuelve el entorno antes de tocar código.
2. Lee `progress/current.md` para entender en qué estado quedó la última sesión.
3. Lee `backend_feature_list.json` y elige **una** tarea con estado `pending`. No
   trabajes en más de una a la vez.

## 2. Mapa del repositorio

| Archivo / carpeta              | Qué contiene                                                | Cuándo leerlo         |
|--------------------------------|-------------------------------------------------------------|-----------------------|
| `backend_feature_list.json`    | Lista de features con estado (pending/in_progress/done)     | Siempre, al empezar   |
| `frontend_feature_list.json`   | Backlog de features de frontend (`apps/web`), mismo formato | Al trabajar en frontend |
| `issues_list.json`             | Backlog de bugs/issues (open/resolved), fuente de verdad — `progress/issues.md` quedó obsoleto | Al reportar o resolver un bug |
| `progress/current.md`          | Estado de la sesión actual                                  | Siempre, al empezar   |
| `progress/history.md`          | Bitácora append-only de sesiones anteriores                 | Si necesitas contexto |
| `docs/architecture.md`         | Estructura, principios y flujo de datos del proyecto        | Antes de implementar  |
| `docs/conventions.md`          | Reglas de código obligatorias                               | Antes de escribir código |
| `docs/verification.md`         | Cómo verificar que el trabajo está completo                 | Antes de declarar done |
| `docs/schema.md`               | Esquema completo de la base de datos                        | Al diseñar modelos    |
| `docs/api.md`                  | Contratos de los endpoints REST                             | Al implementar rutas  |
| `docs/external-apis.md`        | Referencia de TMDB, Open Library e IGDB                    | Al implementar adapters |
| `CHECKPOINTS.md`               | Criterios objetivos de "estado final correcto"              | Para auto-evaluarte   |
| `.claude/agents/`              | Definiciones de subagentes (leader, implementer, reviewer)  | Si orquestas trabajo  |
| `backlogg/`                    | Código fuente de la aplicación                              | Para implementar      |
| `tests/`                       | Tests automáticos                                           | Para verificar        |
| `alembic/`                     | Migraciones de base de datos                                | Al añadir modelos     |

## 3. Reglas duras

- ⛔ **NUNCA toques el `.env` local del usuario.** Es su archivo de desarrollo
  con secretos reales, está en `.gitignore` y **no es recuperable** desde el repo
  si se pierde. Prohibido `cp .env.example .env`, `>`/`>>` sobre `.env`, `rm`,
  `mv` o cualquier escritura sobre `.env`. Para plantillas edita **solo**
  `.env.example`. Si un test necesita variables de entorno, expórtalas en el
  proceso (`set -a; source .env` en local ya lo hace el usuario) o usa las de CI;
  jamás generes ni sobrescribas `.env`.
- **Una sola feature a la vez.** No mezcles cambios de varias features.
- **No declares una tarea `done` sin pruebas verdes.** Ejecuta `bash init.sh`
  y asegúrate de que termina sin errores.
- **Documenta lo que haces** en `progress/current.md` mientras trabajas.
- **Si no sabes algo, busca en `docs/`** antes de inventarlo.
- **Fecha strings de APIs externas** siempre se convierten explícitamente a
  `date`/`datetime` de Python antes de pasarlos al repositorio.

## 4. Cómo elegir una tarea

```
1. Abre backend_feature_list.json
2. Filtra por status == "pending"
3. Respeta depends_on — no empieces una feature si sus dependencias no están "done"
4. Coge la de menor "id" que tenga sus dependencias satisfechas
5. Cambia su status a "in_progress" y guarda
6. Anota en progress/current.md: feature, hora de inicio, plan breve
```

## 5. Flujo por feature (workflow completo)

1. **Branch** ⚠️ **BLOQUEANTE** — antes de cualquier otra acción:
   ```
   git checkout main && git pull
   git checkout -b feat/<feature_name>
   git branch --show-current   # debe mostrar feat/<feature_name>
   ```
   Si la rama ya existe: `git checkout feat/<feature_name>`.
   **Nunca se trabaja en `main`. Si estás en `main`, crea la rama primero.**
2. **Plan** — escribe el plan en `progress/current.md`.
3. **Implement** — lanza el subagente `implementer`.
4. **Review** — cuando exista `progress/impl_<feature_id>.md`, lanza `reviewer`.
   El reviewer guarda su veredicto en `progress/review_<feature_id>.md` **solo si la tarea forma parte del `backend_feature_list.json`**. Para bugfixes o cambios puntuales fuera del backlog, devuelve el veredicto únicamente como texto — sin crear ningún archivo en `progress/`.
5. **Finalize** — con aprobación del reviewer: marca `done`, mueve resumen a
   `progress/history.md`, limpia archivos temporales de `progress/`.
6. **Manual QA** — presenta al usuario una checklist de tests manuales.
   Espera confirmación antes de seguir.
7. **Ship** — al terminar la feature, pide confirmación al usuario antes de ejecutar
   los siguientes pasos (en inglés):
   - `git add` de los archivos relevantes + `git commit -m "<message>"` (sin firma de autoría)
   - `git push -u origin <branch>`
   - `gh pr create` apuntando a `main`
   El mensaje de commit usa el formato: `feat(<domain>): <short description>` (en inglés).
   Espera confirmación explícita antes de ejecutar cualquiera de estos comandos.

## 6. Cierre de sesión

Antes de terminar:

1. Ejecuta `bash init.sh` — todo verde.
2. Si la tarea está acabada: marca `status: "done"` en `backend_feature_list.json`.
3. Mueve el resumen de `progress/current.md` al final de `progress/history.md`.
4. Vacía `progress/current.md`.
5. No dejes archivos temporales, `print()` de debug, ni TODOs sin contexto.

## 7. Si te bloqueas

- Relee la sección relevante de `docs/`.
- Documenta el bloqueo en `progress/current.md` con estado `blocked` y para la sesión.
