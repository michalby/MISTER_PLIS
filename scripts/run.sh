#!/usr/bin/env bash
# Run the server for the lab (listens on the network, port from config.toml, default 8000).
cd "$(dirname "$0")/.." && exec .venv/bin/python -m mister_plis "$@"
