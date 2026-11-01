# SPDX-License-Identifier: GPL-2.0
"""Reading and writing data as XML.

Each key of a mapping is a child element named after it, or an
``entry`` element with a ``key`` attribute when the key is not an XML
name. Each member of a list is an ``item`` element. None is an empty
element with ``nil="true"``, and other values are the text of their
element. XML does not say which text is a number, so the reader takes
the type of the value it reads and turns text into numbers, booleans,
lists or mappings where the type asks for them. The reader refuses a
document type declaration, so a document cannot declare entities, read
other files or expand into more data than it holds.
"""

from __future__ import annotations

import collections
import enum
import math
import re
import types
import typing
from collections.abc import Mapping, Sequence
from typing import Any
from xml.parsers import expat

from ._validators import is_model, split_annotated

_NAME = re.compile(r"[^\W\d][\w.\-]*\Z")
_INT = re.compile(r"[-+]?[0-9]+\Z")
_FLOAT = re.compile(
    r"[-+]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][-+]?[0-9]+)?\Z|[-+]?(inf|infinity|nan)\Z", re.I
)
_BAD_CHARS = re.compile("[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")
_TEXT = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\r": "&#13;"})
_ATTRIBUTE = str.maketrans(
    {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "\r": "&#13;",
        "\n": "&#10;",
        "\t": "&#9;",
    }
)
_LISTS = (list, set, frozenset, collections.deque, Sequence)
_NIL = "nil"


class XMLError(ValueError):
    """Text that is not XML, or XML that the reader does not take."""


class _Node:
    __slots__ = ("attributes", "children", "line", "tag", "text")

    def __init__(self, tag: str, attributes: dict[str, str], line: int) -> None:
        self.tag = tag
        self.attributes = attributes
        self.line = line
        self.children: list[_Node] = []
        self.text: list[str] = []

    @property
    def nil(self) -> bool:
        return self.attributes.get(_NIL) == "true"

    @property
    def key(self) -> str:
        return self.attributes.get("key", self.tag) if self.tag == "entry" else self.tag

    @property
    def value(self) -> str:
        return "".join(self.text)


def _refuse_doctype(*_: Any) -> None:
    raise XMLError("document type declarations are not supported")


def _parse(data: str | bytes | bytearray) -> _Node:
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    stack: list[_Node] = []
    root: list[_Node] = []

    def start(tag: str, attributes: dict[str, str]) -> None:
        node = _Node(tag, attributes, parser.CurrentLineNumber)
        if stack:
            stack[-1].children.append(node)
        else:
            root.append(node)
        stack.append(node)

    def end(_: str) -> None:
        stack.pop()

    def text(chunk: str) -> None:
        if stack:
            stack[-1].text.append(chunk)

    parser.StartDoctypeDeclHandler = _refuse_doctype
    parser.EntityDeclHandler = _refuse_doctype
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.buffer_text = True
    try:
        parser.Parse(bytes(data) if isinstance(data, bytearray) else data, True)
    except expat.ExpatError as error:
        raise XMLError(str(error)) from None
    return root[0]


def _unwrap(tp: Any) -> Any:
    while True:
        tp, _ = split_annotated(tp)
        if isinstance(tp, typing.TypeAliasType):
            tp = tp.__value__
        elif isinstance(tp, typing.NewType):
            tp = tp.__supertype__
        else:
            return tp


def _children(node: _Node) -> list[_Node]:
    """Return the children of ``node``, refusing text mixed with them."""
    if node.children and node.value.strip():
        raise XMLError(f"line {node.line}: <{node.tag}> mixes text and elements")
    return node.children


def _generic(node: _Node) -> Any:
    """Decode ``node`` without a type: lists of items, mappings, or text."""
    if node.nil:
        return None
    children = _children(node)
    if not children:
        return node.value
    if all(child.tag == "item" for child in children):
        return [_generic(child) for child in children]
    return _mapping(children, lambda _: Any)


def _mapping(children: list[_Node], type_of: typing.Callable[[str], Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for child in children:
        key = child.key
        if key in result:
            raise XMLError(f"line {child.line}: <{child.tag}> repeats the key {key!r}")
        result[key] = decode(child, type_of(key))
    return result


def _field_types(models: list[Any]) -> dict[str, Any]:
    from .main import _schema

    types_by_key: dict[str, Any] = {}
    for model in models:
        for field in _schema(model).fields.values():
            info = field.info
            for key in (*field.keys, field.name, info.alias, info.serialization_alias):
                if isinstance(key, str):
                    types_by_key.setdefault(key, info.annotation)
    return types_by_key


def _record(node: _Node, models: list[Any]) -> Any:
    children = _children(node)
    if not children and node.value.strip():
        return node.value
    types_by_key = _field_types(models)
    return _mapping(children, lambda key: types_by_key.get(key, Any))


def _literal(text: str, values: tuple[Any, ...]) -> Any:
    for value in values:
        if isinstance(value, enum.Enum):
            value = value.value
        if isinstance(value, bool):
            if text == ("true" if value else "false"):
                return value
        elif str(value) == text:
            return value
    return text


def _scalar(text: str, tp: Any) -> tuple[bool, Any]:
    """Return whether ``text`` reads as a value of the scalar type ``tp``, and the value."""
    if tp is bool:
        if text in ("true", "false"):
            return True, text == "true"
        return False, text
    if tp is int:
        return (True, int(text)) if _INT.match(text) else (False, text)
    if tp is float:
        return (True, float(text)) if _FLOAT.match(text) else (False, text)
    if typing.get_origin(tp) is typing.Literal:
        value = _literal(text, typing.get_args(tp))
        return value is not text, value
    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        value = _literal(text, tuple(tp))
        return value is not text, value
    return True, text


def _is_scalar(tp: Any) -> bool:
    if is_model(tp) or tp is Any or tp is object:
        return False
    origin = typing.get_origin(tp)
    if origin is typing.Union or origin is types.UnionType:
        return all(_is_scalar(_unwrap(member)) for member in typing.get_args(tp))
    if origin is typing.Literal:
        return True
    if origin is not None:
        return False
    return not (isinstance(tp, type) and issubclass(tp, (*_LISTS[:4], tuple, dict, Mapping)))


def _union(node: _Node, members: list[Any]) -> Any:
    if len(members) == 1:
        return decode(node, members[0])
    if all(is_model(member) for member in members):
        return _record(node, members)
    if all(_is_scalar(member) for member in members) and not node.children:
        text = node.value
        for member in members:
            found, value = _scalar(text, member)
            if found:
                return value
        return text
    return _generic(node)


def decode(node: _Node, tp: Any) -> Any:  # noqa: C901
    """Return the data that ``node`` holds, read as the type ``tp``."""
    tp = _unwrap(tp)
    if node.nil:
        return None
    if tp is Any or tp is object or isinstance(tp, typing.TypeVar):
        return _generic(node)
    if is_model(tp):
        return _record(node, [tp])
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Union or origin is types.UnionType:
        members = [member for member in args if member is not type(None)]
        return _union(node, members)
    container = origin or tp
    if container in (tuple, typing.Tuple):  # noqa: UP006
        children = _children(node)
        if not children and node.value.strip():
            return node.value
        if not args or (len(args) == 2 and args[1] is Ellipsis):
            item = args[0] if args else Any
            return [decode(child, item) for child in children]
        positions = [] if args == ((),) else list(args)
        return [
            decode(child, positions[index] if index < len(positions) else Any)
            for index, child in enumerate(children)
        ]
    if isinstance(container, type) and issubclass(container, Mapping):
        children = _children(node)
        if not children and node.value.strip():
            return node.value
        value_type = args[1] if len(args) > 1 else Any
        return _mapping(children, lambda _: value_type)
    if container in _LISTS or (
        isinstance(container, type)
        and issubclass(container, _LISTS)
        and not issubclass(container, (str, bytes, bytearray))
    ):
        children = _children(node)
        if not children and node.value.strip():
            return node.value
        item = args[0] if args else Any
        return [decode(child, item) for child in children]
    if node.children:
        return _generic(node)
    return _scalar(node.value, tp)[1]


def loads(data: str | bytes | bytearray, tp: Any) -> Any:
    """Return the data of the XML document ``data``, read as the type ``tp``.

    The name of the root element is not checked. Raise XMLError for
    text that is not XML or that the reader does not take.
    """
    return decode(_parse(data), tp)


def _check(text: str) -> str:
    bad = _BAD_CHARS.search(text)
    if bad:
        raise ValueError(f"XML cannot hold the character {bad.group()!r}")
    return text


def _name_ok(key: str) -> bool:
    return (
        bool(_NAME.match(key))
        and not key.lower().startswith("xml")
        and key not in ("entry", "item")
    )


def _text(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "-inf" if value < 0 else "inf"
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _check(value).translate(_TEXT)
    raise TypeError(f"cannot write {type(value).__name__} as XML")


def _element(  # noqa: C901
    out: list[str], tag: str, attributes: str, value: Any, indent: str | None, depth: int
) -> None:
    pad = "" if indent is None else "\n" + indent * depth
    if depth:
        out.append(pad)
    if value is None:
        out.append(f'<{tag}{attributes} {_NIL}="true" />')
        return
    if isinstance(value, dict) and value:
        out.append(f"<{tag}{attributes}>")
        for key, item in value.items():
            key = str(key)
            if _name_ok(key):
                _element(out, key, "", item, indent, depth + 1)
            else:
                _element(
                    out,
                    "entry",
                    f' key="{_check(key).translate(_ATTRIBUTE)}"',
                    item,
                    indent,
                    depth + 1,
                )
        out.append(f"{pad}</{tag}>")
        return
    if isinstance(value, list) and value:
        out.append(f"<{tag}{attributes}>")
        for item in value:
            _element(out, "item", "", item, indent, depth + 1)
        out.append(f"{pad}</{tag}>")
        return
    if isinstance(value, (dict, list)) or value == "":
        out.append(f"<{tag}{attributes} />")
        return
    out.append(f"<{tag}{attributes}>{_text(value)}</{tag}>")


def dumps(data: Any, root: str, indent: int | None = None) -> str:
    """Return ``data``, made of dicts, lists and JSON scalars, as XML under ``root``.

    The output is one line unless ``indent`` gives the number of spaces
    to indent each level by. Raise ValueError if ``root`` is not an XML
    name or the data holds a character that XML cannot.
    """
    if not _NAME.match(root):
        raise ValueError(f"{root!r} is not an XML element name")
    out: list[str] = []
    _element(out, root, "", data, None if indent is None else " " * indent, 0)
    return "".join(out) + ("\n" if indent is not None else "")
