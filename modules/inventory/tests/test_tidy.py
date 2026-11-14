"""Reagents' tidy-up (mister_plis/tidy.py): format and spelling checks, notes from the lab read by a (fake) local
model, what is applied by itself, applying and rejecting proposals, the schedule; and the notebook's automatic
sync and the nightly code update settings."""

import json
import time

import pytest
from openpyxl import load_workbook

from modules.inventory import tidy as tidy_mod
from mister_plis import updater
from mister_plis.errors import ToolError
from modules.inventory.tidy import Tidy
from test_reagents import XLSX, _git, inv  # noqa: F401  (the inventory fixture)


class FakeOllama:
    """Answers like Ollama's /api/chat with structured output: one queued answer per call."""

    def __init__(self, answers=None, up=True):
        self.url, self.answers, self.calls, self.up = "http://127.0.0.1:11434", list(answers or []), [], up

    enabled = True

    def models(self):
        if not self.up:
            raise ToolError("Ollama isn't answering at http://127.0.0.1:11434 (refused). Is it running?")
        return ["qwen3:32b"]

    def chat(self, model, messages, schema, timeout=900):
        self.calls.append(messages)
        return self.answers.pop(0)


def _edit(inv, rid, **cells):
    """Write cells straight into the workbook, as Excel or a script would, and commit."""
    wb = load_workbook(inv.repo / XLSX)
    ws = wb["reagents"]
    head = [c.value for c in ws[1]]
    row = next(r for r in range(2, ws.max_row + 1) if str(ws.cell(r, 1).value) == str(rid))
    for k, v in cells.items():
        ws.cell(row, head.index(k) + 1).value = v
    wb.save(inv.repo / XLSX)
    inv._book = None
    inv.commit("edit in Excel", "t")


@pytest.fixture
def tidy(inv):  # noqa: F811
    t = Tidy(inv, "")
    t.ollama = FakeOllama()
    return t


def _by_kind(rec, kind):
    return [p for p in rec["proposals"] if p["kind"] == kind]


def test_format_checks_and_problems(inv, tidy):  # noqa: F811
    _edit(inv, 1, storage_exact_location="brak danych", producer_1_containers_count="3", ghs02_flammable="TRUE",
          storage_categories="A; G", disposed_date="5.11.2026", hazard_priority="wysoki", cas_no="  67-64-1  ")
    _edit(inv, 3, hazard_priority="ŚREDNI")  # not an allowed value: for a person
    tidy.save_settings(apply="none")
    rec = tidy.run("Ola")
    assert rec["ok"] and rec["model"] == ""
    (p,) = _by_kind(rec, "format")
    got = {c["column"]: (c["old"], c["new"]) for c in p["changes"]}
    assert got == {"storage_exact_location": ("brak danych", None), "producer_1_containers_count": ("3", 3),
                   "ghs02_flammable": ("TRUE", True), "storage_categories": ("A; G", "A;G"), "disposed_date": ("5.11.2026", "2026-11-05"),
                   "hazard_priority": ("wysoki", "WYSOKI"), "cas_no": ("  67-64-1  ", "67-64-1")}
    assert p["status"] == "waiting" and [x["column"] for x in rec["problems"]] == ["hazard_priority"]
    assert inv.get("1")["storage_exact_location"] == "brak danych"  # nothing applied: apply = none

    rec = tidy.decide(p["id"], "apply", "Ola")
    assert rec["proposals"][0]["status"] == "applied"
    r = inv.get("1")
    assert r["storage_exact_location"] is None and r["producer_1_containers_count"] == 3 and r["ghs02_flammable"] is True
    assert r["disposed_date"] == "2026-11-05" and r["hazard_priority"] == "WYSOKI"
    log = _git(inv.repo, "log", "-1", "--format=%an%n%B")
    assert log.startswith("Ola\nlabel_no 1 aceton: tidy-up of ") and "Action: tidy" in log and "Proposed-by: Tidy-up" in log
    assert "Reagent: 1" in log and _git(inv.repo, "status", "--porcelain") == ""
    assert tidy.run()["proposals"] == []  # tidy now


def test_checks_apply_by_themselves_and_producers_get_one_spelling(inv, tidy):  # noqa: F811
    _edit(inv, 2, producer_1_name="Sigma Aldrich", storage_exact_location="-")
    _edit(inv, 3, producer_2_name="sigma-aldrich")
    _edit(inv, 1, producer_2_name="Sigma Aldrich")
    rec = tidy.run()  # apply = checks (the default)
    (sp,) = _by_kind(rec, "spelling")
    assert sp["status"] == "applied" and {c["new"] for c in sp["changes"]} == {"Sigma Aldrich"}
    assert inv.get("3")["producer_2_name"] == "Sigma Aldrich" and inv.get("2")["storage_exact_location"] is None
    assert all(p["status"] == "applied" for p in rec["proposals"])
    assert "Tidy-up" in _git(inv.repo, "log", "--format=%an")


def test_a_note_becomes_a_correction(inv, tidy):  # noqa: F811
    note = inv.add_info("Zostały dwie butelki acetonu z Rotha, przeniesione do szafy B", "Ola", "1")
    tidy.save_settings(model="qwen3:32b")
    tidy.ollama.answers = [{"clear": True, "summary": "aceton: 2 butelki, szafa B", "changes": [
        {"label_no": "1", "column": "producer_1_containers_count", "value": "2", "why": "dwie butelki"},
        {"label_no": "1", "column": "storage_exact_location", "value": "szafa B", "why": "przeniesione"}]}]
    rec = tidy.run()
    (p,) = _by_kind(rec, "note")
    assert p["status"] == "waiting" and p["note"] == note["id"] and "aceton" in p["note_text"]  # checks only: waits
    prompt = tidy.ollama.calls[0][1]["content"]
    assert "Zostały dwie butelki" in prompt and "label_no 1" in prompt and "1 | aceton | acetone" in prompt
    assert "producer_N_containers_count" in prompt and "storage_category_primary: one of [A;C;G]" in prompt

    again = tidy.run()  # still waiting: not asked again
    assert len(tidy.ollama.calls) == 1 and _by_kind(again, "note")[0]["note"] == note["id"]
    pid = _by_kind(again, "note")[0]["id"]
    tidy.decide(pid, "apply", "Michał")
    r = inv.get("1")
    assert r["producer_1_containers_count"] == 2 and r["storage_exact_location"] == "szafa B"
    i = inv.infos()[0]
    assert i["status"] == "done" and i["done_by"] == "Michał" and "szafa B" in i["agent_note"]
    log = _git(inv.repo, "log", "-1", "--format=%B")
    assert f"Info {note['id']}" in log and f"Info: {note['id']}" in log and "Reagent: 1" in log
    assert _git(inv.repo, "show", "--name-only", "--format=", "HEAD").split() == sorted(
        ["info/" + note["id"] + ".json", "wykaz_odczynnikow_kompletny.csv", XLSX])  # one commit: workbook, CSV and note
    with pytest.raises(ToolError, match="already dealt with"):
        tidy.decide(pid, "apply", "Michał")


def test_unclear_notes_and_a_second_try(inv, tidy):  # noqa: F811
    a = inv.add_info("coś jest nie tak z tą butelką", "Ola")
    b = inv.add_info("fenol do szafy G", "Ola")
    tidy.save_settings(model="qwen3:32b", apply="all")
    tidy.ollama.answers = [
        {"clear": False, "question": "Której butelki dotyczy ta informacja?", "summary": "", "changes": []},
        {"clear": True, "summary": "fenol → G", "changes": [{"label_no": "3", "column": "storage_category_primary", "value": "Z"}]},
        {"clear": True, "summary": "fenol → G", "changes": [{"label_no": "3", "column": "storage_category_primary", "value": "G"}]},
    ]
    rec = tidy.run()
    assert rec["unclear"][0]["note"] == a["id"] and "Której butelki" in rec["unclear"][0]["question"]
    retry = tidy.ollama.calls[2]
    assert retry[-1]["role"] == "user" and "is not one of A, C, G" in retry[-1]["content"]
    (p,) = _by_kind(rec, "note")
    assert p["status"] == "applied" and inv.get("3")["storage_category_primary"] == "G"
    notes = {i["id"]: i for i in inv.infos()}
    assert notes[a["id"]]["status"] == "new" and "Której butelki" in notes[a["id"]]["agent_note"]
    assert notes[b["id"]]["status"] == "done" and notes[b["id"]]["done_by"] == "Tidy-up (qwen3:32b)"
    assert tidy.run()["unclear"] == [] and len(tidy.ollama.calls) == 3  # a note with a question isn't asked again


def test_model_mistakes_never_reach_the_inventory(inv, tidy):  # noqa: F811
    inv.add_info("aceton wyrzucony", "Ola")
    tidy.save_settings(model="m", apply="all")
    bad = {"clear": True, "summary": "x", "changes": [{"label_no": "99", "column": "is_disposed", "value": "true"},
                                                      {"label_no": "1", "column": "label_no", "value": "7"}]}
    tidy.ollama.answers = [bad, bad]
    rec = tidy.run()
    assert _by_kind(rec, "note") == [] and "no reagent with label_no '99'" in rec["unclear"][0]["question"]
    assert inv.get("1")["is_disposed"] is False


def test_a_proposal_is_refused_when_the_cell_changed_meanwhile(inv, tidy):  # noqa: F811
    _edit(inv, 2, storage_exact_location="?")
    tidy.save_settings(apply="none")
    p = _by_kind(tidy.run(), "format")[0]
    inv.save({"storage_exact_location": "szafa G"}, "Ola", "2")
    rec = tidy.decide(p["id"], "apply", "Michał")
    assert rec["proposals"][0]["status"] == "failed" and "since this was proposed" in rec["proposals"][0]["error"]
    assert inv.get("2")["storage_exact_location"] == "szafa G" and _git(inv.repo, "status", "--porcelain") == ""


def test_rejecting_a_note_proposal_leaves_it_for_a_person(inv, tidy):  # noqa: F811
    n = inv.add_info("agar się kończy", "Ola", "2")
    tidy.save_settings(model="m")
    tidy.ollama.answers = [{"clear": True, "summary": "agar do zamówienia",
                            "changes": [{"label_no": "2", "column": "producer_1_to_order", "value": "true"}]}]
    p = _by_kind(tidy.run(), "note")[0]
    tidy.decide(p["id"], "reject", "Michał")
    i = inv.infos()[0]
    assert i["id"] == n["id"] and i["status"] == "new" and "rejected by Michał" in i["agent_note"]
    assert inv.get("2")["producer_1_to_order"] is False


def test_no_model_running(inv, tidy):  # noqa: F811
    inv.add_info("x", "Ola")
    tidy.save_settings(model="m")
    tidy.ollama.up = False
    rec = tidy.run()
    assert rec["ok"] and any("the model isn't available" in s["name"] and not s["ok"] for s in rec["steps"])
    assert tidy.status()["ollama"]["ok"] is False and "isn't answering" in tidy.status()["ollama"]["error"]


def test_schedule(tidy, monkeypatch):
    def at(day, hm):
        return time.mktime(time.strptime(f"{day} {hm}", "%Y-%m-%d %H:%M"))

    monkeypatch.setattr(tidy_mod, "_now", lambda: at("2026-11-06", "01:00"))  # a Friday
    assert not tidy.due()
    tidy.save_settings(schedule="weekdays", at="02:30")
    assert not tidy.due(at("2026-11-06", "02:00")) and tidy.due(at("2026-11-06", "02:31"))
    assert not tidy.due(at("2026-11-07", "03:00"))  # Saturday
    assert tidy.next_run() == at("2026-11-06", "02:30")
    tidy.save_settings(last_scheduled="2026-11-06")
    assert not tidy.due(at("2026-11-06", "05:00")) and tidy.next_run() == at("2026-11-09", "02:30")
    monkeypatch.setattr(tidy_mod, "_now", lambda: at("2026-11-10", "09:00"))
    tidy.save_settings(schedule="daily")  # chosen after today's time: the first run is tomorrow
    assert not tidy.due() and tidy.next_run() == at("2026-11-11", "02:30")
    with pytest.raises(ToolError):
        tidy.save_settings(at="25:00")
    with pytest.raises(ToolError):
        tidy.save_settings(apply="sometimes")


def test_tidy_api(client):
    st = client.get("/api/reagents/tidy").json()
    assert st["settings"]["apply"] == "checks" and "ollama" in st and st["running"] is None
    r = client.post("/api/reagents/tidy/settings", json={"schedule": "nightly"})
    assert r.status_code == 422
    r = client.post("/api/reagents/tidy/p1", json={"action": "apply"})
    assert r.status_code == 422
    assert 'id="rg-tidy"' in client.get("/settings").text


def test_notes_and_code_update_by_themselves(client, monkeypatch, tmp_path):
    assert client.post("/api/notes/settings", json={"auto_minutes": 7}).status_code == 422
    from mister_plis.app import modules
    notebook = modules.get("notebook")
    assert client.post("/api/notes/settings", json={"auto_minutes": 15}).json() == {"auto_minutes": 15} and notebook.auto_minutes() == 15
    notebook.set_auto(0)

    monkeypatch.setattr(updater, "_auto_file", lambda: tmp_path / "auto_update.json")
    assert client.post("/api/system/auto-update", json={"mode": "always"}).status_code == 422
    assert client.post("/api/system/auto-update", json={"mode": "night"}).json()["auto"]["mode"] == "night"
    three = time.mktime(time.strptime("2026-11-06 03:10", "%Y-%m-%d %H:%M"))
    assert updater.auto_due(three) and not updater.auto_due(three + 3 * 3600)
    monkeypatch.setattr(updater, "check", lambda: {"is_repo": True, "fetch_ok": True, "behind": 2, "dirty": ["x.py"]})
    assert updater.auto_update(busy=True) == {"restart": False, "waiting": True}
    r = updater.auto_update(busy=False)
    assert r["restart"] is False and not r["ok"] and "changed on this machine" in r["result"]
    assert json.loads((tmp_path / "auto_update.json").read_text(encoding="utf-8"))["last_day"] == time.strftime("%Y-%m-%d")
    monkeypatch.setattr(updater, "check", lambda: {"is_repo": True, "fetch_ok": True, "behind": 1, "dirty": []})
    monkeypatch.setattr(updater, "sync", lambda: {"ok": True, "steps": [], "restart": True, "new": {"short": "abc1234", "subject": "New"}})
    assert updater.auto_update(busy=False) == {"restart": True, "ok": True, "result": "Updated to abc1234 New"}
