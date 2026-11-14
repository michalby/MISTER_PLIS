// Shared helpers + sidebar behaviour + "new version" banner. Loaded on every page.
(function () {
  const MP = window.MP;

  // ---- language: English in the code, the catalogue (/i18n/<lang>.js → MP.i18n) for the rest -------------
  const fill = (text, vars) => (vars ? text.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : text);
  // MP.t("Saved"), MP.t("Deleted {name}", {name}) — the English text is the key.
  MP.t = function (text, vars) {
    const hit = MP.i18n && Object.prototype.hasOwnProperty.call(MP.i18n, text) ? MP.i18n[text] : null;
    return fill(hit ?? text, vars);
  };
  // Polish has three plural forms: MP.tn(5, "{n} file", "{n} files") → "5 plików".
  MP.pluralForm = function (n) {
    if (MP.prefs.lang !== "pl") return n === 1 ? 0 : 1;
    if (n !== Math.floor(n)) return 1;
    n = Math.abs(n);
    if (n === 1) return 0;
    return [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? 1 : 2;
  };
  MP.tn = function (n, one, other, vars) {
    const hit = MP.i18n && MP.i18n[`${one}|${other}`];
    const forms = hit ? hit.split("|") : [one, other];
    return fill(forms[Math.min(MP.pluralForm(n), forms.length - 1)], { n, ...(vars || {}) });
  };

  // Text for searching: "stezenie" finds "stężenie", case doesn't matter.
  MP.fold = (s) => String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ł/g, "l").replace(/Ł/g, "L").toLowerCase();

  MP.$ = (sel, root = document) => root.querySelector(sel);
  MP.$$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // A link or picture address that would run something when clicked ("javascript:…"): an address someone typed or a
  // catalogue gave (feedback's page, an inventory link…) is never trusted to be safe (docs/SECURITY_AUDIT.md M2).
  const SAFE_SCHEMES = ["http:", "https:", "mailto:", "blob:"];
  MP.safeUrl = function (v, attr = "href") {
    let u;
    try { u = new URL(String(v), location.href); } catch (_) { return false; }
    return SAFE_SCHEMES.includes(u.protocol) || (attr === "src" && u.protocol === "data:" && /^data:image\/(png|jpe?g|gif|webp);/i.test(u.href));
  };

  MP.el = function (tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if ((k === "href" || k === "src" || k === "action" || k === "formaction") && v !== true && !MP.safeUrl(v, k)) continue;
      if (k === "class") node.className = v;
      else if (k === "html") node.innerHTML = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (k === "dataset") Object.assign(node.dataset, v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  };

  MP.icon = function (name, size = 16) {
    const span = document.createElement("span");
    span.innerHTML = `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${MP.icons[name] || ""}</svg>`;
    return span.firstChild;
  };

  MP.api = async function (url, opts = {}) {
    const init = { ...opts, headers: { ...(opts.headers || {}) } };
    if (opts.json !== undefined) {
      init.method = init.method || "POST";
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.json);
    }
    const res = await fetch(url, init);
    let data = null;
    try { data = await res.json(); } catch (_) { /* not json */ }
    if (!res.ok) {
      const err = new Error((data && (data.detail || data.error)) || `${res.status} ${res.statusText}`);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  };

  MP.bytes = function (n) {
    if (n == null) return "";
    const u = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${i === 0 ? n : n.toFixed(n < 10 ? 1 : 0)} ${u[i]}`;
  };

  // Dates are always yyyy-mm-dd (and 24-hour time).
  const pad = (n) => String(n).padStart(2, "0");
  MP.date = function (d) {
    d = d instanceof Date ? d : new Date(typeof d === "number" ? d * 1000 : d);
    return isNaN(d) ? "" : `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  };
  MP.datetime = function (d) {
    d = d instanceof Date ? d : new Date(typeof d === "number" ? d * 1000 : d);
    return isNaN(d) ? "" : `${MP.date(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  MP.ago = function (ts) {
    if (!ts) return "";
    const s = Date.now() / 1000 - ts;
    if (s < 45) return MP.t("just now");
    if (s < 3600) return MP.t("{n} min ago", { n: Math.round(s / 60) });
    if (s < 86400) return MP.t("{n} h ago", { n: Math.round(s / 3600) });
    if (s < 86400 * 1.5) return MP.t("a day ago");
    if (s < 86400 * 7) return MP.t("{n} d ago", { n: Math.round(s / 86400) });
    return MP.date(ts);
  };

  // Numbers on screen use the decimal separator from Settings.
  MP.num = function (v) {
    if (typeof v !== "number") return v;
    const s = String(v);
    return MP.prefs.decimal === "comma" ? s.replace(".", ",") : s;
  };

  MP.duration = function (s) {
    if (s == null) return "";
    if (s < 1) return `${Math.round(s * 1000)} ms`;
    if (s < 60) return `${MP.num(+s.toFixed(1))} s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m} min ${Math.round(s % 60)} s`;
    return `${Math.floor(m / 60)} h ${m % 60} min`;
  };

  MP.toast = function (text, ms = 2200) {
    const t = MP.el("div", { class: "toast", text });
    document.body.append(t);
    setTimeout(() => t.remove(), ms);
  };

  // Stored files from an origin of their own (mister_plis/fileorigin.py): once a session, check this page can reach it
  // (a firewall may close its port; a page on HTTPS can't use plain HTTP). Until then, and if not, the app's own links.
  MP.filesOk = null;
  if (MP.filesOrigin) {
    const key = "mp:files-ok:" + MP.filesOrigin;
    let cached = null;
    try { cached = sessionStorage.getItem(key); } catch (_) { /* no storage: check every page */ }
    if (cached !== null) MP.filesOk = cached === "1";
    else {
      const done = (ok) => {
        if (MP.filesOk !== null) return;
        MP.filesOk = ok;
        try { sessionStorage.setItem(key, ok ? "1" : "0"); } catch (_) { /* fine */ }
      };
      const img = new Image();
      const timer = setTimeout(() => done(false), 3000);
      img.onload = () => { clearTimeout(timer); done(true); };
      img.onerror = () => { clearTimeout(timer); done(false); };
      img.src = `${MP.filesOrigin}/ping.gif?${Date.now()}`;
    }
  }
  const FILE_URL = /^\/api\/[^/]+\/[^/]+\/files\/(.+)$/;
  // A job (or a kept result) whose files_base the server gave: its file links point there, if this page reaches it.
  MP.filesFrom = function (d) {
    if (!d || !d.files_base || MP.filesOk !== true) return d;
    const move = (u) => { const m = typeof u === "string" && u.match(FILE_URL); return m ? d.files_base + m[1] : u; };
    for (const o of d.outputs || []) {
      if (o.url) o.url = move(o.url);
      if (o.download && o.download.url) o.download.url = move(o.download.url);
    }
    for (const f of d.files_kept || []) if (f.url) f.url = move(f.url);
    return d;
  };

  MP.copy = async function (text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (_) {
      const ta = MP.el("textarea", {}, text);
      document.body.append(ta); ta.select();
      const ok = document.execCommand("copy"); ta.remove(); return ok;
    }
  };

  // ---- sidebar search -----------------------------------------------------
  const search = MP.$("#tool-search");
  if (search) {
    const apply = () => {
      const q = search.value.trim().toLowerCase();
      const words = q.split(/\s+/).filter(Boolean);
      const match = (el) => words.every((w) => el.dataset.search.includes(w));
      MP.$$(".tool-link").forEach((a) => { a.hidden = !match(a); });
      MP.$$(".side-group").forEach((g) => { g.hidden = !MP.$$(".tool-link", g).some((a) => !a.hidden); });
      // On the home page also filter the cards.
      let any = false;
      MP.$$(".cat-section").forEach((sec) => {
        let shown = 0;
        MP.$$(".tool-card", sec).forEach((c) => { c.hidden = !match(c); if (!c.hidden) shown++; });
        sec.hidden = shown === 0;
        any = any || shown > 0;
      });
      const empty = MP.$("#empty-search");
      if (empty) empty.hidden = any;
    };
    search.addEventListener("input", apply);
    search.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const first = MP.$$(".tool-link").find((a) => !a.hidden);
        if (first) location.href = first.href;
      }
      if (e.key === "Escape") { search.value = ""; apply(); search.blur(); }
    });
    document.addEventListener("keydown", (e) => {
      const t = e.target;
      if (e.key === "/" && !(t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement)) {
        e.preventDefault();
        document.body.classList.add("nav-open");
        search.focus();
      }
    });
  }

  // "Chlorophyll concentration — WT vs mutant, day 3": the tool's name and a title anyone can set or change.
  // save(title) stores it and returns the stored title.
  MP.titleEditor = function (name, title, save) {
    const box = MP.el("div", { class: "job-title" });
    const put = (...nodes) => box.replaceChildren(...nodes.filter(Boolean));  // replaceChildren would print "null"
    const show = () => {
      put(
        name ? MP.el("span", { class: "job-title-tool" }, name) : null,
        name && title ? MP.el("span", { class: "job-title-dash" }, " — ") : null,
        title ? MP.el("span", { class: "job-title-text" }, title) : null,
        MP.el("button", { type: "button", class: "link-btn job-title-btn", onclick: edit }, MP.icon("tag", 13), title ? MP.t("Change title") : MP.t("Add a title")));
    };
    const edit = () => {
      const input = MP.el("input", { type: "text", maxlength: 120, value: title || "", placeholder: MP.t("e.g. WT vs mutant, day 3"), "aria-label": MP.t("Title") });
      const done = async (keep) => {
        if (keep) {
          try { title = await save(input.value.trim()); MP.toast(MP.t("Saved")); } catch (err) { MP.toast(err.message, 4000); }
        }
        show();
      };
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); done(true); } if (e.key === "Escape") done(false); });
      put(name ? MP.el("span", { class: "job-title-tool" }, name) : null, name ? MP.el("span", { class: "job-title-dash" }, " — ") : null,
        MP.el("div", { class: "control job-title-input" }, input),
        MP.el("button", { type: "button", class: "btn btn-small btn-primary", onclick: () => done(true) }, MP.t("Save")),
        MP.el("button", { type: "button", class: "btn btn-small", onclick: () => done(false) }, MP.t("Cancel")));
      input.focus();
      input.select();
    };
    show();
    return box;
  };

  // ---- where modules join in on the base's pages (mister_plis/modules.py) -----------------------------
  // resultActions: (job, toolSpec) → a button above a finished result, or null; jobMarks: job → a mark in its row.
  MP.hooks = MP.hooks || { resultActions: [], jobMarks: [] };

  // The job number, with the quiet galaxy mark (the job mark): the number to find a result again (also on printed PDFs).
  MP.jobNumber = function (job) {
    return MP.el("button", { type: "button", class: "job-no", title: MP.t("Job number — type it in Time Machine to find this result again. Click to copy."),
      onclick: async (e) => { e.preventDefault(); e.stopPropagation(); await MP.copy(job.id); MP.toast(MP.t("Job number copied")); } },
      MP.icon("galaxy", 13), MP.el("code", {}, job.id));
  };

  // Every print and download button in the app looks the same: a small rounded button, PDF in the accent colour
  // with the file icon (it opens to print), every other format plain with the download icon. kind: "pdf", "xlsx",
  // "csv", or any file extension (shown in capitals). Give href (a link) or onclick; label replaces the format's name.
  const FORMAT = { pdf: "PDF", xlsx: "Excel", xls: "Excel", csv: "CSV" };
  MP.exportBtn = function (kind, { href, onclick, title, label } = {}) {
    kind = String(kind || "").toLowerCase().replace(/^\./, "");
    const pdf = kind === "pdf";
    const attrs = { class: `btn btn-small export-btn${pdf ? " btn-primary" : ""}`, title, onclick };
    const body = [MP.icon(pdf ? "file" : "download", 14), label || FORMAT[kind] || kind.toUpperCase() || MP.t("Download")];
    return href ? MP.el("a", { ...attrs, href, target: pdf ? "_blank" : null, rel: pdf ? "noopener" : null }, ...body)
      : MP.el("button", { ...attrs, type: "button" }, ...body);
  };

  // The galaxies turn with SVG animations; stop them for people who asked for less motion.
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    MP.$$("svg.galaxy").forEach((svg) => { try { svg.pauseAnimations(); } catch (_) { } });
  }

  // A text box in the page, instead of the browser's prompt() popup.
  // MP.ask("Name for this layout:") → a promise of the text, or null on Cancel / Esc.
  MP.ask = async function (label, value = "", opts = {}) {
    const got = await MP.askForm({ title: opts.title, ok: opts.ok, fields: [{ label, value, placeholder: opts.placeholder, maxlength: opts.maxlength }] });
    return got ? got[0] : null;
  };
  // Several text boxes in one dialog: fields = [{ label, value, placeholder, maxlength }] → a promise of the
  // values in the same order, or null on Cancel / Esc. extra: more controls under the boxes (read them yourself).
  MP.askForm = function ({ title, fields, ok, extra }) {
    return new Promise((resolve) => {
      const inputs = fields.map((f) => MP.el("input", { type: "text", value: f.value ?? "", placeholder: f.placeholder, maxlength: f.maxlength }));
      const dlg = MP.el("dialog", { class: "dialog dialog-ask" });
      dlg.append(MP.el("form", { method: "dialog" },  // Enter in a box presses OK, the only submit button
        title ? MP.el("h3", {}, title) : null,
        fields.map((f, i) => MP.el("label", { class: "field" }, MP.el("span", { class: "field-label" }, f.label), MP.el("div", { class: "control" }, inputs[i]))),
        extra || null,
        MP.el("div", { class: "dialog-actions" },
          MP.el("button", { type: "button", class: "btn", onclick: () => dlg.close("cancel") }, MP.t("Cancel")),
          MP.el("button", { type: "submit", class: "btn btn-primary", value: "ok" }, ok || MP.t("OK")))));
      document.body.append(dlg);
      dlg.addEventListener("close", () => {
        dlg.remove();
        resolve(dlg.returnValue === "ok" ? inputs.map((x) => x.value) : null);
      });
      dlg.showModal();
      inputs[0]?.focus();
      inputs[0]?.select();
    });
  };

  // ---- settings: one cookie each, so the server can use them too (theme, number format)
  MP.setPref = function (name, value) {
    // over HTTPS, never sent over plain HTTP
    document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=63072000; samesite=lax${location.protocol === "https:" ? "; secure" : ""}`;
    if (name in MP.prefs) MP.prefs[name] = value;
    MP.$$(`.seg[data-pref="${name}"] button`).forEach((b) => {
      b.classList.toggle("active", b.dataset.value === value);
      b.setAttribute("aria-checked", b.dataset.value === value ? "true" : "false");
    });
  };

  // language switch (top right): a cookie like the other settings, then the page is drawn again in that language
  MP.$$(".lang-switch [data-lang]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.lang === MP.prefs.lang) return;
    MP.setPref("lang", b.dataset.lang);
    location.reload();
  }));

  // theme toggle (top right): flips between light and dark; Settings also offers "System"
  MP.$("#theme-btn")?.addEventListener("click", () => {
    MP.setPref("theme", document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    MP.applyTheme();
  });

  // ---- tabs inside a page (Settings): <div data-tabs> holding a [role=tablist] of a.tab[role=tab][data-tab] and
  // section.tabpanel[role=tabpanel][data-tab]. The address follows the tab (#id), so a tab can be linked and the back
  // button works. A tab's panel is announced the first time it is shown ("mp:tab-open"), so it loads its data only
  // then. A fragment naming something inside a tab (#storage, an old link) opens that tab and scrolls to it.
  // data-tab-aliases maps other old fragments to a tab, or to another address when the value starts with "/".
  // Without a fragment, data-tab-default (or the first tab) is shown.
  MP.tabs = function (root) {
    const tabs = MP.$$('[role="tab"][data-tab]', root);
    const panels = new Map(MP.$$('[role="tabpanel"][data-tab]', root).map((p) => [p.dataset.tab, p]));
    let aliases = {};
    try { aliases = JSON.parse(root.dataset.tabAliases || "{}"); } catch (_) { }
    let target = null;  // an element inside a tab to scroll to once it shows
    const fromHash = () => {
      let id = decodeURIComponent(location.hash.slice(1));
      target = null;
      if (aliases[id]) {
        if (aliases[id].startsWith("/")) { location.replace(aliases[id]); return null; }
        id = aliases[id];
        history.replaceState(null, "", "#" + id);
      }
      if (panels.has(id)) return id;
      const inside = id && document.getElementById(id)?.closest('[role="tabpanel"][data-tab]');
      if (inside && panels.get(inside.dataset.tab) === inside) { target = document.getElementById(id); return inside.dataset.tab; }
      return panels.has(root.dataset.tabDefault) ? root.dataset.tabDefault : tabs[0]?.dataset.tab;
    };
    const show = (id, focus) => {
      tabs.forEach((t) => {
        const on = t.dataset.tab === id;
        t.classList.toggle("active", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;
        if (on && focus) t.focus();
      });
      panels.forEach((p, pid) => p.classList.toggle("is-active", pid === id));
      const p = panels.get(id);
      if (p && !p.dataset.opened) {
        p.dataset.opened = "1";
        document.dispatchEvent(new CustomEvent("mp:tab-open", { detail: { id, panel: p } }));
      }
      if (target) { const t = target; target = null; requestAnimationFrame(() => t.scrollIntoView({ block: "start" })); }
    };
    tabs.forEach((t, i) => {
      t.addEventListener("click", (e) => {  // switch at once, then note it in the address (a new history entry)
        e.preventDefault();
        if (location.hash.slice(1) !== t.dataset.tab) history.pushState(null, "", "#" + t.dataset.tab);
        show(t.dataset.tab);
      });
      t.addEventListener("keydown", (e) => {  // arrow keys move between tabs, as in any tab list
        const j = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
        if (j === undefined) return;
        e.preventDefault();
        const next = tabs[(j + tabs.length) % tabs.length];
        history.replaceState(null, "", "#" + next.dataset.tab);
        show(next.dataset.tab, true);
      });
    });
    const follow = () => { const id = fromHash(); if (id) show(id); };  // back / forward, or a #link on the page
    window.addEventListener("popstate", follow);
    window.addEventListener("hashchange", follow);
    const first = fromHash();
    if (first) show(first);
    return { show };
  };

  // Run fn now if node is on a visible part of the page, else the first time the tab holding it is opened.
  MP.whenShown = function (node, fn) {
    if (!node) return;
    const panel = node.closest('[role="tabpanel"]');
    if (!panel || panel.classList.contains("is-active")) { fn(); return; }
    const on = (e) => { if (e.detail.panel === panel) { document.removeEventListener("mp:tab-open", on); fn(); } };
    document.addEventListener("mp:tab-open", on);
  };
  MP.$$("[data-tabs]").forEach((root) => MP.tabs(root));

  // ---- mobile nav ------------------------------------------------------------
  MP.$("#menu-btn")?.addEventListener("click", () => document.body.classList.toggle("nav-open"));
  MP.$("#scrim")?.addEventListener("click", () => document.body.classList.remove("nav-open"));

  // ---- greet ------------------------------------------------------------------
  const greet = MP.$("#greeting");
  if (greet) {
    const h = new Date().getHours();
    const first = (MP.prefs.name || "").split(" ")[0];
    greet.textContent = MP.t(h < 5 ? "Burning the midnight oil" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening") + (first ? `, ${first}` : "");
  }

  // ---- version watch: tell people when a new version is live -------------------
  async function checkVersion() {
    try {
      const v = await MP.api("/api/version");
      if (MP.commit && v.commit && v.commit !== MP.commit) MP.$("#update-banner").hidden = false;
    } catch (_) { /* server restarting — try later */ }
  }
  MP.$("#update-refresh")?.addEventListener("click", () => location.reload());
  setInterval(checkVersion, 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) checkVersion(); });

  // ---- running jobs badge -------------------------------------------------------
  async function activeBadge() {
    try {
      const d = await MP.api("/api/jobs?limit=50");
      const n = d.jobs.filter((j) => j.status === "running" || j.status === "queued").length;
      const b = MP.$("#active-jobs");
      if (b) { b.hidden = n === 0; b.textContent = n; }
    } catch (_) { }
  }
  activeBadge();
  setInterval(activeBadge, 15000);
})();
