"""The Settings tabs in a real browser (Playwright + Chromium): switching, the address, back, reload, old links, and
that a tab asks the server for its data only when opened. Skipped where no browser is installed."""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    data = tmp_path_factory.mktemp("data")
    (data / "lab.json").write_text('{"format": 1, "state": "skipped"}', encoding="utf-8")  # not led to the setup page
    env = {**os.environ, "MISTER_PLIS_DATA_DIR": str(data), "MISTER_PLIS_FETCH_TOOL_SOURCES": "0",
           "MISTER_PLIS_MODULE_INVENTORY_REPO": "", "MISTER_PLIS_MODULE_NOTEBOOK_REPO": "",
           "MISTER_PLIS_TOOL_FOLDERS": str(ROOT / "tests" / "fixtures" / "toolsource")}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "mister_plis.app:app", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            urllib.request.urlopen(base + "/api/version", timeout=1)
            break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("the server didn't start")
    yield base
    proc.terminate()
    proc.wait(10)


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # pragma: no cover - no browser on this machine
            pytest.skip(f"no browser: {e}")
        yield b
        b.close()


def _active(page) -> str:
    return page.eval_on_selector('[role="tab"][aria-selected="true"]', "t => t.dataset.tab")


def _visible(page, tab) -> bool:
    return page.is_visible(f"#tab-{tab}")


def test_tabs_switch_in_the_page(server, browser):
    page = browser.new_page()
    asked = []
    page.on("request", lambda r: asked.append(r.url))
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server + "/settings")
    assert _active(page) == "you" and _visible(page, "you") and not _visible(page, "server")
    page.wait_for_timeout(300)
    assert not any("/api/system" in u for u in asked)  # the Server tab's GitHub check waits until it is opened
    assert not any("/api/tools/sources" in u for u in asked)

    page.click('[role="tab"][data-tab="tools"]')
    assert page.url.endswith("#tools") and _active(page) == "tools" and _visible(page, "tools") and not _visible(page, "you")
    page.wait_for_selector("#ts-list .ts-row, #ts-list .muted")
    page.wait_for_selector("#tset-list .tset-tool")  # the toy tool's own setting
    assert "Helper program" in page.inner_text("#tset-list")

    page.click('[role="tab"][data-tab="server"]')
    page.wait_for_function("document.querySelector('#server-info dt').textContent !== 'Loading…'")
    assert any("/api/system" in u for u in asked)

    page.go_back()
    assert _active(page) == "tools" and page.url.endswith("#tools")
    page.reload()
    assert _active(page) == "tools"

    page.focus('[role="tab"][data-tab="tools"]')
    page.keyboard.press("ArrowRight")
    assert _active(page) == "jobs" and page.url.endswith("#jobs")
    assert not errors, errors


def test_old_links_open_the_right_tab(server, browser):
    page = browser.new_page()
    page.goto(server + "/system#storage")  # the old page and one of its panels
    assert page.url.split("?")[0].endswith("/settings") and _active(page) == "jobs" and page.is_visible("#storage")
    page.goto(server + "/system")
    assert _active(page) == "server"
    page.goto(server + "/settings#printer-panel")
    assert _active(page) == "exports"
    page.goto(server + "/settings#feedback")
    page.wait_for_url("**/feedback")
    page.goto(server + "/settings#reagents")  # the inventory's old anchor, now its tab
    assert _active(page) == "inventory"


def test_the_lab_name_shows_in_the_sidebar(server, browser):
    page = browser.new_page()
    page.goto(server + "/settings#server")
    page.fill("#lab-name", "Smith Lab")
    page.click("#lab-name-save")
    page.wait_for_function("document.querySelector('.brand-sub').textContent === 'Smith Lab'")
    page.goto(server + "/")
    assert page.inner_text(".brand-sub") == "Smith Lab"
    page.goto(server + "/settings#server")
    page.fill("#lab-name", "")
    page.click("#lab-name-save")
    page.wait_for_function("document.querySelector('.brand-sub').textContent === 'lab toolbox'")


def test_the_setup_page_loads_a_lab_file_into_its_form(server, browser):
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(server + "/setup")
        page.wait_for_selector(".setup-module")
        assert page.input_value("[name='module.inventory.repo']") == ""  # nothing set on this server
        page.select_option("#setup-files", "labs/example.toml")
        page.click("#setup-load-file")
        page.wait_for_function("document.querySelector(\"[name='module.inventory.repo']\").value !== ''")
        assert page.input_value("[name='module.inventory.repo']").endswith(".git")
        assert page.input_value("[name='lab.name']") == "Smith Lab" and page.locator(".setup-source").count() >= 1
        assert "labs/example.toml" in page.inner_text("#setup-source") and not errors
    finally:
        page.close()
