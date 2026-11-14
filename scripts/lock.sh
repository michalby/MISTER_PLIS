#!/usr/bin/env bash
# Pin every package MISTER PLIS needs — requirements.txt and what those need in turn — to one exact version with its
# checksums, in requirements.lock (docs/SECURITY_AUDIT.md M5). The Docker image and a release install exactly these
# (pip --require-hashes), so a new or hijacked version on PyPI never reaches a lab by itself.
#   ./scripts/lock.sh            after changing requirements.txt, or to take newer versions on purpose
# Then run the tests, look at what changed (git diff requirements.lock) and commit both files. Needs uv in the
# development environment (.venv/bin/pip install uv); the servers don't.
set -euo pipefail
cd "$(dirname "$0")/.."
UV=.venv/bin/uv
[ -x "$UV" ] || UV=uv
# one file for every system and Python from 3.11 (requires-python in pyproject.toml): Linux, macOS, Windows
"$UV" pip compile requirements.txt --universal --python-version 3.11 --generate-hashes --no-header --quiet \
  --output-file requirements.lock
sed -i.bak '1i # Pinned with checksums by scripts/lock.sh from requirements.txt — do not edit by hand.' requirements.lock && rm -f requirements.lock.bak
echo "requirements.lock: $(grep -c '^[a-z]' requirements.lock) packages pinned"
