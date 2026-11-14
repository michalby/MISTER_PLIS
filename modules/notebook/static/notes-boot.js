// Lab notebook panel, before the first paint (shell/head.html): on a wide screen it starts open (unless this browser
// closed it last time); on a small one it starts closed and opens over the page.
(function () {
  var d = document.documentElement;
  if (!d.classList.contains("notes-on")) return;
  MP.notesWide = window.matchMedia("(min-width: 1100px)");
  var closed = null, w = null;
  try { closed = localStorage.getItem("mp:notes-open") === "0"; w = localStorage.getItem("mp:notes-w"); } catch (e) {}
  if (w && +w >= 300) d.style.setProperty("--notes-w", Math.round(+w) + "px");
  if (MP.notesWide.matches && !closed) d.classList.add("notes-open");
})();
