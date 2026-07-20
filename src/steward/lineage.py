"""lineage: a SET of parsed papers -> a within-set CITATION graph (lineage-graph/1.0).

The DETERMINISTIC half of direction synthesis (scriptorium-spec
`specs/literature-reading.md` P3). Given the `parsed-paper/1.0` files for a set of
own-library papers, this builds the citation graph that links them: for each paper
it walks the parsed `references` and, whenever a reference matches ANOTHER paper in
the same set (by DOI when present, else by normalized title), emits a `cites` edge
whose `evidence` is the matched reference's raw string. Edges are within-set only —
a reference to a paper outside the set produces no edge.

What this does NOT do: the typed relations (extends / supersedes / method-of /
contrasts) and cluster assignments. Those are agent-enriched later in the
`synthesize-direction` skill — this layer only supplies the deterministic
`cites` skeleton + nodes + a year-ordered timeline. No LLM, stdlib only, read-only
(consumes parsed files, produces one lineage-graph file).
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

SCHEMA_VERSION = "lineage-graph/1.0"
GENERATED_BY = "steward lineage"
SCOPE_METHOD = "own-library citation match"

PARSED_PAPER_SCHEMA = "parsed-paper/1.0"


class LineageError(RuntimeError):
    pass


# -- normalization -----------------------------------------------------------

def _norm_doi(doi: str | None) -> str:
    """Lowercase a DOI and strip a leading resolver URL / `doi:` prefix."""
    if not doi:
        return ""
    d = doi.strip().lower()
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", d)
    return d.strip()


def _norm_title(title: str | None) -> str:
    """Collapse a title to a comparison key: lowercase, alphanumerics + spaces,
    single-spaced. Robust to punctuation/whitespace differences between a paper's
    own title and how another paper cites it."""
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


# -- loading -----------------------------------------------------------------

def load_parsed(path: Path) -> dict:
    """Load one parsed-paper/1.0 file, raising LineageError on a wrong format."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise LineageError(f"{path}: not valid JSON ({e})") from e
    if not isinstance(doc, dict):
        raise LineageError(f"{path}: expected a parsed-paper object")
    sv = doc.get("schema_version", "")
    if sv != PARSED_PAPER_SCHEMA:
        raise LineageError(
            f"{path}: not a {PARSED_PAPER_SCHEMA} file (schema_version={sv!r}). "
            "Run `steward parse` first.")
    if not doc.get("id"):
        raise LineageError(f"{path}: parsed-paper has no `id` (citekey)")
    return doc


def load_set(paths: list[Path]) -> list[dict]:
    """Load a set of parsed-paper files, de-duplicating on citekey (first wins)."""
    papers: list[dict] = []
    seen: set[str] = set()
    for p in paths:
        doc = load_parsed(p)
        ck = doc["id"]
        if ck in seen:
            continue
        seen.add(ck)
        papers.append(doc)
    return papers


# -- graph build -------------------------------------------------------------

def _node(paper: dict) -> dict:
    """A graph node from a parsed-paper's metadata (citekey/title/year)."""
    md = paper.get("metadata") or {}
    node = {"citekey": paper["id"]}
    if md.get("title"):
        node["title"] = md["title"]
    if md.get("year"):
        node["year"] = str(md["year"])
    return node


def _ref_evidence(ref: dict) -> str:
    """The evidence string for a citation edge: the reference's raw text, or a
    best-effort reconstruction from its title/year when no raw was parsed."""
    raw = (ref.get("raw") or "").strip()
    if raw:
        return raw
    bits = [b for b in (ref.get("title"), ref.get("year")) if b]
    return " ".join(str(b) for b in bits)


def build_graph(papers: list[dict], *, query: str = "",
                created: str | None = None) -> dict:
    """Build a lineage-graph/1.0 from a set of parsed-paper/1.0 dicts.

    Within-set citation edges only: for each paper, a reference that matches
    ANOTHER paper in the set (DOI first, else normalized title) -> a `cites` edge
    {from, to, relation, evidence}. Self-citations and out-of-set references are
    dropped. Nodes carry citekey/title/year; `timeline` is the citekeys in
    year-ascending order (papers lacking a year sort last, input order preserved).
    """
    nodes = [_node(p) for p in papers]

    # within-set lookup tables: DOI and normalized title -> citekey.
    by_doi: dict[str, str] = {}
    by_title: dict[str, str] = {}
    for p in papers:
        ck = p["id"]
        md = p.get("metadata") or {}
        doi = _norm_doi(md.get("doi"))
        if doi:
            by_doi.setdefault(doi, ck)
        title = _norm_title(md.get("title"))
        if title:
            by_title.setdefault(title, ck)

    edges: list[dict] = []
    for p in papers:
        src = p["id"]
        for ref in p.get("references") or []:
            if not isinstance(ref, dict):
                continue
            target = None
            doi = _norm_doi(ref.get("doi"))
            if doi:
                target = by_doi.get(doi)
            if target is None:
                title = _norm_title(ref.get("title"))
                if title:
                    target = by_title.get(title)
            if target is None or target == src:
                continue  # out-of-set reference or self-citation -> no edge
            edge = {"from": src, "to": target, "relation": "cites"}
            evidence = _ref_evidence(ref)
            if evidence:
                edge["evidence"] = evidence
            edges.append(edge)

    timeline = _timeline(papers)

    if created is None:
        created = (datetime.datetime.now(datetime.timezone.utc)
                   .replace(microsecond=0).isoformat().replace("+00:00", "Z"))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": GENERATED_BY,
        "direction": {
            "query": query,
            "scope_method": SCOPE_METHOD,
            "created": created,
        },
        "nodes": nodes,
        "edges": edges,
        "timeline": timeline,
    }


def _timeline(papers: list[dict]) -> list[str]:
    """Citekeys in year-ascending order; missing/unparseable years sort last,
    ties and year-less papers keep input order (stable sort)."""
    def key(idx_paper):
        idx, p = idx_paper
        yr = str((p.get("metadata") or {}).get("year") or "")
        m = re.match(r"\d{4}", yr)
        return (0, int(m.group()), idx) if m else (1, 0, idx)

    ordered = sorted(enumerate(papers), key=key)
    return [p["id"] for _, p in ordered]
