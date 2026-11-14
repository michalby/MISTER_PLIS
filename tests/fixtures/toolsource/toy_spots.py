"""A toy picture tool: circles placed on an uploaded picture (inputs.ImageSpots, toolkit 1.3), and the mean
brightness inside each. Its suggester offers the picture and a circle on each bright square it finds."""

from __future__ import annotations

import numpy as np
import pandas as pd
from PIL import Image

from mister_plis.toolkit import Tool, ToolError, data_url, inputs as I, outputs as O

tool = Tool(
    id="toy-spots",
    name="Toy spots",
    category="Spectroscopy",
    icon="grid",
    description="Mean brightness inside circles placed on a picture (a test tool).",
    wide=True,
    order=30,
    inputs=[
        I.File("picture", "Picture", accept=".png"),
        I.ImageSpots("spots", "Circles", source="picture", radius=6, refresh_on=("size",)),
        I.Number("size", "Circle radius", default=6, min=1, unit="px"),
    ],
)


def _gray(path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=float)


@tool.suggest("spots")
def suggest(files, params):
    if not files:
        return {}
    a = _gray(files[0].path)
    h, w = a.shape
    r = float(params.get("size") or 6)
    spots = []
    for y in range(0, h, 20):  # the test pictures have bright 10×10 squares on a 20-pixel grid
        for x in range(0, w, 20):
            if a[y:y + 10, x:x + 10].mean() > 128:
                spots.append({"id": f"S{len(spots) + 1}", "x": x + 5, "y": y + 5, "r": r, "sample": "bright",
                              "row": "ABCDEFGH"[y // 20], "col": x // 20 + 1})
    with open(files[0].path, "rb") as f:
        src = data_url(f.read(), "image/png")
    return {"images": [{"label": "Picture", "src": src}], "width": w, "height": h, "spots": spots,
            "grids": [{"group": "", "title": "Squares", "rows": h // 20, "cols": w // 20}],
            "note": f"{len(spots)} bright squares"}


@tool.runner
def run(p, ctx):
    if not p.spots:
        raise ToolError("Place a circle first.")
    a = _gray(p.picture.path)
    yy, xx = np.mgrid[: a.shape[0], : a.shape[1]]
    rows = [{"Circle": s["id"], "Sample": s["sample"], "Mean": a[(xx - s["x"]) ** 2 + (yy - s["y"]) ** 2 <= s["r"] ** 2].mean()}
            for s in p.spots]
    return O.Table(pd.DataFrame(rows), title="Brightness")
