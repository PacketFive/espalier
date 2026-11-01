# SPDX-License-Identifier: GPL-2.0
"""Reading and writing YAML: the part of YAML 1.2 that data files use.

The reader takes one document made of block and flow collections and
plain, quoted and block scalars. Plain scalars are resolved with the
core schema of YAML 1.2: null, booleans, integers and floats, and
strings otherwise. Mapping keys are kept as strings, as in JSON. The
reader refuses anchors, aliases, tags, complex keys and more than one
document, so a file means the same data to every reader and cannot
expand into more data than it holds.
"""

from __future__ import annotations

import math
import re
from typing import Any

_NULL = frozenset({"", "~", "null", "Null", "NULL"})
_TRUE = frozenset({"true", "True", "TRUE"})
_FALSE = frozenset({"false", "False", "FALSE"})
_INT = re.compile(r"[-+]?[0-9]+\Z")
_OCT = re.compile(r"0o[0-7]+\Z")
_HEX = re.compile(r"0x[0-9a-fA-F]+\Z")
_FLOAT = re.compile(r"[-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?\Z")
_INF = re.compile(r"[-+]?\.(inf|Inf|INF)\Z")
_NAN = re.compile(r"\.(nan|NaN|NAN)\Z")
_YAML_1_1 = re.compile(
    r"(y|Y|yes|Yes|YES|n|N|no|No|NO|on|On|ON|off|Off|OFF|=|<<)\Z"
    r"|[-+]?(0b[01_]+|[0-9][0-9_:]*(\.[0-9_]*)?([eE][-+]?[0-9]+)?|\.[0-9_]+([eE][-+]?[0-9]+)?)\Z"
    r"|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}"
)
_INDICATORS = frozenset("-?:,[]{}#&*!|>'\"%@`")
_ESCAPES = {
    "0": "\0",
    "a": "\a",
    "b": "\b",
    "t": "\t",
    "\t": "\t",
    "n": "\n",
    "v": "\v",
    "f": "\f",
    "r": "\r",
    "e": "\x1b",
    " ": " ",
    '"': '"',
    "/": "/",
    "\\": "\\",
    "N": "\x85",
    "_": "\xa0",
    "L": "\u2028",
    "P": "\u2029",
}
_HEX_DIGITS = {"x": 2, "u": 4, "U": 8}


class YAMLError(ValueError):
    """Text that is not YAML, or uses a part of YAML the reader does not take."""

    def __init__(self, message: str, line: int) -> None:
        """Record ``message`` for the 1-based ``line``."""
        super().__init__(f"line {line}: {message}")
        self.line = line


def resolve(text: str) -> Any:
    """Return the value of a plain scalar under the YAML 1.2 core schema."""
    if text in _NULL:
        return None
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    if _INT.match(text):
        return int(text)
    if _OCT.match(text):
        return int(text[2:], 8)
    if _HEX.match(text):
        return int(text[2:], 16)
    if _FLOAT.match(text):
        return float(text)
    if _INF.match(text):
        return -math.inf if text[0] == "-" else math.inf
    if _NAN.match(text):
        return math.nan
    return text


def _quote_end(text: str, quote: str) -> int:
    """Return the index of the quote that closes the scalar opened at 0, or -1."""
    index = 1
    while index < len(text):
        char = text[index]
        if quote == '"' and char == "\\":
            index += 2
            continue
        if char == quote:
            if quote == "'" and text[index + 1 : index + 2] == "'":
                index += 2
                continue
            return index
        index += 1
    return -1


def _scan_quoted(text: str, index: int) -> tuple[str, int]:  # noqa: C901
    """Return the value of the quoted scalar at ``index`` and the index after it.

    Line breaks inside the scalar fold to a space, and empty lines to
    line breaks, as YAML specifies.
    """
    quote = text[index]
    index += 1
    out: list[str] = []
    hard = 0
    while True:
        if index >= len(text):
            raise ValueError("the quoted scalar is not closed")
        char = text[index]
        if char == quote:
            if quote == "'" and text[index + 1 : index + 2] == "'":
                out.append("'")
                index += 2
                continue
            return "".join(out), index + 1
        if char == "\\" and quote == '"':
            escape = text[index + 1 : index + 2]
            if escape == "\n":
                index += 2
                while index < len(text) and text[index] in " \t":
                    index += 1
                continue
            if escape in _ESCAPES:
                out.append(_ESCAPES[escape])
                index += 2
            elif escape in _HEX_DIGITS:
                size = _HEX_DIGITS[escape]
                digits = text[index + 2 : index + 2 + size]
                if len(digits) != size or not all(c in "0123456789abcdefABCDEF" for c in digits):
                    raise ValueError(f"\\{escape} needs {size} hexadecimal digits")
                out.append(chr(int(digits, 16)))
                index += 2 + size
            else:
                raise ValueError(f"unknown escape \\{escape}")
            hard = len(out)
            continue
        if char == "\n":
            while len(out) > hard and out[-1] in " \t":
                out.pop()
            index += 1
            breaks = 0
            while index < len(text):
                while index < len(text) and text[index] in " \t":
                    index += 1
                if text[index : index + 1] != "\n":
                    break
                breaks += 1
                index += 1
            out.append("\n" * breaks if breaks else " ")
            hard = len(out)
            continue
        out.append(char)
        index += 1


def _strip_comment(text: str) -> tuple[str, bool]:
    """Return ``text`` without a trailing comment, and whether there was one."""
    for index in range(1, len(text)):
        if text[index] == "#" and text[index - 1] in " \t":
            return text[:index].rstrip(), True
    return text.rstrip(), False


def _is_entry(text: str) -> bool:
    return text == "-" or text[:2] in ("- ", "-\t")


def _is_explicit(text: str) -> bool:
    return text == "?" or text[:2] in ("? ", "?\t")


def _is_marker(line: str) -> bool:
    return line.rstrip() in ("---", "...") or line.startswith(("--- ", "... "))


class _Flow:
    """A recursive descent parser of one flow collection, given as one string."""

    def __init__(self, text: str, line: int) -> None:
        self.text = text
        self.index = 0
        self.line = line

    def fail(self, message: str) -> YAMLError:
        return YAMLError(message, self.line)

    def skip(self) -> None:
        while self.index < len(self.text) and self.text[self.index] in " \t\n":
            self.index += 1

    def peek(self) -> str:
        self.skip()
        return self.text[self.index : self.index + 1]

    def parse(self) -> Any:
        value = self.value()
        if self.peek():
            raise self.fail("unexpected text after a flow collection")
        return value

    def quoted(self) -> str:
        try:
            value, self.index = _scan_quoted(self.text, self.index)
        except ValueError as error:
            raise self.fail(str(error)) from None
        return value

    def plain(self) -> str:
        start = self.index
        text = self.text
        while self.index < len(text):
            char = text[self.index]
            if char in ",[]{}":
                break
            if char == ":" and text[self.index + 1 : self.index + 2] in (
                "",
                " ",
                "\t",
                "\n",
                ",",
                "]",
                "}",
                "[",
                "{",
            ):
                break
            self.index += 1
        plain = " ".join(part.strip() for part in text[start : self.index].split("\n")).strip()
        if not plain:
            raise self.fail("expected a value")
        if plain[0] in "&*!":
            raise self.fail("anchors, aliases and tags are not supported")
        if plain[0] in "@`|>%#" or plain[:2] in ("? ", "?\t", "- ", "-\t") or plain in ("?", "-"):
            raise self.fail(f"a plain scalar cannot start with {plain[0]!r}")
        return plain

    def value(self) -> Any:
        char = self.peek()
        if char == "[":
            return self.sequence()
        if char == "{":
            return self.mapping()
        if char in ("'", '"'):
            return self.quoted()
        if not char:
            raise self.fail("expected a value")
        return resolve(self.plain())

    def key(self) -> str:
        char = self.peek()
        if char == "?" and self.text[self.index + 1 : self.index + 2] in (" ", "\t", "\n"):
            self.index += 1
            char = self.peek()
        if char in ("[", "{"):
            raise self.fail("complex mapping keys are not supported")
        if char in ("'", '"'):
            return self.quoted()
        return self.plain()

    def pair_value(self) -> Any:
        self.index += 1
        if self.peek() in (",", "]", "}"):
            return None
        return self.value()

    def sequence(self) -> list[Any]:
        self.index += 1
        items: list[Any] = []
        while True:
            char = self.peek()
            if char == "]":
                self.index += 1
                return items
            if not char:
                raise self.fail("the flow sequence is not closed")
            if char in ("[", "{"):
                items.append(self.value())
            else:
                quoted = char in ("'", '"')
                text = self.quoted() if quoted else self.plain()
                if self.peek() == ":":
                    items.append({text: self.pair_value()})
                else:
                    items.append(text if quoted else resolve(text))
            char = self.peek()
            if char == ",":
                self.index += 1
            elif char != "]":
                raise self.fail("expected ',' or ']' in a flow sequence")

    def mapping(self) -> dict[str, Any]:
        self.index += 1
        result: dict[str, Any] = {}
        while True:
            char = self.peek()
            if char == "}":
                self.index += 1
                return result
            if not char:
                raise self.fail("the flow mapping is not closed")
            key = self.key()
            value = self.pair_value() if self.peek() == ":" else None
            if key in result:
                raise self.fail(f"duplicate key {key!r}")
            result[key] = value
            char = self.peek()
            if char == ",":
                self.index += 1
            elif char != "}":
                raise self.fail("expected ',' or '}' in a flow mapping")


class _Reader:
    """Block structure, read line by line; scalars and flow collections are read in place."""

    def __init__(self, text: str) -> None:
        text = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
        self.lines = text.removesuffix("\n").split("\n")
        self.pos = 0

    def fail(self, message: str) -> YAMLError:
        return YAMLError(message, self.pos + 1)

    def peek(self) -> tuple[int, str] | None:
        """Move to the next line with content; return its indentation and text."""
        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            text = line.lstrip(" ")
            if not text.strip() or text.startswith("#"):
                self.pos += 1
                continue
            if text[0] == "\t":
                raise self.fail("tabs cannot indent YAML")
            indent = len(line) - len(text)
            if indent == 0 and _is_marker(line):
                return None
            return indent, text.rstrip()
        return None

    def document(self) -> Any:
        self.peek()
        while self.pos < len(self.lines) and self.lines[self.pos].startswith("%"):
            if not self.lines[self.pos].startswith("%YAML "):
                raise self.fail("directives other than %YAML are not supported")
            self.pos += 1
            self.peek()
        if self.pos < len(self.lines) and self.lines[self.pos].rstrip() == "---":
            self.pos += 1
        elif self.pos < len(self.lines) and self.lines[self.pos].startswith("--- "):
            rest = self.lines[self.pos][4:].strip()
            if rest.startswith("#"):
                self.pos += 1
            else:
                self.lines[self.pos] = rest
        value = self.node(-1)
        if self.peek() is not None:
            raise self.fail("unexpected text after the document")
        if self.pos < len(self.lines) and self.lines[self.pos].startswith("..."):
            self.pos += 1
            self.peek()
        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            if line.strip() and not line.lstrip().startswith("#"):
                if line.startswith("---"):
                    raise self.fail("only one document is supported")
                raise self.fail("unexpected text after the document")
            self.pos += 1
        return value

    def node(self, parent: int) -> Any:
        """Read the node that starts on the next line, if it is indented more than ``parent``."""
        found = self.peek()
        if found is None or found[0] <= parent:
            return None
        indent, text = found
        if _is_entry(text):
            return self.sequence(indent)
        if _is_explicit(text) or self.split_key(text) is not None:
            return self.mapping(indent)
        return self.inline(text, parent)

    def sequence(self, indent: int) -> list[Any]:
        items: list[Any] = []
        while True:
            found = self.peek()
            if found is None or found[0] < indent:
                return items
            if found[0] > indent:
                raise self.fail("unexpected indentation")
            text = found[1]
            if not _is_entry(text):
                return items
            rest = text[1:].lstrip(" \t")
            if not rest or rest.startswith("#"):
                self.pos += 1
            else:
                self.lines[self.pos] = " " * (indent + len(text) - len(rest)) + rest
            items.append(self.node(indent))

    def mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while True:
            found = self.peek()
            if found is None or found[0] < indent:
                return result
            if found[0] > indent:
                raise self.fail("unexpected indentation")
            if _is_explicit(found[1]):
                key = self.explicit_key(found[1], indent)
                if key in result:
                    raise self.fail(f"duplicate key {key!r}")
                result[key] = self.explicit_value(indent)
                continue
            split = self.split_key(found[1])
            if split is None:
                raise self.fail("expected 'key: value'")
            key, rest = split
            if key in result:
                raise self.fail(f"duplicate key {key!r}")
            if not rest or rest.startswith("#"):
                self.pos += 1
                after = self.peek()
                if after is not None and after[0] == indent and _is_entry(after[1]):
                    result[key] = self.sequence(indent)
                else:
                    result[key] = self.node(indent)
            else:
                result[key] = self.inline(rest, indent)

    def explicit_key(self, text: str, indent: int) -> str:
        """Read the scalar key of a ``? key`` line, and any lines it continues on."""
        rest = text[1:].strip()
        if not rest or rest[0] in "#[{" or _is_entry(rest) or _is_explicit(rest):
            raise self.fail("complex mapping keys are not supported")
        if rest[0] in ("'", '"'):
            return self.quoted(rest)
        if rest[0] in "|>":
            return self.block_scalar(rest, indent)
        return self.plain(rest, indent, raw=True)

    def explicit_value(self, indent: int) -> Any:
        """Read the ``: value`` part that follows an explicit key, or None if there is none."""
        found = self.peek()
        if found is None or found[0] != indent:
            return None
        text = found[1]
        if text != ":" and text[:2] not in (": ", ":\t"):
            return None
        rest = text[1:].lstrip(" \t")
        if not rest or rest.startswith("#"):
            self.pos += 1
            after = self.peek()
            if after is not None and after[0] == indent and _is_entry(after[1]):
                return self.sequence(indent)
            return self.node(indent)
        self.lines[self.pos] = " " * (indent + len(text) - len(rest)) + rest
        return self.node(indent)

    def split_key(self, text: str) -> tuple[str, str] | None:
        """Return the key and the rest of a ``key: value`` line, or None for other lines."""
        first = text[0]
        if first in ("'", '"'):
            end = _quote_end(text, first)
            if end < 0:
                return None
            after = text[end + 1 :].lstrip(" \t")
            if not after.startswith(":") or after[1:2] not in ("", " ", "\t"):
                return None
            try:
                key, _ = _scan_quoted(text, 0)
            except ValueError as error:
                raise self.fail(str(error)) from None
            return key, after[1:].strip()
        if first in "[{":
            return None
        for index, char in enumerate(text):
            if char == "#" and index and text[index - 1] in " \t":
                return None
            if char == ":" and text[index + 1 : index + 2] in ("", " ", "\t"):
                key = text[:index].rstrip()
                if not key:
                    return None
                self.check_plain(key)
                return key, text[index + 1 :].strip()
        return None

    def check_plain(self, text: str) -> None:
        first = text[0]
        if first in "&*!":
            raise self.fail("anchors, aliases and tags are not supported")
        if first in "@`%,]}#|>":
            raise self.fail(f"a plain scalar cannot start with {first!r}")
        if _is_entry(text):
            raise self.fail("a sequence entry is not allowed here")
        if text == "?" or text.startswith(("? ", "?\t", ": ", ":\t")) or text == ":":
            raise self.fail(f"a plain scalar cannot start with {first!r}")

    def inline(self, text: str, floor: int) -> Any:
        """Read the scalar or flow collection that starts with ``text`` on the current line.

        Continuation lines must be indented more than ``floor``. The
        reader is left on the line after the value.
        """
        first = text[0]
        if first in "[{":
            return self.flow(text)
        if first in ("'", '"'):
            return self.quoted(text)
        if first in "|>":
            return self.block_scalar(text, floor)
        return self.plain(text, floor)

    def rest_is_empty(self, rest: str) -> None:
        if rest.strip() and not (rest[0] in " \t" and rest.strip().startswith("#")):
            raise self.fail("unexpected text after a value")

    def flow(self, text: str) -> Any:
        start = self.pos
        parts: list[str] = []
        depth = 0
        quote = ""
        line = text
        previous = ""
        while True:
            index = 0
            cut = len(line)
            closed = False
            while index < len(line):
                char = line[index]
                if quote == '"' and char == "\\":
                    index += 2
                    continue
                if quote:
                    if char == quote:
                        if quote == "'" and line[index + 1 : index + 2] == "'":
                            index += 2
                            continue
                        quote = ""
                        previous = char
                    index += 1
                    continue
                if char in ("'", '"') and previous in "[{,:?":
                    quote = char
                elif char == "#" and (index == 0 or line[index - 1] in " \t"):
                    cut = index
                    break
                elif char in "[{":
                    depth += 1
                elif char in "]}":
                    depth -= 1
                    if depth == 0:
                        cut = index + 1
                        self.rest_is_empty(line[cut:])
                        closed = True
                        break
                if char not in " \t":
                    previous = char
                index += 1
            parts.append(line[:cut])
            if closed:
                break
            self.pos += 1
            if self.pos >= len(self.lines) or _is_marker(self.lines[self.pos]):
                self.pos = start
                raise self.fail("the flow collection is not closed")
            line = self.lines[self.pos]
        line_number = start + 1
        self.pos += 1
        return _Flow("\n".join(parts), line_number).parse()

    def quoted(self, text: str) -> str:
        start = self.pos
        joined = text
        while _quote_end(joined, text[0]) < 0:
            self.pos += 1
            if self.pos >= len(self.lines) or _is_marker(self.lines[self.pos]):
                self.pos = start
                raise self.fail("the quoted scalar is not closed")
            joined += "\n" + self.lines[self.pos]
        try:
            value, end = _scan_quoted(joined, 0)
        except ValueError as error:
            raise self.fail(str(error)) from None
        self.rest_is_empty(joined[end:])
        self.pos += 1
        return value

    def plain(self, text: str, floor: int, raw: bool = False) -> Any:
        text, commented = _strip_comment(text)
        self.check_plain(text)
        self.check_inside(text)
        parts = [text]
        self.pos += 1
        look = self.pos
        breaks = 0
        while not commented and look < len(self.lines):
            line = self.lines[look]
            stripped = line.strip()
            if not stripped:
                breaks += 1
                look += 1
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent <= floor or stripped.startswith("#") or (indent == 0 and _is_marker(line)):
                break
            body, commented = _strip_comment(stripped)
            self.pos = look
            self.check_inside(body)
            parts.append("\n" * breaks if breaks else " ")
            parts.append(body)
            breaks = 0
            look += 1
            self.pos = look
        return "".join(parts) if raw else resolve("".join(parts))

    def check_inside(self, text: str) -> None:
        if ": " in text or ":\t" in text or text.endswith(":"):
            raise self.fail("a mapping value is not allowed here")

    def block_scalar(self, text: str, floor: int) -> str:  # noqa: C901
        header, _ = _strip_comment(text)
        style = header[0]
        chomp = ""
        explicit = 0
        for char in header[1:]:
            if char in "+-" and not chomp:
                chomp = char
            elif char in "123456789" and not explicit:
                explicit = int(char)
            else:
                raise self.fail(f"bad block scalar header {header!r}")
        self.pos += 1
        indent = max(floor, 0) + explicit if explicit else 0
        lines: list[str] = []
        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            if not line.strip():
                lines.append(line)
                self.pos += 1
                continue
            current = len(line) - len(line.lstrip(" "))
            if not indent:
                if current <= floor:
                    break
                indent = current
            if current < indent or (current == 0 and _is_marker(line)):
                break
            lines.append(line)
            self.pos += 1
        content = [line[indent:] if len(line) > indent else "" for line in lines]
        while content and not content[-1].strip():
            content.pop()
        trailing = len(lines) - len(content)
        if style == "|":
            body = "\n".join(content)
        else:
            body = self.fold(content)
        if chomp == "-":
            return body
        if chomp == "+":
            return body + "\n" * (trailing + (1 if content else 0))
        return body + "\n" if content else ""

    @staticmethod
    def fold(lines: list[str]) -> str:
        out: list[str] = []
        breaks = 0
        previous_more = True
        started = False
        for line in lines:
            if not line.strip():
                breaks += 1
                continue
            more = line[0] in " \t"
            if not started:
                out.append("\n" * breaks)
                started = True
            elif more or previous_more:
                out.append("\n" * (breaks + 1))
            else:
                out.append("\n" * breaks if breaks else " ")
            out.append(line)
            breaks = 0
            previous_more = more
        return "".join(out)


def loads(data: str | bytes | bytearray) -> Any:
    """Return the data of the YAML document ``data``.

    Raise YAMLError for text that is not YAML or uses a part of YAML
    the reader does not take, and UnicodeDecodeError for bytes that are
    not UTF-8.
    """
    text = bytes(data).decode() if isinstance(data, (bytes, bytearray)) else data
    return _Reader(text).document()


def _plain_ok(text: str) -> bool:
    return (
        bool(text)
        and text == text.strip()
        and text.isprintable()
        and text[0] not in _INDICATORS
        and isinstance(resolve(text), str)
        and not _YAML_1_1.match(text)
        and ": " not in text
        and " #" not in text
        and not text.endswith(":")
    )


def _quote(text: str) -> str:
    out = ['"']
    for char in text:
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif char == "\n":
            out.append("\\n")
        elif char == "\t":
            out.append("\\t")
        elif not char.isprintable():
            code = ord(char)
            if code <= 0xFF:
                out.append(f"\\x{code:02X}")
            elif code <= 0xFFFF:
                out.append(f"\\u{code:04X}")
            else:
                out.append(f"\\U{code:08X}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _literal(text: str) -> list[str] | None:
    """Return the header and lines of ``text`` as a literal block scalar, if it can be one."""
    if "\n" not in text:
        return None
    body = text.rstrip("\n")
    lines = body.split("\n")
    if not body.strip() or any(not line.isprintable() or line != line.rstrip() for line in lines):
        return None
    first = next(line for line in lines if line)
    if first[0] == " ":
        return None
    trailing = len(text) - len(body)
    header = "|-" if trailing == 0 else "|" if trailing == 1 else "|+"
    return [header, *lines, *([""] * (trailing - 1))]


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return ".nan"
        if math.isinf(value):
            return "-.inf" if value < 0 else ".inf"
        text = repr(value)
        return text.replace("e", ".0e") if "e" in text and "." not in text else text
    if isinstance(value, str):
        return value if _plain_ok(value) else _quote(value)
    raise TypeError(f"cannot write {type(value).__name__} as YAML")


def _block(value: Any) -> list[str]:
    """Return the lines of ``value`` as a block node, not indented."""
    if isinstance(value, dict) and value:
        lines: list[str] = []
        for key, item in value.items():
            name = _scalar(str(key))
            literal = _literal(item) if isinstance(item, str) else None
            if literal is not None:
                lines.append(f"{name}: {literal[0]}")
                lines.extend("  " + line for line in literal[1:])
            elif isinstance(item, (dict, list)) and item:
                lines.append(f"{name}:")
                lines.extend("  " + line for line in _block(item))
            else:
                lines.append(f"{name}: {_block(item)[0]}")
        return lines
    if isinstance(value, list) and value:
        lines = []
        for item in value:
            literal = _literal(item) if isinstance(item, str) else None
            child = literal if literal is not None else _block(item)
            lines.append("- " + child[0])
            lines.extend("  " + line for line in child[1:])
        return lines
    if isinstance(value, dict):
        return ["{}"]
    if isinstance(value, list):
        return ["[]"]
    return [_scalar(value)]


def dumps(data: Any) -> str:
    """Return ``data``, made of dicts, lists and JSON scalars, as a YAML document."""
    return "".join(line.rstrip() + "\n" for line in _block(data))
