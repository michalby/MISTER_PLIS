"""Reagents: a scheduled tidy-up of the inventory, with a model running on this machine (Ollama).

It runs inside the server, so every correction goes the same way as a person's edit: checked against the
workbook's `columns` sheet, saved under the inventory's lock, committed, and sent to GitHub with the usual
cell-by-cell sync. Nothing outside the server writes to the inventory's folder, so nothing can clash with the lab.

One run (on the schedule, or **Run now** on Settings → Reagents & consumables):

1. Sync with GitHub (so the run starts from everyone's newest edits; a failed sync stops the run).
2. **Format checks** (no model): filler such as "brak danych" emptied, TRUE/FALSE and numbers stored as text made
   real, dates as yyyy-mm-dd, lists as ``B;C``, spaces, an allowed value written in another case. Values that
   can't be fixed this way are listed for a person.
3. **Spelling of producers** (no model): one manufacturer written several ways ("Sigma Aldrich", "Sigma-Aldrich")
   becomes the spelling used most.
4. **Info from the lab** (the model): each note still ``new`` is read with the inventory, and the model says
   which cells to change. Every change is checked like an edit (the reagent exists, the column exists, the value
   fits its type); a model that proposes something that doesn't fit is told why and asked once more. A note the
   model finds unclear gets its question in ``agent_note`` and stays ``new`` for a person (AGENTS.md: don't guess).

What is applied by itself is a lab-wide choice (``apply``): nothing (everything waits on the page for someone to
apply or reject it), the checks only (the default: the model's corrections wait), or everything. An applied
proposal is one commit; a person who applies a waiting one is its author.

Kept in ``<data>/modules/inventory/tidy/``: ``settings.json``, ``last_run.json`` (the newest run with its proposals) and
``runs.json`` (a short summary of the last 60 runs).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from mister_plis.errors import ToolError
from mister_plis.text import fold

from .service import N_SLOTS, Inventory, _line, _read_json, _write_json, convert, key_str, version

SCHEDULES = ("off", "daily", "weekdays")
APPLY = ("none", "checks", "all")
DEFAULTS = {"model": "", "schedule": "off", "at": "02:30", "apply": "checks"}
MAX_NOTES = 25  # notes read by the model in one run
MAX_PROBLEMS = 300
KEEP_RUNS = 60
NUM_CTX = 32768  # the prompt holds the whole (compact) inventory
FILLER = {"brak danych", "brak", "b.d.", "b/d", "bd.", "-", "--", "---", "—", "–", "?", "??", "???", "n/a", "none", "null",
          "nan", "unknown", "nieznany", "nieznane", "nieznana", "tbd", "todo"}
TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _now() -> float:
    return time.time()


def _today(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(_now() if t is None else t))


# ---- the model --------------------------------------------------------------------------------------------

class Ollama:
    """The few calls of Ollama's HTTP API that are needed (no extra packages). Never through a proxy: the model
    runs on this machine (or one on the lab's network)."""

    def __init__(self, url: str):
        self.url = (url or "").strip().rstrip("/")
        self._open = urllib.request.build_opener(urllib.request.ProxyHandler({})).open

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def _call(self, path: str, body: dict | None = None, timeout: float = 5) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with self._open(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            try:
                detail = json.loads(detail).get("error", detail)
            except (ValueError, AttributeError):
                pass
            raise ToolError(f"Ollama answered with an error: {detail}") from None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise ToolError(f"Ollama isn't answering at {self.url} ({getattr(e, 'reason', e)}). Is it running?") from None
        except ValueError:
            raise ToolError("Ollama's answer wasn't JSON.") from None

    def models(self) -> list[str]:
        if not self.enabled:
            return []
        return sorted(m.get("name") or m.get("model") for m in self._call("/api/tags").get("models", []) if m.get("name") or m.get("model"))

    def chat(self, model: str, messages: list[dict], schema: dict, timeout: float = 900) -> dict:
        """One answer, as JSON following ``schema`` (Ollama's structured outputs)."""
        r = self._call("/api/chat", {"model": model, "messages": messages, "format": schema, "stream": False,
                                     "options": {"temperature": 0, "num_ctx": NUM_CTX}}, timeout=timeout)
        content = (r.get("message") or {}).get("content") or ""
        try:
            out = json.loads(content)
        except ValueError:
            raise ToolError(f"The model's answer wasn't JSON: {content[:300]}") from None
        if not isinstance(out, dict):
            raise ToolError("The model's answer wasn't a JSON object.")
        return out


NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "clear": {"type": "boolean"},
        "question": {"type": "string"},
        "summary": {"type": "string"},
        "changes": {"type": "array", "items": {"type": "object", "properties": {
            "label_no": {"type": "string"}, "column": {"type": "string"}, "value": {"type": "string"}, "why": {"type": "string"}},
            "required": ["label_no", "column", "value"]}},
    },
    "required": ["clear", "changes", "summary"],
}

RULES = """You keep a chemistry lab's reagent inventory tidy. People send short notes from the lab ("the Sigma acetone
moved to cabinet 3", "only two bottles left", or a transcript of a walk round the lab). For ONE note you say which
cells of the inventory to change. The inventory is one row per reagent, keyed by label_no.

How notes become corrections:
- moved -> storage_exact_location
- running low -> producer_N_to_order = true and producer_N_order_amount (e.g. "2 × 1 L")
- opened -> producer_N_opened_date
- used up -> producer_N_containers_count = 0
- thrown away -> is_disposed = true and disposed_date
- borrowed -> is_borrowed, borrowed_by, borrowed_date
- a different number of containers -> producer_N_containers_count
producer_N_* is one producer slot (N = 1 to 5) of that reagent: pick the slot whose producer matches the note.

Rules:
- Use only label_no values and columns that are listed. Never invent a reagent or a column.
- Values: text as written; numbers as digits; yes/no as "true" or "false"; dates as yyyy-mm-dd; a choice from the
  allowed values only; lists separated by ";" with no spaces. An empty string empties the cell.
- Change only what the note says. Don't tidy other cells.
- DON'T GUESS. If the note is ambiguous, names a reagent you can't find for sure, needs a new reagent or a new
  producer slot, or you're unsure which slot is meant: answer "clear": false, no changes, and in "question" say
  what is unclear, in the language of the note.
- The lab keeps its consumables (pipette tips, membranes, blotting paper, coverslips, vials, gloves…) in a separate
  list you can't change. If the note says anything about consumables, even next to reagents, answer "clear": false,
  no changes, and in "question" say that the part about consumables is for a person.
- "summary": one short line saying what changes, in the language of the note.
Answer with JSON only."""


# ---- the tidy-up -----------------------------------------------------------------------------------------

class Tidy:
    def __init__(self, inv: Inventory, ollama_url: str):
        self.inv = inv
        self.root: Path = inv.root / "tidy"
        self.ollama = Ollama(ollama_url)
        self._run_lock = threading.Lock()
        self.progress: dict | None = None  # while a run is going: {"started", "step", "by"}

    # ---- settings ------------------------------------------------------------------------------------
    def settings(self) -> dict:
        d = _read_json(self.root / "settings.json")
        d = d if isinstance(d, dict) else {}
        out = {k: d.get(k, v) for k, v in DEFAULTS.items()}
        if out["schedule"] not in SCHEDULES:
            out["schedule"] = "off"
        if out["apply"] not in APPLY:
            out["apply"] = "checks"
        if not TIME.match(str(out["at"])):
            out["at"] = DEFAULTS["at"]
        out["last_scheduled"] = d.get("last_scheduled", "")
        return out

    def save_settings(self, **changes) -> dict:
        d = _read_json(self.root / "settings.json")
        d = d if isinstance(d, dict) else {}
        if "model" in changes:
            d["model"] = _line(changes["model"], 200)
        if "schedule" in changes:
            if changes["schedule"] not in SCHEDULES:
                raise ToolError("Run it every day, on weekdays, or only by hand.")
            d["schedule"] = changes["schedule"]
        if "at" in changes:
            if not TIME.match(str(changes["at"] or "")):
                raise ToolError("Write the time as hh:mm, e.g. 02:30.")
            d["at"] = changes["at"]
        if "apply" in changes:
            if changes["apply"] not in APPLY:
                raise ToolError("Unknown choice of what the tidy-up may change by itself.")
            d["apply"] = changes["apply"]
        if "schedule" in changes or "at" in changes:  # a time already past today waits for tomorrow
            at = d.get("at", DEFAULTS["at"])
            d["last_scheduled"] = _today() if time.strftime("%H:%M", time.localtime(_now())) >= at else d.get("last_scheduled", "")
        if "last_scheduled" in changes:
            d["last_scheduled"] = changes["last_scheduled"]
        self.root.mkdir(parents=True, exist_ok=True)
        _write_json(self.root / "settings.json", d)
        return self.settings()

    # ---- when ----------------------------------------------------------------------------------------
    def _runs_on(self, day: dt.date, schedule: str) -> bool:
        return schedule == "daily" or (schedule == "weekdays" and day.weekday() < 5)

    def due(self, t: float | None = None) -> bool:
        st = self.settings()
        t = _now() if t is None else t
        lt = time.localtime(t)
        day = dt.date(lt.tm_year, lt.tm_mon, lt.tm_mday)
        return (st["schedule"] != "off" and self._runs_on(day, st["schedule"]) and time.strftime("%H:%M", lt) >= st["at"]
                and st["last_scheduled"] != day.isoformat())

    def next_run(self) -> float | None:
        st = self.settings()
        if st["schedule"] == "off":
            return None
        h, m = (int(x) for x in st["at"].split(":"))
        now = dt.datetime.fromtimestamp(_now())
        for i in range(8):
            day = now.date() + dt.timedelta(days=i)
            when = dt.datetime.combine(day, dt.time(h, m))
            if self._runs_on(day, st["schedule"]) and st["last_scheduled"] != day.isoformat() and (when >= now or i == 0):
                return max(when, now).timestamp()
        return None

    def loop(self) -> None:  # pragma: no cover - a background thread
        while True:
            time.sleep(60)
            try:
                if self.due():
                    self.save_settings(last_scheduled=_today())
                    self.run("MISTER PLIS", "schedule")
            except Exception as e:
                self.inv.last_error = f"Tidy-up: {e}"

    # ---- what the page shows -------------------------------------------------------------------------
    def last(self) -> dict | None:
        r = _read_json(self.root / "last_run.json")
        return r if isinstance(r, dict) else None

    def runs(self) -> list[dict]:
        r = _read_json(self.root / "runs.json")
        return r if isinstance(r, list) else []

    def status(self, check_model: bool = True) -> dict:
        st = self.settings()
        model = {"url": self.ollama.url, "enabled": self.ollama.enabled, "ok": False, "models": [], "error": ""}
        if check_model and self.ollama.enabled:
            try:
                model["models"] = self.ollama.models()
                model["ok"] = True
            except ToolError as e:
                model["error"] = str(e)
        return {"settings": st, "ollama": model, "running": self.progress, "next_run": self.next_run(),
                "last": self.last(), "runs": self.runs()[:10], "ready": self.inv.book() is not None}

    # ---- one run -------------------------------------------------------------------------------------
    def start(self, user: str = "") -> bool:
        """Run now, in the background. False if a run is already going."""
        if self.progress is not None:
            return False
        threading.Thread(target=self._run_quietly, args=(user,), daemon=True, name="reagents-tidy").start()
        return True

    def _run_quietly(self, user: str) -> None:  # pragma: no cover - a background thread
        try:
            self.run(user, "by hand")
        except Exception as e:
            self.inv.last_error = f"Tidy-up: {e}"

    def run(self, user: str = "", trigger: str = "by hand") -> dict:
        if not self._run_lock.acquire(blocking=False):
            raise ToolError("A tidy-up is already running.")
        st = self.settings()
        rec = {"id": time.strftime("%Y%m%d-%H%M%S", time.localtime(_now())), "started": round(_now()), "finished": None,
               "trigger": trigger, "by": _line(user, 60), "model": st["model"] if self.ollama.enabled else "", "apply": st["apply"],
               "ok": False, "steps": [], "proposals": [], "problems": [], "unclear": []}
        self.progress = {"started": rec["started"], "step": "starting", "by": rec["by"]}
        try:
            self._run(rec, st)
        except Exception as e:  # a run that breaks still leaves its log
            rec["steps"].append({"name": "the tidy-up stopped", "ok": False, "output": str(e)})
        finally:
            rec["finished"] = round(_now())
            self._save_run(rec)
            self.progress = None
            self._run_lock.release()
        return rec

    def _step(self, rec: dict, name: str, ok: bool = True, output: str = "") -> None:
        rec["steps"].append({"name": name, "ok": ok, "output": output})
        if self.progress is not None:
            self.progress["step"] = name

    def _run(self, rec: dict, st: dict) -> None:
        inv = self.inv
        if inv.url:
            self.progress["step"] = "sync with GitHub"
            r = inv.sync("MISTER PLIS")
            failed = [s for s in r.get("steps", []) if not s.get("ok")]
            if not r.get("ok"):
                self._step(rec, "sync with GitHub", False, "\n".join(f"{s['name']}\n{s.get('output', '')}" for s in failed))
                return
            self._step(rec, "sync with GitHub")
        book = inv.book()
        if book is None:
            self._step(rec, "The inventory isn't here yet. Sync with GitHub first (Settings → Reagents & consumables).", False)
            return
        n = 0
        for p in self.format_checks(rec):
            n += 1
            rec["proposals"].append(p)
        self._step(rec, f"format checks: {n} reagent(s) to tidy, {len(rec['problems'])} value(s) for a person")
        n = 0
        for p in self.producer_spelling():
            n += 1
            rec["proposals"].append(p)
        self._step(rec, f"spelling of producers: {n} to unify")
        self._notes(rec, st)
        for i, p in enumerate(rec["proposals"], 1):
            p["id"] = f"p{i}"
        auto = {"none": set(), "checks": {"format", "spelling"}, "all": {"format", "spelling", "note"}}[st["apply"]]
        applied = failed = 0
        for p in rec["proposals"]:
            if p["kind"] in auto:
                self._apply(p, self.author(rec["model"]))
                applied += p["status"] == "applied"
                failed += p["status"] == "failed"
        waiting = sum(p["status"] == "waiting" for p in rec["proposals"])
        if failed:
            self._step(rec, f"{applied} applied, {waiting} waiting for a person, {failed} failed", False)
        else:
            self._step(rec, f"{applied} applied, {waiting} waiting for a person")
        rec["ok"] = True

    @staticmethod
    def author(model: str) -> str:
        return f"Tidy-up ({model})" if model else "Tidy-up"

    def _save_run(self, rec: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _write_json(self.root / "last_run.json", rec)
        summary = {k: rec[k] for k in ("id", "started", "finished", "trigger", "by", "model", "ok")}
        summary.update({k: sum(p["status"] == k for p in rec["proposals"]) for k in ("applied", "waiting", "rejected", "failed")})
        summary["problems"], summary["unclear"] = len(rec["problems"]), len(rec["unclear"])
        _write_json(self.root / "runs.json", ([summary] + [r for r in self.runs() if r.get("id") != rec["id"]])[:KEEP_RUNS])

    # ---- checks without a model ----------------------------------------------------------------------
    def _fields(self) -> dict[str, dict]:
        return {f["key"]: f for f in self.inv._need_book().columns}

    def _name(self, row: dict) -> str:
        t = self.inv.config()["title"].get("pl") or "name_pl"
        return _line(row.get(t) or row.get("name_pl") or "", 80)

    @staticmethod
    def _normal(f: dict, v):
        """(the tidy value, why) — or (v, None) when it is fine. Raises ToolError for a value nobody can fix here."""
        if isinstance(v, str) and fold(" ".join(v.split())) in FILLER:
            return None, "filler — an empty cell means unknown"
        t = f["type"]
        if t == "bool" and isinstance(v, bool):
            return v, None
        if t == "number" and isinstance(v, (int, float)) and not isinstance(v, bool):
            if f.get("integer") and isinstance(v, float) and not v.is_integer():
                raise ToolError(f"“{f['label']}” must be a whole number (got “{v}”).")
            return v, None
        if t in ("text", "url") and isinstance(v, str) and len(v) > 1000:
            return v, None  # longer than an edit keeps: left alone
        try:
            new = convert(f, v)
        except ToolError:
            if t in ("choice", "multi") and f.get("options"):  # an allowed value written in another case
                by_fold = {fold(o): o for o in f["options"]}
                items = [v] if t == "choice" else re.split(r"[;,\n]", str(v))
                mapped = [by_fold.get(fold(_line(i, 120))) for i in items if _line(i, 120)]
                if mapped and all(mapped):
                    return (mapped[0] if t == "choice" else ";".join(dict.fromkeys(mapped))), "an allowed value, spelled as in the list"
            raise
        if new == v and type(new) is type(v):
            return v, None
        if t in ("text", "longtext", "url", "choice", "multi") and not isinstance(v, str) and str(v) == str(new):
            return v, None  # e.g. a catalogue number stored as a number: fine as it is
        why = {"bool": "yes/no as a real TRUE/FALSE", "number": "a real number, not text", "date": "a date as yyyy-mm-dd",
               "multi": "a list separated by ; without spaces"}.get(t, "spaces tidied")
        return new, why

    def format_checks(self, rec: dict | None = None):
        """One proposal per reagent whose cells can be tidied; values that can't be are added to ``rec['problems']``."""
        book = self.inv._need_book()
        fields = self._fields()
        key = book.key
        for row in book.rows:
            rid = key_str(row[key])
            changes = []
            for k, v in row.items():
                f = fields.get(k)
                if f is None or k == key or v is None:
                    continue
                try:
                    new, why = self._normal(f, v)
                except ToolError as e:
                    if rec is not None and len(rec["problems"]) < MAX_PROBLEMS:
                        rec["problems"].append({"label_no": rid, "name": self._name(row), "column": k, "label": f["label"], "label_pl": f["label_pl"],
                                                "value": v if isinstance(v, (str, int, float, bool)) else str(v), "problem": str(e)})
                    continue
                if why:
                    changes.append({"label_no": rid, "name": self._name(row), "column": k, "label": f["label"], "label_pl": f["label_pl"], "old": v, "new": new, "why": why})
            if changes:
                yield self._proposal("format", f"label_no {rid} {self._name(row)}: tidy the format of {len(changes)} cell(s)",
                                     "; ".join(dict.fromkeys(c["why"] for c in changes)), changes, {rid: version(row)})

    def producer_spelling(self):
        """A manufacturer written several ways becomes the spelling used most often."""
        book = self.inv._need_book()
        if not any(f"producer_{i}_name" in book.header for i in range(1, N_SLOTS + 1)):
            return
        uses: Counter = Counter()
        for row in book.rows:
            for i in range(1, N_SLOTS + 1):
                v = row.get(f"producer_{i}_name")
                if isinstance(v, str) and v.strip():
                    uses[v] += 1
        groups: dict[str, list[str]] = {}
        for name in uses:
            groups.setdefault(re.sub(r"[^a-z0-9]", "", fold(name)), []).append(name)
        fields = self._fields()
        for spellings in groups.values():
            if len(spellings) < 2:
                continue
            best = sorted(spellings, key=lambda s: (-uses[s], s))[0]
            changes, bases = [], {}
            for row in book.rows:
                rid = key_str(row[book.key])
                for i in range(1, N_SLOTS + 1):
                    k = f"producer_{i}_name"
                    v = row.get(k)
                    if v in spellings and v != best:
                        changes.append({"label_no": rid, "name": self._name(row), "column": k, "label": fields[k]["label"], "label_pl": fields[k]["label_pl"], "old": v, "new": best,
                                        "why": "the spelling used most"})
                        bases[rid] = version(row)
            others = ", ".join(f"“{s}”" for s in spellings if s != best)
            yield self._proposal("spelling", f"Producer {others} → “{best}”", f"the spelling used by {uses[best]} reagent(s)", changes, bases)

    @staticmethod
    def _proposal(kind: str, title: str, why: str, changes: list, bases: dict, note: dict | None = None) -> dict:
        return {"id": "", "kind": kind, "title": title, "why": why, "changes": changes, "bases": bases,
                "note": (note or {}).get("id", ""), "note_text": (note or {}).get("text", "")[:4000], "note_user": (note or {}).get("user", ""),
                "status": "waiting", "error": "", "commit": "", "decided_by": "", "decided_at": None}

    # ---- info from the lab, with the model -----------------------------------------------------------
    def _notes(self, rec: dict, st: dict) -> None:
        # a note sent from a consumable's page is for a person (the tidy-up changes only the reagents)
        notes = [i for i in reversed(self.inv.infos()) if i.get("status") != "done" and not i.get("agent_note") and not i.get("consumable")]
        if not notes:
            self._step(rec, "info from the lab: nothing new")
            return
        if not self.ollama.enabled or not st["model"]:
            self._step(rec, f"info from the lab: {len(notes)} new note(s) wait — choose a model to read them", True)
            return
        try:
            self.ollama.models()
        except ToolError as e:
            self._step(rec, f"info from the lab: {len(notes)} new note(s) wait — the model isn't available", False, str(e))
            return
        before = {p["note"]: p for p in (self.last() or {}).get("proposals", []) if p.get("note") and p.get("status") == "waiting"}
        done = 0
        for note in notes[:MAX_NOTES]:
            if self.progress is not None:
                self.progress["step"] = f"reading note {done + 1} of {min(len(notes), MAX_NOTES)}"
            if note["id"] in before:  # already proposed, still waiting for a person: not asked again
                rec["proposals"].append(dict(before[note["id"]], id=""))
                done += 1
                continue
            try:
                kind, out = self.read_note(note, st["model"])
            except ToolError as e:
                self._step(rec, f"note {note['id']}: the model failed", False, str(e))
                continue
            done += 1
            if kind == "unclear":
                rec["unclear"].append({"note": note["id"], "text": note.get("text", "")[:4000], "user": note.get("user", ""), "question": out})
                if st["apply"] != "none":
                    self.inv.update_info(note["id"], self.author(st["model"]), agent_note=out)
            else:
                rec["proposals"].append(out)
        rest = len(notes) - min(len(notes), MAX_NOTES)
        self._step(rec, f"info from the lab: {done} note(s) read by {st['model']}" + (f", {rest} left for the next run" if rest else ""))

    def _context(self, note: dict) -> str:
        book = self.inv._need_book()
        fields = self._fields()
        key = book.key
        lines = []
        for r in book.rows:
            slots = []
            for i in range(1, N_SLOTS + 1):
                p = f"producer_{i}_"
                if not r.get(p + "name"):
                    continue
                size = " ".join(str(x) for x in (r.get(p + "container_size"), r.get(p + "container_unit")) if x not in (None, ""))
                bits = [str(r.get(p + "name"))] + [str(x) for x in (r.get(p + "catalog_no"), size) if x not in (None, "")]
                if r.get(p + "containers_count") not in (None, ""):
                    bits.append(f"×{r.get(p + 'containers_count')}")
                slots.append(f"{i}: " + " ".join(bits))
            place = " ".join(str(x) for x in (r.get("storage_category_primary"), r.get("storage_exact_location")) if x not in (None, ""))
            lines.append(" | ".join([key_str(r[key]), str(r.get("name_pl") or ""), str(r.get("name_en") or ""), place, "; ".join(slots)])
                         + (" | DISPOSED" if r.get("is_disposed") is True else ""))
        cols = []
        for k, f in fields.items():
            if k == key or (f.get("slot") or 0) > 1:
                continue
            name = f"producer_N_{f['slot_key']}" if f.get("slot") else k
            kind = {"bool": "yes/no", "number": "integer" if f.get("integer") else "number", "date": "date", "choice": "one of",
                    "multi": "list of", "longtext": "text"}.get(f["type"], "text")
            allowed = f" [{';'.join(f['options'])}]" if f.get("options") else ""
            cols.append(f"- {name}: {kind}{allowed} — {f['label']}")
        parts = [f"Today is {_today()}.", "",
                 f"NOTE {note['id']} from {note.get('user') or 'someone'}, {time.strftime('%Y-%m-%d %H:%M', time.localtime(note.get('created') or 0))}:",
                 note.get("text", "")]
        rid = str(note.get("reagent") or "")
        row = book.by_key().get(rid) if rid else None
        if row is not None:
            filled = {k: v for k, v in row.items() if v not in (None, "")}
            parts += ["", f"The note was sent from the page of label_no {rid}. That reagent, every filled cell:",
                      json.dumps(filled, ensure_ascii=False, default=str)]
        parts += ["", f"ALL REAGENTS ({len(lines)}): label_no | name_pl | name_en | storage | producer slots (N: name catalog size ×containers)",
                  *lines, "", "COLUMNS YOU MAY CHANGE:", *cols]
        return "\n".join(parts)

    def _rules(self) -> str:
        """The built-in rules, plus the inventory's own (AGENTS.md, its part about notes from the lab)."""
        p = self.inv.repo / "AGENTS.md"
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return RULES
        m = re.search(r"^##[^\n]*(?:Notes from the lab|info/)[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M | re.I)
        return RULES + ("\n\nThe inventory's own instructions (AGENTS.md):\n" + m.group(1).strip()[:6000] if m else "")

    def read_note(self, note: dict, model: str) -> tuple[str, object]:
        """("note", a proposal) or ("unclear", the question). The model gets a second try when its answer doesn't fit."""
        messages = [{"role": "system", "content": self._rules()}, {"role": "user", "content": self._context(note)}]
        for attempt in (1, 2):
            out = self.ollama.chat(model, messages, NOTE_SCHEMA)
            if not out.get("clear", False):
                return "unclear", _line(out.get("question") or "The model found the note unclear.", 1000)
            changes, bases, errors = self._check_changes(out.get("changes") or [])
            if not errors and changes:
                summary = _line(out.get("summary") or "", 200) or "corrections from a note"
                rids = list(dict.fromkeys(c["label_no"] for c in changes))
                where = ", ".join(f"label_no {r} {next(c['name'] for c in changes if c['label_no'] == r)}" for r in rids[:3])
                return "note", self._proposal("note", f"{where}: {summary}", summary, changes, bases, note)
            if not errors:
                errors = ["no changes — if nothing in the inventory should change, answer clear: false and say why"]
            if attempt == 1:
                messages += [{"role": "assistant", "content": json.dumps(out, ensure_ascii=False)},
                             {"role": "user", "content": "These changes can't be made:\n- " + "\n- ".join(errors[:20])
                              + "\nAnswer again, following the rules. If you aren't sure, answer clear: false."}]
        return "unclear", "The model's corrections didn't fit the inventory: " + "; ".join(errors[:5])

    def _check_changes(self, proposed: list) -> tuple[list, dict, list]:
        book = self.inv._need_book()
        rows = book.by_key()
        fields = self._fields()
        changes, bases, errors = [], {}, []
        for c in proposed[:60]:
            if not isinstance(c, dict):
                continue
            rid, col = key_str(str(c.get("label_no") or "").strip().lstrip("#")), str(c.get("column") or "").strip()
            row = rows.get(rid)
            if row is None:
                errors.append(f"there is no reagent with label_no {rid!r}")
                continue
            f = fields.get(col)
            if f is None or col == book.key:
                errors.append(f"label_no {rid}: there is no column {col!r} that can be changed")
                continue
            raw = c.get("value")
            try:
                new = None if raw is None or (isinstance(raw, str) and not raw.strip()) else convert(f, raw)
            except ToolError as e:
                errors.append(f"label_no {rid}, {col}: {e}")
                continue
            old = row.get(col)
            if new == old and type(new) is type(old):
                continue
            changes.append({"label_no": rid, "name": self._name(row), "column": col, "label": f["label"], "label_pl": f["label_pl"], "old": old, "new": new,
                            "why": _line(c.get("why") or "", 300)})
            bases[rid] = version(row)
        return changes, bases, errors

    # ---- applying -----------------------------------------------------------------------------------
    def _apply(self, p: dict, author: str, proposed_by: str = "") -> dict:
        inv = self.inv
        with inv.lock:
            try:
                rows = inv._need_book().by_key()
                for c in p["changes"]:  # cell by cell, like the sync: other cells of the reagent may have changed
                    row = rows.get(c["label_no"])
                    if row is None:
                        raise ToolError(f"label_no {c['label_no']} is gone.")
                    cur = row.get(c["column"])
                    if cur != c["old"] or type(cur) is not type(c["old"]):
                        raise ToolError(f"Someone changed label_no {c['label_no']}, {c['column']} since this was proposed. Run the tidy-up again.")
                if p["note"]:
                    info = next((i for i in inv.infos() if i.get("id") == p["note"]), None)
                    if info is None or info.get("status") == "done":
                        raise ToolError("That note was dealt with or deleted meanwhile.")
                by_rid: dict[str, dict] = {}
                for c in p["changes"]:
                    by_rid.setdefault(c["label_no"], {})[c["column"]] = c["new"]
                for rid, values in by_rid.items():
                    inv.save(values, author, rid, commit=False)
                if p["note"]:
                    inv.update_info(p["note"], author, status="done", agent_note=f"{self.author('')}: {p['why']}", commit=False)
                cols = ", ".join(dict.fromkeys(c["column"] for c in p["changes"]))
                cols = cols if len(cols) <= 80 else cols[:79] + "…"
                if p["kind"] == "note":
                    subject = f"Info {p['note']} → {_line(p['title'], 70)}"
                elif len(by_rid) == 1:
                    rid = next(iter(by_rid))
                    subject = f"label_no {rid} {p['changes'][0]['name']}: tidy-up of {cols}"
                else:
                    subject = f"Tidy-up: {_line(p['title'], 80)} ({len(by_rid)} reagents)"
                trailers = [f"Reagent: {rid}" for rid in by_rid] + ([f"Info: {p['note']}"] if p["note"] else []) + ["Action: tidy"]
                if proposed_by and proposed_by != author:
                    trailers.append(f"Proposed-by: {proposed_by}")
                p["commit"] = inv.commit(subject, author, trailers) or ""
                p["status"], p["error"] = "applied", ""
            except ToolError as e:
                inv.discard_changes()
                p["status"], p["error"] = "failed", str(e)
            except Exception as e:  # pragma: no cover - keep the folder clean whatever happened
                inv.discard_changes()
                p["status"], p["error"] = "failed", f"{type(e).__name__}: {e}"
            p["decided_by"], p["decided_at"] = author, round(_now())
        return p

    def decide(self, pid: str, action: str, user: str = "") -> dict:
        """A person applies or rejects a waiting proposal of the last run."""
        if action not in ("apply", "reject"):
            raise ToolError("Apply or reject.")
        if self.progress is not None:
            raise ToolError("A tidy-up is running — wait until it's done.")
        rec = self.last()
        p = next((x for x in (rec or {}).get("proposals", []) if x.get("id") == pid), None)
        if p is None:
            raise ToolError("That proposal is gone — a newer tidy-up replaced it.")
        if p["status"] != "waiting":
            raise ToolError("That proposal was already dealt with.")
        who = _line(user, 60) or "Someone without a name"
        if action == "apply":
            self._apply(p, who, self.author(rec.get("model", "")))
        else:
            p["status"], p["decided_by"], p["decided_at"] = "rejected", who, round(_now())
            if p["note"]:  # so the model doesn't propose the same again; the note waits for a person
                try:
                    self.inv.update_info(p["note"], who, agent_note=f"{self.author(rec.get('model', ''))} proposed: {p['why']} — rejected by {who}.")
                except ToolError:
                    pass
        self._save_run(rec)
        return rec

    def apply_all(self, user: str = "") -> dict:
        rec = self.last()
        for p in (rec or {}).get("proposals", []):
            if p.get("status") == "waiting":
                self.decide(p["id"], "apply", user)
        return self.last() or {}
