import socket
import threading

import pytest

from mister_plis.errors import ToolError
from PIL import Image

from mister_plis.labels import TAPES, Label, Printer, _raster_lines, parse_status, preview_png, raster_job, render, render_all


def test_render_fits_tape_and_grows_with_text():
    short = render(Label("NaCl", "150 mM", "Anna", "2026-10-20"))
    long = render(Label("EDTA disodium dihydrate", "0.5 M", "Anna", "2026-10-20"))
    assert short.mode == "1" and short.height == 70 and long.height == 70
    assert long.width > short.width
    # high resolution: twice the dots along the tape
    assert abs(render(Label("NaCl", "1 M"), 12, hires=True).width - 2 * render(Label("NaCl", "1 M"), 12, hires=False).width) <= 2
    assert render(Label("NaCl"), 24).height == 128
    # subscripts and Polish letters draw (the main font lacks ₂; a fallback font is used)
    assert render(Label("MgCl₂·6H₂O", person="Michał Żółć")).width > 100
    with pytest.raises(ToolError):
        render(Label("x" * 2000))


def _pages(job: bytes):
    """Split a raster job into pages: (print info bytes, advanced mode, raster lines, end byte)."""
    assert job.startswith(b"\x00" * 100 + b"\x1b@")
    pages, i = [], 102
    while i < len(job):
        assert job[i:i + 4] == b"\x1bia\x01"
        info = job[i + 7:i + 17]
        k = job.index(b"\x1biK", i)
        advanced = job[k + 3]
        margin = int.from_bytes(job[k + 7:k + 9], "little")
        i = job.index(b"M\x02", i) + 2
        lines = 0
        while job[i:i + 1] in (b"Z", b"G"):  # each line is blank (Z) or one 16-byte literal run
            if job[i:i + 1] == b"Z":
                i += 1
            else:
                assert job[i:i + 4] == b"G\x11\x00\x0f"
                line = int.from_bytes(job[i + 4:i + 20], "big")
                assert line >> (29 + 70) == 0 and line & ((1 << 29) - 1) == 0  # only the 70 pins over 12 mm tape
                i += 20
            lines += 1
        pages.append((info, advanced, margin, lines, job[i]))
        i += 1
    return pages


def test_strip_job_half_cut_and_high_res():
    imgs = [render(Label("NaCl", "1 M")), render(Label("KCl", "2 M"))]
    job = raster_job(imgs, 12, hires=True)  # default: the printer's cut option 5
    assert job.count(b"\x1biM\x00") == 2  # no auto cut, no mirror printing
    pages = _pages(job)
    assert len(pages) == 2
    (info1, adv1, m1, n1, end1), (info2, adv2, m2, n2, end2) = pages
    assert info1[2] == 12 and int.from_bytes(info1[4:8], "little") == n1 == imgs[0].width
    assert info1[8] == 0 and info2[8] == 1  # starting page, other page
    assert adv1 == adv2 == 0x04 | 0x40  # half cut + high resolution, chain printing on
    assert m1 == 28  # 2 mm at 360 dpi
    assert end1 == 0x0C and end2 == 0x1A  # FF between pages, Control-Z after the last
    job = raster_job(imgs, 12, hires=False, half_cut=False, auto_cut=True, chain=False)
    assert job.count(b"\x1biM\x40") == 2 and job.count(b"\x1biA\x01") == 2
    assert _pages(job)[0][1] == 0x08 and _pages(job)[0][2] == 14  # no chain printing; 2 mm at 180 dpi
    assert raster_job(imgs, 12, half_cut=True, auto_cut=True).count(b"\x1biA\x02") == 2  # cut through after the strip


def test_raster_not_mirrored():
    """The picture's top row goes to the highest pin over the tape, its bottom row to the lowest."""
    dots, offset = TAPES[12]
    img = Image.new("1", (2, dots), 1)
    img.putpixel((0, 0), 0)
    img.putpixel((1, dots - 1), 0)
    top, bottom = (int.from_bytes(line, "big") for line in _raster_lines(img, 12))
    assert top == 1 << (offset + dots - 1) and bottom == 1 << offset


def test_preview_strip():
    png = preview_png([Label("NaCl", "1 M"), Label(""), Label("KCl")])  # the empty one is skipped
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(ToolError, match="nothing to print"):
        preview_png([Label("")])
    with pytest.raises(ToolError, match="At most"):
        preview_png([Label("x")] * 100)
    assert set(TAPES) >= {9, 12, 18, 24}


def test_status():
    st = bytes([0x80, 0x20] + [0] * 6 + [0, 0x10, 12] + [0] * 21)
    s = parse_status(st)
    assert s.tape_mm == 12 and s.errors == ["the cover is open"]
    with pytest.raises(ToolError):
        parse_status(b"\x00" * 5)


def test_printer_settings_and_send(tmp_path):
    pr = Printer(tmp_path)
    s = pr.settings()
    assert s.address == "" and s.hires and s.half_cut and s.chain and not s.auto_cut
    with pytest.raises(ToolError, match="Settings"):
        pr.print([Label("NaCl")])
    for bad in ({"address": "http://x/"}, {"tape_mm": 7}):
        with pytest.raises(ToolError):
            pr.update(bad)
    assert pr.update({"auto_cut": True, "hires": False}).auto_cut and not pr.settings().hires
    pr.update({"auto_cut": False, "hires": True})
    one = pr.settings().with_options({"tape_mm": 18, "chain": False, "address": "ignored"})
    assert one.tape_mm == 18 and not one.chain and one.address == "" and pr.settings().chain  # this print only
    with pytest.raises(ToolError):
        pr.settings().with_options({"tape_mm": 5})

    # a fake printer: answers the status request (18 mm tape), then records the job
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    got = bytearray()

    def serve():
        conn, _ = srv.accept()
        with conn:
            buf = b""
            while b"\x1biS" not in buf:
                buf += conn.recv(4096)
            conn.sendall(bytes([0x80, 0x20] + [0] * 8 + [18] + [0] * 21))
            while chunk := conn.recv(65536):
                got.extend(chunk)

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    pr.update({"address": f"127.0.0.1:{srv.getsockname()[1]}", "tape_mm": 12})
    msg = pr.print([Label("NaCl", "150 mM"), Label("KCl", "1 M")])
    t.join(5)
    srv.close()
    assert "2 labels" in msg and "18 mm" in msg
    assert got.count(b"\x1biK\x44") == 2  # half cut + high resolution + chain printing
    assert got.count(b"\x1biz") == 2 and got[got.index(b"\x1biz") + 5] == 18 and got.endswith(b"\x1a")


def test_label_api(client):
    r = client.post("/api/tools/toy-calc/label", json={"params": {"compound": "salt", "conc": 150, "conc__unit": "mM", "volume": 1, "volume__unit": "L"}})
    assert r.status_code == 200, r.text
    f = r.json()["fields"]
    assert f["name"] == "Salt" and f["detail"] == "150 mM" and f["logo"] is True
    r = client.post("/api/tools/toy-calc/label", json={"params": {"compound": "sugar", "conc": 10, "conc__unit": "mM"}})
    assert r.json()["fields"]["detail"] == "10 mM"
    assert client.post("/api/tools/toy-table/label", json={}).status_code == 404
    specs = {t["id"]: t for t in client.get("/api/tools").json()["tools"]}
    assert specs["toy-calc"]["label"] and not specs["toy-table"]["label"]

    r = client.post("/api/label/preview.png", json={"labels": [{"name": "NaCl", "detail": "150 mM"}, {"name": "KCl"}]})
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.post("/api/label/preview.png", json={"labels": [{"name": "x"}], "tape_mm": 5}).status_code == 422
    assert client.post("/api/label/preview.png", json={}).status_code == 422
    assert client.post("/api/label/print", json={"labels": [{}]}).status_code == 422
    page = client.get("/settings")
    assert page.status_code == 200 and "Label printer" in page.text and "Half cut" in page.text
    assert client.post("/api/label/printer", json={"address": "bad address"}).status_code == 422
    assert client.post("/api/label/printer", json={"chain": False}).json()["chain"] is False
    r = client.post("/api/label/preview.png", json={"labels": [{"name": "x"}], "options": {"tape_mm": 24, "half_cut": False}})
    assert r.status_code == 200
    assert client.post("/api/label/preview.png", json={"labels": [{"name": "x"}], "options": {"tape_mm": 5}}).status_code == 422


def test_reagent_portion_and_safety_labels():
    """A portion's label: the storage letter in a square instead of the logo; its safety label: GHS pictograms."""
    plain = render(Label.from_dict({"name": "Phenol", "detail": "M = 94.11 g/mol", "person": "Ola", "date": "2026-11-06", "logo": False}))
    square = Label.from_dict({"name": "Phenol", "detail": "M = 94.11 g/mol", "person": "Ola", "date": "2026-11-06", "square": "C", "logo": False})
    assert square.square == "C"
    a = render(square)
    assert a.height == plain.height and a.width > plain.width
    safety = Label.from_dict({"name": "Cat. no. 123", "pictos": ["05", "GHS06", "6", "x", "10"]})
    assert safety.pictos == ("05", "06")
    assert not safety.empty and not Label.from_dict({"pictos": ["05"]}).empty
    one = render(Label.from_dict({"pictos": ["05"]}), 12)
    two = render(Label.from_dict({"pictos": ["05", "06"]}), 12)
    assert two.width > one.width >= one.height  # each pictogram as high as the tape


def test_portion_labels_same_length_and_number_on_the_right():
    first = Label.from_dict({"name": "Phenol", "detail": "M = 94.11 g/mol", "square": "C", "right": "14", "match": "p", "logo": False})
    second = Label.from_dict({"name": "Cat. no. PA-14-4056", "detail": "POCH (Avantor)", "person": "LOT MKCK1234",
                              "pictos": ["05", "06", "08"], "match": "p", "logo": False})
    other = Label.from_dict({"name": "x", "logo": False})
    a, b, c = render_all([first, second, other], 12)
    assert a.width == b.width and c.width < a.width
    no_number = render(Label.from_dict({"name": "Phenol", "detail": "M = 94.11 g/mol", "square": "C", "logo": False}))
    assert render(first).width > no_number.width
    # the number sits at the right end: black dots near the end of the label
    px = a.load()
    assert any(not px[x, y] for x in range(a.width - 40, a.width) for y in range(a.height))
