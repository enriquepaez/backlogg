# Sesión actual

Sprint 2 planificado. 9 features añadidas al backlog (ids 14–22). Sin feature en curso.

## Features pendientes Sprint 2

| ID | Nombre                   | Depende de     | Estado  |
|----|--------------------------|----------------|---------|
| 14 | list_endpoints           | [2,3,4,5]      | pending |
| 15 | genres_endpoint          | [14]           | pending |
| 16 | similar_items            | [2,3]          | pending |
| 17 | search_external_fallback | [7]            | pending |
| 18 | admin_api_key            | [8]            | pending |
| 19 | book_authors_people      | [4,6]          | pending |
| 20 | trending_popular         | [2,3]          | pending |
| 21 | credits_in_detail        | [2,3,5,6]      | pending |
| 22 | cors_and_security        | [9]            | pending |

## Orden de arranque recomendado

Primer batch (paralelas, sin dependencias entre sí):
- **14** (list_endpoints) — desbloqueará la 15
- **16** (similar_items)
- **17** (search_external_fallback)
- **18** (admin_api_key)
- **19** (book_authors_people)
- **20** (trending_popular)
- **21** (credits_in_detail)
- **22** (cors_and_security)

Después de 14: **15** (genres_endpoint)
