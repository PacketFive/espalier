# SPDX-License-Identifier: GPL-2.0
"""Models: fields, defaults, aliases, validators, copies and equality."""

# The tests give models input their annotations do not allow, to check
# how it is converted or refused.
# pyright: reportArgumentType=false, reportCallIssue=false, reportUnhashable=false

from __future__ import annotations

import copy
import pickle
from typing import Annotated, Any, ClassVar, Self

import pytest

from espalier import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    PlainValidator,
    ValidationError,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
    to_camel,
    to_pascal,
    to_snake,
)


class Point(BaseModel):
    model_config = ConfigDict(frozen=True)
    x: int
    y: int = 0


class Bag(BaseModel):
    items: list[int] = []
    tags: dict[str, str] = Field(default_factory=dict)
    note: str | None = Field(default=None, repr=False)
    counter: ClassVar[int] = 0
    _private: int = 0


def _types(run: Any) -> list[str]:
    with pytest.raises(ValidationError) as info:
        run()
    return [e["type"] for e in info.value.errors()]


def test_fields_and_defaults() -> None:
    assert list(Bag.model_fields) == ["items", "tags", "note"]
    assert Point.model_fields["x"].is_required()
    assert not Point.model_fields["y"].is_required()
    first, second = Bag(), Bag()
    first.items.append(1)
    first.tags["a"] = "b"
    assert second.items == []
    assert second.tags == {}


def test_fields_set() -> None:
    assert Point(x=1).model_fields_set == {"x"}
    assert Point(x=1, y=0).model_fields_set == {"x", "y"}


def test_frozen() -> None:
    point = Point(x=1)
    with pytest.raises(ValidationError) as info:
        point.x = 2  # type: ignore[misc]
    assert info.value.errors()[0]["type"] == "frozen_instance"
    assert str(info.value) == (
        "1 validation error for Point\nx\n"
        "  Instance is frozen [type=frozen_instance, input_value=2, input_type=int]"
    )
    with pytest.raises(ValidationError):
        del point.x
    assert hash(point) == hash(Point(x=1))
    assert {point, Point(x=1)} == {point}


def test_mutable_model() -> None:
    bag = Bag()
    bag.items = [3]
    assert bag.items == [3]
    del bag.note
    with pytest.raises(TypeError, match="unhashable"):
        hash(bag)


def test_equality() -> None:
    assert Point(x=1) == Point(x=1)
    assert Point(x=1) != Point(x=2)
    assert Point(x=1) != Bag()
    assert Point(x=1) != 1

    class Other(Point):
        pass

    assert Other(x=1) != Point(x=1)


def test_repr_and_iter() -> None:
    assert repr(Point(x=1)) == "Point(x=1, y=0)"
    assert str(Point(x=1)) == "x=1 y=0"
    assert repr(Bag(note="n")) == "Bag(items=[], tags={})"
    assert dict(Point(x=1, y=2)) == {"x": 1, "y": 2}


def test_extra_policies() -> None:
    class Ignore(BaseModel):
        a: int = 0

    class Allow(BaseModel):
        model_config = ConfigDict(extra="allow")
        a: int = 0

    assert Ignore(a=1, b=2).model_dump() == {"a": 1}
    allowed = Allow(a=1, b=2)
    assert allowed.model_extra == {"b": 2}
    assert allowed.b == 2  # type: ignore[attr-defined]
    assert allowed.model_dump() == {"a": 1, "b": 2}
    assert Ignore().model_extra is None


def test_aliases() -> None:
    class Wire(BaseModel):
        model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
        container_id: str
        host: str = Field(default="h", alias="hostName")

    wire = Wire.model_validate({"containerId": "c", "hostName": "x"})
    assert (wire.container_id, wire.host) == ("c", "x")
    assert Wire(container_id="c").container_id == "c"
    assert wire.model_dump(by_alias=True) == {"containerId": "c", "hostName": "x"}
    assert wire.model_dump() == {"container_id": "c", "host": "x"}

    class Only(BaseModel):
        value: int = Field(alias="v")

    assert _types(lambda: Only.model_validate({"value": 1})) == ["missing"]


def test_alias_generators() -> None:
    assert [to_camel("container_id"), to_camel("a"), to_camel("oci_version")] == [
        "containerId",
        "a",
        "ociVersion",
    ]
    assert to_pascal("host_id") == "HostId"
    assert to_snake("containerId") == "container_id"
    assert to_snake("HostID") == "host_id"


def test_config_is_inherited_and_merged() -> None:
    class Base(BaseModel):
        model_config = ConfigDict(frozen=True, extra="forbid")
        a: int = 0

    class Child(Base):
        model_config = ConfigDict(strict=True)
        b: int = 0

    assert list(Child.model_fields) == ["a", "b"]
    assert _types(lambda: Child(b="1")) == ["int_type"]
    assert _types(lambda: Child(c=1)) == ["extra_forbidden"]
    with pytest.raises(ValidationError):
        Child().a = 1  # type: ignore[misc]


class Checked(BaseModel):
    name: str
    size: int = 0
    seen: list[str] = []

    @field_validator("name", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("name")
    @classmethod
    def _lower(cls, value: str, info: ValidationInfo) -> str:
        assert info.field_name == "name"
        if not value:
            raise ValueError("empty name")
        return value.lower()

    @field_validator("size")
    @classmethod
    def _positive(cls, value: int, info: ValidationInfo) -> int:
        assert value >= 0, "size is negative"
        assert info.data["name"]
        return value

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.name == "boom":
            raise ValueError("no boom")
        return self


def test_field_validators() -> None:
    assert Checked(name="  ABC ").name == "abc"
    with pytest.raises(ValidationError) as info:
        Checked(name=" ")
    [error] = info.value.errors()
    assert (error["type"], error["msg"]) == ("value_error", "Value error, empty name")
    with pytest.raises(ValidationError) as info:
        Checked(name="a", size=-1)
    [error] = info.value.errors()
    assert error["type"] == "assertion_error"
    assert error["msg"].startswith("Assertion failed, size is negative")
    assert _types(lambda: Checked(name="boom")) == ["value_error"]


def test_plain_field_validator() -> None:
    class Plain(BaseModel):
        value: int = 0

        @field_validator("value", mode="plain")
        @classmethod
        def _any(cls, value: Any) -> int:
            return len(value)

    assert Plain(value="abc").value == 3


def test_validator_for_unknown_field() -> None:
    with pytest.raises(TypeError, match="no field 'other'"):

        class Wrong(BaseModel):
            value: int = 0

            @field_validator("other")
            @classmethod
            def _check(cls, value: int) -> int:
                return value

        Wrong()


class Wrapped(BaseModel):
    value: int = 0
    calls: ClassVar[list[str]] = []

    @model_validator(mode="before")
    @classmethod
    def _before(cls, data: Any) -> Any:
        if isinstance(data, int):
            return {"value": data}
        return data

    @model_validator(mode="wrap")
    @classmethod
    def _wrap(cls, data: Any, handler: ModelWrapValidatorHandler[Wrapped]) -> Wrapped:
        cls.calls.append("wrap")
        try:
            return handler(data)
        except ValidationError:
            return cls.model_construct(value=-1)


def test_model_validators() -> None:
    assert Wrapped.model_validate(5).value == 5
    assert Wrapped.model_validate({"value": "x"}).value == -1
    assert Wrapped.calls


def test_annotated_validators() -> None:
    def double(value: int) -> int:
        return value * 2

    def parse(value: Any, info: ValidationInfo) -> Any:
        return int(value) if info.mode == "python" and isinstance(value, str) else value

    class Pipes(BaseModel):
        model_config = ConfigDict(strict=True)
        a: Annotated[int, BeforeValidator(parse), AfterValidator(double)] = 0
        b: Annotated[str, PlainValidator(str)] = ""

    pipes = Pipes(a="2", b=3)
    assert (pipes.a, pipes.b) == (4, "3")


def test_unexpected_exception_escapes() -> None:
    class Broken(BaseModel):
        value: int = 0

        @field_validator("value")
        @classmethod
        def _fail(cls, value: int) -> int:
            raise KeyError(value)

    with pytest.raises(KeyError):
        Broken(value=1)


class Sized(BaseModel):
    model_config = ConfigDict(frozen=True)
    width: int
    height: int

    @computed_field
    @property
    def area(self) -> int:
        return self.width * self.height


def test_computed_fields() -> None:
    sized = Sized(width=2, height=3)
    assert sized.area == 6
    assert Sized.model_computed_fields == ("area",)
    assert sized.model_dump() == {"width": 2, "height": 3, "area": 6}
    assert sized.model_dump_json() == '{"width":2,"height":3,"area":6}'


def test_model_construct_and_copy() -> None:
    point = Point.model_construct(x=1)
    assert (point.x, point.y) == (1, 0)
    assert point.model_fields_set == {"x"}
    moved = point.model_copy(update={"y": 5})
    assert (moved.x, moved.y) == (1, 5)
    assert moved.model_fields_set == {"x", "y"}
    bag = Bag(items=[1])
    shallow, deep = bag.model_copy(), bag.model_copy(deep=True)
    assert shallow.items is bag.items
    assert deep.items == bag.items
    assert deep.items is not bag.items
    assert copy.copy(bag) == bag
    assert copy.deepcopy(bag).items is not bag.items


def test_pickle() -> None:
    sized = Sized(width=2, height=3)
    assert sized.area == 6
    restored = pickle.loads(pickle.dumps(sized))  # noqa: S301
    assert restored == sized
    assert restored.model_fields_set == {"width", "height"}
    assert hash(restored) == hash(sized)


def test_instance_is_not_revalidated() -> None:
    point = Point(x=1)
    assert Point.model_validate(point) is point

    class Holder(BaseModel):
        point: Point

    assert Holder(point=point).point is point


class Later(BaseModel):
    child: Child | None = None


class Child(BaseModel):
    value: int = 0


def test_forward_reference_and_rebuild() -> None:
    assert Later(child={"value": 1}).child == Child(value=1)
    assert Later.model_rebuild() is True


def test_unresolved_forward_reference() -> None:
    class Dangling(BaseModel):
        other: Missing  # type: ignore[name-defined]  # noqa: F821

    assert Dangling.model_rebuild(raise_errors=False) is False
    with pytest.raises(NameError):
        Dangling.model_rebuild()


class Leaf(BaseModel):
    model_config = ConfigDict(strict=False)
    n: int = 0


class Tree(BaseModel):
    leaf: Leaf = Leaf()
    n: int = 0
    loose: int = Field(default=0, strict=False)


def test_strict_override_reaches_nested_models() -> None:
    assert Tree.model_validate({"leaf": {"n": "1"}, "n": "2"}).leaf.n == 1
    with pytest.raises(ValidationError) as info:
        Tree.model_validate({"leaf": {"n": "1"}, "n": "2", "loose": "3"}, strict=True)
    assert [e["loc"] for e in info.value.errors()] == [("leaf", "n"), ("n",)]
    assert Tree.model_validate_json('{"n":"2"}', strict=False).n == 2
    with pytest.raises(ValidationError):
        Tree.model_validate_json('{"n":"2"}', strict=True)
