"""The formats register (docs/PREP_PLAN.md R5): which version of each on-disk format this MISTER PLIS writes, and which
versions it can read.

A version that writes a new format says so here (and ``tests/test_formats_register.py`` fails until it does, since each
number must equal the constant where the format is written). The release feed carries ``WRITES``, so going back to an
older version that can't read what a newer one wrote is refused instead of breaking the lab's data. Every format is
described in docs/FORMATS.md.
"""

from __future__ import annotations

# what this version writes
WRITES = {
    "job": 1,               # <storage>/jobs/<id>/job.json (jobformat.VERSION)
    "job_index": 1,         # <storage>/jobs/index.json (jobstore.INDEX_VERSION; a rebuildable cache)
    "backup": 1,            # a job's backup folder (backup.VERSION)
    "backup_catalogue": 1,  # <backup>/index.json (backup.CATALOGUE_VERSION)
    "lab_file": 1,          # labs/*.toml (labsetup.FORMAT)
    "lab_state": 1,         # <data>/lab.json (labsetup.FORMAT)
    "transfer": 1,          # a moved server's folder, and a settings snapshot (transfer.VERSION)
    "tool_settings": 1,     # <data>/tool-settings/<tool>.json (toolsettings.FORMAT)
    "release_feed": 1,      # feed-<channel>.json (updates.FEED_VERSION)
    "accounts": 1,          # <data>/accounts.json, <instance>/secrets/sessions.json (accounts.FORMAT)
}

# what this version can read: (oldest, newest)
READS = {
    "job": (0, 1),             # v0: meta.json
    "job_index": (1, 1),
    "backup": (0, 1),          # v0: a backup made before backup.json
    "backup_catalogue": (1, 1),
    "lab_file": (1, 1),
    "lab_state": (1, 1),
    "transfer": (1, 1),
    "tool_settings": (1, 1),
    "release_feed": (1, 1),
    "accounts": (1, 1),
}


def can_read(writes: dict) -> tuple[bool, list[str]]:
    """Whether this version reads everything another version wrote (``writes`` from the feed); the formats it can't."""
    too_new = [name for name, v in (writes or {}).items() if name in READS and isinstance(v, int) and v > READS[name][1]]
    return not too_new, too_new
