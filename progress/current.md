# Sesión actual — Épico: migración de fuentes + recomendaciones cross-type

**Inicio:** 2026-08-29
**Rama base del épico:** `epic/source-migration`
**Snapshot previo:** tag `v0.1-tmdb-igdb` (main en 2dddc84, catálogo sobre TMDB + IGDB)

## Por qué existe este épico

TMDB prohíbe el uso comercial bajo su licencia gratuita (149 $/mes desde el
primer euro de ingreso) e IGDB tiene la misma restricción bajo el Twitch
Developer Services Agreement. TheTVDB es gratis por debajo de 50.000 $/año de
facturación y RAWG permite uso comercial hasta 20.000 peticiones/mes.

Se migra **ahora, con el catálogo sin usuarios reales**, porque el coste de
hacerlo después no es el código: es que cada entrada de biblioteca, rating y
reseña cuelga de ítems identificados por `external_ids`, y re-sourcing con
usuarios dentro dejaría huérfano el historial de quien tuviera ítems que la
nueva fuente no cubre.

Documentación de referencia, toda en el repo (una sesión nueva no necesita
nada más):

- `docs/external-apis.md` — referencia de TheTVDB v4 y RAWG (endpoints, auth,
  límites, trampas), y los hallazgos sobre clasificación y calidad de Open
  Library.
- `docs/recommendations-plan.md` — diseño de las cuatro capas de similitud
  cross-type y del ranker.
- `.env.example` — `THETVDB_API_KEY` y `RAWG_API_KEY` con sus notas.

Análisis estratégico completo (monetización, marketing e infraestructura), como
artifact fuera del repo:
https://claude.ai/code/artifact/43874a91-9655-40d6-88f9-a8082ad1dd08

## Desviación deliberada del flujo de AGENTS.md §5

`AGENTS.md` manda abrir PR **a `main`** por cada feature. Durante este épico
**no**: cada feature sale de `epic/source-migration` y vuelve a
`epic/source-migration`. `main` se queda intacta sobre TMDB + IGDB, funcionando
y verde, hasta que el épico esté completo y coherente — un `main` a medio
migrar no arrancaría, porque las features 72-78 se rompen mutuamente hasta que
el corte (78) está hecho.

El PR a `main` es **uno solo**, al final, de todo el épico.

Todo lo demás del flujo se mantiene: rama por feature, implementer, reviewer,
QA manual, y confirmación del usuario antes de commit/push/PR.

## Bloqueantes antes de lanzar el primer implementer

- [ ] **Clave de API de TheTVDB** — cuenta en thetvdb.com, modalidad
      **licenciada** (no la "sostenida por usuarios", que obliga a que cada
      usuario final pague 12 $/año). Gratis en el tramo <50.000 $/año.
- [ ] **Clave de API de RAWG** — registro gratuito en rawg.io/apidocs.
- [ ] Ambas en el `.env` del usuario (los agentes **no** tocan ese archivo) y
      añadidas a `.env.example` como plantilla.

## Orden de ejecución

Las features 75, 76 y 77 (RAWG y libros) **no dependen** de TheTVDB: pueden
avanzar en paralelo mientras se consigue la clave.

| Bloque | Features | Nota |
|---|---|---|
| A · Migración | 72 → 78 | 74 es la cara: TheTVDB no tiene feed de popularidad paginado |
| B · Base de recomendación | 79 → 84 | 79 bloqueada por el issue #15 (créditos vacíos) |
| C · Endpoints propios | 85 → 88 | 85 y 86 sustituyen a `/similar` y `/trending` de TMDB |

## Issues relacionados

- **#15** (abierto, high): créditos vacíos en el 100 % de series y el 75 % de
  movies. Bloquea la feature 79 y degrada el SEO de las fichas. La reingesta
  de la feature 78 debería resolverlo de paso — verificarlo explícitamente.
