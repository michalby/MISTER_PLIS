"""Polish interface: the catalogue is complete and consistent, pages and results come out in Polish."""

import json
import re
from pathlib import Path

import pytest

from mister_plis import i18n
from mister_plis.locale import PL

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*|\d+)\}")


@pytest.fixture
def polish(client):
    client.cookies.set("lang", "pl")
    yield client
    client.cookies.set("lang", "en")


def test_catalogue_is_consistent():
    for key, value in PL.items():
        if "|" in key and "{" in key:  # plural: English one|other, Polish one|few|many
            assert len(key.split("|")) == 2 and len(value.split("|")) == 3, key
            continue
        # Polish may drop an English plural "s" ({1} in "label{1}"), but never invent a value
        assert set(PLACEHOLDER.findall(value)) <= set(PLACEHOLDER.findall(key)), key
        assert len(set(PLACEHOLDER.findall(key)) - set(PLACEHOLDER.findall(value))) <= 1, key
        assert value.strip(), key


def _literals():
    """Every text the pages and scripts translate: _("…") in templates, MP.t("…") / MP.tn(…) in scripts."""
    out = set()
    for p in [*(ROOT / "mister_plis/templates").rglob("*.html"), *(ROOT / "modules").glob("*/templates/**/*.html")]:
        text = p.read_text(encoding="utf-8")
        out |= {m.group(2) for m in re.finditer(r"""(?<![\w.])_\(\s*(["'])((?:(?!\1).)+)\1""", text)}
        out |= {f"{a}|{b}" for a, b in re.findall(r'_n\([^,]+,\s*"([^"]*)",\s*"([^"]*)"', text)}
    for p in [*(ROOT / "mister_plis/static/js").glob("*.js"), *(ROOT / "modules").glob("*/static/*.js")]:
        text = p.read_text(encoding="utf-8")
        out |= {json.loads(f'"{s}"') for s in re.findall(r'MP\.t\(\s*"((?:[^"\\]|\\.)*)"', text)}
        out |= {f"{json.loads(chr(34) + a + chr(34))}|{json.loads(chr(34) + b + chr(34))}"
                for a, b in re.findall(r'MP\.tn\([^"]*"((?:[^"\\]|\\.)*)",\s*"((?:[^"\\]|\\.)*)"', text)}
    return out


def test_every_interface_text_has_polish():
    missing = sorted(s for s in _literals() if s not in PL and s.strip() and re.search(r"[A-Za-z]{2}", s)
                     and s not in ("Deleted {name}", "{n} file|{n} files", "Saved"))  # examples in a comment
    assert not missing, missing


def test_plurals():
    assert [i18n.tn(n, "{n} row", "{n} rows", "pl") for n in (1, 2, 5, 12, 22, 25)] == \
        ["1 wiersz", "2 wiersze", "5 wierszy", "12 wierszy", "22 wiersze", "25 wierszy"]
    assert i18n.tn(1, "{n} row", "{n} rows", "en") == "1 row" and i18n.tn(3, "{n} row", "{n} rows", "en") == "3 rows"


def test_patterns_and_cells():
    assert i18n.tr("Samples and means — Every measurement", "pl") == "Próbki i średnie — Wszystkie pomiary"
    assert i18n.tr("Values × **3**.", "pl") == "Wartości × **3**."
    assert i18n.exact("1 of 3", "pl") == "1 z 3"
    assert i18n.exact("WT of mutant", "pl") == "WT of mutant"  # names in cells are never bent by a pattern
    # a stray word inside a long sentence is not "translated" on its own
    s = "For dilute samples: the sample makes up 80 % of the cuvette."
    assert " z " not in i18n.tr(s, "pl")
    # Markdown: line by line, longest known run of sentences
    md = i18n.tr_text("**Sample names**\n\nValues × **2**.\n\nNo measurements selected — upload files and tick the samples to use.", "pl")
    assert md.startswith("**Nazwy próbek**") and "Wartości × **2**." in md and "Nie wybrano pomiarów" in md
    assert i18n.tr("Saved", "en") == "Saved" and i18n.tr("nothing like this", "pl") == "nothing like this"


def test_pages_in_polish(polish):
    page = polish.get("/").text
    assert 'lang="pl"' in page and "Wszystkie narzędzia" in page and "Zgłoś uwagę" in page and "/i18n/pl.js" in page
    assert 'data-lang="en"' in page and 'data-lang="pl"' in page  # the PL / EN switch in the top bar
    page = polish.get("/tool/toy-calc").text
    assert "Roztwór testowy" in page and "Masa molowa" in page
    js = polish.get("/i18n/pl.js")
    assert js.status_code == 200 and js.text.startswith("MP.i18n = ") and "Dodaj do protokołu" in js.text
    assert polish.get("/i18n/xx.js").status_code == 404


def test_english_still_english(client):
    page = client.get("/").text
    assert 'lang="en"' in page and "All tools" in page and "/i18n/" not in page


def test_results_in_polish(polish):
    job = polish.post("/api/tools/toy-calc/run", json={"params": {"compound": "sugar", "conc": 250, "volume": 100}}).json()
    labels = [o.get("label") for o in job["outputs"] if o["kind"] == "metric"]
    assert labels == ["Odważyć", "Stężenie"]
    html = next(o["html"] for o in job["outputs"] if o["kind"] == "html")
    assert "Rozpuścić" in html and "Cukier" in html
    assert job["heading"] == "Cukier · 250 mM"
    bad = polish.post("/api/tools/toy-calc/run", json={"params": {"compound": "sugar", "conc": "abc", "volume": 100}}).json()
    assert bad["status"] == "failed" and "Stężenie" in bad["error"] and "nie jest liczbą" in bad["error"]


def test_compounds_alphabetical_in_each_language(client, polish):
    from mister_plis.toolkit import alphabetical_key

    for lang in ("en", "pl"):
        page = client.get("/tool/toy-calc", cookies={"lang": lang}).text
        spec = json.loads(re.search(r'<script type="application/json" id="tool-spec">(.*?)</script>', page, re.S).group(1))
        opts = next(i for i in spec["inputs"] if i.get("name") == "compound")["options"]
        names = [o[1] for o in opts[:-1]]
        assert names == sorted(names, key=alphabetical_key), lang
        assert opts[-1][0] == "custom"  # "Other…" stays last
    assert alphabetical_key("Lizyna") < alphabetical_key("Łój") < alphabetical_key("Mocznik") < alphabetical_key("Sacharoza")  # Ł after L
    assert alphabetical_key("K₂HPO₄") < alphabetical_key("KCl")
