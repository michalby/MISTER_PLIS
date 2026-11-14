"""The lab's accounts and sign-in (mister_plis/accounts.py, access.py; docs/SECURITY_AUDIT.md §7)."""

from __future__ import annotations

import re

import pytest
from fastapi.routing import APIRoute

from mister_plis import access


def _filled(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


# ---- with no account, the server is open as it always was -------------------------------------------------------------

def test_without_accounts_the_server_is_open(client):
    assert access.mode() == "open"
    assert client.get("/api/account").json() == {"mode": "open", "name": "", "role": "admin", "signed_in": False}
    assert client.get("/").status_code == 200 and client.get("/api/jobs").status_code == 200


# ---- once there are accounts, nothing without signing in ---------------------------------------------------------------

def test_signed_out_every_route_but_the_public_ones_is_refused(client, accounts_on):
    """Deny by default: every route the base and its modules have answers 401 (a page: leads to /login), except the
    few access.PUBLIC lists."""
    from mister_plis.app import app

    assert access.mode() == "accounts"
    checked = 0
    for r in app.routes:
        if not isinstance(r, APIRoute) or access.is_public(r.path):
            continue
        for method in r.methods - {"HEAD", "OPTIONS"}:
            res = client.request(method, _filled(r.path), follow_redirects=False)
            if method == "GET" and not r.path.startswith("/api/"):
                assert res.status_code == 303 and res.headers["location"].startswith("/login?next="), (method, r.path)
            else:
                assert res.status_code == 401 and res.json().get("sign_in"), (method, r.path, res.status_code)
            checked += 1
    assert checked > 150
    for url in ("/api/version", "/static/js/app.js", "/login", "/i18n/pl.js"):
        assert client.get(url).status_code == 200, url


def test_the_sign_in_page_leads_back_only_to_this_server(client, accounts_on):
    r = client.get("/settings?tab=server", follow_redirects=False)
    assert r.headers["location"] == "/login?next=/settings%3Ftab%3Dserver"
    page = client.get("/login?next=//evil.example/x").text
    assert "evil.example" not in page and "Sign in" in page
    admin = accounts_on("Ada Admin")
    assert admin.get("/login?next=//evil.example", follow_redirects=False).headers["location"] == "/"
    assert admin.get("/login?next=/jobs", follow_redirects=False).headers["location"] == "/jobs"


def test_a_wrong_password_and_too_many_tries(client, accounts_on, monkeypatch):
    from mister_plis import app as app_module

    monkeypatch.setattr(app_module.sign_in_throttle, "LIMIT", 3)
    monkeypatch.setattr(app_module.sign_in_throttle, "failed", lambda *k, real=app_module.sign_in_throttle.failed: real(*k) * 0)
    for name in ("Ada Admin", "Nobody", "Ada Admin"):
        r = client.post("/api/login", json={"name": name, "password": "guess-guess"})
        assert r.status_code == 401 and r.json()["error"] == "Wrong name or password."  # the same for a name that doesn't exist
    assert client.post("/api/login", json={"name": "Ada Admin", "password": "admin-password"}).status_code == 429
    assert "sign-in failed" in str(app_module.lab_accounts.activity())


# ---- who may do what ---------------------------------------------------------------------------------------------------

def test_a_member_sees_no_server_internals(accounts_on):
    member, admin = accounts_on("Mo Member"), accounts_on("Ada Admin")
    for url in ("/api/system", "/api/system/credentials", "/api/setup/export", "/api/system/snapshots",
                "/api/accounts", "/api/activity"):
        assert member.get(url).status_code == 403, url
        assert admin.get(url).status_code == 200, url
    assert 'id="tab-server"' not in member.get("/settings").text and 'id="tab-server"' in admin.get("/settings").text


def test_the_signed_in_account_is_who_runs_a_job_whatever_the_name_cookie_says(accounts_on):
    member = accounts_on("Mo Member")
    member.cookies.set("name", "Someone Else")
    job = member.post("/api/tools/toy-calc/run", json={"params": {}, "wait": 10}).json()
    assert job["user"] == "Mo Member"
    assert member.get("/api/account").json() == {"mode": "accounts", "name": "Mo Member", "role": "member", "signed_in": True}
    assert member.post("/api/feedback", json={"kind": "bug", "text": "x"}).json()["user"] == "Mo Member"


def test_a_traceback_is_for_admins_only(accounts_on):
    from mister_plis.app import jobs

    member, admin = accounts_on("Mo Member"), accounts_on("Ada Admin")
    job_id = member.post("/api/tools/toy-calc/run", json={"params": {}, "wait": 10}).json()["id"]
    jobs.get(job_id).traceback = "Traceback: /secret/path/tool.py line 3"
    assert member.get(f"/api/jobs/{job_id}").json()["traceback"] == ""
    assert "secret/path" in admin.get(f"/api/jobs/{job_id}").json()["traceback"]


# ---- accounts: made, reset, removed --------------------------------------------------------------------------------------

def test_an_admin_adds_an_account_whose_person_chooses_their_own_password(accounts_on):
    admin = accounts_on("Ada Admin")
    r = admin.post("/api/accounts", json={"name": "Nina New", "role": "member"})
    assert r.status_code == 200 and re.fullmatch(r"[a-z2-9]{4}-[a-z2-9]{4}-[a-z2-9]{4}", r.json()["password"])
    assert "password" not in str(admin.get("/api/accounts").json()["accounts"][0].keys() - {"must_change"})
    nina = accounts_on("Nina New", r.json()["password"])
    assert nina.get("/api/jobs").json()["error"] == "Choose your own password first."
    assert nina.get("/", follow_redirects=False).headers["location"] == "/login?change=1"
    assert nina.post("/api/account/password", json={"new": "short"}).status_code == 422
    assert nina.post("/api/account/password", json={"new": "ninas-own-password"}).status_code == 200
    assert nina.get("/api/jobs").status_code == 200
    # her own change now needs her current password
    assert nina.post("/api/account/password", json={"old": "wrong", "new": "another-password"}).status_code == 422
    assert admin.post("/api/accounts", json={"name": "nina new"}).status_code == 422  # names are one per person


def test_a_reset_or_a_removal_ends_the_persons_sessions(accounts_on):
    admin, member = accounts_on("Ada Admin"), accounts_on("Mo Member")
    assert member.get("/api/jobs").status_code == 200
    temp = admin.post("/api/accounts/reset", json={"name": "Mo Member"}).json()["password"]
    assert member.get("/api/jobs").status_code == 401
    again = accounts_on("Mo Member", temp)
    admin.request("DELETE", "/api/accounts", json={"name": "Mo Member"})
    assert again.get("/api/jobs").status_code == 401
    assert again.post("/api/login", json={"name": "Mo Member", "password": temp}).status_code == 401


def test_the_lab_keeps_an_admin(accounts_on):
    admin = accounts_on("Ada Admin")
    assert "at least one admin" in admin.post("/api/accounts/role", json={"name": "Ada Admin", "role": "member"}).json()["error"]
    assert "at least one admin" in admin.request("DELETE", "/api/accounts", json={"name": "Ada Admin"}).json()["error"]
    admin.post("/api/accounts/role", json={"name": "Mo Member", "role": "admin"})
    assert admin.post("/api/accounts/role", json={"name": "Ada Admin", "role": "member"}).status_code == 200


def test_signing_out(accounts_on):
    admin = accounts_on("Ada Admin")
    other = accounts_on("Ada Admin")
    admin.post("/api/logout", json={})
    assert admin.get("/api/jobs").status_code == 401 and other.get("/api/jobs").status_code == 200
    other.post("/api/logout", json={"everywhere": True})
    assert other.get("/api/jobs").status_code == 401


def test_the_session_cookie_is_safe(accounts_on, client):
    r = client.post("/api/login", json={"name": "Ada Admin", "password": "admin-password"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    from mister_plis.app import lab_accounts

    token = r.cookies.get("mp_session")
    assert token and token not in lab_accounts.sessions_file.read_text(encoding="utf-8")  # only its hash is kept
    assert "admin-password" not in lab_accounts.file.read_text(encoding="utf-8")
    assert lab_accounts.file.stat().st_mode & 0o077 == 0
    client.cookies.delete("mp_session")


def test_changes_to_the_settings_are_in_the_activity_log(accounts_on):
    admin = accounts_on("Ada Admin")
    admin.post("/api/lab/name", json={"lab_name": "Smith Lab"})
    admin.post("/api/lab/name", json={"lab_name": ""})
    log = admin.get("/api/activity").json()["entries"]
    assert any(e["who"] == "Ada Admin" and e["what"] == "POST /api/lab/name" for e in log)
    assert any(e["what"] == "signed in" for e in log)


# ---- the first account -------------------------------------------------------------------------------------------------

@pytest.fixture
def no_accounts_yet(tmp_path, monkeypatch):
    from mister_plis import app as app_module, setupcode

    monkeypatch.setattr(setupcode, "path", lambda: tmp_path / "setup-code")
    code = setupcode.ensure()
    yield code
    store = app_module.lab_accounts
    for f in (store.file, store.sessions_file):
        f.unlink(missing_ok=True)
    store._cache, store._sessions = None, None


def test_the_first_account_needs_the_setup_code_from_another_computer(client, no_accounts_yet):
    from mister_plis import setupcode

    body = {"name": "Ada Admin", "password": "admin-password", "repeat": "admin-password"}
    assert client.get("/api/accounts").json()["first_needs_code"] is True  # the test client isn't on this computer
    assert client.post("/api/accounts/first", json=body).status_code == 403
    r = client.post("/api/accounts/first", json={**body, "code": no_accounts_yet})
    assert r.status_code == 200 and access.mode() == "accounts"
    assert not setupcode.current()  # used up
    assert client.get("/api/account").json()["name"] == "Ada Admin"  # and signed in
    assert client.post("/api/accounts/first", json={**body, "code": no_accounts_yet}).status_code in (403, 409)
    client.cookies.delete("mp_session")


def test_the_settings_page_offers_the_first_account(client, no_accounts_yet):
    page = client.get("/settings").text
    assert 'id="first-account"' in page and "setup code" in page


# ---- the command line, and what doesn't travel ------------------------------------------------------------------------

def test_the_command_line_resets_a_forgotten_password(accounts_on, capsys):
    from mister_plis.__main__ import account_command

    assert account_command(["reset", "Ada Admin"]) == 0
    temp = re.search(r"[a-z2-9]{4}-[a-z2-9]{4}-[a-z2-9]{4}", capsys.readouterr().out).group(0)
    accounts_on("Ada Admin", temp)  # signs in with it (and must choose a new one)


def test_a_snapshot_never_brings_back_an_account(accounts_on):
    from mister_plis import transfer
    from mister_plis.config import settings

    plan = [arc for arc, _ in transfer._settings_plan(settings.data_path, settings.storage_path, [])]
    assert plan and "data/accounts.json" not in plan and not any(a.startswith("data/audit.log") for a in plan)
    assert "data/accounts.json" in [arc for arc, _ in transfer._plan(settings.data_path, settings.storage_path, [])]


def _kept_job(c) -> str:
    """A job kept in the history (the toy table tool), run by the client ``c``: its id."""
    up = c.post("/api/uploads", files={"file": ("run.csv", b"sample,value\nwt,0.25\n", "text/csv")}).json()
    rows = c.post("/api/tools/toy-table/suggest/samples", json={"files": [up["id"]]}).json()["result"]
    job = c.post("/api/tools/toy-table/run", json={"params": {"files": [up["id"]], "samples": rows}, "wait": 20}).json()
    assert job["status"] == "done", job
    return job["id"]


# ---- an account owns its jobs and its names (0.15.0) --------------------------------------------------------------------

def test_a_job_stores_the_account_that_ran_it(accounts_on):
    from mister_plis.app import jobs, lab_accounts

    member = accounts_on("Mo Member")
    acct = lab_accounts.get("Mo Member")
    assert re.fullmatch(r"[0-9a-f]{16}", acct["id"])
    job_id = _kept_job(member)
    job = jobs.get(job_id)
    assert job.account == acct["id"] and job.to_dict(translated=False)["account"] == acct["id"]
    from mister_plis.jobformat import read_job

    assert read_job(job.workdir)["account"] == acct["id"]  # on disk, in job.json
    assert member.post("/api/feedback", json={"kind": "bug", "text": "x"}).json()["account"] == acct["id"]


def test_renaming_an_account_moves_its_jobs_and_keeps_its_sessions(accounts_on):
    from mister_plis.app import jobs, lab_accounts

    admin, member = accounts_on("Ada Admin"), accounts_on("Mo Member")
    job_id = _kept_job(member)
    r = admin.post("/api/accounts/rename", json={"name": "Mo Member", "new": "Morgan Member"})
    assert r.status_code == 200, r.text
    assert jobs.get(job_id).user == "Morgan Member"
    acct = lab_accounts.get("Morgan Member")
    assert acct and acct["names"] == ["Mo Member"] and lab_accounts.get("Mo Member") is None
    assert member.get("/api/account").json()["name"] == "Morgan Member"  # still signed in, under the new name
    assert member.post("/api/login", json={"name": "Morgan Member", "password": "member-password"}).status_code == 200
    # and back to a name it had: everything follows again (the old name is in use again, not "merged")
    assert admin.post("/api/accounts/rename", json={"name": "Morgan Member", "new": "Mo Member"}).status_code == 200
    assert jobs.get(job_id).user == "Mo Member" and lab_accounts.get("Mo Member")["names"] == ["Morgan Member"]


def test_an_earlier_name_is_attached_to_an_account_and_its_jobs_become_theirs(client, request):
    from types import SimpleNamespace

    from mister_plis.app import jobs

    client.cookies.set("name", "Ola")  # before sign-in was on: a job under a name typed in the top bar
    job = SimpleNamespace(id=_kept_job(client))
    client.cookies.delete("name")
    accounts_on = request.getfixturevalue("accounts_on")  # then the lab makes its accounts
    admin = accounts_on("Ada Admin")
    assert admin.post("/api/accounts/attach", json={"name": "Mo Member", "earlier": "Nobody At All"}).status_code == 422
    r = admin.post("/api/accounts/attach", json={"name": "Mo Member", "earlier": "Ola"})
    assert r.status_code == 200 and r.json()["moved"]["jobs"] >= 1
    assert jobs.get(job.id).user == "Mo Member"
    member = accounts_on("Mo Member")
    preview = member.get("/api/history/clear?scope=mine").json()
    assert preview["count"] >= 1  # the attached job counts as theirs
    # an account's name can't be merged away on the People list; a name merged into an account's is attached
    assert "rename the account" in admin.post("/api/people/merge", json={"from": "Mo Member", "into": "Ada Admin"}).json()["error"]


def test_a_new_account_cant_take_a_name_merged_into_someone_else(accounts_on):
    from mister_plis.app import merged_people

    admin = accounts_on("Ada Admin")
    merged_people.merge("Adka", "Ada Admin", by="test")
    r = admin.post("/api/accounts", json={"name": "Adka"})
    assert r.status_code == 422 and "Ada Admin" in r.json()["error"]


def test_mine_is_the_accounts_not_a_namesake(accounts_on):
    """A removed account's jobs don't become someone else's who later gets the same name."""
    from mister_plis.app import jobs, lab_accounts

    admin, member = accounts_on("Ada Admin"), accounts_on("Mo Member")
    job_id = _kept_job(member)
    admin.request("DELETE", "/api/accounts", json={"name": "Mo Member"})
    temp = admin.post("/api/accounts", json={"name": "Mo Member"}).json()["password"]
    newcomer = accounts_on("Mo Member", temp)
    newcomer.post("/api/account/password", json={"new": "member-password"})
    ids = [j["id"] for j in newcomer.get("/api/history/clear?scope=mine").json()["unbacked"]]
    assert job_id not in ids and jobs.get(job_id).user == "Mo Member"
