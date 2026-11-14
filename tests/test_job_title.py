"""A job's title: typed above the Run button or set later, shown after the tool's name."""

from test_backup import CSV


def test_title_at_run_and_changed_later(client, tmp_path):
    from mister_plis.app import jobs
    from mister_plis.export.readme import build
    from mister_plis.registry import registry

    csv = tmp_path / "run1.csv"
    csv.write_text(CSV, encoding="utf-8")
    with csv.open("rb") as f:
        up = client.post("/api/uploads", files={"file": ("run1.csv", f, "text/csv")}).json()
    rows = client.post("/api/tools/toy-table/suggest/samples", json={"files": [up["id"]]}).json()["result"]
    job = client.post("/api/tools/toy-table/run", json={"params": {"files": [up["id"]], "samples": rows}, "title": "  WT   vs mutant "}).json()
    assert job["status"] == "done" and job["title"] == "WT vs mutant"

    r = client.post(f"/api/jobs/{job['id']}/title", json={"title": "WT vs mutant, day 3"})
    assert r.json()["title"] == "WT vs mutant, day 3"
    assert client.get(f"/api/jobs/{job['id']}").json()["title"] == "WT vs mutant, day 3"
    assert any(j["id"] == job["id"] and j["title"] == "WT vs mutant, day 3" for j in client.get("/api/jobs").json()["jobs"])
    assert '"title": "WT vs mutant, day 3"' in (jobs.get(job["id"]).workdir / "job.json").read_text(encoding="utf-8")  # survives a restart
    stored = jobs.get(job["id"])
    assert build(stored.record_dict(), stored.workdir, {}, registry.get("toy-table")).startswith("# Toy averages — WT vs mutant, day 3")
    assert client.get(job["report"]).status_code == 200
    assert client.post(f"/api/jobs/{job['id']}/title", json={"title": ""}).json()["title"] == ""
    assert client.post("/api/jobs/20200101-000000-abcdef/title", json={"title": "x"}).status_code == 404
