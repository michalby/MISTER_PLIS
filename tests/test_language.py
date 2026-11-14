"""English by default; files on disk always English; only the interface is translated (Polish on request)."""

import json

from openpyxl import load_workbook

from mister_plis import i18n
from mister_plis.prefs import DEFAULTS, current_prefs
from test_backup import CSV


def _polish_job(client, tmp_path, name="Ola"):
    """A job of the test tool toy-table (kept in the history) run by someone whose interface is in Polish."""
    csv = tmp_path / "run1.csv"
    csv.write_text(CSV, encoding="utf-8")
    client.cookies.set("lang", "pl")
    client.cookies.set("name", name)
    try:
        with csv.open("rb") as f:
            up = client.post("/api/uploads", files={"file": ("run1.csv", f, "text/csv")}).json()
        rows = client.post("/api/tools/toy-table/suggest/samples", json={"files": [up["id"]]}).json()["result"]
        job = client.post("/api/tools/toy-table/run", json={"params": {"files": [up["id"]], "samples": rows}}).json()
        assert job["status"] == "done", job
        again = client.get(f"/api/jobs/{job['id']}").json()
    finally:
        client.cookies.clear()
        client.cookies.set("lang", "en")
    return job, again


def _metric_labels(outputs):
    return [o["label"] for o in outputs if o["kind"] == "metric"]


def test_english_is_the_default(client):
    client.cookies.clear()
    try:
        page = client.get("/").text
        assert 'lang="en"' in page and "All tools" in page and "/i18n/" not in page
    finally:
        client.cookies.set("lang", "en")
    assert DEFAULTS["lang"] == "en" and i18n.lang() == "en"


def test_a_polish_users_job_is_stored_in_english_and_shown_in_polish(client, tmp_path):
    from mister_plis.app import jobs

    job, again = _polish_job(client, tmp_path)
    # shown: Polish, when the job is run and when it is opened again
    for shown in (job, again):
        assert "Wartość średnia" in _metric_labels(shown["outputs"])
        table = next(o for o in shown["outputs"] if o["kind"] == "table")
        assert table["title"] == "Próbki i średnie" and "Próbka" in table["columns"]
    # stored: English
    stored = jobs.get(job["id"])
    meta = json.loads((stored.workdir / "job.json").read_text(encoding="utf-8"))
    book = meta.pop("phrases")
    assert book["pl"]["Mean value"] == "Wartość średnia"  # the tool's translated pieces, for showing it later
    assert "Mean value" in _metric_labels(meta["outputs"]) and "Wartość średnia" not in json.dumps(meta, ensure_ascii=False)
    # result files: English
    for f in (stored.workdir / "out").glob("*.xlsx"):
        ws = load_workbook(f).worksheets[0]
        header = [c.value for c in ws[1]]
        words = " ".join(map(str, header)).lower()
        assert "próbka" not in words and "sample" in words, (f.name, header)
    # someone with an English interface sees English
    assert "Mean value" in _metric_labels(client.get(f"/api/jobs/{job['id']}").json()["outputs"])


def test_backups_are_english_whoever_presses_back_up_now(client, tmp_path):
    from mister_plis.app import backups

    job, _ = _polish_job(client, tmp_path, name="Ola Nowak")
    folder = tmp_path / "bk"
    folder.mkdir()
    backups.update(str(folder), 1)
    client.cookies.set("lang", "pl")
    try:
        assert client.post("/api/lab/backup").status_code == 200
    finally:
        client.cookies.set("lang", "en")
        backups.update("", 1)
    [info] = [p for p in folder.rglob("README.md") if job["id"] in p.parent.name]
    text = info.read_text(encoding="utf-8")
    assert "## Settings" in text and "**Samples:**" in text and "Dilution" in text and "Mean value" in text
    assert "Próbki" not in text and "Rozcieńczenie" not in text and "Wartość średnia" not in text
    meta = json.loads((info.parent / "mister-plis" / "job.json").read_text(encoding="utf-8"))
    assert "Mean value" in _metric_labels(meta["outputs"])
    summary = load_workbook(info.parent / "results.xlsx")["Summary"]
    assert "Mean value" in [c.value for c in summary["A"]]


def test_time_machine_keeps_english_and_shows_polish(client, tmp_path):
    from mister_plis.app import modules
    timemachine = modules.get("timemachine")

    job, _ = _polish_job(client, tmp_path)
    assert client.post(f"/api/jobs/{job['id']}/timemachine", json={}).status_code == 200
    try:
        kept = json.loads((timemachine.root / job["id"] / "meta.json").read_text(encoding="utf-8"))
        assert "Mean value" in _metric_labels(kept["outputs"])
        shown = client.get(f"/api/tm/{job['id']}", cookies={"lang": "pl"}).json()
        assert "Wartość średnia" in _metric_labels(shown["outputs"])
    finally:
        client.cookies.set("lang", "en")
        client.delete(f"/api/tm/{job['id']}")


def test_plurals_inside_sentences_are_translated():
    assert i18n.tr("6 spectra", "pl") == "6 widm" and i18n.tr("22 spectra", "pl") == "22 widma"
    assert i18n.tr("1 spectrum", "pl") == "1 widmo" and i18n.tr("big spectra", "pl") == "big spectra"
    assert i18n.tr("**6 spectra** from **2 samples**", "pl") == "**6 widm**, **2 próbki**"


def test_glued_pieces_come_back_in_polish():
    """A tool that glues translated pieces with + (or lower-cases one) reads as if it had run in Polish."""
    token = current_prefs.set({**DEFAULTS, "lang": "en"})
    try:
        with i18n.recording() as book:
            how = i18n.tr("Peak maximum in the window").lower()
            text = (i18n.tr("Signal = **{how}**", how=how) + i18n.tr(", × dilution") + i18n.tr(" — relative units."))
            n = i18n.tn(5, "{n} spectrum", "{n} spectra")
    finally:
        current_prefs.reset(token)
    assert text.startswith("Signal = **peak maximum in the window**") and n == "5 spectra"
    polish = {**DEFAULTS, "lang": "pl"}
    token = current_prefs.set(polish)
    try:
        expected = (i18n.tr("Signal = **{how}**", how=i18n.tr("Peak maximum in the window").lower())
                    + i18n.tr(", × dilution") + i18n.tr(" — relative units."))
        with i18n.phrases(book):
            assert i18n.tr_text(text) == expected
            assert i18n.tr(n) == "5 widm"
        assert i18n.tr_text(text) != expected  # without the phrase book the glued sentence can't be translated
    finally:
        current_prefs.reset(token)
