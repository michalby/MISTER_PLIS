#!/usr/bin/env bash
# Create the project's own virtual environment (.venv) and install dependencies.
#   ./scripts/setup.sh         runtime only (lab server)
#   ./scripts/setup.sh --dev   plus test tools (your laptop)
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv .venv --python 3.12 --seed
  else
    PY=""
    for c in python3.13 python3.12 python3.11 python3; do
      if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then PY="$c"; break; fi
    done
    if [ -z "$PY" ]; then
      echo "MISTER PLIS needs Python 3.11 or newer. The easiest way to get it:"
      echo "  curl -LsSf https://astral.sh/uv/install.sh | sh    # then re-run this script"
      exit 1
    fi
    "$PY" -m venv .venv
  fi
fi

.venv/bin/python -m pip install --quiet --upgrade pip
if [ "${1:-}" = "--dev" ]; then
  .venv/bin/python -m pip install -r requirements-dev.txt
else
  # a server: exactly the pinned versions, checked against their checksums (scripts/lock.sh)
  .venv/bin/python -m pip install --require-hashes -r requirements.lock
fi
echo
echo "Ready. Start with ./scripts/run.sh (server) or ./scripts/dev.sh (auto-reload while editing)."
