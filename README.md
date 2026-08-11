# Steward

[![CI](https://github.com/scriptorium-suite/steward/actions/workflows/ci.yml/badge.svg)](https://github.com/scriptorium-suite/steward/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/scriptorium-suite/steward)](https://github.com/scriptorium-suite/steward/releases)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Steward is the literature and reference-library component of the Scriptorium suite. It helps turn a local or Zotero-backed library into reviewable reading notes, structured proposals, citation lineage, and downstream handoff files.

![Steward literature workflow](docs/assets/steward-flow.svg)

## What it is for

Research work often starts with a vague idea and a pile of papers. Steward is designed for the part of the workflow where sources need to be selected, parsed, reviewed, compared, and turned into structured material that another tool or agent can continue from.

Steward can be used independently as a reference-library governance tool. Inside Scriptorium, it acts as the literature and source-preparation component.

## Core capabilities

| Capability | Description |
| --- | --- |
| Backup and audit | Inspect and protect a reference library before making changes. |
| Pick and propose | Select candidate sources and draft structured proposals. |
| Parse | Convert papers into structured records with local parsing support. |
| Lineage | Build a library-level citation graph from parsed material. |
| Reading notes | Render reading-note contracts into browsable notes. |
| Review | Produce review files that keep claims, limitations, and evidence explicit. |
| Handoff | Export Scriptorium Spec-compatible files for downstream tools. |

## Quick start

```powershell
git clone https://github.com/scriptorium-suite/steward.git
cd steward
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\steward.exe --help
```

Run a safe audit before applying any library operation:

```powershell
.\.venv\Scripts\steward.exe audit --help
```

Work with proposals and handoffs:

```powershell
.\.venv\Scripts\steward.exe pick --help
.\.venv\Scripts\steward.exe proposal --help
.\.venv\Scripts\steward.exe export --help
```

## Literature workflow

```text
Zotero or local source list
        │
        ▼
backup + audit
        │
        ▼
pick sources → parse papers → produce reading notes
        │
        ▼
lineage graph + review files
        │
        ▼
proposal / handoff files for Scriptorium, Provenance, or other tools
```

The workflow is intentionally review-first. Steward should help a researcher or project owner see what changed and why before a downstream tool treats the material as project context.

## Optional local parsing

Some parsing workflows use GROBID or other local services. Those services are optional and should be run by the user in their own environment. Steward's public contract is the structured output file, not a hosted parsing service.

## Suite interoperability

Steward writes [scriptorium-spec](https://github.com/scriptorium-suite/scriptorium-spec) contracts. That means its outputs can be consumed by:

- [Scriptorium](https://github.com/scriptorium-suite/scriptorium) as project intake material.
- [Provenance](https://github.com/foxsplendid/Provenance) as local project memory.
- Slide or report components as downstream handoff material.

## Safety contract

Steward is built around preview, backup, and review. It should not silently mutate a user's reference library. Use explicit source selection, inspect generated drafts, and keep the original library data recoverable.

The public fixtures are synthetic or harmless. Do not commit private papers, private notes, Zotero credentials, or personal research material to the public repository.

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## License

Apache-2.0. See [LICENSE](LICENSE).
