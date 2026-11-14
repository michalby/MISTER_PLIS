"""The ImageSpots widget in a real browser: circles suggested on an uploaded picture, added, moved, selected, named,
deleted, and sent to the run (Playwright + Chromium; skipped where none is installed)."""

import io

import pytest
from PIL import Image


def _png(squares=((0, 0), (40, 20))) -> bytes:
    im = Image.new("L", (80, 60), 0)
    for x, y in squares:
        im.paste(255, (x, y, x + 10, y + 10))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


pytest.importorskip("playwright.sync_api")
from test_settings_browser import browser, server  # noqa: E402,F401  (the same running app and browser)


def test_the_widget_places_moves_and_names_circles(server, browser, tmp_path):
    pic = tmp_path / "squares.png"
    pic.write_bytes(_png())
    page = browser.new_page(viewport={"width": 1280, "height": 1400})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(server + "/tool/toy-spots")
        page.set_input_files('[data-name="picture"] input[type=file]', str(pic))
        page.wait_for_selector(".spots-svg .spot")
        assert page.locator(".spots-svg .spot").count() == 2
        assert "2 bright squares" in page.inner_text(".spots-note")
        svg = page.locator(".spots-svg")
        svg.scroll_into_view_if_needed()
        box = svg.bounding_box()
        k = box["width"] / 80  # screen pixels per picture pixel

        # double-click on the picture adds a circle there
        page.mouse.dblclick(box["x"] + 70 * k, box["y"] + 50 * k)
        assert page.locator(".spots-svg .spot").count() == 3
        # drag the first circle 10 picture-pixels to the right
        page.mouse.move(box["x"] + 5 * k, box["y"] + 5 * k)
        page.mouse.down()
        page.mouse.move(box["x"] + 10 * k, box["y"] + 5 * k, steps=4)
        page.mouse.move(box["x"] + 15 * k, box["y"] + 5 * k, steps=4)
        page.mouse.up()
        # the squares are wells of a plate beside the picture; the added circle is listed under it
        assert page.locator(".spots-plate .spots-well").count() == 2 and page.locator(".spots-free .well").count() == 1
        assert page.locator(".spots-plate .spots-nowell").count() == 10
        # select everything by dragging across the picture (measured again: the list beside it has grown), and name
        # the circles one per column
        box = svg.bounding_box()
        k = box["width"] / 80
        page.mouse.move(box["x"] + 1.5 * k, box["y"] + 1.5 * k)  # (not in the frame's rounded corner)
        page.mouse.down()
        page.mouse.move(box["x"] + 78.5 * k, box["y"] + 58.5 * k, steps=5)
        page.mouse.up()
        assert "3" in page.inner_text(".pl-meta .muted")
        names = page.locator(".pl-controls .pl-field")
        names.nth(0).locator("input").fill("a, b, c")
        names.nth(1).locator("select").select_option("cols")
        page.click(".pl-controls .btn-primary")
        spots = page.evaluate("() => { const out = []; document.querySelectorAll('.spots-svg .spot title').forEach((t) => out.push(t.textContent)); return out; }")
        assert spots[0].startswith("S1 · a") and spots[1].startswith("S2 · b") and spots[2].startswith("3 · c"), spots
        assert page.inner_text(".spots-plate .spots-well >> nth=0").startswith("a")
        # on the plate: a row label selects that row's wells, and one name goes to all of them
        page.click(".spots-plate .plate-head:text-is('B')")
        assert "1" in page.inner_text(".pl-meta .muted")
        names.nth(0).locator("input").fill("row B")
        page.click(".pl-controls .btn-primary")
        assert page.inner_text(".spots-plate .spots-well >> nth=1").startswith("row B")
        # Delete removes the selection
        svg.scroll_into_view_if_needed()
        box = svg.bounding_box()  # (typing in the fields below may have scrolled the page)
        page.mouse.click(box["x"] + 70 * k, box["y"] + 50 * k)  # the added circle
        page.keyboard.press("Delete")
        assert page.locator(".spots-svg .spot").count() == 2
        # the run gets the moved circle
        page.click("#run-btn") if page.locator("#run-btn").count() else page.click("button[type=submit]")
        page.wait_for_selector(".results table")
        assert "a" in page.inner_text(".results table")
        assert not errors, errors
    finally:
        page.close()
