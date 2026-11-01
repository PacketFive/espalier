# SPDX-License-Identifier: GPL-2.0
"""Turning validated values back into Python or JSON-ready data."""

from __future__ import annotations

import datetime
import enum
import json
import pathlib
from typing import Any, Literal

from .functional import PlainSerializer, SerializationInfo, wants_info

Mode = Literal["python", "json"]

_SCALARS = (str, int, float, bool, type(None))


def _datetime(value: datetime.datetime) -> str:
    text = value.isoformat()
    offset = value.utcoffset()
    if offset is not None and not offset:
        text = text[: -len("+00:00")] + "Z"
    return text


def _key(key: Any) -> Any:
    if isinstance(key, enum.Enum):
        key = key.value
    if isinstance(key, str):
        return key
    if isinstance(key, bool):
        return "true" if key else "false"
    return str(key)


def dump(value: Any, mode: Mode, by_alias: bool | None, exclude_none: bool) -> Any:
    """Return ``value`` with every model in it turned into a dict.

    In ``json`` mode, tuples and sets also become lists, enums their
    values, datetimes ISO 8601 strings and dict keys strings, so the
    result can be given to json.dumps.
    """
    kind = type(value)
    if kind in _SCALARS:
        return value
    dumper = getattr(kind, "__espalier_dump__", None)
    if dumper is not None:
        return dumper(value, mode, by_alias, None, None, exclude_none)
    if isinstance(value, enum.Enum):
        return dump(value.value, mode, by_alias, exclude_none) if mode == "json" else value
    if isinstance(value, dict):
        if mode == "json":
            return {_key(k): dump(v, mode, by_alias, exclude_none) for k, v in value.items()}
        return {k: dump(v, mode, by_alias, exclude_none) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [dump(item, mode, by_alias, exclude_none) for item in value]
        if mode == "json" or isinstance(value, list):
            return items
        if isinstance(value, tuple):
            return tuple(items)
        return type(value)(items)
    if mode == "json":
        if isinstance(value, datetime.datetime):
            return _datetime(value)
        if isinstance(value, (datetime.date, datetime.time)):
            return value.isoformat()
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).decode()
        if isinstance(value, pathlib.PurePath):
            return str(value)
    return value


def serialize(
    serializer: PlainSerializer | None,
    value: Any,
    mode: Mode,
    by_alias: bool | None,
    exclude_none: bool,
) -> Any:
    """Dump ``value``, through ``serializer`` first if there is one for this mode."""
    if serializer is not None and (serializer.when_used == "always" or mode == "json"):
        function = serializer.func
        if wants_info(function, 1):
            value = function(value, SerializationInfo(mode, bool(by_alias)))
        else:
            value = function(value)
    return dump(value, mode, by_alias, exclude_none)


def to_json(data: Any, indent: int | None) -> str:
    """Return ``data`` as JSON text: compact unless ``indent`` is given, UTF-8 kept as is."""
    if indent is None:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(data, ensure_ascii=False, indent=indent)
