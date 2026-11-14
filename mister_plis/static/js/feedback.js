// Feedback bubble: the glowing button in the middle of the top bar opens it; a bug (red), an inconvenience (orange)
// or a feature idea (green) is sent with the page it came from. The list is on the Feedback page (/feedback).
(function () {
  const { $, api } = MP;
  const btn = $("#fb-btn"), pop = $("#fb-pop"), form = $("#fb-form"), text = $("#fb-text"), send = $("#fb-send");
  if (!btn || !pop || !form) return;
  const DRAFT = "mp:feedback-draft";

  // Where it was sent from, in words people recognise ("Tools / Calculators / Molar solution").
  function where() {
    const crumbs = $(".crumbs");
    return (crumbs ? crumbs.textContent : document.title).replace(/\s+/g, " ").trim();
  }

  function place() {
    const r = btn.getBoundingClientRect();
    const w = Math.min(420, window.innerWidth - 24);
    const left = Math.max(12, Math.min(window.innerWidth - w - 12, r.left + r.width / 2 - w / 2));
    pop.style.width = `${w}px`;
    pop.style.left = `${left}px`;
    pop.style.top = `${r.bottom + 12}px`;
    pop.style.setProperty("--fb-tip", `${r.left + r.width / 2 - left}px`);
  }

  function who() {
    const name = MP.prefs.name;
    $("#fb-who").replaceChildren(name
      ? MP.t("Sent as {name}", { name })
      : MP.el("span", {}, MP.t("Sent without a name"), " · ", MP.el("a", { class: "link", href: "/settings#you" }, MP.t("add yours"))));
  }

  function open() {
    if (!pop.hidden) return;
    place();
    who();
    try { const d = JSON.parse(localStorage.getItem(DRAFT) || "null"); if (d && !text.value) { text.value = d.text || ""; const r = form.querySelector(`input[value="${d.kind}"]`); if (r) r.checked = true; } } catch (_) { }
    pop.classList.remove("is-sent");
    pop.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    btn.classList.add("on");
    requestAnimationFrame(() => pop.classList.add("is-open"));
    setTimeout(() => text.focus(), 60);
  }

  function close() {
    if (pop.hidden) return;
    pop.classList.remove("is-open");
    btn.setAttribute("aria-expanded", "false");
    btn.classList.remove("on");
    setTimeout(() => { if (!pop.classList.contains("is-open")) pop.hidden = true; }, 180);
  }

  function saveDraft() {
    const kind = (form.querySelector("input[name=kind]:checked") || {}).value;
    try { localStorage.setItem(DRAFT, JSON.stringify({ kind, text: text.value })); } catch (_) { }
  }

  btn.addEventListener("click", () => (pop.hidden ? open() : close()));
  $("#fb-close").addEventListener("click", close);
  form.addEventListener("input", saveDraft);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) { close(); btn.focus(); } });
  document.addEventListener("pointerdown", (e) => { if (!pop.hidden && !pop.contains(e.target) && !btn.contains(e.target)) close(); });
  window.addEventListener("resize", () => { if (!pop.hidden) place(); });
  text.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); form.requestSubmit(); } });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const kind = (form.querySelector("input[name=kind]:checked") || {}).value;
    if (!text.value.trim()) { text.focus(); MP.toast(MP.t("Write a few words first.")); return; }
    send.disabled = true;
    try {
      await api("/api/feedback", { json: { kind, text: text.value, page: location.pathname + location.search, where: where() } });
      text.value = "";
      try { localStorage.removeItem(DRAFT); } catch (_) { }
      const count = $("#feedback-count");
      if (count) { count.hidden = false; count.textContent = String((parseInt(count.textContent, 10) || 0) + 1); }
      pop.classList.add("is-sent");
      setTimeout(close, 1500);
      document.dispatchEvent(new CustomEvent("mp:feedback"));
    } catch (err) { MP.toast(err.message, 5000); }
    send.disabled = false;
  });
})();

// The Feedback page (/feedback): everything sent with the bubble — a to-do list of bugs, inconveniences and ideas.
(function () {
  const { $, el, icon, api } = MP;
  const box = $("#fb-list");
  if (!box) return;
  let items = [], kinds = {}, filter = "all", showDone = false;

  function counts() {
    const open = items.filter((i) => i.status !== "done");
    $("#fb-sum").textContent = open.length ? MP.tn(open.length, "{n} open", "{n} open") : MP.t("nothing open");
    MP.$$("#fb-filter button").forEach((b) => {
      const k = b.dataset.kind, n = open.filter((i) => k === "all" || i.kind === k).length;
      b.querySelector(".n").textContent = n ? ` ${n}` : "";
    });
    const side = $("#feedback-count");
    if (side) { side.hidden = !open.length; side.textContent = String(open.length); }
  }

  function render() {
    counts();
    const shown = items.filter((i) => (filter === "all" || i.kind === filter) && (showDone || i.status !== "done"));
    if (!shown.length) {
      box.replaceChildren(el("div", { class: "fb-empty" }, items.length ? MP.t("Nothing here with these filters.")
        : MP.t("No feedback yet. The glowing button at the top of every page sends some.")));
      return;
    }
    box.replaceChildren(...shown.map((it) => {
      const done = it.status === "done";
      return el("div", { class: `fb-item fb-kind-${it.kind}` + (done ? " is-done" : "") },
        el("span", { class: "fb-dot", title: kinds[it.kind] || it.kind }),
        el("div", {},
          el("div", { class: "fb-item-text" }, it.text),
          el("div", { class: "fb-item-meta" }, [
            kinds[it.kind] || it.kind,
            it.user || MP.t("no name"),
            MP.datetime(it.created),
          ].join(" · "), it.page ? [" · ", el("a", { href: it.page, title: it.page }, it.where || it.page)] : null,
          done && it.done_at ? " · " + MP.t("done {when}", { when: MP.date(it.done_at) }) : null)),
        el("div", { class: "fb-item-actions" },
          el("button", { type: "button", class: "icon-btn icon-btn-sm" + (done ? " on" : ""), title: done ? MP.t("Mark as not done") : MP.t("Mark as done"),
            onclick: () => setStatus(it, done ? "new" : "done") }, icon("check", 16)),
          el("button", { type: "button", class: "icon-btn icon-btn-sm", title: MP.t("Delete"), onclick: () => remove(it) }, icon("x", 16))));
    }));
  }

  async function load() {
    try { const d = await api("/api/feedback"); items = d.items; kinds = d.kinds; render(); }
    catch (e) { box.replaceChildren(el("div", { class: "fb-empty" }, e.message)); }
  }

  async function setStatus(it, status) {
    try { Object.assign(it, await api(`/api/feedback/${it.id}`, { json: { status } })); render(); }
    catch (e) { MP.toast(e.message); load(); }
  }

  async function remove(it) {
    if (!confirm(MP.t("Delete this feedback for everyone?"))) return;
    try { await api(`/api/feedback/${it.id}`, { method: "DELETE" }); items = items.filter((x) => x !== it); render(); }
    catch (e) { MP.toast(e.message); load(); }
  }

  // The open items as a Markdown list — to paste into an issue, an e-mail or a chat with whoever implements them.
  $("#fb-copy").addEventListener("click", async () => {
    const open = items.filter((i) => i.status !== "done" && (filter === "all" || i.kind === filter));
    if (!open.length) { MP.toast(MP.t("Nothing open to copy")); return; }
    const md = Object.keys(kinds).map((k) => {
      const list = open.filter((i) => i.kind === k);
      return list.length ? `## ${kinds[k]}\n\n` + list.map((i) => `- ${i.text.replace(/\s*\n\s*/g, " ")} — ${i.user || MP.t("no name")}, ${MP.date(i.created)}${i.where ? `, ${i.where}` : ""}`).join("\n") : "";
    }).filter(Boolean).join("\n\n");
    MP.toast(await MP.copy(md) ? MP.tn(open.length, "Copied {n} item", "Copied {n} items") : MP.t("Could not copy"));
  });

  MP.$$("#fb-filter button").forEach((b) => b.addEventListener("click", () => {
    filter = b.dataset.kind;
    MP.$$("#fb-filter button").forEach((x) => { x.classList.toggle("active", x === b); x.setAttribute("aria-checked", x === b ? "true" : "false"); });
    render();
  }));
  $("#fb-show-done").addEventListener("change", (e) => { showDone = e.target.checked; render(); });
  document.addEventListener("mp:feedback", load);
  load();
})();
