#!/usr/bin/env bash
# Build a release of the version in mister_plis/__init__.py, by hand (there is no CI — docs/PREP_PLAN.md R5).
#   ./scripts/release.sh [beta|stable]
# It checks, tests and builds; it publishes nothing. What to publish, and where, is printed at the end (the owner
# decides: docs/FINAL_VERSION.md F1, F2).
set -euo pipefail
cd "$(dirname "$0")/.."
CHANNEL="${1:-beta}"
VERSION=$(.venv/bin/python -c "import mister_plis; print(mister_plis.__version__)")
COMMIT=$(git rev-parse HEAD)

[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "Commit or undo the changes first."; exit 1; }
grep -q "^## $VERSION" CHANGELOG.md || { echo "CHANGELOG.md has no section for $VERSION."; exit 1; }
! git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null || { echo "v$VERSION is tagged already: raise the version."; exit 1; }

echo "== the tool sources it brings with it (bundled-tools.toml)"
.venv/bin/python - <<'PY'
import shutil, sys, tempfile
from pathlib import Path
from mister_plis.toolsources import ToolSources, bundled_list
root = Path("bundled-tools")
for d in root.iterdir():
    if d.is_dir():
        shutil.rmtree(d)  # what an earlier build put here (fetched again below)
ts = ToolSources(Path(tempfile.mkdtemp()), bundled_root=root)
listed = bundled_list()
ts.ensure_bundled(listed)  # as a server running from a git checkout fetches them: by commit when listed, else by tag
if ts.errors:
    sys.exit("\n".join(f"  {k}: {v}" for k, v in ts.errors.items()))
for s in listed:
    print(f"  {s['name']} {s['tag']} {s['commit'][:12]}")
print(f"  {len(listed)} bundled")
PY
echo "== tests"
.venv/bin/python -m pytest -q
echo "== the wheel"
rm -rf dist/release && mkdir -p dist/release
.venv/bin/python -m pip wheel --no-deps --quiet -w dist/release .
WHEEL=$(ls dist/release/mister_plis-"$VERSION"-*.whl)
echo "== the Docker image"
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  docker build --build-arg COMMIT="$COMMIT" --build-arg COMMIT_DATE="$(git log -1 --format=%cI)" \
    -t "mister-plis:$VERSION" -t "mister-plis:$CHANNEL" .
  IMAGE="mister-plis:$VERSION"
else
  echo "(Docker isn't running here: no image built.)"; IMAGE=""
fi
echo "== the packages it installs (requirements.lock, made by scripts/lock.sh)"
grep -q -- "--hash=sha256:" requirements.lock || { echo "requirements.lock has no checksums: run ./scripts/lock.sh"; exit 1; }
cp requirements.lock dist/release/
echo "== the feed"
.venv/bin/python scripts/make_feed.py "$CHANNEL" "dist/release/feed-$CHANNEL.json" --wheel "$WHEEL" ${IMAGE:+--image "$IMAGE"} \
  --lock dist/release/requirements.lock
echo "== its signature (docs/RELEASES.md)"
if [ -n "${MISTER_PLIS_SIGNING_KEY:-}" ]; then
  rm -f "dist/release/feed-$CHANNEL.json.sig"
  ssh-keygen -Y sign -f "$MISTER_PLIS_SIGNING_KEY" -n mister-plis-release "dist/release/feed-$CHANNEL.json"
  SIGNED="feed-$CHANNEL.json.sig"
else
  echo "(MISTER_PLIS_SIGNING_KEY isn't set: the feed is not signed — servers with a release key in their code refuse it.)"
  SIGNED=""
fi

cat <<DONE

Built $VERSION ($COMMIT) for the $CHANNEL channel in dist/release/.
To publish it (not done by this script):
  git tag -a v$VERSION -m "channel: $CHANNEL" && git push origin v$VERSION
  a GitHub release for v$VERSION with: $(basename "$WHEEL"), requirements.lock, feed-$CHANNEL.json ${SIGNED:+and $SIGNED,} and its CHANGELOG.md section
  ${IMAGE:+docker tag $IMAGE ghcr.io/<owner>/mister-plis:$VERSION && docker push ghcr.io/<owner>/mister-plis:$VERSION}
Before the next feed, start from the published feed-$CHANNEL.json so earlier releases stay listed.
DONE
