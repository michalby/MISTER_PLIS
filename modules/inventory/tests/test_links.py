"""A URL field keeps only web addresses: a "javascript:" link would run in the page when clicked (SECURITY_AUDIT.md M2)."""

import pytest

from mister_plis.errors import ToolError
from modules.inventory.service import convert

FIELD = {"type": "url", "label": "Link", "key": "link"}


def test_a_url_field_refuses_a_link_that_runs_something():
    for bad in ("javascript:alert(1)", " JavaScript:alert(1)", "data:text/html,<b>x</b>"):
        with pytest.raises(ToolError):
            convert(FIELD, bad)


def test_a_url_field_keeps_web_addresses_and_old_ones_without_a_scheme():
    assert convert(FIELD, "https://www.sigmaaldrich.com/x") == "https://www.sigmaaldrich.com/x"
    assert convert(FIELD, "www.sigmaaldrich.com") == "www.sigmaaldrich.com"
    assert convert(FIELD, "") is None
