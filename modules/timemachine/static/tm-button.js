// Time Machine on the base's pages: "Add to Time Machine" above every finished result (MP.hooks.resultActions),
// and the galaxy mark on kept jobs in the job list (MP.hooks.jobMarks). Loaded on every page by the module.
(function () {
  const MP = window.MP;
  MP.hooks = MP.hooks || { resultActions: [], jobMarks: [] };

  MP.addToTM = async function (job, task = null) {
    const d = await MP.api(`/api/jobs/${job.id}/timemachine`, { json: task ? { task: task.id } : {} });
    job.in_tm = true;
    MP.toast(task ? MP.t("Added to Time Machine for the task “{title}”", { title: task.title })
      : d.already ? MP.t("Already in Time Machine") : d.entry && d.entry.version_of ? MP.t("Added to Time Machine as a new version") : MP.t("Copied to Time Machine"), 2600);
    document.dispatchEvent(new CustomEvent("mp:tm", { detail: job.id }));
    return d;
  };

  // "Add to Time Machine" above a finished result; once it's there, a link to its copy.
  MP.tmButton = function (job) {
    if (job.status !== "done") return null;
    const draw = (btn) => {
      const inTm = !!job.in_tm;
      btn.className = `btn btn-small tm-btn${inTm ? " is-in" : ""}`;
      const asVersion = !inTm && job.tm_root;  // a re-run of something kept: it becomes that result's next version
      btn.title = inTm ? MP.t("In Time Machine — open its copy")
        : asVersion ? MP.t("This is a re-run of a result kept in Time Machine — add it there as its next version")
        : MP.t("Add to Time Machine — keep this result for good, as the basis of a study");
      btn.replaceChildren(MP.icon("galaxy", 14), MP.el("span", {}, inTm ? MP.t("In Time Machine") : asVersion ? MP.t("Add as a new version") : MP.t("Add to Time Machine")));
    };
    const btn = MP.el("button", { type: "button", onclick: async (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (job.in_tm) { location.href = `/timemachine/${job.id}`; return; }
      const add = async (task) => {
        btn.disabled = true;
        try { await MP.addToTM(job, task); btn.classList.add("tm-pop"); } catch (err) { MP.toast(err.message, 4000); }
        btn.disabled = false;
        draw(btn);
      };
      // open tasks this result could be for: ask which (or none). A re-run joins its result as before.
      let tasks = [];
      if (!job.tm_root) {
        btn.disabled = true;
        try { tasks = (await MP.api("/api/tm/tasks")).tasks; } catch (_) { }
        btn.disabled = false;
      }
      if (!tasks.length) { add(null); return; }
      const me = MP.fold(MP.prefs.name || "");
      const mine = (t) => !!me && MP.fold(t.assignee) === me;
      tasks.sort((a, b) => mine(b) - mine(a));  // mine first
      MP.$$(".tm-menu").forEach((m) => m.remove());
      const menu = MP.el("div", { class: "tm-menu tm-task-menu", role: "menu" },
        MP.el("button", { type: "button", role: "menuitem", onclick: () => { menu.remove(); add(null); } }, MP.icon("galaxy", 14), MP.t("Keep it on its own")),
        MP.el("div", { class: "tm-menu-label" }, MP.t("…or as what a task asked for:")),
        ...tasks.map((t) => MP.el("button", { type: "button", role: "menuitem", onclick: () => { menu.remove(); add(t); } }, MP.icon("clock", 14),
          MP.el("span", {}, t.title, t.assignee ? MP.el("span", { class: "tm-menu-who" }, ` · ${t.assignee}`) : null))));
      document.body.append(menu);
      const r = btn.getBoundingClientRect();
      menu.style.left = `${Math.max(12, Math.min(innerWidth - menu.offsetWidth - 12, r.left))}px`;
      menu.style.top = `${r.bottom + 6}px`;
      setTimeout(() => document.addEventListener("click", function close(ev) {
        if (!menu.contains(ev.target)) { menu.remove(); document.removeEventListener("click", close); }
      }), 0);
    } });
    draw(btn);
    return btn;
  };


  MP.hooks.resultActions.push((job) => MP.tmButton(job));
  MP.hooks.jobMarks.push((job) => job.in_tm ? MP.el("span", { class: "jtm-mark", title: MP.t("In Time Machine") }, MP.icon("galaxy", 13)) : null);
})();
