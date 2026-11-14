"""Settings page and the cookies behind it: theme, decimal separator on screen and in Excel files."""

import pandas as pd
from openpyxl import load_workbook

from mister_plis.excel import write_workbook
from mister_plis.outputs import fmt
from mister_plis.prefs import DEFAULTS, current_prefs, from_cookies


def _with(**prefs):
    return current_prefs.set({**DEFAULTS, **prefs})


def test_cookies_are_validated():
    assert from_cookies({}) == DEFAULTS and DEFAULTS["lang"] == "en"  # English unless the browser chose Polish
    p = from_cookies({"theme": "dark", "decimal": "comma", "xlsx_numbers": "nonsense"})
    assert p["theme"] == "dark" and p["decimal"] == "comma" and p["xlsx_numbers"] == "number"


def test_settings_page_and_theme(client):
    try:
        page = client.get("/settings").text
        assert 'data-pref="theme"' in page and 'data-pref="xlsx_numbers"' in page and 'data-theme="light"' in page
        client.cookies.set("theme", "dark")
        page = client.get("/settings").text
        assert 'data-theme="dark"' in page and "Decimal separator on screen" in page
        assert 'id="theme-btn"' in client.get("/").text  # the toggle in the top-right corner
    finally:
        client.cookies.clear()
        client.cookies.set("lang", "en")


def test_fmt_follows_decimal_setting():
    assert fmt(1.5) == "1.5"
    token = _with(decimal="comma")
    try:
        assert fmt(1.5) == "1,5" and fmt(12345) == "12 345" and fmt(0.00001234) == "1,234e-05"
        assert fmt("1.5") == "1.5"  # text is left alone
    finally:
        current_prefs.reset(token)


def test_job_uses_the_decimal_setting_of_whoever_ran_it(client):
    params = {"compound": "salt", "conc": "150", "conc__unit": "mM", "volume": "1", "volume__unit": "L"}
    try:
        client.cookies.set("decimal", "comma")
        job = client.post("/api/tools/toy-calc/run", json={"params": params}).json()
        weigh = next(o for o in job["outputs"] if o["kind"] == "metric")
        assert "," in weigh["value"] and "." not in weigh["value"]
    finally:
        client.cookies.clear()
        client.cookies.set("lang", "en")


def _cells(path):
    ws = load_workbook(path).active
    return [c.value for c in ws[2]]


def test_xlsx_numbers(tmp_path):
    df = pd.DataFrame({"name": ["a"], "x": [1.25], "n": [3], "whole": [2.0]})
    write_workbook(tmp_path / "num.xlsx", {"S": df})
    assert _cells(tmp_path / "num.xlsx") == ["a", 1.25, 3, 2]
    for setting, text in (("comma", "1,25"), ("dot", "1.25")):
        token = _with(xlsx_numbers=setting)
        try:
            write_workbook(tmp_path / f"{setting}.xlsx", {"S": df}, notes=[("factor", 0.5)])
        finally:
            current_prefs.reset(token)
        assert _cells(tmp_path / f"{setting}.xlsx") == ["a", text, 3, 2]


def test_csv_download_with_comma(tmp_path):
    from mister_plis.outputs import Table

    def save(name, data):
        (tmp_path / name).write_bytes(data)
        return tmp_path / name

    token = _with(xlsx_numbers="comma")
    try:
        Table(pd.DataFrame({"x": [1.5, 2.25], "y": [1, 2]}), download="t.csv").render(str, save)
    finally:
        current_prefs.reset(token)
    assert (tmp_path / "t.csv").read_text(encoding="utf-8").splitlines() == ["x;y", "1,5;1", "2,25;2"]
