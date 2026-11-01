# SPDX-License-Identifier: GPL-2.0
"""Validating values of any type, outside a model."""

from __future__ import annotations

from typing import Any, overload

from . import _validators, _xml, _yaml
from ._serialize import Mode, serialize, to_json
from .config import ConfigDict
from .errors import ValidationError
from .functional import ValidationInfo
from .main import _load_json, _load_xml, _load_yaml, _public


class TypeAdapter[T]:
    """Validate and dump values of a type that is not a model, such as ``tuple[M, ...]``.

    The type is validated in lax mode unless ``config`` sets ``strict``;
    models inside it keep their own configuration.
    """

    @overload
    def __init__(self, type: type[T], *, config: ConfigDict | None = None) -> None: ...

    @overload
    def __init__(self, type: Any, *, config: ConfigDict | None = None) -> None: ...

    def __init__(self, type: Any, *, config: ConfigDict | None = None) -> None:  # noqa: A002
        """Prepare to validate values of ``type``."""
        self._type = type
        self._strict = bool((config or {}).get("strict", False))
        self._validator: _validators.Validator | None = None
        self._serializer = _validators.serializer_of(type)
        self._title = _validators.type_label(type)

    def _check(self, value: Any, mode: Mode, strict: bool | None = None) -> T:
        if strict is not None and strict != self._strict:
            validator = _validators.build(self._type, strict)
        else:
            if self._validator is None:
                self._validator = _validators.build(self._type, self._strict)
            validator = self._validator
        return _public(self._title, lambda: validator(value, ValidationInfo(mode, strict)))

    def validate_python(self, value: Any, *, strict: bool | None = None) -> T:
        """Return ``value`` validated as the type."""
        return self._check(value, "python", strict)

    def validate_json(self, data: str | bytes | bytearray, *, strict: bool | None = None) -> T:
        """Return the value of the JSON text ``data`` validated as the type."""
        return _public(self._title, lambda: self._check(_load_json(data), "json", strict))

    def validate_yaml(self, data: str | bytes | bytearray, *, strict: bool | None = None) -> T:
        """Return the value of the YAML document ``data`` validated as the type."""
        return _public(self._title, lambda: self._check(_load_yaml(data), "json", strict))

    def validate_xml(self, data: str | bytes | bytearray, *, strict: bool | None = None) -> T:
        """Return the value of the XML document ``data``, read and validated as the type."""
        return _public(
            self._title, lambda: self._check(_load_xml(data, self._type), "json", strict)
        )

    def dump_python(
        self,
        value: T,
        *,
        mode: Mode = "python",
        by_alias: bool | None = None,
        exclude_none: bool = False,
    ) -> Any:
        """Return ``value`` with the models in it turned into dicts. See BaseModel.model_dump."""
        return serialize(self._serializer, value, mode, by_alias, exclude_none)

    def dump_json(
        self,
        value: T,
        *,
        indent: int | None = None,
        by_alias: bool | None = None,
        exclude_none: bool = False,
    ) -> bytes:
        """Return ``value`` as UTF-8 JSON, compact unless ``indent`` is given."""
        data = serialize(self._serializer, value, "json", by_alias, exclude_none)
        return to_json(data, indent).encode()

    def dump_yaml(
        self,
        value: T,
        *,
        by_alias: bool | None = None,
        exclude_none: bool = False,
    ) -> bytes:
        """Return ``value`` as a UTF-8 YAML document in block style."""
        data = serialize(self._serializer, value, "json", by_alias, exclude_none)
        return _yaml.dumps(data).encode()

    def dump_xml(
        self,
        value: T,
        *,
        root: str = "value",
        indent: int | None = None,
        by_alias: bool | None = None,
        exclude_none: bool = False,
    ) -> bytes:
        """Return ``value`` as UTF-8 XML under the root element ``root``.

        See BaseModel.model_dump_xml for the layout.
        """
        data = serialize(self._serializer, value, "json", by_alias, exclude_none)
        return _xml.dumps(data, root, indent).encode()


__all__ = ["TypeAdapter", "ValidationError"]
