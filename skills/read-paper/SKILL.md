---
name: read-paper
description: >-
  Read one paper at glance, close, deep, or situate depth and create or update
  its reading-note/1.0 from local library evidence. Use for requests such as
  读这篇、精读、深读这篇文献、串一下这篇的位置, read this paper, or situate this paper.
---

# Read paper (staged literature reading)

Read ONE paper at the **depth** the user asks for, and write or update its
`reading-note/1.0` file. The depths escalate and are **on-demand** — you fill
only the stage(s) requested and never touch the others. You (the agent — Claude
Code / Codex) do **all** the reasoning and prose **in this session**; suite-owned
code wires **no LLM client**. This is the same "agent is the intelligence" precedent as the
sibling `review-fill` skill and Provenance's `session-summary`: the deterministic
scaffolding (library-kb, the Zotero MCP, annotations, the parsed file) is the
suite's; the interpretation is yours.

## Inputs

- **A paper** — identified by its **Better BibTeX citekey** (the stable
  reading-note id) or a **Zotero selection** the user points you at. If you were
  given a selection, resolve it to its citekey first (via the Zotero MCP or the
  `library-kb`); the citekey is what keys the note.
- **A target DEPTH** — one of `glance` / `close` / `deep` / `situate`. If the
  user said "读这篇" / "read this" without a level, infer from the Read-Status
  (see below) and state which depth you chose before writing.

## The four depths (escalating, on-demand)

| Depth | Reads from | Fills `reading-note` stage | Read-Status it fits |
|---|---|---|---|
| **glance** | `library-kb` (Steward already emits TLDR/tags) — the cheap pass; no full-text read needed | `glance` | To Read |
| **close** | the **parsed-paper file if it exists** (`parsed/<citekey>.json`, structured sections/references from `steward parse`), else the **full text via the local Zotero MCP** (read-only) — plus the user's **annotations** (PDF++ markdown / Zotero) | `close_read` | In Progress |
| **deep** | everything `close` reads (parsed file preferred), **plus Provenance memory** (`get_current_context` via prov-mcp) for the user's project context | `deep_read` | In Progress → Read |
| **situate** | the note so far + other papers' citekeys / `library-kb` to place this paper in its research-direction lineage | `situate` | Read |

Depths are independent and additive: a `deep` request fills `deep_read` only —
it does NOT require `glance`/`close_read` to be present, and it must not rewrite
them if they are.

### glance
The cheapest pass, mostly from `library-kb`. Produce a 1-line TLDR, the tags, and
the key findings already captured. No full-text read is required; if the
`library-kb` entry is thin, say so rather than inventing detail.

### close
You **read the full text** and fold in the user's annotations. Extract: the
research **question**, the **method**, the **data**, the **results**, and the
**figures** that carry the argument. Every figure/number/quote must come from
what you actually read (see anti-fabrication).

- **Figures.** Record the figure as the **caption text** that carries the argument
  (e.g. `"Fig. 4 (predicted vs observed T)"`). If — and only if — an image-emitting
  parse produced a local figure **image file** (local MinerU; **GROBID / parsed-paper
  carry caption text only**), you MAY put its **image path** (ending
  `.png`/`.jpg`/`.jpeg`/`.gif`/`.webp`) into `figures[]` and `read-render` will inline
  it as an Obsidian embed `![[path]]`. Do not invent a path — caption text is the norm.
- **Annotations → `sources.annotations`.** You MAY record a meaningful **highlight's
  TEXT** here (not just a reference like `PDF++/<citekey>#highlight-x`): `read-render`
  renders a plain-text annotation as an inline `> blockquote` (a URI/path entry renders
  as a link/`code`), so the highlight shows in the browsable note. Only record text the
  user actually highlighted — never paraphrase or invent.

**Prefer the parsed-paper file.** If a `parsed-paper/1.0` file exists for this
citekey (default `parsed/<citekey>.json`, written by `steward parse` — local
GROBID, structured `sections[]` + `references[]` + `metadata`), read it **first**:
it gives you clean section text and the reference list without re-parsing the PDF,
and it is fully local. Fall back to reading the **live full text via the local
Zotero MCP** (the P1 behavior) when no parsed file is present. Either way, record
the source you used in `sources.parsed_file` / `sources.annotations`.

### deep
On top of the `close` reading (parsed-paper file preferred over the live MCP
read, same rule as above), pull the user's **project context from Provenance**
(`get_current_context`, optionally `search_brain`, via prov-mcp) so the critique
is grounded in their work. Produce: a **critique**, a **reproducibility**
assessment, the **limits**, and the paper's **relation-to-my-work**. If Provenance
context is unavailable, write the critique from the text alone and note that the
project linkage is missing — don't fabricate a connection.

### situate
Place the paper in its **research-direction lineage**: which direction it belongs
to and the other papers (by **citekey**) it builds on, extends, supersedes, or
contrasts with. Reference real citekeys from the library only; if you cannot
verify a reference edge, leave it out rather than guess.

## Drive depth off Read-Status

The Zotero **Read-Status** (zotero-reading-list convention, stored in the Zotero
`Extra` field; canonical Steward vocabulary: `New` / `To Read` / `In Progress` /
`Read` / `Not Reading`) tells you which depth is natural:

- `To Read` → **glance**
- `In Progress` → **close** (then **deep** once the close read is done)
- `Read` → **situate**

After writing a stage you **may suggest** bumping the status (e.g. "I did a close
read — consider moving this from *To Read* to *In Progress*"). The Zotero MCP is
**read-only**: do not write the status back yourself. Status writebacks stay with
the user or the sync layer.

## Output — reading-note/1.0 (one file per paper, keyed by citekey)

Write or update **one reading-note per paper**, named by its citekey. Default
location: a **`reading-notes/` directory in the working vault** (sibling to the
`Literature/` notes Steward exports and the `Reviews/` notes — e.g.
`<vault>/reading-notes/<citekey>.json`). If the user names a different path, use
it; otherwise use `reading-notes/<citekey>.json` and state the path you wrote.

**Update, never clobber:** if the file already exists, read it, fill only the
requested stage(s), and preserve every other field. The same paper accumulates
its stages across separate `read-paper` invocations.

### Contract

```json
{
  "schema_version": "reading-note/1.0",
  "id": "betterBibtexCitekey",
  "zotero_key": "ABCD1234",
  "doi": "10.xxxx/yyyy",
  "read_status": "In Progress",
  "created": "2026-06-22T00:00:00Z",
  "generated_by": "read-paper skill (agent: <Claude Code | Codex>)",
  "stages": {
    "glance":     { "tldr": "", "tags": [], "key_findings": [] },
    "close_read": { "question": "", "method": "", "data": "", "results": "", "figures": [] },
    "deep_read":  { "critique": "", "reproducibility": "", "limits": "", "relation_to_my_work": "" },
    "situate":    { "direction": "", "lineage_refs": [] }
  },
  "sources": {
    "annotations": "link/path to the PDF++ or Zotero annotations used",
    "parsed_file": "link/path to the parsed structured file, if any"
  }
}
```

- Include `stages` keys **only** for the depth(s) you filled this run; leave
  existing stages from earlier runs untouched.
- `id` is the **Better BibTeX citekey** — the universal cross-system join and the
  filename stem. `read_status` mirrors the Zotero Read-Status at read time.
- `lineage_refs` are other papers' **citekeys** (the situate edges); keep them to
  references you can actually verify in the library.

### Then render the browsable note (`steward read-render`)

After writing/updating `reading-notes/<citekey>.json`, ALSO produce the **browsable
Obsidian note** so the read persists as a per-paper long-term archive you can open
and link to:

```sh
steward read-render reading-notes/<citekey>.json --vault <vault> [--kb <library-kb.json>]
```

- The **`.json` is the machine source of truth**; the **`.md` is the canonical
  browsable Obsidian note** — YAML frontmatter (Obsidian properties), one bilingual
  `## ` section **per filled stage** (速览·Glance / 精读·Close read / 深读·Deep read /
  串联定位·Situate — absent stages are skipped), the situate `lineage_refs` as
  `[[citekey]]` wikilinks, a dedicated **`## 标注 · Annotations`** section (highlight
  TEXT inlines as a blockquote; a URI/path reference renders as a link), and a links
  block to the library note + your sources. A `figures[]` **image path** inlines as an
  Obsidian embed `![[path]]` (else the caption renders as text). The `[[citekey]]`
  library link resolves because `steward export` now writes a citekey alias onto each
  Literature note (from the `Citation Key:` extra-field line).
- It is a **deterministic projection** and is **re-rendered idempotently**: run it
  again after each depth you fill, and it overwrites `<vault>/reading-notes/<citekey>.md`
  to reflect the accumulated stages. It changes **nothing** in the `.json` contract or
  the four-depth behavior.
- Pass **`--kb <library-kb.json>`** to enrich the frontmatter with title/authors/year
  (matched on the citekey); without it the note renders only what the reading-note
  carries (reading-note has no bibliographic fields — those live in `library-kb/1.x`).

### And refresh the reading overview (`steward read-index`)

To see every paper you have a reading-note for at a glance, build the status dashboard:

```sh
steward read-index --vault <vault>     # -> <vault>/reading-notes/_index.md
```

It scans `reading-notes/*.json` and emits one overview note — status-grouped sections
(To Read / In Progress / Read / …), a full table (citekey · title · year · status ·
stages · tags), and a Dataview block — idempotently overwriting `_index.md` only. Run
it after a read session to keep the overview current; it reads only, the per-paper
`.json` files stay the source of truth.

## Anti-fabrication (hard rule — same guarantee as Steward `review assemble`)

Figures, data, numeric results, quotes, and citations must come from the
**parsed-paper file**, the **MCP-read full text**, the **`library-kb`**, or the
user's **annotations** — **never invented**.

- If neither a parsed-paper file nor the live full text (via the Zotero MCP) is
  reachable, **say so** and do the most you can from `library-kb` + annotations;
  do not guess at method/results.
- Do not state specific numbers, figure contents, or quotes you did not read.
- For `situate`, every `lineage_refs` citekey must be a real library entry; drop
  edges you can't verify rather than fabricating a lineage.
- For `deep`, do not invent a relation to the user's work — if Provenance context
  is missing, note the gap.

## Local + read-only

- The **Zotero MCP is read-only and local** (local Zotero API, no key; semantic
  search local-only or off — never cloud). You read metadata / full-text /
  annotations / notes through it; you **never** write to Zotero.
- The **parsed-paper file is local too** (`steward parse` runs GROBID on the
  user's own machine — Docker on localhost:8070, no cloud egress). Preferring it
  for `close`/`deep` is both faster and keeps the read fully local.
- All reasoning + prose happens **in this session**. Suite-owned code opens no
  model connection and adds no hidden generation call. The selected Codex or
  Claude Code host owns any configured model/network egress; do not describe a
  cloud-backed host session as fully local. The only suite-local model in the
  planned stack is the optional embedding model used for retrieval — not for
  generation.
- This skill writes the local `reading-note/1.0` contract and its Markdown
  projection. Direct Provenance ingestion of reading notes is not implemented;
  do not claim that the file was automatically archived or indexed there.
- **Writebacks** (Read-Status changes, Zotero edits) stay with the **user or the
  sync layer**, not this skill.

## Guardrails

- **The JSON is the source of truth:** the paper's `reading-notes/<citekey>.json`.
  Fill only the requested stage(s); preserve all others. The browsable
  `reading-notes/<citekey>.md` is a derived projection rendered by
  `steward read-render` (idempotent overwrite); never hand-edit it — re-render it.
- **Language:** note content matches the library's working language (Chinese by
  default here); the JSON keys stay exactly as in the contract.
- **No additional connector/network calls beyond the local Zotero MCP and
  prov-mcp.** The selected agent host may use its configured model endpoint;
  that host-managed egress must follow the user's host policy. The skill adds no
  telemetry and performs no writes to Zotero.
