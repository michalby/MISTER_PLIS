import pytest

from mister_plis.errors import ToolError
from mister_plis.inputs import Checkbox, Column, Integer, Number, Select, Text
from mister_plis.outputs import Metric, Table, coerce_outputs, fmt
from mister_plis.toolkit import Tool, read_table


def no_upload(_):
    raise AssertionError("no uploads expected")


def test_fmt():
    assert fmt(3.14159265) == "3.142"
    assert fmt(0.000012345) == "1.234e-05"
    assert fmt(1234567.0) == "1.235e+06"
    assert fmt(12) == "12"
    assert fmt(2.0) == "2"


def test_number_parsing():
    n = Number("x", min=0, max=10)
    assert n.parse("2,5", no_upload) == 2.5
    with pytest.raises(ToolError):
        n.parse("11", no_upload)
    with pytest.raises(ToolError):
        n.parse("", no_upload)
    assert Number("x", required=False).parse("", no_upload) is None
    with pytest.raises(ToolError):
        Integer("n").parse("2.5", no_upload)


def test_select_checkbox_text():
    s = Select("s", options=[("a", "A"), ("b", "B")])
    assert s.default == "a"
    assert s.parse("b", no_upload) == "b"
    with pytest.raises(ToolError):
        s.parse("c", no_upload)
    assert Checkbox("c").parse("true", no_upload) is True
    assert Text("t").parse("  hi ", no_upload) == "hi"
    assert Column("c", multiple=True, required=False).parse([], no_upload) == []


def test_tool_parse_collects_errors_and_units():
    t = Tool(id="t", name="T", inputs=[Number("a"), Number("b", units=["mL", "µL"])])
    with pytest.raises(ToolError) as e:
        t.parse({"a": "", "b": "x"}, no_upload)
    assert "A: required" in str(e.value) and "B:" in str(e.value)
    p = t.parse({"a": "1", "b": "2", "b__unit": "µL"}, no_upload)
    assert p.a == 1 and p.b_unit == "µL"
    assert t.parse({"a": "1", "b": "2"}, no_upload).b_unit == "mL"


def test_duplicate_inputs_rejected():
    with pytest.raises(ValueError):
        Tool(id="t", name="T", inputs=[Number("a"), Number("a")])


def test_coerce_outputs():
    import pandas as pd

    outs = coerce_outputs(["text", pd.DataFrame({"a": [1]}), {"k": 1}, None])
    kinds = [type(o).__name__ for o in outs]
    assert kinds == ["Markdown", "Table", "Metric"]
    assert isinstance(outs[2], Metric)
    assert isinstance(outs[1], Table)


def test_read_table_formats(tmp_path):
    import pandas as pd

    df = pd.DataFrame({"a": [1.5, 2.5], "b": ["x", "y"]})
    df.to_csv(tmp_path / "t.csv", index=False)
    df.to_excel(tmp_path / "t.xlsx", index=False)
    (tmp_path / "eu.csv").write_text("a;b\n1,5;x\n2,5;y\n", encoding="utf-8")
    (tmp_path / "t.tsv").write_text("a\tb\n1.5\tx\n2.5\ty\n", encoding="utf-8")
    for name, kw in [("t.csv", {}), ("t.xlsx", {}), ("eu.csv", {"decimal": ","}), ("t.tsv", {})]:
        got = read_table(tmp_path / name, **kw)
        assert list(got.columns) == ["a", "b"], name
        assert got["a"].tolist() == [1.5, 2.5], name
