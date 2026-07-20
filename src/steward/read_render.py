"""read_render: a reading-note/1.0 -> a self-contained, browsable Obsidian note.

The deterministic PROJECTION half of staged reading: the `read-paper` skill saves
its `reading-note/1.0` (the four on-demand stages — glance / close_read /
deep_read / situate), then this turns that JSON into the per-paper long-term
archive — ONE self-contained Markdown note that renders in vanilla Obsidian:
YAML frontmatter (Obsidian properties), a section per FILLED stage (absent stages
skipped), the situate lineage as `[[citekey]]` wikilinks, and a links block to the
library note + the parsed/annotation sources.

`render()` is a pure, deterministic function: same note in -> identical string
out, no I/O, no clocks (it reuses the note's own `created`). The machine source of
truth stays the `reading-note/1.0` JSON; this `.md` is the canonical browsable
view, re-rendered idempotently. reading-note carries no title/authors/year (those
live in `library-kb/1.0` or `library-kb/1.1`), so an OPTIONAL `kb_item` enriches
the frontmatter;
without it the note renders only what it carries.
"""
from __future__ import annotations

import re

from . import __version__

SCHEMA_VERSION = "reading-note/1.0"


class RenderError(RuntimeError):
    pass


# -- helpers -----------------------------------------------------------------

def _oneline(text) -> str:
    """Collapse CR/LF/tabs so a value can never break/forge YAML or a wikilink.
    None -> "" so an absent optional field is dropped by the guards (never the
    literal string "None")."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def _y(value) -> str:
    """A YAML-safe scalar: a JSON string is valid YAML, with newlines escaped."""
    import json
    return json.dumps(_oneline(value), ensure_ascii=False)


def _y_list(values) -> str:
    """A YAML-safe inline flow list `[a, b]` of one-lined, JSON-quoted scalars."""
    items = [v for v in (values or []) if _oneline(v)]
    return "[" + ", ".join(_y(v) for v in items) + "]"


def _wikilink(citekey) -> str:
    """A safe `[[citekey]]` wikilink: one-lined and stripped of `[`/`]`/`|` so a
    value can never forge or terminate the link target."""
    key = _oneline(citekey).replace("[", "").replace("]", "").replace("|", "")
    return f"[[{key}]]"


def _para(text) -> str:
    """A body paragraph: a string with CR/LF normalized to LF, trailing space
    trimmed. Unlike frontmatter, body prose may keep its internal newlines."""
    return re.sub(r"[ \t]+\n", "\n", str(text).replace("\r\n", "\n").replace("\r", "\n")).strip()


# -- render ------------------------------------------------------------------

def render(note: dict, *, kb_item: dict | None = None) -> str:
    """Render a reading-note/1.0 dict into a self-contained Obsidian Markdown note.

    Deterministic and side-effect-free: no I/O, no clock — `created` is copied
    from the note, never regenerated. A section is emitted only for a stage that
    is actually present (and non-empty). Raises RenderError if the input is not a
    reading-note/1.0.

    `kb_item` (optional, a `library-kb/1.0` or `library-kb/1.1` item) enriches
    the frontmatter with
    title / authors / year (and a kb tldr fallback); without it the note renders
    only what the reading-note carries.
    """
    if not isinstance(note, dict):
        raise RenderError("expected a reading-note/1.0 object")
    sv = note.get("schema_version")
    if sv != SCHEMA_VERSION:
        raise RenderError(
            f"not a {SCHEMA_VERSION} note (schema_version={sv!r}). "
            "Run the read-paper skill to produce one first.")

    citekey = _oneline(note.get("id") or "")
    if not citekey:
        raise RenderError("reading-note has no `id` (Better BibTeX citekey)")

    stages = note.get("stages") if isinstance(note.get("stages"), dict) else {}
    glance = stages.get("glance") if isinstance(stages.get("glance"), dict) else None
    close_read = stages.get("close_read") if isinstance(stages.get("close_read"), dict) else None
    deep_read = stages.get("deep_read") if isinstance(stages.get("deep_read"), dict) else None
    situate = stages.get("situate") if isinstance(stages.get("situate"), dict) else None
    kb = kb_item if isinstance(kb_item, dict) else None

    title = _oneline((kb or {}).get("title") or "") or citekey

    L: list[str] = []
    # -- frontmatter (Obsidian properties; the JSON is the machine SSoT) -------
    L.append("---")
    L.append(f"citekey: {_y(citekey)}")
    L.append("type: reading-note")
    if kb and _oneline(kb.get("title")):
        L.append(f"title: {_y(kb.get('title'))}")
    if kb and kb.get("authors"):
        L.append(f"authors: {_y_list(kb.get('authors'))}")
    if kb and _oneline(kb.get("year")):
        L.append(f"year: {_y(kb.get('year'))}")
    if _oneline(note.get("read_status")):
        L.append(f"read_status: {_y(note.get('read_status'))}")
    if _oneline(note.get("doi")):
        L.append(f"doi: {_y(note.get('doi'))}")
    if _oneline(note.get("zotero_key")):
        L.append(f"zotero_key: {_y(note.get('zotero_key'))}")
    if _oneline(note.get("created")):
        L.append(f"created: {_y(note.get('created'))}")
    if glance and glance.get("tags"):
        L.append(f"tags: {_y_list(glance.get('tags'))}")
    L.append("---")
    L.append("")
    L.append(f"# {title}")
    L.append("")

    # -- one section PER FILLED stage (absent stages skipped) -----------------
    if glance:
        sec = _glance_section(glance)
        if sec:
            L += sec
    if close_read:
        sec = _close_read_section(close_read)
        if sec:
            L += sec
    if deep_read:
        sec = _deep_read_section(deep_read)
        if sec:
            L += sec
    if situate:
        sec = _situate_section(situate)
        if sec:
            L += sec

    # -- annotations (own section, only when present) -------------------------
    L += _annotations_section(note.get("sources"))

    # -- links block ----------------------------------------------------------
    L += _links_section(citekey, note.get("sources"))

    # -- footer ---------------------------------------------------------------
    L += ["---", ""]
    gen = _oneline(note.get("generated_by"))
    if gen:
        L.append(f"> **generated_by:** {gen}")
    L.append(f"> Machine source of truth: `reading-notes/{citekey}.json` "
             "(this note is a derived, regenerable view).")
    L.append(f"> Rendered by steward read-render ({__version__}).")
    L.append("")
    return "\n".join(L)


# -- per-stage sections ------------------------------------------------------

def _glance_section(glance: dict) -> list[str]:
    """## 速览 · Glance — tldr (prose) + key_findings (bullets) + tags."""
    tldr = _para(glance.get("tldr") or "")
    findings = [f for f in (glance.get("key_findings") or []) if _oneline(f)]
    tags = [t for t in (glance.get("tags") or []) if _oneline(t)]
    if not (tldr or findings or tags):
        return []
    out = ["## 速览 · Glance", ""]
    if tldr:
        out += [tldr, ""]
    if findings:
        out.append("**Key findings**")
        out += [f"- {_oneline(f)}" for f in findings]
        out.append("")
    if tags:
        out += ["**Tags:** " + " ".join(f"#{_tag(t)}" for t in tags), ""]
    return out


def _close_read_section(cr: dict) -> list[str]:
    """## 精读 · Close read — question/method/data/results + figures.

    A figure entry that looks like an IMAGE path (ends .png/.jpg/.jpeg/.gif/.webp,
    optionally with a leading path) is rendered as an Obsidian embed `![[path]]`;
    everything else (caption text) renders as a `- caption` bullet as before.
    Actual figure images require an image-emitting parse (local MinerU); GROBID /
    parsed-paper carry caption text only, so embeds light up only when a figure
    path was populated — this is render-support, not extraction.
    """
    fields = [("Question", cr.get("question")), ("Method", cr.get("method")),
              ("Data", cr.get("data")), ("Results", cr.get("results"))]
    figures = [f for f in (cr.get("figures") or []) if _oneline(f)]
    body = _labeled(fields)
    if not (body or figures):
        return []
    out = ["## 精读 · Close read", ""] + body
    if figures:
        out.append("**Figures**")
        for f in figures:
            f = _oneline(f)
            if _is_image_path(f):
                out.append(f"![[{_embed_target(f)}]]")   # Obsidian image embed
            else:
                out.append(f"- {f}")             # caption text (GROBID, etc.)
        out.append("")
    return out


def _deep_read_section(dr: dict) -> list[str]:
    """## 深读 · Deep read — critique/reproducibility/limits/relation paragraphs."""
    fields = [("Critique", dr.get("critique")),
              ("Reproducibility", dr.get("reproducibility")),
              ("Limits", dr.get("limits")),
              ("Relation to my work", dr.get("relation_to_my_work"))]
    body = _labeled(fields)
    if not body:
        return []
    return ["## 深读 · Deep read", ""] + body


def _situate_section(sit: dict) -> list[str]:
    """## 串联定位 · Situate — direction (prose) + lineage_refs as wikilinks."""
    direction = _para(sit.get("direction") or "")
    refs = [r for r in (sit.get("lineage_refs") or []) if _oneline(r)]
    if not (direction or refs):
        return []
    out = ["## 串联定位 · Situate", ""]
    if direction:
        out += [direction, ""]
    if refs:
        out.append("**Lineage:**")
        out += [f"- {_wikilink(r)}" for r in refs]
        out.append("")
    return out


def _annotations_section(sources) -> list[str]:
    """## 标注 · Annotations — the user's highlights, rendered as readable content.

    Only emitted when `sources.annotations` is non-empty. An entry that looks like
    a URI/path (a `scheme:` prefix, or a `/`/`#` with no spaces — i.e. a reference,
    not prose) renders as a link/`code`; otherwise the entry is highlight TEXT and
    renders as a `> blockquote` so it shows inline. The other Links (library note,
    parsed_file, zotero_uri) stay in the `## 链接 · Links` section."""
    src = sources if isinstance(sources, dict) else {}
    annotations = [_oneline(a) for a in (src.get("annotations") or []) if _oneline(a)]
    if not annotations:
        return []
    out = ["## 标注 · Annotations", ""]
    for a in annotations:
        if _is_uri(a):
            if _has_scheme(a):
                out += [f"- <{_oneline(a)}>", ""]            # angle-bracket autolink
            else:
                out += [f"- `{_code_safe(a)}`", ""]          # inline code path/ref
        else:
            out += [f"> {a}", ""]               # highlight text, inlined (already one-lined)
    return out


def _links_section(citekey: str, sources) -> list[str]:
    """Links block: a wikilink to the library note + parsed/Zotero sources."""
    out = ["## 链接 · Links", "",
           f"- Library note: {_wikilink(citekey)}"]
    src = sources if isinstance(sources, dict) else {}
    parsed = _oneline(src.get("parsed_file"))
    if parsed:
        out.append(f"- Parsed file: `{parsed}`")
    zuri = _oneline(src.get("zotero_uri"))
    if zuri:
        out.append(f"- Zotero: <{zuri}>")
    out.append("")
    return out


# -- small text helpers ------------------------------------------------------

def _labeled(fields) -> list[str]:
    """Render `(label, value)` pairs as `**Label** — paragraph` blocks, skipping
    empty values. Each block is followed by a blank line."""
    out: list[str] = []
    for label, value in fields:
        text = _para(value or "")
        if text:
            out += [f"**{label}**", "", text, ""]
    return out


def _tag(text) -> str:
    """An Obsidian-#tag-safe token: collapse whitespace to `-`, drop a leading #."""
    t = re.sub(r"\s+", "-", _oneline(text)).lstrip("#")
    return t or "tag"


_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def _is_image_path(text: str) -> bool:
    """True if a (one-lined) string looks like an image path — an image extension,
    optionally with a leading path, and no internal spaces (a caption like
    'Fig. 4 ... .png plot' is prose, not a path)."""
    s = text.strip()
    return bool(s) and " " not in s and s.lower().endswith(_IMAGE_EXTS)


def _embed_target(text: str) -> str:
    """An Obsidian `![[target]]` embed target stripped of `[`/`]`/`|` so a value can
    never close the embed early or forge a second `![[ ]]` (mirrors `_wikilink`)."""
    return _oneline(text).replace("[", "").replace("]", "").replace("|", "")


def _code_safe(text: str) -> str:
    """An inline-`code`-span-safe value: one line with backticks dropped (a backtick
    would terminate the span) and `[`/`]` stripped (so a path can't carry a forged
    `![[ ]]` embed payload out of the span)."""
    return _oneline(text).replace("`", "").replace("[", "").replace("]", "")


def _has_scheme(text: str) -> bool:
    """True if a string starts with a URI scheme like `http:` / `zotero:` / `file:`
    (a leading `scheme:` token, not a Windows drive letter like `C:`)."""
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]+:", text.strip()))


def _is_uri(text: str) -> bool:
    """True if a string looks like a URI/path reference rather than highlight prose:
    a `scheme:` prefix, or it contains a `/` or `#` and has no spaces (a path /
    fragment id). Plain text with spaces is treated as a highlight (blockquote)."""
    s = text.strip()
    if _has_scheme(s):
        return True
    return " " not in s and ("/" in s or "#" in s)
