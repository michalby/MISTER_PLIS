"""A tool page opened from a link fills its inputs in (/tool/<id>?<input>=<value>, <input>__unit=<unit>), over what the
browser remembers — as a reagent's "Make a solution" button in the inventory does. In a real browser (Playwright +
Chromium); skipped where none is installed."""

import json
import urllib.request

import pytest

pytest.importorskip("playwright.sync_api")
from test_settings_browser import browser, server  # noqa: E402,F401  (the same running app and browser)


def _post(base, path, data):
    req = urllib.request.Request(base + path, json.dumps(data).encode(), {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def test_a_link_fills_the_form_in(server, browser):
    page = browser.new_page()
    try:
        # what this browser remembers from the last time: another compound, a 2 L volume
        page.goto(server + "/tool/toy-calc")
        page.fill("#f-volume", "2")
        page.select_option('[data-name="volume"] .unit-select', "L")
        page.wait_for_timeout(300)

        page.goto(server + "/tool/toy-calc?compound=custom&new_name=Spermidine&mw=145.25&conc__unit=M&nope=1")
        page.wait_for_selector(".out-card, .metric, .results > *")
        assert page.input_value("#f-compound") == "custom"
        assert page.is_visible("#f-new_name") and page.input_value("#f-new_name") == "Spermidine"
        assert page.input_value("#f-mw") == "145.25"
        assert page.input_value('[data-name="conc"] .unit-select') == "M"
        assert page.input_value("#f-volume") == "2" and page.input_value('[data-name="volume"] .unit-select') == "L"  # kept
        assert "?" not in page.url  # a reload keeps what the person changes next, not the link
        page.wait_for_function("document.querySelector('#results').textContent.includes('Spermidine')")

        # …and remembered, like anything typed in
        page.goto(server + "/tool/toy-calc")
        assert page.input_value("#f-new_name") == "Spermidine" and page.input_value("#f-mw") == "145.25"
        assert not page.eval_on_selector("details.form-section", "d => d.open")  # collapsed, as the tool has it

        # a collapsed section opens when the link sets one of its inputs to something other than its default (the first)
        names = ("Cadaverine", "Putrescine")
        for n in names:
            _post(server, "/api/tools/toy-calc/action/save", {"params": {"new_name": n, "mw": "88.15"}})
        try:
            page.goto(server + "/tool/toy-calc?remove_which=" + urllib.request.quote("user:Cadaverine"))
            assert page.input_value("#f-remove_which") == "user:Cadaverine"
            assert not page.eval_on_selector("details.form-section", "d => d.open")
            page.goto(server + "/tool/toy-calc?remove_which=" + urllib.request.quote("user:Putrescine"))
            assert page.input_value("#f-remove_which") == "user:Putrescine"
            assert page.eval_on_selector("details.form-section", "d => d.open")
        finally:
            for n in names:
                _post(server, "/api/tools/toy-calc/action/remove", {"params": {"remove_which": f"user:{n}"}})
    finally:
        page.close()
