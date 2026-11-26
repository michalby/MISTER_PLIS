// Rich form inputs: SampleTable (arrange uploaded files into samples), PlateLayout (96-well map) and ImageSpots
// (circles placed and named on a picture).
(function () {
  const { el, icon, api } = MP;
  MP.widgets = {};

  // ---------------------------------------------------------------- SampleTable
  MP.widgets.samples = function (inp, ctx) {
    let rows = [];
    let status = "";
    let sel = null;        // cells picked in one text/number column: { key, from, to } (row indexes)
    let dragging = false;
    let boxes = {};        // column key → the row inputs, to mirror edits made to a selection
    const editable = inp.columns.filter((c) => !["readonly", "image"].includes(c.kind)).map((c) => c.key);
    const info = el("div", { class: "st-info" });
    const scroll = el("div", { class: "st-scroll" });
    const wrap = el("div", { class: "sample-table" }, info, scroll);
    const node = ctx.fieldShell(inp, wrap);

    const selRows = () => sel ? [Math.min(sel.from, sel.to), Math.max(sel.from, sel.to)] : null;
    const inSel = (ri, key) => { const r = selRows(); return !!r && sel.key === key && ri >= r[0] && ri <= r[1] && r[0] !== r[1]; };

    function paintSel() {
      Object.entries(boxes).forEach(([key, list]) => list.forEach((b, ri) => b.closest("td").classList.toggle("st-sel", inSel(ri, key))));
      showInfo();
    }

    function clearSel() { if (sel) { sel = null; paintSel(); } }

    // Text / number cells: a click selects the whole text (easy to paste over); dragging down a column, or
    // shift-clicking, picks several cells and whatever is typed or pasted goes into all of them.
    function textCell(row, c, ri, v) {
      const i = el("input", { type: c.kind === "number" ? "number" : "text", step: "any", value: v ?? "" });
      (boxes[c.key] ||= [])[ri] = i;
      i.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        if (e.shiftKey && sel && sel.key === c.key) sel.to = ri;
        else { sel = { key: c.key, from: ri, to: ri }; dragging = true; }
        if (document.activeElement !== i || e.shiftKey || inSel(ri, c.key)) { e.preventDefault(); i.focus(); i.select(); }
        paintSel();
      });
      i.addEventListener("mouseenter", () => {
        if (!dragging || !sel || sel.key !== c.key || sel.to === ri) return;
        sel.to = ri;
        window.getSelection()?.removeAllRanges();
        i.focus();
        i.select();
        paintSel();
      });
      i.addEventListener("input", () => {
        const r = selRows();
        const targets = inSel(ri, c.key) ? rows.slice(r[0], r[1] + 1) : [row];
        targets.forEach((t) => { t[c.key] = i.value; });
        if (targets.length > 1) boxes[c.key].slice(r[0], r[1] + 1).forEach((b) => { if (b !== i) b.value = i.value; });
        dimRows();
        ctx.onChange();
      });
      i.addEventListener("keydown", (e) => { if (e.key === "Escape") clearSel(); });
      return i;
    }

    function cell(row, c, ri) {
      const v = row[c.key];
      const set = (val) => { row[c.key] = val; dimRows(); ctx.onChange(); };
      if (c.kind === "readonly") return el("span", { class: "st-ro", title: v ?? "" }, v ?? "");
      if (c.kind === "image") return v ? el("img", { src: v, class: "st-img", alt: "" }) : el("span", { class: "muted" }, "—");
      if (c.kind === "checkbox") {
        const cb = el("input", { type: "checkbox" });
        cb.checked = !!v;
        cb.addEventListener("change", () => set(cb.checked));
        return cb;
      }
      if (c.kind === "select") {
        // Like text cells: shift-click picks a run of cells in the column; changing one of them changes them all.
        const s = el("select", {}, c.options.map(([val, lab]) => el("option", { value: val }, lab)));
        s.value = v ?? "";
        (boxes[c.key] ||= [])[ri] = s;
        s.addEventListener("mousedown", (e) => {
          if (e.button !== 0) return;
          if (e.shiftKey && sel && sel.key === c.key) { e.preventDefault(); sel.to = ri; s.focus(); }
          else if (!inSel(ri, c.key)) sel = { key: c.key, from: ri, to: ri };
          paintSel();
        });
        s.addEventListener("change", () => {
          const r = selRows();
          const targets = inSel(ri, c.key) ? rows.slice(r[0], r[1] + 1) : [row];
          targets.forEach((t) => { t[c.key] = s.value; });
          if (targets.length > 1) boxes[c.key].slice(r[0], r[1] + 1).forEach((b) => { b.value = s.value; });
          dimRows();
          ctx.onChange();
        });
        s.addEventListener("keydown", (e) => { if (e.key === "Escape") clearSel(); });
        return s;
      }
      return textCell(row, c, ri, v);
    }

    // A dropdown column's title opens its choices; the one picked goes into every row
    // (or only the selected cells of that column, when some are selected).
    let menu = null;
    function closeMenu() { if (menu) { menu.remove(); menu = null; } }
    document.addEventListener("pointerdown", (e) => { if (menu && !menu.contains(e.target)) closeMenu(); });
    window.addEventListener("scroll", closeMenu, true);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
    function pickFor(c, button) {
      closeMenu();
      const r = sel && sel.key === c.key && sel.from !== sel.to ? selRows() : null;
      const target = r ? rows.slice(r[0], r[1] + 1) : rows;
      menu = el("div", { class: "st-menu", role: "menu" },
        el("div", { class: "st-menu-head" }, r ? MP.tn(target.length, "Set for the {n} selected row", "Set for the {n} selected rows")
                                               : MP.tn(target.length, "Set for the {n} row", "Set for all {n} rows")),
        c.options.map(([val, lab]) => el("button", { type: "button", role: "menuitem", onclick: () => {
          target.forEach((t) => { t[c.key] = val; });
          closeMenu();
          render();
          ctx.onChange();
        } }, lab)));
      const box = button.getBoundingClientRect();  // on the page, so the table's scroll box can't clip it
      menu.style.left = `${Math.max(8, Math.min(box.left, window.innerWidth - 220))}px`;
      menu.style.top = `${box.bottom + 6}px`;
      document.body.append(menu);
      menu.querySelector("button[role=menuitem]")?.focus();
    }

    async function setAll(c, button) {
      if (!rows.length) return;
      if (c.kind === "select") { pickFor(c, button); return; }
      let val;
      if (c.kind === "checkbox") val = !rows.every((r) => r[c.key]);
      else {
        const hint = c.kind === "select" ? `\n(${c.options.map((o) => o[0]).join(", ")})` : "";
        val = await MP.ask(MP.tn(rows.length, "Set “{label}” for the {n} row to:", "Set “{label}” for all {n} rows to:", { label: c.label }) + hint, rows[0][c.key] ?? "");
        if (val === null) return;
        if (c.kind === "select" && !c.options.some((o) => String(o[0]) === val)) { MP.toast(MP.t("Not one of the options")); return; }
      }
      rows.forEach((r) => { r[c.key] = val; });
      render();
      ctx.onChange();
    }

    function dimRows() {
      scroll.querySelectorAll("tbody tr").forEach((tr, i) => {
        const r = rows[i];
        tr.classList.toggle("dim", !!r && (r.role === "ignore" || r.include === false));
        tr.classList.toggle("is-blank", !!r && (r.role === "blank" || r.role === "background"));
      });
    }

    function showInfo() {
      const r = selRows();
      info.replaceChildren(status === "loading"
        ? el("span", {}, el("span", { class: "spinner", style: "width:13px;height:13px" }), " " + MP.t("Reading files…"))
        : status ? el("span", { class: "field-error" }, status)
        : r && r[0] !== r[1] ? el("span", {}, el("b", {}, MP.tn(r[1] - r[0] + 1, "{n} cell selected", "{n} cells selected")), " — " + MP.t("type or paste to change them all · Esc to cancel"))
        : rows.length ? el("span", {}, MP.tn(rows.length, "{n} row", "{n} rows") + " — " + MP.t("edit any cell; drag down a column (or shift-click) to change several at once; click a column title to set it for every row."))
        : el("span", { class: "muted" }, MP.t("Upload files — they'll be listed here to arrange.")));
    }

    function render() {
      sel = null;
      showInfo();
      if (!rows.length) { scroll.replaceChildren(); return; }
      const head = el("tr", {}, inp.columns.map((c) => {
        const canSet = !["readonly", "image"].includes(c.kind);
        return el("th", { style: c.width ? `width:${c.width}px` : null, title: c.help || (canSet ? MP.t("Set for all rows") : "") },
          canSet ? el("button", { type: "button", class: "st-head", onclick: (e) => setAll(c, e.currentTarget) }, c.label) : c.label);
      }));
      boxes = {};
      const body = rows.map((r, ri) => el("tr", {}, inp.columns.map((c) => el("td", { class: `st-${c.kind}` }, cell(r, c, ri)))));
      scroll.replaceChildren(el("table", { class: "st" }, el("thead", {}, head), el("tbody", {}, body)));
      dimRows();
    }

    let seq = 0;              // only the latest request may fill the table (they can finish out of order)
    let resetLater = false;   // a reset asked for while files were still uploading
    async function refresh(reset = false) {
      const src = ctx.fields[inp.source];
      const me = ++seq;
      // mid-upload: wait — the source fires files-changed (→ refresh) once the whole batch is in
      if (src && src.busy && src.busy()) { resetLater ||= reset; status = "loading"; showInfo(); return; }
      reset ||= resetLater;
      resetLater = false;
      const ids = src ? src.get() : [];
      if (!ids.length) { rows = []; status = ""; render(); ctx.onChange(); return; }
      status = "loading";
      render();
      try {
        const d = await api(`/api/tools/${ctx.spec.id}/suggest/${inp.name}`, { json: { files: ids, params: ctx.values() } });
        if (me !== seq) return;
        const old = new Map(reset ? [] : rows.map((r) => [r.key, r]));
        rows = d.result.map((r) => {
          const o = old.get(r.key);
          if (!o) return r;
          const keep = {};
          editable.forEach((k) => { if (k in o) keep[k] = o[k]; });
          return { ...r, ...keep };
        });
        status = "";
      } catch (e) {
        if (me !== seq) return;
        status = e.message;
      }
      render();
      ctx.onChange();
    }

    document.addEventListener("mouseup", () => { dragging = false; });
    document.addEventListener("mousedown", (e) => { if (!scroll.contains(e.target)) clearSel(); });

    render();
    return {
      node, refresh,
      get: () => rows.map((r) => {
        const out = {};
        for (const [k, v] of Object.entries(r)) if (!(typeof v === "string" && v.startsWith("data:"))) out[k] = v;
        return out;
      }),
      set: (v) => { if (Array.isArray(v) && v.length) { rows = v.map((r) => ({ ...r })); render(); } },
    };
  };

  // ---------------------------------------------------------------- PlateLayout
  const ROW_NAMES = "ABCDEFGHIJKLMNOP";

  MP.widgets.plate = function (inp, ctx) {
    const R = inp.rows, C = inp.cols;
    let wells = {};
    let measured = {};
    let selected = new Set();
    let anchor = null, dragging = false, dragStart = null;
    const PRESETS = `mp:plate:${ctx.spec.id}:${inp.name}`;
    const id = (r, c) => `${ROW_NAMES[r]}${c + 1}`;
    const pos = (w) => [ROW_NAMES.indexOf(w[0]), parseInt(w.slice(1), 10) - 1];

    const grid = el("div", { class: "plate", style: `grid-template-columns: 26px repeat(${C}, minmax(40px, 1fr))` });
    const cells = {};
    grid.append(el("button", { type: "button", class: "plate-corner", title: MP.t("Select all"), onclick: () => { selectRect(0, 0, R - 1, C - 1); } }, "◢"));
    for (let c = 0; c < C; c++) grid.append(el("button", { type: "button", class: "plate-head", onclick: (e) => selectRect(0, c, R - 1, c, e.metaKey || e.ctrlKey) }, String(c + 1)));
    for (let r = 0; r < R; r++) {
      grid.append(el("button", { type: "button", class: "plate-head", onclick: (e) => selectRect(r, 0, r, C - 1, e.metaKey || e.ctrlKey) }, ROW_NAMES[r]));
      for (let c = 0; c < C; c++) {
        const w = id(r, c);
        const cellNode = el("div", { class: "well", dataset: { well: w } });
        cellNode.addEventListener("mousedown", (e) => {
          e.preventDefault();
          if (e.shiftKey && anchor) { const [ar, ac] = pos(anchor); selectRect(ar, ac, r, c); return; }
          if (e.metaKey || e.ctrlKey) { selected.has(w) ? selected.delete(w) : selected.add(w); anchor = w; paint(); return; }
          dragging = true; dragStart = [r, c]; anchor = w; selectRect(r, c, r, c);
        });
        cellNode.addEventListener("mouseenter", () => { if (dragging) selectRect(dragStart[0], dragStart[1], r, c); });
        cells[w] = cellNode;
        grid.append(cellNode);
      }
    }
    document.addEventListener("mouseup", () => { dragging = false; });

    function selectRect(r0, c0, r1, c1, add = false) {
      if (!add) selected = new Set();
      for (let r = Math.min(r0, r1); r <= Math.max(r0, r1); r++)
        for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++) selected.add(id(r, c));
      paint();
    }

    // name → tone so replicates share a colour
    const toneOf = (name) => 1 + ([...String(name)].reduce((a, ch) => a + ch.charCodeAt(0), 0) % 5);
    const short = (v) => { const n = Number(v); return Math.abs(n) >= 1e5 ? n.toExponential(1) : String(+n.toPrecision(5)); };

    function paint() {
      for (const [w, node] of Object.entries(cells)) {
        const info = wells[w];
        node.className = "well" + (selected.has(w) ? " sel" : "") + (info ? ` role-${info.role}` : "") + (info && info.role === "sample" ? ` tone-${toneOf(info.name)}` : "");
        const label = !info ? "" : info.role === "blank" ? MP.t("blank") : info.role === "standard" ? short(info.value) : info.name;
        const dil = info && info.role === "sample" && info.dilution && info.dilution !== 1 ? `×${short(info.dilution)}` : "";
        const m = measured[w];
        node.replaceChildren(...[el("span", { class: "wl" }, label), dil ? el("span", { class: "wd" }, dil) : null,
          m !== undefined && m !== null ? el("span", { class: "wv" }, (+m).toFixed(3)) : null].filter(Boolean));
        node.title = `${w}${label ? " · " + label : ""}${dil ? " " + dil : ""}${m != null ? " · A " + m : ""}`;
      }
      selInfo.textContent = selected.size ? MP.t("Wells selected: {n}", { n: selected.size }) : MP.t("Drag across wells (or click row/column labels) to select");
      const counts = { blank: 0, standard: 0, sample: 0 };
      Object.values(wells).forEach((i) => counts[i.role]++);
      const samples = new Set(Object.values(wells).filter((i) => i.role === "sample").map((i) => i.name));
      summary.textContent = MP.t("{blank} blank · {standard} standard · {sample} sample wells ({samples} samples)", { blank: counts.blank, standard: counts.standard, sample: counts.sample, samples: samples.size });
    }

    // ---- assignment controls
    let role = "standard";
    const roleSeg = el("div", { class: "seg" }, [["blank", "Blank"], ["standard", "Standard"], ["sample", "Sample"], ["empty", "Clear"]].map(([r, l]) =>
      el("button", { type: "button", class: r === role ? "active" : "", dataset: { role: r }, onclick: () => { role = r; syncRole(); } }, MP.t(l))));
    const valIn = el("input", { type: "text", placeholder: MP.t("e.g. 2000, 1000, 500, 250, 125, 62.5, 0") });
    const nameIn = el("input", { type: "text" });
    const dilIn = el("input", { type: "text", value: "1", placeholder: MP.t("1  or  1, 2, 4, 8") });
    const dirSel = el("select", {}, el("option", { value: "rows" }, MP.t("one per row (A, B, C…)")), el("option", { value: "cols" }, MP.t("one per column (1, 2, 3…)")));
    const dilDir = el("select", {}, el("option", { value: "rows" }, MP.t("down the rows")), el("option", { value: "cols" }, MP.t("across the columns")));
    const seriesBtn = el("button", { type: "button", class: "btn btn-small", title: MP.t("Fill in a two-fold series for the selected rows/columns"), onclick: () => {
      const n = selected.size ? groupsBy(dilDir.value).length : 4;
      dilIn.value = Array.from({ length: n }, (_, i) => 2 ** i).join(", ");
    } }, MP.t("×2 series"));
    const valBox = el("label", { class: "pl-field" }, el("span", {}, inp.unit ? `${MP.t("Concentration")} (${inp.unit})` : MP.t("Concentration")), el("div", { class: "control" }, valIn));
    const nameBox = el("label", { class: "pl-field" }, el("span", {}, MP.t("Sample name(s)")), el("div", { class: "control" }, nameIn));
    const dilBox = el("div", { class: "pl-field pl-dil" }, el("span", {}, MP.t("Dilution ×")), el("div", { class: "pl-inline" }, el("div", { class: "control" }, dilIn), seriesBtn));
    const dilDirBox = el("label", { class: "pl-field pl-mid" }, el("span", {}, MP.t("Several dilutions go")), el("div", { class: "control" }, dilDir));
    const dirBox = el("label", { class: "pl-field pl-mid" }, el("span", {}, MP.t("Several values →")), el("div", { class: "control" }, dirSel));
    const applyBtn = el("button", { type: "button", class: "btn btn-primary btn-small", onclick: apply }, MP.t("Apply to selection"));
    const selInfo = el("span", { class: "muted" });
    const summary = el("span", { class: "muted" });

    function syncRole() {
      roleSeg.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.role === role));
      valBox.hidden = role !== "standard";
      nameBox.hidden = dilBox.hidden = dilDirBox.hidden = role !== "sample";
      dirBox.hidden = !(role === "standard" || role === "sample");
    }

    function groupsBy(dir) {
      // selected wells grouped by row or column, in plate order
      const by = new Map();
      [...selected].sort((a, b) => { const [ra, ca] = pos(a), [rb, cb] = pos(b); return dir === "rows" ? ra - rb || ca - cb : ca - cb || ra - rb; })
        .forEach((w) => { const [r, c] = pos(w); const k = dir === "rows" ? r : c; if (!by.has(k)) by.set(k, []); by.get(k).push(w); });
      return [...by.values()];
    }
    const groups = () => groupsBy(dirSel.value);
    const splitList = (text) => text.split(/[,;\t]+/).map((x) => x.trim()).filter(Boolean);
    function indexIn(gs) { const m = new Map(); gs.forEach((g, i) => g.forEach((w) => m.set(w, i))); return m; }

    function apply() {
      if (!selected.size) { MP.toast(MP.t("Select wells first")); return; }
      if (role === "empty") { selected.forEach((w) => delete wells[w]); }
      else if (role === "blank") { selected.forEach((w) => { wells[w] = { role: "blank" }; }); }
      else {
        const raw = splitList(role === "standard" ? valIn.value : nameIn.value);
        if (!raw.length) { MP.toast(MP.t(role === "standard" ? "Enter a concentration" : "Enter a sample name")); return; }
        if (role === "standard" && raw.some((v) => isNaN(parseFloat(v.replace(",", "."))))) { MP.toast(MP.t("Concentrations must be numbers")); return; }
        const gs = groups();
        if (raw.length > 1 && raw.length !== gs.length) { MP.toast(MP.t(dirSel.value === "rows" ? "{a} values, but the selection has {b} rows" : "{a} values, but the selection has {b} columns", { a: raw.length, b: gs.length })); return; }
        let dils = [1], dIdx = null;
        if (role === "sample") {
          dils = splitList(dilIn.value || "1").map((d) => parseFloat(d.replace(",", ".")));
          if (dils.some((d) => !(d > 0))) { MP.toast(MP.t("Dilutions must be positive numbers")); return; }
          if (dils.length > 1) {
            const dg = groupsBy(dilDir.value);
            if (dils.length !== dg.length) { MP.toast(MP.t(dilDir.value === "rows" ? "{a} dilutions, but the selection has {b} rows" : "{a} dilutions, but the selection has {b} columns", { a: dils.length, b: dg.length })); return; }
            dIdx = indexIn(dg);
          }
        }
        const nIdx = indexIn(gs);
        for (const w of selected) {
          const v = raw[raw.length === 1 ? 0 : nIdx.get(w)];
          wells[w] = role === "standard" ? { role, value: parseFloat(v.replace(",", ".")) }
            : { role, name: v, dilution: dils[dIdx ? dIdx.get(w) : 0] };
        }
      }
      selected = new Set();
      paint();
      ctx.onChange();
    }

    // ---- presets (saved in this browser)
    const presetSel = el("select", { class: "pl-preset" });
    function loadPresets() { try { return JSON.parse(localStorage.getItem(PRESETS) || "{}"); } catch (_) { return {}; } }
    function refreshPresets() {
      const p = loadPresets();
      presetSel.replaceChildren(el("option", { value: "" }, MP.t("Load a saved layout…")), ...Object.keys(p).sort().map((n) => el("option", { value: n }, n)));
    }
    presetSel.addEventListener("change", () => {
      const p = loadPresets()[presetSel.value];
      if (p) { wells = JSON.parse(JSON.stringify(p)); paint(); ctx.onChange(); }
      presetSel.value = "";
    });
    const saveBtn = el("button", { type: "button", class: "btn btn-small", onclick: async () => {
      const n = (await MP.ask(MP.t("Name for this layout:")))?.trim(); if (!n) return;
      const p = loadPresets(); p[n] = wells;
      try { localStorage.setItem(PRESETS, JSON.stringify(p)); MP.toast(MP.t("Layout saved in this browser")); } catch (_) { MP.toast(MP.t("Could not save")); }
      refreshPresets();
    } }, MP.t("Save layout"));
    const clearBtn = el("button", { type: "button", class: "btn btn-small", onclick: () => { if (confirm(MP.t("Clear the whole plate layout?"))) { wells = {}; paint(); ctx.onChange(); } } }, MP.t("Clear plate"));

    const controls = el("div", { class: "pl-controls" },
      el("div", { class: "pl-row" }, roleSeg, valBox, nameBox, dirBox, dilBox, dilDirBox, applyBtn),
      el("div", { class: "pl-row pl-meta" }, selInfo, el("span", { class: "grow" }), presetSel, saveBtn, clearBtn));
    const legend = el("div", { class: "pl-legend" }, summary);
    const node = ctx.fieldShell(inp, el("div", { class: "plate-wrap" }, el("div", { class: "plate-scroll" }, grid), controls, legend));
    syncRole();
    refreshPresets();
    paint();

    let seq = 0;  // only the latest request may fill the plate
    async function refresh() {
      const src = ctx.fields[inp.source];
      const ids = src ? src.get() : [];
      const me = ++seq;
      let next = {};
      if (ids.length) {
        try {
          const d = await api(`/api/tools/${ctx.spec.id}/suggest/${inp.name}`, { json: { files: ids, params: ctx.values() } });
          next = (d.result && d.result.values) || {};
        } catch (e) { if (me === seq) MP.toast(e.message); }
      }
      if (me !== seq) return;
      measured = next;
      paint();
    }

    return {
      node, refresh,
      get: () => wells,
      set: (v) => { if (v && typeof v === "object") { wells = JSON.parse(JSON.stringify(v)); paint(); } },
    };
  };
  // ---------------------------------------------------------------- ImageSpots
  // Regions (circles) on a picture the tool shows; its suggester gives the pictures and the first regions. On the
  // picture: click a region to select it (Ctrl/⌘/Shift adds), drag to move, drag the handle to resize, drag across the
  // picture to select several, double-click (or "Add regions") to add one; Delete removes, arrow keys nudge.
  // Regions with a row and a column (e.g. wells of a chamber) are also shown as plates, named like a plate layout:
  // select wells (drag, or click row/column labels), type the sample name(s), Apply.
  const SVG = "http://www.w3.org/2000/svg";
  const svgEl = (tag, attrs = {}) => { const n = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };

  MP.widgets.spots = function (inp, ctx) {
    let spots = [];            // {id, x, y, r, sample, group, row?, col?}
    let grids = [];            // [{group, title, rows, cols}]: plates to show the regions with a row and column on
    let images = [];           // [{label, src}]
    let imgIdx = 0;
    let W = 640, H = 480;
    let selected = new Set();  // ids
    let note = "";
    let addMode = false;
    let restored = false;      // set() filled it (a job opened again): the next suggestion keeps these regions
    let drag = null;           // on the picture: {kind: "move" | "resize" | "band", ...}
    let lastDown = null;       // the last press on the picture itself: two in a row make a double click
    let wellDrag = null, anchor = null;  // selecting wells on the plates
    const PRESETS = `mp:spots:${ctx.spec.id}:${inp.name}`;

    const svg = svgEl("svg", { class: "spots-svg", tabindex: "0", viewBox: `0 0 ${W} ${H}` });
    const bg = svgEl("image", { x: 0, y: 0, width: W, height: H, preserveAspectRatio: "none" });
    const layer = svgEl("g");
    const band = svgEl("rect", { class: "spots-band", visibility: "hidden" });
    svg.append(bg, layer, band);
    const empty = el("div", { class: "spots-empty muted" }, MP.t("Upload a file to see the picture"));
    const stage = el("div", { class: "spots-stage" }, svg, empty);
    const platesBox = el("div", { class: "spots-plates" });

    // samples in the order they first appear, each a golden angle (≈137.5°) round the colour wheel from the last:
    // neighbours (GPS 1, GPS 2…) always look different
    let hues = new Map();
    const sampleOf = (s) => s.sample || s.id;
    const hueOf = (s) => hues.get(sampleOf(s)) ?? 190;
    const colour = (s) => `hsl(${hueOf(s)} 85% 62%)`;
    const byId = (id) => spots.find((s) => s.id === id);
    const onGrid = (s) => !!(s.row && s.col && grids.some((g) => g.group === (s.group || "")));
    const rowIdx = (s) => ROW_NAMES.indexOf(String(s.row));
    const short = (s) => (onGrid(s) ? `${s.row}${s.col}` : s.id);
    let edits = 0;             // changes made by the person: a suggestion that arrives after one doesn't undo it
    const changed = () => { edits++; paint(); ctx.onChange(); };

    function point(e) {
      const pt = svg.createSVGPoint();
      pt.x = e.clientX; pt.y = e.clientY;
      const m = svg.getScreenCTM();
      const q = m ? pt.matrixTransform(m.inverse()) : { x: 0, y: 0 };
      return { x: Math.max(0, Math.min(W, q.x)), y: Math.max(0, Math.min(H, q.y)) };
    }

    function nextId() {
      let n = spots.length + 1;
      while (byId(String(n))) n++;
      return String(n);
    }

    // ---- the plates: built again when the regions change, repainted otherwise (so a drag across wells keeps going)
    let wellNodes = new Map(), builtKey = "", order = [];
    function buildPlates() {
      const key = JSON.stringify([grids, spots.map((s) => [s.id, s.group, s.row, s.col])]);
      if (key === builtKey) return;
      builtKey = key;
      wellNodes = new Map();
      order = [];
      const parts = [];
      const gridded = new Set();
      for (const g of grids) {
        const inG = () => spots.filter((s) => (s.group || "") === g.group && onGrid(s));
        const plate = el("div", { class: "plate spots-plate", style: `grid-template-columns: 26px repeat(${g.cols}, 64px)` });
        plate.append(el("button", { type: "button", class: "plate-corner", title: MP.t("Select all"), onclick: (e) => pick(inG(), e) }, "◢"));
        for (let c = 1; c <= g.cols; c++) plate.append(el("button", { type: "button", class: "plate-head", onclick: (e) => pick(inG().filter((s) => +s.col === c), e) }, String(c)));
        for (let r = 0; r < g.rows; r++) {
          const R = ROW_NAMES[r];
          plate.append(el("button", { type: "button", class: "plate-head", onclick: (e) => pick(inG().filter((s) => s.row === R), e) }, R));
          for (let c = 1; c <= g.cols; c++) {
            const s = spots.find((x) => (x.group || "") === g.group && x.row === R && +x.col === c);
            if (!s) { plate.append(el("div", { class: "well spots-nowell", title: MP.t("No region here") })); continue; }
            gridded.add(s.id);
            plate.append(wellNode(s));
          }
        }
        parts.push(el("div", { class: "spots-plate-box" }, el("div", { class: "spots-plate-title" }, g.title || g.group), plate));
      }
      const free = spots.filter((s) => !gridded.has(s.id));
      if (free.length) {
        const list = el("div", { class: "spots-free" }, ...free.map((s) => wellNode(s)));
        parts.push(el("div", { class: "spots-plate-box" }, grids.length ? el("div", { class: "spots-plate-title" }, MP.t("Other regions")) : null, list));
      }
      platesBox.replaceChildren(...parts);
    }

    function wellNode(s) {
      const node = el("div", { class: "well", dataset: { id: s.id } });
      order.push(s.id);
      node.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const id = node.dataset.id;
        if (e.shiftKey && anchor && byId(anchor)) { selected = new Set(range(anchor, id)); paint(); return; }
        if (e.metaKey || e.ctrlKey) { selected.has(id) ? selected.delete(id) : selected.add(id); anchor = id; paint(); return; }
        wellDrag = id; anchor = id; selected = new Set([id]); paint();
      });
      node.addEventListener("mouseenter", () => { if (wellDrag) { selected = new Set(range(wellDrag, node.dataset.id)); paint(); } });
      wellNodes.set(s.id, node);
      return node;
    }
    document.addEventListener("mouseup", () => { wellDrag = null; });

    function range(fromId, toId) {
      const a = byId(fromId), b = byId(toId);
      if (a && b && onGrid(a) && onGrid(b) && (a.group || "") === (b.group || "")) {
        const [r0, r1] = [rowIdx(a), rowIdx(b)].sort((x, y) => x - y), [c0, c1] = [+a.col, +b.col].sort((x, y) => x - y);
        return spots.filter((s) => (s.group || "") === (a.group || "") && onGrid(s) && rowIdx(s) >= r0 && rowIdx(s) <= r1 && +s.col >= c0 && +s.col <= c1).map((s) => s.id);
      }
      const [i, j] = [order.indexOf(fromId), order.indexOf(toId)].sort((x, y) => x - y);
      return i < 0 ? [toId] : order.slice(i, j + 1);
    }

    function pick(list, e) {
      if (!(e && (e.metaKey || e.ctrlKey))) selected = new Set();
      list.forEach((s) => selected.add(s.id));
      paint();
    }

    function paint() {
      svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      bg.setAttribute("width", W); bg.setAttribute("height", H);
      const src = images[imgIdx] && images[imgIdx].src;
      if (src) bg.setAttribute("href", src); else bg.removeAttribute("href");
      empty.hidden = !!src || spots.length > 0;
      hues = new Map();
      spots.forEach((s) => { if (!hues.has(sampleOf(s))) hues.set(sampleOf(s), Math.round((190 + hues.size * 137.508) % 360)); });
      svg.classList.toggle("adding", addMode);
      const font = Math.max(9, Math.round(W / 64));
      layer.replaceChildren(...spots.map((s) => {
        const g = svgEl("g", { class: "spot" + (selected.has(s.id) ? " sel" : ""), "data-id": s.id });
        const c = svgEl("circle", { cx: s.x, cy: s.y, r: s.r, stroke: colour(s) });
        const t = svgEl("text", { x: s.x, y: s.y - s.r - 3, "font-size": font, fill: colour(s) });
        t.textContent = short(s);
        const tip = svgEl("title");
        tip.textContent = `${s.id}${s.sample && s.sample !== s.id ? " · " + s.sample : ""} · r ${+(+s.r).toFixed(1)}`;
        g.append(c, t, tip);
        if (selected.has(s.id) && selected.size === 1) g.append(svgEl("circle", { class: "spot-handle", cx: s.x + s.r, cy: s.y, r: Math.max(3, W / 160) }));
        return g;
      }));
      buildPlates();
      for (const [id, node] of wellNodes) {
        const s = byId(id);
        if (!s) continue;
        node.className = "well spots-well" + (selected.has(id) ? " sel" : "");
        node.style.background = `hsl(${hueOf(s)} 85% 62% / .24)`;
        node.style.borderColor = colour(s);
        node.replaceChildren(el("span", { class: "wl" }, sampleOf(s)), el("span", { class: "wv" }, short(s)));
        node.title = `${s.id} · ${sampleOf(s)}`;
      }
      platesBox.hidden = !wellNodes.size;
      const n = selected.size;
      selInfo.textContent = n ? MP.t("Regions selected: {n}", { n }) : MP.t("Drag across the wells or the picture (or click row/column labels) to select");
      const one = n === 1 ? byId([...selected][0]) : null;
      if (one && document.activeElement !== radiusIn) radiusIn.value = +(+one.r).toFixed(1);
      const counts = new Map();
      spots.forEach((s) => counts.set(sampleOf(s), (counts.get(sampleOf(s)) || 0) + 1));
      legend.replaceChildren(
        el("span", { class: "muted" }, MP.t("{a} regions · {b} samples", { a: spots.length, b: counts.size })),
        ...[...counts].map(([name, k]) => el("button", { type: "button", class: "spots-chip", title: MP.t("Select this sample's regions"),
          onclick: () => { selected = new Set(spots.filter((s) => sampleOf(s) === name).map((s) => s.id)); paint(); } },
          el("i", { style: `background:hsl(${hues.get(name) ?? 190} 85% 62%)` }), k > 1 ? `${name} ×${k}` : name)));
      noteLine.textContent = note || "";
      noteLine.hidden = !note;
      bgBox.hidden = images.length < 1;
    }

    // ---- pointer on the picture: select, move, resize, band-select, add
    svg.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || !(images.length || spots.length)) return;
      svg.focus();
      const p = point(e);
      const handle = e.target.closest(".spot-handle");
      const g = e.target.closest(".spot");
      if (handle) {
        drag = { kind: "resize", id: [...selected][0] };
      } else if (g) {
        const id = g.dataset.id;
        if (e.ctrlKey || e.metaKey || e.shiftKey) { selected.has(id) ? selected.delete(id) : selected.add(id); paint(); return; }
        if (!selected.has(id)) selected = new Set([id]);
        drag = { kind: "move", id, from: p, start: new Map(spots.filter((s) => selected.has(s.id)).map((s) => [s.id, [s.x, s.y]])), moved: false };
      } else if (addMode || (lastDown && e.timeStamp - lastDown.t < 400 && Math.hypot(p.x - lastDown.x, p.y - lastDown.y) < 6)) {
        lastDown = null;  // a double click on the picture (or "Add regions" on) adds one
        addAt(p);
        return;
      } else {
        lastDown = { t: e.timeStamp, x: p.x, y: p.y };
        drag = { kind: "band", from: p, add: e.shiftKey || e.ctrlKey || e.metaKey, before: new Set(selected) };
      }
      svg.setPointerCapture(e.pointerId);
      e.preventDefault();
      paint();
    });
    svg.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const p = point(e);
      if (drag.kind === "move") {
        const dx = p.x - drag.from.x, dy = p.y - drag.from.y;
        if (Math.abs(dx) + Math.abs(dy) > 0) drag.moved = true;
        for (const [id, [x0, y0]] of drag.start) { const s = byId(id); s.x = Math.round(x0 + dx); s.y = Math.round(y0 + dy); }
        paint();
      } else if (drag.kind === "resize") {
        const s = byId(drag.id);
        if (s) { s.r = Math.max(1, Math.round(Math.hypot(p.x - s.x, p.y - s.y))); paint(); }
      } else {
        const x = Math.min(p.x, drag.from.x), y = Math.min(p.y, drag.from.y), w = Math.abs(p.x - drag.from.x), h = Math.abs(p.y - drag.from.y);
        Object.entries({ x, y, width: w, height: h, visibility: "visible" }).forEach(([k, v]) => band.setAttribute(k, v));
        selected = new Set(drag.add ? drag.before : []);
        spots.forEach((s) => { if (s.x >= x && s.x <= x + w && s.y >= y && s.y <= y + h) selected.add(s.id); });
        paint();
      }
    });
    const endDrag = () => {
      if (!drag) return;
      const was = drag;
      drag = null;
      band.setAttribute("visibility", "hidden");
      if (was.kind === "band" && !was.add && Math.abs(+band.getAttribute("width") || 0) < 2 && Math.abs(+band.getAttribute("height") || 0) < 2) selected = new Set();
      band.setAttribute("width", 0); band.setAttribute("height", 0);
      if (was.kind === "move" && !was.moved) selected = new Set([was.id]);  // a click (no drag) picks just this one
      if (was.kind === "resize" || (was.kind === "move" && was.moved)) changed(); else paint();
    };
    svg.addEventListener("pointerup", endDrag);
    svg.addEventListener("pointercancel", endDrag);

    function addAt(p) {
      const one = selected.size === 1 ? byId([...selected][0]) : null;
      const r = parseFloat(String(radiusIn.value).replace(",", ".")) || (one && one.r) || inp.radius || 15;
      const s = { id: nextId(), x: Math.round(p.x), y: Math.round(p.y), r, sample: "", group: "" };
      s.sample = s.id;
      spots.push(s);
      selected = new Set([s.id]);
      changed();
    }

    svg.addEventListener("keydown", (e) => {
      if ((e.key === "Delete" || e.key === "Backspace") && selected.size) { e.preventDefault(); removeSelected(); return; }
      if (e.key === "Escape") { selected = new Set(); addMode = false; syncAdd(); paint(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") { e.preventDefault(); selected = new Set(spots.map((s) => s.id)); paint(); return; }
      const step = e.shiftKey ? 5 : 1;
      const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
      if (d && selected.size) {
        e.preventDefault();
        spots.forEach((s) => { if (selected.has(s.id)) { s.x += d[0]; s.y += d[1]; } });
        changed();
      }
    });

    function removeSelected() {
      if (!selected.size) { MP.toast(MP.t("Select regions first")); return; }
      spots = spots.filter((s) => !selected.has(s.id));
      selected = new Set();
      changed();
    }

    // ---- naming, as on a plate layout: one name for the selection, or several (one per row / column)
    const splitList = (text) => text.split(/[,;\t]+/).map((x) => x.trim()).filter(Boolean);
    function byPosition(list, dir) {  // regions without a row and column: rows / columns of the picture
      const key = dir === "rows" ? "y" : "x", other = dir === "rows" ? "x" : "y";
      const out = [];
      for (const s of [...list].sort((a, b) => a[key] - b[key])) {
        const last = out[out.length - 1];
        if (last && Math.abs(s[key] - last[0][key]) <= Math.max(s.r, last[0].r)) last.push(s); else out.push([s]);
      }
      out.forEach((g) => g.sort((a, b) => a[other] - b[other]));
      return out;
    }
    function groupsBy(list, dir) {
      const gi = (s) => grids.findIndex((g) => g.group === (s.group || ""));
      const by = new Map();
      list.filter(onGrid)
        .sort((a, b) => gi(a) - gi(b) || (dir === "rows" ? rowIdx(a) - rowIdx(b) || a.col - b.col : a.col - b.col || rowIdx(a) - rowIdx(b)))
        .forEach((s) => { const k = `${gi(s)}|${dir === "rows" ? s.row : s.col}`; if (!by.has(k)) by.set(k, []); by.get(k).push(s); });
      return [...by.values(), ...byPosition(list.filter((s) => !onGrid(s)), dir)];
    }
    const nameIn = el("input", { type: "text" });
    const dirSel = el("select", {}, el("option", { value: "rows" }, MP.t("one per row (A, B, C…)")), el("option", { value: "cols" }, MP.t("one per column (1, 2, 3…)")));
    function applyNames() {
      const chosen = spots.filter((s) => selected.has(s.id));
      if (!chosen.length) { MP.toast(MP.t("Select regions first")); return; }
      const names = splitList(nameIn.value);
      if (!names.length) { MP.toast(MP.t("Enter a sample name")); return; }
      if (names.length === 1) chosen.forEach((s) => { s.sample = names[0]; });
      else {
        const gs = groupsBy(chosen, dirSel.value);
        if (names.length !== gs.length) {
          MP.toast(MP.t(dirSel.value === "rows" ? "{a} values, but the selection has {b} rows" : "{a} values, but the selection has {b} columns", { a: names.length, b: gs.length }));
          return;
        }
        gs.forEach((g, i) => g.forEach((s) => { s.sample = names[i]; }));
      }
      selected = new Set();
      changed();
    }

    // ---- the picture's tools
    const radiusIn = el("input", { type: "number", min: "1", step: "any", value: inp.radius || 15 });
    function applyRadius() {
      const r = parseFloat(String(radiusIn.value).replace(",", "."));
      if (!(r > 0)) { MP.toast(MP.t("Enter a radius")); return; }
      if (!selected.size) { MP.toast(MP.t("Select regions first")); return; }
      spots.forEach((s) => { if (selected.has(s.id)) s.r = r; });
      changed();
    }
    const addBtn = el("button", { type: "button", class: "btn btn-small", onclick: () => { addMode = !addMode; syncAdd(); paint(); } }, MP.t("Add regions"));
    function syncAdd() { addBtn.classList.toggle("active", addMode); addBtn.setAttribute("aria-pressed", addMode); }
    const bgSel = el("select", {});
    bgSel.addEventListener("change", () => { imgIdx = +bgSel.value || 0; paint(); });
    const bgBox = el("label", { class: "pl-field pl-mid" }, el("span", {}, MP.t("Picture")), el("div", { class: "control" }, bgSel));
    const againBtn = el("button", { type: "button", class: "btn btn-small", title: MP.t("Place the regions again from the settings above"), onclick: () => refresh(true) }, MP.t("Place again"));
    const removeAllBtn = el("button", { type: "button", class: "btn btn-small", onclick: () => {
      if (spots.length && confirm(MP.t("Remove all regions?"))) { spots = []; selected = new Set(); changed(); }
    } }, MP.t("Remove all"));
    const tools = el("div", { class: "pl-row spots-tools" }, bgBox,
      el("label", { class: "pl-field spots-r" }, el("span", {}, MP.t("Radius (px)")), el("div", { class: "control" }, radiusIn)),
      el("button", { type: "button", class: "btn btn-small", onclick: applyRadius }, MP.t("Set radius")),
      el("button", { type: "button", class: "btn btn-small", onclick: removeSelected }, MP.t("Delete")),
      el("span", { class: "grow" }), addBtn, againBtn, removeAllBtn);

    // ---- saved layouts (this browser): names by region; positions too, when none of the regions is here
    const presetSel = el("select", { class: "pl-preset" });
    function loadPresets() { try { return JSON.parse(localStorage.getItem(PRESETS) || "{}"); } catch (_) { return {}; } }
    function refreshPresets() {
      const p = loadPresets();
      presetSel.replaceChildren(el("option", { value: "" }, MP.t("Load a saved layout…")), ...Object.keys(p).sort().map((n) => el("option", { value: n }, n)));
    }
    presetSel.addEventListener("change", () => {
      const p = loadPresets()[presetSel.value];
      if (Array.isArray(p)) {
        const saved = new Map(p.map((s) => [s.id, s]));
        if (spots.some((s) => saved.has(s.id))) spots.forEach((s) => { if (saved.has(s.id)) s.sample = saved.get(s.id).sample; });
        else spots = JSON.parse(JSON.stringify(p));
        selected = new Set();
        changed();
      }
      presetSel.value = "";
    });
    const saveBtn = el("button", { type: "button", class: "btn btn-small", onclick: async () => {
      const n = (await MP.ask(MP.t("Name for this layout:")))?.trim(); if (!n) return;
      const p = loadPresets(); p[n] = spots;
      try { localStorage.setItem(PRESETS, JSON.stringify(p)); MP.toast(MP.t("Layout saved in this browser")); } catch (_) { MP.toast(MP.t("Could not save")); }
      refreshPresets();
    } }, MP.t("Save layout"));
    const clearBtn = el("button", { type: "button", class: "btn btn-small", onclick: () => {
      if (spots.length && confirm(MP.t("Clear all sample names?"))) { spots.forEach((s) => { s.sample = s.id; }); changed(); }
    } }, MP.t("Clear names"));

    const selInfo = el("span", { class: "muted" });
    const legend = el("div", { class: "spots-legend pl-legend" });
    const noteLine = el("div", { class: "spots-note muted" });
    const controls = el("div", { class: "pl-controls" },
      el("div", { class: "pl-row" },
        el("label", { class: "pl-field" }, el("span", {}, MP.t("Sample name(s)")), el("div", { class: "control" }, nameIn)),
        el("label", { class: "pl-field pl-mid" }, el("span", {}, MP.t("Several values →")), el("div", { class: "control" }, dirSel)),
        el("button", { type: "button", class: "btn btn-primary btn-small", onclick: applyNames }, MP.t("Apply to selection"))),
      el("div", { class: "pl-row pl-meta" }, selInfo, el("span", { class: "grow" }), presetSel, saveBtn, clearBtn));
    const node = ctx.fieldShell(inp, el("div", { class: "spots-wrap" }, tools,
      el("div", { class: "spots-body" }, stage, platesBox), noteLine, controls, legend));
    syncAdd();
    refreshPresets();
    paint();

    const clean = (list) => list.map((s, i) => {
      const o = { id: String(s.id ?? i + 1), x: +s.x, y: +s.y, r: +s.r || inp.radius || 15, sample: String(s.sample ?? s.id ?? i + 1), group: String(s.group ?? "") };
      if (s.row && s.col) { o.row = String(s.row); o.col = +s.col; }
      return o;
    });

    let seq = 0;  // only the latest request may fill the picture
    async function refresh(reset = false) {
      const src = ctx.fields[inp.source];
      const ids = src ? src.get() : [];
      const list = Array.isArray(ids) ? ids : ids ? [ids] : [];
      const me = ++seq, before = edits;
      let d = null;
      if (list.length) {
        try { d = (await api(`/api/tools/${ctx.spec.id}/suggest/${inp.name}`, { json: { files: list, params: ctx.values() } })).result || {}; }
        catch (e) { if (me === seq) MP.toast(e.message); return; }
      }
      if (me !== seq) return;
      const edited = edits !== before && spots.length > 0;  // named or moved while this was on its way: keep that
      if (edited) MP.toast(MP.t("Your changes to the regions were kept: press Place again to place them from the settings."), 5000);
      const keep = (!reset && restored && spots.length) || edited;
      restored = false;
      const done = () => { paint(); ctx.onChange(); };
      if (!d) { images = []; note = ""; if (!keep) { spots = []; grids = []; selected = new Set(); } done(); return; }
      W = d.width || W; H = d.height || H;
      const was = images[imgIdx] && images[imgIdx].label;
      images = d.images || (d.image ? [{ label: "", src: d.image }] : []);
      imgIdx = Math.max(0, images.findIndex((im) => im.label === was));
      bgSel.replaceChildren(...images.map((im, i) => el("option", { value: i }, im.label || String(i + 1))));
      bgSel.value = String(imgIdx);
      note = d.note || "";
      if (!edited) grids = (d.grids || []).map((g) => ({ group: String(g.group ?? ""), title: String(g.title ?? g.group ?? ""), rows: +g.rows || 1, cols: +g.cols || 1 }));
      if (!keep) { spots = clean(d.spots || []); selected = new Set(); }
      done();
    }

    return {
      node, refresh,
      get: () => spots.map((s) => ({ ...s })),
      set: (v) => {
        const list = Array.isArray(v) ? v : v && Array.isArray(v.spots) ? v.spots : null;
        if (list) { spots = clean(list); restored = true; selected = new Set(); paint(); }
      },
    };
  };
})();
