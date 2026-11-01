# SPDX-License-Identifier: GPL-2.0
"""Turning a type annotation into a function that validates values of it.

A validator is called as ``validate(value, info)`` and returns the
validated value or raises Invalid. ``info.mode`` is ``"json"`` when the
value was decoded from JSON, where a list stands for a tuple or set and
a string for an enum or datetime.
"""

from __future__ import annotations

import collections
import datetime
import enum
import pathlib
import re
import types
import typing
from collections.abc import Callable, Mapping
from typing import Any

from .errors import Invalid, from_exception, invalid
from .fields import FieldInfo
from .functional import (
    AfterValidator,
    BeforeValidator,
    PlainSerializer,
    PlainValidator,
    ValidationInfo,
    wants_info,
)

Validator = Callable[[Any, ValidationInfo], Any]

_cache: dict[tuple[object, bool], Validator] = {}

_SEQUENCES = (
    list,
    tuple,
    set,
    frozenset,
    collections.deque,
    types.GeneratorType,
    type({}.keys()),
    type({}.values()),
)
_TRUE = {"1", "on", "t", "true", "y", "yes"}
_FALSE = {"0", "off", "f", "false", "n", "no"}


def is_model(tp: object) -> bool:
    """Return whether ``tp`` is a model class."""
    return isinstance(tp, type) and hasattr(tp, "__espalier_fields__")


def split_annotated(tp: Any) -> tuple[Any, list[Any]]:
    """Return the type under any Annotated layers and their metadata, outer last."""
    metadata: list[Any] = []
    while typing.get_origin(tp) is typing.Annotated:
        metadata[:0] = list(tp.__metadata__)
        tp = tp.__origin__
    return tp, metadata


def build(tp: Any, strict: bool) -> Validator:
    """Return the validator of ``tp``, from a cache when possible."""
    try:
        key = (tp, strict)
        found = _cache.get(key)
    except TypeError:
        return _build(tp, strict)
    if found is None:
        found = _cache[key] = _build(tp, strict)
    return found


def _call(function: Callable[..., Any], value: Any, info: ValidationInfo) -> Any:
    try:
        if wants_info(function, 1):
            return function(value, info)
        return function(value)
    except (ValueError, AssertionError) as error:
        raise from_exception(error, value) from None


def _build(tp: Any, strict: bool) -> Validator:
    tp, metadata = split_annotated(tp)
    if not metadata:
        return _base(tp, strict)
    merged = FieldInfo()
    for item in metadata:
        if isinstance(item, FieldInfo):
            merged = merged.merge(item)
    if merged.strict is not None:
        strict = merged.strict
    base: Validator
    if merged.discriminator is not None:
        base = _discriminated(tp, merged.discriminator)
    else:
        base = build(tp, strict)
    checks = _constraints(tp, merged)
    if checks is not None:
        inner, check = base, checks

        def checked(value: Any, info: ValidationInfo) -> Any:
            return check(inner(value, info))

        base = checked

    for item in metadata:
        if isinstance(item, PlainValidator):
            function = item.func
            base = _plain(function)
        elif isinstance(item, AfterValidator):
            base = _after(base, item.func)
        elif isinstance(item, BeforeValidator):
            base = _before(base, item.func)
        elif not isinstance(item, (FieldInfo, PlainSerializer)):
            continue
    return base


def _plain(function: Callable[..., Any]) -> Validator:
    def validate(value: Any, info: ValidationInfo) -> Any:
        return _call(function, value, info)

    return validate


def _after(inner: Validator, function: Callable[..., Any]) -> Validator:
    def validate(value: Any, info: ValidationInfo) -> Any:
        return _call(function, inner(value, info), info)

    return validate


def _before(inner: Validator, function: Callable[..., Any]) -> Validator:
    def validate(value: Any, info: ValidationInfo) -> Any:
        return inner(_call(function, value, info), info)

    return validate


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _constraints(tp: Any, field: FieldInfo) -> Callable[[Any], Any] | None:
    found = field.constraints()
    if not found:
        return None
    origin = typing.get_origin(tp) or tp
    label = {
        tuple: "Tuple",
        list: "List",
        dict: "Dictionary",
        set: "Set",
        frozenset: "Frozenset",
    }.get(origin, "Value")
    pattern = re.compile(found["pattern"]) if "pattern" in found else None

    def check(value: Any) -> Any:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            for name, kind, words in (
                ("gt", "greater_than", "greater than"),
                ("ge", "greater_than_equal", "greater than or equal to"),
                ("lt", "less_than", "less than"),
                ("le", "less_than_equal", "less than or equal to"),
            ):
                if name in found:
                    bound = found[name]
                    ok = {
                        "gt": value > bound,
                        "ge": value >= bound,
                        "lt": value < bound,
                        "le": value <= bound,
                    }[name]
                    if not ok:
                        raise invalid(
                            kind, f"Input should be {words} {bound}", value, **{name: bound}
                        )
            if "multiple_of" in found and value % found["multiple_of"]:
                step = found["multiple_of"]
                raise invalid("multiple_of", f"Input should be a multiple of {step}", value)
        if isinstance(value, str):
            length = len(value)
            if "min_length" in found and length < found["min_length"]:
                least = found["min_length"]
                raise invalid(
                    "string_too_short",
                    f"String should have at least {_plural(least, 'character')}",
                    value,
                    min_length=least,
                )
            if "max_length" in found and length > found["max_length"]:
                most = found["max_length"]
                raise invalid(
                    "string_too_long",
                    f"String should have at most {_plural(most, 'character')}",
                    value,
                    max_length=most,
                )
            if pattern is not None and not pattern.search(value):
                raise invalid(
                    "string_pattern_mismatch",
                    f"String should match pattern '{pattern.pattern}'",
                    value,
                    pattern=pattern.pattern,
                )
        elif isinstance(value, (tuple, list, dict, set, frozenset)):
            length = len(value)
            if "min_length" in found and length < found["min_length"]:
                least = found["min_length"]
                raise invalid(
                    "too_short",
                    f"{label} should have at least {_plural(least, 'item')} after validation, "
                    f"not {length}",
                    value,
                )
            if "max_length" in found and length > found["max_length"]:
                most = found["max_length"]
                raise invalid(
                    "too_long",
                    f"{label} should have at most {_plural(most, 'item')} after validation, "
                    f"not {length}",
                    value,
                )
        return value

    return check


def _expected(values: list[Any]) -> str:
    shown = [repr(value) for value in values]
    if len(shown) == 1:
        return shown[0]
    return f"{', '.join(shown[:-1])} or {shown[-1]}"


def _base(tp: Any, strict: bool) -> Validator:  # noqa: C901
    if tp is Any or tp is object:
        return _any
    if isinstance(tp, typing.TypeAliasType):
        return build(tp.__value__, strict)
    if isinstance(tp, typing.NewType):
        return build(tp.__supertype__, strict)
    if isinstance(tp, typing.TypeVar):
        return _any
    if tp is None or tp is type(None):
        return _none
    if is_model(tp):
        return tp.__espalier_validator__
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Union or origin is types.UnionType:
        return _union(args, strict)
    if origin is typing.Literal:
        return _literal(args)
    if tp is str:
        return _str
    if tp is bool:
        return _bool_strict if strict else _bool_lax
    if tp is int:
        return _int_strict if strict else _int_lax
    if tp is float:
        return _float_strict if strict else _float_lax
    if tp is bytes:
        return _bytes(strict)
    if tp is datetime.date:
        return _date(strict)
    if isinstance(tp, type) and issubclass(tp, pathlib.PurePath):
        return _path(tp, strict)
    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        return _enum(tp, strict)
    if tp is datetime.datetime:
        return _datetime(strict)
    if origin in (tuple, typing.Tuple) or tp in (tuple, typing.Tuple):  # noqa: UP006
        return _tuple(args, strict)
    if origin in (list, typing.List) or tp in (list, typing.List):  # noqa: UP006
        return _collection(list, "list_type", "list", args, strict)
    if origin in (set, typing.Set) or tp in (set, typing.Set):  # noqa: UP006
        return _collection(set, "set_type", "set", args, strict)
    if origin in (frozenset, typing.FrozenSet) or tp in (frozenset, typing.FrozenSet):  # noqa: UP006
        return _collection(frozenset, "frozen_set_type", "frozenset", args, strict)
    if origin in (dict, typing.Dict, Mapping) or tp in (dict, typing.Dict, Mapping):  # noqa: UP006
        return _dict(args, strict)
    if origin is type:
        return _subclass(args[0] if args else object)
    if isinstance(tp, type):
        return _instance(tp)
    raise TypeError(f"espalier cannot validate the type {tp!r}")


def _any(value: Any, info: ValidationInfo) -> Any:
    return value


def _none(value: Any, info: ValidationInfo) -> Any:
    if value is not None:
        raise invalid("none_required", "Input should be None", value)
    return value


def _str(value: Any, info: ValidationInfo) -> Any:
    if not isinstance(value, str):
        raise invalid("string_type", "Input should be a valid string", value)
    return value


def _bool_strict(value: Any, info: ValidationInfo) -> Any:
    if type(value) is not bool:
        raise invalid("bool_type", "Input should be a valid boolean", value)
    return value


def _bool_lax(value: Any, info: ValidationInfo) -> Any:
    if type(value) is bool:
        return value
    if isinstance(value, (int, float)):
        if value in (0, 1):
            return bool(value)
        raise invalid(
            "bool_parsing", "Input should be a valid boolean, unable to interpret input", value
        )
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise invalid(
            "bool_parsing", "Input should be a valid boolean, unable to interpret input", value
        )
    raise invalid("bool_type", "Input should be a valid boolean", value)


def _int_strict(value: Any, info: ValidationInfo) -> Any:
    if not isinstance(value, int) or isinstance(value, bool):
        raise invalid("int_type", "Input should be a valid integer", value)
    return value


def _int_lax(value: Any, info: ValidationInfo) -> Any:
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise invalid(
            "int_from_float",
            "Input should be a valid integer, got a number with a fractional part",
            value,
        )
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            raise invalid(
                "int_parsing",
                "Input should be a valid integer, unable to parse string as an integer",
                value,
            ) from None
    raise invalid("int_type", "Input should be a valid integer", value)


def _float_strict(value: Any, info: ValidationInfo) -> Any:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise invalid("float_type", "Input should be a valid number", value)
    return float(value)


def _float_lax(value: Any, info: ValidationInfo) -> Any:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            raise invalid(
                "float_parsing",
                "Input should be a valid number, unable to parse string as a number",
                value,
            ) from None
    raise invalid("float_type", "Input should be a valid number", value)


def _instance(cls: type) -> Validator:
    def validate(value: Any, info: ValidationInfo) -> Any:
        if not isinstance(value, cls):
            raise invalid("is_instance_of", f"Input should be an instance of {cls.__name__}", value)
        return value

    return validate


def _subclass(cls: Any) -> Validator:
    def validate(value: Any, info: ValidationInfo) -> Any:
        if not isinstance(value, type) or (isinstance(cls, type) and not issubclass(value, cls)):
            name = getattr(cls, "__name__", repr(cls))
            raise invalid("is_subclass_of", f"Input should be a subclass of {name}", value)
        return value

    return validate


def _literal(expected: tuple[Any, ...]) -> Validator:
    allowed = [(type(value), value) for value in expected]
    message = f"Input should be {_expected(list(expected))}"

    def validate(value: Any, info: ValidationInfo) -> Any:
        for kind, item in allowed:
            if value == item and (
                type(value) is kind or (isinstance(value, kind) and kind is not int)
            ):
                return item
        raise invalid("literal_error", message, value, expected=_expected(list(expected)))

    return validate


def _enum(cls: type[enum.Enum], strict: bool) -> Validator:
    values = [member.value for member in cls]
    message = f"Input should be {_expected(values)}"

    def validate(value: Any, info: ValidationInfo) -> Any:
        if isinstance(value, cls):
            return value
        if strict and info.mode == "python":
            raise invalid("is_instance_of", f"Input should be an instance of {cls.__name__}", value)
        for member in cls:
            if member.value == value and type(member.value) is type(value):
                return member
        raise invalid("enum", message, value, expected=_expected(values))

    return validate


def _parse_datetime(value: str) -> datetime.datetime:
    text = value.strip()
    if text.endswith(("z", "Z")):
        text = text[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(text)


def _datetime(strict: bool) -> Validator:
    def validate(value: Any, info: ValidationInfo) -> Any:
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, str) and (info.mode == "json" or not strict):
            try:
                return _parse_datetime(value)
            except ValueError as error:
                raise invalid(
                    "datetime_parsing", f"Input should be a valid datetime, {error}", value
                ) from None
        raise invalid("datetime_type", "Input should be a valid datetime", value)

    return validate


def _date(strict: bool) -> Validator:
    def validate(value: Any, info: ValidationInfo) -> Any:
        if type(value) is datetime.date:
            return value
        if isinstance(value, str) and (info.mode == "json" or not strict):
            try:
                return datetime.date.fromisoformat(value.strip())
            except ValueError as error:
                raise invalid(
                    "date_parsing",
                    f"Input should be a valid date in the format YYYY-MM-DD, {error}",
                    value,
                ) from None
        raise invalid("date_type", "Input should be a valid date", value)

    return validate


def _bytes(strict: bool) -> Validator:
    def validate(value: Any, info: ValidationInfo) -> Any:
        if type(value) is bytes:
            return value
        if info.mode == "json" or not strict:
            if isinstance(value, str):
                return value.encode()
            if isinstance(value, (bytes, bytearray)):
                return bytes(value)
        raise invalid("bytes_type", "Input should be a valid bytes", value)

    return validate


def _path(cls: type[pathlib.PurePath], strict: bool) -> Validator:
    def validate(value: Any, info: ValidationInfo) -> Any:
        if isinstance(value, cls):
            return value
        if isinstance(value, str) and (info.mode == "json" or not strict):
            return cls(value)
        raise invalid("path_type", f"Input is not a valid path for {cls!r}", value)

    return validate


def _items(value: Any, item: Validator, info: ValidationInfo) -> list[Any]:
    result = []
    errors: list[dict[str, Any]] = []
    for index, element in enumerate(value):
        try:
            result.append(item(element, info))
        except Invalid as error:
            errors.extend(error.prefixed(index))
    if errors:
        raise Invalid(errors)
    return result


def _accepts(value: Any, kind: type, strict: bool, info: ValidationInfo) -> bool:
    if isinstance(value, kind):
        return True
    if info.mode == "json":
        return isinstance(value, list)
    return not strict and isinstance(value, _SEQUENCES)


def _tuple(args: tuple[Any, ...], strict: bool) -> Validator:
    if not args or (len(args) == 2 and args[1] is Ellipsis):
        item = build(args[0], strict) if args else _any

        def validate(value: Any, info: ValidationInfo) -> Any:
            if not _accepts(value, tuple, strict, info):
                raise invalid("tuple_type", "Input should be a valid tuple", value)
            return tuple(_items(value, item, info))

        return validate
    if args == ((),):
        args = ()
    positions = [build(arg, strict) for arg in args]

    def validate_fixed(value: Any, info: ValidationInfo) -> Any:
        if not _accepts(value, tuple, strict, info):
            raise invalid("tuple_type", "Input should be a valid tuple", value)
        elements = list(value)
        if len(elements) > len(positions):
            raise invalid(
                "too_long",
                f"Tuple should have at most {_plural(len(positions), 'item')} after "
                f"validation, not {len(elements)}",
                value,
            )
        result = []
        errors: list[dict[str, Any]] = []
        for index, check in enumerate(positions):
            if index >= len(elements):
                errors.append(
                    {"type": "missing", "loc": (index,), "msg": "Field required", "input": value}
                )
                continue
            try:
                result.append(check(elements[index], info))
            except Invalid as error:
                errors.extend(error.prefixed(index))
        if errors:
            raise Invalid(errors)
        return tuple(result)

    return validate_fixed


def _collection(
    kind: type, error: str, name: str, args: tuple[Any, ...], strict: bool
) -> Validator:
    item = build(args[0], strict) if args else _any
    article = "a valid"

    def validate(value: Any, info: ValidationInfo) -> Any:
        if not _accepts(value, kind, strict, info) or isinstance(value, (str, bytes)):
            raise invalid(error, f"Input should be {article} {name}", value)
        return kind(_items(value, item, info))

    return validate


def _dict(args: tuple[Any, ...], strict: bool) -> Validator:
    keys = build(args[0], strict) if args else _any
    json_keys = build(args[0], False) if args else _any
    values = build(args[1], strict) if len(args) > 1 else _any

    def validate(value: Any, info: ValidationInfo) -> Any:
        if not isinstance(value, dict) and (strict or not isinstance(value, Mapping)):
            raise invalid("dict_type", "Input should be a valid dictionary", value)
        check_key = json_keys if info.mode == "json" else keys
        result = {}
        errors: list[dict[str, Any]] = []
        for key, item in value.items():
            try:
                key_out = check_key(key, info)
            except Invalid as error:
                errors.extend(error.prefixed(key, "[key]"))
                continue
            try:
                result[key_out] = values(item, info)
            except Invalid as error:
                errors.extend(error.prefixed(key))
        if errors:
            raise Invalid(errors)
        return result

    return validate


def type_label(tp: Any) -> str:
    base, _ = split_annotated(tp)
    if isinstance(base, type):
        return base.__name__
    return repr(base).replace("typing.", "")


def _union(args: tuple[Any, ...], strict: bool) -> Validator:
    members = [arg for arg in args if arg is not type(None)]
    nullable = len(members) != len(args)
    if nullable and len(members) == 1:
        inner = build(members[0], strict)

        def validate_optional(value: Any, info: ValidationInfo) -> Any:
            if value is None:
                return None
            return inner(value, info)

        return validate_optional
    checks = [
        (split_annotated(member)[0], type_label(member), build(member, strict))
        for member in members
    ]

    def validate(value: Any, info: ValidationInfo) -> Any:
        if value is None and nullable:
            return None
        for base, _, check in checks:
            if base is type(value) or (is_model(base) and isinstance(value, base)):
                try:
                    return check(value, info)
                except Invalid:
                    break
        errors: list[dict[str, Any]] = []
        for _, label, check in checks:
            try:
                return check(value, info)
            except Invalid as error:
                errors.extend(error.prefixed(label))
        raise Invalid(errors)

    return validate


def _discriminated(tp: Any, field: str) -> Validator:
    members = [arg for arg in typing.get_args(tp) if arg is not type(None)]
    table: dict[Any, tuple[type, Validator]] = {}
    keys: list[str] = []

    def setup() -> None:
        for member in members:
            base, _ = split_annotated(member)
            if not is_model(base):
                raise TypeError(f"a discriminated union holds models, not {member!r}")
            info = base.model_fields[field]
            for name in (info.alias, field):
                if name is not None and name not in keys:
                    keys.append(name)
            for tag in typing.get_args(split_annotated(info.annotation)[0]):
                table[tag] = (base, build(member, False))

    def validate(value: Any, info: ValidationInfo) -> Any:
        if not table:
            setup()
        for base, _ in table.values():
            if isinstance(value, base):
                return value
        if isinstance(value, dict):
            tag = next((value[key] for key in keys if key in value), None)
        else:
            raise invalid(
                "model_attributes_type",
                "Input should be a valid dictionary or object to extract fields from",
                value,
            )
        if tag is None:
            raise invalid(
                "union_tag_not_found",
                f"Unable to extract tag using discriminator '{field}'",
                value,
                discriminator=f"'{field}'",
            )
        try:
            found = table.get(tag)
        except TypeError:
            found = None
        if found is None:
            expected = ", ".join(repr(key) for key in table)
            raise invalid(
                "union_tag_invalid",
                f"Input tag {tag!r} found using '{field}' does not match any of the expected "
                f"tags: {expected}",
                value,
                tag=tag,
            )
        try:
            return found[1](value, info)
        except Invalid as error:
            raise Invalid(error.prefixed(tag)) from None

    return validate


def serializer_of(tp: Any) -> PlainSerializer | None:
    """Return the last PlainSerializer in the Annotated metadata of ``tp``, if any."""
    _, metadata = split_annotated(tp)
    found = None
    for item in metadata:
        if isinstance(item, PlainSerializer):
            found = item
    return found
