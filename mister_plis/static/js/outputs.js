// Renders the JSON outputs produced by mister_plis/outputs.py.
(function () {
  const { el, icon, bytes } = MP;

  const PALETTE = {
    light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
    dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
  };

  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function isDark() { return css("color-scheme") === "dark"; }

  // Re-skin chart chrome so plots match the page in both light and dark mode.
  function themedLayout(layout) {
    const L = JSON.parse(JSON.stringify(layout || {}));
    const ink2 = css("--ink-2"), grid = css("--grid"), axis = css("--axis"), ink = css("--ink");
    L.paper_bgcolor = "rgba(0,0,0,0)";
    L.plot_bgcolor = "rgba(0,0,0,0)";
    L.font = { ...(L.font || {}), color: ink2, family: getComputedStyle(document.body).fontFamily };
    const [from, to] = isDark() ? [PALETTE.light, PALETTE.dark] : [PALETTE.dark, PALETTE.light];
    L.colorway = (L.colorway || PALETTE.light).map((c) => { const i = from.indexOf(c.toLowerCase()); return i >= 0 ? to[i] : c; });
    L.separators = MP.prefs.decimal === "comma" ? ", " : ". ";  // decimal mark, then thousands
    if (L.title) { L.title = typeof L.title === "string" ? { text: L.title } : L.title; L.title.font = { ...(L.title.font || {}), color: ink }; }
    const axes = Object.keys(L).filter((k) => /^[xy]axis\d*$/.test(k));
    if (!axes.length) axes.push("xaxis", "yaxis");
    for (const k of axes) {
      L[k] = { ...(L[k] || {}), gridcolor: grid, linecolor: axis, tickcolor: axis, zerolinecolor: axis };
    }
    if (L.legend) L.legend.font = { ...(L.legend.font || {}), color: ink2 };
    L.hoverlabel = { ...(L.hoverlabel || {}), bgcolor: css("--surface"), bordercolor: css("--line-2"), font: { color: ink, family: L.font.family } };
    for (const k of axes) if (L[k].showspikes) Object.assign(L[k], { spikecolor: css("--ink-3") });
    if (L.annotations) L.annotations = L.annotations.map((a) => (a.font && a.font.color) ? a : { ...a, font: { ...(a.font || {}), color: ink2 } });
    if (L.template && L.template.layout) {
      delete L.template.layout.paper_bgcolor;
      delete L.template.layout.plot_bgcolor;
    }
    return L;
  }

  function card(title, sub, actions, ...body) {
    const head = (title || sub || (actions && actions.length))
      ? el("div", { class: "out-head" },
          el("div", {}, title ? el("div", { class: "out-title" }, title) : null, sub ? el("div", { class: "out-sub" }, sub) : null),
          el("div", { class: "out-actions" }, actions || []))
      : null;
    return el("div", { class: "out-card" }, head, ...body);
  }

  const dl = (url) => url + (url.includes("?") ? "&" : "?") + "download=1";
  const ext = (name) => (String(name || "").match(/\.([A-Za-z0-9]{1,5})$/) || [])[1] || "";

  const R = {};

  R.html = (o) => el("div", { class: "out-card html-out prose", html: o.html });

  R.text = (o) => card(o.title, null, [el("button", { class: "btn btn-small", type: "button", onclick: async () => { await MP.copy(o.text); MP.toast(MP.t("Copied")); } }, MP.t("Copy"))], el("pre", { class: "text-out" }, o.text));

  R.alert = (o) => el("div", { class: `alert alert-${o.level === "info" ? "" : o.level}`.trim() },
    icon(o.level === "success" ? "check" : "alert", 16), el("div", { html: o.html }));

  R.metric = (o) => {
    // the value was formatted when the job ran; show it with today's decimal separator
    const value = typeof o.raw === "number" ? (MP.prefs.decimal === "comma" ? o.value.replace(".", ",") : o.value.replace(",", ".")) : o.value;
    const m = el("div", { class: "metric" + (o.highlight ? " highlight" : ""), title: MP.t("Click to copy") },
      el("div", { class: "metric-label" }, o.label),
      el("div", { class: "metric-value" }, value, o.unit ? el("span", { class: "unit" }, o.unit) : null),
      o.help ? el("div", { class: "metric-help" }, o.help) : null);
    m.addEventListener("click", async () => {
      await MP.copy(String(MP.num(o.raw)));
      const c = el("span", { class: "copied" }, MP.t("copied"));
      m.append(c); setTimeout(() => c.remove(), 1200);
    });
    return m;
  };

  R.table = (o) => {
    let rows = o.rows.slice();
    let sortCol = -1, sortDir = 1;
    const tbody = el("tbody");
    const headRow = el("tr");
    const ths = o.columns.map((c, i) => {
      const th = el("th", { class: o.numeric[i] ? "num" : "" }, c);
      th.addEventListener("click", () => {
        sortDir = sortCol === i ? -sortDir : 1;
        sortCol = i;
        rows.sort((a, b) => {
          const x = a[i], y = b[i];
          if (x === null) return 1; if (y === null) return -1;
          const nx = parseFloat(x), ny = parseFloat(y);
          const cmp = (!isNaN(nx) && !isNaN(ny)) ? nx - ny : String(x).localeCompare(String(y), undefined, { numeric: true });
          return cmp * sortDir;
        });
        ths.forEach((t, j) => { t.querySelector(".arrow")?.remove(); if (j === i) t.append(el("span", { class: "arrow" }, sortDir > 0 ? "↑" : "↓")); });
        fill();
      });
      return th;
    });
    headRow.append(...ths);
    function fill() {
      tbody.replaceChildren(...rows.map((r) => el("tr", {}, r.map((v, i) =>
        el("td", { class: (o.numeric[i] ? "num" : "") + (v === null ? " null" : ""), title: v === null ? "" : String(MP.num(v)) }, v === null ? "—" : String(MP.num(v)))))));
    }
    fill();
    const shown = o.rows.length;
    const sub = `${MP.tn(o.total_rows, "{n} row", "{n} rows", { n: o.total_rows.toLocaleString(MP.prefs.lang) })} × ${MP.tn(o.columns.length, "{n} column", "{n} columns")}`;
    const actions = [];
    if (o.download) actions.push(MP.exportBtn(ext(o.download.name) || "csv", { href: dl(o.download.url), title: MP.t("Download this table") }));
    return card(o.title || MP.t("Table"), sub, actions,
      el("div", { class: "table-wrap" }, el("table", { class: "data" }, el("thead", {}, headRow), tbody)),
      shown < o.total_rows ? el("div", { class: "table-foot" }, MP.t("Showing the first {n} rows — download the file for all of them.", { n: shown.toLocaleString(MP.prefs.lang) })) : null);
  };

  // ---- per-sample colours: tucked behind a small palette button, remembered per tool in this browser
  const COLOR_KEY = () => `mp:colors:${MP.toolId || "any"}`;
  function savedColors() { try { return JSON.parse(localStorage.getItem(COLOR_KEY()) || "{}"); } catch (_) { return {}; } }
  function saveColors(c) { try { localStorage.setItem(COLOR_KEY(), JSON.stringify(c)); } catch (_) { } }
  function toHex(c) {
    if (!c || typeof c !== "string") return null;
    if (c[0] === "#") return c.length === 4 ? "#" + [...c.slice(1)].map((x) => x + x).join("") : c.slice(0, 7);
    const m = c.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    return m ? "#" + m.slice(1, 4).map((v) => (+v).toString(16).padStart(2, "0")).join("") : null;
  }
  function alphaOf(c) { const m = typeof c === "string" && c.match(/rgba\([^)]*,\s*([\d.]+)\)/); return m ? +m[1] : null; }
  function withAlpha(hex, a) {
    if (a === null) return hex;
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
  }
  function plotGroups(div) {
    const groups = new Map();
    div.data.forEach((t, i) => {
      if (t.type === "heatmap") return;
      const key = t.legendgroup || t.name;
      if (!key) return;
      if (!groups.has(key)) groups.set(key, { idx: [], color: null, label: null });
      const g = groups.get(key);
      g.idx.push(i);
      const full = div._fullData && div._fullData[i];
      if (!g.color && t.type === "mesh3d") g.color = toHex(t.color || (full && full.color));
      if (!g.color) g.color = toHex((t.line && t.line.width !== 0 && t.line.color) || (t.marker && typeof t.marker.color === "string" && t.marker.color) ||
        (full && ((full.line && full.line.width !== 0 && full.line.color) || (full.marker && typeof full.marker.color === "string" && full.marker.color))));
      if (!g.label && t.showlegend !== false && t.name) g.label = t.name;
    });
    for (const [k, g] of groups) g.label = g.label || k;
    return groups;
  }
  function recolor(div, idx, hex) {
    idx.forEach((i) => {
      const t = div.data[i], full = (div._fullData && div._fullData[i]) || {};
      const u = {};
      if (t.type === "mesh3d") { Plotly.restyle(div, { color: hex }, [i]); return; }
      if (t.fill && t.fill !== "none") u.fillcolor = withAlpha(hex, alphaOf(t.fillcolor || full.fillcolor) ?? 0.2);
      const lc = (t.line && t.line.color) || (full.line && full.line.color);
      if (lc && !(t.line && t.line.width === 0)) u["line.color"] = withAlpha(hex, alphaOf(lc));
      const mc = (t.marker && t.marker.color) || (full.marker && full.marker.color);
      if (typeof mc === "string") u["marker.color"] = withAlpha(hex, alphaOf(mc));
      if (t.marker && t.marker.line && t.marker.line.color && t.marker.line.color !== "white") u["marker.line.color"] = hex;
      if (t.error_y && t.error_y.color) u["error_y.color"] = hex;
      if (Object.keys(u).length) Plotly.restyle(div, u, [i]);
    });
  }
  function applySaved(div) {
    const saved = savedColors();
    for (const [k, g] of plotGroups(div)) if (saved[k]) recolor(div, g.idx, saved[k]);
  }
  function colorPanel(div) {
    const panel = el("div", { class: "color-panel" });
    const render = () => {
      const saved = savedColors();
      const rows = [...plotGroups(div)].map(([k, g]) => {
        const input = el("input", { type: "color", value: saved[k] || g.color || "#888888", title: MP.t("Colour of {name}", { name: g.label }) });
        input.addEventListener("input", () => { recolor(div, g.idx, input.value); });
        input.addEventListener("change", () => { const s2 = savedColors(); s2[k] = input.value; saveColors(s2); });
        return el("label", { class: "color-row" }, input, el("span", {}, g.label));
      });
      panel.replaceChildren(
        el("div", { class: "color-head" }, el("span", {}, MP.t("Colours")), el("span", { class: "muted" }, MP.t("remembered for this tool in this browser"))),
        el("div", { class: "color-list" }, rows),
        el("div", { class: "color-foot" },
          el("button", { type: "button", class: "btn btn-small", onclick: () => {
            const s2 = savedColors(); for (const k of plotGroups(div).keys()) delete s2[k]; saveColors(s2);
            MP.toast(MP.t("Colours reset — re-run or reload to see the defaults"));
          } }, MP.t("Reset to defaults"))));
    };
    render();
    return panel;
  }

  R.plot = (o) => {
    const div = el("div", { class: "plot" });
    if (o.height) div.style.height = o.height + "px";
    const name = (o.title || "plot").replace(/[^\w.-]+/g, "_");
    let panel = null;
    const box = el("div", { class: "plot-box" }, div);
    const colorBtn = el("button", { class: "icon-btn icon-btn-sm", type: "button", hidden: true, title: MP.t("Change sample colours"), onclick: () => {
      if (panel) { panel.remove(); panel = null; colorBtn.classList.remove("on"); return; }
      panel = colorPanel(div); box.before(panel); colorBtn.classList.add("on");
    } }, icon("palette", 16));
    const actions = [
      colorBtn,
      MP.exportBtn("png", { onclick: () => Plotly.downloadImage(div, { format: "png", scale: +MP.prefs.plot_scale || 3, filename: name }) }),
      MP.exportBtn("svg", { onclick: () => Plotly.downloadImage(div, { format: "svg", filename: name }) }),
    ];
    const c = card(o.title, null, actions, box);
    const draw = () => {
      if (!window.Plotly) return setTimeout(draw, 50);
      const fig = o.figure;
      div._mpLayout = fig.layout;  // re-skinned when the theme changes
      Plotly.newPlot(div, fig.data, themedLayout(fig.layout), {
        responsive: true, displaylogo: false,
        toImageButtonOptions: { format: "png", scale: +MP.prefs.plot_scale || 3, filename: name },
        modeBarButtonsToRemove: ["lasso2d", "select2d"],
      }).then(() => { applySaved(div); colorBtn.hidden = !plotGroups(div).size; });
    };
    requestAnimationFrame(draw);
    return c;
  };

  R.image = (o) => el("div", { class: "out-card img-card" },
    o.title ? el("div", { class: "out-head" }, el("div", { class: "out-title" }, o.title)) : null,
    el("a", { class: "img-frame", href: o.url, target: "_blank" }, el("img", { src: o.url, alt: o.caption || o.name, loading: "lazy" })),
    el("div", { class: "img-meta" },
      el("span", { class: "fname", title: o.name }, o.caption || o.name),
      el("span", { class: "muted" }, bytes(o.size)),
      MP.exportBtn(ext(o.name), { href: dl(o.url) })));

  R.file = (o) => el("div", { class: "out-card file-out" + (o.primary ? " primary" : "") },
    el("span", { class: "tile" }, icon(o.primary ? "download" : "file", 18)),
    el("div", { class: "grow" },
      el("div", { class: "fname", title: o.name }, o.label),
      el("div", { class: "fdesc" }, [o.description, o.label !== o.name ? o.name : null, bytes(o.size)].filter(Boolean).join(" · "))),
    el("a", { class: "btn" + (o.primary ? " btn-primary" : ""), href: o.url + "?download=1" }, icon("download", 16), MP.t("Download")));

  R.video = (o) => card(o.title, `${o.name} · ${bytes(o.size)}`, [MP.exportBtn(ext(o.name), { href: dl(o.url) })],
    el("div", { class: "plot-box" }, el("video", { src: o.url, controls: true, loop: true, playsinline: true, style: "width:100%;border-radius:8px;display:block" })));

  // A chart as a PNG for paper: light colours whatever the theme, the sample colours as chosen on the page.
  MP.chartPNG = async function (div) {
    if (!window.Plotly || !div.data) return null;
    const layout = JSON.parse(JSON.stringify(div._mpLayout || {}));
    const width = 1100;
    const height = Math.max(380, Math.min(1000, Math.round(width * (div.clientHeight || 450) / (div.clientWidth || width))));
    Object.assign(layout, { paper_bgcolor: "#ffffff", plot_bgcolor: "#ffffff", width, height, autosize: false });
    layout.separators = MP.prefs.decimal === "comma" ? ", " : ". ";
    try { return await Plotly.toImage({ data: div.data, layout }, { format: "png", width, height, scale: 2 }); }
    catch (_) { return null; }
  };

  // Theme switched: redraw the chart chrome in the new colours (sample colours stay as they are).
  document.addEventListener("mp:theme", () => {
    if (!window.Plotly) return;
    MP.$$(".plot").forEach((div) => { if (div._mpLayout && div.data) Plotly.react(div, div.data, themedLayout(div._mpLayout)); });
  });

  // Groups consecutive metrics / images into grids. skip: indexes not to draw (the workbook, shown as a button).
  MP.renderOutputs = function (container, outputs, { skip } = {}) {
    const nodes = [];
    let group = null, groupKind = null;
    for (const [index, o] of outputs.entries()) {
      if (skip && skip.has(index)) continue;
      const r = R[o.kind];
      if (!r) { nodes.push(R.text({ text: JSON.stringify(o, null, 2), title: MP.t("Unknown output “{kind}”", { kind: o.kind }) })); continue; }
      const node = r(o);
      const plot = o.kind === "plot" && node.querySelector(".plot");
      if (plot) plot.dataset.out = index;  // the whole-result PDF sends this chart along under its index
      if (o.kind === "metric" || o.kind === "image") {
        if (groupKind !== o.kind) {
          group = el("div", { class: o.kind === "metric" ? "metrics" : "gallery" });
          groupKind = o.kind;
          nodes.push(group);
        }
        group.append(node);
      } else {
        groupKind = null;
        nodes.push(node);
      }
    }
    nodes.forEach((n) => { if (n.classList?.contains("gallery") && n.children.length === 1) n.classList.add("single"); });
    container.append(...nodes);
  };

  // ---- the buttons above a finished result, the same on the tool's page, an old job's page and Time Machine

  MP.askName = async function () {
    if (MP.prefs.name) return;
    const name = await MP.ask(MP.t("Your name, to put on the printout (change it any time in Settings):"), "", { maxlength: 60 });
    if (name && name.trim()) MP.setPref("name", name.trim().replace(/\s+/g, " ").slice(0, 60));
  };

  // The whole result as one PDF. Charts are drawn here, in the browser, and posted along so they're on paper too.
  async function openReport(e, url) {
    const plots = MP.$$(".plot[data-out]").filter((d) => d.data);
    if (!MP.prefs.name) {  // ask first, then open it ourselves: the dialog's OK is a click too
      e.preventDefault();
      await MP.askName();
      if (!plots.length) { window.open(url, "_blank", "noopener"); return; }
    } else if (!plots.length) return;  // nothing to draw: the plain link does it
    else e.preventDefault();
    const name = `mp-pdf-${Date.now()}`;
    const win = window.open("", name);  // opened now, while it still counts as the click
    if (win) win.document.body.innerHTML = '<p style="font:15px -apple-system,system-ui,sans-serif;padding:2em;color:#555">' + MP.t("Preparing the PDF…") + "</p>";
    const charts = {};
    for (const div of plots) {
      const png = await MP.chartPNG(div);
      if (png) charts[div.dataset.out] = png;
    }
    const f = el("form", { method: "post", action: url, target: win ? name : "_self", enctype: "multipart/form-data", hidden: true },
      el("input", { type: "hidden", name: "charts", value: JSON.stringify(charts) }));
    document.body.append(f);
    f.submit();
    f.remove();
  }

  // The tool's workbook (a primary .xlsx file) of a result that also has something to read: shown as an "Excel"
  // button next to "PDF" instead of a card of its own. -1 if there is none.
  MP.workbookIndex = function (job) {
    if (!job || !job.report) return -1;
    return (job.outputs || []).findIndex((o) => o.kind === "file" && o.primary && /\.xlsx$/i.test(o.name || ""));
  };

  // "PDF" (everything on the page, printable) and "Excel" (the tool's workbook, if it makes one).
  MP.resultExports = function (job) {
    const nodes = [];
    if (job.report) nodes.push(MP.exportBtn("pdf", { href: job.report, onclick: (e) => openReport(e, job.report),
      title: MP.t("The whole result — settings, numbers, tables and charts — as one printable PDF") }));
    const wb = MP.workbookIndex(job);
    if (wb >= 0) {
      const o = job.outputs[wb];
      nodes.push(MP.exportBtn("xlsx", { href: dl(o.url), title: [o.label, o.description, o.name].filter(Boolean).join(" · ") }));
    }
    return nodes;
  };

  // A result's buttons, kept together on the right, also when they wrap under the status in a narrow column.
  MP.resultButtons = (...nodes) => el("div", { class: "result-buttons" }, ...nodes.flat().filter(Boolean));

  MP.renderError = function (job) {
    return el("div", { class: "out-card error-card" },
      el("div", { class: "out-head" }, el("div", { class: "out-title" }, MP.t(job.status === "interrupted" ? "Interrupted" : "Something went wrong"))),
      el("div", { class: "err-msg" }, job.error || MP.t("Unknown error")),
      job.traceback ? el("details", {}, el("summary", { class: "muted" }, MP.t("Technical details")), el("pre", {}, job.traceback)) : null);
  };
})();
