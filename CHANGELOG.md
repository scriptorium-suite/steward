# Changelog

## 0.2.0 — 2026-07-20

- Moved the three audited product Skills from the agent-host-specific `.claude/skills/` path to the neutral `skills/` directory; public release candidates no longer carry `.claude/` governance state.
- Replaced potentially identifying bibliographic and research-domain fixtures with explicitly labelled `[SYNTHETIC] XQ-17` data.
- `steward export` now emits `library-kb/1.1`, the additive minor that
  identifies the stable `citekey` field already written by Steward.
- First-party KB readers accept both `library-kb/1.0` and `library-kb/1.1`;
  legacy top-level item arrays remain compatible.
- `steward status` reports only whether the API key is set; it no longer prints
  any key prefix.

## 0.1.1 — 2026-06-22

Agent-native cleanup: the literature loop is now on-demand and interactive rather
than scheduled and headless.

- **Removed the `harden/` weekly literature automation.** The Task Scheduler wiring
  (`lit-env.ps1` / `lit-run.ps1` / `register-lit-task.ps1` / `unregister-lit-task.ps1`
  / `logs/`) is gone; literature is refreshed **on demand** (`steward review
  scaffold --since-days N --unread` → assemble), run when you want to archive new
  arrivals.
- **Retired the headless `review fill` driver.** `src/steward/review_fill.py` (and
  its `review fill` subcommand) drove the `review-fill` skill through a `claude -p`
  subprocess to write `review.draft.json` unattended. The draft is now filled
  **interactively by an agent in-session** via the `skills/review-fill`
  skill (kept). `review scaffold` and `review assemble` are unchanged; the package
  still never wires an LLM API. The `STEWARD_REVIEW_*` env knobs and the `claude`
  binary lookup that only served the headless driver are gone.

## 0.1.0 — 2026-06-22

First tagged release: a Zotero **governance** CLI with a stdlib-only core — backup →
audit → propose → review → apply → rollback, AI tagging, KB + Obsidian export, a
project-portfolio dashboard, topic literature reviews with on-demand refresh, and
multi-paper handoff packages for Lectern. Write operations are dry-run-first,
backup-gated, journaled, and reversible. (The M0–M3 / Phase D / handoff-1.1 / R16
work below is folded into this first release; the experiment-log layer that M3 once
shipped was dropped before release — see scriptorium-spec v2.0.0.)

### R16 ③: on-demand literature + optional weekly automation

- `steward review scaffold` gains a **what's-new selection mode** for the R13
  「库内新进展」digest: `--since YYYY-MM-DD` / `--since-days N` (recent additions,
  UTC-aligned to Zotero `dateAdded`) and `--unread` (readStatus != "Read"),
  composable with the existing `--topic` (all filters AND; the CLI requires ≥1; an
  invalid `--since` exits 2). A topic-less digest is labelled `库内新进展`.
  Anti-fabrication is unchanged — `assemble` builds the reference table/DOIs from
  the KB, never the draft. An empty selection is a clean no-op (no file written);
  `--out` defaults to a dated `review.input-<date>.json`.
- `steward review fill` — a **headless fill driver** (`review_fill.py`) that runs
  the `review-fill` skill via the user's `claude` CLI to produce
  `review.draft.json` unattended (dry-run by default; `--run` executes). The
  package never wires an LLM API; the single LLM-touching step sits behind an
  injectable `fill_fn` seam, so it is deterministic to test. A malformed draft is
  moved to `review.draft.rejected.json` (retryable); a non-zero `claude` exit
  surfaces its stderr + code, and a missing `claude` binary is reported clearly.
- Literature refresh is **on-demand by default** (`steward review --since-days N`,
  run when you want to archive new arrivals). An **optional** `harden/` weekly
  scheduled-task set (`lit-env.ps1` / `lit-run.ps1` / `register-lit-task.ps1` /
  `unregister-lit-task.ps1`) automates `export → prov-ingest-library → digest`
  for those who want it: idempotent registration, clean rollback, read-only Zotero
  key. The runner invokes `conda run -n $CondaEnv python -m …` (a `$CondaEnv`
  placeholder in `lit-env.ps1`, set to your provenance-bearing env);
  `register-lit-task.ps1` smoke-checks `import provenance.ingest.library` and
  aborts if it fails. Each run `Start-Transcript`s to `harden/logs/`; a non-zero
  stage drops a `LAST-RUN-FAILED.txt` sentinel + a desktop toast. Script-level
  UTF-8; the README documents the interactive-logon constraint
  (`-StartWhenAvailable` catch-up) and `-Force` name+path idempotency.

### handoff/1.1: multi-paper pick

- `steward pick` accepts multiple keys/title-substrings. One source still produces
  a single-paper `handoff/1.0` (unchanged); two or more produce a multi-paper
  `handoff/1.1` — top-level `key`/`title` describe the report, `papers[]` lists the
  sources, and `report_type` (`--report-type` literature|experiment, default
  literature) tags the kind. The report key is derived deterministically from the
  member keys; each PDF is staged as `p<i>_<name>` so filenames never collide.
  `--report-title` overrides the auto-generated title. Backward-compatible: the
  single-paper output is byte-for-byte the same as before.
- produces `handoff/1.1` (additive over 1.0): single-paper pick still emits the
  `handoff/1.0` subset, multi-paper emits `handoff/1.1`; consumers reading 1.0 are
  unaffected.

### Phase D: literature review

- `steward review scaffold` / `review assemble` — scaffold→fill→assemble for topic
  literature reviews, vault-side and zero-credential (Steward never calls an LLM
  itself). `scaffold` filters a `library-kb/1.0` KB by a collection-path prefix
  (exact boundary: `01_ML` never captures `01_MLX`) into `review.input.json` + a
  REVIEW-PROMPT.md; an LLM/agent/human drafts `review.draft.json` (steward-local
  `review-draft/1.0`: framing/intro/sections/gaps_future/priority_reads).
  `assemble` validates the draft (fabricated paper keys are rejected; a malformed
  draft now raises before render) and writes `Reviews/<name>.md`: an AI-draft
  banner (N papers, only M read — a reading roadmap, not a close-reading summary) +
  intro + themed sections (each with a "涉及: Author Year" line) + research gaps +
  ⭐ priority reads + an AUTHORITATIVE reference table built FROM THE KB
  (keys/authors/years/DOIs/read-status — never the draft, so citations and DOIs
  can't be fabricated) + a coverage note. Refuses to overwrite an existing note
  without `--force`.
- now consumes `library-kb/1.0` and `review-draft/1.0`.

### M3: project-portfolio dashboard

Lifts project-portfolio management from manual to automatic (scriptorium-spec
`project/1.0`):

- `steward portfolio` — refreshes the 总纲 dashboard: scans `Projects/*.md`
  (`project/1.0` frontmatter, `_`-prefixed files skipped), optionally joins each
  `linked_repo`'s git branch/commit/date (`--git`), and rewrites only the
  marker-delimited static-snapshot block in `Projects/_总纲.md` — Dataview blocks
  and any other content outside the markers are preserved. Dry-run by default; the
  snapshot is deterministic so a re-run is a no-op unless the projects (or their
  repos) actually changed. Pointed at an existing dashboard with no markers it
  refuses (rather than appending a duplicate snapshot): paste the two marker lines
  where the block should live, or pass `--init` to append a fresh one.
- `yamlmini` — a tiny stdlib-only YAML *subset* reader (block maps/sequences,
  scalars, inline flow, multi-line plain scalars) so both commands can consume real
  `safe_dump` output and Obsidian frontmatter with zero dependencies.
- now consumes `project/1.0`.

### M2: feature complete

- `steward tag scaffold` / `tag apply` — proposal-file workflow for AI tags +
  one-line TLDR + reading status; scaffold emits items + controlled vocabulary +
  TAG-PROMPT.md (zero credentials, `--db` works on backups, `--all` to re-tag),
  apply writes `ai:`-prefixed automatic tags and one `TLDR:`/`Read_Status:`/
  `Read_Status_Date:` line into `extra` (preserving other extra content, stripping
  legacy status tags), journaled and conflict-safe.
- `steward export` — KB JSON (library-kb/1.0) + Obsidian vault (`Literature/`
  notes with frontmatter/TLDR/zotero:// link/PDF path + `文献库 MOC.md`);
  `Literature/` and the MOC are fully regenerated, other vault folders are left
  untouched; warns when the storage dir is unset or all PDFs are missing.
- `steward pick` — stage a paper's largest local PDF + handoff/1.0 meta.json for
  Lectern.
- generalized rollback: a journal restores exactly the fields it captured
  (collections, or tags+extra).
- config loader tolerates a UTF-8 BOM (Windows editors / PowerShell `Out-File`).

### M1: governance core

- `steward propose` — scaffold a `proposal/1.0` file from a read-only library
  snapshot (`--db` works on backups; zero credentials), with per-item metadata
  context and a PROPOSAL-PROMPT.md so any LLM/agent/human can fill targets.
- `steward apply` — schema + target-tree + server-existence validation, per-folder
  plan summary, dry-run by default; `--run` enforces a verified backup
  (fail-closed: an unreadable/missing backup timestamp blocks the write unless
  `--no-backup-check`), creates missing collections parents-first, journals every
  item's pre-state before the first write, applies with per-object versions and one
  412 retry round.
- `steward rollback` — `--list` journals; replay one to restore collections.

### M0: read-only foundation

- `steward setup` — interactive config wizard; profiles in
  `~/.config/scriptorium/steward/config.toml`; env vars
  (`ZOTERO_API_KEY`/`ZOTERO_LIBRARY_ID`/`ZOTERO_LIBRARY_TYPE`/`ZOTERO_LOCAL`)
  override the file.
- `steward backup` — full data-directory snapshot with byte verification,
  `PRAGMA integrity_check`, restore manifest; refuses to run over journal/WAL
  residue (Zotero still running) unless `--force`.
- `steward audit` — read-only health report from a temp copy of zotero.sqlite:
  counts by type, collection tree, tag hygiene (manual/automatic/singletons),
  reading-status histogram (zotero-reading-list convention), PDF coverage,
  duplicate-DOI groups. Zero credentials required.
- `steward status` — config/paths/schemas/last-backup overview.
- Zotero API client (stdlib urllib): web + local modes, per-object version writes,
  429/Backoff handling, 50-object batching (write plumbing for M1).
- Implements scriptorium-spec: produces `library-kb/1.0`, `handoff/1.0` (from M2);
  consumes `proposal/1.0` (from M1).
