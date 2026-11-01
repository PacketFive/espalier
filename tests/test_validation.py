# SPDX-License-Identifier: GPL-2.0
"""Validation of values against types, constraints and modes.

The expected types and messages are those pydantic 2 gives for the same
input, recorded by running both on the same cases.
"""

# The tests give models input their annotations do not allow, to check
# how it is converted or refused.
# pyright: reportArgumentType=false

from __future__ import annotations

import datetime
import enum
import pathlib
from typing import Annotated, Any, Literal

import pytest

from espalier import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError


class Colour(enum.StrEnum):
    RED = "red"
    BLUE = "blue"


class Inner(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    x: int


class Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    i: int = 0
    f: float = 0.0
    t: tuple[str, ...] = ()
    inner: Inner | None = None
    colour: Colour = Colour.RED
    d: dict[int, str] = {}
    dt: datetime.datetime | None = None
    lit: Literal["switch", "boot", "test"] = "switch"
    s: str = Field(default="xx", min_length=2)
    p: str = Field(default="ab", pattern=r"^[a-z]+$")
    g: int = Field(default=1, ge=0)
    tt: tuple[str, ...] = Field(default=("a",), min_length=1, max_length=1)
    fs: frozenset[str] = frozenset()


class Lax(BaseModel):
    v: int | str | None = None
    items: list[Any] = []
    t: tuple[int, ...] = ()
    b: bool = False
    f: float = 0.0
    i: int = 0
    s: set[int] = set()
    path: pathlib.Path | None = None


def _errors(run: Any) -> list[tuple[str, tuple[Any, ...], str]]:
    with pytest.raises(ValidationError) as info:
        run()
    return [(e["type"], e["loc"], e["msg"]) for e in info.value.errors()]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"i": "1"}, ("int_type", ("i",), "Input should be a valid integer")),
        ({"i": True}, ("int_type", ("i",), "Input should be a valid integer")),
        ({"f": True}, ("float_type", ("f",), "Input should be a valid number")),
        ({"t": ["a"]}, ("tuple_type", ("t",), "Input should be a valid tuple")),
        ({"t": "ab"}, ("tuple_type", ("t",), "Input should be a valid tuple")),
        (
            {"colour": "red"},
            ("is_instance_of", ("colour",), "Input should be an instance of Colour"),
        ),
        ({"d": {"1": "a"}}, ("int_type", ("d", "1", "[key]"), "Input should be a valid integer")),
        ({"d": []}, ("dict_type", ("d",), "Input should be a valid dictionary")),
        (
            {"dt": "2024-01-02T03:04:05Z"},
            ("datetime_type", ("dt",), "Input should be a valid datetime"),
        ),
        (
            {"lit": "x"},
            ("literal_error", ("lit",), "Input should be 'switch', 'boot' or 'test'"),
        ),
        ({"s": "a"}, ("string_too_short", ("s",), "String should have at least 2 characters")),
        ({"s": 1}, ("string_type", ("s",), "Input should be a valid string")),
        (
            {"p": "A1"},
            ("string_pattern_mismatch", ("p",), "String should match pattern '^[a-z]+$'"),
        ),
        ({"g": -1}, ("greater_than_equal", ("g",), "Input should be greater than or equal to 0")),
        (
            {"tt": ()},
            ("too_short", ("tt",), "Tuple should have at least 1 item after validation, not 0"),
        ),
        (
            {"tt": ("a", "b")},
            ("too_long", ("tt",), "Tuple should have at most 1 item after validation, not 2"),
        ),
        ({"zz": 1}, ("extra_forbidden", ("zz",), "Extra inputs are not permitted")),
        ({"fs": {"a"}}, ("frozen_set_type", ("fs",), "Input should be a valid frozenset")),
        (
            {"inner": 3},
            ("model_type", ("inner",), "Input should be a valid dictionary or instance of Inner"),
        ),
        ({"inner": {}}, ("missing", ("inner", "x"), "Field required")),
    ],
)
def test_strict_python_errors(data: dict[str, Any], expected: tuple[Any, ...]) -> None:
    assert _errors(lambda: Strict(**data)) == [expected]


def test_strict_python_accepts() -> None:
    model = Strict(inner={"x": 1}, f=1, fs=frozenset({"a"}), d={1: "a"})
    assert model.inner == Inner(x=1)
    assert model.f == 1.0
    assert isinstance(model.f, float)
    assert model.fs == frozenset({"a"})


def test_strict_json_converts_containers() -> None:
    model = Strict.model_validate_json(
        '{"t":["a"],"colour":"blue","d":{"1":"a"},"dt":"2024-01-02T03:04:05Z","fs":["a"],"f":1}'
    )
    assert model.t == ("a",)
    assert model.colour is Colour.BLUE
    assert model.d == {1: "a"}
    assert model.dt == datetime.datetime(2024, 1, 2, 3, 4, 5, tzinfo=datetime.UTC)
    assert model.fs == frozenset({"a"})
    assert model.f == 1.0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"colour":"green"}', ("enum", ("colour",), "Input should be 'red' or 'blue'")),
        ('{"i":1.0}', ("int_type", ("i",), "Input should be a valid integer")),
        ("3", ("model_type", (), "Input should be a valid dictionary or instance of Strict")),
    ],
)
def test_strict_json_errors(text: str, expected: tuple[Any, ...]) -> None:
    assert _errors(lambda: Strict.model_validate_json(text)) == [expected]


def test_invalid_json() -> None:
    [(kind, loc, msg)] = _errors(lambda: Strict.model_validate_json("{"))
    assert (kind, loc) == ("json_invalid", ())
    assert msg.startswith("Invalid JSON: ")


def test_every_error_is_reported() -> None:
    assert [e[0] for e in _errors(lambda: Strict(s="a", g=-1, i="x"))] == [
        "int_type",
        "string_too_short",
        "greater_than_equal",
    ]


def test_lax_conversions() -> None:
    assert Lax(t=[1, "2"]).t == (1, 2)
    assert Lax(b="yes").b is True
    assert Lax(b="off").b is False
    assert Lax(v="1").v == "1"
    assert Lax(v=1.0).v == 1
    assert Lax(items=(1,)).items == [1]
    assert Lax(f="1.5").f == 1.5
    assert Lax(i="7").i == 7
    assert Lax(i=3.0).i == 3
    assert Lax(s=[1, 1, 2]).s == {1, 2}
    assert Lax(path="/x").path == pathlib.Path("/x")


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        ({"b": "maybe"}, "bool_parsing"),
        ({"b": 2}, "bool_parsing"),
        ({"i": 3.5}, "int_from_float"),
        ({"i": "x"}, "int_parsing"),
        ({"f": "x"}, "float_parsing"),
        ({"t": 3}, "tuple_type"),
        ({"items": 3}, "list_type"),
        ({"s": 3}, "set_type"),
    ],
)
def test_lax_errors(data: dict[str, Any], kind: str) -> None:
    assert _errors(lambda: Lax(**data))[0][0] == kind


def test_union_errors_name_each_member() -> None:
    errors = _errors(lambda: Lax(v=[]))
    assert [loc for _, loc, _ in errors] == [("v", "int"), ("v", "str")]


@pytest.mark.parametrize(
    ("tp", "value", "kind"),
    [
        (Annotated[int, Field(gt=1)], 1, "greater_than"),
        (Annotated[int, Field(lt=1)], 1, "less_than"),
        (Annotated[int, Field(le=1)], 2, "less_than_equal"),
        (Annotated[int, Field(multiple_of=2)], 3, "multiple_of"),
        (Annotated[str, Field(max_length=1)], "ab", "string_too_long"),
        (Annotated[list[int], Field(min_length=1)], [], "too_short"),
        (Annotated[dict[str, int], Field(max_length=0)], {"a": 1}, "too_long"),
    ],
)
def test_constraints(tp: Any, value: Any, kind: str) -> None:
    assert _errors(lambda: TypeAdapter(tp).validate_python(value))[0][0] == kind


def test_constraint_messages() -> None:
    adapter = TypeAdapter(Annotated[str, Field(min_length=1)])
    assert _errors(lambda: adapter.validate_python("")) == [
        ("string_too_short", (), "String should have at least 1 character")
    ]


class Cat(BaseModel):
    kind: Literal["cat"] = "cat"
    lives: int = 9


class Dog(BaseModel):
    kind: Literal["dog"] = "dog"
    good: bool = True


class Owner(BaseModel):
    pet: Annotated[Cat | Dog, Field(discriminator="kind")]
    pets: list[Annotated[Cat | Dog, Field(discriminator="kind")]] = []


def test_discriminated_union() -> None:
    owner = Owner.model_validate({"pet": {"kind": "dog"}, "pets": [{"kind": "cat", "lives": 3}]})
    assert owner.pet == Dog()
    assert owner.pets == [Cat(lives=3)]
    assert Owner(pet=Cat()).pet == Cat()


def test_discriminated_union_errors() -> None:
    assert _errors(lambda: Owner.model_validate({"pet": {"kind": "cat", "lives": "x"}})) == [
        (
            "int_parsing",
            ("pet", "cat", "lives"),
            "Input should be a valid integer, unable to parse string as an integer",
        )
    ]
    [(kind, loc, _)] = _errors(lambda: Owner.model_validate({"pet": {"kind": "fish"}}))
    assert (kind, loc) == ("union_tag_invalid", ("pet",))
    [(kind, loc, _)] = _errors(lambda: Owner.model_validate({"pet": {}}))
    assert (kind, loc) == ("union_tag_not_found", ("pet",))


class Node(BaseModel):
    name: str
    children: list[Node] = []


def test_recursive_model() -> None:
    tree = Node.model_validate({"name": "a", "children": [{"name": "b"}]})
    assert tree.children[0].name == "b"
    assert _errors(lambda: Node.model_validate({"name": "a", "children": [{}]})) == [
        ("missing", ("children", 0, "name"), "Field required")
    ]


def test_datetime_and_date_parsing() -> None:
    adapter = TypeAdapter(datetime.datetime)
    assert adapter.validate_python("2024-01-02T03:04:05") == datetime.datetime(2024, 1, 2, 3, 4, 5)
    assert adapter.validate_json('"2024-01-02T03:04:05+01:00"').utcoffset() == datetime.timedelta(
        hours=1
    )
    assert TypeAdapter(datetime.date).validate_python("2024-01-02") == datetime.date(2024, 1, 2)
    assert _errors(lambda: adapter.validate_python("nope"))[0][0] == "datetime_parsing"


def test_bytes_none_and_any() -> None:
    assert TypeAdapter(bytes).validate_python("ab") == b"ab"
    assert TypeAdapter(None).validate_python(None) is None
    assert _errors(lambda: TypeAdapter(None).validate_python(1))[0][0] == "none_required"
    marker = object()
    assert TypeAdapter(Any).validate_python(marker) is marker


def test_arbitrary_class_is_checked_with_isinstance() -> None:
    class Thing:
        pass

    thing = Thing()
    adapter = TypeAdapter(Thing)
    assert adapter.validate_python(thing) is thing
    assert _errors(lambda: adapter.validate_python(1))[0][0] == "is_instance_of"


def test_field_strict_overrides_model() -> None:
    class Mixed(BaseModel):
        loose: int = 0
        tight: int = Field(default=0, strict=True)

    assert Mixed(loose="1").loose == 1
    assert _errors(lambda: Mixed(tight="1"))[0][:2] == ("int_type", ("tight",))


def test_strict_argument() -> None:
    assert _errors(lambda: Lax.model_validate({"i": "1"}, strict=True))[0][0] == "int_type"
    assert TypeAdapter(int).validate_python("1") == 1
    assert _errors(lambda: TypeAdapter(int).validate_python("1", strict=True))[0][0] == "int_type"
