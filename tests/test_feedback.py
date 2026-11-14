"""Feedback button (bugs, inconveniences, ideas), protocol headings, the server's keep-alive."""


def test_feedback_round_trip(client):
    client.cookies.set("name", "Ola")
    try:
        r = client.post("/api/feedback", json={"kind": "bug", "text": "  PDF button does nothing  ", "page": "/tool/molarity", "where": "Tools / Molar solution"})
        assert r.status_code == 200
        item = r.json()
        assert item["kind"] == "bug" and item["text"] == "PDF button does nothing" and item["user"] == "Ola" and item["status"] == "new"
    finally:
        client.cookies.delete("name")
    assert client.post("/api/feedback", json={"kind": "rant", "text": "x"}).status_code == 422
    assert client.post("/api/feedback", json={"kind": "idea", "text": "   "}).status_code == 422
    listed = client.get("/api/feedback").json()
    assert listed["items"][0]["id"] == item["id"] and listed["kinds"] == {"bug": "Bug", "inconvenience": "Inconvenience", "idea": "Feature idea"}
    # the sidebar's Feedback link counts what isn't done; the Feedback page lists it
    page = client.get("/feedback").text
    assert 'id="feedback-count"' in page and 'href="/feedback"' in page and 'id="fb-list"' in page
    assert 'id="feedback-count"' in client.get("/").text
    assert client.post(f"/api/feedback/{item['id']}", json={"status": "done"}).json()["status"] == "done"
    assert client.post(f"/api/feedback/{item['id']}", json={"status": "maybe"}).status_code == 404
    assert client.delete(f"/api/feedback/{item['id']}").json() == {"ok": True}
    assert client.delete(f"/api/feedback/{item['id']}").status_code == 404
    assert all(i["id"] != item["id"] for i in client.get("/api/feedback").json()["items"])


def test_feedback_button_on_every_page(client):
    for url in ("/", "/jobs", "/settings", "/tool/toy-calc"):
        page = client.get(url).text
        assert 'id="fb-btn"' in page and 'id="fb-pop"' in page and "/static/js/feedback.js" in page, url
        assert page.count('name="kind"') == 3


def test_protocol_heading_is_the_compound(client):
    j = client.post("/api/tools/toy-calc/run", json={"params": {"compound": "custom", "new_name": "Tris-HCl pH 8", "mw": 157.6, "conc": 50}}).json()
    assert j["heading"] == "Tris-HCl pH 8 · 50 mM"
    assert "Tris-HCl pH 8" in next(o["html"] for o in j["outputs"] if o["kind"] == "html")
    j = client.post("/api/tools/toy-calc/run", json={"params": {"compound": "custom", "mw": 10, "conc": 50}}).json()
    assert j["heading"] == "Toy solution · 50 mM"  # no compound named: the calculator names it
    j = client.post("/api/tools/toy-calc/run", json={"params": {"compound": "salt", "conc": 1, "volume": 1}}).json()
    assert j["heading"] == "Salt · 1 mM"


def test_server_keeps_idle_connections_open(monkeypatch):
    """A click on a connection the server is just closing showed "page unavailable" until a refresh."""
    import sys

    import uvicorn

    from mister_plis import __main__ as main

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: seen.update(kw))
    monkeypatch.setattr(sys, "argv", ["mister_plis", "--port", "8123"])
    monkeypatch.setattr(main.os, "chdir", lambda p: None)
    main.main()
    assert seen["timeout_keep_alive"] >= 60


def test_people_lists_everyone_who_added_anything(client):
    client.cookies.set("name", "Ola Nowak")
    try:
        assert client.post("/api/feedback", json={"kind": "idea", "text": "a people list"}).status_code == 200
    finally:
        client.cookies.delete("name")
    people = client.get("/api/people").json()["people"]
    ola = next(p for p in people if p["name"] == "Ola Nowak")
    assert ola["feedback"] >= 1 and ola["last"] >= ola["first"]
    assert [p["name"].casefold() for p in people] == sorted(p["name"].casefold() for p in people)
    assert 'id="people-list"' in client.get("/settings").text


def test_merging_two_people(client):
    from mister_plis.app import merged_people

    for who in ("Kasia", "Kasia K."):
        client.cookies.set("name", who)
        assert client.post("/api/feedback", json={"kind": "idea", "text": f"from {who}"}).status_code == 200
    client.cookies.delete("name")
    assert client.post("/api/people/merge", json={"from": "Kasia", "into": "kasia"}).status_code == 422  # the same one
    assert client.post("/api/people/merge", json={"from": "", "into": "Kasia K."}).status_code == 422
    d = client.post("/api/people/merge", json={"from": "Kasia", "into": "Kasia K."}).json()
    assert d["moved"]["feedback"] == 1
    names = [p["name"] for p in d["people"]]
    assert "Kasia K." in names and "Kasia" not in names
    assert next(p for p in d["people"] if p["name"] == "Kasia K.")["feedback"] == 2
    assert all(i["user"] != "Kasia" for i in client.get("/api/feedback").json()["items"])
    # a browser still set to the old name is counted as the kept one, so the old name doesn't come back
    client.cookies.set("name", "kasia")
    try:
        assert client.post("/api/feedback", json={"kind": "idea", "text": "again"}).json()["user"] == "Kasia K."
    finally:
        client.cookies.delete("name")
    # merging the kept name further takes the first one along
    merged_people.merge("Kasia K.", "Katarzyna")
    assert merged_people.canonical("Kasia") == "Katarzyna"
