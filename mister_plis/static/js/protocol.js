// Whole-result PDF button, and the protocol: results collected with "Add to protocol" on calculator pages
// (Molar solution, Stock solution …) and printed together for the bench. The list lives in this browser and is
// shared by every tool that offers it, so a buffer from one calculator and a dilution from another end up on one sheet.
(function () {
  const { el, icon } = MP;
  const KEY = "mp:protocol";

  function load() {
    try {
      const d = JSON.parse(localStorage.getItem(KEY) || "{}");
      return { title: d.title || "", items: Array.isArray(d.items) ? d.items : [], extra_labels: Array.isArray(d.extra_labels) ? d.extra_labels : [], labels: d.labels || {} };
    } catch (_) { return { title: "", items: [], extra_labels: [], labels: {} }; }
  }
  function save(d) {
    try { localStorage.setItem(KEY, JSON.stringify(d)); } catch (_) { MP.toast(MP.t("Could not save the protocol in this browser")); }
    document.dispatchEvent(new CustomEvent("mp:protocol"));
  }

  MP.protocol = { load, save };

  // One line to recognise a result by: the recipe sentence if there is one, else the main number.
  function summary(outputs) {
    const html = outputs.find((o) => o.kind === "html");
    if (html) {
      const div = document.createElement("div");
      div.innerHTML = html.html;
      const t = div.textContent.replace(/\s+/g, " ").trim();
      if (t) return t;
    }
    const m = outputs.find((o) => o.kind === "metric" && o.highlight) || outputs.find((o) => o.kind === "metric");
    return m ? `${m.label}: ${m.value} ${m.unit || ""}`.trim() : "";
  }

  function add(spec, job) {
    const d = load();
    const params = JSON.stringify(job.params || {});
    if (d.items.some((it) => it.tool_id === spec.id && JSON.stringify(it.params) === params)) {
      MP.toast(MP.t("Already in the protocol"));
      return false;
    }
    const outputs = (job.outputs || []).filter((o) => o.kind !== "file");
    d.items.push({ tool_id: spec.id, tool_name: spec.name, heading: job.heading || spec.name, params: job.params || {}, outputs, summary: summary(outputs), added: Date.now(), labelable: !!spec.label });
    save(d);
    MP.toast(MP.t("Added — {n} in the protocol", { n: d.items.length }));
    return true;
  }

  async function print() {
    const d = load();
    if (!d.items.length) return;
    await MP.askName();  // the dialog's OK is a click too, so the new tab isn't blocked
    // a real form post, so the PDF opens in a new tab like any other link
    const f = el("form", { method: "post", action: "/api/protocol.pdf", target: "_blank", hidden: true },
      el("input", { type: "hidden", name: "data", value: JSON.stringify({ title: d.title, items: d.items }) }));
    document.body.append(f);
    f.submit();
    f.remove();
  }

  // Buttons above a finished result: "PDF" and "Excel" (MP.resultExports, outputs.js), then "Add to protocol".
  MP.resultActions = function (spec, job) {
    const nodes = MP.resultExports(job);
    if (spec.protocol && job.status === "done" && (job.outputs || []).length) {
      nodes.push(el("button", { class: "btn btn-small", type: "button", title: MP.t("Collect this result; print all collected results at once below"),
        onclick: () => add(spec, job) }, icon("plus", 14), MP.t("Add to protocol")));
    }
    return nodes;
  };

  // The list under the form on pages that offer "Add to protocol".
  MP.protocolPanel = function () {
    const box = el("section", { class: "recent protocol", hidden: true });
    const render = () => {
      const d = load();
      box.hidden = !d.items.length;
      if (!d.items.length) { box.replaceChildren(); return; }
      const title = el("input", { type: "text", class: "protocol-title", maxlength: 120, placeholder: MP.t("Protocol"), value: d.title, "aria-label": MP.t("Title of the printout") });
      title.addEventListener("change", () => { const x = load(); x.title = title.value.trim(); save(x); });
      const rows = d.items.map((it, i) => el("div", { class: "job-row protocol-row" },
        el("span", { class: "muted" }, `${i + 1}.`),
        el("div", { class: "grow" }, el("div", { class: "jtool" }, it.heading || it.tool_name),
          el("div", { class: "muted protocol-sum" }, [it.heading && it.heading !== it.tool_name ? it.tool_name : "", it.summary || ""].filter(Boolean).join(" · "))),
        el("button", { type: "button", class: "icon-btn", title: MP.t("Remove from the protocol"), onclick: () => { const x = load(); x.items.splice(i, 1); save(x); } }, icon("x", 16))));
      box.replaceChildren(
        el("div", { class: "section-head" },
          el("h2", { class: "section-title" }, `${MP.t("Protocol")} · ${d.items.length}`),
          el("div", { class: "protocol-actions" },
            title,
            el("button", { type: "button", class: "btn btn-small", onclick: () => { if (confirm(MP.t("Remove all {n} from the protocol?", { n: d.items.length }))) save({ title: load().title, items: [], extra_labels: [], labels: load().labels }); } }, MP.t("Clear")),
            MP.labelStrip ? el("button", { type: "button", class: "btn btn-small", title: MP.t("All the reagents in this protocol on one strip of P-touch tape"), onclick: () => MP.labelStrip() }, icon("tag", 14), MP.t("Labels")) : null,
            MP.exportBtn("pdf", { onclick: print, label: MP.t("Print protocol"), title: MP.t("Everything in the protocol on one PDF, to print") }))),
        el("div", { class: "job-list" }, rows),
        el("p", { class: "muted protocol-note" }, MP.t("Kept in this browser — every calculator with “Add to protocol” collects into this one list.")));
    };
    document.addEventListener("mp:protocol", render);
    window.addEventListener("storage", (e) => { if (e.key === KEY) render(); });  // added in another tab
    render();
    return box;
  };
})();
