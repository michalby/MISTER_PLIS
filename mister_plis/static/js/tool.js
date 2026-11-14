// Tool page: builds the form from the tool's spec, uploads files, runs the tool, shows results.
(function () {
  const { $, el, icon, bytes, api } = MP;
  const spec = JSON.parse($("#tool-spec").textContent);
  MP.toolId = spec.id;
  const form = $("#tool-form");
  const results = $("#results");
  const fields = {};
  const sections = [];
  const STORE_KEY = `mp:form:${spec.id}`;
  let seq = 0;
  let pollTimer = null;

  // ------------------------------------------------------------------ fields
  function fieldShell(inp, control, { label = true } = {}) {
    const optional = !inp.required && !inp.show_if && ["number", "integer", "select", "file", "column"].includes(inp.kind);
    const node = el("div", { class: "field", dataset: { name: inp.name, kind: inp.kind } },
      label ? el("label", { class: "field-label", for: `f-${inp.name}` }, el("span", {}, inp.label), optional ? el("span", { class: "opt" }, MP.t("optional")) : null) : null,
      control,
      inp.help ? el("div", { class: "field-help" }, inp.help) : null,
      el("div", { class: "field-error", hidden: true }));
    return node;
  }

  const builders = {
    number(inp) {
      const input = el("input", { id: `f-${inp.name}`, type: "number", step: inp.step ?? "any", min: inp.min, max: inp.max, placeholder: inp.placeholder || "", inputmode: "decimal" });
      input.value = inp.default ?? "";
      const key = `${inp.name}__unit`;
      const unitSel = inp.units && inp.units.length
        ? el("select", { class: "unit-select", "aria-label": MP.t("{label} unit", { label: inp.label }) }, inp.units.map((u) => el("option", { value: u }, u)))
        : null;
      if (unitSel) unitSel.value = inp.default_unit;
      const control = el("div", { class: "control" }, input, unitSel || (inp.unit ? el("span", { class: "unit" }, inp.unit) : null));
      return {
        node: fieldShell(inp, control), get: () => input.value, set: (v) => { input.value = v ?? ""; },
        extra: () => (unitSel ? { [key]: unitSel.value } : {}),
        setExtra: (params) => { if (unitSel && params && params[key]) unitSel.value = params[key]; },
      };
    },
    integer(inp) { return builders.number(inp); },
    slider(inp) {
      const input = el("input", { id: `f-${inp.name}`, type: "range", step: inp.step, min: inp.min, max: inp.max });
      input.value = inp.default ?? inp.min;
      const out = el("output", {}, input.value + (inp.unit ? ` ${inp.unit}` : ""));
      input.addEventListener("input", () => { out.textContent = input.value + (inp.unit ? ` ${inp.unit}` : ""); });
      return { node: fieldShell(inp, el("div", { class: "slider-row" }, input, out)), get: () => input.value, set: (v) => { input.value = v; input.dispatchEvent(new Event("input")); } };
    },
    text(inp) {
      const input = el("input", { id: `f-${inp.name}`, type: "text", placeholder: inp.placeholder || "" });
      input.value = inp.default ?? "";
      return { node: fieldShell(inp, el("div", { class: "control" }, input)), get: () => input.value, set: (v) => { input.value = v ?? ""; } };
    },
    textarea(inp) {
      const ta = el("textarea", { id: `f-${inp.name}`, rows: inp.rows, placeholder: inp.placeholder || "", class: inp.monospace ? "mono" : "", spellcheck: "false" });
      ta.value = inp.default ?? "";
      return { node: fieldShell(inp, el("div", { class: "control" }, ta)), get: () => ta.value, set: (v) => { ta.value = v ?? ""; } };
    },
    select(inp) {
      const sel = el("select", { id: `f-${inp.name}` }, inp.options.map(([v, l]) => el("option", { value: v }, l)));
      sel.value = inp.default ?? "";
      // a remembered value is only restored if it is still one of the options (lists can change)
      const set = (v) => { if (v !== undefined && [...sel.options].some((o) => o.value === String(v))) sel.value = v; };
      return { node: fieldShell(inp, el("div", { class: "control" }, sel)), get: () => sel.value, set };
    },
    checkbox(inp) {
      const cb = el("input", { id: `f-${inp.name}`, type: "checkbox" });
      cb.checked = !!inp.default;
      const sw = el("label", { class: "switch" }, cb, el("span", { class: "track" }), el("span", {}, inp.label));
      return { node: fieldShell(inp, sw, { label: false }), get: () => cb.checked, set: (v) => { cb.checked = !!v; } };
    },
    file(inp) { return fileField(inp); },
    column(inp) { return columnField(inp); },
    button(inp) {
      const btn = el("button", { type: "button", class: "btn btn-small" }, inp.label);
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          const r = await api(`/api/tools/${spec.id}/action/${inp.name}`, { json: { params: values() } });
          MP.toast(r.message, 3000);
          if (r.reload) setTimeout(() => location.reload(), 900);
        } catch (e) { MP.toast(e.message, 4000); }
        btn.disabled = false;
      });
      return { node: fieldShell(inp, el("div", {}, btn), { label: false }), get: () => undefined, set: () => { } };
    },
    samples(inp) { return MP.widgets.samples(inp, widgetCtx); },
    plate(inp) { return MP.widgets.plate(inp, widgetCtx); },
    spots(inp) { return MP.widgets.spots(inp, widgetCtx); },
  };
  const widgetCtx = { spec, fields, fieldShell, onChange: () => onChange(), values: () => values() };

  function fileField(inp) {
    let items = []; // {id, name, size, status: 'uploading'|'done'|'error', progress, error}
    const picker = el("input", { type: "file", accept: inp.accept || null, multiple: inp.multiple || null, hidden: true });
    const folderPicker = inp.multiple ? el("input", { type: "file", webkitdirectory: true, multiple: true, hidden: true }) : null;
    const exts = (inp.accept || "").split(",").map((x) => x.trim().toLowerCase()).filter((x) => x.startsWith("."));
    const zone = el("div", { class: "dropzone", tabindex: 0, role: "button" },
      icon("upload", 22),
      el("div", {}, el("strong", {}, MP.t(inp.multiple ? "Choose files" : "Choose file")),
        inp.multiple ? el("span", {}, ", ", el("a", { href: "#", class: "folder-link", onclick: (e) => { e.preventDefault(); e.stopPropagation(); folderPicker.click(); } }, MP.t("a folder"))) : null,
        " " + MP.t("or drop here")),
      inp.accept ? el("div", { class: "accept" }, inp.accept.replaceAll(",", " ")) : null);
    const note = el("div", { class: "file-note", hidden: true });
    const list = el("div", { class: "files" });
    const wrap = el("div", {}, zone, picker, folderPicker, note, list);
    const node = fieldShell(inp, wrap);

    zone.addEventListener("click", () => picker.click());
    zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); picker.click(); } });
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag"));
    zone.addEventListener("drop", async (e) => {
      e.preventDefault();
      zone.classList.remove("drag");
      add(await droppedFiles(e.dataTransfer));
    });
    picker.addEventListener("change", () => { add(Array.from(picker.files)); picker.value = ""; });
    if (folderPicker) folderPicker.addEventListener("change", () => { add(Array.from(folderPicker.files)); folderPicker.value = ""; });

    function changed() { render(); node.dispatchEvent(new CustomEvent("files-changed", { bubbles: true })); onChange(); }

    function render() {
      zone.classList.toggle("compact", items.length > 0);
      zone.querySelector("strong").textContent = MP.t(items.length && !inp.multiple ? "Replace file" : items.length ? "Add more" : inp.multiple ? "Choose files" : "Choose file");
      list.replaceChildren(...items.map((it) => {
        const bar = el("div", { class: "bar", style: `width:${it.status === "uploading" ? Math.round(it.progress * 100) : 0}%` });
        it.bar = bar;
        return el("div", { class: "file-chip" + (it.status === "error" ? " error" : "") },
          it.status === "uploading" ? el("span", { class: "spinner", style: "width:14px;height:14px" }) : icon(it.status === "error" ? "alert" : "file", 16),
          el("div", { class: "fname", title: it.name }, it.name, el("span", { class: "fsize" }, it.status === "error" ? it.error : bytes(it.size))),
          el("button", { type: "button", title: MP.t("Remove"), onclick: () => { items = items.filter((x) => x !== it); changed(); } }, icon("x", 14)),
          bar);
      }));
      renderNote();
    }

    let ignored = {};  // extension → count of files skipped in the last add
    function renderNote() {
      const parts = Object.entries(ignored).map(([ext, n]) => `${ext || "?"} × ${n}`);
      const showClear = inp.multiple && items.length > 1;
      note.hidden = !parts.length && !showClear;
      note.replaceChildren(...[
        parts.length ? el("span", {}, MP.t("Ignored {files} — not a type this tool reads.", { files: parts.join(", ") })) : el("span", {}),
        showClear ? el("button", { type: "button", class: "link-btn", onclick: () => { items = []; ignored = {}; changed(); } }, MP.t("Remove all ({n})", { n: items.length })) : null,
      ].filter(Boolean));
    }

    function add(files) {
      // skip hidden files (.DS_Store …) and anything this input can't read — they are never uploaded
      ignored = {};
      files = files.filter((f) => {
        if (f.name.startsWith(".")) return false;
        const lower = f.name.toLowerCase();
        if (exts.length && !exts.some((x) => lower.endsWith(x))) {
          const ext = lower.includes(".") ? lower.slice(lower.lastIndexOf(".")).toUpperCase() : "";
          ignored[ext] = (ignored[ext] || 0) + 1;
          return false;
        }
        return true;
      }).sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
      if (!files.length) { render(); if (Object.keys(ignored).length) MP.toast(MP.t("None of those files can be used here")); return; }
      if (!inp.multiple) { items = []; files = files.slice(0, 1); }
      for (const f of files) {
        const it = { name: f.name, size: f.size, status: "uploading", progress: 0 };
        items.push(it);
        upload(f, (p) => { it.progress = p; if (it.bar) it.bar.style.width = `${Math.round(p * 100)}%`; })
          .then((r) => { Object.assign(it, r, { status: "done" }); settle(); })
          .catch((e) => { it.status = "error"; it.error = e.message; settle(); });
      }
      render();
    }

    // refresh dependent tables once, when the whole batch has finished uploading
    function settle() { if (items.some((i) => i.status === "uploading")) render(); else changed(); }

    return {
      node,
      get: () => items.filter((i) => i.status === "done").map((i) => i.id),
      set: async (list) => {
        // list: [{id, name}] from a previous job — keep the ones still on the server
        const kept = [];
        for (const f of list || []) {
          try { const info = await api(`/api/uploads/${f.id}`); kept.push({ ...info, status: "done" }); } catch (_) { }
        }
        items = kept;
        changed();
      },
      busy: () => items.some((i) => i.status === "uploading"),
      first: () => items.find((i) => i.status === "done"),
    };
  }

  // Files from a drop — folders are walked recursively (call before any await: the entries expire).
  async function droppedFiles(dt) {
    const entries = [...(dt.items || [])].map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null)).filter(Boolean);
    if (!entries.length) return Array.from(dt.files);
    const out = [];
    async function walk(entry) {
      if (entry.isFile) {
        out.push(await new Promise((res, rej) => entry.file(res, rej)));
      } else if (entry.isDirectory) {
        const reader = entry.createReader();
        let batch;
        do {
          batch = await new Promise((res, rej) => reader.readEntries(res, rej));
          for (const e of batch) await walk(e);
        } while (batch.length);
      }
    }
    for (const e of entries) await walk(e);
    return out;
  }

  function upload(file, onProgress) {
    return new Promise((resolve, reject) => {
      if (MP.maxUpload && file.size > MP.maxUpload) {
        reject(new Error(MP.t("The file is larger than {mb} MB, the most this lab allows (Settings → Jobs & backup).",
                              { mb: Math.round(MP.maxUpload / 1048576) })));
        return;
      }
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/uploads");
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
      xhr.onload = () => {
        if (xhr.status < 300) { resolve(JSON.parse(xhr.responseText)); return; }
        let said = "";
        try { said = JSON.parse(xhr.responseText).error || ""; } catch (_) { /* not JSON */ }
        reject(new Error(said || MP.t("upload failed ({status})", { status: xhr.status })));
      };
      xhr.onerror = () => reject(new Error(MP.t("network error")));
      const fd = new FormData();
      fd.append("file", file);
      xhr.send(fd);
    });
  }

  function columnField(inp) {
    let columns = [];
    let chosen = inp.multiple ? (Array.isArray(inp.default) ? inp.default.slice() : []) : null;
    let pending = null; // value to apply once columns load
    const sel = el("select", { id: `f-${inp.name}`, disabled: true }, el("option", { value: "" }, MP.t("Upload a table first")));
    const pills = el("div", { class: "pills" }, el("span", { class: "pill-hint" }, MP.t("Upload a table first")));
    const control = inp.multiple ? pills : el("div", { class: "control" }, sel);
    const node = fieldShell(inp, control);
    sel.addEventListener("change", () => onChange());

    function pickDefault() {
      const names = columns.map((c) => c.name);
      if (pending !== null) { const p = pending; pending = null; return p; }
      if (inp.multiple) return (chosen || []).filter((c) => names.includes(c));
      const cur = sel.value;
      if (cur && names.includes(cur)) return cur;
      if (typeof inp.default === "string" && names.includes(inp.default)) return inp.default;
      if (typeof inp.default === "number" && names[inp.default] !== undefined) return names[inp.default];
      return inp.required ? names[0] ?? "" : "";
    }

    function render() {
      const value = pickDefault();
      if (inp.multiple) {
        chosen = Array.isArray(value) ? value : [];
        if (!columns.length) { pills.replaceChildren(el("span", { class: "pill-hint" }, MP.t("Upload a table first"))); return; }
        pills.replaceChildren(...columns.map((c) => {
          const p = el("span", { class: "pill" + (chosen.includes(c.name) ? " on" : ""), tabindex: 0, role: "checkbox" }, c.name);
          const toggle = () => {
            chosen = chosen.includes(c.name) ? chosen.filter((x) => x !== c.name) : [...chosen, c.name];
            p.classList.toggle("on");
            onChange();
          };
          p.addEventListener("click", toggle);
          p.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); toggle(); } });
          return p;
        }));
      } else {
        sel.disabled = !columns.length;
        const opts = columns.length ? columns.map((c) => el("option", { value: c.name }, c.name)) : [el("option", { value: "" }, MP.t("Upload a table first"))];
        if (columns.length && !inp.required) opts.unshift(el("option", { value: "" }, MP.t("— none —")));
        sel.replaceChildren(...opts);
        sel.value = value;
      }
    }

    async function refresh() {
      const src = fields[inp.source];
      const f = src && src.first && src.first();
      if (!f) { columns = []; render(); return; }
      try {
        const info = await api(`/api/uploads/${f.id}/table`);
        columns = info.columns.filter((c) => !inp.numeric || c.numeric);
      } catch (e) {
        columns = [];
      }
      render();
      onChange();
    }

    return {
      node,
      refresh,
      get: () => (inp.multiple ? chosen : sel.value),
      set: (v) => { pending = v; if (columns.length) render(); },
    };
  }

  function build() {
    const root = $("#fields");
    let container = el("div", { class: "form-grid" });
    root.append(container);
    for (const inp of spec.inputs) {
      if (inp.kind === "section") {
        container = el("div", { class: "form-grid" });
        const det = el("details", { class: "form-section", open: !inp.collapsed },
          el("summary", {}, inp.title), inp.description ? el("p", { class: "section-desc" }, inp.description) : null, container);
        root.append(det);
        sections.push({ inp, node: det });
        continue;
      }
      const b = builders[inp.kind] || builders.text;
      const f = b(inp);
      f.inp = inp;
      fields[inp.name] = f;
      container.append(f.node);
    }
    // Column dropdowns follow their source file input.
    for (const f of Object.values(fields)) {
      if (["column", "samples", "plate", "spots"].includes(f.inp.kind) && fields[f.inp.source] && f.refresh) {
        fields[f.inp.source].node.addEventListener("files-changed", () => f.refresh());
      }
      // …and re-read the files from scratch when an input that changes how they're read changes.
      for (const name of f.inp.refresh_on || []) {
        if (fields[name] && f.refresh) fields[name].node.addEventListener("change", () => f.refresh(true));
      }
    }
    form.addEventListener("input", (e) => { if (e.target.type !== "file") onChange(); });
    form.addEventListener("change", (e) => { if (e.target.tagName === "SELECT" || e.target.type === "checkbox") onChange(); });
  }

  function values() {
    const v = {};
    for (const [name, f] of Object.entries(fields)) {
      v[name] = f.get();
      if (f.extra) Object.assign(v, f.extra());
    }
    return v;
  }

  function visible(cond) {
    if (!cond) return true;
    return Object.entries(cond).every(([k, want]) => {
      const cur = fields[k] ? fields[k].get() : undefined;
      return (Array.isArray(want) ? want : [want]).some((w) => String(w) === String(cur));
    });
  }

  function updateVisibility() {
    for (const f of Object.values(fields)) f.node.hidden = !visible(f.inp.show_if);
    for (const s of sections) s.node.hidden = !visible(s.inp.show_if);
  }

  let liveTimer = null;
  let restoring = false;
  function onChange() {
    if (restoring) return;
    updateVisibility();
    saveForm();
    if (spec.live) { clearTimeout(liveTimer); liveTimer = setTimeout(run, 220); }
  }

  // ------------------------------------------------------------------ file names
  // Result files are named "<date>_<your name>_<keyword>_<file>" (same rule as Job.file_prefix on the server).
  const keywordInput = $("#f-keyword");
  const titleInput = $("#f-title");  // the job's title: not remembered between runs, each result gets its own
  const namePart = (s) => String(s || "").replace(/[^\p{L}\p{N}\-.()]+/gu, " ").trim().split(/\s+/).join("-").replace(/^[.-]+|[.-]+$/g, "");
  function showFilePreview() {
    const box = $("#keyword-preview");
    if (!box) return;
    const prefix = [MP.date(new Date()), namePart(MP.prefs.name), namePart(keywordInput.value)].filter(Boolean).join("_");
    box.replaceChildren(MP.t("Files are named") + " ", el("code", {}, `${prefix}_…`),
      MP.prefs.name ? "" : el("span", {}, " — ", el("a", { class: "link", href: "/settings#you" }, MP.t("add your name")), MP.t(" to have it in them too")));
  }
  keywordInput?.addEventListener("input", () => { showFilePreview(); saveForm(); });

  function saveForm() {
    if (MP.prefs.remember_inputs === "off") return;
    const v = values();
    if (keywordInput) v.__keyword = keywordInput.value;
    for (const f of Object.values(fields)) if (["file", "samples", "spots"].includes(f.inp.kind)) delete v[f.inp.name];  // circles belong to one picture
    try { localStorage.setItem(STORE_KEY, JSON.stringify(v)); } catch (_) { }
  }

  function loadSaved() {
    if (MP.prefs.remember_inputs === "off") return null;
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || "null"); } catch (_) { return null; }
  }

  async function fill(params, files, keyword, title) {
    restoring = true;
    try {
      if (titleInput && title !== undefined) titleInput.value = title || "";
      if (keywordInput) {
        keywordInput.value = keyword ?? (params && params.__keyword) ?? keywordInput.value;
        showFilePreview();
      }
      for (const [name, f] of Object.entries(fields)) {
        if (f.inp.kind === "file") { if (files && files[name]) await f.set(files[name]); }
        else if (params && name in params) f.set(params[name]);
        if (f.setExtra) f.setExtra(params);
      }
    } finally { restoring = false; }
    updateVisibility();
  }

  // ------------------------------------------------------------------ filled in by a link
  // /tool/<id>?<input>=<value> (and <input>__unit=<unit>) fills those inputs in, over what this browser remembers: e.g.
  // a reagent in the inventory opens a calculator with its name and molar mass. Only plain inputs (no files).
  const LINKABLE = ["number", "integer", "slider", "text", "textarea", "select", "checkbox"];
  function fromLink() {
    const params = {};
    for (const [k, v] of new URLSearchParams(location.search)) {
      const name = k.endsWith("__unit") ? k.slice(0, -6) : k;
      const f = fields[name];
      if (!f || !LINKABLE.includes(f.inp.kind)) continue;
      params[k] = f.inp.kind === "checkbox" && k === name ? ["1", "true", "yes", "on"].includes(v.toLowerCase()) : v;
    }
    return Object.keys(params).length ? params : null;
  }

  // a collapsed section opens when the link gives one of its inputs something other than the default
  function openSectionsFor(params) {
    for (const s of sections) {
      if (Object.entries(fields).some(([name, f]) => name in params && s.node.contains(f.node) && String(f.get()) !== String(f.inp.default ?? ""))) s.node.open = true;
    }
  }

  // ------------------------------------------------------------------ running
  function setBusy(on) {
    const btn = $("#run-btn");
    if (!btn) return;
    btn.disabled = on || !!spec.unavailable;
    btn.replaceChildren(on ? el("span", { class: "spinner" }) : icon("play", 16), el("span", {}, on ? MP.t("Running…") : spec.submit_label));
  }

  async function run() {
    const uploading = Object.values(fields).some((f) => f.busy && f.busy());
    if (uploading) { if (!spec.live) MP.toast(MP.t("Wait for the upload to finish")); return; }
    clearTimeout(pollTimer);
    const my = ++seq;
    if (spec.live) {
      const t = setTimeout(() => results.classList.add("is-stale"), 180);
      try {
        const job = await api(`/api/tools/${spec.id}/run`, { json: { params: values(), wait: 15 } });
        if (my !== seq) return;
        handle(job, my);
      } catch (e) {
        if (my === seq) showFatal(e);
      } finally { clearTimeout(t); if (my === seq) results.classList.remove("is-stale"); }
      return;
    }
    setBusy(true);
    showStatus({ status: "queued", message: MP.t("Starting…"), log: [] }, my);
    try {
      const job = await api(`/api/tools/${spec.id}/run`, { json: { params: values(), keyword: keywordInput ? keywordInput.value.trim() : "", title: titleInput ? titleInput.value.trim() : "", parent: MP.parentJob || "", wait: 25 } });
      if (my !== seq) return;
      history.replaceState(null, "", `?job=${job.id}`);
      if (MP.parentJob) MP.parentJob = job.id;  // a chain of re-runs: each one follows the last
      handle(job, my);
    } catch (e) {
      if (my === seq) { setBusy(false); showFatal(e); }
    }
  }

  function handle(job, my) {
    if (my !== seq) return;
    if (job.status === "queued" || job.status === "running") {
      setBusy(!spec.background);
      showStatus(job, my);
      pollTimer = setTimeout(async () => {
        try { handle(await api(`/api/jobs/${job.id}`), my); }
        catch (e) { if (my === seq) pollTimer = setTimeout(() => handle(job, my), 2000); }
      }, 700);
      return;
    }
    setBusy(false);
    showResult(job);
    if (!spec.live) loadHistory();
  }

  function showStatus(job, my) {
    let card = results.querySelector(".run-status");
    if (!card) {
      card = el("div", { class: "out-card run-status" },
        el("div", { class: "run-status-top" },
          el("span", { class: "spinner" }),
          el("div", { class: "grow" }, el("div", { class: "run-status-title" }), el("div", { class: "run-status-msg" })),
          job.id ? el("button", { class: "btn btn-small btn-danger", type: "button", onclick: () => cancel(job.id) }, MP.t("Cancel")) : null),
        el("div", { class: "progress" }, el("div")),
        el("pre", { class: "log", hidden: true }));
      results.replaceChildren(card);
    }
    if (job.id && !card.querySelector(".btn-danger")) {
      card.querySelector(".run-status-top").append(el("button", { class: "btn btn-small btn-danger", type: "button", onclick: () => cancel(job.id) }, MP.t("Cancel")));
    }
    const elapsed = job.started ? ` · ${MP.duration(Date.now() / 1000 - job.started)}` : "";
    const where = job.worker && job.status === "running" ? ` · ${MP.t("on {name}", { name: job.worker })}` : "";
    card.querySelector(".run-status-title").textContent = MP.t(job.status === "queued" ? "Queued" : "Running") + where + elapsed;
    card.querySelector(".run-status-msg").textContent = job.message || MP.t(job.status === "queued" ? "Waiting to start" : spec.background ? "You can leave this page — the job keeps running. Find it under Jobs." : "Working…");
    const prog = card.querySelector(".progress");
    prog.classList.toggle("indeterminate", job.progress == null);
    prog.firstChild.style.width = job.progress == null ? "" : `${Math.round(job.progress * 100)}%`;
    const log = card.querySelector(".log");
    if (job.log && job.log.length) {
      const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 30;
      log.hidden = false;
      log.textContent = job.log.slice(-200).join("\n");
      if (atBottom) log.scrollTop = log.scrollHeight;
    }
  }

  async function cancel(id) {
    try { await api(`/api/jobs/${id}/cancel`, { method: "POST" }); MP.toast(MP.t("Cancelling…")); } catch (e) { MP.toast(e.message); }
  }

  function showResult(job) {
    MP.filesFrom(job);  // its files from their own origin, where the page reaches it
    const nodes = [];
    if (!spec.live) {
      const icons = { done: "check", failed: "alert", cancelled: "x", interrupted: "alert" };
      const took = job.started && job.finished ? MP.t("in {time}", { time: MP.duration(job.finished - job.started) }) : "";
      if (job.id && job.status === "done") nodes.push(MP.titleEditor(MP.t(spec.name), job.title, async (title) => {
        const d = await api(`/api/jobs/${job.id}/title`, { json: { title } });
        job.title = d.title;
        if (titleInput) titleInput.value = d.title;
        return d.title;
      }));
      nodes.push(el("div", { class: "result-meta" },
        el("span", { class: `status status-${job.status}` }, icon(icons[job.status] || "check", 14), MP.t({ done: "Done", failed: "Failed", cancelled: "Cancelled", interrupted: "Interrupted" }[job.status] || job.status)),
        el("span", {}, [took, job.worker ? MP.t("on {name}", { name: job.worker }) : "", MP.ago(job.finished || job.created)].filter(Boolean).join(" · ")),
        job.id ? MP.jobNumber(job) : null,
        MP.resultButtons(
          ...MP.resultActions(spec, job),
          ...(spec.history !== false ? MP.hooks.resultActions.map((fn) => fn(job, spec)).filter(Boolean) : []),
          el("button", { class: "btn btn-small", type: "button", onclick: async () => { await MP.copy(`${location.origin}/tool/${spec.id}?job=${job.id}`); MP.toast(MP.t("Link copied — share it with anyone in the lab")); } }, MP.t("Copy link")))));
    } else {
      const actions = MP.resultActions(spec, job);
      if (actions.length) nodes.push(el("div", { class: "result-meta result-actions" }, MP.resultButtons(...actions)));
    }
    if (job.status === "failed" || job.status === "interrupted") {
      if (spec.live && !job.traceback) nodes.push(el("div", { class: "alert alert-warning" }, icon("alert", 16), el("div", {}, job.error)));
      else nodes.push(MP.renderError(job));
    }
    if (job.status === "cancelled") nodes.push(el("div", { class: "alert" }, MP.t("The job was cancelled.")));
    const out = el("div", { class: "results", style: "gap:16px" });
    MP.renderOutputs(out, job.outputs || [], { skip: new Set([MP.workbookIndex(job)]) });
    nodes.push(...out.childNodes);
    if (!spec.live && job.log && job.log.length) {
      nodes.push(el("details", { class: "log-details" }, el("summary", {}, MP.tn(job.log.length, "Log ({n} line)", "Log ({n} lines)")), el("pre", { class: "log" }, job.log.join("\n"))));
    }
    if (!nodes.length) nodes.push(el("div", { class: "empty-state" }, el("p", {}, MP.t("Nothing to show."))));
    results.replaceChildren(...nodes);
  }

  function showFatal(e) {
    results.replaceChildren(el("div", { class: "alert alert-error" }, icon("alert", 16), el("div", {}, e.message || String(e))));
  }

  // ------------------------------------------------------------------ history
  async function loadHistory() {
    const box = $("#tool-history");
    if (!box) return;
    try {
      const d = await api(`/api/jobs?tool=${encodeURIComponent(spec.id)}&limit=6`);
      box.hidden = d.jobs.length === 0;
      $("#history-list").replaceChildren(...d.jobs.map(MP.jobRow));
    } catch (_) { }
  }

  // ------------------------------------------------------------------ init
  form.addEventListener("submit", (e) => { e.preventDefault(); if (!spec.unavailable) run(); });
  form.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); if (!spec.unavailable) run(); } });

  build();
  if (spec.protocol) $(".tool-layout").after(MP.protocolPanel());
  updateVisibility();
  showFilePreview();
  // inputs are remembered per tool in this browser; this puts the defaults back
  $("#fields").append(el("div", { class: "reset-row" }, el("button", { type: "button", class: "link-btn", onclick: () => {
    try { localStorage.removeItem(STORE_KEY); } catch (_) { }
    location.href = location.pathname;
  } }, MP.t("Reset inputs to defaults"))));

  (async function init() {
    const jobId = new URLSearchParams(location.search).get("job");
    if (jobId) {
      try {
        const job = await api(`/api/jobs/${jobId}`);
        MP.parentJob = job.id;  // running again from here makes a re-run (a new version in Time Machine)
        await fill(job.params, job.files, job.keyword || "", job.title || "");
        handle(job, ++seq);
      } catch (e) {
        showFatal(new Error(MP.t("That result is no longer available — it may have been cleaned up.")));
      }
    } else {
      const saved = loadSaved();
      if (saved) await fill(saved, null);
      const linked = fromLink();
      if (linked) {
        await fill(linked, null);
        openSectionsFor(linked);
        history.replaceState(null, "", location.pathname);  // a reload keeps what the person changed after
        saveForm();
      }
      if (spec.live && !spec.unavailable) run();
    }
    loadHistory();
  })();
})();
