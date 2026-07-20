"""A tiny stdlib-only YAML *subset* reader.

Steward is dependency-free by design, but Phase B has to read two real YAML
inputs: an ML project's `config_used.yaml` (PyYAML `safe_dump` block style) and
the `project/1.0` frontmatter of Obsidian notes. Rather than take a runtime
dependency, this parses exactly the block subset those producers emit.

Supported: block mappings, block sequences (items at the same indent as their
key, as `safe_dump` writes them), nested structures, plain/single/double-quoted
scalars, int/float/bool/null, inline-flow `{}` / `[]` / `[a, b]` / `{k: v}`, and
multi-line plain-scalar continuation. NOT supported (absent from our inputs):
anchors/aliases, multiple documents, block scalars (`|`, `>`), tags, and inline
comments after a value. Two-space block indentation is assumed.
"""
from __future__ import annotations

import json
import re

_INT = re.compile(r"^[+-]?\d+$")
_FLOAT = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$")
_MAP_ENTRY = re.compile(r"^.+?:(?:\s|$)")


def parse(text: str):
    """Parse a YAML-subset document; returns a dict, list, scalar, or None."""
    lines: list[list] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        stripped = raw.lstrip(" ")
        if stripped.startswith("#"):
            continue
        lines.append([len(raw) - len(stripped), stripped.rstrip()])
    if not lines:
        return None
    value, _ = _node(lines, 0)
    return value


def parse_frontmatter(md_text: str) -> dict:
    """Return the leading `---` YAML frontmatter of a markdown file as a dict."""
    text = md_text.lstrip("﻿")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    for j in range(1, len(lines)):
        if lines[j].strip() in ("---", "..."):
            data = parse("\n".join(lines[1:j]))
            return data if isinstance(data, dict) else {}
    return {}


# -- internals ---------------------------------------------------------------

def _node(lines, i):
    content = lines[i][1]
    if content == "-" or content.startswith("- "):
        return _seq(lines, i, lines[i][0])
    return _map(lines, i, lines[i][0])


def _map(lines, i, indent):
    result: dict = {}
    while i < len(lines):
        ind, content = lines[i]
        if ind != indent or content == "-" or content.startswith("- "):
            break
        key, inline = _split_kv(content)
        i += 1
        if inline is None:
            val, i = _child(lines, i, indent)
        else:
            val = _scalar(inline)
            while i < len(lines) and lines[i][0] > indent and not _structural(lines[i][1]):
                val = f"{val} {lines[i][1].strip()}"
                i += 1
        result[_scalar(key)] = val
    return result, i


def _seq(lines, i, indent):
    result: list = []
    while i < len(lines):
        ind, content = lines[i]
        if ind != indent or not (content == "-" or content.startswith("- ")):
            break
        if content == "-":
            i += 1
            if i < len(lines) and lines[i][0] > indent:
                val, i = _node(lines, i)
            else:
                val = None
        else:
            rest = content[2:]
            if _MAP_ENTRY.match(rest):
                lines[i] = [indent + 2, rest]   # virtual dedent: first key of the item map
                val, i = _map(lines, i, indent + 2)
            else:
                val = _scalar(rest)
                i += 1
        result.append(val)
    return result, i


def _child(lines, i, indent):
    """Parse the nested block that follows an empty `key:` (or null)."""
    if i >= len(lines):
        return None, i
    nind, ncont = lines[i]
    if (ncont == "-" or ncont.startswith("- ")) and nind >= indent:
        return _seq(lines, i, nind)          # block seq items sit at >= the key's indent
    if nind > indent:
        return _map(lines, i, nind)
    return None, i


def _structural(content: str) -> bool:
    return content == "-" or content.startswith("- ") or bool(_MAP_ENTRY.match(content))


def _split_kv(content: str):
    if content.endswith(":") and ": " not in content:
        return content[:-1], None
    idx = content.find(": ")
    if idx == -1:
        return content, None
    return content[:idx], content[idx + 2:]


def _scalar(s):
    s = s.strip()
    if not s:
        return None
    if s[0] in "'\"":
        return _quoted(s)
    if s[0] == "[" and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_scalar(p) for p in _split_top(inner)] if inner else []
    if s[0] == "{" and s.endswith("}"):
        inner = s[1:-1].strip()
        if not inner:
            return {}
        out = {}
        for p in _split_top(inner):
            k, _, v = p.partition(":")
            out[_scalar(k)] = _scalar(v)
        return out
    low = s.lower()
    if low in ("null", "~"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    if _INT.match(s):
        return int(s)
    if _FLOAT.match(s):
        return float(s)
    return s


def _quoted(s: str):
    q = s[0]
    if not (len(s) >= 2 and s[-1] == q):
        return s
    body = s[1:-1]
    if q == '"':
        try:
            return json.loads(s)
        except ValueError:
            return body
    return body.replace("''", "'")


def _split_top(s: str) -> list[str]:
    """Split a flow collection body on top-level commas (respecting nesting/quotes)."""
    parts, depth, quote, buf = [], 0, None, ""
    for ch in s:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            buf += ch
        elif ch in "[{":
            depth += 1
            buf += ch
        elif ch in "]}":
            depth -= 1
            buf += ch
        elif ch == "," and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf)
    return parts
