# SPDX-License-Identifier: GPL-2.0
"""Dumps to Python and JSON, TypeAdapter and the text of ValidationError."""

from __future__ import annotations

import datetime
import enum
import pathlib
from typing import Annotated, Any, Literal

import pytest

from espalier import (
    BaseModel,
    ConfigDict,
    Field,
    FieldInfo,
    PlainSerializer,
    SerializationInfo,
    TypeAdapter,
    ValidationError,
    __version__,
    to_camel,
)


class Colour(enum.Enum):
    RED = 1


class Inner(BaseModel):
    model_config = ConfigDict(frozen=True)
    x: int


class Dumped(BaseModel):
    model_config = ConfigDict(frozen=True)
    t: tuple[str, ...] = ()
    inner: Inner | None = None
    colour: Colour = Colour.RED
    d: dict[int, str] = {}
    dt: datetime.datetime | None = None
    fs: frozenset[str] = frozenset()
    path: pathlib.Path = pathlib.Path("/a")
    day: datetime.date = datetime.date(2024, 1, 2)
    raw: bytes = b"ab"
    hidden: int = Field(default=0, exclude=True)


UTC_TIME = datetime.datetime(2024, 1, 2, 3, 4, 5, tzinfo=datetime.UTC)


def test_dump_python_keeps_types() -> None:
    model = Dumped(t=("a",), inner=Inner(x=1), d={1: "x"}, dt=UTC_TIME)
    data = model.model_dump()
    assert data["t"] == ("a",)
    assert data["inner"] == {"x": 1}
    assert data["colour"] is Colour.RED
    assert data["d"] == {1: "x"}
    assert data["dt"] is UTC_TIME
    assert "hidden" not in data


def test_dump_json_mode() -> None:
    model = Dumped(t=("a",), d={1: "x"}, dt=UTC_TIME, fs=frozenset({"a"}))
    assert model.model_dump(mode="json") == {
        "t": ["a"],
        "inner": None,
        "colour": 1,
        "d": {"1": "x"},
        "dt": "2024-01-02T03:04:05Z",
        "fs": ["a"],
        "path": "/a",
        "day": "2024-01-02",
        "raw": "ab",
    }


def test_dump_json_text() -> None:
    assert Inner(x=1).model_dump_json() == '{"x":1}'
    assert Inner(x=1).model_dump_json(indent=2) == '{\n  "x": 1\n}'
    assert Dumped(t=("é",)).model_dump_json().startswith('{"t":["é"]')


def test_dump_options() -> None:
    model = Dumped(inner=Inner(x=1))
    assert model.model_dump(include={"inner"}) == {"inner": {"x": 1}}
    assert "inner" not in model.model_dump(exclude={"inner"})
    assert "dt" not in model.model_dump(exclude_none=True)
    assert '"dt"' not in model.model_dump_json(exclude_none=True)


def test_serialize_by_alias_config() -> None:
    class Wire(BaseModel):
        model_config = ConfigDict(alias_generator=to_camel, serialize_by_alias=True)
        oci_version: str = "1"
        nested: list[Inner] = []

    assert Wire(nested=[Inner(x=1)]).model_dump() == {"ociVersion": "1", "nested": [{"x": 1}]}
    assert Wire().model_dump(by_alias=False) == {"oci_version": "1", "nested": []}


def test_plain_serializer() -> None:
    def hexed(value: int, info: SerializationInfo) -> str | int:
        return hex(value) if info.mode_is_json() else value

    class Number(BaseModel):
        value: Annotated[int, PlainSerializer(hexed)] = 255

    assert Number().model_dump() == {"value": 255}
    assert Number().model_dump_json() == '{"value":"0xff"}'
    adapter = TypeAdapter(Annotated[int, PlainSerializer(lambda value: str(value))])
    assert adapter.dump_python(3) == "3"


def test_datetime_json_forms() -> None:
    adapter = TypeAdapter(datetime.datetime)
    plain = datetime.datetime(2024, 1, 2, 3, 4, 5, 120000)
    offset = plain.replace(microsecond=0, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
    assert adapter.dump_json(plain) == b'"2024-01-02T03:04:05.120000"'
    assert adapter.dump_json(offset) == b'"2024-01-02T03:04:05+01:00"'
    assert TypeAdapter(float).dump_json(1.0) == b"1.0"


def test_type_adapter() -> None:
    adapter = TypeAdapter(list[Inner])
    values = adapter.validate_python([{"x": 1}, Inner(x=2)])
    assert values == [Inner(x=1), Inner(x=2)]
    assert adapter.validate_json(b'[{"x":3}]') == [Inner(x=3)]
    assert adapter.dump_python(values) == [{"x": 1}, {"x": 2}]
    assert adapter.dump_python(values, mode="json") == [{"x": 1}, {"x": 2}]
    assert adapter.dump_json(values, indent=1) == b'[\n {\n  "x": 1\n },\n {\n  "x": 2\n }\n]'


def test_type_adapter_config_and_errors() -> None:
    strict = TypeAdapter(int, config=ConfigDict(strict=True))
    with pytest.raises(ValidationError) as info:
        strict.validate_python("1")
    assert info.value.title == "int"
    assert strict.validate_python("1", strict=False) == 1
    with pytest.raises(ValidationError) as info:
        TypeAdapter(dict[str, int]).validate_python({"a": "x"})
    assert info.value.errors()[0]["loc"] == ("a",)
    with pytest.raises(ValidationError) as info:
        TypeAdapter(Literal["a"]).validate_json("nope")
    assert info.value.errors()[0]["type"] == "json_invalid"


def test_unsupported_type() -> None:
    with pytest.raises(TypeError, match="cannot validate"):
        TypeAdapter(3).validate_python(1)  # type: ignore[call-overload]


def test_validation_error_text() -> None:
    class Limits(BaseModel):
        s: str = Field(default="xx", min_length=2)
        g: int = Field(default=1, ge=0)

    with pytest.raises(ValidationError) as info:
        Limits(s="a", g=-1)
    error = info.value
    assert issubclass(ValidationError, ValueError)
    assert error.error_count() == 2
    assert str(error) == (
        "2 validation errors for Limits\n"
        "s\n"
        "  String should have at least 2 characters "
        "[type=string_too_short, input_value='a', input_type=str]\n"
        "g\n"
        "  Input should be greater than or equal to 0 "
        "[type=greater_than_equal, input_value=-1, input_type=int]"
    )
    [first, _] = error.errors(include_input=False, include_context=False)
    assert "input" not in first
    assert "ctx" not in first


def test_field_info() -> None:
    info = Field(default=1, ge=0, description="d")
    assert isinstance(info, FieldInfo)
    assert info.constraints() == {"ge": 0}
    assert "ge=0" in repr(info)
    assert FieldInfo(default_factory=list).get_default() == []
    merged = FieldInfo(ge=0, repr=False).merge(FieldInfo(default=2, le=5))
    assert (merged.default, merged.ge, merged.le, merged.repr) == (2, 0, 5, False)


def test_version() -> None:
    assert __version__.count(".") == 2


def test_any_values_dump_as_they_are() -> None:
    marker: Any = object()
    assert TypeAdapter(Any).dump_python(marker) is marker
