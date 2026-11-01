# SPDX-License-Identifier: GPL-2.0
"""BaseModel: classes whose instances are validated from their annotations."""

from __future__ import annotations

import copy
import inspect
import json
import sys
import typing
from collections.abc import Callable, Iterator
from typing import Any, ClassVar, Literal, Self, dataclass_transform

from . import _validators, _xml, _yaml
from ._serialize import Mode, dump, serialize, to_json
from .config import ConfigDict
from .errors import Invalid, ValidationError, from_exception, invalid
from .fields import MISSING, ComputedField, Field, FieldInfo
from .functional import Decorated, PlainSerializer, ValidationInfo, wants_info

_ModeIn = Literal["python", "json"]


class _Field:
    __slots__ = ("after", "before", "info", "keys", "name", "plain", "serializer", "validator")

    def __init__(self, name: str, info: FieldInfo, keys: tuple[str, ...]) -> None:
        self.name = name
        self.info = info
        self.keys = keys
        self.validator: _validators.Validator = _validators.build(
            typing.Annotated[info.annotation, info], False
        )
        self.serializer: PlainSerializer | None = _validators.serializer_of(info.annotation)
        self.before: list[Callable[..., Any]] = []
        self.after: list[Callable[..., Any]] = []
        self.plain: Callable[..., Any] | None = None


class _Schema:
    __slots__ = ("after", "before", "computed", "config", "fields", "frozen", "names", "wrap")

    def __init__(self) -> None:
        self.fields: dict[str, _Field] = {}
        self.computed: list[str] = []
        self.before: list[Callable[..., Any]] = []
        self.wrap: list[Callable[..., Any]] = []
        self.after: list[Callable[..., Any]] = []
        self.config: ConfigDict = {}
        self.names: tuple[str, ...] = ()
        self.frozen = False


def _call_validator(
    function: Callable[..., Any],
    fixed: int,
    args: tuple[Any, ...],
    info: ValidationInfo,
    value: Any,
) -> Any:
    try:
        if wants_info(function, fixed):
            return function(*args, info)
        return function(*args)
    except (ValueError, AssertionError) as error:
        raise from_exception(error, value) from None


@dataclass_transform(kw_only_default=True, field_specifiers=(Field, FieldInfo))
class ModelMeta(type):
    """The metaclass of BaseModel, which records each model's configuration."""

    def __new__(
        mcs, name: str, bases: tuple[type, ...], namespace: dict[str, Any], **kwargs: Any
    ) -> ModelMeta:
        """Create a model class and merge its configuration over its bases'."""
        config: dict[str, Any] = {}
        for base in reversed(bases):
            config.update(getattr(base, "__espalier_config__", {}))
        config.update(namespace.get("model_config", {}))
        frozen_eq = config.get("frozen") and "__eq__" in namespace and "__hash__" not in namespace
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)
        frame = sys._getframe(1)
        cls.__espalier_namespace__ = (  # type: ignore[attr-defined]
            None if frame.f_locals is frame.f_globals else dict(frame.f_locals)
        )
        cls.__espalier_config__ = config  # type: ignore[attr-defined]
        cls.__espalier_fields__ = None  # type: ignore[attr-defined]
        cls.model_config = typing.cast(ConfigDict, config)  # type: ignore[attr-defined]
        if frozen_eq:
            cls.__hash__ = BaseModel.__hash__  # type: ignore[method-assign]
        return cls

    @property
    def model_fields(cls) -> dict[str, FieldInfo]:
        """The model's fields by name, each with its annotation and default."""
        schema = _schema(cls)
        return {name: field.info for name, field in schema.fields.items()}

    @property
    def model_computed_fields(cls) -> tuple[str, ...]:
        """The names of the model's computed fields."""
        return tuple(_schema(cls).computed)


def _schema(cls: Any, strict: bool | None = None) -> _Schema:
    schema = cls.__dict__.get("__espalier_fields__")
    if schema is None:
        schema = _build_schema(cls, None)
        cls.__espalier_fields__ = schema
        cls.__espalier_variants__ = {}
    if strict is None or strict == bool(schema.config.get("strict", False)):
        return schema
    variants = cls.__espalier_variants__
    variant = variants.get(strict)
    if variant is None:
        variant = variants[strict] = _build_schema(cls, strict)
    return variant


def _build_schema(cls: Any, override: bool | None) -> _Schema:  # noqa: C901
    """Read the fields of ``cls``; ``override`` replaces the config's ``strict``."""
    schema = _Schema()
    config: ConfigDict = cls.__espalier_config__
    schema.config = config
    localns = dict(cls.__espalier_namespace__ or {})
    localns.setdefault(cls.__name__, cls)
    hints = typing.get_type_hints(cls, localns=localns, include_extras=True)
    strict = bool(config.get("strict", False)) if override is None else override
    generator = config.get("alias_generator")
    by_name = bool(config.get("populate_by_name") or config.get("validate_by_name"))
    by_alias = config.get("validate_by_alias", True)
    models = [klass for klass in reversed(cls.__mro__) if "__espalier_config__" in klass.__dict__]
    for klass in models:
        for name in inspect.get_annotations(klass):
            if name.startswith("_") or name == "model_config":
                continue
            annotation = hints[name]
            if annotation is ClassVar or typing.get_origin(annotation) is ClassVar:
                continue
            info = FieldInfo()
            for item in _validators.split_annotated(annotation)[1]:
                if isinstance(item, FieldInfo):
                    info = info.merge(item)
            raw = klass.__dict__.get(name, MISSING)
            if isinstance(raw, FieldInfo):
                info = info.merge(raw)
            elif raw is not MISSING:
                info.default = raw
            info.annotation = annotation
            if info.strict is None:
                info.strict = strict
            if info.alias is None and generator is not None:
                info.alias = generator(name)
            alias = info.validation_alias or info.alias
            keys: tuple[str, ...]
            if alias is None or alias == name:
                keys = (name,)
            else:
                keys = ((alias,) if by_alias else ()) + ((name,) if by_name or not by_alias else ())
            schema.fields[name] = _Field(name, info, keys)
    for klass in models:
        for attribute, value in klass.__dict__.items():
            if isinstance(value, ComputedField) and attribute not in schema.computed:
                schema.computed.append(attribute)
            if not isinstance(value, Decorated):
                continue
            if value.kind == "field":
                for field_name in value.fields:
                    if field_name not in schema.fields:
                        raise TypeError(f"{cls.__name__}: no field {field_name!r} to validate")
                    target = schema.fields[field_name]
                    bound = value.bound(cls)
                    if value.mode == "before":
                        target.before.append(bound)
                    elif value.mode == "plain":
                        target.plain = bound
                    else:
                        target.after.append(bound)
            elif value.mode == "after":
                schema.after.append(value.raw())
            elif value.mode == "before":
                schema.before.append(value.bound(cls))
            else:
                schema.wrap.append(value.bound(cls))
    schema.names = tuple(schema.fields)
    schema.frozen = bool(config.get("frozen"))
    return schema


def _construct(cls: Any, schema: _Schema, data: Any, mode: _ModeIn, strict: bool | None) -> Any:  # noqa: C901
    if not isinstance(data, dict):
        raise invalid(
            "model_type", f"Input should be a valid dictionary or instance of {cls.__name__}", data
        )
    info = ValidationInfo(mode, strict)
    values: dict[str, Any] = {}
    info.data = values
    fields_set: set[str] = set()
    used: set[str] = set()
    errors: list[dict[str, Any]] = []
    for name, field in schema.fields.items():
        key = None
        for candidate in field.keys:
            if candidate in data:
                key = candidate
                break
        if key is None:
            if field.info.is_required():
                errors.append(
                    {
                        "type": "missing",
                        "loc": (field.keys[0],),
                        "msg": "Field required",
                        "input": data,
                    }
                )
            else:
                values[name] = field.info.get_default()
            continue
        used.add(key)
        raw = data[key]
        info.field_name = name
        try:
            value = raw
            for function in field.before:
                value = _call_validator(function, 1, (value,), info, raw)
            if field.plain is not None:
                value = _call_validator(field.plain, 1, (value,), info, raw)
            else:
                value = field.validator(value, info)
            for function in field.after:
                value = _call_validator(function, 1, (value,), info, value)
        except Invalid as error:
            errors.extend(error.prefixed(key))
            continue
        values[name] = value
        fields_set.add(name)
    extra: dict[str, Any] | None = None
    if len(used) != len(data):
        policy = schema.config.get("extra", "ignore")
        unknown = {key: value for key, value in data.items() if key not in used}
        if policy == "forbid":
            errors.extend(
                {
                    "type": "extra_forbidden",
                    "loc": (key,),
                    "msg": "Extra inputs are not permitted",
                    "input": value,
                }
                for key, value in unknown.items()
            )
        elif policy == "allow":
            extra = unknown
    if errors:
        raise Invalid(errors)
    instance = cls.__new__(cls)
    vars(instance).update(values)
    if extra:
        vars(instance).update(extra)
    object.__setattr__(instance, "__espalier_fields_set__", fields_set)
    object.__setattr__(instance, "__espalier_extra__", extra)
    for function in schema.after:
        info.field_name = None
        result = _call_validator(function, 1, (instance,), info, instance)
        if result is not None:
            instance = result
    return instance


def _validate(cls: Any, data: Any, mode: _ModeIn, strict: bool | None = None) -> Any:
    if isinstance(data, cls):
        return data
    schema = _schema(cls, strict)

    def construct(value: Any) -> Any:
        if isinstance(value, cls):
            return value
        return _construct(cls, schema, value, mode, strict)

    handler: Callable[[Any], Any] = construct
    for function in schema.wrap:
        handler = _wrapped(cls.__name__, function, handler, mode, strict)
    info = ValidationInfo(mode, strict)
    for function in schema.before:
        data = _call_validator(function, 1, (data,), info, data)
    return handler(data)


def _wrapped(
    title: str,
    function: Callable[..., Any],
    inner: Callable[[Any], Any],
    mode: _ModeIn,
    strict: bool | None,
) -> Callable[[Any], Any]:
    def public(value: Any) -> Any:
        return _public(title, lambda: inner(value))

    def handler(value: Any) -> Any:
        info = ValidationInfo(mode, strict)
        return _call_validator(function, 2, (value, public), info, value)

    return handler


def _public[T](title: str, run: Callable[[], T]) -> T:
    try:
        return run()
    except Invalid as error:
        raise ValidationError(title, error.errors) from None


def _load_json(data: str | bytes | bytearray) -> Any:
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError) as error:
        raise invalid("json_invalid", f"Invalid JSON: {error}", data) from None


def _load_yaml(data: str | bytes | bytearray) -> Any:
    try:
        return _yaml.loads(data)
    except (ValueError, UnicodeDecodeError) as error:
        raise invalid("yaml_invalid", f"Invalid YAML: {error}", data) from None


def _load_xml(data: str | bytes | bytearray, tp: Any) -> Any:
    try:
        return _xml.loads(data, tp)
    except ValueError as error:
        raise invalid("xml_invalid", f"Invalid XML: {error}", data) from None


class BaseModel(metaclass=ModelMeta):
    """A class whose fields are its annotations, checked when an instance is made.

    Subclass it, annotate the fields, and give defaults or Field()
    descriptions. Instances are made from keyword arguments, from a dict
    with model_validate, or from JSON text with model_validate_json. Each
    raises ValidationError listing every field that does not validate.
    """

    model_config: ClassVar[ConfigDict] = {}
    __espalier_fields_set__: ClassVar[set[str]]
    __espalier_extra__: ClassVar[dict[str, Any] | None]

    if not typing.TYPE_CHECKING:

        def __init__(self, /, **data: Any) -> None:
            """Validate ``data`` as the fields of the model."""
            cls = type(self)
            result = _public(cls.__name__, lambda: _validate(cls, data, "python"))
            vars(self).update(result.__dict__)
            object.__setattr__(self, "__espalier_fields_set__", result.__espalier_fields_set__)
            object.__setattr__(self, "__espalier_extra__", result.__espalier_extra__)

    @classmethod
    def __espalier_validator__(cls, value: Any, info: ValidationInfo) -> Any:
        """Validate ``value`` as this model inside another validation."""
        if isinstance(value, cls):
            return value
        return _validate(cls, value, info.mode, info.strict)

    @classmethod
    def model_validate(cls, obj: Any, *, strict: bool | None = None, context: Any = None) -> Self:
        """Return an instance validated from ``obj``, a dict or an instance.

        An instance of the class is returned as it is. ``strict``, if
        given, replaces the ``strict`` of the config of this model and of
        the models in it; a field's own ``Field(strict=...)`` still applies.
        """
        return _public(cls.__name__, lambda: _validate(cls, obj, "python", strict))

    @classmethod
    def model_validate_json(
        cls, json_data: str | bytes | bytearray, *, strict: bool | None = None, context: Any = None
    ) -> Self:
        """Return an instance validated from JSON text.

        Values from JSON may give a list for a tuple or a set, and a string
        for an enum or a datetime, even when the model is strict.
        """
        return _public(cls.__name__, lambda: _validate(cls, _load_json(json_data), "json", strict))

    @classmethod
    def model_validate_yaml(
        cls, yaml_data: str | bytes | bytearray, *, strict: bool | None = None, context: Any = None
    ) -> Self:
        """Return an instance validated from a YAML document.

        The document is read as model_validate_json reads JSON, so the
        same values are accepted. See the README for the part of YAML
        that is read.
        """
        return _public(cls.__name__, lambda: _validate(cls, _load_yaml(yaml_data), "json", strict))

    @classmethod
    def model_validate_xml(
        cls, xml_data: str | bytes | bytearray, *, strict: bool | None = None, context: Any = None
    ) -> Self:
        """Return an instance validated from an XML document, as model_dump_xml writes it.

        The types of the fields say how to read each element, so text
        becomes a number where a field is a number. The name of the
        root element is not checked.
        """
        return _public(
            cls.__name__, lambda: _validate(cls, _load_xml(xml_data, cls), "json", strict)
        )

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Self:
        """Return an instance holding ``values`` without validating them."""
        schema = _schema(cls)
        instance = cls.__new__(cls)
        for name, field in schema.fields.items():
            if name in values:
                vars(instance)[name] = values[name]
            elif not field.info.is_required():
                vars(instance)[name] = field.info.get_default()
        fields_set = set(values) if _fields_set is None else set(_fields_set)
        object.__setattr__(instance, "__espalier_fields_set__", fields_set)
        object.__setattr__(instance, "__espalier_extra__", None)
        return instance

    @classmethod
    def model_rebuild(cls, *, force: bool = False, raise_errors: bool = True) -> bool | None:
        """Resolve the annotations again, once names they refer to are defined."""
        cls.__espalier_fields__ = None  # type: ignore[attr-defined]
        cls.__espalier_variants__ = {}  # type: ignore[attr-defined]
        try:
            _schema(cls)
        except NameError:
            if raise_errors:
                raise
            return False
        return True

    @property
    def model_fields_set(self) -> set[str]:
        """The names of the fields the input gave, not left to their defaults."""
        return self.__espalier_fields_set__

    @property
    def model_extra(self) -> dict[str, Any] | None:
        """Input keys kept by ``extra="allow"``, or None."""
        return self.__espalier_extra__

    def __espalier_dump__(
        self,
        mode: Mode,
        by_alias: bool | None,
        include: set[str] | None,
        exclude: set[str] | None,
        exclude_none: bool,
    ) -> dict[str, Any]:
        """Dump this model. See model_dump."""
        schema = _schema(type(self))
        if by_alias is None:
            by_alias = bool(schema.config.get("serialize_by_alias", False))
        result: dict[str, Any] = {}
        values = self.__dict__
        for name, field in schema.fields.items():
            if field.info.exclude or (include is not None and name not in include):
                continue
            if exclude is not None and name in exclude:
                continue
            value = values.get(name)
            if exclude_none and value is None:
                continue
            key = (field.info.serialization_alias or field.info.alias or name) if by_alias else name
            result[key] = serialize(field.serializer, value, mode, by_alias, exclude_none)
        for name in schema.computed:
            if (include is not None and name not in include) or (exclude and name in exclude):
                continue
            result[name] = dump(getattr(self, name), mode, by_alias, exclude_none)
        if self.__espalier_extra__:
            for name, value in self.__espalier_extra__.items():
                result[name] = dump(value, mode, by_alias, exclude_none)
        return result

    def model_dump(
        self,
        *,
        mode: Mode = "python",
        include: set[str] | None = None,
        exclude: set[str] | None = None,
        by_alias: bool | None = None,
        exclude_none: bool = False,
    ) -> dict[str, Any]:
        """Return the fields, then computed fields, as a dict.

        Models inside become dicts. In ``json`` mode, tuples and sets also
        become lists, enums their values and datetimes ISO 8601 strings.
        """
        return self.__espalier_dump__(mode, by_alias, include, exclude, exclude_none)

    def model_dump_json(
        self,
        *,
        indent: int | None = None,
        include: set[str] | None = None,
        exclude: set[str] | None = None,
        by_alias: bool | None = None,
        exclude_none: bool = False,
    ) -> str:
        """Return model_dump in ``json`` mode as JSON text, compact unless ``indent`` is given."""
        data = self.__espalier_dump__("json", by_alias, include, exclude, exclude_none)
        return to_json(data, indent)

    def model_dump_yaml(
        self,
        *,
        include: set[str] | None = None,
        exclude: set[str] | None = None,
        by_alias: bool | None = None,
        exclude_none: bool = False,
    ) -> str:
        """Return model_dump in ``json`` mode as a YAML document in block style."""
        data = self.__espalier_dump__("json", by_alias, include, exclude, exclude_none)
        return _yaml.dumps(data)

    def model_dump_xml(
        self,
        *,
        root: str | None = None,
        indent: int | None = None,
        include: set[str] | None = None,
        exclude: set[str] | None = None,
        by_alias: bool | None = None,
        exclude_none: bool = False,
    ) -> str:
        """Return model_dump in ``json`` mode as XML, on one line unless ``indent`` is given.

        The root element is named ``root``, or after the class. Each
        field is a child element; see the README for the whole layout.
        """
        data = self.__espalier_dump__("json", by_alias, include, exclude, exclude_none)
        return _xml.dumps(data, root or type(self).__name__, indent)

    def model_copy(self, *, update: dict[str, Any] | None = None, deep: bool = False) -> Self:
        """Return a copy with the fields in ``update`` replaced, without validating them.

        Values of computed fields are not copied, so they are computed
        again from the new fields.
        """
        cls = type(self)
        schema = _schema(cls)
        values = {name: self.__dict__[name] for name in schema.fields if name in self.__dict__}
        extra = dict(self.__espalier_extra__) if self.__espalier_extra__ else None
        if deep:
            values = copy.deepcopy(values)
            extra = copy.deepcopy(extra)
        fields_set = set(self.__espalier_fields_set__)
        if update:
            for name, value in update.items():
                if name in schema.fields:
                    values[name] = value
                    fields_set.add(name)
                else:
                    extra = (extra or {}) | {name: value}
        instance = cls.__new__(cls)
        vars(instance).update(values)
        if extra:
            vars(instance).update(extra)
        object.__setattr__(instance, "__espalier_fields_set__", fields_set)
        object.__setattr__(instance, "__espalier_extra__", extra)
        return instance

    def __copy__(self) -> Self:
        """Return a shallow copy."""
        return self.model_copy()

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Self:
        """Return a deep copy."""
        return self.model_copy(deep=True)

    def __getstate__(self) -> dict[str, Any]:
        """Return the state pickle stores."""
        schema = _schema(type(self))
        return {
            "fields": {
                name: self.__dict__[name] for name in schema.fields if name in self.__dict__
            },
            "fields_set": self.__espalier_fields_set__,
            "extra": self.__espalier_extra__,
        }

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Restore what __getstate__ returned."""
        vars(self).update(state["fields"])
        if state["extra"]:
            vars(self).update(state["extra"])
        object.__setattr__(self, "__espalier_fields_set__", state["fields_set"])
        object.__setattr__(self, "__espalier_extra__", state["extra"])

    def __setattr__(self, name: str, value: Any) -> None:
        """Set a field, unless the model is frozen."""
        cls = type(self)
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        schema = _schema(cls)
        if schema.config.get("frozen"):
            raise ValidationError(
                cls.__name__,
                [
                    {
                        "type": "frozen_instance",
                        "loc": (name,),
                        "msg": "Instance is frozen",
                        "input": value,
                    }
                ],
            )
        if name in schema.fields:
            vars(self)[name] = value
            self.__espalier_fields_set__.add(name)
        elif self.__espalier_extra__ is not None:
            self.__espalier_extra__[name] = value
            vars(self)[name] = value
        else:
            raise ValueError(f'"{cls.__name__}" object has no field "{name}"')

    def __delattr__(self, name: str) -> None:
        """Refuse to delete a field of a frozen model."""
        if _schema(type(self)).config.get("frozen") and not name.startswith("_"):
            raise ValidationError(
                type(self).__name__,
                [
                    {
                        "type": "frozen_instance",
                        "loc": (name,),
                        "msg": "Instance is frozen",
                        "input": None,
                    }
                ],
            )
        object.__delattr__(self, name)

    def _field_values(self) -> tuple[Any, ...]:
        cls = type(self)
        schema = cls.__dict__.get("__espalier_fields__") or _schema(cls)
        values = self.__dict__
        return tuple([values.get(name) for name in schema.names])

    def __eq__(self, other: object) -> bool:
        """Compare equal to a model of the same class with equal fields."""
        if not isinstance(other, BaseModel):
            return NotImplemented
        if self is other:
            return True
        return (
            type(self) is type(other)
            and self._field_values() == other._field_values()
            and self.__espalier_extra__ == other.__espalier_extra__
        )

    def __hash__(self) -> int:
        """Hash the class and fields of a frozen model; other models are unhashable."""
        cls = type(self)
        if not (cls.__dict__.get("__espalier_fields__") or _schema(cls)).frozen:
            raise TypeError(f"unhashable type: '{type(self).__name__}'")
        return hash((type(self), self._field_values()))

    def __iter__(self) -> Iterator[tuple[str, Any]]:  # type: ignore[override]
        """Yield ``(name, value)`` for each field."""
        for name in _schema(type(self)).fields:
            yield name, self.__dict__.get(name)

    def _repr_args(self) -> list[tuple[str, Any]]:
        schema = _schema(type(self))
        args = [
            (name, self.__dict__.get(name))
            for name, field in schema.fields.items()
            if field.info.repr
        ]
        args.extend((name, getattr(self, name)) for name in schema.computed)
        return args

    def __repr__(self) -> str:
        """Show the class and its fields as keyword arguments."""
        shown = ", ".join(f"{name}={value!r}" for name, value in self._repr_args())
        return f"{type(self).__name__}({shown})"

    def __str__(self) -> str:
        """Show the fields as ``name=value`` separated by spaces."""
        return " ".join(f"{name}={value!r}" for name, value in self._repr_args())
