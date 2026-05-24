# Stage 1: builder — instala dependencias con uv
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Copiar archivos de dependencias primero para aprovechar caché de capas
COPY pyproject.toml uv.lock ./

# Instalar solo dependencias de producción
RUN uv sync --no-dev --frozen

# Stage 2: runtime — imagen final limpia
FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

# Crear usuario no-root para seguridad
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Copiar el virtualenv desde el builder
COPY --from=builder /app/.venv /app/.venv

# Copiar el código fuente
COPY backlogg/ ./backlogg/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini
COPY entrypoint.sh ./entrypoint.sh

# Hacer ejecutable el entrypoint
RUN chmod +x /app/entrypoint.sh

# Usar el usuario no-root
RUN chown -R appuser:appgroup /app
USER appuser

# Exponer puerto
EXPOSE 8080

# Añadir el virtualenv al PATH
ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["/app/entrypoint.sh"]
