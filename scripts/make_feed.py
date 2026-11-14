"""Add this version to a release feed (docs/FORMATS.md "Release feed"; scripts/release.sh runs it):

    .venv/bin/python scripts/make_feed.py <channel> <feed.json> [--wheel dist/x.whl] [--image ghcr.io/…:0.9.0]

The feed file is read if it is there (earlier releases are kept) and written again with this version: its date, its
lines from CHANGELOG.md, the formats it writes and reads (mister_plis/formats.py) and its artifacts with checksums.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mister_plis import __version__  # noqa: E402
from mister_plis.formats import READS, WRITES  # noqa: E402
from mister_plis.updates import FEED_FORMAT, make_feed  # noqa: E402


def notes(version: str) -> str:
    """This version's section of CHANGELOG.md, as plain lines."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(version)}\b.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("channel", choices=["beta", "stable"])
    ap.add_argument("feed")
    ap.add_argument("--wheel", default="")
    ap.add_argument("--image", default="", help="the image by its digest, e.g. ghcr.io/x/mister-plis@sha256:… (a tag can move)")
    ap.add_argument("--lock", default="", help="requirements.lock: the exact packages the release installs")
    ap.add_argument("--url-base", default="", help="where the wheel will be downloaded from (the release's address)")
    a = ap.parse_args()
    path = Path(a.feed)
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    releases = [r for r in (old.get("releases") or []) if old.get("format") == FEED_FORMAT and r.get("version") != __version__]
    artifacts = {}
    if a.wheel:
        w = Path(a.wheel)
        artifacts["wheel"] = {"url": f"{a.url_base.rstrip('/')}/{w.name}" if a.url_base else w.name,
                              "sha256": hashlib.sha256(w.read_bytes()).hexdigest()}
    if a.image:
        artifacts["docker"] = a.image
    if a.lock:
        lock = Path(a.lock)
        artifacts["lock"] = {"url": f"{a.url_base.rstrip('/')}/{lock.name}" if a.url_base else lock.name,
                             "sha256": hashlib.sha256(lock.read_bytes()).hexdigest()}
    releases.append({"version": __version__, "date": time.strftime("%Y-%m-%d"), "notes": notes(__version__), "notes_pl": "",
                     "writes": WRITES, "min_reads": {k: lo for k, (lo, _) in READS.items()}, "artifacts": artifacts})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(make_feed(a.channel, releases), indent=1, ensure_ascii=False), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
