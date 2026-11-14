// The sign-in page (templates/login.html): sign in, or choose one's own password after an admin's reset.
(function () {
  const data = JSON.parse(document.getElementById("login-data").textContent);
  const error = document.getElementById("error");
  const show = (text) => { error.textContent = text; error.hidden = !text; };

  async function post(url, body) {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    let d = {};
    try { d = await res.json(); } catch (_) { /* not JSON */ }
    if (!res.ok) throw new Error(d.error || d.detail || data.failed);
    return d;
  }

  const login = document.getElementById("login-form");
  if (login) login.addEventListener("submit", async (e) => {
    e.preventDefault();
    show("");
    try {
      const d = await post("/api/login", { name: login.querySelector("#name").value, password: login.querySelector("#password").value });
      location.href = d.change ? "/login?change=1&next=" + encodeURIComponent(data.next) : data.next;
    } catch (err) { show(err.message); login.querySelector("#password").select(); }
  });

  const change = document.getElementById("change-form");
  if (change) change.addEventListener("submit", async (e) => {
    e.preventDefault();
    const nw = change.querySelector("#new").value;
    if (nw !== change.querySelector("#repeat").value) { show(data.differ); return; }
    show("");
    try { await post("/api/account/password", { new: nw }); location.href = data.next; } catch (err) { show(err.message); }
  });

  document.querySelectorAll(".login-lang [data-lang]").forEach((b) => b.addEventListener("click", () => {
    document.cookie = `lang=${b.dataset.lang}; path=/; max-age=63072000; samesite=lax${location.protocol === "https:" ? "; secure" : ""}`;
    location.reload();
  }));
})();
