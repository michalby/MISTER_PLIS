// The setup page (/setup; docs/LAB_SETUP_PLAN.md): start from a lab file or this server's settings, change what is
// needed, Check (what would change, and can each repository be read), then Set up. The page holds the lab in the same
// shape as a lab file (mister_plis/labsetup.py); what the form doesn't show (a tool's own settings, the label printer's
// options…) passes through as loaded.
(function () {
  const { $, $$, el, api } = MP;
  const form = $("#setup-form");
  if (!form) return;
  let info = null;        // GET /api/setup: state, current, files, modules
  let lab = {};           // the lab being set up
  let source = "page";    // where it came from (kept in lab.json)

  const clone = (x) => JSON.parse(JSON.stringify(x || {}));
  const errorBox = (text) => el("div", { class: "alert alert-error" }, MP.icon("alert", 16), el("span", {}, text));

  // a lab file over this server's settings: what the file leaves out stays as it is
  function merge(base, over) {
    const out = clone(base);
    for (const [k, v] of Object.entries(over || {})) {
      if (k === "tool_sources") {
        const list = out.tool_sources || [];
        for (const s of v) {
          const i = list.findIndex((x) => x.name === s.name);
          if (i >= 0) list[i] = { ...list[i], ...s }; else list.push(clone(s));
        }
        out.tool_sources = list;
      } else if (k === "module" || k === "tool") {
        out[k] = out[k] || {};
        for (const [id, t] of Object.entries(v)) out[k][id] = { ...(out[k][id] || {}), ...t };
      } else if (k === "modules") out.modules = clone(v);
      else if (v && typeof v === "object" && !Array.isArray(v)) out[k] = { ...(out[k] || {}), ...v };
    }
    return out;
  }

  // ---- filling the form from the lab -------------------------------------------------------------------------------
  const baseInputs = () => $$("[name]", form).filter((i) => !i.name.startsWith("module.") && !i.name.startsWith("src."));

  function fill() {
    for (const inp of baseInputs()) {
      const [s, k] = inp.name.split(".");
      let v = (lab[s] || {})[k];
      if (inp.name === "lab.language" && v === "en") v = "";
      inp.value = v === undefined || v === null ? "" : String(v);
    }
    renderSources();
    renderModules();
    unchecked();
  }

  function sourceRow(s, here) {
    const name = el("input", { type: "text", name: "src.name", value: s.name || "", spellcheck: "false", "aria-label": MP.t("Name") });
    const url = el("input", { type: "text", name: "src.url", value: s.url || "", placeholder: "https://github.com/your-lab/tools.git", spellcheck: "false", "aria-label": MP.t("Repository address") });
    const branch = el("input", { type: "text", name: "src.branch", value: s.branch || "main", placeholder: "main", spellcheck: "false", "aria-label": MP.t("Branch") });
    const trusted = el("input", { type: "checkbox", name: "src.trusted" });
    trusted.checked = !!s.trusted;
    if (here) name.readOnly = true;  // a source on this server keeps its name
    const row = el("div", { class: "setup-source" + (here ? " is-here" : "") },
      el("div", { class: "control setup-src-name" }, name), el("div", { class: "control setup-src-url" }, url),
      el("div", { class: "control setup-src-branch" }, branch),
      el("label", { class: "setup-check" }, trusted, el("span", {}, MP.t("trusted"))),
      here ? el("span", { class: "muted small setup-src-here" }, MP.t("on this server"))
        : el("button", { type: "button", class: "icon-btn icon-btn-sm", title: MP.t("Leave out"), "aria-label": MP.t("Leave out"),
          onclick: () => { row.remove(); unchecked(); } }, MP.icon("x", 14)));
    return row;
  }

  function renderSources() {
    const here = new Set((info.current.tool_sources || []).map((s) => s.name));
    const list = lab.tool_sources || [];
    $("#setup-sources").replaceChildren(...(list.length ? list.map((s) => sourceRow(s, here.has(s.name)))
      : [el("p", { class: "muted setup-none" }, MP.t("No tool source yet: MISTER PLIS runs without tools until one is added."))]));
  }

  // one question of a module: its label, the input, then its help (so the inputs of a row line up)
  function fieldInput(m, f, value) {
    const name = `module.${m.id}.${f.key}`;
    const help = f.help ? el("span", { class: "setting-help" }, f.help) : null;
    if (f.kind === "bool") {
      const box = el("input", { type: "checkbox", name });
      box.checked = !!value;
      return el("div", { class: "setup-field is-wide" }, el("label", { class: "setup-check" }, box, el("span", {}, f.label)), help);
    }
    let input;
    if (f.kind === "choice") {
      input = el("select", { name }, f.choices.map(([v, label]) => el("option", { value: String(v) }, label)));
      input.value = value === undefined || value === null ? "" : String(value);
    } else if (f.kind === "tool") {  // one of the loaded tools; one that isn't here (yet) stays chosen
      const here = info.tools.some((t) => t.id === value);
      input = el("select", { name },
        el("option", { value: "" }, (f.choices[0] || [])[1] || MP.t("none")),
        info.tools.map((t) => el("option", { value: t.id }, `${t.name} (${t.id})`)),
        value && !here ? el("option", { value }, MP.t("{id} — not loaded yet", { id: value })) : null);
      input.value = value || "";
    } else if (f.kind === "list") {
      input = el("textarea", { name, rows: 3, spellcheck: "false", placeholder: f.placeholder || "" });
      input.value = Array.isArray(value) ? value.join("\n") : (value || "");
    } else {
      input = el("input", { type: f.kind === "number" ? "number" : "text", name, placeholder: f.placeholder || "", spellcheck: "false" });
      input.value = value === undefined || value === null ? "" : String(value);
    }
    const wide = f.kind === "repository" || f.kind === "list";
    return el("label", { class: "setup-field" + (wide ? " is-wide" : "") }, el("span", { class: "field-label" }, f.label),
      el("div", { class: "control" }, input), help);
  }

  // what a folded group holds, in a few words: its first choice
  function brief(fields, values) {
    const f = fields.find((x) => x.kind === "choice" || x.kind === "tool");
    if (!f) return "";
    const v = values[f.key];
    if (f.kind === "tool") return v ? (info.tools.find((t) => t.id === v) || { name: v }).name : (f.choices[0] || [])[1] || "";
    const c = f.choices.find(([x]) => String(x) === String(v));
    return c ? `${f.label}: ${c[1]}` : "";
  }

  function renderModules() {
    const on = (lab.modules || {}).on;
    const box = $("#setup-modules");
    box.replaceChildren(...info.modules.map((m) => {
      const toggle = el("input", { type: "checkbox", name: `module.${m.id}.__on` });
      toggle.checked = on === undefined || on === "all" || (Array.isArray(on) && on.includes(m.id));
      const values = (lab.module || {})[m.id] || {};
      const waiting = !m.loaded && Object.keys(values).length;
      const groups = (m.groups.length ? m.groups : [{ id: "", title: "" }]).map((g) => {
        const fields = m.fields.filter((f) => (f.group || "") === g.id);
        if (!fields.length) return null;
        const body = [g.help ? el("p", { class: "setting-help setup-group-help" }, g.help) : null,
          el("div", { class: "setup-fields" }, fields.map((f) => fieldInput(m, f, values[f.key])))];
        if (g.folded) {
          const sum = brief(fields, values);
          return el("details", { class: "setup-group" },
            el("summary", {}, el("span", { class: "setup-group-title" }, g.title), sum ? el("span", { class: "muted" }, " · ", sum) : null), body);
        }
        return el("div", { class: "setup-group" }, g.title ? el("div", { class: "setup-group-title" }, g.title) : null, body);
      });
      const card = el("div", { class: "setup-module" + (toggle.checked ? "" : " is-off") },
        el("label", { class: "setup-module-head" }, toggle,
          el("span", {}, el("b", {}, m.name), m.intro ? el("span", { class: "setting-help" }, m.intro) : null)),
        el("div", { class: "setup-module-body" },
          m.fields.length ? groups : el("p", { class: "muted small setup-module-note" }, !m.loaded
            ? (waiting ? MP.t("Not loaded now. Its settings from the lab file are applied when it is loaded, after a restart.")
              : MP.t("Not loaded now: its questions appear here once it is turned on and the server has restarted."))
            : MP.t("Nothing to set up."))));
      toggle.addEventListener("change", () => card.classList.toggle("is-off", !toggle.checked));
      return card;
    }));
  }

  // ---- reading the form back into a lab ----------------------------------------------------------------------------
  function collect() {
    const out = clone(lab);
    for (const inp of baseInputs()) {
      const [s, k] = inp.name.split(".");
      let v = inp.value;
      if (inp.dataset.type === "int") {
        if (v === "") { if (out[s]) delete out[s][k]; continue; }
        v = parseInt(v, 10);
      } else v = v.trim();
      out[s] = out[s] || {};
      out[s][k] = v;
    }
    out.tool_sources = $$(".setup-source", form).map((row) => ({
      name: $("[name='src.name']", row).value.trim(), url: $("[name='src.url']", row).value.trim(),
      branch: $("[name='src.branch']", row).value.trim() || "main", trusted: $("[name='src.trusted']", row).checked,
    })).filter((s) => s.name || s.url);
    const chosen = info.modules.filter((m) => form.elements[`module.${m.id}.__on`].checked).map((m) => m.id);
    out.modules = { on: chosen.length === info.modules.length ? "all" : chosen };
    out.module = out.module || {};
    for (const m of info.modules) {
      if (!m.fields.length) continue;
      const t = {};
      for (const f of m.fields) {
        const inp = form.elements[`module.${m.id}.${f.key}`];
        if (f.kind === "bool") t[f.key] = inp.checked;
        else if (f.kind === "choice") {
          const c = f.choices.find(([v]) => String(v) === inp.value);
          if (c) t[f.key] = c[0];
        } else if (f.kind === "list") t[f.key] = inp.value.split("\n").map((x) => x.trim()).filter(Boolean);
        else if (f.kind === "number") { if (inp.value !== "") t[f.key] = Number(inp.value); }
        else t[f.key] = inp.value.trim();
      }
      out.module[m.id] = t;
    }
    return out;
  }

  // ---- loading a lab file ------------------------------------------------------------------------------------------
  function loaded(r) {
    lab = merge(info.current, r.lab);
    source = r.source;
    $("#setup-source").textContent = MP.t("Loaded: {name}", { name: r.source });
    $("#setup-warnings").replaceChildren(...(r.warnings || []).map((w) => el("div", { class: "alert alert-warning" }, MP.icon("alert", 16), el("span", {}, w))));
    fill();
    MP.toast(MP.t("Loaded — check the steps below, then Check"));
  }

  async function read(body) {
    try { loaded(await api("/api/setup/read", { json: body })); }
    catch (err) { $("#setup-warnings").replaceChildren(errorBox(err.message)); }
  }

  $("#setup-load-file").addEventListener("click", () => { if ($("#setup-files").value) read({ path: $("#setup-files").value }); });
  $("#setup-load-url").addEventListener("click", () => { if ($("#setup-url").value.trim()) read({ url: $("#setup-url").value.trim() }); });
  $("#setup-upload").addEventListener("change", (e) => {
    const file = e.currentTarget.files[0];
    if (!file) return;
    const r = new FileReader();
    r.onload = () => read({ text: String(r.result), name: file.name });
    r.readAsText(file);
  });
  $("#setup-load-current").addEventListener("click", () => {
    lab = clone(info.current); source = "page";
    $("#setup-source").textContent = ""; $("#setup-warnings").replaceChildren();
    fill();
  });
  $("#setup-add-source").addEventListener("click", () => {
    $(".setup-none", form)?.remove();
    $("#setup-sources").append(sourceRow({ branch: "main", trusted: !(lab.tool_sources || []).length }, false));
    unchecked();
  });

  // ---- check, set up --------------------------------------------------------------------------------------------------
  const STATUS = () => ({ change: MP.t("will change"), same: MP.t("stays"), skip: MP.t("left alone"), later: MP.t("later"),
    error: MP.t("can't be set"), done: MP.t("done") });
  const ACCESS = () => ({ public: MP.t("can be read (public)"), token: MP.t("can be read with the server's GitHub token"),
    folder: MP.t("a git folder on this computer"), unreachable: MP.t("can't be read") });
  const show = (v) => Array.isArray(v) ? v.join(", ") : (v === "" || v === null || v === undefined ? "—" : typeof v === "boolean" ? (v ? MP.t("yes") : MP.t("no")) : String(v));

  function rowsTable(rows, hideSame) {
    const shown = hideSame ? rows.filter((r) => r.status !== "same") : rows;
    const same = rows.length - shown.length;
    const table = el("table", { class: "setup-rows" }, el("tbody", {}, shown.map((r) => el("tr", { class: `is-${r.status}` },
      el("td", {}, el("span", { class: `setup-status is-${r.status}` }, STATUS()[r.status] || r.status)),
      el("td", {}, r.label),
      el("td", { class: "setup-change" }, r.status === "same" ? show(r.new) : el("span", {}, el("span", { class: "muted" }, show(r.old)), " → ", el("b", {}, show(r.new)))),
      el("td", { class: "muted small" }, r.note || "")))));
    const out = [shown.length ? table : el("p", { class: "muted" }, MP.t("Nothing would change."))];
    if (hideSame && same) {
      out.push(el("button", { type: "button", class: "btn btn-small", onclick: (e) => e.currentTarget.parentNode.replaceWith(el("div", {}, rowsTable(rows, false))) },
        MP.tn(same, "Show the {n} setting that stays as it is", "Show the {n} settings that stay as they are")));
    }
    return el("div", {}, out);
  }

  function unchecked() { $("#setup-apply-btn").disabled = true; }
  form.addEventListener("input", unchecked);
  form.addEventListener("change", unchecked);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#setup-check-btn");
    btn.disabled = true;
    $("#setup-result").replaceChildren(el("div", { class: "muted pad" }, MP.t("Checking… (reaching each repository can take a few seconds)")));
    try {
      const r = await api("/api/setup/plan", { json: { lab: collect() } });
      const errors = r.rows.filter((x) => x.status === "error").length;
      const changes = r.rows.filter((x) => x.status === "change" || x.status === "later").length;
      $("#setup-result").replaceChildren(...[
        ...(r.warnings || []).map((w) => el("div", { class: "alert alert-warning" }, MP.icon("alert", 16), el("span", {}, w))),
        errors ? el("div", { class: "alert alert-error" }, MP.icon("alert", 16), el("span", {}, MP.tn(errors, "{n} setting can't be set as it is: fix it above, or Set up leaves it out.", "{n} settings can't be set as they are: fix them above, or Set up leaves them out."))) : null,
        el("h3", { class: "setup-h3" }, MP.tn(changes, "{n} change", "{n} changes")),
        rowsTable(r.rows, true),
        r.access.length ? el("h3", { class: "setup-h3" }, MP.t("Repositories")) : null,
        r.access.length ? el("ul", { class: "setup-access" }, r.access.map((a) => el("li", { class: `is-${a.status}` },
          MP.icon(a.status === "unreachable" ? "alert" : "check", 14), el("span", {}, el("b", {}, a.what), " ", el("code", {}, a.url), " — ", ACCESS()[a.status] || a.status,
            a.note ? el("small", { class: "muted" }, " (", a.note, ")") : null)))) : null,
        r.access.some((a) => a.status === "unreachable")
          ? el("p", { class: "setting-help" }, MP.t("A repository that can't be read: check its address, and that the server's GitHub token (on the Mac: the MISTER PLIS app → Change GitHub Token) includes it. The rest can be set up anyway.")) : null,
      ].filter(Boolean));
      $("#setup-apply-btn").disabled = false;
    } catch (err) { $("#setup-result").replaceChildren(errorBox(err.message)); }
    btn.disabled = false;
  });

  async function waitForRestart(prev, box) {
    box.replaceChildren(el("div", { class: "muted pad" }, MP.t("Restarting… this page goes on by itself.")));
    const t0 = Date.now();
    while (Date.now() - t0 < 120000) {
      await new Promise((r) => setTimeout(r, 1000));
      try {
        const v = await api("/api/version");
        if (v.started !== prev.started) { location.href = "/"; return; }
      } catch (_) { /* still down */ }
    }
    box.replaceChildren(errorBox(MP.t("The server did not come back within 2 minutes. Check the log on the server (logs/server.log).")));
  }

  $("#setup-apply-btn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const r = await api("/api/setup/apply", { json: { lab: collect(), source } });
      const failed = r.rows.filter((x) => x.status === "error").length;
      const next = el("div", { class: "sync-actions" });
      if (r.restart) {
        next.append(el("button", { type: "button", class: "btn btn-primary", onclick: async () => {
          const prev = await api("/api/version");
          const d = await api("/api/system/restart", { method: "POST" });
          if (d.restarting) waitForRestart(prev, next); else MP.toast(MP.t("Running in dev mode (--reload): restart it from the terminal"), 6000);
        } }, MP.icon("sync", 16), MP.t("Restart now")));
      } else next.append(el("a", { class: "btn btn-primary", href: "/" }, MP.t("Open MISTER PLIS")));
      $("#setup-result").replaceChildren(
        el("div", { class: `alert ${failed ? "alert-warning" : "alert-success"}` }, MP.icon(failed ? "alert" : "check", 16),
          el("span", {}, failed ? MP.tn(failed, "Set up, except {n} setting that couldn't be set (below).", "Set up, except {n} settings that couldn't be set (below).") : MP.t("Set up."),
            r.restart ? " " + MP.t("Restart the server to load the tools and modules.") : "")),
        rowsTable(r.rows, true), next);
      $("#setup-skip")?.remove();
      info = await api("/api/setup");
    } catch (err) { $("#setup-result").replaceChildren(errorBox(err.message)); btn.disabled = false; }
  });

  $("#setup-skip")?.addEventListener("click", async () => {
    try { await api("/api/setup/skip", { method: "POST" }); location.href = "/"; } catch (err) { MP.toast(err.message, 5000); }
  });

  $("#setup-download").addEventListener("click", async () => {
    try {
      const res = await fetch("/api/setup/file", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lab: collect() }) });
      if (!res.ok) throw new Error((await res.json()).error || res.statusText);
      const name = (res.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || "lab.toml";
      const a = el("a", { href: URL.createObjectURL(await res.blob()), download: name });
      document.body.append(a); a.click(); a.remove();
    } catch (err) { MP.toast(err.message, 5000); }
  });

  // ---- everything from another server (Settings → Server & updates → Move this server, there) --------------------------
  $("#setup-transfer-check").addEventListener("click", async (e) => {
    const dir = $("#setup-transfer").value.trim();
    const box = $("#setup-transfer-result");
    if (!dir) return;
    const btn = e.currentTarget;
    btn.disabled = true;
    box.replaceChildren(el("div", { class: "muted setup-transfer-box" }, MP.t("Checking every file…")));
    try {
      const s = await api("/api/transfer/check", { json: { dir } });
      const when = s.created ? MP.datetime(s.created) : "";
      const go = el("button", { type: "button", class: "btn btn-primary", disabled: s.here_has_jobs }, MP.icon("download", 16), MP.t("Bring it here"));
      go.addEventListener("click", async () => {
        if (!confirm(MP.t("Bring everything from {lab} into this server and restart it? What is here now is kept, renamed.", { lab: s.lab_name || s.path }))) return;
        go.disabled = true;
        try {
          const prev = await api("/api/version");
          const r = await api("/api/transfer/import", { json: { dir } });
          box.replaceChildren(el("div", { class: "alert alert-success setup-transfer-box" }, MP.icon("check", 16),
            el("span", {}, MP.tn(r.jobs, "Brought in, with {n} job.", "Brought in, with {n} jobs."), " ",
              r.restarting ? MP.t("Restarting… this page goes on by itself.") : MP.t("Running in dev mode (--reload): restart it from the terminal"))));
          if (r.restarting) {
            const t0 = Date.now();
            while (Date.now() - t0 < 120000) {
              await new Promise((ok) => setTimeout(ok, 1000));
              try { if ((await api("/api/version")).started !== prev.started) { location.href = "/"; return; } } catch (_) { /* still down */ }
            }
          }
        } catch (err) { box.replaceChildren(errorBox(err.message)); go.disabled = false; }
      });
      box.replaceChildren(el("div", { class: "setup-transfer-box" },
        el("div", { class: "setup-transfer-head" }, MP.icon("check", 16), el("span", {}, el("b", {}, s.lab_name || MP.t("(no lab name)")), " — ",
          MP.t("from {host}, copied {when}", { host: (s.from || {}).host || "?", when }))),
        el("div", { class: "muted small" }, MP.tn(s.jobs, "{n} job", "{n} jobs"), " · ", MP.tn(s.files, "{n} file", "{n} files"), " · ", MP.bytes(s.bytes),
          " · ", MP.t("every file checked")),
        s.here_has_jobs ? el("div", { class: "alert alert-warning" }, MP.icon("alert", 16),
          el("span", {}, MP.t("This server has jobs already: a copied server is brought only into a new one."))) : null,
        el("p", { class: "setting-help" }, MP.t("Everything comes as it was: the lab's settings, jobs, and what each module keeps. The steps below aren't needed then. Tool sources are fetched again when the server restarts, with this server's GitHub token.")),
        el("div", { class: "sync-actions" }, go)));
    } catch (err) { box.replaceChildren(errorBox(err.message)); }
    btn.disabled = false;
  });

  // ---- start ----------------------------------------------------------------------------------------------------------
  (async function start() {
    try { info = await api("/api/setup"); } catch (err) { $("#setup").prepend(errorBox(err.message)); return; }
    if (info.code_needed) {  // a new server, set up from another computer: its setup code first (mister_plis/setupcode.py)
      const box = $("#setup-code"), input = $("#setup-code-input");
      box.hidden = false;
      $("#setup").style.display = "none";
      const go = async () => {
        try { await api("/api/setup/code", { json: { code: input.value } }); location.reload(); }
        catch (err) { MP.toast(err.message, 5000); input.select(); }
      };
      $("#setup-code-go").addEventListener("click", go);
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
      input.focus();
      return;
    }
    $("#setup-files").replaceChildren(el("option", { value: "" }, info.files.length ? MP.t("Choose…") : MP.t("none in this copy (labs/)")),
      ...info.files.map((f) => el("option", { value: f.path }, f.name ? `${f.name} — ${f.path}` : f.path)));
    lab = clone(info.current);
    fill();
  })();
})();
