# SPDX-License-Identifier: GPL-2.0
"""YAML: the reader, the writer, and models and adapters read from YAML."""

from __future__ import annotations

import datetime
import math
from typing import Any

import pytest

from espalier import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from espalier._yaml import YAMLError, dumps, loads, resolve


class Port(BaseModel):
    model_config = ConfigDict(strict=True)
    number: int
    proto: str = "tcp"


class Host(BaseModel):
    name: str
    ports: list[Port] = []
    tags: tuple[str, ...] = ()
    env: dict[str, str] = {}
    note: str | None = None
    when: datetime.datetime | None = None
    weight: float = 1.0
    alias_field: int = Field(0, alias="aliasField")


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("", None),
        ("~", None),
        ("null", None),
        ("NULL", None),
        ("true", True),
        ("False", False),
        ("TRUE", True),
        ("0", 0),
        ("-17", -17),
        ("+3", 3),
        ("0o17", 15),
        ("0x1F", 31),
        ("1.5", 1.5),
        ("-.5", -0.5),
        ("1e3", 1000.0),
        ("1.0e-07", 1e-07),
        ("6.", 6.0),
        (".inf", math.inf),
        ("-.Inf", -math.inf),
        ("yes", "yes"),
        ("on", "on"),
        ("0b101", "0b101"),
        ("1_000", "1_000"),
        ("2024-01-02", "2024-01-02"),
        ("text", "text"),
    ],
)
def test_core_schema(text: str, value: Any) -> None:
    assert resolve(text) == value
    assert type(resolve(text)) is type(value)


def test_nan() -> None:
    assert math.isnan(resolve(".nan"))
    assert math.isnan(loads("- .NaN")[0])


DOCUMENT = """\
%YAML 1.2
---
# A host
name: web  # trailing comment
port: 8080
ratio: 1.5
none: ~
empty:
list:
- a
- b: 1
  c: [1, 2, {x: y}]
-   - nested
- 'single'
nested:
  deep:
    k: 'it''s'
    q: "tab\\there \\u00e9 \\x41 \\U0001F600 \\N\\_\\L\\P \\0\\a\\b\\v\\f\\r\\e\\/\\ "
literal: |
  line1
   line2

keep: |+
  x

strip: |-
  x
folded: >
  a
  b

  c
    indented
  d
explicit: |2
    two
plain: multi
  line

  words
"quoted key": 1
'single key': 2
flow: {a: 1, b: [x, "y z", 'w'], c, d: , [e]: f}
pairs: [a: 1, "b": 2, c]
multiline flow: [1,
  2, # comment
  3]
multi "quoted": "one
  two

  three \\
  four"
...
"""


def test_document() -> None:
    with pytest.raises(YAMLError, match="complex mapping keys"):
        loads(DOCUMENT)
    data = loads(DOCUMENT.replace(", [e]: f", ""))
    assert data == {
        "name": "web",
        "port": 8080,
        "ratio": 1.5,
        "none": None,
        "empty": None,
        "list": ["a", {"b": 1, "c": [1, 2, {"x": "y"}]}, ["nested"], "single"],
        "nested": {
            "deep": {
                "k": "it's",
                "q": "tab\there \u00e9 A \U0001f600 \x85\xa0\u2028\u2029 \0\a\b\v\f\r\x1b/ ",
            }
        },
        "literal": "line1\n line2\n",
        "keep": "x\n\n",
        "strip": "x",
        "folded": "a b\nc\n  indented\nd\n",
        "explicit": "  two\n",
        "plain": "multi line\nwords",
        "quoted key": 1,
        "single key": 2,
        "flow": {"a": 1, "b": ["x", "y z", "w"], "c": None, "d": None},
        "pairs": [{"a": 1}, {"b": 2}, "c"],
        "multiline flow": [1, 2, 3],
        'multi "quoted"': "one two\nthree four",
    }


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("--- [1, 2]\n", [1, 2]),
        ("--- # comment\na: 1\n", {"a": 1}),
        ("a: 1\r\nb: 2\r\n", {"a": 1, "b": 2}),
        ("\ufeffa: 1", {"a": 1}),
        (b"a: \xc3\xa9", {"a": "\u00e9"}),
        (bytearray(b"- 1"), [1]),
        ("x", "x"),
        ("'a b': 1", {"a b": 1}),
        ("a: b\n  c\n\n  d", {"a": "b c\nd"}),
        ("a:\n- 1\n- 2\nb: 3", {"a": [1, 2], "b": 3}),
        ("- |\n  a\n- >-\n  b\n  c\n", ["a\n", "b c"]),
        ("- |2\n   x\n", [" x\n"]),
        ("a: |\n\n  x\n", {"a": "\nx\n"}),
        ("a: |\nb: 1", {"a": "", "b": 1}),
        ("a: >\n  x\n\n\n  y\n", {"a": "x\n\ny\n"}),
        ("a: >+\n  x\n\n", {"a": "x\n\n"}),
        ("? a\n: 1\n? 'b c'\n:\n  - 2\n? d\n", {"a": 1, "b c": [2], "d": None}),
        ("? |\n  long\n: - 1\n  - 2\n", {"long\n": [1, 2]}),
        ("? >-\n  k\n:\n- 1\n", {"k": [1]}),
        ("- ? x\n  : y\n", [{"x": "y"}]),
        ("{? a : 1, ? '' : 2}", {"a": 1, "": 2}),
        ("[{}, [], '', \"\"]", [{}, [], "", ""]),
        ("{'a''b': \"c\\\"d\"}", {"a'b": 'c"d'}),
        ("{X': y'z}", {"X'": "y'z"}),
        ("a: [b # c\n  ]", {"a": ["b"]}),
        ("a: 'x\n\n  y'", {"a": "x\ny"}),
        ('a: "x \\\n  y"', {"a": "x y"}),
        ("a: b#c", {"a": "b#c"}),
        ("a:b: c", {"a:b": "c"}),
        ("url: http://x/y", {"url": "http://x/y"}),
        ("a: 1\n...\n# end\n", {"a": 1}),
        ("a:\n  # comment\n  b: 1", {"a": {"b": 1}}),
    ],
)
def test_loads(text: str | bytes, value: Any) -> None:
    assert loads(text) == value


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("a: &x 1", "anchors, aliases and tags"),
        ("a: *x", "anchors, aliases and tags"),
        ("a: !t 1", "anchors, aliases and tags"),
        ("&x a: 1", "anchors, aliases and tags"),
        ("[&x 1]", "anchors, aliases and tags"),
        ("a: @x", "cannot start with '@'"),
        ("[`x]", "cannot start with '`'"),
        ("[- x]", "cannot start with '-'"),
        ("? [a]\n: 1", "complex mapping keys"),
        ("? \n  a\n: 1", "complex mapping keys"),
        ("{[a]: 1}", "complex mapping keys"),
        ("a: 1\na: 2", "line 2: duplicate key 'a'"),
        ("{a: 1, a: 2}", "duplicate key 'a'"),
        ("---\na\n---\nb", "line 3: only one document"),
        ("a\n...\nb", "unexpected text after the document"),
        ("%TAG ! x\n---\na", "directives other than %YAML"),
        ("a:\n\tb: 1", "tabs cannot indent"),
        ("a: b: c", "a mapping value is not allowed here"),
        ("a: b\n  c: d", "a mapping value is not allowed here"),
        ("a: [1, 2", "the flow collection is not closed"),
        ("a: [1, 2\n---", "the flow collection is not closed"),
        ("a: {b: 1", "the flow collection is not closed"),
        ("a: [1, 2] x", "unexpected text after a value"),
        ("[1 2 3}", "expected ',' or ']'"),
        ("{a: 1 [b]}", "expected ',' or '}'"),
        ("{a: 1] ", "expected ',' or '}'"),
        ("[1, , 2]", "expected a value"),
        ("a: 'x", "the quoted scalar is not closed"),
        ("a: 'x' y", "unexpected text after a value"),
        ('a: "\\q"', "unknown escape"),
        ('a: "\\x4"', "needs 2 hexadecimal digits"),
        ('["\\u12"]', "needs 4 hexadecimal digits"),
        ('"a', "the quoted scalar is not closed"),
        ("a: |x\n  b", "bad block scalar header"),
        ("a:\n    b: 1\n  c: 2", "unexpected indentation"),
        ("a:\n  - 1\n - 2", "unexpected indentation"),
        ("- a\nb: 1", "unexpected text after the document"),
        ("a: 1\n- b", "expected 'key: value'"),
    ],
)
def test_refused(text: str, message: str) -> None:
    with pytest.raises(YAMLError, match=message):
        loads(text)


def test_error_line() -> None:
    with pytest.raises(YAMLError) as error:
        loads("a: 1\nb:\n  c: *x\n")
    assert error.value.line == 3


DATA: list[Any] = [
    None,
    {},
    [],
    "",
    {"a": {}, "b": [], "c": ""},
    {"true": "true", "1": "1", "null": "null", "yes": "no", "x y": "x: y", "#": "a #b"},
    ["-", "- a", "?", "? a", ":", "a:", " lead", "trail ", "'q'", '"d"', "[", "{", "|", ">"],
    ["@a", "`a", "%a", "&a", "*a", "!a", "~", "=", "<<", "0b1", "1_0", "1:2", "2024-1-2"],
    {"text": "line\n", "strip": "line", "keep": "a\nb\n\n\n", "lead": " a\nb", "tab": "a\t\nb"},
    {"blank": "\n", "blanks": "\n\n", "inner": "a\n\nb", "first": "\na\n", "nonprint": "a\x00\nb"},
    [1, -2, 0, 1.5, -1e-07, 1e100, math.inf, -math.inf, True, False],
    [[1, [2, [3]]], [{"a": [{"b": {}}]}], [[], {}]],
    {"\u00e9": "\u2028", "emoji": "\U0001f600", "c": "\x07\x85\ud7ff"},
    "multi\nline\n",
]


@pytest.mark.parametrize("data", DATA)
def test_round_trip(data: Any) -> None:
    text = dumps(data)
    assert loads(text) == data
    assert all(line == line.rstrip() for line in text.splitlines())


def test_dumps_layout() -> None:
    data = {"a": [{"b": 1, "c": [2]}, "x\ny\n"], "d": {}, "e": "f", "g": 0.5, "h": math.nan}
    assert dumps(data) == (
        "a:\n  - b: 1\n    c:\n      - 2\n  - |\n    x\n    y\nd: {}\ne: f\ng: 0.5\nh: .nan\n"
    )
    assert dumps(1e-07) == "1.0e-07\n"
    assert dumps("on") == '"on"\n'
    assert dumps({1: "a"}) == '"1": a\n'


def test_dumps_refuses_other_types() -> None:
    with pytest.raises(TypeError, match="cannot write bytes"):
        dumps(b"x")


def test_model_round_trip() -> None:
    host = Host(
        name="web: 1",
        ports=[Port(number=80), Port(number=53, proto="udp")],
        tags=("a", "b"),
        env={"PATH": "/bin", "1": "x"},
        when=datetime.datetime(2024, 1, 2, 3, 4, 5),
        weight=math.inf,
        aliasField=3,
    )
    text = host.model_dump_yaml(by_alias=True)
    assert 'name: "web: 1"' in text
    assert 'when: "2024-01-02T03:04:05"' in text
    assert Host.model_validate_yaml(text) == host
    assert Host.model_validate_yaml(text.encode()) == host
    assert host.model_dump_yaml(include={"name"}) == 'name: "web: 1"\n'
    assert "note" not in host.model_dump_yaml(exclude_none=True)
    assert "alias_field: 3" in host.model_dump_yaml(exclude={"ports"})


def test_strict() -> None:
    assert Port.model_validate_yaml("number: 80") == Port(number=80)
    with pytest.raises(ValidationError, match="valid integer"):
        Port.model_validate_yaml("number: '80'")
    assert Host.model_validate_yaml("name: x\nweight: '2'").weight == 2.0
    with pytest.raises(ValidationError, match="valid number"):
        Host.model_validate_yaml("name: x\nweight: '2'", strict=True)


def test_invalid_yaml() -> None:
    with pytest.raises(ValidationError) as error:
        Host.model_validate_yaml("name: [x")
    (detail,) = error.value.errors()
    assert detail["type"] == "yaml_invalid"
    assert "Invalid YAML: line 1: the flow collection is not closed" in detail["msg"]
    with pytest.raises(ValidationError, match="yaml_invalid"):
        Host.model_validate_yaml(b"name: \xff")


def test_adapter() -> None:
    adapter = TypeAdapter(dict[str, tuple[int, ...]])
    value = {"a": (1, 2), "b": ()}
    assert adapter.dump_yaml(value) == b"a:\n  - 1\n  - 2\nb: []\n"
    assert adapter.validate_yaml(adapter.dump_yaml(value)) == value
    with pytest.raises(ValidationError, match="valid integer"):
        adapter.validate_yaml("a: ['1']", strict=True)
    with pytest.raises(ValidationError, match="yaml_invalid"):
        adapter.validate_yaml("a: *b")
    assert TypeAdapter(Port).dump_yaml(Port(number=1), exclude_none=True) == (
        b"number: 1\nproto: tcp\n"
    )
