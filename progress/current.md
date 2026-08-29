# Sesión actual — Decisiones de 2026-08-29

## Decisión 1: no se migra de APIs. El proyecto se queda en TMDB, IGDB y Open Library

Se evaluó a fondo migrar a TheTVDB (cine y series) y RAWG (juegos) para salir
de las licencias no comerciales de TMDB e IGDB. **Se descarta.**

El razonamiento: el coste de TMDB es **condicional** —149 $/mes solo cuando
monetizas, y solo monetizas si el producto funciona— mientras que el de migrar
es **cierto e inmediato**: tres semanas de trabajo, datos de cine peores, un
motor de siembra reconstruido desde cero y la pérdida de `/similar` y
`/trending`. Sería pagar un coste seguro para cubrirse de un problema que solo
aparece si hay éxito, gastando el recurso que hace falta para tenerlo. Con 105
suscriptores a 19 €/año se cubren los 1.788 $/año de TMDB.

Dato adicional que confirmó la decisión: el tramo gratuito de TheTVDB
(<50.000 $/año) **no es autoservicio** — exige la modalidad "Negotiated
Contract", que entra en cola de revisión comercial.

Las features de migración que se habían planificado quedan **eliminadas del
backlog** — el backlog es para trabajo real. La investigación completa (TheTVDB
v4 y RAWG: endpoints, auth, límites y trampas) se conserva íntegra en
`docs/external-apis.md`, que es suficiente para retomar el plan si el coste de
TMDB llega a pesar.

**Riesgo aceptado y su mitigación**: migrar más tarde dejaría huérfano el
historial de biblioteca de los usuarios, porque los ítems se identifican por
`external_ids`. Se neutraliza con la **feature 79**, que persiste el QID de
Wikidata de cada ítem — `external_ids` ya admite varios `source` por ítem. Con
ese ancla, cualquier cambio futuro de fuente es un remapeo mecánico.

## Decisión 2: sin rama épica

Al no haber migración, no hay un bloque de features que se rompan mutuamente.
Se vuelve al flujo normal de `AGENTS.md` §5: una rama por feature, PR a `main`.

## Lo que sí queda planificado (12 features `pending`)

| Bloque | Features | Estado |
|---|---|---|
| Calidad del catálogo de libros | 72, 73 | Listas para empezar, sin bloqueantes |
| Base de recomendación cross-type | 74-79 | 74 bloqueada por issue #15; 75 bloqueada por consulta legal a TMDB |
| Endpoints propios | 80-83 | Mejoras, no sustitutos |

Diseño completo en `docs/recommendations-plan.md`. Hallazgos sobre Open Library
(clasificación `ddc`/`lcc` y filtro de calidad de la siembra) en
`docs/external-apis.md`.

## ⚠️ Consulta legal pendiente antes de la feature 75

Los términos de TMDB listan «entrenar sistemas de machine learning / IA con
datos de TMDB» entre sus **ejemplos de uso comercial**. Generar embeddings
sobre sus sinopsis podría por tanto activar la licencia de 149 $/mes **antes**
de monetizar — justo lo que la decisión de quedarse buscaba evitar. Hay que
preguntarlo por escrito a `sales@themoviedb.org` antes de escribir código.

## La prioridad real no está en este backlog

Con 70 features de backend y 63 de frontend cerradas, lo que separa al proyecto
de producción es corto: páginas legales (aviso legal, privacidad, cookies —
**no existe ninguna**), decidir nombre y comprar dominio, salir del free tier de
Render (50 s de cold start), y el **issue #15** (créditos vacíos en el 100 % de
series y el 75 % de movies).

Las recomendaciones cross-type son el diferencial real del producto —ningún
competidor cruza cuatro verticales— pero se construyen **después** de tener
usuarios: un sistema de recomendación con cero usuarios no se puede evaluar.

Análisis estratégico completo (monetización, marketing e infraestructura):
https://claude.ai/code/artifact/43874a91-9655-40d6-88f9-a8082ad1dd08
