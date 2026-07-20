English | [中文](README.zh.md)

# Steward

> Safe, auditable, reversible governance for the Zotero library you already have.

## Related

[README](README.md) · [中文 README.zh](README.zh.md) · [Skills](skills/) · [CHANGELOG](CHANGELOG.md)

**Suite / 套件:** [scriptorium-spec](https://github.com/scriptorium-suite/scriptorium-spec) (contract SSoT) · [steward](https://github.com/scriptorium-suite/steward) · [Provenance](https://github.com/foxsplendid/Provenance) · [Academic-Slides-Agent / Lectern](https://github.com/foxsplendid/Academic-Slides-Agent) · [.github](https://github.com/scriptorium-suite/.github)
> Contract facts are canonical in **scriptorium-spec/README**; other repos mirror, never fork them.

## Overview

Steward is a command-line tool for **governing a Zotero reference library** — not chatting with it. Where most Zotero AI tools talk to your papers, Steward operates on the library itself: it backs up first, audits read-only, expresses every change as an **offline, human-reviewable proposal file**, applies changes only after review, and keeps a rollback baseline for everything it writes. It is part of the [Scriptorium suite](https://github.com/scriptorium-suite) and is built for researchers who want AI- or agent-assisted library maintenance without surrendering control of their data.

The core is pure Python standard library — **zero runtime dependencies**. Every write phase is dry-run-first, backup-gated, journaled, and reversible.

## Features

- **Backup with verification** — full data-directory snapshot, byte-count check, SQLite `PRAGMA integrity_check`, and a restore manifest; refuses to run over journal/WAL residue (Zotero still open) unless forced.
- **Read-only audit** — library health report (item counts by type, collection tree, tag hygiene, reading-status histogram, PDF coverage, duplicate-DOI groups) needing **zero credentials**.
- **Proposal workflow** — scaffold a `proposal/1.0` file (items + metadata + your target collection tree) plus filling instructions; an LLM, an agent, *or you in a text editor* fills the targets, then `apply` validates and writes.
- **Conflict-safe apply** — dry-run by default; `--run` requires a recent verified backup, journals pre-state before writing, and reassigns collections with per-object version checks so concurrent edits abort (HTTP 412) rather than being clobbered.
- **AI tagging** — scaffold/fill/apply `ai:`-prefixed tags, a one-line TLDR, and reading status into the `extra` field, journaled.
- **Export** — write KB JSON (`library-kb/1.1`) and a re-runnable Obsidian vault (`Literature/` notes + MOC).
- **Pick** — stage paper PDF(s) plus handoff metadata for downstream slide generation (Lectern): one paper → `handoff/1.0`, two or more → a multi-paper `handoff/1.1` report (`papers[]` + `report_type`).
- **Parse** — PDF → `parsed-paper/1.0` (structured `sections[]` + `references[]` + `metadata`) via a **local** parser. The default back-end is **GROBID** (a Java service you run on `localhost:8070`); the parser is pluggable (`--parser`) so heavier optional back-ends (Docling/MinerU) can slot in later. Fully local — no cloud egress; this is the local parse layer that, once Lectern adopts it, removes Lectern's cloud-MinerU upload.
- **Lineage** — a SET of parsed papers → `lineage-graph/1.0`, the **own-library citation graph** for a research direction. Deterministic and stdlib-only: each paper's parsed `references` are matched against the other papers in the set (by DOI, else normalized title) to emit `cites` edges (evidence = the matched reference text), plus year-ordered `nodes` and a `timeline`. Within-set only — a reference to a paper outside the set produces no edge. The agent enriches the typed relations (extends / supersedes / method-of / contrasts) and clusters later during synthesis; `lineage` just builds the citation skeleton.
- **Literature review** — scaffold a topic's papers from a KB by collection-path prefix (or a what's-new digest with `--since` / `--since-days` / `--unread`, labelled 库内新进展), have an LLM/agent/human draft the prose (interactively in-session via the `review-fill` skill, or by hand), then assemble a vault note whose **reference table is built authoritatively from the KB** (keys/authors/years/DOIs/read-status), so citations cannot be fabricated.
- **Portfolio** — refresh a portfolio dashboard (总纲) from `Projects/*.md`, optionally joining each `linked_repo`'s git state; rewrites only its marker-delimited snapshot block, leaving Dataview blocks and hand-authored content untouched.
- **Rollback** — replay any journal (apply or tag) to restore collections/tags/extra; dry-run by default, library-matched, and itself journaled.
- **Multi-profile config** — interactive `setup` wizard; env vars (`ZOTERO_API_KEY` / `ZOTERO_LIBRARY_ID` / `ZOTERO_LIBRARY_TYPE` / `ZOTERO_LOCAL`) override the config file.

## Installation

Requires **Python ≥ 3.11** and **uv 0.11.16**. The package (`scriptorium-steward`) is not yet published to PyPI, so run it from a locked source environment:

```sh
git clone https://github.com/scriptorium-suite/steward
cd steward
uv sync --locked
uv run --locked steward --version
```

For development (adds pytest):

```sh
uv sync --locked --extra dev
uv run --locked --extra dev pytest
```

`audit` and `backup` need **no API key** — they read your local Zotero data directory. Write commands (`apply`, `tag apply`, `rollback`) need a Zotero Web API key plus library ID, supplied via `steward setup` or the `ZOTERO_*` environment variables.

## Usage

Get started:

```sh
steward setup      # interactive config wizard (profiles)
steward backup     # verified snapshot of the Zotero data dir
steward audit      # read-only health report (no credentials)
steward status     # config, paths, schemas, last backup
```

The **literature loop** (Zotero-side):

```sh
steward backup
steward propose --tree targets.txt --out proposal.json   # scaffold (zero credentials)
# fill proposal.json's targets with an LLM / agent / editor, review, then:
steward apply proposal.json            # dry-run plan
steward apply proposal.json --run      # execute (backup-gated, journaled)
steward tag scaffold --vocab vocab.txt # AI tags + TLDR + read status
steward tag apply tag-plan.json --run
steward export --vault /path/to/vault  # KB JSON + Obsidian Literature/ notes
steward pick "title or key" --kb kb/library.json   # stage PDF + handoff/1.0
steward pick KEY1 KEY2 --kb kb/library.json        # multi-paper handoff/1.1 report
steward parse paper.pdf                            # PDF -> parsed-paper/1.0 (local GROBID)
steward parse CITEKEY --kb kb/library.json         # resolve a citekey/key/title to its PDF, then parse
steward lineage --papers parsed/ --query "your direction"   # parsed papers -> lineage-graph/1.0 (own-library citation graph)
steward lineage-render --graph lineage.json --vault VAULT   # lineage-graph/1.0 -> Reviews/<slug>.lineage.md (Mermaid + timeline + edge table)
steward read-render reading-notes/CITEKEY.json --vault VAULT --kb kb/library.json   # reading-note/1.0 -> reading-notes/<id>.md (browsable Obsidian note)
steward read-index --vault VAULT --kb kb/library.json   # reading-notes/*.json -> reading-notes/_index.md (status dashboard; --kb fills titles/years)
steward rollback --list                # list journals; replay one anytime
```

The **vault loop** (no Zotero credentials):

```sh
steward review scaffold --topic 01_ML --kb kb/library.json   # collect topic papers
steward review scaffold --since-days 7 --unread --kb kb/library.json   # what's-new digest (库内新进展)
# draft review.draft.json interactively in-session via the review-fill skill, or by hand per REVIEW-PROMPT.md:
steward review assemble --input review.input.json --draft review.draft.json --out Reviews/ml.md
steward portfolio --vault /vault --git --run   # refresh the 总纲 dashboard
```

Run `steward --help` or `steward <command> --help` for full options. Every write phase prints a dry-run plan first and only writes with `--run`.

## Literature reading (P1) setup

Steward governs the library; the **`read-paper`** skill (in `skills/`,
beside `review-fill`) reads any paper at four escalating, on-demand depths —
`glance` / `close` / `deep` / `situate` — and writes a per-paper
`reading-note/1.0` keyed by the Better BibTeX citekey. The agent (Claude Code /
Codex) does all the reading and prose **in-session**; no LLM is wired into the
suite. To use it, adopt these four plugins. Everything stays **local-first and
read-only** — Steward and the skill never write to Zotero.

- **zotero-mcp** — the agent's read window into the library. Register it as an
  **MCP server** pointed at your **local Zotero API** (read-only, **no API
  key**). Force semantic search to **local embeddings or turn it off — never
  cloud**. This is how `read-paper` reads full text / annotations / notes for the
  `close` and `deep` depths.
- **PDF++** (Obsidian) — read PDFs in-vault and keep annotations as **in-vault
  markdown** (file-contract-clean — they survive the plugin). `read-paper` folds
  these annotations into the close/deep stages.
- **zotero-reading-list** (already in use) — the **depth driver**: the Zotero
  Read-Status (`New` / `To Read` / `In Progress` / `Read` / `Not Reading`, in the
  Zotero `Extra` field) maps to a depth — `To Read`→glance, `In Progress`→close,
  `Read`→situate. `read-paper` may *suggest* bumping the status; writebacks stay
  with you / the sync layer.
- **Better BibTeX** — the **stable citekey** is the `reading-note` id and filename
  stem (the universal cross-system join). Keep citekey generation stable so notes
  stay keyed across re-reads.

Reading notes land in a **`reading-notes/`** directory in the vault (sibling to
the exported `Literature/` and `Reviews/` notes). The skill enforces the same
**anti-fabrication** guarantee as `review assemble`: figures / data / quotes /
citations come from the MCP-read full text, `library-kb`, or your annotations —
never invented; if a source is unavailable the skill says so rather than guessing.

> Design reference: scriptorium-spec `specs/literature-reading.md` §4–5
> (`reading-note/1.0` is a ratified contract — `schemas/reading-note/v1.json`, spec v2.1.0).

### Local parse layer — `steward parse` + GROBID

`steward parse` turns a paper PDF into a `parsed-paper/1.0` file — structured
`sections[]`, `references[]`, and `metadata` (title/authors/year/doi/abstract) —
that the `read-paper` skill prefers over a live full-text read for the `close` and
`deep` depths (structured, cached, and fully local). The default parser is
**GROBID**, a **local** Java service:

```sh
# run GROBID locally (fully on your machine; no cloud egress)
docker run --rm --init -p 8070:8070 grobid/grobid:0.8.0

steward parse paper.pdf                            # -> parsed/<stem>.json
steward parse CITEKEY --kb kb/library.json         # resolve the PDF from the library-kb, then parse
steward parse paper.pdf --grobid-url http://localhost:8070 --out parsed/x.json
```

The GROBID base URL resolves **CLI flag (`--grobid-url`) > `STEWARD_GROBID_URL`
env > default `http://localhost:8070`**. If GROBID isn't running, `parse` prints
a clear, actionable error (how to start the Docker service) instead of crashing.
The parser is **pluggable** (`--parser`, default `grobid`): the stdlib-clean
GROBID path needs no extra dependency, and heavier optional back-ends
(Docling/MinerU) can register later without touching the core. Because the parse
is local, once **Lectern** adopts this same layer it removes Lectern's current
cloud-MinerU PDF-upload egress (a net trust improvement, per
scriptorium-spec `specs/trust-model.md`).

### Lineage — `steward lineage` (own-library citation graph)

`steward lineage` builds the **citation-graph half** of direction synthesis: give
it a set of `parsed-paper/1.0` files (from `steward parse`) and it emits a
`lineage-graph/1.0` — the 脉络 of how those papers cite one another.

```sh
steward lineage --papers parsed/                          # a directory of parsed files
steward lineage --papers parsed/a.json parsed/b.json      # an explicit list
steward lineage --papers parsed/ --query "[SYNTHETIC] XQ-17 calibration lineage" --out lineage.json
```

It is **deterministic and fully local** (no LLM, stdlib only): for each paper it
walks the parsed `references` and adds a `cites` edge wherever a reference matches
**another paper in the same set** — by DOI first, else by normalized title — with
the matched reference's raw text recorded as the edge `evidence` (anti-fabrication:
edges are read off real reference data, never invented). A reference to a paper
**outside** the set produces no edge (own-library only). Nodes carry
citekey/title/year and `timeline` lists them in year order.

The **typed relations** (`extends` / `supersedes` / `method-of` / `contrasts`) and
cluster assignments are deliberately left to the **agent**, which enriches the
graph during synthesis (the `synthesize-direction` skill) with the reasoning the
suite never wires an LLM for. `lineage` just lays down the deterministic `cites`
skeleton the agent reasons over.

### Lineage render — `steward lineage-render` (graph → a self-contained note)

`steward lineage-render` is the **deterministic projection** of an (agent-enriched)
`lineage-graph/1.0` into a single, self-contained Markdown note. The JSON stays the
machine source of truth; the note is a regenerable view.

```sh
steward lineage-render --graph lineage.json --vault <vault>     # -> <vault>/Reviews/<slug>.lineage.md
steward lineage-render --graph lineage.json --out path.md       # explicit output path
steward lineage-render --graph lineage.json --vault <vault> --stamp-notes
```

The note carries a **native Mermaid flowchart** (one relation-labeled edge per graph
edge, cluster subgraphs when present) that renders in **vanilla Obsidian with no
plugin**, a chronological **timeline**, and a plain **edge table** (from | relation |
to | evidence — Dataview-friendly, but renders as a table without it). Output lands in
`Reviews/` (the tool-owned derived view per scriptorium-spec `specs/vault-layout.md`);
overwriting its own derived note is idempotent. The render is **self-contained** — it
does not depend on per-paper notes existing (lean-vault).

`--stamp-notes` is **opt-in** (default off): it ALSO stamps Breadcrumbs-compatible
frontmatter (the relationship-field convention's `cites` / `extends` / `supersedes` /
`method-of` / `contrasts` keys) onto per-paper notes — but **only where the note
already exists** under `Literature/` or `reading-notes/`. It **merges, never
clobbers**, never creates a paper note, and never touches human-input zones; absent
notes are skipped silently (they live in Provenance, lean-vault).

### Read render — `steward read-render` (reading-note → a browsable Obsidian note)

`steward read-render` turns a `reading-note/1.0` (the per-paper staged notes the
`read-paper` skill writes) into **one self-contained, browsable Obsidian note** — the
per-paper long-term archive. The JSON stays the machine source of truth; the `.md` is
the canonical browsable view, re-rendered idempotently.

```sh
steward read-render reading-notes/CITEKEY.json --vault <vault>                 # -> <vault>/reading-notes/<id>.md
steward read-render reading-notes/CITEKEY.json --vault <vault> --kb kb/library.json   # enrich frontmatter with title/authors/year
steward read-render reading-notes/CITEKEY.json --out path.md                   # explicit output path
```

The note carries **YAML frontmatter** (Obsidian properties — citekey, read_status,
doi, created, glance tags), a bilingual `## ` section **per filled stage only**
(速览·Glance / 精读·Close read / 深读·Deep read / 串联定位·Situate — absent stages are
skipped), the situate `lineage_refs` rendered as `[[citekey]]` **wikilinks**, a
dedicated **`## 标注 · Annotations`** section, a links block to the library note +
parsed-file / Zotero sources, and a footer naming the JSON SSoT. Because
`reading-note/1.0` carries no title/authors/year (those live in `library-kb/1.x`),
pass **`--kb`** to enrich the frontmatter by matching the note's citekey in the KB;
without it the note renders only what it carries. Output defaults to `--out`, else
`<vault>/reading-notes/<id>.md` with `--vault`, else `<json-dir>/<id>.md`; overwriting
the derived `.md` is **idempotent**.

Two render-support niceties:

- **Annotations inline.** When `sources.annotations` is non-empty it gets its own
  `## 标注 · Annotations` section. An entry that looks like a URI/path (a `scheme:`
  prefix, or a `/`/`#` with no spaces) renders as a link/`code` reference; a plain-text
  entry renders as a `> blockquote` so the **highlight text shows inline** (record
  meaningful highlight text into `sources.annotations`, not just a reference, to use it).
- **Figure embeds.** A `close_read.figures[]` entry that looks like an **image path**
  (ends `.png`/`.jpg`/`.jpeg`/`.gif`/`.webp`, optionally with a leading path) renders as
  an Obsidian embed `![[path]]`; a caption string still renders as a `- caption` bullet.
  This is **render-support only** — actual figure images require a layout parser that
  emits image files (local **MinerU**); **GROBID / `parsed-paper` carry caption text
  only**, so embeds light up only when an image-producing parse populated figure paths.
  Steward does not fake extraction.

The reading-note links its library note as `[[citekey]]`. For that wikilink to resolve,
`steward export` now writes a Better BibTeX **citekey** onto each `Literature/` note —
it parses the `Citation Key:` line from the Zotero item's `extra` field into the
`library-kb/1.1` item's optional `citekey`, and when present stamps `aliases:
["<citekey>"]` + a `citekey:` property into the note's frontmatter. So an Obsidian
`[[citekey]]` (from a reading-note, lineage edge, or by hand) resolves to the library
note suite-wide. Items without a `Citation Key:` line are unaffected (empty citekey, no
alias).

### Read index — `steward read-index` (reading-notes → a status dashboard)

`steward read-index` scans `<vault>/reading-notes/*.json` (the reading-note/1.0 SSoT
files) and emits a single overview note, `<vault>/reading-notes/_index.md` — the
reading status dashboard, so you can see every paper you have a reading-note for at a
glance.

```sh
steward read-index --vault <vault>                 # -> <vault>/reading-notes/_index.md
steward read-index --vault <vault> --out path.md   # explicit output path
```

It carries four views of the same set, so it is useful **with or without a plugin**:
**status-grouped sections** (`## To Read` / `## In Progress` / `## Read` / `## Not
Reading` / `## (no status)`), each a `- [[citekey]] — title year (glance·close)`
wikilink list with the filled stages; a **full static table** (citekey | title | year |
status | stages | tags); and a fenced **Dataview block** for plugin users (the static
views still render for everyone else). Ordering is deterministic (status lifecycle then
citekey); a non-reading-note JSON in the dir is skipped with a warning; an empty/absent
`reading-notes/` prints a clear message (no crash, no file written). It overwrites only
`_index.md` (idempotent); the `.json` files stay the machine source of truth.

## Project Structure

```
steward/
├── pyproject.toml          # build metadata, console script, dev extras (stdlib-only core)
├── CHANGELOG.md            # milestone history (M0–M3 + Phase D review)
├── LICENSE                 # Apache-2.0
├── src/steward/
│   ├── cli.py              # argparse entry point; all subcommands (main = console script)
│   ├── config.py           # ~/.config/scriptorium/steward/config.toml profiles; env overrides
│   ├── zotero_api.py        # stdlib urllib client (web + local read-only modes)
│   ├── backup.py           # verified data-dir snapshots + restore manifest
│   ├── audit.py            # read-only health report
│   ├── proposal.py         # proposal/1.0 scaffold + summarize
│   ├── apply.py            # plan/execute/rollback with journals + version checks
│   ├── tagging.py          # tag-plan/1.0 scaffold/validate/execute
│   ├── export.py           # library-kb/1.1 JSON + Obsidian vault writer
│   ├── pick.py             # stage PDF(s) + handoff/1.0 or 1.1 meta
│   ├── parse.py            # PDF -> parsed-paper/1.0 (local GROBID; pluggable parser seam)
│   ├── lineage.py          # parsed papers -> lineage-graph/1.0 (own-library citation graph)
│   ├── lineage_render.py   # lineage-graph/1.0 -> self-contained Reviews/ note (Mermaid + timeline + edge table)
│   ├── read_render.py      # reading-note/1.0 -> browsable Obsidian note (frontmatter + per-stage sections + wikilinks + annotations)
│   ├── read_index.py       # reading-notes/*.json -> reading-notes/_index.md (status dashboard: grouped sections + table + Dataview)
│   ├── portfolio.py        # project/1.0 -> 总纲 dashboard snapshot
│   ├── review.py           # review scaffold/assemble (review-draft/1.0)
│   └── yamlmini.py         # tiny stdlib-only YAML-subset reader
├── skills/                 # three portable, host-neutral agent Skills
└── tests/                  # pytest suite (one module per command)
```

## Status

Active, **v0.2.0**, Development Status: 3 - Alpha. Feature-complete through milestone M3, the Phase D literature-review layer, and on-demand literature refresh (per `CHANGELOG.md`); not yet published to PyPI.

Exchange formats implemented (per [scriptorium-spec](https://github.com/scriptorium-suite/scriptorium-spec)):
- **Produces:** `library-kb/1.1`, `handoff/1.1` (single-paper `1.0` subset), `proposal/1.0`, `parsed-paper/1.0`, `lineage-graph/1.0`
- **Consumes:** `proposal/1.0`, `tag-plan/1.0`, `project/1.0`, `library-kb/1.0` and `library-kb/1.1`, `review-draft/1.0`

## Safety contract

1. Backup before any write phase; backups are verified (byte counts + `PRAGMA integrity_check`) and carry a restore manifest.
2. Writes only ever touch `collections`, `tags`, and `extra` — never deletions.
3. Every write goes through the Zotero Web API v3 with per-object version concurrency (412 conflicts surface instead of clobbering).
4. Machine tags carry the `ai:` prefix; one-line summaries and read status live in the `extra` field following documented conventions.
5. Downstream tools consume exported files (`library-kb/1.0` or `library-kb/1.1`), never your live library.

## Public fixture policy

The three reusable Skills live in the host-neutral `skills/` directory: `read-paper`, `review-fill`, and `synthesize-direction`. They do not depend on a private agent-host configuration directory.

Potentially identifying paper identities, authors, DOIs, titles, measurements, and research-domain fixtures have been replaced with explicitly labelled **`[SYNTHETIC] XQ-17` data**. Remaining short values are structural placeholders; none come from a real Zotero library, research project, or personal record.

## License

Apache-2.0 (see [LICENSE](LICENSE)).
