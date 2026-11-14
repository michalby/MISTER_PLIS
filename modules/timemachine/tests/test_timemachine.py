"""Time Machine: keeping a job for good — from its result page, or by typing its job number."""

import pytest

from test_backup import _downloads, _run


@pytest.fixture
def backup_dir(tmp_path):
    from mister_plis.app import backups

    folder = tmp_path / "backup"
    folder.mkdir()
    backups.update(str(folder), 1)
    yield folder
    backups.update("", 1)


def test_add_a_job_and_it_outlives_the_original(client, tmp_path):
    from mister_plis.app import jobs, modules
    timemachine = modules.get("timemachine")

    job_d = _run(client, tmp_path, keyword="PSI study", name="Anna Kowalska")
    jid = job_d["id"]
    assert client.get(f"/api/jobs/{jid}").json()["in_tm"] is False
    r = client.post(f"/api/jobs/{jid}/timemachine")
    assert r.status_code == 200 and not r.json()["already"]
    assert client.post(f"/api/jobs/{jid}/timemachine").json()["already"]
    assert client.get(f"/api/jobs/{jid}").json()["in_tm"] is True
    listed = next(j for j in client.get("/api/jobs").json()["jobs"] if j["id"] == jid)
    assert listed["in_tm"] and any(n.endswith(".xlsx") for n in listed["result_files"])

    # the original goes away (cleanup); the copy stays, with its files and links pointing at it
    jobs.delete([jobs.get(jid)])
    assert jobs.get(jid) is None and timemachine.has(jid)
    d = client.get(f"/api/tm/{jid}").json()
    assert d["user"] == "Anna Kowalska" and d["keyword"] == "PSI study" and d["entry"]["source"] == "jobs"
    assert d["input_files"] and "run1.csv" in d["input_files"][0]["names"]
    assert not d["in_jobs"] and d["files_kept"]
    assert "/api/jobs/" not in str(d["outputs"]) and d["report"] == f"/api/tm/{jid}/report.pdf"
    t = next(o for o in d["outputs"] if o["kind"] == "table")
    assert client.get(t["download"]["url"] + "?download=1").status_code == 200
    pdf = client.get(d["report"])
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    entries = client.get("/api/tm").json()["entries"]
    assert any(e["id"] == jid for e in entries)

    # a note, then removal
    assert client.post(f"/api/tm/{jid}", json={"note": "Figure 3"}).json()["note"] == "Figure 3"
    timemachine.load()  # survives a restart
    assert timemachine.entry(jid)["note"] == "Figure 3"
    assert client.delete(f"/api/tm/{jid}").status_code == 200
    assert client.get(f"/api/tm/{jid}").status_code == 404


def test_projects_moves_and_history(client, tmp_path):
    from mister_plis.app import modules
    timemachine = modules.get("timemachine")

    a = _run(client, tmp_path, keyword="a")["id"]
    b = _run(client, tmp_path, keyword="b")["id"]
    client.cookies.set("name", "Anna")
    try:
        psi = client.post("/api/tm/projects", json={"name": "PSI paper"}).json()
        thesis = client.post("/api/tm/projects", json={"name": "Thesis"}).json()
        assert client.post("/api/tm/projects", json={"name": "psi paper"}).status_code == 422  # same name
        coloured = client.post("/api/tm/projects", json={"name": "Coloured", "color": "#12AB34"}).json()
        assert coloured["color"] == "#12ab34"  # a colour chosen when the project is made
        assert client.post("/api/tm/projects", json={"name": "Bad colour", "color": "red"}).status_code == 422
        client.delete(f"/api/tm/projects/{coloured['id']}")
        client.post(f"/api/jobs/{a}/timemachine")
        r = client.post("/api/tm/retrieve", json={"id": b, "projects": [psi["id"]]})
        assert r.json()["entry"]["projects"] == [psi["id"]]

        # one result in two projects, then both moved out of one into the other in a single change
        assert client.post("/api/tm/assign", json={"ids": [a, b], "add": [psi["id"]]}).json()["changed"] == 1
        assert client.post(f"/api/tm/{a}", json={"projects": [psi["id"], thesis["id"]]}).status_code == 200
        assert timemachine.entry(a)["projects"] == [psi["id"], thesis["id"]]
        moved = client.post("/api/tm/assign", json={"ids": [a, b], "add": [thesis["id"]], "remove": [psi["id"]]}).json()
        assert moved["changed"] == 2 and {p["id"]: p["count"] for p in moved["projects"]} == {psi["id"]: 0, thesis["id"]: 2}

        log = client.get("/api/tm/history").json()
        assert log["available"]
        top = log["commits"][0]
        assert top["subject"].startswith("Move 2 results from “PSI paper” to “Thesis”") and top["author"] == "Anna"
        assert set(top["jobs"]) == {a, b} and top["action"] == "projects"
        mine = client.get(f"/api/tm/history?job={a}").json()["commits"]
        assert [c["action"] for c in mine][-1] == "add" and all(a in c["jobs"] for c in mine)
        assert any(c["subject"].startswith("New project “PSI paper”") for c in client.get(f"/api/tm/history?project={psi['id']}").json()["commits"])
        assert client.get(f"/api/tm/history/{top['short']}").json()["files"]

        # rename and delete a project: the results stay
        client.post(f"/api/tm/projects/{thesis['id']}", json={"name": "Thesis ch. 2"})
        assert timemachine.project_name(thesis["id"]) == "Thesis ch. 2"
        client.delete(f"/api/tm/projects/{thesis['id']}")
        assert timemachine.has(a) and timemachine.entry(a)["projects"] == []

        # a removed result comes back from the history
        client.delete(f"/api/tm/{a}")
        gone = next(c for c in client.get("/api/tm/history").json()["commits"] if c["action"] == "remove" and a in c["jobs"])
        assert gone["restorable"]
        back = client.post("/api/tm/restore", json={"commit": gone["id"]})
        assert back.status_code == 200 and timemachine.has(a) and client.get(f"/api/tm/{a}").json()["files_kept"]
        assert client.post("/api/tm/restore", json={"commit": gone["id"]}).status_code == 422
    finally:
        client.cookies.delete("name")
        for j in (a, b):
            if timemachine.has(j):
                client.delete(f"/api/tm/{j}")
        for p in timemachine.projects():
            client.delete(f"/api/tm/projects/{p['id']}")


def test_studies_become_projects(tmp_path):
    import json

    from mister_plis.jobs import JobManager, UploadStore
    from modules.timemachine.service import TimeMachine

    d = tmp_path / "timemachine" / "20261019-142301-a1b2c3"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"id": d.name, "tool_id": "x", "tool_name": "X", "status": "done", "created": 1}), encoding="utf-8")
    (d / "entry.json").write_text(json.dumps({"id": d.name, "added": 1, "study": "Old study"}), encoding="utf-8")
    tm = TimeMachine(tmp_path, JobManager(tmp_path, UploadStore(tmp_path / "up")))
    [p] = tm.projects()
    assert p["name"] == "Old study" and tm.entry(d.name)["projects"] == [p["id"]] and "study" not in tm.entry(d.name)
    assert (tmp_path / "timemachine" / ".git").is_dir() and tm.log()


def test_retrieve_by_job_number(client, tmp_path):
    from mister_plis.app import modules
    timemachine = modules.get("timemachine")

    jid = _run(client, tmp_path)["id"]
    suffix = jid.rsplit("-", 1)[1]
    found = client.get(f"/api/tm/find?q={suffix.upper()}").json()["results"]
    assert [f["id"] for f in found] == [jid] and found[0]["source"] == "jobs"
    r = client.post("/api/tm/retrieve", json={"id": f" ({suffix}) "})
    assert r.status_code == 200 and r.json()["entry"]["id"] == jid
    assert timemachine.has(jid)
    assert client.post("/api/tm/retrieve", json={"id": jid}).json()["already"]
    bad = client.post("/api/tm/retrieve", json={"id": "ffffff"})
    assert bad.status_code == 422 and "No job" in bad.json()["error"]
    client.delete(f"/api/tm/{jid}")


def test_retrieve_from_the_backup_folder(client, tmp_path, backup_dir):
    from mister_plis.app import jobs, modules
    timemachine = modules.get("timemachine")

    job_d = _run(client, tmp_path, name="Ola")
    jid = job_d["id"]
    client.post("/api/lab/backup")
    jobs.delete([jobs.get(jid)])  # cleaned up from the server, only the backup is left
    found = client.get(f"/api/tm/find?q={jid}").json()["results"]
    assert found and found[0]["source"] == "backup"
    r = client.post("/api/tm/retrieve", json={"id": jid})
    assert r.status_code == 200 and r.json()["entry"]["source"] == "backup"
    d = client.get(f"/api/tm/{jid}").json()
    assert d["user"] == "Ola" and {f["name"] for f in d["files_kept"]} >= set(_downloads(job_d))
    assert not any(f["name"].startswith("job-info") for f in d["files_kept"])
    t = next(o for o in d["outputs"] if o["kind"] == "table")
    assert client.get(t["download"]["url"]).status_code == 200
    client.delete(f"/api/tm/{jid}")
    assert not timemachine.has(jid)


def test_time_machine_page_is_dark(client):
    page = client.get("/timemachine").text
    assert 'data-theme="dark"' in page and 'class=" tm"' in page.replace("notes-on", "") and 'id="tm-retrieve"' in page
    assert client.get("/timemachine/20200101-000000-abcdef").status_code == 200
    home = client.get("/").text
    assert 'href="/timemachine"' in home and "galaxy" in home


def test_pdf_shows_the_job_number_with_its_mark():
    from mister_plis import printout
    from mister_plis.report import ReportInfo

    pdf = printout.results_pdf([{"kind": "metric", "label": "x", "value": 1}], ReportInfo(title="T", job_id="20261019-142301-a1b2c3"))
    assert pdf[:4] == b"%PDF"


def _upload(client, name, data=b"x"):
    return client.post("/api/uploads", files={"file": (name, data)}).json()["id"]


def test_versions_uploaded_file_and_rerun(client, tmp_path):
    from mister_plis.app import jobs, modules
    timemachine = modules.get("timemachine")

    first = _run(client, tmp_path, keyword="v1")
    root = first["id"]
    psi = client.post("/api/tm/projects", json={"name": "Versions test"}).json()
    try:
        client.post(f"/api/jobs/{root}/timemachine")
        client.post("/api/tm/assign", json={"ids": [root], "add": [psi["id"]]})

        # someone adds analysis to the downloaded sheet and uploads it back
        up = _upload(client, "results with stats.xlsx", b"PK fake")
        v2 = client.post(f"/api/tm/{root}/versions", json={"uploads": [up], "note": "added t-test"}).json()
        assert v2["kind"] == "update" and v2["version_of"] == root and v2["projects"] == [psi["id"]] and v2["note"] == "added t-test"
        d2 = client.get(f"/api/tm/{v2['id']}").json()
        assert d2["version"] == 2 and d2["versions"] == 2 and d2["root"] == root
        assert [f["name"] for f in d2["files_kept"]] == ["results with stats.xlsx"]
        assert client.get(d2["outputs"][0]["url"]).content == b"PK fake"
        assert client.post(f"/api/tm/{root}/versions", json={"uploads": []}).status_code == 422

        # a re-run started from the kept job: the result page offers it as a new version, and it joins by itself
        rerun = client.post("/api/tools/toy-table/run", json={"params": first["params"], "keyword": "v3", "parent": root}).json()
        assert rerun["parent"] == root and rerun["tm_root"] == root
        v3 = client.post(f"/api/jobs/{rerun['id']}/timemachine").json()["entry"]
        assert v3["version_of"] == root and timemachine.lineage(root) == [root, v2["id"], rerun["id"]]
        lineage = client.get(f"/api/tm/{root}").json()["lineage"]
        assert [(v["n"], v["kind"]) for v in lineage] == [(1, "job"), (2, "update"), (3, "job")]

        # any other job by its number
        other = _run(client, tmp_path, keyword="other")["id"]
        v4 = client.post(f"/api/tm/{v2['id']}/versions/job", json={"id": other}).json()
        assert v4["version_of"] == root and timemachine.version_number(other) == 4

        # all versions share the projects; moving one moves them all, in one commit
        client.post("/api/tm/assign", json={"ids": [other], "remove": [psi["id"]]})
        assert all(timemachine.entry(v)["projects"] == [] for v in timemachine.lineage(root))
        top = client.get("/api/tm/history").json()["commits"][0]
        assert set(top["jobs"]) == set(timemachine.lineage(root))
        assert any(c["action"] == "version" for c in client.get(f"/api/tm/history?job={root}").json()["commits"])
        assert jobs.get(v2["id"]) is None  # an uploaded version is not a job
    finally:
        for v in list(timemachine.lineage(root)):
            client.delete(f"/api/tm/{v}")
        client.delete(f"/api/tm/projects/{psi['id']}")


def test_manual_entries(client):
    from mister_plis.app import modules
    timemachine = modules.get("timemachine")

    up = _upload(client, "blot.png", b"\x89PNG fake")
    for body in ({"title": "", "description": "d", "uploads": [up]}, {"title": "t", "description": " ", "uploads": [up]},
                 {"title": "t", "description": "d", "uploads": []}):
        assert client.post("/api/tm/manual", json=body).status_code == 422
    e = client.post("/api/tm/manual", json={"title": "Western blot PsbA", "description": "March 2026, 3 replicates", "uploads": [up]}).json()
    try:
        assert e["kind"] == "manual" and e["title"] == "Western blot PsbA"
        d = client.get(f"/api/tm/{e['id']}").json()
        assert d["tool_name"] == "Western blot PsbA" and d["outputs"][0]["kind"] == "image"
        assert not any(j["id"] == e["id"] for j in client.get("/api/jobs?limit=5000").json()["jobs"])  # only in Time Machine
        assert client.get(f"/api/tm/find?q={e['id']}").json()["results"][0]["in_tm"]
        v2 = client.post(f"/api/tm/{e['id']}/versions", json={"uploads": [_upload(client, "blot-v2.png")]}).json()
        assert v2["title"] == "Western blot PsbA" and timemachine.version_number(v2["id"]) == 2
        client.delete(f"/api/tm/{v2['id']}")
    finally:
        client.delete(f"/api/tm/{e['id']}")


def test_titles_in_time_machine(client, tmp_path):
    from mister_plis.app import modules
    timemachine = modules.get("timemachine")

    job = client.post("/api/tools/toy-table/run", json={"params": _run(client, tmp_path)["params"], "title": "WT vs mutant"}).json()
    jid = job["id"]
    client.post(f"/api/jobs/{jid}/timemachine")
    try:
        assert client.get(f"/api/tm/{jid}").json()["title"] == "WT vs mutant"  # comes along when kept
        client.post(f"/api/tm/{jid}", json={"title": "WT vs mutant, day 3"})
        assert client.get(f"/api/tm/{jid}").json()["title"] == "WT vs mutant, day 3"
        assert client.get(f"/api/jobs/{jid}").json()["title"] == "WT vs mutant"  # the copy has its own title
        timemachine.load()
        assert timemachine.job(jid).title == "WT vs mutant, day 3"
        assert client.get(f"/api/tm/history?job={jid}").json()["commits"][0]["action"] == "title"
        v2 = client.post(f"/api/tm/{jid}/versions", json={"uploads": [_upload(client, "a.xlsx")]}).json()
        assert client.get(f"/api/tm/{v2['id']}").json()["title"] == "WT vs mutant, day 3"

        m = client.post("/api/tm/manual", json={"title": "Blot", "description": "d", "uploads": [_upload(client, "b.png")]}).json()
        assert client.post(f"/api/tm/{m['id']}", json={"title": ""}).status_code == 422  # its title is its name
        client.post(f"/api/tm/{m['id']}", json={"title": "Blot, March"})
        assert client.get(f"/api/tm/{m['id']}").json()["tool_name"] == "Blot, March"
        client.delete(f"/api/tm/{m['id']}")
    finally:
        for v in list(timemachine.lineage(jid)):
            client.delete(f"/api/tm/{v}")


def test_tasks_filled_by_files_or_by_a_job(client, tmp_path):
    from mister_plis.app import modules
    timemachine = modules.get("timemachine")

    for body in ({"title": "", "description": "d"}, {"title": "t", "description": " "}):
        assert client.post("/api/tm/tasks", json=body).status_code == 422
    client.cookies.set("name", "Michal")
    try:
        t = client.post("/api/tm/tasks", json={"title": "77K of the PsbA mutant", "description": "3 replicates", "assignee": "Anna"}).json()
    finally:
        client.cookies.delete("name")
    made = [t["id"]]
    try:
        # a task: no files, someone to do it, open
        assert t["kind"] == "task" and t["assignee"] == "Anna" and not t["done"]
        d = client.get(f"/api/tm/{t['id']}").json()
        assert d["tool_name"] == "77K of the PsbA mutant" and d["user"] == "Michal" and d["outputs"] == [] and d["files_kept"] == []
        assert [x["id"] for x in client.get("/api/tm/tasks").json()["tasks"]] == [t["id"]]
        assert "Anna" in client.get("/api/tm").json()["people"]
        michal = next(p for p in client.get("/api/people").json()["people"] if p["name"] == "Michal")
        assert michal["kept"] >= 1  # People (Settings → People) counts what was kept in Time Machine
        assert client.get(f"/api/tm/history?job={t['id']}").json()["commits"][0]["action"] == "task"

        # reassigned, description changed; a job that isn't a task can't be changed like one
        e = client.post(f"/api/tm/{t['id']}", json={"assignee": "Ola", "description": "4 replicates"}).json()
        assert e["assignee"] == "Ola" and e["description"] == "4 replicates"
        assert client.post(f"/api/tm/{t['id']}", json={"description": ""}).status_code == 422

        # the files are uploaded to it → its version 2, and the task is done; taking that version out reopens it
        v2 = client.post(f"/api/tm/{t['id']}/versions", json={"uploads": [_upload(client, "77K.xlsx")]}).json()
        made.append(v2["id"])
        assert v2["version_of"] == t["id"] and v2["title"] == "77K of the PsbA mutant"
        assert timemachine.entry(t["id"])["done_with"] == v2["id"] and client.get("/api/tm/tasks").json()["tasks"] == []
        assert client.get("/api/tm/history").json()["commits"][0]["subject"].startswith("Task “77K of the PsbA mutant” done")
        client.delete(f"/api/tm/{v2['id']}")
        assert not timemachine.entry(t["id"])["done"]

        # a job run for it, from its result page
        job = _run(client, tmp_path, keyword="77K")["id"]
        made.append(job)
        assert client.post(f"/api/jobs/{job}/timemachine", json={"task": job}).status_code == 422  # not a task
        r = client.post(f"/api/jobs/{job}/timemachine", json={"task": t["id"]}).json()
        assert r["entry"]["version_of"] == t["id"] and timemachine.entry(t["id"])["done_with"] == job
        assert client.get(f"/api/tm/{job}").json()["version"] == 2

        # a job kept on its own already joins a task by its number
        t2 = client.post("/api/tm/tasks", json={"title": "Second", "description": "d"}).json()
        made.append(t2["id"])
        other = _run(client, tmp_path)["id"]
        made.append(other)
        client.post(f"/api/jobs/{other}/timemachine")
        e = client.post(f"/api/tm/{t2['id']}/versions/job", json={"id": other}).json()
        assert e["version_of"] == t2["id"] and timemachine.entry(t2["id"])["done_with"] == other
        assert client.post(f"/api/tm/{t['id']}/versions/job", json={"id": other}).status_code == 422  # already part of another
        timemachine.load()
        assert timemachine.entry(t2["id"])["done"] and timemachine.lineage(t2["id"]) == [t2["id"], other]
    finally:
        for v in reversed(made):
            if timemachine.has(v):
                client.delete(f"/api/tm/{v}")


def test_project_colour_and_merge(client, tmp_path):
    from mister_plis.app import modules
    timemachine = modules.get("timemachine")

    a, b = _run(client, tmp_path)["id"], _run(client, tmp_path)["id"]
    psi = client.post("/api/tm/projects", json={"name": "PSI", "description": "photosystem I"}).json()
    psii = client.post("/api/tm/projects", json={"name": "PSII"}).json()
    try:
        assert client.get("/api/tm").json()["colors"][0].startswith("#")
        # a colour of one's own; nonsense is refused
        assert client.post(f"/api/tm/projects/{psi['id']}", json={"color": "#123ABC"}).json()["color"] == "#123abc"
        assert client.post(f"/api/tm/projects/{psi['id']}", json={"color": "red"}).status_code == 422
        assert client.get("/api/tm/history").json()["commits"][0]["subject"] == "New colour for project “PSI”: #123abc"

        # a in PSI, b in both (and a version of a): merging PSI into PSII moves them all, in one commit
        client.post("/api/tm/retrieve", json={"id": a, "projects": [psi["id"]]})
        v2 = client.post(f"/api/tm/{a}/versions", json={"uploads": [_upload(client, "a.xlsx")]}).json()
        client.post("/api/tm/retrieve", json={"id": b, "projects": [psi["id"], psii["id"]]})
        assert client.post(f"/api/tm/projects/{psi['id']}/merge", json={"into": psi["id"]}).status_code == 422
        r = client.post(f"/api/tm/projects/{psi['id']}/merge", json={"into": psii["id"]}).json()
        assert r["moved"] == 3 and r["description"] == "photosystem I"
        assert all(timemachine.entry(j)["projects"] == [psii["id"]] for j in (a, v2["id"], b))
        assert [p["id"] for p in timemachine.projects()].count(psi["id"]) == 0
        top = client.get("/api/tm/history").json()["commits"][0]
        assert top["subject"] == "Merge project “PSI” into “PSII” (3 result(s) moved)" and set(top["jobs"]) == {a, v2["id"], b}
    finally:
        for j in (v2["id"], a, b):
            client.delete(f"/api/tm/{j}")
        for p in (psi, psii):
            client.delete(f"/api/tm/projects/{p['id']}")


def test_merging_people_reaches_time_machine(client):
    from mister_plis.app import modules
    timemachine = modules.get("timemachine")

    client.cookies.set("name", "Basia")
    try:
        t = client.post("/api/tm/tasks", json={"title": "Merge me", "description": "d", "assignee": "Zosia"}).json()
    finally:
        client.cookies.delete("name")
    try:
        client.cookies.set("name", "Zosia")
        client.post("/api/feedback", json={"kind": "idea", "text": "so Zosia is in People"})
        client.cookies.set("name", "Zofia")
        client.post("/api/feedback", json={"kind": "idea", "text": "and Zofia too"})
        client.cookies.delete("name")
        d = client.post("/api/people/merge", json={"from": "Zosia", "into": "Zofia"}).json()
        assert d["moved"]["kept"] == 1 and timemachine.entry(t["id"])["assignee"] == "Zofia"
        d = client.post("/api/people/merge", json={"from": "Basia", "into": "Zofia"}).json()
        assert timemachine.entry(t["id"])["added_by"] == "Zofia" and client.get(f"/api/tm/{t['id']}").json()["user"] == "Zofia"
        offered = client.get("/api/tm").json()["people"]
        assert "Zofia" in offered and "Zosia" not in offered and "Basia" not in offered
        # an old name typed or sent from a page opened before the merge is saved as the kept one
        assert client.post(f"/api/tm/{t['id']}", json={"assignee": "zosia"}).json()["assignee"] == "Zofia"
        assert client.get("/api/tm/history").json()["commits"][0]["subject"].startswith("“Basia” and “Zofia” are one person")
    finally:
        client.delete(f"/api/tm/{t['id']}")
