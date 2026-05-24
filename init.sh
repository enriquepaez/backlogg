#!/usr/bin/env bash
# init.sh — Verificación e inicialización del entorno
#
# Este script lo ejecuta el agente al COMENZAR una sesión y antes de
# declarar cualquier tarea como `done`. Si falla, la sesión no debe avanzar.

set -u
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

ok()   { printf "${GREEN}[OK]${NC}    %s\n" "$1"; }
warn() { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; }
fail() { printf "${RED}[FAIL]${NC}  %s\n" "$1"; }

EXIT_CODE=0

echo "── 1. Verificando entorno ─────────────────────────────"

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 no está disponible"
  exit 1
fi
ok "python3 -> $(python3 --version)"

if command -v uv >/dev/null 2>&1; then
  ok "uv -> $(uv --version)"
elif [ -f "pyproject.toml" ]; then
  fail "uv no está disponible pero pyproject.toml existe — instala uv antes de continuar"
  EXIT_CODE=1
else
  warn "uv no disponible todavía (proyecto sin código — se instalará con pyproject.toml)"
fi

echo ""
echo "── 2. Verificando archivos base del harness ────────────"

for f in AGENTS.md feature_list.json progress/current.md \
          docs/architecture.md docs/conventions.md docs/verification.md \
          docs/schema.md docs/api.md docs/external-apis.md \
          CHECKPOINTS.md; do
  if [ ! -f "$f" ]; then
    fail "Falta archivo base: $f"
    EXIT_CODE=1
  else
    ok "Existe $f"
  fi
done

echo ""
echo "── 3. Validando feature_list.json ──────────────────────"

python3 - <<'PY'
import json, sys
try:
    data = json.load(open("feature_list.json"))
    valid = {"pending", "in_progress", "done", "blocked"}
    in_progress = [f for f in data["features"] if f["status"] == "in_progress"]
    if len(in_progress) > 1:
        print(f"[FAIL]  Hay {len(in_progress)} features en in_progress (máximo 1)")
        sys.exit(1)
    for f in data["features"]:
        if f["status"] not in valid:
            print(f"[FAIL]  Estado inválido en feature {f['id']}: {f['status']}")
            sys.exit(1)
    print(f"[OK]    feature_list.json válido ({len(data['features'])} features)")
except Exception as e:
    print(f"[FAIL]  feature_list.json inválido: {e}")
    sys.exit(1)
PY

if [ $? -ne 0 ]; then EXIT_CODE=1; fi

echo ""
echo "── 4. Lint (ruff) ──────────────────────────────────────"

if [ -f "pyproject.toml" ] || [ -f "ruff.toml" ]; then
  if uv run ruff check . 2>&1; then
    ok "ruff check pasa"
  else
    fail "ruff check encuentra errores"
    EXIT_CODE=1
  fi

  if uv run ruff format --check . 2>&1; then
    ok "ruff format pasa"
  else
    fail "ruff format encuentra issues"
    EXIT_CODE=1
  fi
else
  warn "pyproject.toml no existe todavía — saltando lint"
fi

echo ""
echo "── 5. Tests (pytest) ───────────────────────────────────"

if [ -d "tests" ] && [ -f "pyproject.toml" ]; then
  if uv run pytest --tb=short -q 2>&1; then
    ok "Todos los tests pasan"
  else
    fail "Hay tests rotos"
    EXIT_CODE=1
  fi
else
  warn "tests/ o pyproject.toml no existen todavía — saltando tests"
fi

echo ""
echo "── 6. Resumen ──────────────────────────────────────────"

if [ $EXIT_CODE -eq 0 ]; then
  ok "Entorno listo. Puedes empezar a trabajar."
else
  fail "Entorno NO está listo. Resuelve los errores antes de avanzar."
fi

exit $EXIT_CODE
