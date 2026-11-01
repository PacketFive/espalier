# SPDX-License-Identifier: GPL-2.0
"""XML: the reader, the writer, and models and adapters read from XML."""

from __future__ import annotations

import datetime
import enum
import math
from typing import Annotated, Any, Literal, NewType

import pytest

from espalier import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from espalier._xml import XMLError, dumps, loads

type Names = list[str]
Count = NewType("Count", int)


class Color(enum.Enum):
    RED = 1
    BLUE = 2


class Port(BaseModel):
    model_config = ConfigDict(strict=True)
    number: int
    proto: Literal["tcp", "udp"] = "tcp"


class Cat(BaseModel):
    kind: Literal["cat"]
    lives: int


class Dog(BaseModel):
    kind: Literal["dog"]
    good: bool


class Host(BaseModel):
    model_config = ConfigDict(strict=True)
    name: str
    ports: list[Port] = []
    tags: set[str] = set()
    names: Names = []
    env: dict[str, str] = {}
    weights: dict[str, float] = {}
    pair: tuple[int, str] = (0, "")
    note: str | None = None
    when: datetime.datetime | None = None
    color: Color = Color.RED
    pet: Annotated[Cat | Dog, Field(discriminator="kind")] | None = None
    count: Count = Count(0)
    blob: Any = None
    ratio: float = 0.0
    alias_field: int = Field(0, alias="aliasField")


def make_host() -> Host:
    return Host(
        name="web\r\n<&>\"' ",
        ports=[Port(number=80), Port(number=53, proto="udp")],
        tags={"a"},
        names=["x"],
        env={"PATH": "/bin", "1 bad": "x", "item": "i", "entry": "e", "xmlns": "n", "": ""},
        weights={"w": math.inf, "v": -1e-07},
        pair=(3, "x"),
        when=datetime.datetime(2024, 1, 2, 3, 4, 5),
        color=Color.BLUE,
        pet=Dog(kind="dog", good=True),
        count=Count(4),
        blob={"a": [1, "2", None], "b": {}},
        ratio=0.5,
        aliasField=5,
    )


@pytest.mark.parametrize("indent", [None, 2])
def test_model_round_trip(indent: int | None) -> None:
    host = make_host()
    text = host.model_dump_xml(by_alias=True, indent=indent)
    assert text.startswith("<Host>")
    back = Host.model_validate_xml(text)
    assert back.blob == {"a": ["1", "2", None], "b": ""}
    assert back.model_copy(update={"blob": host.blob}) == host
    assert Host.model_validate_xml(text.encode()) == back


def test_layout() -> None:
    host = Host(name="a", ports=[Port(number=1)], env={"k": "v", "1": "x"}, note=None, aliasField=0)
    text = host.model_dump_xml(include={"name", "ports", "env", "note", "tags"}, root="host")
    assert text == (
        "<host><name>a</name><ports><item><number>1</number><proto>tcp</proto></item></ports>"
        '<tags /><env><k>v</k><entry key="1">x</entry></env><note nil="true" /></host>'
    )
    assert host.model_dump_xml(include={"name"}, indent=2) == "<Host>\n  <name>a</name>\n</Host>\n"
    assert "<note" not in host.model_dump_xml(exclude_none=True)
    assert "<ports" not in host.model_dump_xml(exclude={"ports"})


def test_scalars() -> None:
    assert dumps([True, False, 1, 1.5, math.nan, -math.inf, None], "v") == (
        "<v><item>true</item><item>false</item><item>1</item><item>1.5</item>"
        '<item>nan</item><item>-inf</item><item nil="true" /></v>'
    )
    adapter = TypeAdapter(tuple[bool, int, float, float, float | None, str])
    value = adapter.validate_xml(adapter.dump_xml((True, 1, 1.5, -math.inf, None, "")))
    assert value == (True, 1, 1.5, -math.inf, None, "")
    assert math.isnan(TypeAdapter(float).validate_xml(b"<v>nan</v>"))


def test_unions() -> None:
    assert TypeAdapter(int | str).validate_xml("<v>1</v>") == 1
    assert TypeAdapter(str | int).validate_xml("<v>1</v>") == "1"
    assert TypeAdapter(int | bool).validate_xml("<v>true</v>") is True
    assert TypeAdapter(int | float).validate_xml("<v>1.5</v>") == 1.5
    assert TypeAdapter(list[int] | None).validate_xml("<v><item>1</item></v>") == [1]
    mixed = TypeAdapter(int | list[int])
    assert mixed.validate_xml("<v><item>1</item></v>") == [1]
    assert mixed.validate_xml("<v>2</v>") == 2
    assert TypeAdapter(Literal[1, True, "a"] | None).validate_xml("<v>true</v>") is True
    assert TypeAdapter(Literal[1, "a"]).validate_xml("<v>1</v>") == 1
    with pytest.raises(ValidationError, match="literal_error"):
        TypeAdapter(Literal[1, "a"]).validate_xml("<v>b</v>")
    with pytest.raises(ValidationError):
        TypeAdapter(int | bool).validate_xml("<v>x</v>", strict=True)


def test_collections() -> None:
    adapter = TypeAdapter(dict[str, list[tuple[int, ...]]])
    value = {"a": [(1, 2), ()], "b": []}
    assert adapter.validate_xml(adapter.dump_xml(value)) == value
    assert TypeAdapter(frozenset[int]).validate_xml("<v><x>1</x><y>2</y></v>") == {1, 2}
    assert TypeAdapter(tuple[()]).validate_xml("<v />") == ()
    assert TypeAdapter(tuple).validate_xml("<v><item>1</item></v>") == ("1",)
    assert TypeAdapter(dict).validate_xml("<v><a>1</a></v>") == {"a": "1"}
    assert TypeAdapter(list[str]).validate_xml("<v><item /></v>") == [""]
    assert TypeAdapter(bytes).validate_xml("<v>abc</v>") == b"abc"
    with pytest.raises(ValidationError, match="too_long"):
        TypeAdapter(tuple[int]).validate_xml("<v><i>1</i><i>2</i></v>")
    for tp in (list[int], tuple[int, ...], tuple[int, int], dict[str, int], Port):
        with pytest.raises(ValidationError):
            TypeAdapter(tp).validate_xml("<v>text</v>")
    with pytest.raises(ValidationError, match="valid integer"):
        TypeAdapter(int).validate_xml("<v><a>1</a></v>")


def test_generic() -> None:
    adapter = TypeAdapter(Any)
    text = adapter.dump_xml({"a": [1, {"b": None}], "c": "", "item": 2})
    assert adapter.validate_xml(text) == {"a": ["1", {"b": None}], "c": "", "item": "2"}
    assert adapter.validate_xml("<v><item>1</item><item>2</item></v>") == ["1", "2"]


def test_refused() -> None:
    bomb = '<!DOCTYPE v [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><v>&b;</v>'
    for text in (bomb, '<!DOCTYPE v SYSTEM "file:///etc/passwd"><v />', "<!DOCTYPE v><v />"):
        with pytest.raises(XMLError, match="document type declarations"):
            loads(text, str)
    with pytest.raises(XMLError, match="not well-formed|no element found"):
        loads("<v>", str)
    with pytest.raises(XMLError, match="line 2: <v> mixes text and elements"):
        loads("<w>\n<v>x<a>1</a></v></w>", dict[str, dict[str, int]])
    with pytest.raises(XMLError, match="repeats the key 'a'"):
        loads("<v><a>1</a><entry key='a'>2</entry></v>", dict[str, int])


def test_invalid_xml() -> None:
    with pytest.raises(ValidationError) as error:
        Port.model_validate_xml("<Port><number>1</number>")
    (detail,) = error.value.errors()
    assert detail["type"] == "xml_invalid"
    assert detail["msg"].startswith("Invalid XML: ")
    with pytest.raises(ValidationError, match="xml_invalid"):
        TypeAdapter(int).validate_xml("<!DOCTYPE v><v>1</v>")


def test_strict() -> None:
    assert Port.model_validate_xml("<p><number>80</number></p>") == Port(number=80)
    with pytest.raises(ValidationError, match="valid integer"):
        Port.model_validate_xml("<p><number>8x</number></p>")
    with pytest.raises(ValidationError, match="literal_error"):
        Port.model_validate_xml("<p><number>8</number><proto>x</proto></p>")
    with pytest.raises(ValidationError, match="extra_forbidden"):
        TypeAdapter(Strict).validate_xml("<s><a>1</a><b>2</b></s>")
    assert TypeAdapter(Strict).validate_xml("<s><a>1</a></s>") == Strict(a=1)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: int


def test_writer_refuses() -> None:
    with pytest.raises(ValueError, match="cannot hold the character '\\\\x01'"):
        dumps("\x01", "v")
    with pytest.raises(ValueError, match="cannot hold the character '\\\\x0c'"):
        dumps({"\x0c": 1}, "v")
    with pytest.raises(ValueError, match="not an XML element name"):
        dumps(1, "1v")
    with pytest.raises(TypeError, match="cannot write bytes"):
        dumps(b"x", "v")
    with pytest.raises(ValueError, match="not an XML element name"):
        TypeAdapter(int).dump_xml(1, root="a b")


def test_adapter() -> None:
    adapter = TypeAdapter(list[Port])
    value = [Port(number=1), Port(number=2, proto="udp")]
    text = adapter.dump_xml(value, root="ports", indent=1)
    assert text.startswith(b"<ports>\n <item>\n  <number>1</number>")
    assert adapter.validate_xml(text) == value
    assert TypeAdapter(Count).dump_xml(Count(3)) == b"<value>3</value>"
    assert TypeAdapter(Port | None).dump_xml(None, exclude_none=True) == b'<value nil="true" />'
