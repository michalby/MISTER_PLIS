"""The lab's own logo on its labels (docs/PREP_PLAN.md R11): none by default, chosen on Settings or in the lab file."""

import io
import json

import pytest
from PIL import Image

from mister_plis import labsetup
from mister_plis.errors import ToolError
from mister_plis.labels import Label, Printer, logo_data_url, render
from mister_plis.labsetup import dumps, parse

PKG = labsetup.ROOT / "mister_plis"


def _png(w=60, h=20, colour=0) -> bytes:
    out = io.BytesIO()
    Image.new("L", (w, h), colour).save(out, "PNG")
    return out.getvalue()


def test_no_lab_logo_comes_with_the_code():
    assert not (PKG / "static" / "label" / "logo.png").exists()
    for f in PKG.rglob("*.py"):
        assert "MAAMI" not in f.read_text(encoding="utf-8"), f


def test_a_new_lab_prints_without_a_logo_and_with_its_own_once_chosen(tmp_path):
    p = Printer(tmp_path)
    assert p.logo_png() is None and p.info()["logo"] is False
    plain = render(Label("NaCl", "1 M"))
    p.update({"logo": logo_data_url(_png())})
    assert p.info()["logo"] is True and Image.open(io.BytesIO(p.logo_png())).format == "PNG"
    from mister_plis.labels import logo_image

    with_logo = render(Label("NaCl", "1 M"), lab_logo=logo_image(p.logo_png()))
    assert with_logo.width > plain.width  # the logo comes before the text
    assert render(Label("NaCl", "1 M", logo=False), lab_logo=logo_image(p.logo_png())).width == plain.width
    p.update({"logo": ""})
    assert p.logo_png() is None and json.loads((tmp_path / "label_printer.json").read_text())["logo"] is False


def test_a_transparent_logo_prints_its_dark_parts_only(tmp_path):
    from mister_plis.labels import logo_image

    out = io.BytesIO()
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(out, "PNG")  # see-through black: nothing to print
    assert logo_image(out.getvalue()).getextrema() == (255, 255)


@pytest.mark.parametrize("bad", ["data:image/png;base64,bm90IGEgcGljdHVyZQ==", "not a data address", "data:image/png;base64,%%%"])
def test_what_isnt_a_picture_is_refused(tmp_path, bad):
    with pytest.raises(ToolError):
        Printer(tmp_path).update({"logo": bad})


def test_a_large_picture_is_refused(tmp_path):
    big = io.BytesIO()
    Image.effect_noise((600, 600), 100).save(big, "PNG")
    assert len(big.getvalue()) > 256_000
    with pytest.raises(ToolError, match="small picture"):
        Printer(tmp_path).update({"logo": logo_data_url(big.getvalue())})


def test_a_lab_file_names_a_picture_next_to_it_and_carries_it_when_written_out(tmp_path):
    (tmp_path / "ours.png").write_bytes(_png())
    f = tmp_path / "lab.toml"
    f.write_text('[label_printer]\nlogo = "ours.png"\n', encoding="utf-8")
    lab, warnings = parse(f.read_text(encoding="utf-8"), str(f))
    assert not warnings and lab["label_printer"]["logo"].startswith("data:image/png;base64,")
    again, _ = parse(dumps(lab))  # a downloaded lab file is one file: the picture is inside it
    assert again == lab
    # without its folder (pasted on the setup page), the picture is left out with a warning; the rest applies
    lab, warnings = parse('[lab]\nname = "X"\n[label_printer]\nlogo = "ours.png"\n')
    assert "logo" not in lab["label_printer"] and lab["lab"]["name"] == "X" and "ours.png" in warnings[0]
    assert parse('[label_printer]\nlogo = ""\n')[0] == {"label_printer": {"logo": ""}}  # none


from tests.test_labsetup import setup  # noqa: E402,F401 — the fixture: a small server of its own


def test_setting_a_lab_up_installs_its_logo_and_the_plan_says_so(setup):
    lab = {"label_printer": {"logo": logo_data_url(_png())}}
    rows = {r["key"]: r for r in setup.plan(lab)}
    assert rows["logo"]["old"] == "none" and rows["logo"]["new"] == "a picture" and rows["logo"]["status"] == "change"
    setup.apply(lab, "Ola", "page")
    assert setup.printer.logo_png() and setup.current()["label_printer"]["logo"] == lab["label_printer"]["logo"]
    assert {r["key"]: r for r in setup.plan(lab)}["logo"]["status"] == "same"


def test_a_server_that_printed_labels_before_keeps_its_logo_once(tmp_path):
    (tmp_path / "label_printer.json").write_text('{"address": "10.0.0.5", "tape_mm": 12}', encoding="utf-8")
    p = Printer(tmp_path)
    assert p.keep_old_logo(lambda: _png()) and p.logo_png()
    p.update({"logo": ""})
    assert not p.keep_old_logo(lambda: _png()) and p.logo_png() is None  # asked once only
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    assert not Printer(fresh).keep_old_logo(lambda: _png())  # a new server: nothing to keep


def test_which_old_logo_a_server_keeps(tmp_path):
    def state(**d):
        (tmp_path / "lab.json").write_text(json.dumps({"format": 1, "state": "set_up", **d}), encoding="utf-8")

    state(**{"from": "migrated"})  # older than lab files: only our lab's servers were, with the picture in the code
    if labsetup.LEGACY_LOGO.is_file():
        assert labsetup.old_logo(tmp_path) == labsetup.LEGACY_LOGO.read_bytes()
    else:  # a copy of the code without it (the public one): such a server already kept it, so nothing to give
        assert labsetup.old_logo(tmp_path) is None
    lab_file = tmp_path / "lab.toml"
    (tmp_path / "theirs.png").write_bytes(_png(colour=40))
    lab_file.write_text('[label_printer]\nlogo = "theirs.png"\n', encoding="utf-8")
    state(**{"from": str(lab_file)})
    assert Image.open(io.BytesIO(labsetup.old_logo(tmp_path))).getpixel((0, 0)) == 40
    state(**{"from": "page"})  # set up on the setup page: it never chose one
    assert labsetup.old_logo(tmp_path) is None
