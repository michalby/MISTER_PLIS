// The first script of every page, in <head> (templates/base.html, login.html): MP with what the server put in the page
// (#mp-boot, JSON), and the theme before the first paint ("auto" follows the computer's light / dark mode). In a file of
// its own, not inline, so the pages can forbid inline scripts (Content-Security-Policy, mister_plis/serving.py).
(function () {
  var boot = document.getElementById("mp-boot");
  window.MP = Object.assign({ prefs: { theme: "auto" }, i18n: {}, dark: false }, boot ? JSON.parse(boot.textContent) : {});
  document.documentElement.classList.add("js");  // tabs inside a page show only the active one (app.css)
  var mq = window.matchMedia("(prefers-color-scheme: dark)");
  MP.applyTheme = function () {
    var p = MP.dark ? "dark" : MP.prefs.theme;  // a page that is always dark (Time Machine)
    document.documentElement.dataset.theme = p === "auto" ? (mq.matches ? "dark" : "light") : p;
    document.dispatchEvent(new Event("mp:theme"));
  };
  MP.applyTheme();
  mq.addEventListener("change", function () { if (MP.prefs.theme === "auto") MP.applyTheme(); });
})();
