"""A toy calculator: grams to weigh for a molar solution. It has what the base's calculator features need: a live
form, a list the lab can add to (saved with tool_data_file), buttons, units, a label and protocol items."""

from __future__ import annotations

import json

from mister_plis.toolkit import Tool, ToolError, alphabetical_key, fmt, md_escape, tool_data_file, inputs as I, outputs as O
from ._shared import MOLAR, VOLUME

USER_FILE = tool_data_file("toy-calc", "compounds.json")
BUILTIN = {"salt": ("Salt", 58.44), "sugar": ("Sugar", 342.3)}


def saved() -> dict[str, float]:
    try:
        return {str(k): float(v) for k, v in json.loads(USER_FILE.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    USER_FILE.parent.mkdir(parents=True, exist_ok=True)
    USER_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def options():
    items = [(k, f"{name}  ·  {mw:g} g/mol") for k, (name, mw) in BUILTIN.items()]
    items += [(f"user:{n}", f"{n}  ·  {mw:g} g/mol  ★") for n, mw in saved().items()]
    return sorted(items, key=lambda o: alphabetical_key(o[1])) + [("custom", "Other — enter name and molar mass…")]


def save(raw: dict) -> str:
    name = str(raw.get("new_name") or "").strip()
    try:
        mw = float(str(raw.get("mw") or "").replace(",", "."))
    except ValueError:
        mw = 0
    if not name:
        raise ToolError("Type the compound's name first.")
    if mw <= 0:
        raise ToolError("Enter a molar mass greater than zero.")
    _write({**saved(), name: mw})
    return f"Saved {name} — reloading the list…"


def remove(raw: dict) -> str:
    key = str(raw.get("remove_which") or "")
    data = saved()
    if key[5:] not in data:
        raise ToolError("Pick a saved compound to remove.")
    del data[key[5:]]
    _write(data)
    return "Removed — reloading…"


def compound(p) -> tuple[float | None, str]:
    if p.compound.startswith("user:"):
        return saved().get(p.compound[5:]), p.compound[5:]
    if p.compound == "custom":
        return p.mw, p.new_name or "the compound"
    name, mw = BUILTIN.get(p.compound, (p.compound, None))
    return mw, name


tool = Tool(
    id="toy-calc",
    name="Toy solution",
    category="Calculators",
    icon="beaker",
    description="Grams to weigh for a molar solution (a test tool).",
    live=True,
    protocol=True,
    order=10,
    inputs=[
        I.Select("compound", "Compound", options=options, default="salt", sort=True),
        I.Text("new_name", "Name", show_if={"compound": "custom"}),
        I.Number("mw", "Molar mass", default=100, min=0, unit="g/mol", required=False, show_if={"compound": "custom"}),
        I.Button("save", "Save to the compound list", action=save, reload=True, show_if={"compound": "custom"}),
        I.Number("conc", "Concentration", default=150, min=0, units=list(MOLAR), default_unit="mM"),
        I.Number("volume", "Volume", default=500, min=0, units=list(VOLUME), default_unit="mL"),
        I.Section("Saved compounds", collapsed=True),
        I.Select("remove_which", "Saved compound", required=False, options=lambda: [(f"user:{n}", n) for n in saved()] or [("", "— none —")]),
        I.Button("remove", "Remove from the list", action=remove, reload=True),
    ],
)


@tool.runner
def run(p, ctx):
    mw, name = compound(p)
    if not mw:
        raise ToolError("Enter the molar mass.")
    grams = p.conc * MOLAR[p.conc_unit] * p.volume * VOLUME[p.volume_unit] * mw
    return [
        O.Metric("Weigh out", grams, unit="g", highlight=True),
        O.Metric("Concentration", p.conc, unit=p.conc_unit),
        O.Markdown(f"Dissolve **{fmt(grams)} g** of {md_escape(name)} in **{fmt(p.volume)} {p.volume_unit}**."),
    ]


@tool.label
def label(p):
    _, name = compound(p)
    return {"name": "" if name == "the compound" else name, "detail": f"{fmt(p.conc)} {p.conc_unit}"}
