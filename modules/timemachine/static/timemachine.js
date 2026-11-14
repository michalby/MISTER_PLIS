// Time Machine: the starry sky, bringing a job here by its number, the kept results and one kept result.
(function () {
  const { $, $$, el, icon, api } = MP;
  const root = $("#tm");
  if (!root) return;
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ------------------------------------------------------------------ sky
  (function sky() {
    const cv = $("#tm-sky");
    if (!cv) return;
    const ctx = cv.getContext("2d");
    let w = 0, h = 0, stars = [], dpr = 1;
    const fromOutside = !document.referrer || !new URL(document.referrer, location.href).pathname.startsWith("/timemachine");
    let warp = !still && fromOutside ? 1 : 0;  // a short jump into hyperspace when you arrive
    const t0 = performance.now();
    const resize = () => {
      dpr = Math.min(2, window.devicePixelRatio || 1);
      w = cv.width = Math.round(innerWidth * dpr);
      h = cv.height = Math.round(innerHeight * dpr);
      cv.style.width = innerWidth + "px"; cv.style.height = innerHeight + "px";
      const n = Math.round(innerWidth * innerHeight / 4200);
      stars = Array.from({ length: n }, () => ({
        x: Math.random() * w, y: Math.random() * h, z: Math.random() ** 1.8,
        p: Math.random() * Math.PI * 2, s: 0.4 + Math.random() * 1.6,
        c: ["#ffffff", "#dbeafe", "#f5d0fe", "#fde68a", "#c7d2fe"][Math.floor(Math.random() * 5)],
      }));
    };
    let shooting = null;
    const frame = (now) => {
      const t = (now - t0) / 1000;
      if (warp) warp = Math.max(0, 1 - t / 1.43);
      ctx.clearRect(0, 0, w, h);
      const cx = w / 2, cy = h * 0.42;
      for (const s of stars) {
        if (!still) s.x -= (0.02 + s.z * 0.12) * dpr;  // a slow drift, nearer stars faster
        if (s.x < -4) { s.x = w + 4; s.y = Math.random() * h; }
        const tw = still ? 0.8 : 0.55 + 0.45 * Math.sin(t * s.s * 1.3 + s.p);
        const r = (0.35 + s.z * 1.25) * dpr;
        ctx.globalAlpha = (0.25 + 0.75 * s.z) * tw;
        ctx.fillStyle = ctx.strokeStyle = s.c;
        if (warp > 0.02) {
          const k = warp ** 2 * 0.8 * (0.3 + s.z);
          ctx.lineWidth = r;
          ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.lineTo(s.x + (s.x - cx) * k, s.y + (s.y - cy) * k); ctx.stroke();
        } else {
          ctx.beginPath(); ctx.arc(s.x, s.y, r, 0, Math.PI * 2); ctx.fill();
        }
      }
      if (!still) {  // now and then a shooting star
        if (!shooting && Math.random() < 0.0025) shooting = { x: Math.random() * w, y: Math.random() * h * 0.5, life: 1 };
        if (shooting) {
          const s = shooting;
          s.x += 9 * dpr; s.y += 3.5 * dpr; s.life -= 0.022;
          const g = ctx.createLinearGradient(s.x, s.y, s.x - 90 * dpr, s.y - 35 * dpr);
          g.addColorStop(0, "rgba(255,255,255,.9)"); g.addColorStop(1, "rgba(167,139,250,0)");
          ctx.globalAlpha = Math.max(0, s.life); ctx.strokeStyle = g; ctx.lineWidth = 1.4 * dpr;
          ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.lineTo(s.x - 90 * dpr, s.y - 35 * dpr); ctx.stroke();
          if (s.life <= 0) shooting = null;
        }
      }
      ctx.globalAlpha = 1;
      if (!still || warp) requestAnimationFrame(frame);
    };
    resize();
    addEventListener("resize", resize);
    if (warp) document.documentElement.classList.add("tm-arriving");
    setTimeout(() => document.documentElement.classList.remove("tm-arriving"), 1690);
    requestAnimationFrame(frame);
    if (still) setTimeout(() => frame(performance.now()), 50);
  })();

  // ------------------------------------------------------------------ helpers
  const inputs = (e) => e.input_files.flatMap((f) => f.names);
  const summary = (e) => {
    const f = inputs(e).length ? inputs(e) : (e.result_files || []);
    return f.length > 3 ? `${f.slice(0, 3).join(", ")} +${f.length - 3}` : f.join(", ");
  };
  const isManual = (e) => (e.entry || {}).kind === "manual" || !!(e.entry || {}).title;
  const toolName = (e) => isManual(e) ? e.tool_name : MP.t(e.tool_name);
  // a task: a result that doesn't exist yet, and who is to make it
  const isTask = (e) => (e.entry || {}).kind === "task";
  const isOpen = (e) => isTask(e) && !e.entry.done;
  const isMine = (e) => !!MP.prefs.name && MP.fold(e.entry.assignee || "") === MP.fold(MP.prefs.name);
  let people = [];
  function taskBadge(e) {
    if (!isTask(e)) return null;
    return el("span", { class: `tm-task-badge${e.entry.done ? " is-done" : ""}` }, icon(e.entry.done ? "check" : "clock", 11),
      e.entry.done ? MP.t("task done") : MP.t("task"));
  }
  // whom a task is for: picked from People (Settings → People) — the current names only, merged ones are gone
  function personInput(value = "") {
    const names = [...people];
    if (value && !names.some((n) => MP.fold(n) === MP.fold(value))) names.push(value);
    const input = el("select", { "aria-label": MP.t("Who is to do it (optional)") },
      el("option", { value: "" }, MP.t("no one yet")),
      ...names.map((n) => el("option", { value: n, selected: MP.fold(n) === MP.fold(value) }, n)));
    return { input, node: el("div", { class: "control" }, input) };
  }
  // "v2 · updated file", "v3 · re-run", "v1 · 3 versions"
  function versionBadge(e) {
    if (!(e.versions > 1 || e.version > 1)) return null;
    if (e.version === 1) return el("span", { class: "tm-ver", title: MP.t("The first version — later ones follow on the timeline") }, MP.t("v1 · {n} versions", { n: e.versions }));
    const upd = e.entry.kind === "update";
    return el("span", { class: `tm-ver is-new${upd ? " is-file" : ""}`, title: MP.t("A newer version of job {id}", { id: e.root }) },
      icon(upd ? "upload" : "sync", 11), `v${e.version} · `, upd ? MP.t("updated file") : MP.t("re-run"));
  }
  const from = (src) => src === "backup" ? MP.t("from the backup folder") : src === "upload" ? MP.t("uploaded") : MP.t("from Jobs & results");
  const monthKey = (ts) => MP.date(ts).slice(0, 7);
  const monthName = (key) => {
    const [y, m] = key.split("-").map(Number);
    try { return new Date(y, m - 1, 1).toLocaleDateString(MP.prefs.lang === "pl" ? "pl-PL" : "en-GB", { month: "long", year: "numeric" }); }
    catch (_) { return key; }
  };
  let projects = [];
  const projectById = (id) => projects.find((p) => p.id === id);
  const chip = (p, extra = {}) => el("span", { class: "tm-pchip", style: `--pc:${p.color}`, ...extra }, el("span", { class: "tm-pdot" }), p.name);

  function stats(entries) {
    const who = new Set(entries.map((e) => e.user).filter(Boolean));
    const kept = entries.filter((e) => !isTask(e)).length, open = entries.filter(isOpen).length;
    $("#tm-stats").replaceChildren(
      el("span", {}, el("b", {}, kept), " ", MP.tn(kept, "kept result", "kept results")),
      open ? el("span", {}, el("b", {}, open), " ", MP.tn(open, "open task", "open tasks")) : "",
      el("span", {}, el("b", {}, projects.length), " ", MP.tn(projects.length, "project", "projects")),
      el("span", {}, el("b", {}, who.size), " ", MP.tn(who.size, "person", "people")));
  }

  async function newProject() {
    // the colour it would get anyway is ticked; pick another before the project is made
    let color = colors.length ? colors[projects.length % colors.length] : "#7c5cff";
    const swatches = colors.map((c) => el("button", { type: "button", class: "tm-swatch", title: c, style: `--pc:${c}`, "aria-label": c,
      onclick: () => pick(c) }));
    const custom = el("input", { type: "color", value: color, "aria-label": MP.t("Another colour") });
    const pick = (c) => {
      color = c;
      swatches.forEach((b) => b.classList.toggle("is-on", b.title.toLowerCase() === c.toLowerCase()));
      custom.value = c;
    };
    custom.addEventListener("input", () => pick(custom.value));
    pick(color);
    const got = await MP.askForm({ ok: MP.t("New project"), fields: [{ label: MP.t("Name of the new project:"), maxlength: 80 }],
      extra: el("div", { class: "field tm-new-color" }, el("span", { class: "field-label" }, MP.t("Colour")),
        el("div", { class: "tm-swatches" }, ...swatches),
        el("label", { class: "tm-color-custom" }, custom, MP.t("Another colour…"))) });
    const name = got && got[0].trim();
    if (!name) return null;
    try { const p = await api("/api/tm/projects", { json: { name, color } }); MP.toast(MP.t("Project created")); return p; }
    catch (err) { MP.toast(err.message, 4000); return null; }
  }

  // a small menu under a button: pick a project (or make a new one)
  function projectMenu(anchor, list, onPick, withNew = true) {
    $$(".tm-menu").forEach((m) => m.remove());
    const menu = el("div", { class: "tm-menu", role: "menu" },
      ...list.map((p) => el("button", { type: "button", role: "menuitem", onclick: () => { menu.remove(); onPick(p); } }, chip(p))),
      list.length ? null : el("div", { class: "muted tm-menu-empty" }, MP.t("No projects yet.")),
      withNew ? el("button", { type: "button", class: "tm-menu-new", onclick: async () => { menu.remove(); const p = await newProject(); if (p) onPick(p, true); } },
        icon("tag", 14), MP.t("New project…")) : null);
    document.body.append(menu);
    const r = anchor.getBoundingClientRect();
    menu.style.left = `${Math.min(innerWidth - menu.offsetWidth - 12, r.left)}px`;
    menu.style.top = `${r.bottom + 6}px`;
    setTimeout(() => document.addEventListener("click", function close(ev) {
      if (!menu.contains(ev.target)) { menu.remove(); document.removeEventListener("click", close); }
    }), 0);
  }

  // ------------------------------------------------------------------ history (a local git log)
  async function openHistory({ job = "", project = "", title = "" } = {}) {
    const list = el("div", { class: "tm-hist-list" }, el("div", { class: "muted pad" }, MP.t("Loading…")));
    const dlg = el("dialog", { class: "dialog tm-hist" },
      el("div", { class: "tm-hist-head" },
        el("div", {}, el("h3", {}, icon("branch", 16), " ", MP.t("History")), title ? el("div", { class: "muted" }, title) : null),
        el("button", { type: "button", class: "icon-btn", "aria-label": MP.t("Close"), onclick: () => dlg.close() }, icon("x", 16))),
      list,
      el("p", { class: "muted tm-hist-foot" }, MP.t("Every change in Time Machine is a commit in a git repository on the server — nothing is sent to GitHub.")));
    dlg.addEventListener("close", () => dlg.remove());
    document.body.append(dlg);
    dlg.showModal();
    const q = new URLSearchParams({ job, project });
    try {
      const d = await api(`/api/tm/history?${q}`);
      if (!d.available) { list.replaceChildren(el("div", { class: "muted pad" }, MP.t("The history isn't available — git is not installed on the server."))); return; }
      if (!d.commits.length) { list.replaceChildren(el("div", { class: "muted pad" }, MP.t("Nothing has changed yet."))); return; }
      list.replaceChildren(...d.commits.map((c) => {
        const files = el("div", { class: "tm-hist-files", hidden: true });
        const row = el("div", { class: `tm-hist-row act-${c.action || "other"}` },
          el("span", { class: "tm-hist-node" }),
          el("div", { class: "tm-hist-body" },
            el("div", { class: "tm-hist-subject" }, c.subject),
            el("div", { class: "tm-hist-meta" }, `${c.author} · ${MP.datetime(c.at)} · `,
              el("button", { type: "button", class: "link-btn tm-hist-sha", title: MP.t("Files changed"), onclick: async () => {
                if (!files.hidden) { files.hidden = true; return; }
                try {
                  const x = await api(`/api/tm/history/${c.id}`);
                  files.replaceChildren(...(x.files.length ? x.files.map((f) => el("code", {}, f)) : [el("span", { class: "muted" }, "—")]));
                  files.hidden = false;
                } catch (err) { MP.toast(err.message); }
              } }, c.short)),
            files),
          c.restorable ? el("button", { type: "button", class: "btn btn-small", onclick: async () => {
            if (!confirm(MP.t("Bring this result back to Time Machine?"))) return;
            try { const e = await api("/api/tm/restore", { json: { commit: c.id } }); location.href = `/timemachine/${e.id}`; }
            catch (err) { MP.toast(err.message, 4000); }
          } }, MP.t("Bring back")) : null);
        return row;
      }));
    } catch (err) { list.replaceChildren(el("div", { class: "alert alert-error" }, icon("alert", 16), el("div", {}, err.message))); }
  }

  // ------------------------------------------------------------------ one kept result
  const entryId = root.dataset.entry;
  if (entryId) {
    detail(entryId);
    return;
  }

  async function detail(id) {
    const box = $("#tm-detail");
    let d, plist;
    try { [d, plist] = await Promise.all([api(`/api/tm/${id}`), api("/api/tm")]); }
    catch (e) { box.replaceChildren(el("div", { class: "alert alert-error" }, icon("alert", 16), el("div", {}, e.message))); return; }
    MP.filesFrom(d);  // its files from their own origin, where the page reaches it
    projects = plist.projects;
    people = plist.people || [];
    stats(plist.entries);
    MP.toolId = d.tool_id;
    const e = d.entry;
    let mine = [...(e.projects || [])];
    const kv = (rows) => el("dl", { class: "kv tm-kv" }, ...rows.filter(Boolean).flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
    const note = el("textarea", { rows: 3, maxlength: 4000, placeholder: MP.t("Why this result is kept, what it shows, where it is used…"), "aria-label": MP.t("Note") }, e.note || "");
    note.addEventListener("change", async () => {
      try { await api(`/api/tm/${id}`, { json: { note: note.value } }); MP.toast(MP.t("Saved")); } catch (err) { MP.toast(err.message, 4000); }
    });

    const pbox = el("div", { class: "tm-entry-projects" });
    const saveProjects = async (next) => {
      try { await api(`/api/tm/${id}`, { json: { projects: next } }); mine = next; drawProjects(); }
      catch (err) { MP.toast(err.message, 4000); }
    };
    const drawProjects = () => {
      pbox.replaceChildren(
        ...projects.map((p) => {
          const on = mine.includes(p.id);
          return el("button", { type: "button", class: `tm-pchip tm-ptoggle${on ? " is-on" : ""}`, style: `--pc:${p.color}`, "aria-pressed": on ? "true" : "false",
            title: on ? MP.t("Take it out of this project") : MP.t("Add it to this project"),
            onclick: () => saveProjects(on ? mine.filter((x) => x !== p.id) : [...mine, p.id]) }, el("span", { class: "tm-pdot" }), p.name);
        }),
        el("button", { type: "button", class: "tm-pchip tm-pnew", onclick: async () => {
          const p = await newProject();
          if (p) { projects.push(p); saveProjects([...mine, p.id]); }
        } }, "+ ", MP.t("New project")));
    };
    drawProjects();

    const exports = MP.resultExports(d);  // PDF and Excel, as above every result
    const remove = el("button", { class: "btn btn-small btn-danger", type: "button", onclick: async () => {
      if (!confirm(MP.t("Remove job {id} from Time Machine? It can be brought back from the history.", { id }))) return;
      try { await api(`/api/tm/${id}`, { method: "DELETE" }); location.href = "/timemachine"; } catch (err) { MP.toast(err.message, 4000); }
    } }, MP.t("Remove from Time Machine"));

    const head = el("section", { class: "panel tm-entry-head" },
      el("div", { class: "tm-entry-top" },
        el("div", {},
          el("p", { class: "tm-eyebrow" }, isTask(d) ? MP.t("Task") : isManual(d) ? MP.t("Added by hand") : MP.t("Kept result"),
            d.versions > 1 ? ` · ${MP.t("version {n} of {total}", { n: d.version, total: d.versions })}` : ""),
          el("div", { class: "tm-entry-title" },
            MP.titleEditor(isManual(d) ? "" : toolName(d), isManual(d) ? d.tool_name : d.title, async (title) => {
              await api(`/api/tm/${d.id}`, { json: { title } });
              return title;
            }),
            d.keyword ? el("span", { class: "jkey" }, d.keyword) : null, versionBadge(d)),
          isTask(d) ? taskDescription(d) : isManual(d) && e.description ? el("p", { class: "tm-entry-desc" }, e.description) : null,
          isTask(d) ? taskStatus(d) : null,
          el("div", { class: "tm-entry-sub" }, MP.jobNumber(d))),
        el("div", { class: "tm-entry-actions" }, ...exports,
          d.in_jobs && d.known_tool ? el("a", { class: "btn btn-small", href: `/tool/${d.tool_id}?job=${d.id}` }, MP.t("Open the original")) : null,
          remove)),
      el("div", { class: "tm-entry-grid" },
        kv([
          [isTask(d) ? MP.t("Created by") : e.source === "upload" ? MP.t("Uploaded by") : MP.t("Run by"), d.user || MP.t("(no name set)")],
          isTask(d) ? [MP.t("For"), assigneeEditor(d)] : null,
          [isTask(d) ? MP.t("Created") : MP.t("Started"), MP.datetime(d.started || d.created)],
          d.finished ? [MP.t("Finished"), MP.datetime(d.finished)] : null,
          isTask(d) ? null : [MP.t("Kept"), `${MP.datetime(e.added)}${e.added_by ? " · " + e.added_by : ""} · ${from(e.source)}`],
          d.input_files.length ? [MP.t("Input files"), el("div", {}, ...d.input_files.map((f) => el("div", {}, el("span", { class: "muted" }, `${f.label}: `), f.names.join(", "))))] : null,
        ]),
        el("div", { class: "tm-notes" },
          el("span", { class: "field-label" }, MP.t("Projects")), pbox,
          el("label", { class: "field-label" }, MP.t("Note")), el("div", { class: "control" }, note))),
      el("div", { class: "tm-entry-foot" },
        d.settings.length ? el("details", { class: "tm-settings" }, el("summary", {}, MP.tn(d.settings.length, "Settings ({n})", "Settings ({n})")),
          el("dl", { class: "kv" }, ...d.settings.flatMap((s) => [el("dt", {}, s.label), el("dd", {}, s.value)]))) : el("span"),
        el("button", { type: "button", class: "link-btn tm-history-link", onclick: () => openHistory({ job: id, title: `${MP.t(d.tool_name)} · ${id}` }) },
          icon("branch", 13), MP.t("See history"))));

    const results = el("div", { class: "results", id: "results", style: "gap:16px" });
    MP.renderOutputs(results, d.outputs || [], { skip: new Set([MP.workbookIndex(d)]) });
    const files = d.files_kept.length ? el("section", { class: "panel tm-files" },
      el("div", { class: "panel-head" }, el("h2", {}, icon("folder", 18), " ", MP.tn(d.files_kept.length, "{n} file kept", "{n} files kept"))),
      el("div", { class: "tm-file-list" }, ...d.files_kept.map((f) => el("a", { class: "tm-file", href: f.url + "?download=1" },
        icon("download", 14), el("span", {}, f.name), el("span", { class: "muted" }, MP.bytes(f.size)))))) : null;
    const empty = isTask(d) ? (e.done ? null : el("p", { class: "muted pad" }, MP.t("Nothing here yet — upload the files or add a job above, and the task is done.")))
      : el("p", { class: "muted pad" }, MP.t("No results to show — the files are listed below."));
    box.replaceChildren(head, versionsPanel(d), d.outputs && d.outputs.length ? results : empty || "", files || "");
  }

  // ---- a task's own parts: what is to be done, by whom, and whether it is done
  function taskDescription(d) {
    const p = el("p", { class: "tm-entry-desc tm-editable", title: MP.t("Click to change") }, d.entry.description || "");
    p.addEventListener("click", () => {
      const ta = el("textarea", { rows: 4, maxlength: 4000, "aria-label": MP.t("Description") }, d.entry.description || "");
      const done = async (keep) => {
        if (keep && ta.value.trim() !== d.entry.description) {
          try { d.entry = await api(`/api/tm/${d.id}`, { json: { description: ta.value } }); MP.toast(MP.t("Saved")); } catch (err) { MP.toast(err.message, 4000); return; }
        }
        p.textContent = d.entry.description;
        box.replaceWith(p);
      };
      const box = el("div", { class: "tm-desc-edit" }, el("div", { class: "control" }, ta),
        el("div", { class: "tm-vrow-actions" }, el("button", { type: "button", class: "btn btn-small btn-primary", onclick: () => done(true) }, MP.t("Save")),
          el("button", { type: "button", class: "btn btn-small", onclick: () => done(false) }, MP.t("Cancel"))));
      p.replaceWith(box);
      ta.focus();
    });
    return p;
  }

  function taskStatus(d) {
    const e = d.entry;
    if (!e.done) return el("p", { class: "tm-task-status" }, icon("clock", 14), MP.t("To do — upload the files or add a job below, and the task is done."));
    return el("p", { class: "tm-task-status is-done" }, icon("check", 14),
      MP.t("Done {when}", { when: MP.datetime(e.done) }), e.done_by ? ` · ${e.done_by}` : "", " · ",
      el("a", { class: "link", href: `/timemachine/${e.done_with}` }, MP.t("open the result")));
  }

  function assigneeEditor(d) {
    const { input, node } = personInput(d.entry.assignee || "");
    input.addEventListener("change", async () => {
      try { d.entry = await api(`/api/tm/${d.id}`, { json: { assignee: input.value.trim() } }); MP.toast(MP.t("Saved")); }
      catch (err) { MP.toast(err.message, 4000); }
    });
    return el("div", { class: "tm-assignee" }, node);
  }

  // A "drop files here" area (click to choose, too) with the chosen files listed below it.
  function dropFiles(onChange) {
    let chosen = [];
    const input = el("input", { type: "file", multiple: true, hidden: true });
    const list = el("div", { class: "files" });
    const zone = el("div", { class: "dropzone tm-drop", tabindex: 0, role: "button", "aria-label": MP.t("Choose files") },
      icon("upload", 20), el("span", {}, el("strong", {}, MP.t("Choose files")), " ", MP.t("or drop them here")));
    const draw = () => {
      list.replaceChildren(...chosen.map((f, i) => el("div", { class: "file-chip" }, icon("file", 15),
        el("span", { class: "fname", title: f.name }, f.name, el("span", { class: "fsize" }, MP.bytes(f.size))),
        el("button", { type: "button", title: MP.t("Remove"), onclick: () => { chosen.splice(i, 1); draw(); } }, icon("x", 14)))));
      zone.classList.toggle("compact", chosen.length > 0);
      onChange(chosen);
    };
    const add = (files) => {
      for (const f of files) if (!chosen.some((c) => c.name === f.name && c.size === f.size)) chosen.push(f);
      draw();
    };
    zone.addEventListener("click", () => input.click());
    zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
    input.addEventListener("change", () => { add(input.files); input.value = ""; });
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("drag");
      add([...e.dataTransfer.files].filter((f) => f.size > 0 || f.type));  // folders come through empty: skipped
    });
    return { node: el("div", { class: "tm-dropbox" }, zone, input, list), files: () => chosen };
  }

  // Upload files to the server (the usual uploads); returns their ids.
  async function uploadAll(files, status) {
    const ids = [];
    for (const [i, f] of [...files].entries()) {
      status(MP.t("Uploading {name} ({i} of {n})…", { name: f.name, i: i + 1, n: files.length }));
      const fd = new FormData();
      fd.append("file", f, f.name);
      ids.push((await api("/api/uploads", { method: "POST", body: fd })).id);
    }
    return ids;
  }

  // All versions of a kept result, and adding the next one: a changed file, or a re-run found by its number.
  function versionsPanel(d) {
    const rows = d.lineage.map((v) => el("a", { class: `tm-vrow${v.id === d.id ? " is-current" : ""}`, href: `/timemachine/${v.id}` },
      el("span", { class: `tm-vnode${v.n > 1 ? " is-version" : ""}` }),
      el("span", { class: "tm-vn" }, `v${v.n}`),
      el("span", { class: "tm-vwhat" },
        v.kind === "task" ? MP.t("task") : v.n === 1 ? MP.t("first kept") : v.kind === "update" ? MP.t("updated file") : MP.t("re-run"),
        v.files.length && v.kind === "update" ? el("span", { class: "muted" }, ` · ${v.files.join(", ")}`) : null,
        v.note ? el("span", { class: "tm-vnote" }, ` — ${v.note}`) : null),
      el("span", { class: "muted tm-vwhen" }, [v.user, MP.datetime(v.created)].filter(Boolean).join(" · "))));

    let upBtn = null;
    const drop = dropFiles((f) => { if (upBtn) upBtn.disabled = !f.length; });
    const note = el("input", { type: "text", maxlength: 300, placeholder: isOpen(d) ? MP.t("Note (optional)") : MP.t("What changed? e.g. added the statistics sheet") });
    const status = el("span", { class: "muted tm-vstatus" });
    upBtn = el("button", { type: "button", class: "btn btn-small btn-primary", disabled: true, onclick: async () => {
      upBtn.disabled = true;
      try {
        const ids = await uploadAll(drop.files(), (t) => { status.textContent = t; });
        const entry = await api(`/api/tm/${d.id}/versions`, { json: { uploads: ids, note: note.value.trim() } });
        location.href = `/timemachine/${entry.id}`;
      } catch (err) { status.textContent = ""; MP.toast(err.message, 4000); upBtn.disabled = false; }
    } }, icon("upload", 14), isOpen(d) ? MP.t("Upload and finish the task") : MP.t("Add as a new version"));

    const jobInput = el("input", { type: "text", maxlength: 40, spellcheck: "false", placeholder: isOpen(d) ? MP.t("job number") : MP.t("job number of the re-run") });
    const jobBtn = el("button", { type: "button", class: "btn btn-small", onclick: async () => {
      if (!jobInput.value.trim()) return;
      jobBtn.disabled = true;
      try {
        const entry = await api(`/api/tm/${d.id}/versions/job`, { json: { id: jobInput.value.trim() } });
        if (entry.already) MP.toast(MP.t("Already in Time Machine"));
        location.href = `/timemachine/${entry.id}`;
      } catch (err) { MP.toast(err.message, 4000); jobBtn.disabled = false; }
    } }, MP.t("Add"));

    const todo = isOpen(d);  // an open task: the files or the job it asks for
    return el("section", { class: `panel tm-versions${todo ? " is-todo" : ""}` },
      el("div", { class: "panel-head" }, el("h2", {}, icon("sync", 18), " ", MP.t("Versions")),
        el("span", { class: "muted" }, MP.tn(d.lineage.length, "{n} version", "{n} versions"))),
      el("div", { class: "tm-vlist" }, ...rows),
      el("div", { class: "tm-vadd" },
        el("div", { class: "tm-vadd-box" },
          el("div", { class: "field-label" }, todo ? MP.t("Upload the files") : MP.t("Upload a changed file")),
          el("p", { class: "muted tm-vhelp" }, todo ? MP.t("What the task asked for — this becomes its version 2 and the task is done.")
            : MP.t("E.g. the downloaded Excel sheet with your analysis added. The files stay as they were; this becomes the next version.")),
          drop.node, el("div", { class: "control" }, note), el("div", { class: "tm-vrow-actions" }, upBtn, status)),
        el("div", { class: "tm-vadd-box" },
          el("div", { class: "field-label" }, todo ? MP.t("Add a job") : MP.t("Add a re-run")),
          el("p", { class: "muted tm-vhelp" }, todo ? MP.t("A job run for this task: type its number. Or, on the job's result page, press “Add to Time Machine” and choose this task.")
            : MP.t("Re-runs started from this result join it by themselves when added to Time Machine. Another job can be added here by its number.")),
          el("div", { class: "tm-vrow-actions" }, el("div", { class: "control tm-vjob" }, jobInput), jobBtn))));
  }

  // ------------------------------------------------------------------ the archive
  let all = [];
  const st = { q: "", person: "", tool: "", project: new URLSearchParams(location.search).get("project") || "" };
  const selected = new Set();
  const hay = new WeakMap();
  const textOf = (e) => {
    if (!hay.has(e)) hay.set(e, MP.fold([e.id, e.tool_name, MP.t(e.tool_name), e.user, e.keyword, e.title, e.entry.note, e.entry.added_by, e.entry.assignee, e.entry.description,
      ...(e.entry.projects || []).map((p) => projectById(p)?.name || ""), ...inputs(e), ...(e.result_files || [])].join(" \u0001 ")));
    return hay.get(e);
  };

  function card(e) {
    const box = el("input", { type: "checkbox", class: "tm-check", checked: selected.has(e.id), "aria-label": MP.t("Select"),
      onclick: (ev) => ev.stopPropagation(),
      onchange: (ev) => { if (ev.target.checked) selected.add(e.id); else selected.delete(e.id); bulkBar(); } });
    // a task: tinted with its project's colour, glowing softly (amber when it has no project)
    const task = isTask(e), tints = task ? (e.entry.projects || []).map(projectById).filter(Boolean).map((p) => p.color) : [];
    const tint = task ? (tints[0] || "#fbbf24") : null;
    // several projects: the halo carries every project's colour, and they circle slowly around the card
    const halo = tints.length > 1 ? tints.map((c, j) => {
      const a = `(var(--orbit) + ${Math.round((j / tints.length) * 360)}deg)`;
      return `calc(cos${a} * 16px) calc(sin${a} * 11px) 34px -6px color-mix(in srgb, ${c} 70%, transparent)`;
    }).join(", ") : null;
    return el("div", { class: `tm-card${task ? ` is-task${halo ? " is-multi" : ""}${e.entry.done ? " is-done" : ""}` : ""}${selected.has(e.id) ? " is-selected" : ""}`,
      id: `tm-${e.id}`, dataset: { id: e.id }, style: tint ? `--pc:${tint}${halo ? `;--halo:${halo}` : ""}` : null },
      el("label", { class: "tm-check-wrap", onclick: (ev) => ev.stopPropagation() }, box),
      el("a", { class: "tm-card-body", href: `/timemachine/${e.id}` },
        el("div", { class: "tm-card-top" },
          taskBadge(e) || taskBadge(e.version > 1 ? all.find((x) => x.id === e.root) || {} : {}) || (isManual(e) ? el("span", { class: "tm-manual-badge" }, icon("upload", 11), MP.t("added by hand")) : null),
          el("span", { class: "tm-card-tool" }, toolName(e), !isManual(e) && e.title ? el("span", { class: "tm-card-title" }, ` — ${e.title}`) : null),
          e.keyword ? el("span", { class: "jkey" }, e.keyword) : null, versionBadge(e),
          ...(e.entry.projects || []).map((pid) => projectById(pid)).filter(Boolean).map((p) => chip(p, { class: "tm-pchip tm-pchip-sm" }))),
        isManual(e) && e.entry.description && e.version === 1 ? el("div", { class: "tm-card-note" }, e.entry.description) : null,
        summary(e) ? el("div", { class: "tm-card-sum" }, summary(e)) : null,
        e.entry.note ? el("div", { class: "tm-card-note" }, e.entry.note) : null,
        el("div", { class: "tm-card-meta" },
          el("span", {}, [e.user, MP.datetime(e.started || e.created)].filter(Boolean).join(" · ")),
          isTask(e) && e.entry.assignee ? el("span", { class: "tm-card-for" }, MP.t("for {who}", { who: e.entry.assignee })) : null,
          el("span", { class: "tm-card-id" }, icon("galaxy", 12), e.id),
          e.version > 1 ? el("span", { class: "tm-card-of" }, MP.t("updates {id}", { id: e.root })) : null,
          el("span", {}, MP.t("kept {when}", { when: MP.date(e.entry.added) }) + (e.entry.added_by ? ` · ${e.entry.added_by}` : "")))));
  }

  function fillSelect(sel, values, current, first) {
    sel.replaceChildren(el("option", { value: "" }, first), ...values.map(([v, label]) => el("option", { value: v }, label)));
    sel.value = current;
  }

  function projectsBar() {
    const bar = $("#tm-projects");
    const none = all.filter((e) => !(e.entry.projects || []).length).length;
    bar.replaceChildren(
      el("button", { type: "button", class: `tm-pchip tm-pfilter${!st.project ? " is-on" : ""}`, style: "--pc:#e9e3ff", onclick: () => setProject("") },
        MP.t("All"), el("span", { class: "tm-pcount" }, all.length)),
      ...projects.map((p) => el("button", { type: "button", class: `tm-pchip tm-pfilter${st.project === p.id ? " is-on" : ""}`, style: `--pc:${p.color}`,
        title: p.description || p.name, onclick: () => setProject(st.project === p.id ? "" : p.id) },
        el("span", { class: "tm-pdot" }), p.name, el("span", { class: "tm-pcount" }, p.count))),
      none ? el("button", { type: "button", class: `tm-pchip tm-pfilter tm-pnone${st.project === "none" ? " is-on" : ""}`, style: "--pc:#8e86a8",
        onclick: () => setProject(st.project === "none" ? "" : "none") }, el("span", { class: "tm-pdot" }), MP.t("No project"), el("span", { class: "tm-pcount" }, none)) : "",
      el("button", { type: "button", class: "tm-pchip tm-pnew", onclick: async () => { if (await newProject()) load(); } }, "+ ", MP.t("New project")));

    const head = $("#tm-project-head");
    const p = projectById(st.project);
    head.hidden = !p;
    if (!p) { head.replaceChildren(); return; }
    head.style.setProperty("--pc", p.color);
    head.replaceChildren(
      el("div", { class: "tm-ph-text" },
        el("div", { class: "tm-ph-name" }, el("span", { class: "tm-pdot" }), p.name),
        el("div", { class: "muted" }, [p.description, p.created_by ? MP.t("started by {who}, {when}", { who: p.created_by, when: MP.date(p.created) }) : MP.t("started {when}", { when: MP.date(p.created) })].filter(Boolean).join(" · "))),
      el("div", { class: "tm-ph-actions" },
        el("button", { type: "button", class: "link-btn", onclick: async () => {
          const got = await MP.askForm({ title: MP.t("Rename"), ok: MP.t("Save"), fields: [
            { label: MP.t("New name of the project:"), value: p.name },
            { label: MP.t("Description (optional):"), value: p.description || "" }] });
          if (!got) return;
          const [name, description] = got;
          try { await api(`/api/tm/projects/${p.id}`, { json: { name, description } }); load(); } catch (err) { MP.toast(err.message, 4000); }
        } }, MP.t("Rename")),
        el("button", { type: "button", class: "link-btn tm-color-btn", onclick: (ev) => colorMenu(ev.currentTarget, p) },
          el("span", { class: "tm-pdot" }), MP.t("Colour")),
        projects.length > 1 ? el("button", { type: "button", class: "link-btn", title: MP.t("Move all its results into another project, then remove this one"),
          onclick: (ev) => projectMenu(ev.currentTarget, projects.filter((x) => x.id !== p.id), async (q) => {
            if (!confirm(MP.t("Merge “{name}” into “{into}”? Its {n} result(s) move to “{into}”, and “{name}” goes (it stays in the history).",
              { name: p.name, into: q.name, n: p.count }))) return;
            try {
              await api(`/api/tm/projects/${p.id}/merge`, { json: { into: q.id } });
              MP.toast(MP.t("Merged into “{name}”", { name: q.name }));
              st.project = q.id;
              setProject(q.id);
              load();
            } catch (err) { MP.toast(err.message, 4000); }
          }, false) }, MP.t("Merge into…")) : null,
        el("button", { type: "button", class: "link-btn", onclick: async () => {
          if (!confirm(MP.t("Delete the project “{name}”? Its results stay in Time Machine; only the project goes (it stays in the history).", { name: p.name }))) return;
          try { await api(`/api/tm/projects/${p.id}`, { method: "DELETE" }); setProject(""); load(); } catch (err) { MP.toast(err.message, 4000); }
        } }, MP.t("Delete")),
        el("button", { type: "button", class: "link-btn tm-history-link", onclick: () => openHistory({ project: p.id, title: p.name }) }, icon("branch", 13), MP.t("See history"))));
  }

  // a project's colour: one of the usual ones, or any other
  let colors = [];
  function colorMenu(anchor, p) {
    $$(".tm-menu").forEach((m) => m.remove());
    const save = async (color) => {
      menu.remove();
      if (color.toLowerCase() === p.color.toLowerCase()) return;
      try { await api(`/api/tm/projects/${p.id}`, { json: { color } }); load(); } catch (err) { MP.toast(err.message, 4000); }
    };
    const custom = el("input", { type: "color", value: p.color, "aria-label": MP.t("Another colour") });
    custom.addEventListener("change", () => save(custom.value));
    const menu = el("div", { class: "tm-menu tm-color-menu", role: "menu" },
      el("div", { class: "tm-swatches" }, ...colors.map((c) => el("button", { type: "button", role: "menuitem", title: c,
        class: `tm-swatch${c.toLowerCase() === p.color.toLowerCase() ? " is-on" : ""}`, style: `--pc:${c}`, onclick: () => save(c) }))),
      el("label", { class: "tm-color-custom" }, custom, MP.t("Another colour…")));
    document.body.append(menu);
    const r = anchor.getBoundingClientRect();
    menu.style.left = `${Math.max(12, Math.min(innerWidth - menu.offsetWidth - 12, r.left))}px`;
    menu.style.top = `${r.bottom + 6}px`;
    setTimeout(() => document.addEventListener("click", function close(ev) {
      if (!menu.contains(ev.target)) { menu.remove(); document.removeEventListener("click", close); }
    }), 0);
  }

  function setProject(pid) {
    st.project = pid;
    const q = new URLSearchParams(location.search);
    if (pid) q.set("project", pid); else q.delete("project");
    history.replaceState(null, "", location.pathname + (q.toString() ? `?${q}` : ""));
    projectsBar();
    render();
  }

  // several results at once: add to / move to / take out of a project
  function bulkBar() {
    const bar = $("#tm-bulk");
    $$(".tm-card").forEach((c) => {
      c.classList.toggle("is-selected", selected.has(c.dataset.id));
      const box = c.querySelector(".tm-check");
      if (box) box.checked = selected.has(c.dataset.id);
    });
    selectAllBtn();
    bar.hidden = !selected.size;
    if (!selected.size) { bar.replaceChildren(); return; }
    const ids = [...selected];
    const theirs = [...new Set(all.filter((e) => selected.has(e.id)).flatMap((e) => e.entry.projects || []))];
    const assign = async (body, msg) => {
      try { await api("/api/tm/assign", { json: { ids, ...body } }); MP.toast(msg); await load(); } catch (err) { MP.toast(err.message, 4000); }
    };
    bar.replaceChildren(
      el("span", { class: "tm-bulk-n" }, MP.tn(ids.length, "{n} selected", "{n} selected")),
      el("button", { type: "button", class: "btn btn-small", onclick: (ev) => projectMenu(ev.currentTarget, projects, (p) =>
        assign({ add: [p.id] }, MP.t("Added to “{name}”", { name: p.name }))) }, MP.t("Add to project…")),
      el("button", { type: "button", class: "btn btn-small", title: MP.t("Out of the project shown now (or of all their projects) and into another one"),
        onclick: (ev) => projectMenu(ev.currentTarget, projects, (p) => {
          const out = projectById(st.project) ? [st.project] : theirs;
          assign({ add: [p.id], remove: out.filter((x) => x !== p.id) }, MP.t("Moved to “{name}”", { name: p.name }));
        }) }, MP.t("Move to project…")),
      theirs.length ? el("button", { type: "button", class: "btn btn-small", onclick: (ev) => projectMenu(ev.currentTarget, theirs.map(projectById).filter(Boolean), (p) =>
        assign({ remove: [p.id] }, MP.t("Taken out of “{name}”", { name: p.name })), false) }, MP.t("Take out of project…")) : "",
      el("span", { class: "grow" }),
      el("button", { type: "button", class: "link-btn", onclick: () => { selected.clear(); render(); } }, MP.t("Clear selection")));
  }

  // "Select all": every result shown now (the search and filters apply); all of them selected already → "Select none"
  function selectAllBtn() {
    const btn = $("#tm-select-all");
    const shown = graph.rows.map((e) => e.id);
    btn.hidden = !shown.length;
    const every = shown.length > 0 && shown.every((id) => selected.has(id));
    btn.classList.toggle("on", every);
    btn.querySelector("span").textContent = every ? MP.t("Select none") : MP.t("Select all");
    btn.title = every ? MP.t("Unselect every result shown") : MP.t("Select every result shown (the search and filters apply)");
  }

  function render() {
    const words = MP.fold(st.q).split(/\s+/).filter(Boolean);
    const inProject = (e) => !st.project || (st.project === "none" ? !(e.entry.projects || []).length : (e.entry.projects || []).includes(st.project));
    const rows = all.filter((e) => (!st.person || e.user === st.person) && (!st.tool || e.tool_id === st.tool) && inProject(e)
      && words.every((w) => textOf(e).includes(w)));
    const list = $("#tm-list"), line = $("#tm-timeline");
    for (const id of [...selected]) if (!all.some((e) => e.id === id)) selected.delete(id);
    graph.rows = rows;  // the results shown now ("Select all" picks these)
    if (!all.length) {
      list.replaceChildren(el("div", { class: "tm-empty" }, el("div", { class: "tm-empty-orb" }, icon("galaxy", 34)),
        el("p", {}, MP.t("Nothing kept yet.")),
        el("p", { class: "muted" }, MP.t("Open a result in Jobs & results and press “Add to Time Machine”, or type a job number above."))));
      line.replaceChildren();
      bulkBar();
      return;
    }
    if (!rows.length) { list.replaceChildren(el("div", { class: "muted pad" }, MP.t("Nothing matches — try fewer words or another filter."))); line.replaceChildren(); bulkBar(); return; }
    const months = new Map();
    rows.forEach((e) => { const k = monthKey(e.created); if (!months.has(k)) months.set(k, []); months.get(k).push(e); });
    list.replaceChildren(
      el("svg", {}),  // replaced by the graph below
      ...[...months].map(([k, items]) => el("div", { class: "tm-month", id: `m-${k}`, dataset: { month: k } },
        el("div", { class: "tm-month-head" }, el("span", {}, monthName(k)), el("span", { class: "muted" }, items.length)),
        ...items.map(card))));
    line.replaceChildren(...[...months].map(([k, items]) => el("a", { href: `#m-${k}`, class: "tm-tick", dataset: { month: k },
      onclick: (ev) => { ev.preventDefault(); $(`#m-${k}`).scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start" }); } },
      el("span", { class: "tm-tick-mark" }), el("span", { class: "tm-tick-label" }, k), el("span", { class: "tm-tick-n" }, items.length))));
    graph.rows = rows;
    drawGraph();
    watchMonths();
    bulkBar();
  }

  // ------------------------------------------------------------------ the graph: one lane per project
  // Each project is a vertical line; a result is a dot on the lane of every project it is in, and dots of the
  // same result are joined across — a result in several projects ties their lanes together.
  const NS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs = {}) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) if (v != null) n.setAttribute(k, v); return n; };
  const graph = { rows: [] };
  function drawGraph(again = true) {
    const list = $("#tm-list");
    const old = list.querySelector(":scope > svg");
    const rows = graph.rows;
    const lanes = projects.filter((p) => rows.some((e) => (e.entry.projects || []).includes(p.id)));
    const loose = rows.some((e) => !(e.entry.projects || []).length);
    const n = lanes.length + (loose ? 1 : 0);
    const gap = n > 1 ? Math.max(9, Math.min(18, 150 / (n - 1))) : 18;
    const x0 = 22, width = x0 + (n - 1) * gap + 22;
    list.style.setProperty("--lanes-w", `${width}px`);
    const laneX = (i) => x0 + i * gap;
    const looseX = laneX(lanes.length);
    const right = list.clientWidth - (parseFloat(getComputedStyle(list).paddingRight) || 0);  // the cards' right edge
    // positions from the layout, not the screen: the arrival zoom (a transform) would shift them
    const offsetIn = (n) => { let y = 0; for (; n && n !== list; n = n.offsetParent) y += n.offsetTop; return y; };
    const pos = new Map();
    rows.forEach((e) => {
      const c = document.getElementById(`tm-${e.id}`);
      if (c) pos.set(e.id, offsetIn(c) + 26);
    });
    const g = svg("svg", { class: "tm-graph", width, height: list.scrollHeight, "aria-hidden": "true" });
    const lane = (x, ys, color, dashed, label, pid) => {
      if (!ys.length) return;
      const y1 = Math.min(...ys) - 14, y2 = Math.max(...ys) + 14;
      const l = svg("line", { x1: x, x2: x, y1, y2, stroke: color, class: `tm-lane${dashed ? " is-loose" : ""}`, "data-p": pid || "" });
      const t = svg("title"); t.textContent = label; l.append(t);
      g.append(l);
    };
    lanes.forEach((p, i) => lane(laneX(i), rows.filter((e) => (e.entry.projects || []).includes(p.id)).map((e) => pos.get(e.id)).filter((y) => y != null), p.color, false, p.name, p.id));
    if (loose) lane(looseX, rows.filter((e) => !(e.entry.projects || []).length).map((e) => pos.get(e.id)).filter((y) => y != null), "#8e86a8", true, MP.t("No project"), "");
    const brackets = [];
    rows.forEach((e) => {
      const y = pos.get(e.id);
      if (y == null) return;
      const mine = (e.entry.projects || []).map((pid) => lanes.findIndex((p) => p.id === pid)).filter((i) => i >= 0);
      const xs = mine.length ? mine.map(laneX) : [looseX];
      const left = Math.min(...xs);
      g.append(svg("line", { x1: left, x2: width, y1: y, y2: y, class: `tm-link${mine.length > 1 ? " is-mesh" : ""}`, "data-id": e.id }));
      // a later version is a ring instead of a dot: the same result, updated
      const later = e.version > 1;
      mine.forEach((i) => g.append(svg("circle", { cx: laneX(i), cy: y, r: later ? 5 : mine.length > 1 ? 4.6 : 4,
        fill: later ? "#0b0918" : lanes[i].color, stroke: later ? lanes[i].color : null, class: `tm-node${later ? " is-version" : ""}${isTask(e) ? " is-task" : ""}`,
        style: isTask(e) ? `color:${lanes[i].color}` : null, "data-id": e.id })));
      if (!mine.length) g.append(svg("circle", { cx: looseX, cy: y, r: later ? 4.6 : 3.6, class: `tm-node is-loose${later ? " is-version" : ""}${isTask(e) ? " is-task" : ""}`, "data-id": e.id }));
      // …joined by a curve to the version before it, on the right of the cards (the lanes on the left are busy enough)
      if (later) {
        const prev = rows.filter((x) => x.root === e.root && x.version < e.version).sort((a, b) => b.version - a.version)[0];
        const y0 = prev ? pos.get(prev.id) : null;
        if (y0 != null) {
          brackets.push({ a: Math.min(y, y0), b: Math.max(y, y0), e, prev });
        }
      }
    });
    // brackets: out from the newer card, down to the older one, back in. Ends meeting at one card keep a tiny gap,
    // and brackets that overlap each get their own narrow column, so many fit side by side.
    const cols = [];  // the bottom of the last bracket in each column
    const placedB = brackets.sort((p, q) => p.a - q.a || p.b - q.b).map((k) => {
      const a = k.a + 2, b = k.b - 2;
      let col = cols.findIndex((end) => end + 3 <= a);
      if (col < 0) { col = cols.length; cols.push(b); } else cols[col] = b;
      return { ...k, a, b, col };
    });
    // the cards make room on the right for exactly as many columns as there are; then the graph is drawn again to fit
    const room = cols.length ? 10 + cols.length * 4 : 0;
    if (list.style.getPropertyValue("--brackets-w") !== `${room}px`) {
      list.style.setProperty("--brackets-w", `${room}px`);
      if (again) return drawGraph(false);
    }
    placedB.forEach(({ a, b, e, prev, col }) => {
      const x = right + 7 + col * 4, r = Math.min(4, (b - a) / 2);
      const d = `M${right} ${a} H${x - r} Q${x} ${a} ${x} ${a + r} V${b - r} Q${x} ${b} ${x - r} ${b} H${right}`;
      const pair = { "data-id": e.id, "data-prev": prev.id };
      const hit = svg("path", { d, class: "tm-version-hit", ...pair });
      const t = svg("title"); t.textContent = `v${prev.version} → v${e.version}`; hit.append(t);
      g.append(svg("path", { d, class: "tm-version-link", ...pair }), hit);
    });
    if (old) old.replaceWith(g); else list.prepend(g);
  }
  // keep the graph in place when cards change height (window width, fonts loading)
  const ro = new ResizeObserver(() => { if (graph.rows.length) requestAnimationFrame(drawGraph); });
  ro.observe($("#tm-list"));
  // hovering a card lights up its dots; hovering a lane lights up its project's cards
  $("#tm-list").addEventListener("mouseover", (ev) => {
    const c = ev.target.closest(".tm-card");
    $$(".tm-graph .is-hot").forEach((n) => n.classList.remove("is-hot"));
    if (c) $$(`.tm-graph [data-id="${c.dataset.id}"], .tm-graph .tm-version-link[data-prev="${c.dataset.id}"]`).forEach((n) => n.classList.add("is-hot"));
    const laneEl = ev.target.closest(".tm-lane");
    $$(".tm-card.is-lane").forEach((n) => n.classList.remove("is-lane"));
    if (laneEl) {
      const pid = laneEl.dataset.p;
      graph.rows.filter((e) => pid ? (e.entry.projects || []).includes(pid) : !(e.entry.projects || []).length)
        .forEach((e) => document.getElementById(`tm-${e.id}`)?.classList.add("is-lane"));
    }
    // hovering a bracket between two versions lights it up, and the two cards it joins
    const hit = ev.target.closest(".tm-version-hit");
    if (hit) {
      hit.previousElementSibling.classList.add("is-hot");
      for (const id of [hit.dataset.id, hit.dataset.prev]) document.getElementById(`tm-${id}`)?.classList.add("is-lane");
    }
  });

  let observer = null;
  function watchMonths() {
    observer?.disconnect();
    observer = new IntersectionObserver((seen) => {
      const topSeen = seen.filter((s) => s.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (topSeen) $$(".tm-tick").forEach((t) => t.classList.toggle("active", t.dataset.month === topSeen.target.dataset.month));
    }, { rootMargin: "-80px 0px -60% 0px" });
    $$(".tm-month").forEach((m) => observer.observe(m));
  }

  async function load(flash) {
    try {
      const d = await api("/api/tm");
      all = d.entries;
      projects = d.projects;
      people = d.people || [];
      colors = d.colors || [];
      tasksPanel();
      if (st.project && st.project !== "none" && !projectById(st.project)) st.project = "";
      stats(all);
      const runBy = [...new Set(all.map((e) => e.user).filter(Boolean))].sort((a, b) => a.localeCompare(b)).map((n) => [n, n]);
      const tools = [...new Map(all.map((e) => [e.tool_id, MP.t(e.tool_name)]))].sort((a, b) => a[1].localeCompare(b[1]));
      fillSelect($("#tm-person"), runBy, st.person, MP.t("Everyone"));
      fillSelect($("#tm-tool"), tools, st.tool, MP.t("Any tool"));
      const into = $("#tm-into"), keep = into.value;
      fillSelect(into, projects.map((p) => [p.id, p.name]), keep, MP.t("No project"));
      projectsBar();
      render();
      if (flash) {
        const c = document.getElementById(`tm-${flash}`);
        if (c) { c.classList.add("tm-new"); c.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "center" }); }
      }
    } catch (e) { $("#tm-list").replaceChildren(el("div", { class: "alert alert-error" }, icon("alert", 16), el("div", {}, e.message))); }
  }

  $("#tm-q").addEventListener("input", (e) => { st.q = e.target.value.trim(); render(); });
  $("#tm-select-all").addEventListener("click", () => {
    const shown = graph.rows.map((e) => e.id);
    if (shown.every((id) => selected.has(id))) shown.forEach((id) => selected.delete(id));
    else shown.forEach((id) => selected.add(id));
    bulkBar();
  });
  [["#tm-person", "person"], ["#tm-tool", "tool"]].forEach(([sel, k]) =>
    $(sel).addEventListener("change", (e) => { st[k] = e.target.value; render(); }));
  // ------------------------------------------------------------------ tasks: mine, and everyone's
  function tasksPanel() {
    const tasks = all.filter(isTask);
    const open = tasks.filter(isOpen), done = tasks.filter((e) => e.entry.done).sort((a, b) => b.entry.done - a.entry.done);
    const row = (e) => el("a", { class: `tm-task${e.entry.done ? " is-done" : ""}`, href: `/timemachine/${e.entry.done ? e.entry.done_with || e.id : e.id}` },
      el("span", { class: "tm-task-icon" }, icon(e.entry.done ? "check" : "clock", 14)),
      el("span", { class: "tm-task-text" },
        el("span", { class: "tm-task-title" }, e.tool_name),
        el("span", { class: "tm-task-meta" },
          e.entry.assignee ? el("span", { class: "tm-task-who" }, e.entry.assignee) : el("span", { class: "tm-task-who is-nobody" }, MP.t("no one yet")),
          ` · ${e.entry.done ? MP.t("done {when}", { when: MP.date(e.entry.done) }) : MP.t("since {when}", { when: MP.date(e.created) })}`,
          e.user ? ` · ${MP.t("from {who}", { who: e.user })}` : "")),
      el("span", { class: "tm-task-projects" }, ...(e.entry.projects || []).map(projectById).filter(Boolean).map((p) => el("span", { class: "tm-pdot", style: `--pc:${p.color}`, title: p.name }))));
    const list = (items, none) => items.length ? el("div", { class: "tm-task-list" }, ...items.map(row)) : el("p", { class: "muted tm-task-none" }, none);
    const mine = open.filter(isMine);
    const counts = [...open.reduce((m, e) => m.set(e.entry.assignee || "", (m.get(e.entry.assignee || "") || 0) + 1), new Map())]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    $("#tm-tasks-grid").replaceChildren(
      el("div", { class: "panel tm-task-col is-mine" },
        el("div", { class: "tm-task-col-head" }, el("h3", {}, MP.t("My tasks")), el("span", { class: "tm-pcount" }, mine.length)),
        MP.prefs.name ? list(mine, MP.t("Nothing for you to do."))
          : el("p", { class: "muted tm-task-none" }, MP.t("Set your name (top right) to see the tasks given to you."))),
      el("div", { class: "panel tm-task-col" },
        el("div", { class: "tm-task-col-head" }, el("h3", {}, MP.t("All open tasks")), el("span", { class: "tm-pcount" }, open.length)),
        counts.length ? el("div", { class: "tm-task-people" }, ...counts.map(([who, n]) => el("span", { class: `tm-task-person${who ? "" : " is-nobody"}` },
          who || MP.t("no one yet"), el("b", {}, n)))) : null,
        list(open, MP.t("No open tasks.")),
        done.length ? el("details", { class: "tm-task-done" }, el("summary", {}, MP.tn(done.length, "{n} done", "{n} done")), list(done.slice(0, 20), "")) : null));
  }

  $("#tm-task-btn").addEventListener("click", () => {
    const title = el("input", { type: "text", maxlength: 120, required: true, placeholder: MP.t("e.g. 77K spectra of the PsbA mutant") });
    const desc = el("textarea", { rows: 4, maxlength: 4000, required: true, placeholder: MP.t("What is to be done, with which samples, what the result should be…") });
    const who = personInput();
    const chosen = new Set(st.project && st.project !== "none" ? [st.project] : []);
    const pbox = el("div", { class: "tm-entry-projects" });
    const drawP = () => pbox.replaceChildren(...projects.map((p) => el("button", { type: "button", class: `tm-pchip tm-ptoggle${chosen.has(p.id) ? " is-on" : ""}`,
      style: `--pc:${p.color}`, onclick: () => { if (chosen.has(p.id)) chosen.delete(p.id); else chosen.add(p.id); drawP(); } }, el("span", { class: "tm-pdot" }), p.name)));
    drawP();
    const ok = el("button", { type: "submit", class: "btn btn-primary", disabled: true }, MP.t("Add the task"));
    const check = () => { ok.disabled = !(title.value.trim() && desc.value.trim()); };
    [title, desc].forEach((x) => x.addEventListener("input", check));
    const field = (label, control, req = true) => el("label", { class: "tm-mfield" }, el("span", { class: "field-label" }, label, req ? el("span", { class: "tm-req" }, " *") : null), control);
    const form = el("form", { method: "dialog", class: "tm-manual-form" },
      el("div", { class: "tm-hist-head" },
        el("h3", {}, icon("clock", 16), " ", MP.t("New task")),
        el("button", { type: "button", class: "icon-btn", "aria-label": MP.t("Close"), onclick: () => dlg.close() }, icon("x", 16))),
      el("p", { class: "muted" }, MP.t("No files yet. When someone uploads them to the task, or adds a job to it, the task is done and becomes a kept result.")),
      field(MP.t("Title"), el("div", { class: "control" }, title)),
      field(MP.t("Description"), el("div", { class: "control" }, desc)),
      field(MP.t("For"), who.node, false),
      projects.length ? el("div", { class: "tm-mfield" }, el("span", { class: "field-label" }, MP.t("Projects")), pbox) : null,
      el("div", { class: "dialog-actions" }, el("button", { type: "button", class: "btn", onclick: () => dlg.close() }, MP.t("Cancel")), ok));
    const dlg = el("dialog", { class: "dialog tm-hist tm-manual" }, form);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      check();
      if (ok.disabled) return;
      ok.disabled = true;
      try {
        const entry = await api("/api/tm/tasks", { json: { title: title.value.trim(), description: desc.value.trim(), assignee: who.input.value.trim(), projects: [...chosen] } });
        dlg.close();
        MP.toast(MP.t("Task added"));
        await load(entry.id);
      } catch (err) { MP.toast(err.message, 4000); ok.disabled = false; }
    });
    dlg.addEventListener("close", () => dlg.remove());
    document.body.append(dlg);
    dlg.showModal();
    title.focus();
  });

  // ------------------------------------------------------------------ adding files by hand
  // Something worth keeping that never was a job: title, description and at least one file — all required.
  $("#tm-manual-btn").addEventListener("click", () => {
    const title = el("input", { type: "text", maxlength: 120, required: true, placeholder: MP.t("e.g. Western blot of PsbA, March 2026") });
    const desc = el("textarea", { rows: 4, maxlength: 4000, required: true, placeholder: MP.t("What it is, how it was made, why it is kept…") });
    let check = () => { };
    const files = dropFiles(() => check());
    const status = el("span", { class: "muted tm-vstatus" });
    const chosen = new Set(st.project && st.project !== "none" ? [st.project] : []);
    const pbox = el("div", { class: "tm-entry-projects" });
    const drawP = () => pbox.replaceChildren(...projects.map((p) => el("button", { type: "button", class: `tm-pchip tm-ptoggle${chosen.has(p.id) ? " is-on" : ""}`,
      style: `--pc:${p.color}`, onclick: () => { if (chosen.has(p.id)) chosen.delete(p.id); else chosen.add(p.id); drawP(); } }, el("span", { class: "tm-pdot" }), p.name)));
    drawP();
    const ok = el("button", { type: "submit", class: "btn btn-primary", disabled: true }, MP.t("Add to Time Machine"));
    check = () => { ok.disabled = !(title.value.trim() && desc.value.trim() && files.files().length); };
    [title, desc].forEach((x) => x.addEventListener("input", check));
    const field = (label, control, hint) => el("label", { class: "tm-mfield" }, el("span", { class: "field-label" }, label, el("span", { class: "tm-req" }, " *")), control, hint ? el("span", { class: "muted tm-vhelp" }, hint) : null);
    const form = el("form", { method: "dialog", class: "tm-manual-form" },
      el("div", { class: "tm-hist-head" },
        el("h3", {}, icon("upload", 16), " ", MP.t("Add files by hand")),
        el("button", { type: "button", class: "icon-btn", "aria-label": MP.t("Close"), onclick: () => dlg.close() }, icon("x", 16))),
      el("p", { class: "muted" }, MP.t("For files that didn't come from a MISTER PLIS tool. They are kept only in Time Machine, with their own job number.")),
      field(MP.t("Title"), el("div", { class: "control" }, title)),
      field(MP.t("Description"), el("div", { class: "control" }, desc)),
      el("div", { class: "tm-mfield" }, el("span", { class: "field-label" }, MP.t("Files"), el("span", { class: "tm-req" }, " *")), files.node),
      projects.length ? el("div", { class: "tm-mfield" }, el("span", { class: "field-label" }, MP.t("Projects")), pbox) : null,
      el("div", { class: "dialog-actions" }, status, el("button", { type: "button", class: "btn", onclick: () => dlg.close() }, MP.t("Cancel")), ok));
    const dlg = el("dialog", { class: "dialog tm-hist tm-manual" }, form);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      check();
      if (ok.disabled) return;
      ok.disabled = true;
      try {
        const ids = await uploadAll(files.files(), (t) => { status.textContent = t; });
        const entry = await api("/api/tm/manual", { json: { title: title.value.trim(), description: desc.value.trim(), uploads: ids, projects: [...chosen] } });
        dlg.close();
        MP.toast(MP.t("Added to Time Machine"));
        await load(entry.id);
      } catch (err) { status.textContent = ""; MP.toast(err.message, 4000); ok.disabled = false; }
    });
    dlg.addEventListener("close", () => dlg.remove());
    document.body.append(dlg);
    dlg.showModal();
    title.focus();
  });

  $("#tm-history-all").addEventListener("click", () => openHistory({ title: MP.t("Everything in Time Machine") }));

  // ------------------------------------------------------------------ bringing a job here
  const out = $("#tm-retrieve-out"), idInput = $("#tm-id"), go = $("#tm-go");
  const goLabel = () => go.replaceChildren(icon("download", 16), el("span", {}, MP.t("Retrieve")));
  const where = (f) => f.source === "backup" ? MP.t("in the backup folder") : MP.t("in Jobs & results");

  function candidates(list) {
    return el("div", { class: "tm-candidates" }, ...list.map((f) => el("div", { class: "tm-cand" },
      el("div", { class: "tm-cand-text" },
        el("div", {}, el("b", {}, MP.t(f.tool_name || "")), f.keyword ? el("span", { class: "jkey" }, f.keyword) : null),
        el("div", { class: "muted" }, [f.user, f.created ? MP.datetime(f.created) : "", where(f)].filter(Boolean).join(" · ")),
        el("code", { class: "tm-cand-id" }, f.id)),
      f.in_tm ? el("a", { class: "btn btn-small", href: `/timemachine/${f.id}` }, icon("galaxy", 14), MP.t("Already here"))
        : f.status !== "done" ? el("span", { class: "muted" }, MP.t("not finished"))
        : el("button", { class: "btn btn-small btn-primary", type: "button", onclick: () => retrieve(f.id) }, MP.t("Retrieve")))));
  }

  async function retrieve(id) {
    go.disabled = true;
    go.replaceChildren(el("span", { class: "spinner" }), el("span", {}, MP.t("Retrieving…")));
    root.classList.add("tm-pulling");
    try {
      const into = $("#tm-into").value;
      const d = await api("/api/tm/retrieve", { json: { id, projects: into ? [into] : [] } });
      out.replaceChildren(el("div", { class: "alert alert-success tm-ok" }, icon("check", 16), el("div", {},
        d.already ? MP.t("Job {id} was already in Time Machine.", { id: d.entry.id }) : MP.t("Job {id} is now in Time Machine.", { id: d.entry.id }), " ",
        el("a", { class: "link", href: `/timemachine/${d.entry.id}` }, MP.t("Open it")))));
      idInput.value = "";
      await load(d.entry.id);
    } catch (e) {
      const list = (e.data && e.data.candidates) || [];
      out.replaceChildren(el("div", { class: "alert alert-warning" }, icon("alert", 16), el("div", {}, e.message)), list.length > 1 ? candidates(list) : "");
    }
    setTimeout(() => root.classList.remove("tm-pulling"), 600);
    go.disabled = false;
    goLabel();
  }

  // while typing: what the number would bring
  let findTimer = null, findSeq = 0;
  idInput.addEventListener("input", () => {
    clearTimeout(findTimer);
    const q = idInput.value.trim();
    if (q.length < 4) { out.replaceChildren(); return; }
    findTimer = setTimeout(async () => {
      const my = ++findSeq;
      try {
        const d = await api(`/api/tm/find?q=${encodeURIComponent(q)}`);
        if (my !== findSeq) return;
        out.replaceChildren(d.results.length ? candidates(d.results.slice(0, 6)) : el("div", { class: "muted tm-none" }, MP.t("No job with this number yet — keep typing.")));
      } catch (_) { }
    }, 280);
  });
  $("#tm-retrieve").addEventListener("submit", (e) => { e.preventDefault(); if (idInput.value.trim()) retrieve(idInput.value.trim()); });

  load(new URLSearchParams(location.search).get("added"));
})();
