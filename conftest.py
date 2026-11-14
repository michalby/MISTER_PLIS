import os
import sys
import tempfile
from pathlib import Path

# Keep test runs away from the real data folder.
os.environ.setdefault("MISTER_PLIS_DATA_DIR", tempfile.mkdtemp(prefix="mister_plis_test_"))
# set up already (as if "Skip for now" was pressed), so the pages don't lead to the setup page; tests of it start over
_lab = Path(os.environ["MISTER_PLIS_DATA_DIR"]) / "lab.json"
if not _lab.exists():
    _lab.write_text('{"format": 1, "state": "skipped"}', encoding="utf-8")
ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MISTER_PLIS_MODULE_INVENTORY_REPO", "")  # no GitHub during tests
os.environ.setdefault("MISTER_PLIS_MODULE_NOTEBOOK_REPO", "")
os.environ.setdefault("MISTER_PLIS_SERVER_NAMES", "testserver")  # the name FastAPI's TestClient uses (access.known_host)
os.environ.setdefault("MISTER_PLIS_FETCH_TOOL_SOURCES", "0")  # nor tool sources:
os.environ.setdefault("MISTER_PLIS_TOOL_FOLDERS", str(ROOT / "tests" / "fixtures" / "toolsource"))  # the test tools
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))  # shared helpers (test_backup._run…) for every test folder

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from mister_plis.app import app

    with TestClient(app) as c:
        c.cookies.set("lang", "en")
        yield c


@pytest.fixture
def table_csv(tmp_path):
    rng = np.random.default_rng(1)
    x = np.linspace(0.1, 10, 30)
    df = pd.DataFrame({
        "dose": x,
        "response": 2.5 * x + 1 + rng.normal(0, 0.3, x.size),
        "decay": 5 * np.exp(-0.4 * x) + 0.5 + rng.normal(0, 0.02, x.size),
        "group": np.repeat(["ctrl", "drugA", "drugB"], 10),
    })
    p = tmp_path / "data.csv"
    df.to_csv(p, index=False)
    return p


@pytest.fixture
def accounts_on(client):
    """The lab has accounts (sign-in is on): an admin and a member, each with a password. Returns sign_in(name) → a
    TestClient signed in as them (the session's client stays signed out). Everything is gone afterwards."""
    from fastapi.testclient import TestClient

    from mister_plis import app as app_module

    store = app_module.lab_accounts
    people = app_module.merged_people  # renames and attached names merge names: put back afterwards
    merges, log = dict(people._merged), list(people.log)
    store.create("Ada Admin", "admin", "admin-password", "test")
    store.create("Mo Member", "member", "member-password", "test")
    made = []

    def sign_in(name: str, password: str | None = None) -> TestClient:
        c = TestClient(app_module.app)
        c.cookies.set("lang", "en")
        pw = password or {"Ada Admin": "admin-password", "Mo Member": "member-password"}[name]
        r = c.post("/api/login", json={"name": name, "password": pw})
        assert r.status_code == 200, r.text
        made.append(c)
        return c

    yield sign_in
    for c in made:
        c.close()
    for f in (store.file, store.sessions_file):
        f.unlink(missing_ok=True)
    store._cache, store._sessions = None, None
    app_module.sign_in_throttle.failures.clear()
    people._merged, people.log = merges, log
    people._save()
