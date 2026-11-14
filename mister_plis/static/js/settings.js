// Settings → You, Exports & printing, Jobs & backup: the settings drawn by the server (cookies, the lab's backup).
(function () {
  if (document.body.dataset.page !== "settings") return;
    MP.$$(".seg[data-pref] button").forEach((b) => b.addEventListener("click", () => {
      const name = b.closest(".seg").dataset.pref;
      MP.setPref(name, b.dataset.value);
      if (name === "theme") MP.applyTheme();
      if (name === "lang") { location.reload(); return; }
      MP.toast(MP.t("Saved"));
    }));
    const nameInput = MP.$("#pref-name");
    nameInput?.addEventListener("change", () => {
      const v = nameInput.value.trim().replace(/\s+/g, " ");
      nameInput.value = v;
      MP.setPref("name", v);
      const chip = MP.$("#user-chip");
      if (chip) {
        chip.classList.toggle("is-empty", !v);
        MP.$("#user-avatar").textContent = v ? v[0].toUpperCase() : "?";
        MP.$("#user-name").textContent = v || MP.t("Set your name");
      }
      const mine = MP.$('.clear-history [data-scope="mine"]');
      if (mine) { mine.disabled = !v; mine.title = v ? "" : MP.t("Set your name on the You tab first"); }
      MP.toast(MP.t("Saved"));
    });
    // Jobs & backup → Backup: lab-wide, stored on the server
    const lab = MP.$("#lab-panel");
    if (lab) {
      let info = JSON.parse(MP.$("#lab-info").textContent);
      const dirInput = MP.$("#backup-dir");
      const showStatus = () => {
        const st = info.status, parts = [];
        if (!info.backup_dir) parts.push(MP.t("Backups are off."));
        else {
          parts.push(st.last_run ? MP.t("Last check {when}", { when: MP.datetime(st.last_run) }) + (st.copied ? " — " + MP.tn(st.copied, "{n} job copied", "{n} jobs copied") : "") + "."
            : MP.t("Not run yet — it checks every 10 minutes."));
          parts.push(info.waiting ? MP.tn(info.waiting, "{n} finished job not backed up yet.", "{n} finished jobs not backed up yet.") : MP.t("Everything finished is backed up."));
        }
        const box = MP.$("#backup-status");
        box.replaceChildren(parts.join(" "), st.last_error ? MP.el("div", { class: "backup-error" }, st.last_error) : "");
        MP.$("#backup-now").disabled = !info.backup_dir;
        MP.$("#backup-verify").disabled = !info.backup_dir;
        const up = MP.$("#backup-upgrade");
        up.hidden = !info.old_backups;
        up.textContent = MP.tn(info.old_backups || 0, "Update {n} old backup", "Update {n} old backups");
      };
      MP.$("#backup-verify").addEventListener("click", async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        btn.textContent = MP.t("Checking…");
        try {
          const r = await MP.api("/api/lab/verify", { method: "POST" });
          MP.toast(r.bad.length ? MP.tn(r.bad.length, "{n} backup didn't check out — it will be copied again", "{n} backups didn't check out — they will be copied again")
            : MP.tn(r.ok, "{n} backup checked: all fine", "{n} backups checked: all fine"), 6000);
          info = await MP.api("/api/lab");
        } catch (err) { MP.toast(err.message, 6000); }
        btn.textContent = MP.t("Check the backups");
        showStatus();
      });
      MP.$("#backup-upgrade").addEventListener("click", async (e) => {
        if (!confirm(MP.t("Rewrite the older backups in the readable form (README, workbook, plots)? The old folders are kept beside them."))) return;
        const btn = e.currentTarget;
        btn.disabled = true;
        btn.textContent = MP.t("Updating…");
        try {
          const r = await MP.api("/api/lab/upgrade", { method: "POST" });
          MP.toast(MP.tn(r.upgraded.length, "Updated {n} backup", "Updated {n} backups") + (r.errors.length ? " — " + r.errors.join("; ") : ""), 8000);
          info = await MP.api("/api/lab");
        } catch (err) { MP.toast(err.message, 6000); }
        btn.disabled = false;
        showStatus();
      });
      const save = async (changes) => {
        try {
          info = await MP.api("/api/lab", { json: { backup_dir: info.backup_dir, backup_after_days: info.backup_after_days, ...changes } });
          dirInput.value = info.backup_dir;
          MP.$$("#backup-after button").forEach((b) => {
            const on = Number(b.dataset.value) === info.backup_after_days;
            b.classList.toggle("active", on);
            b.setAttribute("aria-checked", on ? "true" : "false");
          });
          showStatus();
          MP.toast(MP.t("Saved for the whole lab"));
        } catch (e) { MP.toast(e.message, 6000); }
      };
      MP.$("#backup-dir-save").addEventListener("click", () => save({ backup_dir: dirInput.value.trim() }));
      dirInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); save({ backup_dir: dirInput.value.trim() }); } });
      MP.$$("#backup-after button").forEach((b) => b.addEventListener("click", () => save({ backup_after_days: Number(b.dataset.value) })));
      MP.$("#backup-now").addEventListener("click", async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        btn.textContent = MP.t("Backing up…");
        try {
          info = await MP.api("/api/lab/backup", { method: "POST" });
          MP.toast(info.status.last_error ? MP.t("Backup failed") : MP.tn(info.status.copied, "Backed up {n} job", "Backed up {n} jobs"));
        } catch (err) { MP.toast(err.message, 6000); }
        btn.textContent = MP.t("Back up now");
        showStatus();
      });
      showStatus();

      // Clear job history: preview what goes, offer to back up what isn't yet, then delete
      const clearBtns = MP.$$(".clear-history button");
      clearBtns.forEach((b) => b.addEventListener("click", async () => {
        const scope = b.dataset.scope;
        let pre;
        try { pre = await MP.api(`/api/history/clear?scope=${scope}`); } catch (e) { MP.toast(e.message, 6000); return; }
        const mine = scope === "mine";
        if (!pre.count) {
          MP.toast((mine ? MP.t("No finished jobs in your history") : MP.t("No finished jobs in everyone's history"))
            + (pre.running ? " (" + MP.tn(pre.running, "{n} job still running", "{n} jobs still running") + ")" : ""), 4000);
          return;
        }
        const boxes = pre.unbacked.map((j) => MP.el("input", { type: "checkbox", checked: true, value: j.id }));
        const all = MP.el("input", { type: "checkbox", checked: true });
        const sync = () => { const n = boxes.filter((c) => c.checked).length; all.checked = n === boxes.length; all.indeterminate = n > 0 && n < boxes.length; };
        all.addEventListener("change", () => { boxes.forEach((c) => { c.checked = all.checked; }); sync(); });
        boxes.forEach((c) => c.addEventListener("change", sync));
        const go = MP.el("button", { type: "submit", class: "btn btn-danger-solid", value: "ok" }, MP.tn(pre.count, "Delete {n} job", "Delete {n} jobs"));
        const dlg = MP.el("dialog", { class: "dialog" }, MP.el("form", { method: "dialog" },
          MP.el("h3", {}, mine ? MP.t("Clear your job history?") : MP.t("Clear everyone's job history?")),
          MP.el("p", {}, MP.tn(pre.count, "{n} finished job and its result files will be deleted from the server.", "{n} finished jobs and their result files will be deleted from the server.")
            + (pre.running ? " " + MP.tn(pre.running, "{n} running job will be left alone.", "{n} running jobs will be left alone.") : "")),
          boxes.length ? [
            MP.el("p", {}, MP.el("b", {}, MP.tn(boxes.length, "{n} result not backed up yet.", "{n} results not backed up yet.")), " ", MP.t("Ticked ones are copied to the backup folder first:")),
            MP.el("label", { class: "dialog-all" }, all, " ", MP.t("All")),
            MP.el("div", { class: "dialog-list" }, pre.unbacked.map((j, i) => MP.el("label", {}, boxes[i],
              MP.el("span", {}, MP.el("b", {}, MP.t(j.tool)), ` · ${j.user || MP.t("no name")} · ${MP.datetime(j.finished)}`, j.keyword ? ` · ${j.keyword}` : "")))),
            MP.el("p", { class: "muted" }, MP.t("Unticked ones are deleted without a copy.")),
          ] : MP.el("p", { class: pre.backups_on ? "muted" : "warn" }, pre.backups_on
            ? MP.t("Everything here is already in the backup folder.")
            : MP.t("Backups are off — these results will be gone for good.")),
          MP.el("div", { class: "dialog-actions" }, MP.el("button", { type: "submit", class: "btn", value: "cancel" }, MP.t("Cancel")), go)));
        document.body.append(dlg);
        dlg.addEventListener("close", async () => {
          dlg.remove();
          if (dlg.returnValue !== "ok") return;
          clearBtns.forEach((x) => { x.disabled = true; });
          try {
            const r = await MP.api("/api/history/clear", { json: { scope, backup: boxes.filter((c) => c.checked).map((c) => c.value) } });
            const msg = MP.tn(r.deleted, "Deleted {n} job", "Deleted {n} jobs") + (r.backed_up ? MP.t(", backed up {n} first", { n: r.backed_up }) : "");
            MP.toast(r.error ? `${msg}. ${r.error} ${MP.tn(r.kept, "{n} job kept.", "{n} jobs kept.")}` : msg, r.error ? 8000 : 3000);
            info = await MP.api("/api/lab");
            showStatus();
          } catch (e) { MP.toast(e.message, 6000); }
          clearBtns.forEach((x) => { x.disabled = x.dataset.scope === "mine" && !MP.prefs.name; });
        });
        dlg.showModal();
        go.focus();
      }));
    }
    MP.$("#forget-btn")?.addEventListener("click", () => {
      if (!confirm(MP.t("Forget the remembered inputs, sample colours and saved plate layouts in this browser?"))) return;
      try {
        Object.keys(localStorage).filter((k) => k.startsWith("mp:")).forEach((k) => localStorage.removeItem(k));
        MP.toast(MP.t("Forgotten"));
      } catch (_) { MP.toast(MP.t("Could not save")); }
    });
})();

// Settings → Server & updates: version info, "Check for updates", "Sync with git", restart.
(function () {
  const { $, el, icon, api } = MP;
  if (!$("#git-info")) return;
  let info = null;

  function kv(dl, rows) {
    dl.replaceChildren(...rows.filter(Boolean).flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
  }

  function date(iso) { return iso ? MP.datetime(iso) : ""; }

  function badge(text, cls) { const b = $("#sync-badge"); b.textContent = text; b.className = "badge " + (cls || ""); }

  function renderGit(g) {
    if (!g.is_repo) {  // a Docker image or a package: updated another way (updater.HOW)
      const r = g.running || {};
      kv($("#git-info"), [
        [MP.t("Running version"), el("span", {}, g.version || "", r.short && r.short !== "dev" ? el("code", {}, " " + r.short) : "")],
        [MP.t("How it is updated"), MP.t(g.how || "This folder is not a git repository.")],
      ]);
      badge(g.version || MP.t("no git"), g.install === "docker" ? "" : "warn");
      for (const id of ["#sync-btn", "#check-btn"]) $(id).hidden = true;
      for (const id of ["#branch-pick", "#auto-update"]) $(id).hidden = true;
      return;
    }
    const r = g.running;
    kv($("#git-info"), [
      [MP.t("Running version"), el("span", {}, el("code", {}, r.short), " ", r.subject)],
      [MP.t("Committed"), MP.t("{when} by {who}", { when: date(r.date), who: r.author })],
      g.restart_pending ? [MP.t("On disk"), el("span", {}, el("code", {}, g.head.short), " — ", MP.t("newer than what is running; restart to apply"))] : null,
      [MP.t("Branch"), el("span", {}, el("code", {}, g.branch), g.upstream ? ` → ${g.upstream}` : " " + MP.t("(no upstream)"))],
      [MP.t("Remote"), g.remote || "—"],
      [MP.t("Last checked"), g.last_fetch ? MP.ago(g.last_fetch) : MP.t("never")],
      g.dirty.length ? [MP.t("Local edits"), el("span", { class: "status-failed" }, MP.tn(g.dirty.length, "{n} file changed on this machine", "{n} files changed on this machine") + `: ${g.dirty.slice(0, 4).join(", ") + (g.dirty.length > 4 ? "…" : "")} — ` + MP.t("a sync may refuse to overwrite them."))] : null,
    ]);
    if (g.auto) {
      $("#auto-update-select").value = g.auto.mode;
      const l = g.auto.last;
      $("#auto-update-last").textContent = l ? MP.t("Last night: {result} ({when})", { result: MP.t(l.result), when: MP.datetime(l.at) }) : "";
    }
    if (g.behind) badge(MP.tn(g.behind, "{n} update available", "{n} updates available"), "new");
    else if (g.ahead) badge(MP.tn(g.ahead, "{n} local commit not pushed", "{n} local commits not pushed"), "warn");
    else badge(MP.t("up to date"), "ok");
  }

  function renderIncoming(g) {
    const box = $("#incoming");
    if (!g.incoming || !g.incoming.length) { box.replaceChildren(); return; }
    box.replaceChildren(el("div", { class: "incoming" },
      el("div", { class: "incoming-head" }, MP.t("Coming in with the next sync ({n})", { n: g.incoming.length })),
      ...g.incoming.map((c) => el("div", { class: "commit" }, el("code", {}, c.short), el("span", {}, c.subject), el("span", { class: "who" }, `${c.author} · ${MP.ago(Date.parse(c.date) / 1000)}`)))));
  }

  function installKind(k) {
    return ({
      docker: MP.t("Docker"), "mac-app": MP.t("the Mac app"), service: MP.t("a service"),
      checkout: MP.t("a git clone"), package: MP.t("a package"),
    })[k] || k;
  }

  function renderServer(s) {
    kv($("#server-info"), [
      [MP.t("Open from"), el("code", {}, s.url_hint)],
      [MP.t("Uptime"), MP.duration(s.uptime_s)],
      [MP.t("Tools"), MP.t("{n} loaded", { n: s.tools }) + (s.broken.length ? ", " + MP.t("{n} broken", { n: s.broken.length }) : "")],
      [MP.t("Running jobs"), String(s.active_jobs.length)],
      [MP.t("Disk free"), MP.t("{free} of {total}", { free: MP.bytes(s.disk_free), total: MP.bytes(s.disk_total) })],
      [MP.t("Data folder"), el("code", {}, s.data_dir)],
      ...(s.install ? [
        [MP.t("Installed as"), installKind(s.install.kind)],
        [MP.t("Code folder"), el("code", {}, s.install.code)],
        [MP.t("Instance folder"), s.install.separate ? el("code", {}, s.install.home) : MP.t("the code folder")],
      ] : []),
      ["Python", s.python],
      [MP.t("System"), s.platform],
    ]);
  }

  async function load() {
    try {
      info = await api("/api/system");
      renderGit(info.git);
      renderServer(info.server);
    } catch (e) { MP.toast(e.message); }
  }

  function busy(btn, on, label) {
    btn.disabled = on;
    if (on) btn.replaceChildren(el("span", { class: "spinner" }), el("span", {}, label));
  }

  function logStep(name, ok, output) {
    const log = $("#sync-log");
    log.hidden = false;
    const head = el("div", { class: "step-head " + (ok === null ? "" : ok ? "ok" : "bad") },
      ok === null ? el("span", { class: "spinner", style: "width:14px;height:14px" }) : icon(ok ? "check" : "alert", 16), MP.t(name));
    const s = el("div", { class: "step" }, head, output ? el("pre", {}, output) : null);
    log.append(s);
    return s;
  }

  $("#auto-update-select").addEventListener("change", async (e) => {
    try { await api("/api/system/auto-update", { json: { mode: e.currentTarget.value } }); MP.toast(MP.t("Saved")); }
    catch (err) { MP.toast(err.message, 5000); }
  });

  $("#check-btn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    busy(btn, true, MP.t("Checking…"));
    try {
      const d = await api("/api/system/check", { method: "POST" });
      renderGit(d.git);
      renderIncoming(d.git);
      if (!d.git.fetch_ok) {
        // without a fresh fetch the count above is from the last good check, so don't call it "up to date"
        badge(MP.t("couldn't check"), "warn");
        $("#sync-log").replaceChildren();
        logStep("Couldn't reach GitHub (git fetch failed)", false, d.git.fetch_output);
      }
      else if (!d.git.incoming.length) MP.toast(MP.t("Already up to date"));
    } catch (err) { MP.toast(err.message); }
    btn.disabled = false;
    btn.replaceChildren(icon("search", 16), el("span", {}, MP.t("Check for updates")));
  });

  async function waitForRestart(prev, wantNewCommit) {
    const step = logStep("Restarting server…", null);
    const t0 = Date.now();
    while (Date.now() - t0 < 120000) {
      await new Promise((r) => setTimeout(r, 1000));
      try {
        const v = await api("/api/version");
        if (v.started !== prev.started || (wantNewCommit && v.commit !== prev.commit)) {
          step.replaceWith(logStep(MP.t("Back online on {version} — reloading", { version: v.short }), true));
          setTimeout(() => location.reload(), 700);
          return;
        }
      } catch (_) { /* still down */ }
    }
    step.replaceWith(logStep("The server did not come back within 2 minutes. Check the log on the server (logs/server.log).", false));
  }

  async function sync(force) {
    const btn = $("#sync-btn");
    const prev = await api("/api/version");
    busy(btn, true, MP.t("Syncing…"));
    $("#sync-log").replaceChildren();
    try {
      const d = await api("/api/system/sync", { json: { force } });
      d.steps.forEach((s) => logStep(s.name, s.ok, s.output));
      if (d.ok && !d.changed && !d.restart) logStep("Already up to date — nothing to do", true);
      if (d.restarting) return waitForRestart(prev, true);
      if (d.restart && !d.restarting) logStep("Dev mode: the auto-reloader picks up the new code", true);
    } catch (err) {
      if (err.status === 409 && err.data && err.data.needs_confirm) {
        const n = err.data.active.length;
        if (confirm(MP.tn(n, "{n} job still running", "{n} jobs still running") + ` (${err.data.active.map((j) => MP.t(j.tool_name)).join(", ")}).\n` + MP.t("Updating restarts the server and interrupts them. Continue?"))) {
          return sync(true);
        }
      } else if (err.data && err.data.steps) {
        err.data.steps.forEach((s) => logStep(s.name, s.ok, s.output));
      } else {
        logStep(err.message, false);
      }
    }
    btn.disabled = false;
    btn.replaceChildren(icon("sync", 16), el("span", {}, MP.t("Sync with git")));
    load();
  }

  $("#sync-btn").addEventListener("click", () => {
    if (confirm(MP.t("Pull the latest version from GitHub and restart MISTER PLIS?"))) sync(false);
  });

  $("#restart-btn").addEventListener("click", async () => {
    if (!confirm(MP.t("Restart the server? Running jobs will be interrupted."))) return;
    const prev = await api("/api/version");
    $("#sync-log").replaceChildren();
    const d = await api("/api/system/restart", { method: "POST" });
    if (d.restarting) waitForRestart(prev, false);
    else MP.toast(MP.t("Running in dev mode (--reload): restart it from the terminal"));
  });

  // ---- run another branch (a test branch on a laptop, say)
  const branchSel = $("#branch-select"), branchBtn = $("#branch-btn");
  let current = "";
  async function loadBranches() {
    try {
      const d = await api("/api/system/branches");
      current = d.current;
      const names = d.branches.map((b) => b.name);
      if (current && !names.includes(current)) names.unshift(current);
      branchSel.replaceChildren(...names.map((n) => {
        const b = d.branches.find((x) => x.name === n);
        return el("option", { value: n }, n === current ? `${n} — ${MP.t("running now")}` : b ? `${n} · ${MP.date(b.date)}` : n);
      }));
      branchSel.value = current;
      if (!d.fetch_ok) MP.toast(MP.t("Couldn't reach GitHub (git fetch failed)"), 4000);
    } catch (e) {
      branchSel.replaceChildren(el("option", { value: "" }, MP.t("not available")));
    }
    branchBtn.disabled = !branchSel.value || branchSel.value === current;
  }
  branchSel.addEventListener("change", () => { branchBtn.disabled = !branchSel.value || branchSel.value === current; });

  async function switchBranch(force) {
    const branch = branchSel.value;
    const prev = await api("/api/version");
    busy(branchBtn, true, MP.t("Switching…"));
    $("#sync-log").replaceChildren();
    try {
      const d = await api("/api/system/branch", { json: { branch, force } });
      d.steps.forEach((s) => logStep(s.name, s.ok, s.output));
      if (d.restarting) return waitForRestart(prev, true);
      if (d.restart) logStep("Dev mode: the auto-reloader picks up the new code", true);
      else logStep("Already on this version — nothing to restart", true);
    } catch (err) {
      if (err.status === 409 && err.data && err.data.needs_confirm) {
        const n = err.data.active.length;
        if (confirm(MP.tn(n, "{n} job still running", "{n} jobs still running") + ".\n" + MP.t("Updating restarts the server and interrupts them. Continue?"))) return switchBranch(true);
      } else if (err.data && err.data.steps) err.data.steps.forEach((s) => logStep(s.name, s.ok, s.output));
      else logStep(err.message, false);
    }
    branchBtn.replaceChildren(icon("branch", 16), el("span", {}, MP.t("Switch")));
    loadBranches();
    load();
  }
  branchBtn.addEventListener("click", () => {
    if (confirm(MP.t("Switch this server to the branch “{branch}” and restart it? Everyone using this server gets that version.", { branch: branchSel.value }))) switchBranch(false);
  });

  MP.whenShown($("#git-info"), () => { load(); loadBranches(); });
})();

// People: everyone who added anything (ran a job, sent feedback) under the name set in the top bar.
// Two names of one person ("Ola", "Ola Nowak") can be merged: the old one goes for good.
(function () {
  const { $, el, api } = MP;
  const box = $("#people-list");
  if (!box) return;
  let people = [];

  function render() {
    $("#people-sum").textContent = people.length ? MP.tn(people.length, "{n} person", "{n} people") : "";
    if (!people.length) { box.replaceChildren(el("div", { class: "fb-empty" }, MP.t("No names yet — jobs run without a name in the top bar aren't counted."))); return; }
    box.replaceChildren(...people.map((p) => el("div", { class: "person" },
      el("a", { class: "person-link", href: `/jobs?person=${encodeURIComponent(p.name)}`,
        title: MP.t("first {first} · last {last}", { first: MP.date(p.first), last: MP.date(p.last) }) },
        el("span", { class: "person-avatar", "aria-hidden": "true" }, (p.name.trim()[0] || "?").toUpperCase()),
        el("span", { class: "person-text" },
          el("span", { class: "person-name" }, p.name),
          el("span", { class: "person-meta" }, meta(p)))),
      people.length > 1 ? el("button", { type: "button", class: "link-btn person-merge", title: MP.t("This is the same person as someone else in the list"),
        onclick: () => mergeDialog(p) }, MP.t("Merge into…")) : null)));
  }

  function meta(p) {
    return [
      p.jobs ? MP.tn(p.jobs, "{n} job", "{n} jobs") : "",
      p.feedback ? MP.tn(p.feedback, "{n} feedback", "{n} feedback") : "",
      p.kept ? MP.tn(p.kept, "{n} kept in Time Machine", "{n} kept in Time Machine") : "",
      MP.t("last {when}", { when: MP.date(p.last) }),
    ].filter(Boolean).join(" · ");
  }

  function mergeDialog(p) {
    const others = people.filter((x) => x !== p);
    const sel = el("select", {}, ...others.map((x) => el("option", { value: x.name }, x.name)));
    const note = el("p", { class: "muted" });
    const explain = () => { note.textContent = MP.t("Everything under “{from}” — jobs, feedback, what they kept in Time Machine, the tasks given to them — moves to “{into}”, and “{from}” disappears from the list. Anyone still using the name “{from}” is counted as “{into}”. This can't be undone.", { from: p.name, into: sel.value }); };
    sel.addEventListener("change", explain);
    explain();
    const dlg = el("dialog", { class: "dialog dialog-ask" }, el("form", { method: "dialog" },
      el("h3", {}, MP.t("Merge “{name}” into…", { name: p.name })),
      el("label", { class: "field" }, el("span", { class: "field-label" }, MP.t("The same person, under the name to keep:")), el("div", { class: "control" }, sel)),
      note,
      el("div", { class: "dialog-actions" },
        el("button", { type: "button", class: "btn", onclick: () => dlg.close("cancel") }, MP.t("Cancel")),
        el("button", { type: "submit", class: "btn btn-primary", value: "ok" }, MP.t("Merge")))));
    document.body.append(dlg);
    dlg.addEventListener("close", async () => {
      dlg.remove();
      if (dlg.returnValue !== "ok") return;
      try {
        const d = await api("/api/people/merge", { json: { from: p.name, into: sel.value } });
        people = d.people;
        render();
        MP.toast(MP.t("“{from}” merged into “{into}”", { from: d.from, into: d.into }));
      } catch (e) { MP.toast(e.message, 4000); }
    });
    dlg.showModal();
    sel.focus();
  }

  MP.whenShown(box, async () => {
    try { people = (await api("/api/people")).people; render(); }
    catch (e) { box.replaceChildren(el("div", { class: "fb-empty" }, e.message)); }
  });
})();

// Storage: where the jobs are kept (one folder each) and what tools save; moving it to another folder.
(function () {
  const { $, el, api } = MP;
  const box = $("#storage-info");
  if (!box) return;

  const input = $("#storage-dir"), btn = $("#storage-btn");
  let current = "";
  input.addEventListener("input", () => { btn.disabled = !input.value.trim() || input.value.trim() === current; });

  function render(s) {
    current = s.path;
    input.value = s.path;
    btn.disabled = true;
    const map = $("#map-storage");
    if (map) map.textContent = s.path;
    const rows = [
      [MP.t("Jobs"), String(s.jobs)],
      s.disk_free != null ? [MP.t("Disk free"), MP.t("{free} of {total}", { free: MP.bytes(s.disk_free), total: MP.bytes(s.disk_total) })] : null,
      s.is_data_dir ? [MP.t("Note"), MP.t("the server's data folder (no storage folder chosen)")] : null,
      s.network ? [MP.t("Note"), MP.t("this looks like a network folder — jobs are faster and safer on a disk of this computer")] : null,
      s.migration && s.migration.from ? [MP.t("Moved from"), MP.t("{from}: {n} job(s)", { from: s.migration.from, n: s.migration.copied })] : null,
      s.migration && s.migration.failed && s.migration.failed.length ? [MP.t("Not moved yet"), s.migration.failed.join("\n")] : null,
      s.problems && s.problems.length ? [MP.t("Unreadable jobs"), s.problems.join("\n")] : null,
    ];
    box.replaceChildren(...rows.filter(Boolean).flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
  }

  async function load() {
    try { render(await api("/api/system/storage")); } catch (e) { MP.toast(e.message); }
  }

  btn.addEventListener("click", async (e) => {
    const dir = input.value.trim();
    if (!dir) { MP.toast(MP.t("Give the full path of the storage folder.")); return; }
    if (!confirm(MP.t("Copy the jobs to {dir}, check them, and restart the server with that folder?", { dir }))) return;
    const btn = e.currentTarget;
    btn.disabled = true;
    const log = $("#storage-log");
    log.hidden = false;
    log.replaceChildren(el("div", { class: "step-head" }, el("span", { class: "spinner", style: "width:14px;height:14px" }), MP.t("Copying…")));
    try {
      const d = await api("/api/system/storage", { json: { dir, move: true } });
      log.replaceChildren(...d.steps.map((s) => el("div", { class: "step-head ok" }, MP.icon("check", 16), s.name)));
      if (d.restarting) {
        MP.toast(MP.t("Restarting with the new storage folder…"));
        setTimeout(() => location.reload(), 6000);
      }
    } catch (err) {
      log.replaceChildren(el("div", { class: "step-head bad" }, MP.icon("alert", 16), err.message));
      btn.disabled = false;
    }
  });

  MP.whenShown(box, load);
})();

// Tool sources: the git repositories tools come from (mister_plis/toolsources.py).
(function () {
  const { $, el, api } = MP;
  const list = $("#ts-list");
  if (!list) return;
  const log = $("#ts-log");
  const say = (text, ok = true) => {
    log.hidden = false;
    log.replaceChildren(el("div", { class: "step-head " + (ok ? "ok" : "bad") }, MP.icon(ok ? "check" : "alert", 16), text));
  };
  const restartOffer = () => {
    log.hidden = false;
    log.append(el("div", { class: "sync-actions" }, el("button", { class: "btn btn-primary", onclick: async () => {
      if (!confirm(MP.t("Restart the server? Running jobs will be interrupted."))) return;
      await api("/api/system/restart", { method: "POST" });
      MP.toast(MP.t("Restarting…"));
      setTimeout(() => location.reload(), 6000);
    } }, MP.t("Restart now to load the tools"))));
  };
  const act = async (fn) => {
    try {
      const r = await fn();
      if (r && r.requirements && r.requirements.ok === false) say(r.requirements.output || MP.t("Its packages couldn't be installed."), false);
      else if (r && r.restart_needed) { say(MP.t("Done — the change takes effect after a restart.")); restartOffer(); }
      else say(MP.t("Done."));
    } catch (e) { say(e.message, false); }
    load();
  };

  function about(m) {  // what a source's manifest says about it (description, maintainer, homepage, licence)
    if (!m) return null;
    const bits = [m.maintainer ? MP.t("by {who}", { who: m.maintainer }) : null, m.license || null].filter(Boolean);
    if (!m.description && !bits.length && !m.homepage) return null;
    return el("div", { class: "ts-note muted" }, m.description || "", bits.length ? (m.description ? " · " : "") + bits.join(" · ") : "",
      m.homepage ? el("span", {}, " · ", el("a", { href: m.homepage, target: "_blank", rel: "noopener" }, m.homepage)) : null);
  }

  // What a source's tools need installed: installing a package can run its code, so it is said before the source is
  // switched on (or updated), with the lines that won't be installed (mister_plis/toolsources.py requirements_review).
  function packagesNote(r) {
    if (!r || (!(r.packages || []).length && !(r.refused || []).length)) return null;
    return el("div", { class: "alert alert-warning ts-packages" }, MP.icon("alert", 16), el("div", {},
      (r.packages || []).length ? el("div", {}, MP.t("Its tools need these packages: {names}. Installing a package can run that package's code; they are installed only when the source is switched on, and only ready-made ones.", { names: r.packages.join(", ") })) : null,
      (r.refused || []).length ? el("div", {}, el("b", {}, MP.t("Not allowed, never installed:")), el("pre", {}, r.refused.join("\n"))) : null));
  }

  function row(s, loaded) {
    if (s.bundled) {
      const n = Object.values(loaded).filter((x) => x === s.name).length;
      return el("div", { class: "ts-row" }, el("div", {},
        el("div", { class: "ts-title" }, `${s.manifest && s.manifest.title ? s.manifest.title : s.name} `, el("span", { class: "muted" }, `(${s.name})`)),
        el("div", { class: "ts-sub" }, [MP.t("comes with MISTER PLIS {version}", { version: s.version }),
          s.replaced_by_local ? MP.t("not loaded: a folder on this computer stands in for it") : MP.tn(n, "{n} tool loaded", "{n} tools loaded")].join(" · "))),
        el("div", { class: "ts-actions" }, el("button", { type: "button", class: "btn btn-small",
          onclick: () => act(() => api(`/api/tools/sources/${s.name}/enable`, { json: { on: !s.enabled } })) }, s.enabled ? MP.t("Switch off") : MP.t("Switch on"))),
        !s.enabled ? el("div", { class: "ts-note ts-warn" }, MP.t("Switched off: its tools aren't loaded.")) : null, about(s.manifest));
    }
    if (s.local) {
      const n = Object.values(loaded).filter((x) => x === s.name).length;
      return el("div", { class: "ts-row" }, el("div", {},
        el("div", { class: "ts-title" }, `${s.manifest && s.manifest.title ? s.manifest.title : s.name} `, el("span", { class: "muted" }, `(${s.name})`)),
        el("div", { class: "ts-sub" }, [MP.t("a folder on this computer (tool_folders in config.toml)"), s.url,
          MP.tn(n, "{n} tool loaded", "{n} tools loaded")].join(" · ")),
        s.error ? el("div", { class: "ts-error" }, s.error) : null));
    }
    const n = Object.values(loaded).filter((x) => x === s.name).length;
    const head = s.head ? `${s.head.short} · ${MP.datetime(s.head.date)} · ${s.head.subject}` : MP.t("not fetched yet");
    const sub = [s.url, `${MP.t("branch")} ${s.branch}`, head, s.pinned ? MP.t("pinned to {c}", { c: s.pinned.slice(0, 10) }) : null,
      s.replaced_by_local ? MP.t("not loaded: a folder on this computer stands in for it")
        : s.cloned ? MP.tn(n, "{n} tool loaded", "{n} tools loaded") : null].filter(Boolean).join(" · ");
    const btn = (label, fn, opts = {}) => el("button", { type: "button", class: "btn btn-small" + (opts.primary ? " btn-primary" : ""), onclick: fn }, label);
    const review = el("div", { class: "ts-review", hidden: true });
    const actions = el("div", { class: "ts-actions" },
      btn(MP.t("Check"), async () => {
        try {
          const r = await api(`/api/tools/sources/${s.name}/check`, { method: "POST" });
          review.hidden = false;
          review.replaceChildren(
            el("b", {}, r.incoming.length ? MP.tn(r.incoming.length, "{n} new commit", "{n} new commits") : MP.t("Up to date.")),
            ...r.incoming.map((c) => el("div", {}, `${c.short} · ${c.author} · ${c.subject}`)),
            r.files.length ? el("pre", {}, r.files.join("\n")) : null,
            r.requirements !== undefined ? packagesNote(r) : null,
            r.incoming.length ? el("div", { class: "sync-actions" }, btn(MP.t("Update"), () => act(() => api(`/api/tools/sources/${s.name}/update`, { json: { to: r.target } })), { primary: true })) : null);
        } catch (e) { say(e.message, false); }
      }),
      btn(MP.t("Branch…"), async () => {
        const b = await MP.ask(MP.t("Which branch should this source follow?"), s.branch);
        if (b) act(() => api(`/api/tools/sources/${s.name}/branch`, { json: { branch: b.trim() } }));
      }),
      s.trusted ? btn(s.pinned ? MP.t("Unpin") : MP.t("Pin"), () => act(() => api(`/api/tools/sources/${s.name}/pin`, { json: { pinned: !s.pinned } }))) : null,
      btn(s.enabled ? MP.t("Switch off") : MP.t("Switch on"), () => {
        if (!s.enabled && !s.trusted && !confirm(MP.t("Switch on the tools of {url}? They will run inside the server, with access to everything in it.", { url: s.url }))) return;
        act(() => api(`/api/tools/sources/${s.name}/enable`, { json: { on: !s.enabled } }));
      }),
      btn(MP.t("Remove"), () => { if (confirm(MP.t("Remove the tool source {name}?", { name: s.name }))) act(() => api(`/api/tools/sources/${s.name}`, { method: "DELETE" })); }));
    const notes = [];
    if (!s.enabled) notes.push(el("div", { class: "ts-note ts-warn" }, MP.t("Switched off: its tools aren't loaded.")));
    if (s.error) notes.push(el("div", { class: "ts-note ts-warn" }, s.error));
    if (s.dirty && s.dirty.length) notes.push(el("div", { class: "ts-note ts-warn" }, MP.t("Files were changed here on the server: {files}", { files: s.dirty.join(", ") })));
    if (!s.trusted) notes.push(el("div", { class: "ts-note muted" }, MP.t("Not the lab's own: fetched without the server's GitHub token, pinned, every update reviewed.")));
    return el("div", { class: "ts-row" }, el("div", {}, el("div", { class: "ts-title" }, s.manifest && s.manifest.title ? `${s.manifest.title} (${s.name})` : s.name),
      el("div", { class: "ts-sub" }, sub)), actions, about(s.manifest), ...notes, review);
  }

  // Browse a catalogue (mister_plis/catalogue.py)
  const catList = $("#cat-list");
  async function loadCatalogue() {
    if (!catList) return;
    try {
      const d = await api("/api/tools/catalogue");
      $("#cat-address").value = d.address || "";
      if (!d.address) { catList.replaceChildren(el("div", { class: "muted pad" }, MP.t("No catalogue is set."))); return; }
      if (d.error) { catList.replaceChildren(el("div", { class: "ts-note ts-warn" }, d.error)); return; }
      if (!d.sources.length) { catList.replaceChildren(el("div", { class: "muted pad" }, MP.t("The catalogue lists nothing."))); return; }
      catList.replaceChildren(...d.sources.map((c) => el("div", { class: "ts-row" },
        el("div", {}, el("div", { class: "ts-title" }, `${c.title} `, el("span", { class: "muted" }, `(${c.name})`)),
          el("div", { class: "ts-sub" }, [c.url, c.tags.length ? c.tags.join(", ") : null,
            c.fits ? null : MP.t("needs toolkit {v}", { v: c.requires_toolkit })].filter(Boolean).join(" · "))),
        el("div", { class: "ts-actions" }, c.added ? el("span", { class: "badge ok" }, MP.t("added"))
          : el("button", { type: "button", class: "btn btn-small", disabled: !c.fits, onclick: async () => {
            try {
              const r = await api("/api/tools/catalogue/add", { json: { name: c.name } });
              log.hidden = false;
              log.replaceChildren(el("div", { class: "step-head ok" }, MP.icon("check", 16), MP.t("Added {name}: switched off and pinned. Read what it contains, then switch it on.", { name: r.name })),
                el("div", { class: "ts-review" }, el("b", {}, MP.tn(r.review.n_files, "{n} file", "{n} files")), el("pre", {}, r.review.files.join("\n")),
                  packagesNote(r.review)));
            } catch (e) { say(e.message, false); }
            load(); loadCatalogue();
          } }, MP.t("Add"))),
        about(c))));
    } catch (e) { catList.replaceChildren(el("div", { class: "muted pad" }, e.message)); }
  }
  if (catList) {
    $("#cat-save").addEventListener("click", async () => {
      try { await api("/api/tools/catalogue", { json: { address: $("#cat-address").value.trim() } }); MP.toast(MP.t("Saved for the whole lab")); }
      catch (e) { MP.toast(e.message, 5000); }
      loadCatalogue();
    });
    MP.whenShown(catList, loadCatalogue);
  }

  async function load() {
    try {
      const d = await api("/api/tools/sources");
      list.replaceChildren(...(d.sources.length ? d.sources.map((s) => row(s, d.loaded)) : [el("div", { class: "muted pad" }, MP.t("No tool sources."))]));
    } catch (e) { list.replaceChildren(el("div", { class: "muted pad" }, e.message)); }
  }

  $("#ts-add").addEventListener("click", async () => {
    const url = $("#ts-url").value.trim();
    if (!url) return;
    const token = $("#ts-token").value.trim();
    try {
      const r = await api("/api/tools/sources", { json: { url, name: $("#ts-name").value.trim(), token } });
      log.hidden = false;
      log.replaceChildren(el("div", { class: "step-head ok" }, MP.icon("check", 16), MP.t("Added {name}: switched off and pinned. Read what it contains, then switch it on.", { name: r.name })),
        el("div", { class: "ts-review" }, el("b", {}, MP.tn(r.review.n_files, "{n} file", "{n} files")),
          el("pre", {}, r.review.files.join("\n")), r.review.requirements ? el("pre", {}, MP.t("Packages it needs:") + "\n" + r.review.requirements) : null,
          packagesNote(r.review)));
      $("#ts-url").value = $("#ts-name").value = $("#ts-token").value = "";
    } catch (e) {
      say(e.message, false);
      // GitHub asked for a login: a private repository (or a token that can't read it)
      if (/could not read Username|Authentication failed|Repository not found|terminal prompts disabled/i.test(e.message))
        log.append(el("div", { class: "ts-note muted" }, token
          ? MP.t("The token couldn't read this repository: check that it gives read access to its contents and hasn't expired.")
          : MP.t("A private repository needs a token: paste one that can read it, and add it again.")));
    }
    load();
  });
  MP.whenShown(list, load);
})();

// Settings → Server & updates → GitHub access: the instance's own tokens, one per host, owner or repository
// (mister_plis/credentials.py). A token is sent once and never comes back: the list shows its last four characters.
(function () {
  const { $, el, api } = MP;
  const list = $("#cred-list");
  if (!list) return;

  function where(t) {
    return t.repo ? `${t.host}/${t.owner}/${t.repo}` : t.owner ? `${t.host}/${t.owner}/*` : `${t.host} — ${MP.t("every repository")}`;
  }

  function render(d) {
    list.replaceChildren(...(d.tokens.length ? d.tokens.map((t) => el("li", { class: "cred-row" },
      el("code", {}, where(t)), el("span", { class: "muted" }, `…${t.last4}`),
      el("span", { class: "muted" }, t.added ? MP.t("added {when}", { when: t.added }) : ""),
      el("button", { type: "button", class: "btn btn-small", onclick: () => remove(t) }, MP.t("Remove"))))
      : [el("li", { class: "muted" }, MP.t("No tokens on this server yet."))]));
    const other = [];
    if (d.env) other.push(MP.t("MISTER_PLIS_GIT_TOKEN is set on this server: it serves any repository no token here matches."));
    if (d.checkout_helpers.length) other.push(MP.t("After these, git asks the code checkout's own credential helper ({helpers}), e.g. the Mac's Keychain.", { helpers: d.checkout_helpers.join(", ") }));
    $("#cred-other").textContent = other.join(" ");
  }

  async function load() {
    try { render(await api("/api/system/credentials")); } catch (e) { MP.toast(e.message, 5000); }
  }

  async function remove(t) {
    if (!confirm(MP.t("Remove the token for {where}? Repositories that need it can't be read any more.", { where: where(t) }))) return;
    try {
      render(await api("/api/system/credentials", { method: "DELETE", json: { host: t.host, owner: t.owner, repo: t.repo } }));
      MP.toast(MP.t("Removed"));
    } catch (e) { MP.toast(e.message, 5000); }
  }

  $("#cred-add").addEventListener("click", async () => {
    const token = $("#cred-token");
    try {
      render(await api("/api/system/credentials", { json: {
        host: $("#cred-host").value.trim(), owner: $("#cred-owner").value.trim(), repo: $("#cred-repo").value.trim(), token: token.value.trim() } }));
      token.value = $("#cred-owner").value = $("#cred-repo").value = "";
      MP.toast(MP.t("Saved for the whole lab"));
    } catch (e) { MP.toast(e.message, 5000); }
  });
  MP.whenShown(list, load);
})();

// Settings → Server & updates → The lab: its name (sidebar, PDF reports, backups), for everyone.
(function () {
  const { $, api } = MP;
  const input = $("#lab-name");
  if (!input) return;
  const save = async () => {
    try {
      const d = await api("/api/lab/name", { json: { lab_name: input.value.trim() } });
      input.value = d.saved;
      const sub = document.querySelector(".brand-sub");
      if (sub) sub.textContent = d.lab_name || MP.t("lab toolbox");
      MP.toast(MP.t("Saved for the whole lab"));
    } catch (e) { MP.toast(e.message, 5000); }
  };
  $("#lab-name-save").addEventListener("click", save);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); save(); } });
  // a setting of the whole lab saved with its own button (and Enter): the largest upload
  const saveOne = (inputSel, buttonSel, url, body, after) => {
    const box = $(inputSel);
    if (!box) return;
    const go = async () => {
      try { const d = await api(url, { json: body(box.value) }); if (after) after(box, d); MP.toast(MP.t("Saved for the whole lab")); }
      catch (e) { MP.toast(e.message, 5000); }
    };
    $(buttonSel).addEventListener("click", go);
    box.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
  };
  saveOne("#max-upload", "#max-upload-save", "/api/lab/uploads", (v) => ({ max_upload_mb: parseInt(v, 10) || 0 }),
          (box, d) => { box.value = d.max_upload_mb || d.default_max_upload_mb; });
})();

// Settings → Server & updates → Snapshots of the lab's settings (updates.py), and what the release feed has.
(function () {
  const { $, el, api } = MP;
  const list = $("#snapshot-list");
  if (!list) return;

  function show(snaps) {
    if (!snaps.length) { list.replaceChildren(el("li", { class: "muted" }, MP.t("No snapshots yet."))); return; }
    list.replaceChildren(...snaps.map((s) => {
      const btn = el("button", { type: "button", class: "btn btn-small" }, MP.t("Restore"));
      btn.addEventListener("click", async () => {
        if (!confirm(MP.t("Restore the lab's settings from {name} and restart the server? The settings now are kept, renamed.", { name: s.name }))) return;
        btn.disabled = true;
        try { await api("/api/system/snapshots/restore", { json: { name: s.name } }); MP.toast(MP.t("Restarting…")); setTimeout(() => location.reload(), 6000); }
        catch (e) { MP.toast(e.message, 5000); btn.disabled = false; }
      });
      return el("li", {}, el("span", {}, el("b", {}, s.name)),
        el("span", { class: "muted" }, (s.version ? s.version + " · " : "") + MP.tn(s.files, "{n} file", "{n} files")), btn);
    }));
  }

  async function load() {
    try { show((await api("/api/system/snapshots")).snapshots); } catch (e) { /* the panel stays empty */ }
    try {
      const u = await api("/api/system/updates");
      const newest = (u.available || [])[0];
      const dl = $("#git-info");
      if (newest && dl) {
        dl.append(el("dt", {}, MP.t("Newest release")),
          el("dd", {}, `${newest.version}${newest.date ? " (" + newest.date + ")" : ""}${newest.notes ? " — " + newest.notes : ""}`));
      }
    } catch (e) { /* no feed: nothing to add */ }
  }

  $("#snapshot-now").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try { show((await api("/api/system/snapshots", { method: "POST" })).snapshots); MP.toast(MP.t("Saved for the whole lab")); }
    catch (err) { MP.toast(err.message, 5000); }
    finally { btn.disabled = false; }
  });
  MP.whenShown(list, load);
})();

// Settings → Tools → Settings of the tools: what each tool declares it needs on this server (Tool(settings=...),
// toolkit 1.1) — where Blender is, say — with the tool's own status line ("Found: …").
(function () {
  const { $, el, api } = MP;
  const list = $("#tset-list");
  if (!list) return;

  function field(inp, value) {
    const id = `tset-${inp.name}-${Math.random().toString(36).slice(2, 7)}`;
    let control;
    if (inp.kind === "checkbox") {
      control = el("input", { type: "checkbox", id });
      control.checked = !!value;
      return { node: el("label", { class: "tset-check" }, control, el("span", {}, inp.label)), get: () => control.checked };
    }
    if (inp.kind === "select") {
      control = el("select", { id }, (inp.options || []).map(([v, label]) => el("option", { value: v }, label)));
      control.value = value ?? "";
    } else if (inp.kind === "textarea") {
      control = el("textarea", { id, rows: inp.rows || 3, placeholder: inp.placeholder || "", spellcheck: "false" });
      control.value = value ?? "";
    } else {
      const num = inp.kind === "number" || inp.kind === "integer";
      control = el("input", { id, type: "text", inputmode: num ? "decimal" : null, placeholder: inp.placeholder || "", spellcheck: "false" });
      control.value = value ?? "";
    }
    return {
      node: el("label", { class: "field", for: id }, el("span", { class: "field-label" }, inp.label), el("div", { class: "control" }, control),
        inp.help ? el("span", { class: "setting-help" }, inp.help) : null),
      get: () => control.value,
    };
  }

  function block(t) {
    const fields = t.inputs.map((inp) => [inp.name, field(inp, t.values[inp.name])]);
    const status = el("div", { class: "tset-status" }, t.status || "");
    const save = el("button", { type: "button", class: "btn btn-small btn-primary" }, MP.t("Save"));
    const check = el("button", { type: "button", class: "btn btn-small" }, MP.t("Check"));
    const swap = (d) => { const b = block(d); node.replaceWith(b); return b; };
    save.addEventListener("click", async () => {
      save.disabled = true;
      try {
        const d = await api(`/api/tools/${encodeURIComponent(t.id)}/settings`, { json: { values: Object.fromEntries(fields.map(([n, f]) => [n, f.get()])) } });
        swap(d);
        MP.toast(MP.t("Saved for the whole lab"));
      } catch (e) { MP.toast(e.message, 6000); save.disabled = false; }
    });
    check.addEventListener("click", load);
    const node = el("div", { class: "tset-tool", id: `tset-${t.id}` },
      el("div", { class: "tset-title" }, el("b", {}, t.name), t.source ? el("span", { class: "muted" }, ` · ${t.source}`) : null),
      el("div", { class: "tset-fields" }, fields.map(([, f]) => f.node)),
      status,
      el("div", { class: "tset-actions" }, check, save));
    return node;
  }

  async function load() {
    try {
      const d = await api("/api/tools/settings");
      list.replaceChildren(...(d.tools.length ? d.tools.map(block) : [el("div", { class: "muted pad" }, MP.t("No tool needs anything set up."))]));
    } catch (e) { list.replaceChildren(el("div", { class: "muted pad" }, e.message)); }
  }
  MP.whenShown(list, load);
})();

// Server & updates → Move this server: copy everything into a folder another server takes in (mister_plis/transfer.py).
(function () {
  const { $, el, api } = MP;
  const btn = $("#transfer-btn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const dir = $("#transfer-dir").value.trim();
    if (!dir) { MP.toast(MP.t("Give the full path of the folder to copy the server into, e.g. a USB disk or the NAS.")); return; }
    const log = $("#transfer-log");
    log.hidden = false;
    btn.disabled = true;
    log.replaceChildren(el("div", { class: "step-head" }, el("span", { class: "spinner", style: "width:14px;height:14px" }), MP.t("Copying and checking every file…")));
    try {
      const r = await api("/api/transfer/export", { json: { dir } });
      log.replaceChildren(el("div", { class: "step-head ok" }, MP.icon("check", 16),
        MP.t("Copied and checked: {n} files, {size}", { n: r.files, size: MP.bytes(r.bytes) })), el("pre", {}, r.path));
    } catch (err) {
      log.replaceChildren(el("div", { class: "step-head bad" }, MP.icon("alert", 16), err.message));
    }
    btn.disabled = false;
  });
})();

// Settings → People → Accounts (mister_plis/accounts.py): the first account (which turns sign-in on), then everyone's,
// with the activity log; Settings → You → Your password, sign out.
(function () {
  const { $, el, api } = MP;
  const form = (f) => Object.fromEntries(new FormData(f).entries());

  const first = $("#first-account");
  if (first) first.addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = form(first);
    if (d.password !== d.repeat) { MP.toast(MP.t("The two passwords differ."), 5000); return; }
    try { await api("/api/accounts/first", { json: d }); location.reload(); } catch (err) { MP.toast(err.message, 6000); }
  });

  const list = $("#account-list");
  if (list) {
    const when = (t) => t ? MP.datetime(t) : MP.t("never");
    const shown = $("#account-new");
    const showPassword = (name, password) => {
      shown.hidden = false;
      shown.replaceChildren(
        el("div", { class: "step-head ok" }, MP.icon("check", 16), MP.t("Give {name} this temporary password (shown only now); they choose their own when they sign in:", { name })),
        el("pre", {}, password),
        el("div", {}, el("button", { type: "button", class: "btn btn-small", onclick: async () => { await MP.copy(password); MP.toast(MP.t("Copied")); } }, MP.t("Copy"))));
    };
    const act = async (fn) => { try { render(await fn()); } catch (err) { MP.toast(err.message, 6000); } };
    function render(d) {
      const moved = (r) => { const n = Object.values(r.moved || {}).reduce((x, y) => x + (Number(y) || 0), 0); if (n) MP.toast(MP.tn(n, "{n} record moved with it", "{n} records moved with it")); return r; };
      list.replaceChildren(...d.accounts.map((a) => el("li", { class: "cred-row account-row" },
        el("span", {}, el("b", {}, a.name), a.names.length ? el("span", { class: "muted small" }, " · " + MP.t("also: {names}", { names: a.names.join(", ") })) : null),
        el("span", { class: "panel-tag" + (a.role === "admin" ? " panel-tag-lab" : "") }, a.role === "admin" ? MP.t("Admin") : MP.t("Member")),
        el("span", { class: "muted" }, a.must_change ? MP.t("hasn't chosen a password yet") : MP.t("signed in {when}", { when: when(a.last_sign_in) })),
        el("button", { type: "button", class: "btn btn-small", onclick: async () => {
          const nw = await MP.ask(MP.t("New name (everything under the old one moves with it):"), a.name, { maxlength: 60 });
          if (nw && nw.trim() && nw.trim() !== a.name) act(async () => moved(await api("/api/accounts/rename", { json: { name: a.name, new: nw } })));
        } }, MP.t("Rename")),
        d.people.length ? el("button", { type: "button", class: "btn btn-small", title: MP.t("A name this person used before there were accounts: what is under it becomes theirs"), onclick: async () => {
          const earlier = await MP.ask(MP.t("Their earlier name, as on the People list ({names}):", { names: d.people.slice(0, 8).join(", ") + (d.people.length > 8 ? "…" : "") }), "", { maxlength: 60 });
          if (earlier && earlier.trim()) act(async () => moved(await api("/api/accounts/attach", { json: { name: a.name, earlier } })));
        } }, MP.t("Attach a name")) : null,
        el("button", { type: "button", class: "btn btn-small", onclick: () => act(() => api("/api/accounts/role", { json: { name: a.name, role: a.role === "admin" ? "member" : "admin" } })) },
          a.role === "admin" ? MP.t("Make member") : MP.t("Make admin")),
        el("button", { type: "button", class: "btn btn-small", onclick: () => act(async () => { const r = await api("/api/accounts/reset", { json: { name: a.name } }); showPassword(a.name, r.password); return r; }) }, MP.t("New password")),
        a.name === d.me ? null : el("button", { type: "button", class: "btn btn-small", onclick: async () => {
          if (!confirm(MP.t("Remove {name}'s account? They can't sign in any more; their results stay.", { name: a.name }))) return;
          act(() => api("/api/accounts", { method: "DELETE", json: { name: a.name } }));
        } }, MP.t("Remove")))));
      $("#account-people").replaceChildren(...d.people.map((n) => el("option", { value: n })));
    }
    const add = $("#account-add");
    add.addEventListener("submit", async (e) => {
      e.preventDefault();
      const d = form(add);
      act(async () => { const r = await api("/api/accounts", { json: d }); add.reset(); showPassword(d.name.trim(), r.password); return r; });
    });
    MP.whenShown(list, () => act(() => api("/api/accounts")));
    const activity = $("#activity");
    activity.addEventListener("toggle", async () => {
      if (!activity.open) return;
      try {
        const d = await api("/api/activity");
        $("#activity-list").replaceChildren(...(d.entries.length ? d.entries.map((x) => el("li", {},
          el("span", { class: "muted" }, MP.datetime(x.at)), " ", el("b", {}, x.who || "—"), " ", x.what, x.from ? el("span", { class: "muted" }, ` · ${x.from}`) : null))
          : [el("li", { class: "muted" }, MP.t("Nothing yet."))]));
      } catch (err) { MP.toast(err.message, 5000); }
    });
  }

  const pw = $("#password-form");
  if (pw) pw.addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = form(pw);
    if (d.new !== d.repeat) { MP.toast(MP.t("The two passwords differ."), 5000); return; }
    try { await api("/api/account/password", { json: { old: d.old, new: d.new } }); pw.reset(); MP.toast(MP.t("Saved")); }
    catch (err) { MP.toast(err.message, 6000); }
  });
  const out = async (everywhere) => {
    try { await api("/api/logout", { json: { everywhere } }); location.href = "/login"; } catch (err) { MP.toast(err.message, 5000); }
  };
  $("#sign-out")?.addEventListener("click", () => out(false));
  $("#sign-out-all")?.addEventListener("click", () => out(true));
})();
