// Job rows (used on Home, tool pages and the Jobs page) + the Jobs page itself (search, filters).
(function () {
  const { $, $$, el, api } = MP;

  function summary(job) {
    const files = Object.values(job.files || {}).flat().map((f) => f.name);
    if (files.length) return files.length > 2 ? `${files[0]}, ${files[1]} +${files.length - 2}` : files.join(", ");
    const p = Object.entries(job.params || {}).filter(([, v]) => v !== "" && v !== null && typeof v !== "object").slice(0, 3);
    return p.map(([k, v]) => `${k}=${v}`).join(" · ");
  }

  const STATUS = { queued: "Queued", running: "Running", done: "Done", failed: "Failed", cancelled: "Cancelled", interrupted: "Interrupted" };

  MP.jobRow = function (job) {
    const active = job.status === "running" || job.status === "queued";
    const status = MP.t(STATUS[job.status] || job.status);
    const when = active ? (job.message || status) : `${job.status === "done" ? "" : status + " · "}${MP.ago(job.finished || job.created)}`;
    return el("a", { class: "job-row", href: `/tool/${job.tool_id}?job=${job.id}`, title: `${MP.datetime(job.created)} · ${job.id}` },
      el("span", { class: `dot ${job.status}`, title: status }),
      el("div", {}, el("div", { class: "jtool" }, MP.t(job.tool_name), job.title ? el("span", { class: "jtitle" }, ` — ${job.title}`) : null),
        active && job.progress != null ? el("div", { class: "jprog" }, el("div", { style: `width:${Math.round(job.progress * 100)}%` })) : null),
      el("div", { class: "jsum", title: summary(job) }, job.keyword ? el("span", { class: "jkey" }, job.keyword) : null, summary(job)),
      el("div", { class: "jtime" }, when, job.user ? ` · ${job.user}` : "", job.n_outputs && !active ? " · " + MP.t("results: {n}", { n: job.n_outputs }) : "",
        job.backed_up ? el("span", { class: "jbak", title: MP.t("Backed up {when}", { when: MP.datetime(typeof job.backed_up === "object" ? job.backed_up.at : job.backed_up) }) }, " · " + MP.t("backed up")) : "",
        ...MP.hooks.jobMarks.map((fn) => fn(job)).filter(Boolean)));
  };

  // Home: recent results strip
  if (document.body.dataset.page === "home") {
    api("/api/jobs?limit=6").then((d) => {
      if (!d.jobs.length) return;
      $("#recent").hidden = false;
      $("#recent-list").replaceChildren(...d.jobs.map(MP.jobRow));
    }).catch(() => { });
  }

  // Jobs page
  if (document.body.dataset.page === "jobs") {
    const url = new URLSearchParams(location.search);
    const NONAME = "\u0000";
    const st = {
      status: "all",
      q: url.get("q") || "",
      person: url.get("person") ?? "",  // "" = everyone, NONAME = jobs without a name
      tool: url.get("tool") || "",
      days: "", from: "", to: "",
      flags: {},  // flag filters added by modules (data-flag segments): flag → "in" | "out" | ""
    };
    let all = [];
    const personSel = $("#job-person"), toolSel = $("#job-tool"), qInput = $("#job-q");
    const fromInput = $("#job-from"), toInput = $("#job-to");
    qInput.value = st.q;

    const haystack = new WeakMap();
    const textOf = (j) => {
      if (!haystack.has(j)) {
        const files = Object.values(j.files || {}).flat().map((f) => f.name);
        const params = Object.values(j.params || {}).filter((v) => typeof v === "string" || typeof v === "number");
        haystack.set(j, MP.fold([j.id, j.tool_name, MP.t(j.tool_name), j.tool_id, j.user, j.keyword, j.title, ...files, ...(j.result_files || []), ...params].join(" \u0001 ")));
      }
      return haystack.get(j);
    };

    const fillSelects = () => {
      const names = [...new Set(all.map((j) => j.user).filter(Boolean))].sort((a, b) => a.localeCompare(b));
      const mine = MP.prefs.name;
      if (st.person && st.person !== NONAME && !names.includes(st.person)) names.push(st.person);
      const opts = [el("option", { value: "" }, MP.t("Everyone"))];
      if (mine) opts.push(el("option", { value: mine }, MP.t("Mine ({name})", { name: mine })));
      names.filter((n) => n !== mine).forEach((n) => opts.push(el("option", { value: n }, n)));
      if (all.some((j) => !j.user)) opts.push(el("option", { value: NONAME }, MP.t("No name")));
      personSel.replaceChildren(...opts);
      personSel.value = st.person;

      const tools = new Map();
      all.forEach((j) => tools.set(j.tool_id, MP.t(j.tool_name)));
      if (st.tool && !tools.has(st.tool)) tools.set(st.tool, st.tool);
      toolSel.replaceChildren(el("option", { value: "" }, MP.t("Any tool")),
        ...[...tools].sort((a, b) => a[1].localeCompare(b[1])).map(([id, name]) => el("option", { value: id }, name)));
      toolSel.value = st.tool;
    };

    const dayStart = (iso) => iso ? new Date(iso + "T00:00:00").getTime() / 1000 : null;
    const filtersOn = () => [st.person, st.tool, st.days || st.from || st.to, ...Object.values(st.flags)].filter(Boolean).length;

    const syncUrl = () => {
      const q = new URLSearchParams();
      if (st.q) q.set("q", st.q);
      if (st.person) q.set("person", st.person);
      if (st.tool) q.set("tool", st.tool);
      history.replaceState(null, "", location.pathname + (q.toString() ? `?${q}` : ""));
    };

    const render = () => {
      const keep = (j) => st.status === "all" ? true
        : st.status === "active" ? ["running", "queued"].includes(j.status)
        : st.status === "failed" ? ["failed", "interrupted", "cancelled"].includes(j.status)
        : j.status === st.status;
      const who = (j) => !st.person || (st.person === NONAME ? !j.user : j.user === st.person);
      let since = dayStart(st.from), until = st.to ? dayStart(st.to) + 86400 : null;
      if (st.days) { const d = new Date(); d.setHours(0, 0, 0, 0); since = d.getTime() / 1000 - (Number(st.days) - 1) * 86400; until = null; }
      const words = MP.fold(st.q).split(/\s+/).filter(Boolean);
      const rows = all.filter((j) => keep(j) && who(j)
        && (!st.tool || j.tool_id === st.tool)
        && (since == null || j.created >= since) && (until == null || j.created < until)
        && Object.entries(st.flags).every(([flag, want]) => !want || (want === "in") === !!j[flag])
        && words.every((w) => textOf(j).includes(w)));
      const n = filtersOn();
      $("#job-filters-n").hidden = !n;
      $("#job-filters-n").textContent = n;
      $("#job-count").textContent = (words.length || n || st.status !== "all") && all.length
        ? MP.t("{shown} of {total} jobs", { shown: rows.length, total: all.length }) : "";
      $("#jobs-list").replaceChildren(...(rows.length ? rows.map(MP.jobRow)
        : [el("div", { class: "muted pad" }, all.length ? MP.t("No job matches — try fewer words or clear the filters.") : MP.t("No jobs here yet."))]));
    };

    let timer = null;
    const load = async () => {
      clearTimeout(timer);
      try {
        const d = await api("/api/jobs?limit=2000");
        all = d.jobs;
        fillSelects();
        render();
      } catch (_) { }
      // poll fast while something runs, slowly otherwise
      const busy = all.some((j) => j.status === "running" || j.status === "queued");
      timer = setTimeout(() => { if (!document.hidden) load(); else timer = setTimeout(load, 4000); }, busy ? 4000 : 20000);
    };

    qInput.addEventListener("input", () => { st.q = qInput.value.trim(); syncUrl(); render(); });
    personSel.addEventListener("change", () => { st.person = personSel.value; syncUrl(); render(); });
    toolSel.addEventListener("change", () => { st.tool = toolSel.value; syncUrl(); render(); });
    const pickSeg = (seg, btn) => $$(`#${seg} button`).forEach((x) => x.classList.toggle("active", x === btn));
    $$("#job-filter button").forEach((b) => b.addEventListener("click", () => { pickSeg("job-filter", b); st.status = b.dataset.filter; render(); }));
    $$("#job-when button").forEach((b) => b.addEventListener("click", () => {
      pickSeg("job-when", b); st.days = b.dataset.days; st.from = st.to = ""; fromInput.value = toInput.value = ""; render();
    }));
    [fromInput, toInput].forEach((inp) => inp.addEventListener("change", () => {
      st.from = fromInput.value; st.to = toInput.value; st.days = "";
      pickSeg("job-when", st.from || st.to ? null : $('#job-when [data-days=""]'));
      render();
    }));
    $$("[data-flag]").forEach((seg) => seg.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      seg.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
      st.flags[seg.dataset.flag] = b.dataset.want;
      render();
    })));
    const panel = $("#job-filters"), fbtn = $("#job-filters-btn");
    const showPanel = (on) => { panel.hidden = !on; fbtn.setAttribute("aria-expanded", on ? "true" : "false"); fbtn.classList.toggle("active", on); };
    fbtn.addEventListener("click", () => showPanel(panel.hidden));
    $("#job-filters-clear").addEventListener("click", () => {
      Object.assign(st, { person: "", tool: "", days: "", from: "", to: "", flags: {} });
      personSel.value = toolSel.value = fromInput.value = toInput.value = "";
      pickSeg("job-when", $('#job-when [data-days=""]'));
      $$("[data-flag]").forEach((seg) => seg.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x.dataset.want === "")));
      syncUrl();
      render();
    });
    if (st.person || st.tool) showPanel(true);
    load();
  }
})();

// Jobs page → Import from backup: jobs in the backup folder (also those cleaned up from here), brought back as they were.
(function () {
  const { $, el, api } = MP;
  const btn = $("#job-import-btn"), panel = $("#job-import");
  if (!btn || !panel) return;
  const list = $("#imp-list"), q = $("#imp-q"), go = $("#imp-go"), sum = $("#imp-sum");
  const picked = new Set();
  let timer = null;

  function row(r) {
    const here = r.in_jobs;
    const box = el("input", { type: "checkbox", disabled: here, checked: picked.has(r.folder), "aria-label": r.id });
    box.addEventListener("change", () => { box.checked ? picked.add(r.folder) : picked.delete(r.folder); update(); });
    const line = el("label", { class: "imp-row" + (here ? " is-here" : "") },
      box,
      el("div", {}, el("div", {}, MP.t(r.tool_name || "") || r.tool_id || "—", r.title ? el("span", { class: "jtitle" }, ` — ${r.title}`) : null,
        r.keyword ? el("span", { class: "jkey" }, " " + r.keyword) : null), el("div", { class: "imp-id" }, r.id)),
      el("div", { class: "imp-who" }, r.user || r.person || "", r.created ? el("div", { class: "muted" }, MP.datetime(r.created)) : null),
      el("div", { class: "imp-tag" }, here ? MP.t("in Jobs & results") : r.format === 0 ? MP.t("older backup") : ""));
    return line;
  }

  function update() {
    go.disabled = !picked.size;
    go.textContent = picked.size ? MP.tn(picked.size, "Bring back {n} job", "Bring back {n} jobs") : MP.t("Bring back");
  }

  async function load(rescan) {
    list.replaceChildren(el("div", { class: "imp-empty" }, MP.t("Loading…")));
    try {
      const d = await api(`/api/backup/catalogue?q=${encodeURIComponent(q.value.trim())}${rescan ? "&rescan=1" : ""}`);
      if (!d.available) { list.replaceChildren(el("div", { class: "imp-empty" }, MP.t("No backup folder is set, or it is not available (Settings → Jobs & backup)."))); sum.textContent = ""; return; }
      list.replaceChildren(...(d.rows.length ? d.rows.map(row) : [el("div", { class: "imp-empty" }, MP.t("Nothing found in the backup folder."))]));
      sum.textContent = d.total > d.rows.length ? MP.t("{shown} of {total} shown — search to narrow", { shown: d.rows.length, total: d.total }) : MP.tn(d.total, "{n} job in the backup folder", "{n} jobs in the backup folder");
    } catch (e) { list.replaceChildren(el("div", { class: "imp-empty" }, e.message)); }
  }

  btn.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    btn.setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) { load(false); q.focus(); }
  });
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => load(false), 250); });
  $("#imp-rescan").addEventListener("click", () => load(true));
  go.addEventListener("click", async () => {
    go.disabled = true;
    go.textContent = MP.t("Bringing back…");
    try {
      const r = await api("/api/jobs/import", { json: { folders: [...picked] } });
      MP.toast(MP.tn(r.imported.length, "Brought back {n} job", "Brought back {n} jobs") + (r.errors.length ? " — " + r.errors.join("; ") : ""), 8000);
      picked.clear();
      setTimeout(() => location.reload(), 900);
    } catch (e) { MP.toast(e.message, 6000); update(); }
  });
})();
