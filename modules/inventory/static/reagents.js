// Reagents and Consumables: the inventory list (search, quick filters, all filters), one item (read-only), its
// edit view, the order list and info from the lab. The data is a workbook of the lab's inventory repository: the
// reagents (one row per reagent, key label_no) or the consumables (key item_no) — see mister_plis/reagents.py.
// Both spaces share this script; data-kind on #rg says which one, and W() has its words.
(function () {
  const { $, $$, el, api } = MP;
  const root = $("#rg");
  if (!root) return;
  const VIEW = root.dataset.view, RID = root.dataset.id;
  const CONS = root.dataset.kind === "consumables";
  const BASE = root.dataset.base || "/reagents", API = root.dataset.api || "/api/reagents";
  const INFO_API = "/api/reagents/info";  // one list of info from the lab, for reagents and consumables
  const SLOTS = 5;
  let words = null;
  const W = () => words || (words = CONS ? {
    space: MP.t("Consumables"), count: (n) => MP.tn(n, "{n} consumable", "{n} consumables"), newOne: MP.t("New consumable"),
    needsName: MP.t("A consumable needs a name."), infoThis: MP.t("Add info about this consumable"), infoAbout: MP.t("Info about this consumable"),
    infoAll: MP.t("Info about the consumables"), sameValue: MP.t("All consumables with this value"), keyName: MP.t("No."),
    disposed: MP.t("no longer used"), disposedHidden: (n) => MP.t("({n} no longer used not shown)", { n }),
    dispose: MP.t("No longer used…"), undispose: MP.t("In use after all"), disposeQ: (name) => MP.t("{name}: no longer used?", { name }),
    undisposeQ: (name) => MP.t("{name} is in use after all?", { name }),
    disposeText: MP.t("It stays in the inventory with its number, marked as no longer used with today's date, and leaves the list (a filter shows it again)."),
    producers: MP.t("Brands and suppliers"), producer: MP.t("Brand"), producerN: (n) => MP.t("Brand {n}", { n }), producern: (n) => MP.t("brand {n}", { n }),
    another: MP.t("Another brand"), noProducer: MP.t("Supplier not given"), amountHint: MP.t("e.g. 2 boxes"),
    filterFoot: MP.t("Brand filters look at brand 1; Brands (quick filters) looks at all of them."),
    howMany: MP.t("How many packs are there now?"), find: MP.t("Find a consumable to add to the list…"),
    nothing: MP.t("Nothing to order. Press Order… on a consumable, or find one below."),
    grouped: MP.t("Grouped by supplier (or brand). When it is ordered, press Ordered; when it arrives, press Arrived, type how many packs there are now, and it leaves the list."),
  } : {
    space: MP.t("Reagents"), count: (n) => MP.tn(n, "{n} reagent", "{n} reagents"), newOne: MP.t("New reagent"),
    needsName: MP.t("A reagent needs a name."), infoThis: MP.t("Add info about this reagent"), infoAbout: MP.t("Info about this reagent"),
    infoAll: MP.t("Info about the reagents"), sameValue: MP.t("All reagents with this value"), keyName: MP.t("Label no."),
    disposed: MP.t("disposed"), disposedHidden: (n) => MP.t("({n} disposed not shown)", { n }),
    dispose: MP.t("Used up / disposed of…"), undispose: MP.t("Not disposed after all"), disposeQ: (name) => MP.t("{name}: used up or disposed of?", { name }),
    undisposeQ: (name) => MP.t("{name} is not disposed after all?", { name }),
    disposeText: MP.t("It stays in the inventory with its label number, marked as disposed with today's date, and leaves the list (a filter shows it again)."),
    producers: MP.t("Producers"), producer: MP.t("Producer"), producerN: (n) => MP.t("Producer {n}", { n }), producern: (n) => MP.t("producer {n}", { n }),
    another: MP.t("Another producer"), noProducer: MP.t("Producer not given"), amountHint: MP.t("e.g. 2 × 1 L"),
    filterFoot: MP.t("Producer filters look at producer 1; Producers (quick filters) looks at all of them."),
    howMany: MP.t("How many containers are there now?"), find: MP.t("Find a reagent to add to the list…"),
    nothing: MP.t("Nothing to order. Mark a producer “to order” in the reagent's edit view, or add one below."),
    grouped: MP.t("Grouped by producer. When it is ordered, press Ordered; when it arrives, press Arrived, type how many containers there are now, and it leaves the list."),
  });
  const GROUPS = () => [["identification", MP.t("Identification")], ["status", MP.t("Status")], ["storage", MP.t("Storage")],
    ["borrowing", MP.t("Borrowing")], ["hazards", MP.t("Hazards")], ["producers", W().producers], ["ordering", MP.t("Ordering")],
    ["notes", MP.t("Notes")], ["other", MP.t("Other")]];
  // a link to a product page, shown as its site ("sigmaaldrich.com")
  const site = (v) => { try { return new URL(v).hostname.replace(/^www\./, ""); } catch (_) { return MP.t("open"); } };
  const extLink = (v, text) => el("a", { href: v, target: "_blank", rel: "noopener", class: "link", onclick: (e) => e.stopPropagation() }, text || site(v));

  const label = (f) => (MP.prefs.lang === "pl" ? f.label_pl : f.label) || f.label || f.key;
  const slotLabel = (f) => label(f).replace(/\s*\d+$/, "");  // "Producent 2" → "Producent"
  const RESTOCK_WORDS = () => ({ "": MP.t("Not needed"), needed: MP.t("To order"), ordered: MP.t("Ordered") });
  const empty = (v) => v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length);
  // the values of a cell, for filters: lists split, booleans as yes / no
  const vals = (f, v) => {
    if (empty(v)) return [];
    if (f.type === "bool") return [v ? "yes" : "no"];
    if (Array.isArray(v)) return v.map(String);
    if (f.type === "multi") return String(v).split(";").map((s) => s.trim()).filter(Boolean);
    return [String(v)];
  };
  const show = (f, v) => {
    if (empty(v)) return "";
    if (f.type === "bool") return v ? MP.t("yes") : MP.t("no");
    if (f.type === "number") return MP.num(v);
    if (f.type === "text" || f.type === "longtext") return String(v).replace(/;(?=\S)/g, "; ");  // "a;b" lists in text columns
    return vals(f, v).join(", ");
  };
  // bottle dates: an empty "opened on" means not opened; "use by" is checked against today
  const today = () => new Date().toISOString().slice(0, 10);
  const SOON_DAYS = 30;
  function expiryState(v) {
    if (empty(v)) return "";
    const s = String(v), t = today();
    if (s < t.slice(0, s.length)) return "expired";  // "2026-10" has run out only after October
    const end = s.length === 7 ? new Date(+s.slice(0, 4), +s.slice(5, 7), 0) : new Date(s);
    return (end - new Date(t)) / 864e5 <= SOON_DAYS ? "soon" : "";
  }
  const slotInUse = (r, n) => !empty(r[`producer_${n}_name`]) || !empty(r[`producer_${n}_catalog_no`]) || !empty(r[`producer_${n}_lot_no`]);
  // a slot's date, with its meaning: "not opened", "expired", "expires soon"
  function bottleDate(f, v, r) {
    if (f.slot_key === "opened_date" && empty(v)) return r && slotInUse(r, f.slot) ? el("span", { class: "muted rg-unopened" }, MP.t("not opened")) : "";
    if (f.slot_key === "expiry_date" && !empty(v)) {
      const st = expiryState(v);
      if (st) return el("span", { class: `rg-exp rg-exp-${st}`, title: st === "expired" ? MP.t("expired") : MP.t("expires soon") }, String(v), " ", el("small", {}, st === "expired" ? MP.t("expired") : MP.t("expires soon")));
    }
    return null;
  }
  const put = (node, ...kids) => node.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
  const errorBox = (err) => el("div", { class: "alert alert-error" }, MP.icon("alert", 16), el("span", {}, err.message || String(err)));
  const title = (r) => r._title || r.name_pl || r.id;

  // GHS pictograms: the official images (UN GHS, copied from the inventory repository's assets/ to static/ghs/)
  function ghsPicto(code, title, size = 64) {
    return el("img", { class: "rg-picto", src: `/m/inventory/static/ghs/GHS${code}.svg`, width: size, height: size, alt: title || `GHS${code}`, title: title || `GHS${code}`, loading: "lazy" });
  }

  // ordering from the list or a reagent's page: which producer, how much, a note
  function orderDialog(r, done) {
    const slots = [];
    for (let n = 1; n <= SLOTS; n++) if (r[`producer_${n}_name`]) slots.push(n);
    if (!slots.length) slots.push(1);
    const pick = el("select", {}, slots.map((n) => el("option", { value: n }, [r[`producer_${n}_name`] || W().producern(n), r[`producer_${n}_catalog_no`]].filter(Boolean).join(" · ")
      + (r[`producer_${n}_ordered`] ? ` — ${MP.t("ordered")}` : r[`producer_${n}_to_order`] ? ` — ${MP.t("on the list")}` : ""))));
    const first = slots.find((n) => r[`producer_${n}_to_order`]) || slots[0];
    pick.value = String(first);
    const amount = el("input", { type: "text", placeholder: W().amountHint });
    const note = el("input", { type: "text", value: r.order_note || "", placeholder: MP.t("e.g. the cheaper one from Chempur is fine") });
    const off = el("button", { type: "button", class: "btn btn-danger" }, MP.t("Take off the list"));
    const sync = () => { const n = +pick.value; amount.value = r[`producer_${n}_order_amount`] || ""; off.hidden = !(r[`producer_${n}_to_order`] || r[`producer_${n}_ordered`]); };
    pick.addEventListener("change", sync); sync();
    const dlg = el("dialog", { class: "dialog" }, el("form", { method: "dialog" },
      el("h3", {}, MP.t("Order {name}", { name: title(r) })),
      el("label", { class: "field" }, el("span", { class: "field-label" }, W().producer), el("div", { class: "control" }, pick)),
      el("label", { class: "field" }, el("span", { class: "field-label" }, MP.t("How much to order")), el("div", { class: "control" }, amount)),
      el("label", { class: "field" }, el("span", { class: "field-label" }, MP.t("Note for whoever orders")), el("div", { class: "control" }, note)),
      el("div", { class: "dialog-actions" }, off, el("span", { class: "rg-spacer" }), el("button", { class: "btn", value: "cancel" }, MP.t("Cancel")),
        el("button", { class: "btn btn-primary", value: "ok" }, MP.icon("cart", 15), MP.t("Add to the list")))));
    const send = async (state) => {
      try {
        const rec = await api(`${API}/${r.id}/restock`, { json: { slot: +pick.value, state, amount: state ? amount.value : undefined, note: note.value } });
        MP.toast(state ? MP.t("On the order list") : MP.t("Taken off the order list"));
        done && done(rec);
      } catch (err) { MP.toast(err.message, 6000); }
    };
    off.addEventListener("click", () => { dlg.close("off"); });
    document.body.append(dlg);
    dlg.addEventListener("close", () => { dlg.remove(); if (dlg.returnValue === "ok") send("needed"); else if (dlg.returnValue === "off") send(""); });
    dlg.showModal();
    amount.focus();
  }
  function orderButton(r, done, small = true) {
    const on = r.restock;
    return el("button", { type: "button", class: `btn ${small ? "btn-small" : ""} rg-order-btn${on ? ` is-${on}` : ""}`, title: MP.t("Add to the order list"),
      onclick: (e) => { e.stopPropagation(); orderDialog(r, done); } }, MP.icon("cart", 14), on ? RESTOCK_WORDS()[on] : MP.t("Order…"));
  }

  // labels for a portion of a reagent put into a new container, printed on the lab's P-touch: a simple one
  // (English name, molar mass, who and when, the storage category in a rounded square) or, in full, that one
  // plus a second with the GHS pictograms, the catalogue number and the lot
  async function labelDialog(r, ghsFields) {
    let printer;
    try { printer = await api("/api/label/printer"); } catch (err) { MP.toast(err.message, 5000); return; }
    const slots = [];
    for (let n = 1; n <= SLOTS; n++) if (slotInUse(r, n)) slots.push(n);
    const st = { full: false, name: r.name_en || title(r), person: MP.prefs.name || "", date: MP.date(new Date()), slot: slots[0] || 0, copies: 1 };
    const pictos = ghsFields.filter((f) => r[f.key] === true).map((f) => GHS_KEY.exec(f.key)[1]);
    const mass = empty(r.molar_mass_g_mol) ? "" : `M = ${MP.num(r.molar_mass_g_mol)} g/mol`;
    function labels() {
      const first = { name: st.name, detail: mass, person: st.person, date: st.date,
        square: r.storage_category_primary || "", right: String(r.id), logo: false, match: "portion" };
      const p = st.slot ? `producer_${st.slot}_` : null;
      const cat = p && r[p + "catalog_no"], lot = p && r[p + "lot_no"];
      const second = { name: cat ? `Cat. no. ${cat}` : "", detail: (p && r[p + "name"]) || "", person: lot ? `LOT ${lot}` : "", date: "", pictos, logo: false, match: "portion" };
      const one = st.full ? [first, second] : [first];
      return Array.from({ length: st.copies }, () => one).flat();
    }
    const img = el("img", { alt: "" });
    const err = el("p", { class: "alert alert-error", hidden: true });
    let blob = null, url = "", timer = 0;
    const printBtn = el("button", { type: "button", class: "btn btn-primary", disabled: true }, MP.icon("tag", 15), MP.t("Print"));
    async function preview() {
      try {
        const res = await fetch("/api/label/preview.png", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ labels: labels() }) });
        if (!res.ok) { let m = res.statusText; try { m = (await res.json()).error || m; } catch (_) { } throw new Error(m); }
        blob = await res.blob(); if (url) URL.revokeObjectURL(url); url = URL.createObjectURL(blob);
        img.src = url; img.hidden = false; err.hidden = true;
      } catch (e) { blob = null; img.hidden = true; err.hidden = false; err.textContent = e.message; }
      printBtn.disabled = !printer.address || !blob;
    }
    const changed = () => { clearTimeout(timer); timer = setTimeout(preview, 250); };
    const text = (key, attrs = {}) => { const i = el("input", { type: "text", value: st[key], ...attrs }); i.addEventListener("input", () => { st[key] = i.value; changed(); }); return i; };
    const kind = el("div", { class: "seg seg-small", role: "radiogroup" });
    const kinds = [[false, MP.t("Simple (1 label)")], [true, MP.t("Full (2 labels)")]];
    const prodField = el("label", { class: "label-field" }, el("span", { class: "field-label" }, MP.t("Producer (catalogue no., LOT)")),
      el("div", { class: "control" }, (() => {
        const s = el("select", {}, slots.length ? slots.map((n) => el("option", { value: n }, [r[`producer_${n}_name`] || MP.t("producer {n}", { n }), r[`producer_${n}_catalog_no`], r[`producer_${n}_lot_no`] && `LOT ${r[`producer_${n}_lot_no`]}`].filter(Boolean).join(" · ")))
          : el("option", { value: 0 }, "—"));
        s.addEventListener("change", () => { st.slot = +s.value; changed(); });
        return s;
      })()));
    const drawKind = () => { kind.querySelectorAll("button").forEach((b, i) => b.classList.toggle("active", kinds[i][0] === st.full)); prodField.hidden = !st.full; };
    kinds.forEach(([v, t]) => kind.append(el("button", { type: "button", role: "radio", onclick: () => { st.full = v; drawKind(); changed(); } }, t)));
    drawKind();
    const copies = el("input", { type: "number", min: 1, max: 20, value: 1 });
    copies.addEventListener("input", () => { st.copies = Math.max(1, Math.min(20, Math.round(+copies.value) || 1)); changed(); });
    const download = el("button", { type: "button", class: "btn" }, MP.icon("download", 14), "PNG");
    download.addEventListener("click", () => {
      if (!blob) return;
      const a = el("a", { href: url, download: `label_${r.id}.png` }); document.body.append(a); a.click(); a.remove();
    });
    printBtn.addEventListener("click", async () => {
      printBtn.disabled = true;
      try { MP.toast((await api("/api/label/print", { json: { labels: labels() } })).message, 3500); }
      catch (e) { MP.toast(e.message, 5000); }
      finally { printBtn.disabled = !printer.address || !blob; }
    });
    const dlg = el("dialog", { class: "dialog label-dialog rg-label-dlg" }, el("form", { method: "dialog" },
      el("h3", {}, MP.t("Label for a portion of {name}", { name: title(r) })),
      el("p", { class: "muted" }, MP.t("For a new container filled from this reagent.")),
      el("div", { class: "label-preview" }, img, err),
      el("div", { class: "rg-label-form" },
        el("div", { class: "label-field rg-label-kind" }, el("span", { class: "field-label" }, MP.t("Labels")), kind),
        el("label", { class: "label-field" }, el("span", { class: "field-label" }, MP.t("Name on the label")), el("div", { class: "control" }, text("name", { maxlength: 80 }))),
        el("label", { class: "label-field" }, el("span", { class: "field-label" }, MP.t("Portioned by")), el("div", { class: "control" }, text("person", { maxlength: 60 }))),
        el("label", { class: "label-field" }, el("span", { class: "field-label" }, MP.t("Portioned on")), el("div", { class: "control" }, text("date", { maxlength: 30 }))),
        el("label", { class: "label-field" }, el("span", { class: "field-label" }, MP.t("Copies")), el("div", { class: "control" }, copies)),
        prodField),
      el("p", { class: "muted label-printer" }, printer.address ? MP.t("Printer: {address}", { address: printer.address })
        : MP.t("No label printer set up yet — add it in Settings → Exports & printing. You can still download the PNG.")),
      el("div", { class: "dialog-actions" }, el("button", { class: "btn", value: "cancel" }, MP.t("Close")), download, printBtn)));
    dlg.addEventListener("close", () => { clearTimeout(timer); if (url) URL.revokeObjectURL(url); dlg.remove(); });
    document.body.append(dlg);
    dlg.showModal();
    preview();
  }

  // back to the top: a button in the bottom right corner once the page is scrolled
  (function backToTop() {
    const b = $("#rg-top");
    if (!b) return;
    const sync = () => { b.hidden = window.scrollY < 500; };
    window.addEventListener("scroll", sync, { passive: true });
    b.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
    sync();
  })();

  let CATS = {};
  function catBadge(code) {
    if (empty(code)) return null;
    const c = CATS[code];
    const hex = c && c.color_hex ? String(c.color_hex) : "";
    const n = hex.length === 7 ? parseInt(hex.slice(1), 16) : 0xdddddd;
    const light = ((n >> 16) * 0.299 + ((n >> 8) & 255) * 0.587 + (n & 255) * 0.114) > 140;
    return el("span", { class: "rg-cat", style: hex ? `background:${hex};color:${light ? "#111" : "#fff"}` : null, title: c ? c.name : "" }, code);
  }
  function ghsChips(list) {  // small pictograms, e.g. in the list when its column is chosen
    return el("span", { class: "rg-ghs" }, (list || []).map((g) => { const m = /GHS0?(\d)/.exec(g); return m ? ghsPicto(`0${m[1]}`, g, 26) : el("span", { class: "rg-ghs-chip" }, g); }));
  }
  function counts(d) {
    const n = d.items.filter((r) => r.restock === "needed" && r.is_disposed !== true).length;
    const o = $("#rg-n-order"); if (o) { o.hidden = !n; o.textContent = n; }
    const i = $("#rg-n-info"); if (i) { i.hidden = !d.open_info; i.textContent = d.open_info; }
    CATS = Object.fromEntries((d.categories || []).map((c) => [c.code, c]));
  }
  // the values a field has across the inventory, most common first
  function valuesOf(items, f) {
    const c = new Map();
    for (const r of items) for (const v of vals(f, r[f.key])) c.set(v, (c.get(v) || 0) + 1);
    for (const o of f.options || []) if (!c.has(o)) c.set(o, 0);
    return [...c.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], undefined, { numeric: true }));
  }
  function restockBadge(state) {
    if (!state) return null;
    return el("span", { class: `rg-badge rg-badge-${state}` }, MP.icon("cart", 12), RESTOCK_WORDS()[state]);
  }
  // a brand marked "don't buy again"
  function avoidBadge(r) {
    const bad = [];
    for (let n = 1; n <= SLOTS; n++) if (r[`producer_${n}_avoid`] === true) bad.push(r[`producer_${n}_name`] || W().producern(n));
    return bad.length ? el("span", { class: "rg-badge rg-badge-avoid", title: MP.t("Don't buy again") }, MP.t("don't buy: {names}", { names: bad.join(", ") })) : null;
  }
  function notReady(box) {
    put(box, el("div", { class: "rg-empty" }, el("b", {}, MP.t("The inventory isn't here yet.")),
      el("span", {}, MP.t("It comes from the lab's inventory repository on GitHub — sync it first.")),
      el("div", { class: "rg-empty-actions" }, el("a", { class: "btn btn-primary btn-small", href: "/settings#inventory" }, MP.icon("sync", 14), MP.t("Sync with GitHub")))));
  }
  function cellView(f, v, r) {
    const d = f.slot ? bottleDate(f, v, r) : null;
    if (d !== null) return d;
    if (f.key === "storage_category_primary") return catBadge(v);
    if (f.key === "storage_categories") return el("span", { class: "rg-cats" }, vals(f, v).map(catBadge));
    if (f.key === "_ghs") return ghsChips(v);
    if (f.type === "url" && !empty(v)) return extLink(v);
    if (f.type === "bool") return v === true ? el("span", { class: "rg-yes" }, "✓") : v === false ? el("span", { class: "muted" }, "–") : "";
    return show(f, v);
  }

  // =============================================================================== the list
  async function listView() {
    const box = $("#rg-list");
    let data;
    try { data = await api(API); } catch (err) { put(box, errorBox(err)); return; }
    counts(data);
    if (!data.ready) { notReady(box); $("#rg-quick").hidden = true; return; }
    const { fields, items, config } = data;
    const byKey = Object.fromEntries(fields.map((f) => [f.key, f]));
    const quickFields = config.quick.map((k) => byKey[k]).filter(Boolean);
    // the list's columns: chosen in this browser (Columns…), or the lab's default
    const COLS_KEY = CONS ? "mp:cs-cols" : "mp:rg-cols";
    let chosen = null;
    try { chosen = JSON.parse(localStorage.getItem(COLS_KEY) || "null"); } catch (_) { }
    const cols = [];
    function setCols(keys) {
      cols.length = 0;
      for (const k of keys) if (byKey[k]) cols.push(byKey[k]);
      if (!cols.length) cols.push(byKey._title || fields[0]);
    }
    setCols(Array.isArray(chosen) && chosen.length ? chosen : config.list);
    function saveCols(keys) {
      try { localStorage.setItem(COLS_KEY, JSON.stringify(keys)); } catch (_) { }
      setCols(keys); draw();
    }
    const colName = (f) => (f.slot ? slotLabel(f) + " (1)" : (f.key === config.key ? W().keyName : label(f)));
    const titleKey = "_title";
    const SORT0 = "_title";

    const S = { q: "", restock: "", quick: {}, adv: {}, sort: SORT0, desc: false, more: {} };
    const params = new URLSearchParams(location.search);
    S.q = params.get("q") || "";
    S.restock = params.get("restock") || "";
    if (params.get("sort")) { S.sort = params.get("sort"); S.desc = params.get("desc") === "1"; }
    for (const [k, v] of params) {
      if (k.startsWith("f.") && byKey[k.slice(2)]) (S.quick[k.slice(2)] ||= new Set()).add(v);
      if (k.startsWith("a.")) S.adv[k.slice(2)] = v;
    }
    const q = $("#rg-q");
    q.value = S.q;

    function save() {
      const p = new URLSearchParams();
      if (S.q) p.set("q", S.q);
      if (S.restock) p.set("restock", S.restock);
      for (const [k, set] of Object.entries(S.quick)) for (const v of set) p.append(`f.${k}`, v);
      for (const [k, v] of Object.entries(S.adv)) if (v !== "") p.set(`a.${k}`, v);
      if (S.sort !== SORT0 || S.desc) { p.set("sort", S.sort); if (S.desc) p.set("desc", "1"); }
      history.replaceState(null, "", location.pathname + (p.toString() ? `?${p}` : ""));
    }
    const folded = new Map(items.map((r) => [r.id, MP.fold(fields.map((f) => vals(f, r[f.key]).join(" ")).join(" \u0001 "))]));
    const showDisposed = () => (S.quick.is_disposed && S.quick.is_disposed.size) || (S.adv.is_disposed ?? "") !== "";

    function matches(r, skipKey) {
      if (r.is_disposed === true && !showDisposed()) return false;
      if (S.q) {
        const t = folded.get(r.id);
        const words = MP.fold(S.q).split(/\s+/).filter(Boolean);
        if (!words.every((w) => t.includes(w) || r.id === w.replace(/^#/, ""))) return false;
      }
      if (S.restock === "any" ? !r.restock : S.restock && r.restock !== S.restock) return false;
      for (const [k, set] of Object.entries(S.quick)) {
        if (k === skipKey || !set.size || !byKey[k]) continue;
        const have = vals(byKey[k], r[k]);
        if (![...set].some((v) => (v === "∅" ? !have.length : have.includes(v)))) return false;
      }
      for (const [ak, v] of Object.entries(S.adv)) {
        if (v === "") continue;
        const [k, op] = ak.split("~"); const f = byKey[k]; if (!f) continue;
        const val = r[k];
        if (op === "has") { if ((v === "1") === empty(val)) return false; continue; }
        if (op === "min" || op === "max") {
          if (f.type === "number") { const n = parseFloat(String(v).replace(",", ".")); if (isNaN(n)) continue; if (typeof val !== "number" || (op === "min" ? val < n : val > n)) return false; }
          else if (empty(val) || (op === "min" ? String(val) < v : String(val).slice(0, v.length) > v)) return false;
          continue;
        }
        if (["choice", "multi", "bool"].includes(f.type)) { const have = vals(f, val); if (!(v === "∅" ? !have.length : have.includes(v))) return false; continue; }
        if (!MP.fold(vals(f, val).join(" ")).includes(MP.fold(v))) return false;
      }
      return true;
    }

    // quick filters: chips for the chosen fields, counted within the other filters
    const quickBox = $("#rg-quick");
    function drawQuick() {
      const rows = [];
      if (config.quick.includes("_to_order")) {
        const nNeeded = items.filter((r) => r.restock === "needed" && matches(r)).length;
        rows.push(el("div", { class: "rg-quick-row" }, el("span", { class: "rg-quick-label" }, MP.t("To order")),
          el("div", { class: "rg-chips" }, [["", MP.t("Everything")], ["needed", MP.t("To order")], ["ordered", MP.t("Ordered")], ["any", MP.t("To order or ordered")]].map(([v, t]) =>
            el("button", { type: "button", class: `rg-chip${S.restock === v ? " on" : ""}${v === "needed" ? " rg-chip-needed" : ""}`, onclick: () => { S.restock = v; draw(); } },
              t, v === "needed" && nNeeded ? el("small", {}, nNeeded) : null)))));
      }
      for (const f of quickFields) {
        const all = valuesOf(items, f);
        const pool = items.filter((r) => matches(r, f.key) || (f.key === "is_disposed" && r.is_disposed === true));
        const cnt = (v) => pool.filter((r) => vals(f, r[f.key]).includes(v)).length;
        const set = S.quick[f.key] || new Set();
        const LIMIT = 12;
        const more = S.more[f.key];
        let shown = all.filter(([v, total]) => set.has(v) || (total > 0 && (cnt(v) > 0 || all.length <= LIMIT)));
        const hiddenN = Math.max(0, shown.length - LIMIT);
        if (!more && hiddenN) shown = shown.filter(([v], i) => i < LIMIT || set.has(v));
        const blanks = pool.filter((r) => empty(r[f.key])).length;
        const word = (v) => (f.type === "bool" ? MP.t(v) : v);
        const chip = (v, text, n, extra) => el("button", { type: "button", class: `rg-chip${set.has(v) ? " on" : ""}`, "aria-pressed": set.has(v) ? "true" : "false",
          onclick: () => { const s = (S.quick[f.key] ||= new Set()); s.has(v) ? s.delete(v) : s.add(v); if (!s.size) delete S.quick[f.key]; draw(); } },
          extra || null, text, el("small", {}, n));
        rows.push(el("div", { class: "rg-quick-row" }, el("span", { class: "rg-quick-label" }, label(f)),
          el("div", { class: "rg-chips" },
            shown.map(([v]) => chip(v, f.key === "storage_category_primary" && CATS[v] ? CATS[v].name : word(v), cnt(v), f.key === "storage_category_primary" ? catBadge(v) : null)),
            blanks && f.key !== "is_disposed" ? chip("∅", MP.t("not filled in"), blanks) : null,
            hiddenN ? el("button", { type: "button", class: "rg-chip rg-chip-more", onclick: () => { S.more[f.key] = !more; drawQuick(); } },
              more ? MP.t("fewer") : MP.t("{n} more…", { n: hiddenN })) : null)));
      }
      put(quickBox, ...rows);
    }

    // all filters: one per field, in the edit view's groups
    const panel = $("#rg-filters"), fbtn = $("#rg-filters-btn");
    fbtn.addEventListener("click", () => { panel.hidden = !panel.hidden; fbtn.setAttribute("aria-expanded", String(!panel.hidden)); fbtn.classList.toggle("active", !panel.hidden); });
    function advInput(key, kind, attrs = {}) {
      const input = el(kind === "select" ? "select" : "input", attrs);
      if (kind !== "select") input.type = kind;
      input.value = S.adv[key] ?? "";
      input.addEventListener(kind === "select" ? "change" : "input", () => { S.adv[key] = input.value; draw(); });
      return el("div", { class: "control" }, input);
    }
    function filterFor(f) {
      const L = label(f);
      let ctl;
      if (f.type === "number" || f.type === "date") {
        const t = f.type === "number" ? "text" : "date";
        ctl = el("div", { class: "rg-range" }, advInput(`${f.key}~min`, t, { placeholder: MP.t("from"), "aria-label": `${L}: ${MP.t("from")}`, inputmode: f.type === "number" ? "decimal" : null }),
          el("span", { class: "muted" }, "–"), advInput(`${f.key}~max`, t, { placeholder: MP.t("to"), "aria-label": `${L}: ${MP.t("to")}`, inputmode: f.type === "number" ? "decimal" : null }));
      } else if (["choice", "multi", "bool"].includes(f.type)) {
        const opts = f.type === "bool" ? [["yes", MP.t("yes")], ["no", MP.t("no")]] : valuesOf(items, f).map(([v]) => [v, v]);
        const c = advInput(f.key, "select", { "aria-label": L });
        c.firstChild.append(el("option", { value: "" }, MP.t("Any")), ...opts.map(([v, t]) => el("option", { value: v }, t)), el("option", { value: "∅" }, MP.t("not filled in")));
        c.firstChild.value = S.adv[f.key] ?? "";
        ctl = c;
      } else ctl = advInput(f.key, "search", { placeholder: MP.t("contains…"), "aria-label": L });
      const has = advInput(`${f.key}~has`, "select", { "aria-label": `${L}: ${MP.t("filled in")}` });
      has.firstChild.append(el("option", { value: "" }, "—"), el("option", { value: "1" }, MP.t("filled in")), el("option", { value: "0" }, MP.t("empty")));
      has.firstChild.value = S.adv[`${f.key}~has`] ?? "";
      has.classList.add("rg-has");
      return el("div", { class: "filter-field" }, el("span", { class: "field-label" }, L), el("div", { class: `rg-filter-row${f.type === "number" || f.type === "date" ? " is-range" : ""}` }, ctl, has));
    }
    function drawPanel() {
      const parts = GROUPS().map(([g, gname]) => {
        const fs = fields.filter((f) => (f.group || "other") === g && !(f.slot > 1) && !f.hidden && f.key !== "_title");
        if (!fs.length) return null;
        return el("details", { class: "rg-filter-group", open: g !== "producers" && g !== "notes" ? true : null },
          el("summary", {}, gname), el("div", { class: "rg-filter-grid" }, fs.map(filterFor)));
      });
      put(panel, ...parts, el("div", { class: "rg-filter-foot" },
        el("span", { class: "muted small" }, W().filterFoot),
        el("button", { type: "button", class: "btn btn-small", onclick: clearAll }, MP.icon("x", 14), MP.t("Clear all filters"))));
    }
    function clearAll() { S.q = ""; q.value = ""; S.restock = ""; S.quick = {}; S.adv = {}; drawPanel(); draw(); }

    function sortVal(r) {
      const f = byKey[S.sort]; const v = S.sort === "restock" ? r.restock : r[S.sort];
      if (empty(v)) return null;
      if (typeof v === "number") return v;
      if (S.sort === config.key) return Number(v) || v;
      return MP.fold(f ? vals(f, v).join(", ") : String(v));
    }
    function sorted(list) {
      return list.slice().sort((a, b) => {
        const x = sortVal(a), y = sortVal(b);
        if (x === null && y === null) return 0; if (x === null) return 1; if (y === null) return -1;
        const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true });
        return S.desc ? -c : c;
      });
    }
    // the filters in words, for the printed list: [label, value]
    function describe() {
      const out = [];
      if (S.q) out.push([MP.t("Search"), S.q]);
      if (S.restock) out.push([MP.t("To order"), { needed: MP.t("To order"), ordered: MP.t("Ordered"), any: MP.t("To order or ordered") }[S.restock]]);
      for (const [k, set] of Object.entries(S.quick)) {
        const f = byKey[k];
        if (!f || !set.size) continue;
        const word = (v) => (v === "∅" ? MP.t("not filled in") : k === "storage_category_primary" && CATS[v] ? `${v} ${CATS[v].name}` : f.type === "bool" ? MP.t(v) : v);
        out.push([label(f), [...set].map(word).join(", ")]);
      }
      for (const [ak, v] of Object.entries(S.adv)) {
        if (v === "") continue;
        const [k, op] = ak.split("~"); const f = byKey[k]; if (!f) continue;
        const what = op === "has" ? (v === "1" ? MP.t("filled in") : MP.t("empty")) : v === "∅" ? MP.t("not filled in") : f.type === "bool" ? MP.t(v) : v;
        out.push([op === "min" ? `${label(f)} ${MP.t("from")}` : op === "max" ? `${label(f)} ${MP.t("to")}` : label(f), what]);
      }
      return out;
    }
    // Excel, CSV or PDF of what the list shows: these rows, in this order, with these columns
    function download(fmt) {
      const f = byKey[S.sort];
      const data = { ids: sorted(items.filter((r) => matches(r))).map((r) => r.id), columns: cols.map((c) => c.key), filters: describe(),
        sort: S.sort === "restock" ? MP.t("Order") : f ? (f.key === config.key ? W().keyName : label(f)) : "", desc: S.desc };
      const form = el("form", { method: "post", action: `${API}/list.${fmt}`, target: fmt === "pdf" ? "_blank" : null, hidden: true },
        el("input", { type: "hidden", name: "data", value: JSON.stringify(data) }));
      document.body.append(form);
      form.submit();
      form.remove();
    }
    function drawTable(list) {
      // a header sorts when clicked, and can be dragged left or right to move its column
      const th = (key, text, num) => {
        const h = el("th", { class: num ? "num" : "", title: key === "restock" ? null : MP.t("Click to sort, drag to move"),
          onclick: () => { S.desc = S.sort === key ? !S.desc : key === "restock"; S.sort = key; draw(); } },
          text, S.sort === key ? el("span", { class: "arrow" }, S.desc ? "↓" : "↑") : null);
        if (key === "restock") return h;
        h.draggable = true;
        h.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/x-rg-col", key); e.dataTransfer.effectAllowed = "move"; h.classList.add("is-dragged"); });
        h.addEventListener("dragend", () => { h.classList.remove("is-dragged"); $$(".rg-table th").forEach((x) => x.classList.remove("drop-before", "drop-after")); });
        h.addEventListener("dragover", (e) => {
          if (!e.dataTransfer.types.includes("text/x-rg-col")) return;
          e.preventDefault();
          const r = h.getBoundingClientRect(), after = e.clientX > r.left + r.width / 2;
          h.classList.toggle("drop-after", after); h.classList.toggle("drop-before", !after);
        });
        h.addEventListener("dragleave", () => h.classList.remove("drop-before", "drop-after"));
        h.addEventListener("drop", (e) => {
          e.preventDefault();
          const from = e.dataTransfer.getData("text/x-rg-col");
          const after = h.classList.contains("drop-after");
          h.classList.remove("drop-before", "drop-after");
          if (!from || from === key) return;
          const keys = cols.map((f) => f.key).filter((k) => k !== from);
          keys.splice(keys.indexOf(key) + (after ? 1 : 0), 0, from);
          saveCols(keys);
        });
        return h;
      };
      const head = el("tr", {}, ...cols.map((f) => th(f.key, f.key === config.key ? "#" : label(f), f.type === "number")), th("restock", MP.t("Order")));
      const LIMIT = 500;
      const rows = sorted(list).slice(0, LIMIT).map((r) => el("tr", { class: `rg-row${r.is_disposed === true ? " is-disposed" : ""}`, tabindex: "0", dataset: { id: r.id } },
        ...cols.map((f) => {
          const t = show(f, r[f.key]);
          const cell = f.key === titleKey ? el("a", { href: `${BASE}/${r.id}`, class: "rg-name-link" }, t || title(r)) : cellView(f, r[f.key], r);
          return el("td", { class: (f.type === "number" ? "num" : "") + (empty(r[f.key]) ? " null" : "") + (f.key === titleKey ? " rg-name" : ""), title: t }, cell);
        }),
        el("td", { class: "rg-row-act" }, r.is_disposed === true ? el("span", { class: "rg-badge rg-badge-disposed" }, W().disposed) : orderButton(r, (rec) => { Object.assign(r, rec); draw(); }),
          r.is_borrowed === true ? el("span", { class: "rg-badge rg-badge-borrowed", title: r.borrowed_by || "" }, MP.t("borrowed")) : null)));
      const table = el("table", { class: "data rg-table" }, el("thead", {}, head), el("tbody", {}, rows));
      table.addEventListener("click", (e) => { const tr = e.target.closest("tr.rg-row"); if (tr && !e.target.closest("a, button")) location.href = `${BASE}/${tr.dataset.id}`; });
      table.addEventListener("keydown", (e) => { const tr = e.target.closest("tr.rg-row"); if (tr && e.key === "Enter") location.href = `${BASE}/${tr.dataset.id}`; });
      if (!list.length) { put(box, el("div", { class: "rg-empty" }, el("b", {}, MP.t("Nothing matches.")), el("span", {}, MP.t("Try fewer words or clear some filters.")))); return; }
      put(box, table, list.length > LIMIT ? el("div", { class: "table-foot" }, MP.t("The first {n} are shown — narrow the search to see the rest.", { n: LIMIT })) : null);
    }

    function draw() {
      save();
      const list = items.filter((r) => matches(r));
      const live = items.filter((r) => r.is_disposed !== true);
      const nAdv = Object.values(S.adv).filter((v) => v !== "").length;
      const nf = $("#rg-filters-n"); nf.hidden = !nAdv; nf.textContent = nAdv;
      const active = S.q || S.restock || Object.keys(S.quick).length || nAdv;
      const hidden = showDisposed() ? 0 : items.length - live.length;
      put($("#rg-summary"),
        el("span", {}, list.length === live.length && !showDisposed() ? W().count(live.length) : MP.t("{a} of {b}", { a: list.length, b: W().count(live.length) })),
        hidden ? el("span", { class: "muted" }, W().disposedHidden(hidden)) : null,
        active ? el("button", { type: "button", class: "link rg-clear", onclick: clearAll }, MP.t("clear filters")) : null,
        list.length ? el("span", { class: "rg-summary-right" },  // the app's export buttons, in the app's order
          MP.exportBtn("pdf", { onclick: () => download("pdf"), title: MP.t("A list to print, e.g. for the shelf — what goes on it is set in Settings → Reagents & consumables") }),
          MP.exportBtn("xlsx", { onclick: () => download("xlsx"), title: MP.t("What the list shows: these rows, in this order, with these columns") }),
          MP.exportBtn("csv", { onclick: () => download("csv"), title: MP.t("What the list shows: these rows, in this order, with these columns") })) : null);
      drawQuick();
      drawTable(list);
    }
    let t = null;
    q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { S.q = q.value.trim(); draw(); }, 120); });
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && !e.target.closest("input, textarea, select, [contenteditable]")) { e.preventDefault(); q.focus(); }
    });
    // Columns…: what the list shows, and in which order, in this browser
    $("#rg-cols-btn").addEventListener("click", () => {
      let order = cols.map((f) => f.key);
      const boxes = [];
      const list = el("ol", { class: "rg-cols-order" });
      function drawOrder() {
        put(list, order.map((k, i) => {
          const f = byKey[k];
          const li = el("li", { draggable: "true", dataset: { key: k } },
            el("span", { class: "rg-grip", "aria-hidden": "true" }, "⋮⋮"), el("span", { class: "rg-cols-name" }, colName(f)),
            el("button", { type: "button", class: "icon-btn icon-btn-sm", title: MP.t("Move left (up)"), "aria-label": MP.t("Move left (up)"), disabled: i === 0 ? true : null,
              onclick: () => { [order[i - 1], order[i]] = [order[i], order[i - 1]]; drawOrder(); } }, "↑"),
            el("button", { type: "button", class: "icon-btn icon-btn-sm", title: MP.t("Move right (down)"), "aria-label": MP.t("Move right (down)"), disabled: i === order.length - 1 ? true : null,
              onclick: () => { [order[i + 1], order[i]] = [order[i], order[i + 1]]; drawOrder(); } }, "↓"),
            el("button", { type: "button", class: "icon-btn icon-btn-sm", title: MP.t("Hide this column"), "aria-label": MP.t("Hide this column"), disabled: order.length === 1 ? true : null,
              onclick: () => { order = order.filter((x) => x !== k); syncBoxes(); drawOrder(); } }, MP.icon("x", 13)));
          li.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/x-rg-li", k); li.classList.add("is-dragged"); });
          li.addEventListener("dragend", () => li.classList.remove("is-dragged"));
          li.addEventListener("dragover", (e) => { e.preventDefault(); const r = li.getBoundingClientRect(); li.classList.toggle("drop-after", e.clientY > r.top + r.height / 2); li.classList.toggle("drop-before", e.clientY <= r.top + r.height / 2); });
          li.addEventListener("dragleave", () => li.classList.remove("drop-before", "drop-after"));
          li.addEventListener("drop", (e) => {
            e.preventDefault();
            const from = e.dataTransfer.getData("text/x-rg-li"), after = li.classList.contains("drop-after");
            li.classList.remove("drop-before", "drop-after");
            if (!from || from === k) return;
            order = order.filter((x) => x !== from);
            order.splice(order.indexOf(k) + (after ? 1 : 0), 0, from);
            drawOrder();
          });
          return li;
        }));
      }
      const syncBoxes = () => boxes.forEach((b) => { b.checked = order.includes(b.value); });
      const groups = GROUPS().map(([g, gname]) => {
        const fs = fields.filter((f) => (f.group || "other") === g && !(f.slot > 1) && (!f.hidden || order.includes(f.key)));
        if (!fs.length) return null;
        return el("fieldset", { class: "rg-cols-group" }, el("legend", {}, gname), fs.map((f) => {
          const cb = el("input", { type: "checkbox", value: f.key });
          cb.addEventListener("change", () => {
            order = cb.checked ? [...order.filter((x) => x !== f.key), f.key] : order.filter((x) => x !== f.key);
            if (!order.length) { order = [f.key]; cb.checked = true; }
            drawOrder();
          });
          boxes.push(cb);
          return el("label", { class: "rg-opt" }, cb, el("span", {}, colName(f)));
        }));
      });
      syncBoxes(); drawOrder();
      const reset = el("button", { type: "button", class: "btn" }, MP.t("The lab's default"));
      reset.addEventListener("click", () => { order = config.list.filter((k) => byKey[k]); syncBoxes(); drawOrder(); });
      // these columns, in this order, for everyone who hasn't chosen their own
      const makeDefault = el("button", { type: "button", class: "btn", title: MP.t("For everyone who hasn't chosen their own columns") }, MP.t("Use as the lab's default"));
      makeDefault.addEventListener("click", async () => {
        makeDefault.disabled = true;
        try {
          const d = await api(`${API}/fields`, { json: { display: { list: order } } });
          config.list = d.config.list;
          try { localStorage.removeItem(COLS_KEY); } catch (_) { }
          MP.toast(MP.t("Saved as the lab's default"));
          dlg.close("cancel"); setCols(config.list); draw();
        } catch (err) { MP.toast(err.message, 5000); makeDefault.disabled = false; }
      });
      const dlg = el("dialog", { class: "dialog rg-cols-dialog" }, el("form", { method: "dialog" },
        el("h3", {}, MP.t("Columns in the list")),
        el("p", { class: "muted small" }, MP.t("Chosen for this browser. Drag the columns (or use the arrows) to change their order, left to right; you can also drag the column headers in the list.")),
        el("div", { class: "rg-cols-body" },
          el("div", {}, el("div", { class: "rg-cols-head" }, MP.t("Shown, in this order")), list),
          el("div", {}, el("div", { class: "rg-cols-head" }, MP.t("All columns")), el("div", { class: "rg-cols-grid" }, groups.filter(Boolean)))),
        el("div", { class: "dialog-actions" }, reset, makeDefault, el("span", { class: "rg-spacer" }), el("button", { class: "btn", value: "cancel" }, MP.t("Cancel")), el("button", { class: "btn btn-primary", value: "ok" }, MP.t("Show")))));
      document.body.append(dlg);
      dlg.addEventListener("close", () => {
        dlg.remove();
        if (dlg.returnValue !== "ok") return;
        if (order.join() === config.list.filter((k) => byKey[k]).join()) { try { localStorage.removeItem(COLS_KEY); } catch (_) { } setCols(config.list); draw(); }
        else saveCols(order);
      });
      dlg.showModal();
    });
    drawPanel();
    if (Object.values(S.adv).some((v) => v !== "")) { panel.hidden = false; fbtn.classList.add("active"); fbtn.setAttribute("aria-expanded", "true"); }
    draw();
  }

  // =============================================================================== one reagent
  function slotsOf(fields) {
    const by = {};
    for (const f of fields) if (f.slot) (by[f.slot] ||= []).push(f);
    return Object.keys(by).map(Number).sort((a, b) => a - b).map((n) => ({ n, fields: by[n] }));
  }
  const slotUsed = (item, s) => s.fields.some((f) => !empty(item[f.key]) && !(f.type === "bool" && item[f.key] === false));

  // C6H6O → C₆H₆O (subscript numbers; "(C12H18O9)n" too)
  function formula(v) {
    const out = el("span", { class: "rg-formula" });
    String(v).split(/(\d+|(?<=\))n)/).forEach((part, i) => { if (part) out.append(i % 2 ? el("sub", {}, part) : document.createTextNode(part)); });
    return out;
  }
  const GHS_KEY = /^ghs(0\d)_/;

  async function itemView() {
    const box = $("#rg-one");
    let d;
    try { d = await api(`${API}/${encodeURIComponent(RID)}`); } catch (err) { put(box, errorBox(err)); return; }
    const { item, fields, history, info } = d;
    CATS = Object.fromEntries((d.categories || []).map((c) => [c.code, c]));
    MP.rgCurrent = item;
    const infoText = $("#rg-info-btn-text"); if (infoText) infoText.textContent = W().infoThis;
    document.title = `${title(item)} · ${W().space} · MISTER PLIS`;
    const crumb = $("#rg-crumb-name"); if (crumb) crumb.textContent = title(item);
    let showEmpty = false;
    const value = (f) => {
      const v = item[f.key];
      if (empty(v)) return el("span", { class: "muted" }, "—");
      if (f.key === "storage_category_primary") return el("span", {}, catBadge(v), " ", CATS[v] ? CATS[v].name : "");
      if (f.key === "storage_categories") return el("span", { class: "rg-cats" }, vals(f, v).map((c) => el("span", {}, catBadge(c), " ", CATS[c] ? CATS[c].name : "")));
      if (f.type === "url") return extLink(v, v);
      if (f.type === "multi") return el("span", { class: "rg-tags" }, vals(f, v).map((x) => el("span", { class: "rg-tag" }, x)));
      if (f.type === "longtext") return el("div", { class: "rg-pre" }, show(f, v));
      if (f.type === "choice" || (CONS && ["category", "used_for", "storage_place"].includes(f.key))) return el("a", { class: "link", href: `${BASE}?f.${encodeURIComponent(f.key)}=${encodeURIComponent(v)}`, title: W().sameValue }, v);
      return show(f, v);
    };
    // shown in the head, so not repeated below
    const HEAD_FACTS = CONS ? ["category", "size_spec", "storage_place"] : [];
    const inHead = new Set(["label_no", "item_no", "name_pl", "name_en", "formula", "molar_mass_g_mol", "purity_percent", "storage_category_primary", ...HEAD_FACTS]);
    const real = fields.filter((f) => !f.virtual && !f.hidden);
    const ghsFields = real.filter((f) => GHS_KEY.test(f.key) && f.type === "bool");
    function sections() {
      return GROUPS().map(([g, gname]) => {
        const fs = real.filter((f) => (f.group || "other") === g && !inHead.has(f.key) && !GHS_KEY.test(f.key));
        if (!fs.length) return null;
        if (g === "producers") {
          const slots = slotsOf(fs).filter((s) => slotUsed(item, s));
          if (!slots.length) return showEmpty ? el("section", { class: "panel rg-sec" }, el("h3", {}, gname), el("p", { class: "muted pad" }, "—")) : null;
          const cols = slots[0].fields.filter((f) => showEmpty || f.slot_key === "opened_date" || slots.some((s) => { const sf = s.fields.find((x) => x.slot_key === f.slot_key); return sf && !empty(item[sf.key]); }));
          return el("section", { class: "panel rg-sec" }, el("h3", {}, gname), el("div", { class: "rg-slots-wrap" }, el("table", { class: "data rg-slots" },
            el("thead", {}, el("tr", {}, el("th", {}, "#"), cols.map((f) => el("th", {}, slotLabel(f))))),
            el("tbody", {}, slots.map((s) => el("tr", {}, el("td", { class: "muted" }, s.n), cols.map((c) => {
              const f = s.fields.find((x) => x.slot_key === c.slot_key);
              const v = f ? item[f.key] : null;
              const d = f ? bottleDate(f, v, item) : null;
              if (d !== null) return el("td", {}, d);
              if (f && f.type === "url" && !empty(v)) return el("td", {}, extLink(v));
              if (f && f.slot_key === "notes" && !empty(v)) return el("td", { class: "rg-slot-note" }, show(f, v));
              return el("td", {}, f ? (f.type === "bool" ? (v === true ? el("b", { class: f.slot_key === "to_order" || f.slot_key === "avoid" ? "rg-warn" : "" }, MP.t("yes")) : v === false ? el("span", { class: "muted" }, MP.t("no")) : "") : show(f, v)) : "");
            })))))));
        }
        // "no" is left out too (not disposed, not borrowed…) unless empty fields are shown
        const shownFs = fs.filter((f) => showEmpty || !(empty(item[f.key]) || (f.type === "bool" && item[f.key] === false)));
        if (!shownFs.length) return null;
        return el("section", { class: "panel rg-sec" }, el("h3", {}, gname),
          el("dl", { class: "rg-cells" }, shownFs.map((f) => el("div", { class: `rg-cell${f.type === "longtext" ? " is-wide" : ""}` },
            el("dt", { title: f.help || "" }, label(f)), el("dd", {}, value(f))))));
      });
    }
    function expiryBadge(r) {
      const st = slotsOf(real).filter((s) => slotInUse(r, s.n)).map((s) => expiryState(r[`producer_${s.n}_expiry_date`]));
      if (st.includes("expired")) return el("span", { class: "rg-badge rg-badge-expired" }, MP.t("expired"));
      if (st.includes("soon")) return el("span", { class: "rg-badge rg-badge-soon" }, MP.t("expires soon"));
      return null;
    }
    const slotsOrder = slotsOf(real).filter((s) => item[`producer_${s.n}_to_order`] || item[`producer_${s.n}_ordered`]);
    const restock = slotsOrder.length ? el("div", { class: `rg-restock-card rg-restock-${item.restock}` }, MP.icon("cart", 18),
      el("div", {}, slotsOrder.map((s) => el("div", {}, el("b", {}, item[`producer_${s.n}_ordered`] ? MP.t("Ordered") : MP.t("To order")),
        " · ", item[`producer_${s.n}_name`] || W().producern(s.n), item[`producer_${s.n}_order_amount`] ? ` · ${item[`producer_${s.n}_order_amount`]}` : "")),
        item.order_note ? el("div", { class: "muted" }, item.order_note) : null,
        item.order_requested_by ? el("div", { class: "muted small" }, MP.t("marked by {name}", { name: item.order_requested_by }), item.order_requested_date ? ` · ${item.order_requested_date}` : "") : null)) : null;
    // names, formula, molar mass, category and pictograms: the head
    const other = MP.prefs.lang === "pl" ? item.name_en : item.name_pl;
    const on = ghsFields.filter((f) => item[f.key] === true);
    const ghsUnknown = ghsFields.length && ghsFields.every((f) => empty(item[f.key]));
    const fact = (lab, v) => el("div", { class: "rg-fact" }, el("span", { class: "rg-fact-label" }, lab), el("span", { class: "rg-fact-value" }, v));
    const facts = el("div", { class: "rg-facts" },
      !empty(item.formula) ? fact(MP.t("Formula"), formula(item.formula)) : null,
      !empty(item.molar_mass_g_mol) ? fact(MP.t("Molar mass"), el("span", {}, MP.num(item.molar_mass_g_mol), el("small", {}, " g/mol"))) : null,
      !empty(item.purity_percent) ? fact(MP.t("Purity"), el("span", {}, MP.num(item.purity_percent), el("small", {}, " %"))) : null,
      !empty(item.storage_category_primary) ? fact(MP.t("Category"), el("span", {}, catBadge(item.storage_category_primary), " ", CATS[item.storage_category_primary] ? CATS[item.storage_category_primary].name : "")) : null,
      ...HEAD_FACTS.map((k) => fields.find((f) => f.key === k)).filter((f) => f && !empty(item[f.key])).map((f) => fact(label(f), show(f, item[f.key]))));
    const pictos = ghsFields.length ? el("div", { class: "rg-pictos" },
      on.length ? on.map((f) => el("figure", {}, ghsPicto(GHS_KEY.exec(f.key)[1], label(f), 72), el("figcaption", {}, label(f).replace(/^GHS0\d\s*/, ""))))
        : el("span", { class: "muted small" }, ghsUnknown ? MP.t("Pictograms not known yet") : MP.t("No GHS pictograms")),
      item.ghs_verified === true ? el("span", { class: "rg-verified" }, MP.icon("check", 14), MP.t("checked on the label")) : null) : null;
    const body = el("div");
    const toggle = el("button", { type: "button", class: "btn btn-small" });
    function drawBody() { put(body, sections()); put(toggle, showEmpty ? MP.t("Hide empty fields") : MP.t("Show empty fields")); }
    toggle.addEventListener("click", () => { showEmpty = !showEmpty; drawBody(); });
    put(box,
      el("div", { class: "rg-item-top" },
        el("div", { class: "rg-item-head" },
          el("div", { class: "rg-item-names" },
            el("h2", { class: "rg-item-name" }, el("span", { class: "rg-label-no", title: MP.t("Label no.") }, `#${item.id}`), " ", title(item)),
            other && other !== title(item) ? el("div", { class: "rg-item-other" }, other) : null,
            el("div", { class: "rg-item-badges" },
              item.is_disposed === true ? el("span", { class: "rg-badge rg-badge-disposed" }, W().disposed, item.disposed_date ? ` ${item.disposed_date}` : "") : null,
              expiryBadge(item),
              item.is_borrowed === true ? el("span", { class: "rg-badge rg-badge-borrowed" }, MP.t("borrowed"), item.borrowed_by ? ` · ${item.borrowed_by}` : "") : null,
              avoidBadge(item))),
          el("div", { class: "rg-item-actions" },
            el("a", { class: "btn btn-small", href: BASE + (document.referrer.includes(`${BASE}?`) ? new URL(document.referrer).search : "") }, MP.icon("chevron-left", 14), MP.t("Back to the list")),
            toggle,
            item.is_disposed === true ? null : orderButton(item, () => itemView()),
            // the solution calculator with this reagent's name, molar mass and purity filled in (calculator.py)
            d.calculator ? el("a", { class: "btn btn-small", href: d.calculator, title: MP.t("Open the solution calculator with this reagent's name, molar mass and purity filled in") },
              MP.icon("beaker", 14), MP.t("Make a solution")) : null,
            CONS ? null : el("button", { type: "button", class: "btn btn-small", title: MP.t("Label for a portion in a new container"), onclick: () => labelDialog(item, ghsFields) }, MP.icon("tag", 14), MP.t("Label…")),
            el("a", { class: "btn btn-primary btn-small", href: `${BASE}/${item.id}/edit` }, MP.icon("edit", 14), MP.t("Edit")))),
        el("div", { class: "rg-item-facts" }, facts, pictos)),
      restock, body,
      infoList(info, W().infoAbout, false),
      history.length ? el("details", { class: "panel rg-hist" }, el("summary", {}, MP.icon("clock", 15), MP.tn(history.length, "{n} change", "{n} changes")),
        el("ul", { class: "rg-hist-list" }, history.map((c) => el("li", {}, el("span", { class: "muted" }, MP.datetime(c.at)), " ", el("b", {}, c.author), " — ", c.subject)))) : null);
    drawBody();
    if (!itemView.keys) {
      itemView.keys = true;
      document.addEventListener("keydown", (e) => { if (e.key === "e" && !e.target.closest("input, textarea, select, [contenteditable]") && !e.metaKey && !e.ctrlKey && !document.querySelector("dialog[open]")) location.href = `${BASE}/${item.id}/edit`; });
    }
  }

  // =============================================================================== edit view
  async function editView() {
    const box = $("#rg-one");
    let item = {}, fields, items = [], config;
    try {
      const all = await api(API);
      fields = all.fields.filter((f) => !f.virtual && !f.hidden); items = all.items; config = all.config; counts(all);
      if (!all.ready) { notReady(box); return; }
      if (RID) item = (await api(`${API}/${encodeURIComponent(RID)}`)).item;
    } catch (err) { put(box, errorBox(err)); return; }
    MP.rgCurrent = RID ? item : null;
    const crumb = $("#rg-crumb-name"); if (crumb) crumb.textContent = RID ? `${title(item)} — ${MP.t("edit")}` : W().newOne;
    document.title = `${RID ? title(item) : W().newOne} · ${W().space} · MISTER PLIS`;
    const read = {};
    let dirty = false;
    const nameKey = config.title.pl;

    function control(f) {
      const v = item[f.key];
      const id = `rg-f-${f.key}`;
      if (f.key === config.key) return el("div", { class: "rg-fixed" }, RID ? `#${v}` : MP.t("the next free number"));
      if (f.type === "longtext") {
        const ta = el("textarea", { id, rows: 3 }, v ?? ""); read[f.key] = () => ta.value;
        return el("div", { class: "control" }, ta);
      }
      if (f.type === "bool") {
        const s = el("select", { id }, el("option", { value: "" }, MP.t("— not known —")), el("option", { value: "true" }, MP.t("yes")), el("option", { value: "false" }, MP.t("no")));
        s.value = v === true ? "true" : v === false ? "false" : "";
        read[f.key] = () => (s.value === "" ? null : s.value === "true");
        return el("div", { class: "control rg-bool" }, s);
      }
      if (f.type === "multi") {
        const have = new Set(vals(f, v));
        if (f.options) {
          const opts = [...new Set([...f.options, ...have])];
          const boxes = opts.map((o) => { const cb = el("input", { type: "checkbox", value: o }); cb.checked = have.has(o); return el("label", { class: "rg-opt" }, cb, el("span", {}, f.key === "storage_categories" ? catBadge(o) : o, f.key === "storage_categories" && CATS[o] ? ` ${CATS[o].name}` : "")); });
          read[f.key] = () => boxes.map((b) => b.firstChild).filter((c) => c.checked).map((c) => c.value);
          return el("div", { class: "rg-opts", id }, boxes);
        }
        const other = el("input", { type: "text", id, value: [...have].join(";"), placeholder: MP.t("separated by ;") });
        read[f.key] = () => other.value.split(";").map((s) => s.trim()).filter(Boolean);
        return el("div", { class: "control" }, other);
      }
      if (f.type === "choice" && f.options) {
        const s = el("select", { id }, el("option", { value: "" }, "—"), f.options.map((o) => el("option", { value: o }, f.key === "storage_category_primary" && CATS[o] ? `${o} — ${CATS[o].name}` : o)));
        s.value = v ?? "";
        read[f.key] = () => s.value;
        return el("div", { class: "control" }, s);
      }
      const input = el("input", { id, type: f.type === "url" ? "url" : "text", value: empty(v) ? "" : (f.type === "number" ? MP.num(v) : String(v)) });
      if (f.type === "number") input.inputMode = "decimal";
      if (f.type === "date") input.placeholder = MP.t("yyyy-mm-dd");
      read[f.key] = () => input.value;
      if (f.slot_key === "opened_date") {
        input.placeholder = MP.t("not opened");
        const now = el("button", { type: "button", class: "btn btn-small", title: MP.t("Opened today") }, MP.t("today"));
        now.addEventListener("click", () => { input.value = today(); input.focus(); });
        return el("div", { class: "control rg-date-today" }, input, now);
      }
      if (f.type === "text" && (["name", "supplier", "container_unit"].includes(f.slot_key) || /^(storage_place|borrowed_by|order_requested_by|category|used_for)$/.test(f.key))) {
        const listId = `${id}-list`;
        // the values typed so far (for a producer: in any of its slots), to keep one spelling
        const pool = f.slot ? [...new Set(items.flatMap((r) => Array.from({ length: SLOTS }, (_, i) => r[`producer_${i + 1}_${f.slot_key}`]).filter((x) => !empty(x)).map(String)))]
          : valuesOf(items, f).map(([x]) => x);
        input.setAttribute("list", listId);
        return el("div", { class: "control" }, input, el("datalist", { id: listId }, pool.map((x) => el("option", { value: x }))));
      }
      return el("div", { class: "control" }, input);
    }
    const fieldBox = (f, lab) => el("div", { class: `field rg-field rg-field-${f.type}`, title: f.help || null },
      el("label", { class: "field-label", for: `rg-f-${f.key}` }, lab || label(f), f.key === nameKey ? el("span", { class: "opt" }, MP.t("required")) : null), control(f));

    const sections = GROUPS().map(([g, gname]) => {
      const fs = fields.filter((f) => (f.group || "other") === g);
      if (!fs.length) return null;
      if (g === "producers") {
        const slots = slotsOf(fs);
        let used = slots.filter((s) => slotUsed(item, s)).map((s) => s.n);
        if (!used.length) used = [1];
        const cards = slots.map((s) => {
          const card = el("div", { class: "rg-slot" }, el("div", { class: "rg-slot-head" }, W().producerN(s.n)),
            el("div", { class: "rg-slot-grid" }, s.fields.map((f) => fieldBox(f, slotLabel(f)))));
          card.hidden = !used.includes(s.n);
          return card;
        });
        const add = el("button", { type: "button", class: "btn btn-small" }, MP.icon("plus", 14), W().another);
        add.addEventListener("click", () => { const next = cards.find((c) => c.hidden); if (next) next.hidden = false; if (!cards.some((c) => c.hidden)) add.hidden = true; });
        add.hidden = !cards.some((c) => c.hidden);
        const other = fs.filter((f) => !f.slot);
        return el("section", { class: "panel rg-sec rg-edit-sec" }, el("h3", {}, gname),
          other.length ? el("div", { class: "rg-edit-grid" }, other.map((f) => fieldBox(f))) : null,
          el("div", { class: "rg-slots-edit" }, cards), el("div", { class: "rg-slot-add" }, add));
      }
      return el("section", { class: "panel rg-sec rg-edit-sec" }, el("h3", {}, gname), el("div", { class: "rg-edit-grid" }, fs.map((f) => fieldBox(f))));
    });

    const save = el("button", { type: "submit", class: "btn btn-primary" }, MP.icon("check", 16), MP.t("Save"));
    const form = el("form", { class: "rg-edit", novalidate: true },
      el("div", { class: "rg-edit-head" }, el("h2", {}, RID ? MP.t("Edit {name}", { name: title(item) }) : W().newOne),
        el("span", { class: "muted small" }, MP.t("Every save is kept in the history, with your name."))),
      sections,
      el("div", { class: "rg-edit-actions" },
        RID ? el("button", { type: "button", class: "btn btn-danger", onclick: dispose }, MP.icon("trash", 15), item.is_disposed === true ? W().undispose : W().dispose) : el("span"),
        el("span", { class: "rg-spacer" }),
        el("a", { class: "btn", href: RID ? `${BASE}/${RID}` : BASE }, MP.t("Cancel")),
        save));
    form.addEventListener("input", () => { dirty = true; });
    form.addEventListener("change", () => { dirty = true; });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const values = {};
      for (const [k, fn] of Object.entries(read)) values[k] = fn();
      if (!String(values[nameKey] ?? item[nameKey] ?? "").trim()) { MP.toast(W().needsName); $(`#rg-f-${nameKey}`)?.focus(); return; }
      save.disabled = true;
      try {
        const rec = await api(RID ? `${API}/${RID}` : API, { json: { values, base: RID ? item._v : "" } });
        dirty = false;
        location.href = `${BASE}/${rec.id}`;
      } catch (err) { MP.toast(err.message, 7000); save.disabled = false; }
    });
    form.addEventListener("keydown", (e) => { if (e.key === "s" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); form.requestSubmit(); } });
    window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
    async function dispose() {
      const undo = item.is_disposed === true;
      const dlg = el("dialog", { class: "dialog" }, el("form", { method: "dialog" },
        el("h3", {}, undo ? W().undisposeQ(title(item)) : W().disposeQ(title(item))),
        el("p", {}, undo ? MP.t("It comes back to the list.") : W().disposeText),
        el("div", { class: "dialog-actions" }, el("button", { class: "btn", value: "cancel" }, MP.t("Cancel")), el("button", { class: "btn btn-primary", value: "ok" }, MP.t("OK")))));
      document.body.append(dlg);
      dlg.addEventListener("close", async () => {
        dlg.remove();
        if (dlg.returnValue !== "ok") return;
        try { await api(`${API}/${RID}/dispose`, { json: { undo } }); dirty = false; location.href = `${BASE}/${RID}`; } catch (err) { MP.toast(err.message, 5000); }
      });
      dlg.showModal();
    }
    put(box, form);
    if (!RID) $(`#rg-f-${nameKey}`)?.focus();
  }

  // =============================================================================== order list
  async function orderView() {
    const box = $("#rg-order");
    let data;
    try { data = await api(API); } catch (err) { put(box, errorBox(err)); return; }
    counts(data);
    if (!data.ready) { notReady(box); return; }
    const items = data.items.filter((r) => r.is_disposed !== true);
    const lines = [];
    for (const r of items) for (let n = 1; n <= SLOTS; n++) {
      const p = `producer_${n}_`;
      if (r[p + "to_order"] || r[p + "ordered"]) lines.push({ r, n, state: r[p + "ordered"] ? "ordered" : "needed", maker: (CONS && r[p + "supplier"]) || r[p + "name"] || "",
        brand: r[p + "name"] || "", url: r[p + "product_url"] || "", cat: r[p + "catalog_no"] || "",
        size: [r[p + "container_size"], r[p + "container_unit"]].filter((x) => !empty(x)).join(" "), amount: r[p + "order_amount"] || "", count: r[p + "containers_count"] });
    }
    const text = (l) => [title(l.r), l.r.size_spec, l.brand !== l.maker ? l.brand : "", l.maker, l.cat ? `${MP.t("cat.")} ${l.cat}` : "", l.size, l.amount ? `${MP.t("How much to order")}: ${l.amount}` : "", l.url, `#${l.r.id}`].filter(Boolean).join(" · ");

    async function setState(l, state, ask) {
      let amount, count;
      const head = `${title(l.r)}${l.maker ? ` · ${l.maker}` : ""}`;
      if (ask === "amount") { amount = await MP.ask(MP.t("How much to order"), l.amount || "", { title: head, ok: MP.t("Add to the list"), placeholder: W().amountHint }); if (amount === null) return; }
      if (ask === "count") { count = await MP.ask(W().howMany, empty(l.count) ? "" : String(l.count), { title: head, ok: MP.t("Arrived") }); if (count === null) return; }
      try { await api(`${API}/${l.r.id}/restock`, { json: { slot: l.n, state, amount, count } }); orderView(); } catch (err) { MP.toast(err.message, 6000); }
    }
    function section(state, heading, hint) {
      const list = lines.filter((l) => l.state === state);
      const groups = new Map();
      for (const l of list.sort((a, b) => MP.fold(title(a.r)).localeCompare(MP.fold(title(b.r))))) { if (!groups.has(l.maker)) groups.set(l.maker, []); groups.get(l.maker).push(l); }
      const keys = [...groups.keys()].sort((a, b) => (a === "") - (b === "") || a.localeCompare(b));
      return el("section", { class: `panel rg-order-sec rg-order-${state}` },
        el("div", { class: "panel-head" }, el("h2", {}, MP.icon("cart", 18), heading, el("span", { class: "rg-tab-n" }, list.length)),
          list.length && state === "needed" ? el("div", { class: "rg-order-tools" },
            el("button", { type: "button", class: "btn btn-small", onclick: async () => { const txt = keys.map((k) => `${k || W().noProducer}\n` + groups.get(k).map((l) => `- ${text(l)}`).join("\n")).join("\n\n"); if (await MP.copy(txt)) MP.toast(MP.t("Copied")); } }, MP.t("Copy as text")),
            MP.exportBtn("pdf", { href: `${API}/order.pdf`, title: MP.t("The list to order, grouped by producer, to print") }),
            MP.exportBtn("xlsx", { href: `${API}/order.xlsx` }),
            MP.exportBtn("csv", { href: `${API}/order.csv` })) : null),
        el("p", { class: "panel-text" }, hint),
        !list.length ? el("p", { class: "muted pad" }, state === "needed" ? W().nothing : MP.t("Nothing is waiting to arrive.")) :
          el("div", { class: "rg-order-groups" }, el("table", { class: "data rg-order-table" }, keys.map((k) => el("tbody", {},
            el("tr", { class: "rg-order-group" }, el("th", { colspan: 6 }, k || W().noProducer, el("span", { class: "muted" }, ` · ${groups.get(k).length}`))),
            groups.get(k).map((l) => el("tr", {},
              el("td", { class: "rg-order-name" }, el("a", { href: `${BASE}/${l.r.id}`, class: "rg-name-link" }, title(l.r)), el("span", { class: "muted small" }, ` #${l.r.id}`),
                CONS && l.r.size_spec ? el("span", { class: "muted small" }, ` · ${l.r.size_spec}`) : null,
                CONS && l.brand && l.brand !== l.maker ? el("div", { class: "muted small" }, l.brand) : null,
                l.r.order_note ? el("div", { class: "muted small" }, l.r.order_note) : null),
              el("td", {}, l.cat, l.url ? el("div", { class: "small" }, extLink(l.url)) : null),
              el("td", {}, l.size),
              el("td", { class: "rg-order-amount" }, l.amount || el("span", { class: "muted" }, MP.t("amount not given"))),
              el("td", { class: "muted small" }, l.r.order_requested_by ? `${l.r.order_requested_by}${l.r.order_requested_date ? ` · ${l.r.order_requested_date}` : ""}` : ""),
              el("td", { class: "rg-order-act" }, el("div", {}, state === "needed"
                ? el("button", { type: "button", class: "btn btn-small", onclick: () => setState(l, "ordered") }, MP.icon("check", 14), MP.t("Ordered"))
                : el("button", { type: "button", class: "btn btn-small", onclick: () => setState(l, "", "count") }, MP.icon("check", 14), MP.t("Arrived")),
                el("button", { type: "button", class: "icon-btn icon-btn-sm", title: MP.t("Take off the list"), "aria-label": MP.t("Take off the list"), onclick: () => setState(l, "") }, MP.icon("x", 14)))))))))));
    }
    const finder = el("input", { type: "search", placeholder: W().find, autocomplete: "off" });
    const hits = el("div", { class: "rg-finder-hits" });
    finder.addEventListener("input", () => {
      const w = MP.fold(finder.value).split(/\s+/).filter(Boolean);
      if (!w.length) { put(hits); return; }
      const found = items.filter((r) => { const t = MP.fold([title(r), r.name_en, r.cas_no, r.category, r.size_spec, ...(r._producers || [])].join(" ")); return w.every((x) => t.includes(x) || r.id === x.replace(/^#/, "")); }).slice(0, 8);
      const opts = found.flatMap((r) => {
        const used = [];
        for (let n = 1; n <= SLOTS; n++) if (r[`producer_${n}_name`]) used.push(n);
        return (used.length ? used : [1]).map((n) => ({ r, n, maker: r[`producer_${n}_name`] || "", amount: r[`producer_${n}_order_amount`] || "",
          cat: r[`producer_${n}_catalog_no`] || "", state: r[`producer_${n}_ordered`] ? "ordered" : r[`producer_${n}_to_order`] ? "needed" : "" }));
      });
      put(hits, ...opts.map((l) => el("button", { type: "button", class: "rg-finder-hit", onclick: () => setState(l, "needed", "amount") },
        el("b", {}, title(l.r)), el("span", { class: "muted" }, [`#${l.r.id}`, l.r.size_spec, l.maker || W().producern(l.n), l.cat].filter(Boolean).join(" · ")), restockBadge(l.state))),
        opts.length ? null : el("span", { class: "muted pad" }, MP.t("Nothing matches.")));
    });
    put(box,
      section("needed", MP.t("To order"), W().grouped),
      el("div", { class: "panel rg-finder" }, el("label", { class: "job-search" }, MP.icon("search", 16), finder), hits),
      section("ordered", MP.t("Ordered, waiting to arrive"), MP.t("Ordered but not here yet.")));
  }

  // =============================================================================== info from the lab
  function infoList(items, heading, full) {
    if (!items.length && !full) return null;
    const card = (i) => el("article", { class: `rg-info-item${i.status === "done" ? " is-done" : ""}` },
      el("div", { class: "rg-info-meta" },
        el("b", {}, i.user || MP.t("someone")), el("span", { class: "muted" }, ` · ${MP.datetime(i.created)}`),
        i.reagent ? el("span", {}, " · ", el("a", { class: "link", href: `/reagents/${i.reagent}` }, `#${i.reagent} ${i.reagent_name || ""}`)) : null,
        i.consumable ? el("span", {}, " · ", el("a", { class: "link rg-info-cons", href: `/consumables/${i.consumable}`, title: MP.t("Consumables") }, MP.icon("box", 13), `#${i.consumable} ${i.consumable_name || ""}`)) : null,
        i.status === "done" ? el("span", { class: "chip chip-live" }, MP.t("dealt with")) : null,
        i.agent_note ? el("span", { class: "chip" }, MP.t("question from the agent")) : null,
        el("span", { class: "rg-spacer" }),
        el("button", { type: "button", class: "btn btn-small", onclick: async () => { try { await api(`${INFO_API}/${i.id}`, { json: { status: i.status === "done" ? "new" : "done" } }); reload(); } catch (err) { MP.toast(err.message, 5000); } } },
          i.status === "done" ? MP.t("Reopen") : MP.t("Dealt with")),
        full ? el("button", { type: "button", class: "icon-btn icon-btn-sm", title: MP.t("Delete"), "aria-label": MP.t("Delete"), onclick: async () => { if (!confirm(MP.t("Delete this info?"))) return; try { await api(`${INFO_API}/${i.id}`, { method: "DELETE" }); reload(); } catch (err) { MP.toast(err.message, 5000); } } }, MP.icon("trash", 14)) : null),
      el("div", { class: "rg-pre" }, i.text),
      i.agent_note ? el("div", { class: "rg-agent-note" }, MP.icon("info", 14), i.agent_note) : null);
    return el("section", { class: "rg-info-list" }, heading ? el("h3", { class: "rg-sub" }, MP.icon("info", 16), heading) : null, items.map(card));
  }
  function reload() { if (VIEW === "info") infoView(); else if (VIEW === "item") itemView(); }
  async function infoView() {
    const box = $("#rg-infos");
    let d, all;
    try { [d, all] = await Promise.all([api(INFO_API), api(API)]); } catch (err) { put(box, errorBox(err)); return; }
    counts(all);
    let want = "open";
    try { want = sessionStorage.getItem("mp:rg-info-show") || "open"; } catch (_) { }
    const open = d.items.filter((i) => i.status !== "done");
    const shown = want === "open" ? open : want === "done" ? d.items.filter((i) => i.status === "done") : d.items;
    const seg = el("div", { class: "seg seg-small" }, [["open", MP.t("Not dealt with")], ["done", MP.t("Dealt with")], ["all", MP.t("All")]].map(([v, t]) =>
      el("button", { type: "button", class: want === v ? "active" : "", onclick: () => { try { sessionStorage.setItem("mp:rg-info-show", v); } catch (_) { } infoView(); } }, t)));
    put(box,
      el("div", { class: "rg-info-intro panel" },
        el("p", {}, MP.t("What people noticed — things moved, running low, walks round the lab. The records are corrected from it later, by hand or by an agent; mark each one as dealt with when it is done."),
          " ", el("span", { class: "muted" }, MP.t("One list for the reagents and the consumables."))),
        el("div", { class: "rg-info-tools" }, seg,
          el("button", { type: "button", class: "btn btn-small btn-primary", onclick: () => $("#rg-info-btn").click() }, MP.icon("plus", 14), MP.t("Add info")),
          el("button", { type: "button", class: "btn btn-small", disabled: !open.length, onclick: async () => { const t = await (await fetch(`${INFO_API}.md`)).text(); if (await MP.copy(t)) MP.toast(MP.t("Copied — paste it to whoever corrects the records")); } },
            MP.t("Copy the open ones as Markdown")))),
      shown.length ? infoList(shown, "", true) : el("p", { class: "muted pad" }, want === "open" ? MP.t("Nothing waiting — everything has been dealt with.") : MP.t("Nothing here yet.")));
  }

  // =============================================================================== the "Add info" button (Reagents and Consumables pages only)
  (function infoButton() {
    const btn = $("#rg-info-btn"), pop = $("#rg-info-pop"), form = $("#rg-info-form"), text = $("#rg-info-text"), send = $("#rg-info-send");
    if (!btn || !pop) return;
    const DRAFT = "mp:rg-info-draft";
    const about = () => (VIEW === "item" || VIEW === "edit") && MP.rgCurrent ? MP.rgCurrent : null;
    function place() {
      const r = btn.getBoundingClientRect();
      const w = Math.min(520, window.innerWidth - 24);
      const left = Math.max(12, Math.min(window.innerWidth - w - 12, r.left + r.width / 2 - w / 2));
      Object.assign(pop.style, { width: `${w}px`, left: `${left}px`, top: `${r.bottom + 12}px` });
      pop.style.setProperty("--fb-tip", `${r.left + r.width / 2 - left}px`);
    }
    function open() {
      if (!pop.hidden) return;
      const a = about();
      $("#rg-info-title").textContent = a ? MP.t("Info about {name}", { name: `#${a.id} ${title(a)}` }) : W().infoAll;
      const name = MP.prefs.name;
      put($("#rg-info-who"), name ? MP.t("Sent as {name}", { name }) : el("span", {}, MP.t("Sent without a name"), " · ", el("a", { class: "link", href: "/settings#you" }, MP.t("add yours"))));
      try { if (!text.value) text.value = localStorage.getItem(DRAFT) || ""; } catch (_) { }
      place();
      pop.classList.remove("is-sent");
      pop.hidden = false; btn.setAttribute("aria-expanded", "true"); btn.classList.add("on");
      requestAnimationFrame(() => pop.classList.add("is-open"));
      setTimeout(() => text.focus(), 60);
    }
    function close() {
      if (pop.hidden) return;
      pop.classList.remove("is-open"); btn.setAttribute("aria-expanded", "false"); btn.classList.remove("on");
      setTimeout(() => { if (!pop.classList.contains("is-open")) pop.hidden = true; }, 180);
    }
    btn.addEventListener("click", () => (pop.hidden ? open() : close()));
    $("#rg-info-close").addEventListener("click", close);
    text.addEventListener("input", () => { try { localStorage.setItem(DRAFT, text.value); } catch (_) { } });
    text.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); form.requestSubmit(); } });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) { close(); btn.focus(); } });
    document.addEventListener("pointerdown", (e) => { if (!pop.hidden && !pop.contains(e.target) && !btn.contains(e.target)) close(); });
    window.addEventListener("resize", () => { if (!pop.hidden) place(); });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!text.value.trim()) { text.focus(); MP.toast(MP.t("Write a few words first.")); return; }
      send.disabled = true;
      const a = about();
      try {
        await api(INFO_API, { json: { text: text.value, [CONS ? "consumable" : "reagent"]: a ? a.id : "", page: location.pathname + location.search } });
        text.value = ""; try { localStorage.removeItem(DRAFT); } catch (_) { }
        pop.classList.add("is-sent");
        setTimeout(close, 1500);
        const n = $("#rg-n-info"); if (n) { n.hidden = false; n.textContent = String((parseInt(n.textContent, 10) || 0) + 1); }
        if (VIEW === "info" || VIEW === "item") setTimeout(reload, 300);
      } catch (err) { MP.toast(err.message, 5000); }
      send.disabled = false;
    });
  })();

  ({ list: listView, item: itemView, edit: editView, order: orderView, info: infoView }[VIEW] || listView)();
})();
