// Reagent labels for the lab's Brother P-touch printer, made from the protocol: every result in it from a tool
// that offers labels (Molar solution, Stock solution …) becomes one label, plus any extra ones typed in. They
// print as one strip of tape; tape, resolution and cutting can be changed for one print (defaults: Settings →
// Exports & printing). Edits are kept with the protocol in this browser.
// Also drives the "Label printer" panel on Settings → Exports & printing.
(function () {
  const { el, icon } = MP;
  const MAX_COPIES = 20;

  async function postPng(url, body) {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) {
      let msg = `${res.status} ${res.statusText}`;
      try { const d = await res.json(); msg = d.error || d.detail || msg; } catch (_) { /* not json */ }
      throw new Error(msg);
    }
    return res.blob();
  }

  const printerText = (p) => p && p.address
    ? MP.t("Printer: {address}", { address: p.address })
    : MP.t("No label printer set up yet — add it in Settings → Exports & printing. You can still download the PNG.");
  const OPTION_KEYS = ["tape_mm", "hires", "half_cut", "auto_cut", "chain"];

  // a row of toggle buttons; pick(value) on click
  function seg(choices, current, pick) {
    const box = el("div", { class: "seg seg-small", role: "radiogroup" });
    const draw = (value) => box.querySelectorAll("button").forEach((b, i) => {
      const on = choices[i][0] === value;
      b.classList.toggle("active", on); b.setAttribute("aria-checked", on ? "true" : "false");
    });
    choices.forEach(([value, text]) => box.append(el("button", { type: "button", role: "radio", onclick: () => { draw(value); pick(value); } }, text)));
    draw(current);
    return box;
  }

  // Default text for protocol items that don't have their label yet (asked from the tool).
  async function fillDefaults(d) {
    const todo = d.items.filter((it) => it.labelable && !it.label);
    await Promise.all(todo.map(async (it) => {
      try {
        const r = await MP.api(`/api/tools/${it.tool_id}/label`, { json: { params: it.params || {} } });
        it.label = { name: r.fields.name || "", detail: r.fields.detail || "", copies: 1, include: true };
      } catch (_) { it.labelable = false; }  // the tool no longer offers labels
    }));
    if (todo.length) MP.protocol.save(d);
  }

  MP.labelStrip = async function () {
    let d = MP.protocol.load();
    let printer;
    try { [printer] = await Promise.all([MP.api("/api/label/printer"), fillDefaults(d)]); }
    catch (e) { MP.toast(e.message, 4000); return; }
    d = MP.protocol.load();
    const common = { person: MP.prefs.name || "", logo: true, ...(d.labels || {}) };
    const opts = Object.fromEntries(OPTION_KEYS.map((k) => [k, printer[k]]));  // this print only
    if (!common.date_fixed) common.date = MP.date(new Date());  // today, unless typed in

    const store = () => { const x = MP.protocol.load(); x.items = d.items; x.extra_labels = d.extra_labels; x.labels = common; MP.protocol.save(x); };
    const strip = () => {
      const out = [];
      const add = (lb) => {
        if (lb.include === false) return;
        const n = Math.min(MAX_COPIES, Math.max(1, Math.round(Number(lb.copies)) || 1));
        for (let i = 0; i < n; i++) out.push({ name: lb.name, detail: lb.detail, person: common.person, date: common.date, logo: common.logo });
      };
      d.items.filter((it) => it.labelable && it.label).forEach((it) => add(it.label));
      d.extra_labels.forEach(add);
      return out;
    };

    const img = el("img", { alt: MP.t("Preview of the label strip") });
    const err = el("div", { class: "label-error", hidden: true });
    const size = el("div", { class: "muted label-size" });
    let url = null, blob = null, timer = null, seq = 0;
    // the preview has 720 pixels per inch along the tape, in either print resolution
    img.addEventListener("load", () => {
      const n = strip().filter((l) => l.name || l.detail).length;
      size.textContent = MP.tn(n, "{n} label", "{n} labels") + " · " + MP.t("≈ {cm} cm of {mm} mm tape", { cm: MP.num(Number((img.naturalWidth / 720 * 2.54).toFixed(1))), mm: opts.tape_mm });
    });
    const printBtn = el("button", { type: "button", class: "btn btn-primary", disabled: true }, icon("tag", 14), MP.t("Print"));
    const refresh = async () => {
      const mine = ++seq;
      try {
        const b = await postPng("/api/label/preview.png", { labels: strip(), options: opts });
        if (mine !== seq) return;
        blob = b;
        if (url) URL.revokeObjectURL(url);
        url = URL.createObjectURL(b);
        img.src = url; img.hidden = false; err.hidden = true;
      } catch (e) {
        if (mine !== seq) return;
        blob = null; img.hidden = true; err.hidden = false; err.textContent = e.message; size.textContent = "";
      }
      printBtn.disabled = !printer.address || !blob;
    };
    const changed = () => { store(); clearTimeout(timer); timer = setTimeout(refresh, 200); };

    const input = (obj, key, attrs = {}) => {
      const i = el("input", { type: attrs.type || "text", value: obj[key] ?? "", maxlength: attrs.maxlength || 80, placeholder: attrs.placeholder || "",
        spellcheck: "false", min: attrs.min, max: attrs.max, "aria-label": attrs.label });
      i.addEventListener("input", () => { obj[key] = attrs.type === "number" ? Number(i.value) : i.value; if (attrs.onInput) attrs.onInput(); changed(); });
      return el("div", { class: "control" }, i);
    };
    const check = (obj, key, title) => {
      const c = el("input", { type: "checkbox", checked: obj[key] !== false, title, "aria-label": title });
      c.addEventListener("change", () => { obj[key] = c.checked; changed(); });
      return c;
    };
    const fields = (lb) => el("div", { class: "label-row-inputs" },
      input(lb, "name", { placeholder: MP.t("Reagent"), label: MP.t("Reagent") }),
      input(lb, "detail", { placeholder: MP.t("Concentration"), label: MP.t("Concentration") }),
      el("label", { class: "label-copies", title: MP.t("Number of copies") }, "×", input(lb, "copies", { type: "number", min: 1, max: MAX_COPIES, label: MP.t("Copies") })));

    const rows = el("div", { class: "label-rows" });
    const drawRows = () => {
      const lines = [];
      d.items.forEach((it, i) => {
        if (!it.labelable || !it.label) return;
        lines.push(el("div", { class: "label-row" },
          check(it.label, "include", MP.t("Print this label")),
          el("div", { class: "label-row-main" },
            el("div", { class: "label-row-from muted", title: it.summary || "" }, `${i + 1}. ${it.heading || MP.t(it.tool_name)}${it.summary ? " — " + it.summary : ""}`),
            fields(it.label))));
      });
      d.extra_labels.forEach((lb, i) => {
        lines.push(el("div", { class: "label-row" },
          el("button", { type: "button", class: "icon-btn", title: MP.t("Remove this label"), onclick: () => { d.extra_labels.splice(i, 1); drawRows(); changed(); } }, icon("x", 16)),
          el("div", { class: "label-row-main" }, el("div", { class: "label-row-from muted" }, MP.t("Extra label")), fields(lb))));
      });
      if (!lines.length) lines.push(el("p", { class: "muted" }, MP.t("Nothing in this protocol has a label yet — add results from Molar or Stock solution, or an extra label.")));
      rows.replaceChildren(...lines);
    };
    drawRows();

    const onOff = (key) => seg([[true, MP.t("On")], [false, MP.t("Off")]], opts[key], (v) => { opts[key] = v; changed(); });
    const option = (title, help, control) => el("div", { class: "label-option", title: help }, el("span", { class: "field-label" }, title), control);
    const options = el("details", { class: "label-options" },
      el("summary", {}, MP.t("Print options")),
      el("div", { class: "label-options-grid" },
        option(MP.t("Tape width"), MP.t("When printing, the label is drawn for the tape that is actually in the printer."),
          seg(printer.tape_choices.map((t) => [t, `${t} mm`]), opts.tape_mm, (v) => { opts.tape_mm = v; changed(); })),
        option(MP.t("Print resolution"), "", seg([[true, MP.t("High")], [false, ((MP.i18n || {})["printer::Standard"] || "Standard")]], opts.hires, (v) => { opts.hires = v; changed(); })),
        option(MP.t("Half cut"), MP.t("Cuts the tape between labels but not its backing."), onOff("half_cut")),
        option(MP.t("Auto cut"), MP.t("Cuts right through: after the whole strip when half cut is on, otherwise after each label."), onOff("auto_cut")),
        option(MP.t("Chain printing"), MP.t("The end of the strip stays in the printer — cut it with the printer's button."), onOff("chain"))),
      el("p", { class: "muted label-options-note" }, MP.t("For this print only — the defaults are in Settings → Exports & printing.")));

    const download = el("button", { type: "button", class: "btn" }, icon("download", 14), "PNG");
    download.addEventListener("click", () => {
      if (!blob) return;
      const a = el("a", { href: url, download: `labels_${(d.title || "protocol").replace(/[^\p{L}\p{N}.-]+/gu, "-")}.png` });
      document.body.append(a); a.click(); a.remove();
    });
    printBtn.addEventListener("click", async () => {
      const n = strip().filter((l) => l.name || l.detail).length;
      if (n > 1 && !confirm(MP.tn(n, "Print {n} label on one strip?", "Print {n} labels on one strip?"))) return;
      printBtn.disabled = true;
      try { const r = await MP.api("/api/label/print", { json: { labels: strip(), options: opts } }); MP.toast(r.message, 3500); }
      catch (e) { MP.toast(e.message, 5000); }
      finally { printBtn.disabled = !printer.address || !blob; }
    });

    const dlg = el("dialog", { class: "dialog label-dialog" },
      el("form", { method: "dialog" },
        el("h3", {}, MP.t("Labels")),
        el("div", { class: "label-preview" }, img, err, size),
        el("div", { class: "label-common" },
          el("label", { class: "label-field" }, el("span", { class: "field-label" }, MP.t("Person")), input(common, "person", { maxlength: 60 })),
          el("label", { class: "label-field" }, el("span", { class: "field-label" }, MP.t("Date")), input(common, "date", { maxlength: 30, onInput: () => { common.date_fixed = true; } })),
          el("label", { class: "label-check" }, check(common, "logo", MP.t("Logo on the labels")), " " + MP.t("Logo"))),
        rows,
        el("button", { type: "button", class: "btn btn-small label-add", onclick: () => { d.extra_labels.push({ name: "", detail: "", copies: 1 }); drawRows(); changed(); } }, "+ " + MP.t("Extra label")),
        options,
        el("p", { class: "muted label-printer" }, printerText(printer)),
        el("div", { class: "dialog-actions" },
          el("button", { type: "submit", class: "btn", value: "cancel" }, MP.t("Close")), download, printBtn)));
    dlg.addEventListener("close", () => { clearTimeout(timer); if (url) URL.revokeObjectURL(url); dlg.remove(); });
    document.body.append(dlg);
    dlg.showModal();
    refresh();
  };

  // --- Settings → Exports & printing → Label printer --------------------------------------------------------------
  const panel = MP.$("#printer-panel");
  if (!panel) return;
  let info = JSON.parse(MP.$("#printer-info").textContent);
  const address = MP.$("#printer-address");
  const status = MP.$("#printer-status");
  const showSeg = (id, value) => MP.$$(`#${id} button`).forEach((b) => {
    const on = b.dataset.value === String(value);
    b.classList.toggle("active", on); b.setAttribute("aria-checked", on ? "true" : "false");
  });
  const show = () => {
    address.value = info.address;
    showSeg("printer-tape", info.tape_mm); showSeg("printer-hires", info.hires);
    MP.$$(".printer-bool").forEach((box) => box.querySelectorAll("button").forEach((b) => {
      const on = b.dataset.value === String(info[box.dataset.key]);
      b.classList.toggle("active", on); b.setAttribute("aria-checked", on ? "true" : "false");
    }));
    MP.$("#printer-check").disabled = !info.address;
    const img = MP.$("#printer-logo-img");
    img.hidden = !info.logo;
    if (info.logo) img.src = "/api/label/logo.png?v=" + info.logo_version;
    MP.$("#printer-logo-none").hidden = !!info.logo;
    MP.$("#printer-logo-remove").hidden = !info.logo;
  };
  const save = async (changes) => {
    try { info = await MP.api("/api/label/printer", { json: changes }); MP.toast(MP.t("Saved for the whole lab")); }
    catch (e) { MP.toast(e.message, 4000); }
    show();
  };
  MP.$("#printer-save").addEventListener("click", () => save({ address: address.value.trim() }));
  address.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); save({ address: address.value.trim() }); } });
  MP.$$("#printer-tape button").forEach((b) => b.addEventListener("click", () => save({ tape_mm: Number(b.dataset.value) })));
  MP.$$("#printer-hires button").forEach((b) => b.addEventListener("click", () => save({ hires: b.dataset.value === "true" })));
  MP.$$(".printer-bool").forEach((box) => box.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => save({ [box.dataset.key]: b.dataset.value === "true" }))));
  MP.$("#printer-logo-file").addEventListener("change", (e) => {
    const file = e.currentTarget.files[0];
    e.currentTarget.value = "";
    if (!file) return;
    if (file.size > 256000) { MP.toast(MP.t("The logo should be a small picture (at most 256 kB)."), 4000); return; }
    const r = new FileReader();
    r.onload = () => save({ logo: String(r.result) });
    r.readAsDataURL(file);
  });
  MP.$("#printer-logo-remove").addEventListener("click", () => save({ logo: "" }));
  show();
  MP.$("#printer-check").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true; status.textContent = MP.t("Checking…");
    try { status.textContent = (await MP.api("/api/label/printer/check", { method: "POST" })).message; }
    catch (err) { status.textContent = err.message; }
    finally { btn.disabled = !info.address; }
  });
})();
