// Reagents and Consumables, the lab-wide parts, on their own Settings tab: the inventory's GitHub sync and its recent
// changes (one repository for both), the tidy-up, and which columns are shown, filtered and listed (one panel each).
// The pages themselves are in reagents.js.
(function () {
  const { $, el, api } = MP;
  if (!$("#rg-sync") && !$("#rg-fields") && !$("#cs-fields")) return;
  const put = (node, ...kids) => node.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
  const errorBox = (err) => el("div", { class: "alert alert-error" }, MP.icon("alert", 16), el("span", {}, err.message || String(err)));
  const GROUPS = () => [["identification", MP.t("Identification")], ["status", MP.t("Status")], ["storage", MP.t("Storage")],
    ["borrowing", MP.t("Borrowing")], ["hazards", MP.t("Hazards")], ["producers", MP.t("Producers")], ["ordering", MP.t("Ordering")],
    ["notes", MP.t("Notes")], ["other", MP.t("Other")]];

  async function syncPanel() {
    const box = $("#rg-sync");
    let st;
    try { st = await api("/api/reagents/status"); } catch (err) { put(box, errorBox(err)); return; }
    const inFolder = !!st.folder;  // repo is a git repository in a folder on this machine, not on GitHub
    const log = el("div", { class: "sync-log", hidden: true });
    const syncBtn = el("button", { class: "btn btn-primary", disabled: !st.enabled }, MP.icon("sync", 16), inFolder ? MP.t("Sync with the folder") : MP.t("Sync with GitHub"));
    syncBtn.addEventListener("click", async () => {
      syncBtn.disabled = true; log.hidden = false; put(log, el("div", { class: "muted" }, MP.t("Syncing…")));
      try {
        const r = await api("/api/reagents/sync", { method: "POST" });
        put(log, ...r.steps.map((s) => el("div", { class: "step" }, el("div", { class: `step-head ${s.ok ? "ok" : "bad"}` }, MP.icon(s.ok ? "check" : "alert", 14), s.name), s.output ? el("pre", {}, s.output) : null)));
        if (r.ok) { MP.toast(MP.t("Synced")); setTimeout(() => { syncPanel(); historyPanel(); }, 600); }
      } catch (err) { put(log, errorBox(err)); }
      syncBtn.disabled = false;
    });
    const push = el("input", { type: "checkbox" }); push.checked = st.push;
    push.addEventListener("change", async () => { try { await api("/api/reagents/settings", { json: { push: push.checked } }); MP.toast(MP.t("Saved")); } catch (err) { MP.toast(err.message, 5000); push.checked = !push.checked; } });
    const auto = el("select", {}, [[0, MP.t("only by hand")], [15, MP.t("every 15 min")], [60, MP.t("every hour")], [240, MP.t("every 4 hours")]].map(([v, t]) => el("option", { value: v }, t)));
    auto.value = String(st.auto_minutes);
    auto.addEventListener("change", async () => { try { await api("/api/reagents/settings", { json: { auto_minutes: +auto.value } }); MP.toast(MP.t("Saved")); } catch (err) { MP.toast(err.message, 5000); } });
    // the repository: changed here (the old copy is kept on the server), unless config.toml sets it on this computer
    const repoForm = el("form", { class: "rg-repo-form", hidden: true });
    const repoIn = el("input", { type: "text", value: st.repo || "", placeholder: "https://github.com/your-lab/inventory.git", "aria-label": MP.t("Repository") });
    const branchIn = el("input", { type: "text", value: st.branch || "main", placeholder: "main", "aria-label": MP.t("Branch") });
    put(repoForm,
      el("label", {}, el("span", {}, MP.t("Repository")), repoIn),
      el("label", {}, el("span", {}, MP.t("Branch")), branchIn),
      el("small", { class: "muted" }, MP.t("A GitHub address, or a folder on this computer with git in it; empty keeps the inventory on this server only. What was synced from the current repository is kept on the server, set aside, and the new one comes in at the next sync.")),
      el("div", { class: "sync-actions" },
        el("button", { class: "btn btn-primary", type: "submit" }, MP.t("Use this repository")),
        el("button", { class: "btn", type: "button", onclick: () => { repoForm.hidden = true; } }, MP.t("Cancel"))));
    repoForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const r = await api("/api/reagents/repository", { json: { repo: repoIn.value.trim(), branch: branchIn.value.trim() } });
        MP.toast(r.kept ? MP.t("Saved. The old copy is kept as {path}", { path: r.kept }) : MP.t("Saved"), r.kept ? 8000 : 3000);
        syncPanel(); historyPanel();
      } catch (err) { MP.toast(err.message, 6000); }
    });
    const changeRepo = st.locked ? el("small", { class: "muted" }, " ", MP.t("(set in config.toml on this computer)"))
      : el("button", { class: "btn btn-small", type: "button", onclick: () => { repoForm.hidden = !repoForm.hidden; } }, MP.t("Change…"));
    const kv = [
      [inFolder ? MP.t("Folder (git repository)") : MP.t("GitHub repository"),
        el("span", {}, st.enabled ? el("code", {}, st.repo) : el("span", { class: "muted" }, MP.t("none: the inventory is on this server only")), " ", changeRepo)],
      [MP.t("Branch"), el("code", {}, st.branch)],
      [MP.t("Workbook"), st.has_workbook ? el("span", {}, el("code", {}, st.workbook), " · ", MP.tn(st.reagents, "{n} reagent", "{n} reagents"), " · ", MP.tn(st.columns, "{n} column", "{n} columns"))
        : el("span", {}, el("span", { class: "muted" }, st.enabled && !st.synced_at ? MP.t("not here yet — sync to download it") : MP.t("none yet")), " ",
          !st.enabled || st.synced_at ? el("button", { class: "btn btn-small", type: "button", onclick: async (e) => {
            e.currentTarget.disabled = true;
            try { await api("/api/reagents/start", { method: "POST" }); MP.toast(MP.t("An empty inventory is ready")); syncPanel(); historyPanel(); }
            catch (err) { MP.toast(err.message, 6000); e.currentTarget.disabled = false; }
          } }, MP.t("Start an empty inventory")) : null)],
      ...(st.others || []).filter((o) => o.kind === "consumable").map((o) => [MP.t("Consumables"), o.has_workbook
        ? el("span", {}, el("code", {}, o.workbook), " · ", MP.tn(o.rows, "{n} consumable", "{n} consumables"), " · ", MP.tn(o.columns, "{n} column", "{n} columns"))
        : el("span", { class: "muted" }, MP.t("started by itself once the inventory is here"))]),
      [MP.t("Last change"), st.head ? `${st.head.subject} — ${st.head.author}, ${MP.datetime(st.head.at)}` : "—"],
      [MP.t("Last sync"), st.synced_at ? MP.datetime(st.synced_at) : MP.t("never")],
    ];
    if (st.enabled && st.has_workbook) kv.push([MP.t("Waiting"), inFolder
      ? MP.t("{a} change(s) here not in the folder yet · {b} in the folder not here yet (at the last sync)", { a: st.ahead, b: st.behind })
      : MP.t("{a} change(s) here not on GitHub yet · {b} on GitHub not here yet (at the last sync)", { a: st.ahead, b: st.behind })]);
    kv.push([MP.t("On the server"), el("code", {}, st.local)]);
    put(box,
      el("div", { class: "panel-head" }, el("h2", {}, MP.icon("flask", 18), inFolder ? MP.t("Reagents and consumables: inventory in a folder") : MP.t("Reagents and consumables: inventory on GitHub")), el("span", { class: `badge ${st.enabled ? "ok" : ""}` }, st.enabled ? MP.t("connected") : MP.t("local only"))),
      el("p", { class: "panel-text" }, inFolder ? MP.t("The inventory is the lab's workbook in a git repository in a folder on this computer. Every change made here is saved as a commit with your name, and written into the folder shortly after (only if nobody has uncommitted edits there). Sync brings in what was committed in the folder: edits of different cells are merged; the same cell changed differently on both sides stops the sync and is named.") : MP.t("The inventory is the lab's workbook in a GitHub repository. Every change made here is saved in it as a commit with your name, and sent to GitHub shortly after. Sync brings in what changed there: edits of different cells are merged; the same cell changed differently on both sides stops the sync and is named.")),
      st.last_error ? el("div", { class: "alert alert-error" }, MP.icon("alert", 16), el("pre", {}, st.last_error)) : null,
      el("dl", { class: "kv" }, kv.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)])),
      repoForm,
      el("div", { class: "rg-sync-opts" },
        el("label", { class: "rg-check" }, push, el("span", {}, el("b", {}, inFolder ? MP.t("Send the lab's changes to the folder") : MP.t("Send the lab's changes to GitHub")), el("small", { class: "muted" },
          inFolder ? MP.t("On: each change is written into the folder within a minute. Off: the folder's changes come in, the lab's stay on this server. Nothing is ever forced.")
            : MP.t("On: each change goes to GitHub within a minute. Off: GitHub's changes come in, the lab's stay on this server. Nothing is ever forced.")))),
        el("label", { class: "rg-auto" }, el("span", {}, MP.t("Sync automatically")), el("div", { class: "control" }, auto))),
      el("div", { class: "sync-actions" }, syncBtn), log);
  }

  const TYPES = { text: () => MP.t("Text"), longtext: () => MP.t("Long text"), number: () => MP.t("Number"), date: () => MP.t("Date"),
    choice: () => MP.t("One of a list"), multi: () => MP.t("Several of a list"), url: () => MP.t("Link"), bool: () => MP.t("Yes / no") };
  // one panel per inventory: the reagents (#rg-fields) and the consumables (#cs-fields)
  const SPACES = () => ({
    "#rg-fields": { api: "/api/reagents", icon: "flask", title: MP.t("Reagents: fields"),
      text: MP.t("The columns of the inventory workbook. Their names are kept in its sheet “columns”. Visible: on the reagent's page and in the edit view. Quick: a filter at the top of the list. List: a column in the list by default (everyone can choose their own with Columns…). New columns are added in the workbook (see AGENTS.md in the repository).") },
    "#cs-fields": { api: "/api/consumables", icon: "box", title: MP.t("Consumables: fields"),
      text: MP.t("The columns of the consumables workbook (consumables.xlsx, in the same repository). Their names are kept in its sheet “columns”. Visible: on the consumable's page and in the edit view. Quick: a filter at the top of the list. List: a column in the list by default (everyone can choose their own with Columns…). New columns are added in the workbook.") },
  });
  async function fieldsPanel(sel) {
    const box = $(sel), sp = SPACES()[sel];
    let d;
    try { d = await api(sp.api); } catch (err) { put(box, errorBox(err)); return; }
    if (!d.ready) { put(box, el("div", { class: "panel-head" }, el("h2", {}, MP.icon(sp.icon, 18), sp.title)), el("p", { class: "panel-text pad" }, MP.t("The inventory isn't here yet. Sync it with GitHub above first."))); return; }
    const fields = d.fields.filter((f) => !(f.slot > 1));
    const quick = new Set(d.config.quick), list = new Set(d.config.list), hidden = new Set(d.config.hidden || []);
    const pdf = d.config.pdf || { source: "list", columns: [], filters: true, size: "normal" }, onPdf = new Set(pdf.columns);
    const pdfBoxes = [];
    const rows = fields.map((f) => {
      const locked = f.virtual || f.slot ? true : null;
      const Lpl = el("input", { type: "text", value: f.label_pl || "", maxlength: 80, disabled: locked, "aria-label": MP.t("Name in Polish") });
      const Len = el("input", { type: "text", value: f.label || "", maxlength: 80, disabled: locked, "aria-label": MP.t("Name in English") });
      const q = el("input", { type: "checkbox", title: MP.t("A quick filter at the top of the list") }); q.checked = quick.has(f.key);
      const l = el("input", { type: "checkbox", title: MP.t("A column in the list") }); l.checked = list.has(f.key);
      const pd = el("input", { type: "checkbox", title: MP.t("A column on the printed list (PDF)"), disabled: pdf.source === "list" ? true : null }); pd.checked = onPdf.has(f.key);
      pdfBoxes.push(pd);
      const sh = el("input", { type: "checkbox", title: sel === "#cs-fields" ? MP.t("Shown on the consumable's page and in the edit view") : MP.t("Shown on the reagent's page and in the edit view"), disabled: f.virtual || f.key === d.config.key ? true : null }); sh.checked = !hidden.has(f.key);
      const tr = el("tr", {}, el("td", {}, el("code", {}, f.slot ? f.key.replace(/^producer_1_/, "producer_N_") : f.key)),
        el("td", { class: "rg-c" }, sh), el("td", { class: "rg-c" }, q), el("td", { class: "rg-c" }, l), el("td", { class: "rg-c" }, pd),
        el("td", {}, el("div", { class: "control" }, Lpl)), el("td", {}, el("div", { class: "control" }, Len)),
        el("td", { class: "muted small" }, f.virtual ? MP.t("from other columns") : (TYPES[f.type] ? TYPES[f.type]() : f.type)),
        el("td", { class: "muted small" }, sel === "#cs-fields" && f.group === "producers" ? MP.t("Brands and suppliers") : (GROUPS().find(([g]) => g === f.group) || [0, f.group])[1]));
      tr.read = () => ({ key: f.key, label_pl: Lpl.value, label_en: Len.value, changed: !locked && (Lpl.value !== (f.label_pl || "") || Len.value !== (f.label || "")), quick: q.checked, list: l.checked, pdf: pd.checked, hidden: !sh.checked });
      return tr;
    });
    const toOrder = el("input", { type: "checkbox" }); toOrder.checked = quick.has("_to_order");
    // the printed list (the PDF button over the list): which columns, the filters named at the top, the type size
    const pdfSource = el("select", {}, [["list", MP.t("the columns shown in the list (each person's own)")], ["chosen", MP.t("the columns ticked under PDF below")]].map(([v, t]) => el("option", { value: v }, t)));
    pdfSource.value = pdf.source;
    pdfSource.addEventListener("change", () => pdfBoxes.forEach((b) => { b.disabled = pdfSource.value === "list"; }));
    const pdfFilters = el("input", { type: "checkbox" }); pdfFilters.checked = pdf.filters;
    const pdfSize = el("select", {}, [["normal", MP.t("normal")], ["large", MP.t("large — to read from a step away, e.g. on a shelf")]].map(([v, t]) => el("option", { value: v }, t)));
    pdfSize.value = pdf.size;
    const saveBtn = el("button", { type: "button", class: "btn btn-primary" }, MP.icon("check", 16), MP.t("Save"));
    saveBtn.addEventListener("click", async () => {
      const r = rows.map((tr) => tr.read());
      const keep = (old, on) => [...old.filter((k) => on.has(k)), ...[...on].filter((k) => !old.includes(k))];
      const qs = new Set(r.filter((x) => x.quick).map((x) => x.key)); if (toOrder.checked) qs.add("_to_order");
      const ls = new Set(r.filter((x) => x.list).map((x) => x.key));
      const ps = new Set(r.filter((x) => x.pdf).map((x) => x.key));
      saveBtn.disabled = true;
      try {
        const hs = new Set(r.filter((x) => x.hidden).map((x) => x.key));
        if (hs.size && r.some((x) => x.hidden && /^producer_1_/.test(x.key))) for (const x of [...hs]) if (/^producer_1_/.test(x)) for (let n = 2; n <= 5; n++) hs.add(x.replace("producer_1_", `producer_${n}_`));
        await api(`${sp.api}/fields`, { json: { columns: r.filter((x) => x.changed), display: { quick: keep(d.config.quick, qs), list: keep(d.config.list, ls), hidden: [...hs],
          pdf: { source: pdfSource.value, columns: keep(pdf.columns, ps), filters: pdfFilters.checked, size: pdfSize.value } } } });
        MP.toast(MP.t("Saved")); fieldsPanel(sel);
      } catch (err) { MP.toast(err.message, 5000); }
      saveBtn.disabled = false;
    });
    put(box,
      el("div", { class: "panel-head" }, el("h2", {}, MP.icon(sp.icon, 18), sp.title, el("span", { class: "panel-tag" }, MP.t("whole lab")))),
      el("p", { class: "panel-text" }, sp.text),
      el("label", { class: "rg-check rg-pad" }, toOrder, el("span", {}, MP.t("“To order” as a quick filter"))),
      el("div", { class: "rg-pdf-opts" },
        el("h3", {}, MP.icon("file", 15), MP.t("The printed list (PDF)")),
        el("p", { class: "muted small" }, MP.t("The PDF button over the list prints the rows it shows — filtered, in its order — e.g. everything in one cupboard, to tape to its shelf. It looks like the app's other PDFs.")),
        el("div", { class: "rg-pdf-grid" },
          el("label", {}, el("span", { class: "field-label" }, MP.t("Columns on the PDF")), el("div", { class: "control" }, pdfSource)),
          el("label", {}, el("span", { class: "field-label" }, MP.t("Text size")), el("div", { class: "control" }, pdfSize))),
        el("label", { class: "rg-check" }, pdfFilters, el("span", {}, el("b", {}, MP.t("Name the filters used")), el("small", { class: "muted" },
          MP.t("As the title (e.g. the cupboard's name) and listed at the top."))))),
      el("div", { class: "rg-fields-wrap" }, el("table", { class: "data rg-fields-table" },
        el("thead", {}, el("tr", {}, ...[MP.t("Column"), MP.t("Visible"), MP.t("Quick"), MP.t("List"), "PDF", MP.t("Name in Polish"), MP.t("Name in English"), MP.t("Kind"), MP.t("Section")].map((t) => el("th", {}, t)))),
        el("tbody", {}, rows))),
      el("div", { class: "sync-actions" }, el("span", { class: "rg-spacer" }), saveBtn));
  }

  async function historyPanel() {
    const box = $("#rg-history");
    let h;
    try { h = await api("/api/reagents/history?limit=60"); } catch (err) { put(box, errorBox(err)); return; }
    put(box, el("div", { class: "panel-head" }, el("h2", {}, MP.icon("clock", 18), MP.t("Reagents and consumables: recent changes"))),
      h.commits.length ? el("ul", { class: "rg-hist-list pad" }, h.commits.map((c) => el("li", {}, el("span", { class: "muted" }, MP.datetime(c.at)), " ", el("b", {}, c.author), " — ", c.subject)))
        : el("p", { class: "muted pad" }, MP.t("No changes yet.")));
  }


  // The tidy-up by a local model (Ollama): settings, Run now, and what the last run proposed.
  let tidyTimer = null;
  const colName = (c) => (MP.prefs.lang === "pl" ? c.label_pl : c.label) || c.label || c.column;
  const show = (v) => (v === null || v === undefined || v === "" ? el("span", { class: "muted" }, MP.t("empty")) : typeof v === "boolean" ? (v ? MP.t("yes") : MP.t("no")) : String(v));
  async function tidyPanel(d) {
    const box = $("#rg-tidy");
    if (!d) { try { d = await api("/api/reagents/tidy"); } catch (err) { put(box, errorBox(err)); return; } }
    clearTimeout(tidyTimer);
    if (d.running) tidyTimer = setTimeout(() => { tidyPanel(); syncPanel(); historyPanel(); }, 3000);
    const st = d.settings, ol = d.ollama, last = d.last;
    const save = async (changes) => {
      try { await api("/api/reagents/tidy/settings", { json: changes }); MP.toast(MP.t("Saved")); tidyPanel(); }
      catch (err) { MP.toast(err.message, 5000); tidyPanel(); }
    };
    const models = [...new Set([...(ol.models || []), ...(st.model ? [st.model] : [])])];
    const model = el("select", { disabled: !ol.enabled || null },
      el("option", { value: "" }, MP.t("no model — only the checks")), models.map((m) => el("option", { value: m }, m)));
    model.value = st.model;
    model.addEventListener("change", () => save({ model: model.value }));
    const sched = el("select", {}, [["off", MP.t("only by hand")], ["daily", MP.t("every day")], ["weekdays", MP.t("on weekdays")]].map(([v, t]) => el("option", { value: v }, t)));
    sched.value = st.schedule;
    sched.addEventListener("change", () => save({ schedule: sched.value }));
    const at = el("input", { type: "time", value: st.at, disabled: st.schedule === "off" || null });
    at.addEventListener("change", () => at.value && save({ at: at.value }));
    const apply = el("select", {}, [["checks", MP.t("format and spelling fixes; the model's corrections wait for a person")],
      ["all", MP.t("everything, the model's corrections too")], ["none", MP.t("nothing — everything waits for a person")]].map(([v, t]) => el("option", { value: v }, t)));
    apply.value = st.apply;
    apply.addEventListener("change", () => save({ apply: apply.value }));
    const runBtn = el("button", { class: "btn btn-primary", disabled: !!d.running || !d.ready || null }, MP.icon("sync", 16), MP.t("Run now"));
    runBtn.addEventListener("click", async () => {
      runBtn.disabled = true;
      try { tidyPanel(await api("/api/reagents/tidy/run", { method: "POST" })); } catch (err) { MP.toast(err.message, 5000); runBtn.disabled = false; }
    });
    const decide = async (url, json) => {
      try { tidyPanel(await api(url, { json })); syncPanel(); historyPanel(); } catch (err) { MP.toast(err.message, 6000); tidyPanel(); }
    };
    const badge = !ol.enabled ? el("span", { class: "badge" }, MP.t("no model"))
      : ol.ok ? el("span", { class: "badge ok" }, MP.t("Ollama answers")) : el("span", { class: "badge warn" }, MP.t("Ollama not answering"));
    const kv = [
      [MP.t("Model server"), ol.enabled ? el("span", {}, el("code", {}, ol.url), ol.ok ? ` · ${MP.tn(ol.models.length, "{n} model", "{n} models")}` : "")
        : el("span", { class: "muted" }, MP.t("none — set ollama_url in [module.inventory] of config.toml"))],
      [MP.t("Next run"), d.next_run ? MP.datetime(d.next_run) : MP.t("only by hand")],
      [MP.t("Last run"), last ? `${MP.datetime(last.started)} · ${last.trigger === "schedule" ? MP.t("on schedule") : (last.by || MP.t("by hand"))}${last.model ? " · " + last.model : ""}` : MP.t("never")],
    ];
    const proposals = last ? last.proposals : [];
    const waiting = proposals.filter((p) => p.status === "waiting");
    const KIND = { format: MP.t("format"), spelling: MP.t("spelling"), note: MP.t("note from the lab") };
    const STATUS = { applied: MP.t("applied"), rejected: MP.t("rejected"), failed: MP.t("failed"), waiting: MP.t("waiting") };
    const card = (p) => el("div", { class: `rg-tidy-card is-${p.status}` },
      el("div", { class: "rg-tidy-card-head" }, el("span", { class: `chip rg-tidy-kind-${p.kind}` }, KIND[p.kind] || p.kind), el("b", {}, p.title),
        el("span", { class: "grow" }), el("span", { class: "muted small" }, STATUS[p.status] || p.status, p.decided_by && p.status !== "waiting" ? ` · ${p.decided_by}` : "")),
      p.note_text ? el("blockquote", { class: "rg-tidy-note" }, el("small", { class: "muted" }, p.note_user || ""), " ", p.note_text) : null,
      el("table", { class: "data rg-tidy-changes" }, el("tbody", {}, p.changes.map((c) => el("tr", {},
        el("td", {}, el("a", { href: `/reagents/${encodeURIComponent(c.label_no)}` }, `#${c.label_no}`), " ", c.name),
        el("td", {}, colName(c)), el("td", { class: "old" }, show(c.old)), el("td", {}, "→"), el("td", { class: "new" }, show(c.new)),
        el("td", { class: "muted small" }, c.why || ""))))),
      p.error ? el("div", { class: "alert alert-error" }, MP.icon("alert", 16), el("span", {}, p.error)) : null,
      p.status === "waiting" ? el("div", { class: "sync-actions" },
        el("button", { class: "btn btn-small", onclick: () => decide(`/api/reagents/tidy/${p.id}`, { action: "reject" }) }, MP.t("Reject")),
        el("button", { class: "btn btn-small btn-primary", onclick: () => decide(`/api/reagents/tidy/${p.id}`, { action: "apply" }) }, MP.icon("check", 14), MP.t("Apply"))) : null);
    const done = proposals.filter((p) => p.status !== "waiting");
    put(box,
      el("div", { class: "panel-head" }, el("h2", {}, MP.icon("flask", 18), MP.t("Reagents: tidy-up by a local model")), badge),
      el("p", { class: "panel-text" }, MP.t("On a schedule, this server tidies the inventory: values in the wrong format (filler like “brak danych”, TRUE/FALSE or numbers stored as text, dates, lists), producers spelled several ways, and — with a model running on this machine (Ollama) — the notes in Info from the lab, turned into corrections. Every change is checked like an edit and saved as a commit, so it syncs with GitHub like the lab's own edits. A note the model finds unclear gets its question and waits for a person.")),
      ol.enabled && !ol.ok && ol.error ? el("div", { class: "alert alert-warning" }, MP.icon("alert", 16), el("span", {}, ol.error)) : null,
      el("div", { class: "rg-tidy-opts" },
        el("label", {}, el("span", { class: "field-label" }, MP.t("Model")), el("div", { class: "control" }, model)),
        el("label", {}, el("span", { class: "field-label" }, MP.t("When it runs")), el("div", { class: "rg-tidy-when" }, el("div", { class: "control" }, sched), el("div", { class: "control" }, at))),
        el("label", { class: "wide" }, el("span", { class: "field-label" }, MP.t("Applied by itself")), el("div", { class: "control" }, apply))),
      el("dl", { class: "kv" }, kv.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)])),
      d.running ? el("div", { class: "alert" }, el("span", { class: "spinner" }), el("span", {}, MP.t("Running: {step}", { step: d.running.step }))) : null,
      el("div", { class: "sync-actions" },
        waiting.length > 1 ? el("button", { class: "btn", onclick: () => confirm(MP.t("Apply all {n} waiting proposals?", { n: waiting.length })) && decide("/api/reagents/tidy/apply-all", {}) }, MP.t("Apply all")) : null,
        runBtn),
      last ? el("div", { class: "rg-tidy-last" },
        waiting.length ? el("h3", {}, MP.tn(waiting.length, "{n} proposal waiting", "{n} proposals waiting")) : null,
        waiting.map(card),
        last.unclear.length ? el("details", { class: "rg-tidy-more", open: true }, el("summary", {}, MP.tn(last.unclear.length, "{n} note unclear to the model", "{n} notes unclear to the model")),
          last.unclear.map((u) => el("div", { class: "rg-tidy-card" }, el("blockquote", { class: "rg-tidy-note" }, el("small", { class: "muted" }, u.user || ""), " ", u.text),
            el("div", { class: "rg-agent-note" }, MP.icon("info", 14), u.question)))) : null,
        last.problems.length ? el("details", { class: "rg-tidy-more" }, el("summary", {}, MP.tn(last.problems.length, "{n} value for a person to fix", "{n} values for a person to fix")),
          el("table", { class: "data rg-tidy-changes" }, el("tbody", {}, last.problems.map((x) => el("tr", {},
            el("td", {}, el("a", { href: `/reagents/${encodeURIComponent(x.label_no)}` }, `#${x.label_no}`), " ", x.name), el("td", {}, colName(x)),
            el("td", { class: "old" }, show(x.value)), el("td", { class: "muted small" }, x.problem)))))) : null,
        done.length ? el("details", { class: "rg-tidy-more" }, el("summary", {}, MP.tn(done.length, "{n} proposal dealt with", "{n} proposals dealt with")), done.map(card)) : null,
        el("details", { class: "rg-tidy-more" }, el("summary", {}, MP.t("What the last run did")),
          el("div", { class: "sync-log" }, last.steps.map((s) => el("div", { class: "step" }, el("div", { class: `step-head ${s.ok ? "ok" : "bad"}` }, MP.icon(s.ok ? "check" : "alert", 14), s.name), s.output ? el("pre", {}, s.output) : null)))))
        : null);
  }

  // each part asks the server when its tab is first opened (Settings → Reagents & consumables)
  MP.whenShown($("#rg-sync"), () => { syncPanel(); historyPanel(); });
  MP.whenShown($("#rg-tidy"), tidyPanel);
  for (const sel of ["#rg-fields", "#cs-fields"]) MP.whenShown($(sel), () => fieldsPanel(sel));
})();
