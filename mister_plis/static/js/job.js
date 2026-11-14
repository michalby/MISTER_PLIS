// A job whose tool is gone (templates/job.html): its results, read-only.
(async function () {
  const box = MP.$("#job-results");
  if (!box) return;
  try {
    const job = MP.filesFrom(await MP.api(`/api/jobs/${box.dataset.job}`));
    box.replaceChildren();
    const meta = MP.el("div", { class: "result-meta" }, MP.jobNumber(job), MP.resultButtons(...MP.resultExports(job)));
    box.append(meta);
    const out = MP.el("div", {});
    box.append(out);
    if (job.status === "done") MP.renderOutputs(out, job.outputs || [], { skip: new Set([MP.workbookIndex(job)]) });
    else out.append(MP.renderError(job));
  } catch (e) { box.replaceChildren(MP.el("div", { class: "alert alert-error" }, e.message)); }
})();
