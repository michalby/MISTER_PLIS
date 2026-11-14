// Lab notebook: check / sync the Obsidian notes, choose the shown folders.
(function () {
  const { $, el, icon, api } = MP;
  if (!$("#notes-sync-panel")) return;
  let st = null, chosen = new Set();

  const kv = (dl, rows) => dl.replaceChildren(...rows.filter(Boolean).flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
  const badge = (text, cls) => { const b = $("#notes-badge"); b.textContent = text; b.className = "badge " + (cls || ""); };

  // the repository: changed here (the old copy is kept on the server), unless config.toml sets it on this computer
  function repoForm() {
    const repoIn = el("input", { type: "text", value: st.repo || "", placeholder: "https://github.com/your-lab/notes.git", "aria-label": MP.t("Repository") });
    const branchIn = el("input", { type: "text", value: st.branch || "main", placeholder: "main", "aria-label": MP.t("Branch") });
    const form = el("form", { class: "notes-repo-form" },
      el("label", {}, el("span", {}, MP.t("Repository")), repoIn),
      el("label", {}, el("span", {}, MP.t("Branch")), branchIn),
      el("small", { class: "muted" }, MP.t("A GitHub address, or a folder on this computer with git in it; empty turns the notebook off. The current copy is kept on the server, set aside, and the new notebook is downloaded at the next sync.")),
      el("div", { class: "sync-actions" },
        el("button", { class: "btn btn-primary", type: "submit" }, MP.t("Use this repository")),
        el("button", { class: "btn", type: "button", onclick: () => form.remove() }, MP.t("Cancel"))));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const r = await api("/api/notes/repository", { json: { repo: repoIn.value.trim(), branch: branchIn.value.trim() } });
        MP.toast(r.kept ? MP.t("Saved. The old copy is kept as {path}", { path: r.kept }) : MP.t("Saved"), r.kept ? 8000 : 3000);
        form.remove(); log([]); load();
      } catch (err) { MP.toast(err.message, 6000); }
    });
    return form;
  }

  function render() {
    const change = st.locked ? el("small", { class: "muted" }, " ", MP.t("(set in config.toml on this computer)"))
      : el("button", { class: "btn btn-small", type: "button", onclick: () => {
        const open = $("#notes-sync-panel .notes-repo-form");
        if (open) open.remove(); else $("#notes-info").after(repoForm());
      } }, MP.t("Change…"));
    kv($("#notes-info"), [
      [MP.t("Repository"), st.enabled ? el("span", {}, st.repo, " · ", el("code", {}, st.branch), " ", change)
        : el("span", {}, el("span", { class: "muted" }, MP.t("none: the notebook is off")), " ", change)],
      [MP.t("Shown version"), st.head ? el("span", {}, el("code", {}, st.head.short), ` · ${MP.date(st.head.date)} · ${st.head.subject}`) : MP.t("not downloaded yet")],
      [MP.t("Last synced"), st.synced_at ? MP.datetime(st.synced_at) : MP.t("never")],
      [MP.t("Last checked"), st.last_fetch ? MP.ago(st.last_fetch) : MP.t("never")],
      [MP.t("Shown"), `${MP.tn(st.notes, "{n} note", "{n} notes")}, ${MP.tn(st.files, "{n} picture/file", "{n} pictures/files")}`],
      st.folder ? [MP.t("Folder on this computer"), el("code", {}, st.folder)]
        : [MP.t("GitHub access"), MP.t("the same token as the code (on the Mac: the Keychain)")],
      st.last_error ? [MP.t("Problem"), el("span", { class: "status-failed" }, st.last_error.split("\n")[0])] : null,
    ]);
    $("#notes-check-btn").disabled = $("#notes-sync-btn").disabled = !st.enabled;
    if (!st.enabled) badge(MP.t("off"), "");
    else if (!st.cloned) badge(MP.t("not downloaded"), "warn");
    else if (st.behind) badge(st.folder ? MP.tn(st.behind, "{n} update in the folder", "{n} updates in the folder")
      : MP.tn(st.behind, "{n} update on GitHub", "{n} updates on GitHub"), "new");
    else badge(MP.t("up to date"), "ok");
    renderFolders();
  }

  function covered(path) { return [...chosen].some((c) => path.startsWith(c + "/")); }

  function renderFolders() {
    const box = $("#notes-folders");
    if (!st.available.length) {
      box.replaceChildren(el("p", { class: "folder-empty" },
        st.cloned ? MP.t("The notebook has no folders with notes.")
          : st.folders.length ? MP.t("Press Sync notes once to see the notebook's folders. It starts with {folders}.", { folders: st.folders.join(MP.t(" and ")) })
            : MP.t("Press Sync notes once to see the notebook's folders, then tick the ones to show.")));
      $("#notes-folder-sum").textContent = "";
      return;
    }
    box.replaceChildren(...st.available.map((f) => {
      const on = chosen.has(f.path) || covered(f.path);
      const input = el("input", { type: "checkbox", checked: on, disabled: covered(f.path) });
      input.addEventListener("change", () => {
        if (input.checked) chosen.add(f.path); else chosen.delete(f.path);
        [...chosen].forEach((c) => { if (c.startsWith(f.path + "/")) chosen.delete(c); });
        renderFolders();
        $("#notes-save-btn").disabled = same(chosen, new Set(st.folders));
      });
      return el("label", { class: "folder-row" + (covered(f.path) ? " is-covered" : ""), style: `padding-left:${8 + f.depth * 22}px`, title: f.path },
        input, el("span", { class: "name" }, f.path.split("/").pop()), el("span", { class: "count" }, MP.tn(f.notes, "{n} note", "{n} notes")));
    }));
    const n = st.available.filter((f) => chosen.has(f.path)).reduce((a, f) => a + f.notes, 0);
    $("#notes-folder-sum").textContent = `${MP.tn(chosen.size, "{n} folder", "{n} folders")} · ${MP.tn(n, "{n} note", "{n} notes")}`;
  }

  const same = (a, b) => a.size === b.size && [...a].every((x) => b.has(x));

  function log(steps, reset = true) {
    const box = $("#notes-log");
    if (reset) box.replaceChildren();
    box.hidden = !steps.length;
    steps.forEach((s) => box.append(el("div", { class: "step" },
      el("div", { class: "step-head " + (s.ok ? "ok" : "bad") }, icon(s.ok ? "check" : "alert", 16), MP.t(s.name)),
      s.output && !s.ok ? el("pre", {}, s.output) : null)));
  }

  function busy(btn, on, label, idle) {
    btn.disabled = on;
    btn.replaceChildren(...(on ? [el("span", { class: "spinner" }), el("span", {}, label)] : idle()));
  }

  async function load() {
    try {
      st = await api("/api/notes/status");
      $("#notes-auto").value = String(st.auto_minutes || 0);
      chosen = new Set(st.folders);
      $("#notes-save-btn").disabled = true;
      render();
    } catch (e) { MP.toast(e.message); }
  }

  $("#notes-check-btn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    busy(btn, true, MP.t("Checking…"));
    try {
      const d = await api("/api/notes/check", { method: "POST" });
      st = d; chosen = new Set(st.folders); render();
      const inc = $("#notes-incoming");
      if (!d.fetch_ok) {
        badge(MP.t("couldn't check"), "warn");  // the count is from the last good check
        log([{ name: d.folder ? MP.t("Couldn't read the notebook's folder") : MP.t("Couldn't reach the notebook on GitHub"), ok: false, output: d.fetch_output }]);
      }
      else {
        log([]);
        inc.replaceChildren(d.incoming.length ? el("div", { class: "incoming" },
          el("div", { class: "incoming-head" }, MP.t("Changes to the shown folders ({n})", { n: d.incoming.length })),
          ...d.incoming.map((c) => el("div", { class: "commit" }, el("code", {}, c.short), el("span", {}, c.subject),
            el("span", { class: "who" }, `${c.author} · ${MP.ago(Date.parse(c.date) / 1000)}`)))) : "");
        if (!d.incoming.length) MP.toast(d.behind ? MP.t("Only other folders changed") : MP.t("Already up to date"));
      }
    } catch (err) { MP.toast(err.message); }
    busy(btn, false, "", () => [icon("search", 16), el("span", {}, MP.t("Check for updates"))]);
  });

  async function run(btn, url, body, idle) {
    busy(btn, true, MP.t("Syncing…"));
    try {
      const d = await api(url, body ? { json: body } : { method: "POST" });
      log(d.steps || []);
      $("#notes-incoming").replaceChildren();
      if (d.ok) MP.toast(MP.t("Notes are up to date for everyone"));
    } catch (err) {
      if (err.data && err.data.steps) log(err.data.steps); else MP.toast(err.message, 6000);
    }
    busy(btn, false, "", idle);
    load();
  }

  $("#notes-auto").addEventListener("change", async (e) => {
    try { await api("/api/notes/settings", { json: { auto_minutes: +e.currentTarget.value } }); MP.toast(MP.t("Saved")); }
    catch (err) { MP.toast(err.message, 5000); load(); }
  });
  $("#notes-sync-btn").addEventListener("click", (e) => run(e.currentTarget, "/api/notes/sync", null,
    () => [icon("sync", 16), el("span", {}, MP.t("Sync notes"))]));
  $("#notes-save-btn").addEventListener("click", (e) => {
    if (!chosen.size && !confirm(MP.t("No folder is ticked — the lab notebook will be empty. Continue?"))) return;
    run(e.currentTarget, "/api/notes/folders", { folders: [...chosen] }, () => [el("span", {}, MP.t("Save and sync"))]);
  });

  MP.whenShown($("#notes-sync-panel"), load);  // when its Settings tab is first opened
})();
