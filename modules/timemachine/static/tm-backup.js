// Settings → Jobs & backup → Time Machine in the backup folder (status, back up now, restore).
(function () {
  const { $, el, api } = MP;
  const box = $("#tm-backup-info");
  if (!box) return;
  const render = (d) => {
    const st = d.state || {};
    const rows = [
      [MP.t("Kept in"), el("code", {}, d.kept_in)],
      [MP.t("Copied to"), d.folder ? el("code", {}, d.folder) : MP.t("no backup folder set (above)")],
      [MP.t("Last copy"), st.at ? MP.datetime(st.at) + (st.entries != null ? " · " + MP.tn(st.entries, "{n} kept result", "{n} kept results") : "") : MP.t("not yet")],
    ];
    box.replaceChildren(...rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
    $("#tm-backup-now").disabled = !d.folder;
    $("#tm-backup-restore").disabled = !d.bundle;
  };
  const load = async () => { try { render(await api("/api/tm/backup")); } catch (e) { MP.toast(e.message); } };
  $("#tm-backup-now").addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    try { await api("/api/tm/backup", { method: "POST" }); MP.toast(MP.t("Time Machine copied to the backup folder")); } catch (err) { MP.toast(err.message, 6000); }
    load();
  });
  $("#tm-backup-restore").addEventListener("click", async () => {
    if (!confirm(MP.t("Replace Time Machine on this server with the copy in the backup folder? The current one is kept, renamed."))) return;
    try {
      const d = await api("/api/tm/backup/restore", { method: "POST" });
      MP.toast(MP.tn(d.entries, "Restored: {n} kept result", "Restored: {n} kept results"), 6000);
    } catch (err) { MP.toast(err.message, 6000); }
    load();
  });
  MP.whenShown(box, load);  // when Settings → Jobs & backup is first opened
})();
