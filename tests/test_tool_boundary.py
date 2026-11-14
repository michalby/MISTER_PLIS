"""Tools use only mister_plis.toolkit (reorg phase P1), so they can live in their own repositories (tool sources).

Here the rule is checked on the base's own test tools; the lab's tools repository checks its tools the same way."""

import ast
import json
from pathlib import Path

import pytest

from mister_plis import toolkit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests" / "fixtures" / "toolsource"
TOOL_FILES = sorted(SOURCE.glob("*.py")) + sorted((SOURCE / "locale").glob("*.py"))


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield node.lineno, a.name, []
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module, [a.name for a in node.names]


@pytest.mark.parametrize("path", TOOL_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_tools_import_only_the_toolkit(path):
    bad = []
    for line, module, names in _imports(path):
        if module == "mister_plis" or (module.startswith("mister_plis.") and module != "mister_plis.toolkit"):
            bad.append(f"line {line}: {module}")
        if module == "tools" or module.startswith(("tools.", "mp_tools_")):
            bad.append(f"line {line}: {module} (use a relative import: from ._helper import …)")
        if module == "mister_plis.toolkit":
            unknown = [n for n in names if n not in toolkit.__all__]
            if unknown:
                bad.append(f"line {line}: {unknown} are not in toolkit.__all__")
    assert not bad, bad


def test_the_toolkit_api_is_what_it_says():
    assert toolkit.TOOLKIT_API == 1
    missing = [n for n in toolkit.__all__ if not hasattr(toolkit, n)]
    assert not missing, missing
    doc = (ROOT / "docs" / "ADDING_TOOLS.md").read_text(encoding="utf-8")
    undocumented = [n for n in toolkit.__all__ if f"`{n}" not in doc]
    assert not undocumented, f"add these to the API section of docs/ADDING_TOOLS.md: {undocumented}"


def test_tool_data_moves_from_the_old_place_once(tmp_path, monkeypatch):
    from mister_plis.config import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "compounds.json").write_text(json.dumps({"Tris": 121.14}), encoding="utf-8")
    path = toolkit.tool_data_file("molarity", "compounds.json", legacy="compounds.json")
    assert path == tmp_path / "tool-data" / "molarity" / "compounds.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"Tris": 121.14} and (tmp_path / "compounds.json").exists()  # old file kept
    path.write_text(json.dumps({"Tris": 121.14, "HEPES": 238.3}), encoding="utf-8")
    (tmp_path / "compounds.json").write_text(json.dumps({"stale": 1.0}), encoding="utf-8")
    again = toolkit.tool_data_file("molarity", "compounds.json", legacy="compounds.json")
    assert "HEPES" in json.loads(again.read_text(encoding="utf-8"))  # copied once only: newer saves are never overwritten
    with pytest.raises(ValueError):
        toolkit.tool_data_dir("../elsewhere")


def test_find_program(tmp_path, monkeypatch):
    from mister_plis.config import settings

    exe = tmp_path / "blender"
    exe.write_text("", encoding="utf-8")
    assert toolkit.find_program("blender", [str(tmp_path / "nope"), str(exe)]) == str(exe)
    monkeypatch.setattr(settings, "blender_path", str(tmp_path / "missing"))
    assert toolkit.find_program("blender", [str(exe)]) is None  # a configured path must exist
    monkeypatch.setattr(settings, "blender_path", str(exe))
    assert toolkit.find_program("blender") == str(exe)
    assert toolkit.find_program("definitely-not-a-program-xyz") is None


def test_saved_lists_live_in_tool_data(client):
    import importlib

    from mister_plis.registry import registry

    calc = importlib.import_module(registry.get("toy-calc").run_fn.__module__)
    assert calc.__name__ == "mp_tools_fixture.toy_calc"  # loaded from its tool source, as its own package
    assert calc.USER_FILE.parent.name == "toy-calc" and calc.USER_FILE.parent.parent.name == "tool-data"
