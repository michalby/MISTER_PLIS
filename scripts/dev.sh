#!/usr/bin/env bash
# Local development: only reachable from this computer, restarts when you save a file.
cd "$(dirname "$0")/.." && exec .venv/bin/python -m mister_plis --host 127.0.0.1 --reload "$@"
