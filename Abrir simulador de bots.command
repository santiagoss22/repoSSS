#!/bin/zsh
cd "$(dirname "$0")"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Preparando las aplicaciones por primera vez..."
  CODEX_PYTHON="/Users/triples/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
  if [[ -x "$CODEX_PYTHON" ]]; then
    "$CODEX_PYTHON" -m venv .venv
  elif command -v python3 >/dev/null 2>&1; then
    python3 -m venv .venv
  else
    echo "No se encontró una instalación de Python compatible."
    read -k 1
    exit 1
  fi
  .venv/bin/python -m pip install -r requirements.txt
fi

exec .venv/bin/python launcher.py
