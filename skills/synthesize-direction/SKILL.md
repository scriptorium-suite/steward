---
name: synthesize-direction
description: >-
  Synthesize a research direction from the user's own library, producing a
  grounded review/1.0 and lineage-graph/1.0 plus Markdown projections. Use for
  requests such as 梳理这个方向、系统综述某方向、这个方向的脉络, synthesize this
  direction, or how did this direction evolve.
---

# Synthesize direction (research-direction synthesis)

Take a research **question / topic** and produce a systematic synthesis of that
*direction* from the user's **own library**: who built on whom (lineage), how the
direction came to be and where it is now (narrative), and a side-by-side
**comparison table** of the papers. You (the agent — Claude Code / Codex) do
**all** the reasoning and prose **in this session**; suite-owned code wires
**no LLM client** or hidden model call. Any generation egress belongs to the
selected Codex or Claude Code host. The deterministic scaffolding — scoping the
papers, parsing PDFs, walking the citation graph, the anti-fabrication tables and
the contracts — is the suite's; the interpretation is yours. This is the same
"agent is the intelligence" precedent as the sibling `read-paper` and
`review-fill` skills and Provenance's `session-summary`.

This is the agent-driven heart of **P3** (see scriptorium-spec
`specs/literature-reading.md` §4-5). It produces two new contracts —
**`review/1.0`** (the synthesis note) and **`lineage-graph/1.0`** (the citation
graph) — and consumes the existing `parsed-paper/1.0`, `reading-note/1.0`, and
`library-kb/1.x` as its anti-fabrication sources of truth.

## Input

> **Synthetic examples:** Every `[SYNTHETIC] XQ-17` identity, citekey, DOI, title, author, measurement, and domain phrase below is fabricated test data. It does not describe a real paper, person, library, or research project.

A research **question or topic** in natural language — e.g. "梳理一下
[SYNTHETIC] XQ-17 校准方法这个方向" / "how did chain-of-thought prompting evolve" /
"系统综述 X 方向". That is all you need; everything else is derived.

## Steps

### 1. Scope — find the relevant papers in the library

Pull the candidate set from what is **already here** (no new cloud dependency):

- **Local read-only Zotero MCP** — keyword / full-text search + collection / tag
  filters over live metadata, full text, annotations, and notes.
- **`library-kb/1.x`** — the Steward-emitted KB (`<data_dir>/kb/library.json` by
  default). Filter on `folders` (collection paths), `tags` / `aiTags`, `tldr`,
  `year`, `readStatus`. This is also where the **citekeys / years / DOIs** come
  from for the comparison table (never invent them — see anti-fabrication).
- **Already-written `parsed-paper/1.0` files** (`parsed/<citekey>.json` from
  `steward parse`) and **`reading-note/1.0` files** (`reading-notes/<citekey>.json`
  from `read-paper`) — papers you have already read carry close/deep reads,
  figures, and situate edges you can reuse directly.

Resolve each scoped paper to its **Better BibTeX citekey** (the universal join id
across the suite). State the scoped set and the filters you used before going on.

> **P3+ note — semantic recall is not available yet.** Local-embedding semantic
> recall (BAAI/bge-m3 via sentence-transformers + sqlite-vec, on-device, no
> egress) is the **P3+ enhancement**, NOT wired today. Scope with FTS5 keyword /
> collection / tag filters only. If keyword recall feels thin (a fast-moving
> direction, inconsistent tagging, cross-language terms), **say so** — tell the
> user the scope may be incomplete and that semantic recall will improve it later,
> rather than pretending the set is exhaustive.

### 2. Ensure parsed

The comparison table and lineage are built **from the parsed files**, so each
scoped paper needs a `parsed-paper/1.0`. For any scoped paper lacking one
(`parsed/<citekey>.json` absent), **suggest or run**:

```
steward parse <citekey> --kb <library-kb.json>     # -> parsed/<citekey>.json
```

`steward parse` runs a **local** parser (GROBID on localhost, no cloud egress)
and emits structured `sections[]` + `references[]` + `metadata` + figure/table
descriptors. If a paper has no reachable PDF and cannot be parsed, keep it in the
synthesis but mark its table cells unknown — do not guess (anti-fabrication).

### 3. Lineage — deterministic graph, then enrich with typed relations

Get the **deterministic citation graph** among the scoped papers from Steward
(walks the `references[]` of each parsed file — own-library edges only):

```
steward lineage --papers <citekey,...> --query "<the question>"   # -> lineage-graph/1.0
```

This returns a `lineage-graph/1.0` whose edges are the raw `cites` relations
Steward could resolve deterministically. **You then ENRICH** those edges with the
**typed relations** your reading supports — `extends` / `supersedes` /
`method-of` / `contrasts` (in addition to the bare `cites`) — each carrying the
`evidence` (the section / sentence the relation rests on), plus `cluster`
assignments on the nodes. Only add an edge you can ground; drop edges you cannot
verify rather than inventing a lineage.

**Save the enriched graph** as a `lineage-graph/1.0` JSON (e.g.
`Reviews/<direction-slug>.lineage.json`). That JSON is the **machine source of
truth**. You do NOT hand-write Breadcrumbs frontmatter — the rendering is
deterministic (step 5). The per-paper Breadcrumbs frontmatter (the
relationship-field convention, scriptorium-spec `specs/literature-reading.md` §3 —
the fixed keys `cites` / `extends` / `supersedes` / `method-of` / `contrasts`)
becomes **opportunistic**, stamped from this same JSON in step 5.

### 4. Synthesize — write the review/1.0

Write a **`review/1.0`** with two halves, both anti-fabricated:

- **Narrative `sections[]`** — outline first, then prose. Cover: **how the
  direction came to be** (origins / seminal work), the **key turns** (method
  shifts, datasets, results that moved the field), and the **current gaps**.
  Cite papers as "Author Year" / by citekey in prose. Build the narrative from
  the parsed sections + reading-notes you actually read.
- **`comparison_table`** — rows = papers (by citekey), columns =
  method / data / result / … (pick the axes that discriminate this direction).
  Every cell is drawn **FROM the parsed-paper `sections[]` + `library-kb`**
  (citekeys / years / DOIs from the KB).

Also fill `gaps[]` (open problems the direction has not solved),
`priority_reads[]` (the handful a newcomer should read first, by citekey), and
`lineage_ref` (→ the `lineage-graph/1.0` from step 3).

> **Anti-fabrication — hard rule (same guarantee as Steward `review assemble`):**
> **never invent a method, a number, or a citation.** Methods / data / numeric
> results / figures / quotes come from the **parsed-paper files**, the **reading
> notes**, the **MCP-read full text**, or the **`library-kb`** — nothing else.
> Citekeys / years / DOIs come from the KB. **If a cell is unknown, mark it
> (`—` / "unknown" / "not parsed"), don't guess.** Be honest about confidence:
> a paper that is unparsed or abstract-only carries less weight than one you
> close-read — say so. Do not state a numeric result as an established conclusion
> unless you read it.

### 5. Land — authoritative contracts + derived vault views

- **Review contract → vault `Reviews/`.** Write the authoritative `review/1.0`
  JSON as `Reviews/<direction-slug>.review.json`. If a human-readable review is
  wanted, derive `Reviews/<direction-slug>.md` from that JSON; the Markdown file
  is a rebuildable projection, not the contract or its only copy. State both
  paths you wrote.
- **Lineage → vault, renderable (deterministic).** Save the enriched
  `lineage-graph/1.0` JSON (step 3), then render it with Steward — do NOT
  hand-build the visual:

  ```
  steward lineage-render --graph Reviews/<direction-slug>.lineage.json --vault <vault>
  ```

  This deterministically produces the **canonical, reproducible visual** —
  `Reviews/<direction-slug>.lineage.md`, a **self-contained** note (native
  **Mermaid** flowchart with relation-labeled edges + cluster subgraphs, a
  chronological timeline, and a plain edge table). It renders in **vanilla
  Obsidian, no plugin**, and does not depend on per-paper notes existing
  (lean-vault per `specs/vault-layout.md`). The JSON stays the machine source of
  truth; the note is a regenerable view.
- **Per-paper Breadcrumbs frontmatter → opportunistic.** If (and only if) the
  per-paper notes already live in the vault, also stamp the relationship-field
  frontmatter onto them from the same JSON:

  ```
  steward lineage-render --graph Reviews/<direction-slug>.lineage.json --vault <vault> --stamp-notes
  ```

  `--stamp-notes` is **opt-in**: it only stamps notes that **already exist**
  (Literature/ + reading-notes/), **merges** (never clobbers), and **never
  creates** a paper note — absent notes are skipped without assuming they were
  archived elsewhere. ExcaliBrain / Dataview / Breadcrumbs then render the 脉络 off that
  frontmatter where it exists; everyone else reads the Mermaid note.
- **Provenance boundary.** Direct ingestion of `review/1.0` and
  `lineage-graph/1.0` is not implemented. Keep the contract files in the
  workspace and report this release gap; do not claim they were archived,
  indexed, or surfaced by Provenance. A future sync-layer adapter may map them
  explicitly without changing these source contracts.

## Contracts

### `review/1.0` — the direction synthesis (narrative + comparison table)

```json
{
  "schema_version": "review/1.0",
  "direction": { "query": "<the question>", "created": "2026-06-22T00:00:00Z" },
  "sections": [
    { "heading": "How the direction came to be", "prose": "outline -> prose, cite by citekey / Author Year" },
    { "heading": "Key turns", "prose": "..." },
    { "heading": "Current gaps", "prose": "..." }
  ],
  "comparison_table": {
    "columns": ["Method", "Data", "Result"],
    "rows": [
      { "citekey": "xq17SyntheticStudy001", "cells": ["...", "...", "..."] },
      { "citekey": "xq17SyntheticStudy002", "cells": ["—", "unknown", "not parsed"] }
    ]
  },
  "gaps": ["open problem 1", "open problem 2"],
  "priority_reads": ["xq17SyntheticStudy001"],
  "lineage_ref": "Reviews/<direction-slug>.lineage.json",
  "generated_by": "synthesize-direction skill (agent: <Claude Code | Codex>)"
}
```

### `lineage-graph/1.0` — the direction's 脉络 (own-library)

```json
{
  "schema_version": "lineage-graph/1.0",
  "direction": { "query": "<the question>", "scope_method": "...", "created": "2026-06-22T00:00:00Z" },
  "nodes": [ { "citekey": "xq17SyntheticStudy001", "title": "...", "year": "2008", "cluster": "[SYNTHETIC] XQ-17" } ],
  "edges": [
    { "from": "xq17SyntheticStudy001", "to": "xq17SyntheticStudy003", "relation": "extends", "evidence": "recalibrates the synthetic 1996 XQ-17 model" }
  ],
  "clusters": [ { "id": "xq17-models", "label": "[SYNTHETIC] XQ-17 calibration models" } ],
  "timeline": ["xq17SyntheticStudy003", "xq17SyntheticStudy001"]
}
```

- `relation` ∈ `cites` | `extends` | `supersedes` | `method-of` | `contrasts`.
  `cites` is what `steward lineage` resolves deterministically; the typed
  relations are the agent's enrichment, each with `evidence`.
- Both contracts are now ratified JSON Schemas in scriptorium-spec —
  `schemas/review/v1.json` and `schemas/lineage-graph/v1.json` (design in
  `specs/literature-reading.md` §3). The shapes above match those schemas; keep the
  keys exactly as written and validate with `python tools/validate.py` before
  landing. Note `review/1.0`'s `direction` carries only `query` + `created` — the
  `scope_method` field lives on the `lineage-graph` direction, not the review.

> **Note — `review/1.0` ≠ `review-draft/1.0`.** The sibling `review-fill` skill
> writes a `review-draft/1.0` (a digest *roadmap* for the existing `steward
> review` flow). This skill writes a **`review/1.0`** (a direction *synthesis*
> with a `comparison_table`, `gaps`, `priority_reads`, and a `lineage_ref`). They
> are distinct contracts — do not conflate them.

## Local + read-only

- The **Zotero MCP is read-only and local** (local Zotero API, no key; semantic
  search local-only or off — never cloud). You never write to Zotero.
- **`steward parse` / `steward lineage` / `steward lineage-render` are local**
  (GROBID + reference-list walking + Markdown projection on the user's machine,
  no cloud egress).
- All reasoning + prose happens **in this session**. Suite-owned code opens no
  model connection and adds no hidden generation call. The selected Codex or
  Claude Code host owns any configured model/network egress; do not describe a
  cloud-backed host session as fully local. The only suite-local model in the
  planned stack is the optional embedding model used for retrieval (P3+) — not
  for generation.
- **Writebacks** (Zotero edits, Read-Status changes) stay with the **user or the
  sync layer**, not this skill.

## Guardrails

- **Outputs:** the authoritative `Reviews/<slug>.review.json` (`review/1.0`), an
  optional rebuildable `Reviews/<slug>.md` projection, and the authoritative
  `lineage-graph/1.0` JSON plus its deterministic
  `Reviews/<slug>.lineage.md` render (via `steward lineage-render`;
  Breadcrumbs frontmatter is opt-in `--stamp-notes`). Direct Provenance
  ingestion remains a release gap. Do not overwrite human-input zones or JSON
  contract artifacts; only the Markdown files are tool-owned derived views.
- **Anti-fabrication is non-negotiable** — see step 4. Unknown ⇒ mark it.
- **Be honest about recall** — semantic recall is P3+, not available; flag a thin
  scope rather than implying completeness.
- **Language:** note content matches the library's working language (Chinese by
  default here); the JSON keys stay exactly as in the contracts.
- **No additional connector/network calls beyond the local Zotero MCP and
  prov-mcp.** The selected agent host may use its configured model endpoint;
  that host-managed egress must follow the user's host policy. The skill adds
  no telemetry. No commit — landing the files is enough; committing stays with
  the user.
