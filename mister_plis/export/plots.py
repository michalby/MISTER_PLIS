"""Every plot of a job as an interactive page that works offline (``plots/NN_<title>.html`` next to one shared
``plots/plotly.min.js``), and as ``.png`` when the optional ``kaleido`` package (which needs Chrome) is installed."""

from __future__ import annotations

import shutil
from pathlib import Path

from . import slug


def _png_available() -> bool:
    try:
        import kaleido  # noqa: F401
    except Exception:
        return False
    return True


def write(rec: dict, dest: Path) -> dict[int, dict]:
    import plotly
    import plotly.io as pio

    found = [(i, o) for i, o in enumerate(rec.get("outputs") or [])
             if isinstance(o, dict) and o.get("kind") == "plot" and isinstance(o.get("figure"), dict)]
    if not found:
        return {}
    folder = dest / "plots"
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(plotly.__file__).parent / "package_data" / "plotly.min.js", folder / "plotly.min.js")
    png = _png_available()
    out = {}
    for i, o in found:
        title = o.get("title") or ((o["figure"].get("layout") or {}).get("title") or {}).get("text") or "Plot"
        stem = f"{i + 1:02d}_{slug(title)}"
        fig = o["figure"]
        html = pio.to_html(fig, include_plotlyjs="directory", full_html=True, config={"displaylogo": False})
        (folder / f"{stem}.html").write_text(html.replace("<head>", f"<head><title>{_escape(title)}</title>", 1), encoding="utf-8")
        entry = {"title": title, "html": f"plots/{stem}.html", "png": None}
        if png:
            try:
                height = o.get("height") or (fig.get("layout") or {}).get("height") or 600
                (folder / f"{stem}.png").write_bytes(pio.to_image(fig, format="png", width=1200, height=int(height), scale=2))
                entry["png"] = f"plots/{stem}.png"
            except Exception:  # Chrome missing or the export failing must not stop a backup
                pass
        out[i] = entry
    return out


def _escape(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
