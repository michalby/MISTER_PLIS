"""House style for plotly figures. Imported by the toolkit, so every tool's figures use it.

The browser re-skins chart chrome (ink, gridlines, palette) for dark mode, so keep colors
in the layout to ``colorway`` rather than hard-coding them on traces where possible.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# Validated colorblind-safe categorical order (light surface). Use in this order; past
# ~8 series, fold into "Other" or facet instead of inventing colors.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIVERGING = [[0, "#2a78d6"], [0.5, "#f0efec"], [1, "#e34948"]]

_axis = dict(
    showgrid=True,
    gridcolor="#e1e0d9",
    gridwidth=1,
    zeroline=False,
    showline=True,
    linecolor="#c3c2b7",
    ticks="outside",
    tickcolor="#c3c2b7",
    ticklen=4,
    title=dict(standoff=10),
    automargin=True,
)

pio.templates["mister"] = go.layout.Template(
    layout=dict(
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', size=13, color="#52514e"),
        colorway=PALETTE,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=56, r=24, t=48, b=48),
        hovermode="closest",
        hoverlabel=dict(font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif')),
        legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0),
        title=dict(x=0, xanchor="left", font=dict(size=15, color="#0b0b0b")),
        xaxis=_axis,
        yaxis=_axis,
        colorscale=dict(sequential=[[i / (len(SEQUENTIAL) - 1), c] for i, c in enumerate(SEQUENTIAL)], diverging=DIVERGING),
    ),
    data=dict(
        scatter=[go.Scatter(line=dict(width=2), marker=dict(size=8, line=dict(width=1, color="rgba(255,255,255,0.8)")))],
        bar=[go.Bar(marker=dict(line=dict(width=0)))],
    ),
)
pio.templates.default = "mister"
