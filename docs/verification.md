# Verification — Cómo verificar que el trabajo está completo

> Una feature no está `done` hasta que `bash init.sh` termina en verde
> Y el reviewer la aprueba.

## Comando principal

```bash
bash init.sh
```

Este script ejecuta en orden:

1. **Comprobación del entorno** — verifica que Python y uv están disponibles.
2. **Comprobación de archivos del harness** — verifica que existen todos los
   archivos de infraestructura (`AGENTS.md`, `feature_list.json`, etc.).
3. **Validación de `feature_list.json`** — formato correcto, máximo 1 feature
   `in_progress` simultáneamente.
4. **Lint** (`uv run ruff check .`) — cero errores.
5. **Format check** (`uv run ruff format --check .`) — cero issues.
6. **Tests** (`uv run pytest --tb=short -q`) — todos en verde.

Salida esperada al final:
```
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Si cualquier paso falla, el script termina con código de salida != 0 y
**no debes declarar la tarea como `done`**.

## Verificación manual de un endpoint nuevo

Para cada endpoint nuevo, el leader presenta al usuario una checklist que cubre:

1. **Estado de DB** — tablas/filas vía psql:
   ```bash
   psql $DATABASE_URL -c "\d <table_name>"
   ```

2. **Endpoint happy path** — curl con respuesta esperada:
   ```bash
   curl -s http://localhost:8000/<path>/<slug> | jq .
   # Expected: HTTP 200, campos requeridos presentes
   ```

3. **Endpoint not found** — verificar 404:
   ```bash
   curl -o /dev/null -w "%{http_code}" http://localhost:8000/<path>/slug-inexistente
   # Expected: 404
   ```

4. **On-demand fallback** — slug no en DB pero sí en API externa:
   ```bash
   # 1. Verificar que el slug NO está en DB
   # 2. Hacer GET → debería persistir y devolver 200
   # 3. Verificar que el slug YA está en DB
   ```

## Variables de entorno requeridas

Copiar `.env.example` a `.env` y rellenar antes de correr tests de integración:

```bash
cp .env.example .env
```

Ver `docs/external-apis.md` para las variables requeridas por cada API externa.

## Base de datos de test

Los tests de repositorio usan una DB PostgreSQL real (separada de la de desarrollo).
La variable `TEST_DATABASE_URL` debe apuntar a una DB de test limpia.

Alembic aplica las migraciones automáticamente en la sesión de test
a través de `conftest.py`.
