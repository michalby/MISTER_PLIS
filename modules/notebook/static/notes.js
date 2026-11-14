// Lab notebook: the Notes panel beside every page, and the search on the full /notes page.
(function () {
  const { $, el, icon, api } = MP;
  const root = document.documentElement;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* private window */ } },
    del(k) { try { localStorage.removeItem(k); } catch (_) { } },
  };
  const noteHref = (id) => "/notes/" + id.split("/").map(encodeURIComponent).join("/");
  const prettyFolder = (f) => f.split("/").join(" / ");
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  // Folders fold open and shut; each browser remembers which ones it closed.
  const closedFolders = () => { try { return new Set(JSON.parse(store.get("mp:notes-closed") || "[]")); } catch (_) { return new Set(); } };
  function rememberFolders(container) {
    // "toggle" doesn't bubble, so listen while it travels down
    container.addEventListener("toggle", (e) => {
      const d = e.target;
      if (!(d instanceof HTMLDetailsElement) || !d.dataset.folder) return;
      const closed = closedFolders();
      if (d.open) closed.delete(d.dataset.folder); else closed.add(d.dataset.folder);
      store.set("mp:notes-closed", JSON.stringify([...closed]));
    }, true);
  }

  function treeView(tree, activeId) {
    if (!tree.length) return [el("p", { class: "notes-empty" }, MP.t("No notes in the chosen folders."))];
    const closed = closedFolders();
    return tree.map((g) => el("details", { class: "notes-group", open: !closed.has(g.folder), dataset: { folder: g.folder } },
      el("summary", { class: "notes-folder" }, icon("folder", 14), el("span", {}, prettyFolder(g.folder)), el("span", { class: "n" }, String(g.notes.length))),
      g.notes.map((n) => el("a", { class: "notes-item" + (n.id === activeId ? " active" : ""), href: noteHref(n.id), dataset: { note: n.id } },
        icon("file", 14), el("span", {}, n.title)))));
  }

  function resultsView(results, q) {
    if (!results.length) return [el("p", { class: "notes-empty" }, MP.t("No notes match “{q}”.", { q }))];
    return [el("div", { class: "notes-group" },
      el("div", { class: "notes-folder" }, icon("search", 14), el("span", {}, `${results.length} note${results.length === 1 ? "" : "s"}`)),
      results.map((r) => el("a", { class: "notes-item notes-hit", href: noteHref(r.id), dataset: { note: r.id } },
        el("span", { class: "notes-hit-title" }, r.title),
        el("span", { class: "notes-hit-folder" }, prettyFolder(r.folder)),
        r.snippet ? el("span", { class: "notes-hit-snippet" }, r.snippet) : null)))];
  }

  // Pictures in a note open full size in a new tab.
  function openImages(container) {
    container.addEventListener("click", (e) => {
      const img = e.target.closest(".note-body img");
      if (img && !img.closest("a")) window.open(img.src, "_blank", "noopener");
    });
  }

  // ---- full page (/notes) -----------------------------------------------------------
  if (document.body.dataset.page === "notes") {
    const q = $("#notes-page-q"), list = $("#notes-page-list");
    const closed = closedFolders();
    list.querySelectorAll("details.notes-group").forEach((d) => {
      if (closed.has(d.dataset.folder) && !d.querySelector(".notes-item.active")) d.open = false;
    });
    rememberFolders(list);
    const original = Array.from(list.childNodes);
    let seq = 0;
    q?.addEventListener("input", debounce(async () => {
      const text = q.value.trim(), mine = ++seq;
      if (!text) { list.replaceChildren(...original); return; }
      try {
        const d = await api("/api/notes/search?q=" + encodeURIComponent(text));
        if (mine === seq) list.replaceChildren(...resultsView(d.results, text));
      } catch (e) { MP.toast(e.message); }
    }, 180));
    q?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { const first = list.querySelector("a.notes-item"); if (first) location.href = first.href; }
      if (e.key === "Escape") { q.value = ""; list.replaceChildren(...original); }
    });
    const art = $(".notes-article");
    if (art) openImages(art);
    return;
  }

  // ---- the panel -----------------------------------------------------------------------
  const panel = $("#notes-panel");
  if (!panel) return;
  const body = $("#notes-body"), sub = $("#notes-sub"), full = $("#notes-full"), qIn = $("#notes-q"), btn = $("#notes-btn");
  const wide = MP.notesWide || window.matchMedia("(min-width: 1100px)");
  let data = null, loading = null, seq = 0;

  const isOpen = () => root.classList.contains("notes-open");
  function setOpen(open, remember = true) {
    root.classList.toggle("notes-open", open);
    btn?.setAttribute("aria-expanded", open ? "true" : "false");
    btn?.classList.toggle("on", open);
    if (remember && wide.matches) store.set("mp:notes-open", open ? "1" : "0");
    if (open) load();
    if (open && !wide.matches) qIn.focus({ preventScroll: true });
    // plots and wide tables re-fit to the new width
    requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
  }

  function load() {
    if (!loading) {
      loading = api("/api/notes").then((d) => {
        data = d;
        sub.textContent = d.commit && d.commit.short
          ? `${d.repo} · ${MP.t("synced {date}", { date: d.synced_at ? MP.date(d.synced_at) : MP.date(d.commit.date) })} · ${MP.t("read-only")}`
          : MP.t("not synced yet");
        const last = store.get("mp:notes-last");
        if (last) showNote(last, "", false); else showTree();
      }).catch((e) => {
        loading = null;
        body.replaceChildren(el("p", { class: "notes-empty" }, MP.t("Couldn't load the notes: {error}", { error: e.message })));
      });
    }
    return loading;
  }

  function showTree() {
    store.del("mp:notes-last");
    full.href = "/notes";
    if (!data.tree.length) {
      body.replaceChildren(el("p", { class: "notes-empty" },
        data.commit && data.commit.short ? MP.t("No notes in the chosen folders.") : MP.t("The notebook hasn't been downloaded yet.") + " ",
        data.commit && data.commit.short ? null : el("a", { href: "/settings#notebook" }, MP.t("Sync notes on Settings → Lab notebook"))));
      return;
    }
    body.replaceChildren(...treeView(data.tree, null));
    body.scrollTop = 0;
  }

  async function showNote(id, hash = "", userAction = true) {
    const mine = ++seq;
    let note;
    try { note = await api("/api/notes/note?id=" + encodeURIComponent(id)); }
    catch (e) {
      if (mine !== seq) return;
      if (userAction) MP.toast(e.message, 4000);
      showTree();
      return;
    }
    if (mine !== seq) return;
    store.set("mp:notes-last", note.id);
    full.href = noteHref(note.id) + (hash || "");
    const content = el("div", { class: "prose note-body", html: note.html });
    body.replaceChildren(...[
      el("div", { class: "note-crumbs" },
        el("button", { type: "button", class: "link-btn note-back", onclick: () => { qIn.value = ""; showTree(); } }, icon("chevron-left", 14), MP.t("All notes")),
        el("span", {}, "/ " + prettyFolder(note.folder))),
      el("h2", { class: "note-title" }, note.title),
      content,
      note.backlinks.length ? el("div", { class: "note-backlinks" },
        el("div", { class: "note-backlinks-head" }, MP.t("Linked from")),
        note.backlinks.map((b) => el("a", { class: "wikilink", href: noteHref(b.id), dataset: { note: b.id } }, b.title))) : null,
    ].filter(Boolean));  // a bare null here would be shown as the text "null"
    const target = hash && body.querySelector(`[id="${CSS.escape(decodeURIComponent(hash.slice(1)))}"]`);
    if (target) target.scrollIntoView({ block: "start" }); else body.scrollTop = 0;
  }

  // links inside the panel stay in the panel (ctrl/⌘-click still opens a tab)
  body.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    if (a.dataset.note) {
      e.preventDefault();
      const href = a.getAttribute("href") || "";
      showNote(a.dataset.note, href.includes("#") ? href.slice(href.indexOf("#")) : "");
    } else if ((a.getAttribute("href") || "").startsWith("#")) {
      e.preventDefault();
      const t = body.querySelector(`[id="${CSS.escape(decodeURIComponent(a.getAttribute("href").slice(1)))}"]`);
      t?.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  });
  openImages(body);
  rememberFolders(body);

  qIn.addEventListener("input", debounce(async () => {
    if (!data) await load();
    const text = qIn.value.trim(), mine = ++seq;
    if (!text) { showTree(); return; }
    try {
      const d = await api("/api/notes/search?q=" + encodeURIComponent(text));
      if (mine === seq) { body.replaceChildren(...resultsView(d.results, text)); body.scrollTop = 0; }
    } catch (e) { MP.toast(e.message); }
  }, 180));
  qIn.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { const first = body.querySelector("a.notes-item"); if (first) first.click(); }
    if (e.key === "Escape") { qIn.value = ""; showTree(); }
  });

  btn?.addEventListener("click", () => setOpen(!isOpen()));
  $("#notes-close").addEventListener("click", () => setOpen(false));
  $("#notes-rail").addEventListener("click", () => setOpen(true));
  $("#notes-scrim").addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (e) => {
    const t = e.target;
    const typing = t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement || t.isContentEditable;
    if ((e.key === "n" || e.key === "N") && !typing && !e.metaKey && !e.ctrlKey && !e.altKey && !e.repeat) {
      e.preventDefault();
      setOpen(!isOpen());
    } else if (e.key === "Escape" && isOpen() && !wide.matches) {
      setOpen(false);
    }
  });
  // crossing the size limit: small screens start closed, wide ones go back to what this browser chose
  wide.addEventListener("change", (e) => setOpen(e.matches && store.get("mp:notes-open") !== "0", false));

  // drag the left edge to resize (wide screens)
  const grip = $("#notes-resize");
  const maxW = () => Math.max(320, Math.min(900, window.innerWidth - 640));
  const setW = (w) => {
    w = Math.round(Math.min(maxW(), Math.max(300, w)));
    root.style.setProperty("--notes-w", w + "px");
    return w;
  };
  grip.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    grip.setPointerCapture(e.pointerId);
    root.classList.add("notes-resizing");
    const move = (ev) => setW(window.innerWidth - ev.clientX);
    const up = () => {
      grip.removeEventListener("pointermove", move);
      root.classList.remove("notes-resizing");
      store.set("mp:notes-w", String(panel.getBoundingClientRect().width));
      window.dispatchEvent(new Event("resize"));
    };
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", up, { once: true });
    grip.addEventListener("pointercancel", up, { once: true });
  });
  grip.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const w = setW(panel.getBoundingClientRect().width + (e.key === "ArrowLeft" ? 24 : -24));
    store.set("mp:notes-w", String(w));
  });

  btn?.setAttribute("aria-expanded", isOpen() ? "true" : "false");
  btn?.classList.toggle("on", isOpen());
  if (isOpen()) load();
})();
