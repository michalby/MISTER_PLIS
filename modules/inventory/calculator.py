"""From a reagent to the lab's solution calculator: a link that opens the tool with the reagent's name, molar mass and
purity filled in (the base fills a tool's inputs from its address: ``/tool/<id>?<input>=<value>``).

The calculator is a tool from a tool source (by default ``molarity``, "Solution & dilution", in MISTER_PLIS-tools), so
it may not be loaded, and its inputs may change. The link is offered only while the tool has a compound list with
"Other" (``compound``, ``new_name``, ``mw``); purity and density are filled in only if it has them.
"""

from __future__ import annotations

import math
from urllib.parse import quote, urlencode

MOLAR_MASS = "molar_mass_g_mol"  # g/mol
PURITY = "purity_percent"  # % (a mass fraction for a weighed reagent, a volume fraction for a measured liquid)
NEEDS = ("compound", "new_name", "mw")


def _number(v) -> float | None:
    try:
        x = float(str(v).replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None
    return x if x is not None and math.isfinite(x) and x > 0 else None


def _text(x: float) -> str:
    """58.44 as "58.44" (the shortest exact form), 100.0 as "100"."""
    s = repr(x)
    return s[:-2] if s.endswith(".0") else s


class Calculator:
    def __init__(self, registry, tool_id: str):
        self.registry = registry
        self.tool_id = (tool_id or "").strip()

    def link(self, item: dict) -> str:
        """The calculator's address with this reagent filled in, or "" when there is no calculator to open."""
        tool = self.registry.get(self.tool_id) if self.tool_id and self.registry is not None else None
        if tool is None:
            return ""
        have = tool.input_map()
        if not all(n in have for n in NEEDS):
            return ""
        mw = _number(item.get(MOLAR_MASS))
        q = {"compound": "custom", "new_name": str(item.get("_title") or ""), "mw": _text(mw) if mw else ""}
        # the purity and density the page remembers from another reagent must not stay: unknown purity is 100 %
        if "purity" in have:
            p = _number(item.get(PURITY))
            q["purity"] = _text(p) if p and p <= 100 else "100"
        if "density" in have:
            q["density"] = ""
        return f"/tool/{quote(self.tool_id, safe='')}?{urlencode(q)}"
