"""steward CLI: setup / backup / audit / status."""
from __future__ import annotations

import argparse
import sqlite3
import sys
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import json

from . import CONSUMES, PRODUCES, __version__
from . import apply as apply_mod
from . import backup as backup_mod
from . import config as cfg
from . import export as export_mod
from . import lineage as lineage_mod
from . import lineage_render as lineage_render_mod
from . import parse as parse_mod
from . import pick as pick_mod
from . import portfolio as portfolio_mod
from . import proposal as proposal_mod
from . import read_index as read_index_mod
from . import read_render as read_render_mod
from . import review as review_mod
from . import tagging as tag_mod
from .apply import ApplyError
from .audit import run_audit
from .backup import BackupError
from .export import ExportError
from .lineage import LineageError
from .lineage_render import RenderError
from .read_render import RenderError as ReadRenderError
from .parse import ParseError
from .pick import PickError
from .portfolio import PortfolioError
from .proposal import ProposalError
from .read_index import IndexError_
from .review import ReviewError
from .tagging import TagError
from .zotero_api import ZoteroClient, ZoteroError


def _utf8_streams():
    # Windows consoles default to legacy code pages (GBK etc.); our I/O is UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        # -sig strips a UTF-8 BOM that Windows pipes often prepend to stdin
        sys.stdin.reconfigure(encoding="utf-8-sig")
    except Exception:
        pass


def cmd_setup(args) -> int:
    # file-only load: env-sourced secrets must never be persisted to disk
    if args.profile:
        cfg.validate_profile_name(args.profile)
    p = cfg.load_profile(args.profile, apply_env=False)
    print(f"Configuring profile '{p.name}' -> {cfg.config_path()}")
    print("(Enter keeps the value in [brackets]; audit/backup work without an API key)")

    def ask(label, current, secret=False):
        shown = ("*" * 8 if (secret and current) else current) or ""
        val = input(f"  {label} [{shown}]: ").strip()
        return val or current

    default_data = ""
    guess = Path.home() / "Zotero"
    if not p.data_dir and (guess / "zotero.sqlite").is_file():
        default_data = str(guess)
    p.data_dir = ask("Zotero data directory", p.data_dir or default_data)
    if p.data_dir and not (Path(p.data_dir) / "zotero.sqlite").is_file():
        print(f"  WARNING: no zotero.sqlite under {p.data_dir}")
    p.backup_dir = ask("Backup destination directory (outside the data dir)", p.backup_dir)
    p.library_id = ask("Zotero library ID (zotero.org/settings/keys; optional for now)",
                       p.library_id)
    while True:
        p.library_type = ask("Library type (user/group)", p.library_type or "user")
        if p.library_type in ("user", "group"):
            break
        print("  please answer 'user' or 'group'")
    p.api_key = ask("Zotero API key (optional; empty = read-only local mode)",
                    p.api_key, secret=True)
    path = cfg.write_profile(p)
    print(f"written: {path}")
    print("Note: keys in config files are stored in plain text; prefer the "
          f"{cfg.ENV_API_KEY} environment variable on shared machines.")
    return 0


def cmd_backup(args) -> int:
    p = cfg.load_profile(args.profile)
    missing = p.missing("data_dir", "backup_dir")
    if missing:
        print(f"missing config: {', '.join(missing)} - run `steward setup`")
        return 2
    backup_mod.run_backup(p, force=args.force, tag=args.tag)
    return 0


def cmd_audit(args) -> int:
    if args.db:
        db = Path(args.db)
    else:
        p = cfg.load_profile(args.profile)
        if not p.data_dir:
            print("missing config: data_dir - run `steward setup` or pass --db")
            return 2
        db = Path(p.data_dir) / "zotero.sqlite"
    if not db.is_file():
        print(f"not found: {db}")
        return 2
    print(run_audit(db, as_json=args.json))
    return 0


def _web_client(p: cfg.Profile) -> ZoteroClient:
    missing = p.missing("library_id", "api_key")
    if missing:
        raise ZoteroError(f"web API requires {', '.join(missing)} - run `steward setup` "
                          f"or set the ZOTERO_* environment variables")
    return ZoteroClient(p, local=False)


def cmd_propose(args) -> int:
    if args.db:
        db = Path(args.db)
    else:
        p = cfg.load_profile(args.profile)
        if not p.data_dir:
            print("missing config: data_dir - run `steward setup` or pass --db")
            return 2
        db = Path(p.data_dir) / "zotero.sqlite"
    if not db.is_file():
        print(f"not found: {db}")
        return 2
    tree = [ln.strip() for ln in Path(args.tree).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    if not tree:
        print(f"target tree file is empty: {args.tree}")
        return 2
    if args.inbox and args.inbox not in tree:
        print(f"--inbox {args.inbox!r} is not one of the target-tree paths")
        return 2
    out = Path(args.out)
    if out.exists() and not args.force:
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
            filled = any(p.get("targets") and not p.get("note", "").startswith("(prefilled")
                         for p in existing.get("proposals", []))
        except Exception:
            filled = True
        print(f"refusing to overwrite existing {out}"
              + (" (it has filled-in targets!)" if filled else "")
              + " - pass --force or choose another --out")
        return 2
    doc = proposal_mod.scaffold(db, tree, inbox=args.inbox)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    prompt = out.with_name("PROPOSAL-PROMPT.md")
    prompt.write_text(proposal_mod.PROMPT_TEMPLATE, encoding="utf-8")
    print(f"scaffold: {out} ({len(doc['proposals'])} items, "
          f"{len(tree)} target paths)")
    print(f"filling instructions: {prompt}")
    print("fill `targets` (LLM, agent, or by hand), review, then: "
          f"steward apply \"{out}\"")
    return 0


def cmd_apply(args) -> int:
    doc = proposal_mod.load(Path(args.proposal))
    p = cfg.load_profile(args.profile)
    client = _web_client(p)
    print(proposal_mod.summarize(doc))
    print()
    pl = apply_mod.plan(doc, client)
    print(f"collections to create: {len(pl['collections_to_create'])}")
    for c in pl["collections_to_create"]:
        print(f"  + {c}")
    if pl["keys_not_on_server"]:
        print(f"NOT ON SERVER ({len(pl['keys_not_on_server'])}): "
              f"{pl['keys_not_on_server'][:10]}")
    if not args.run:
        print("\nDRY RUN - nothing written. Re-run with --run to execute.")
        return 0
    apply_mod.execute(doc, client, p, backup_check=not args.no_backup_check)
    return 0


def cmd_rollback(args) -> int:
    if args.list or not args.journal:
        journals = apply_mod.list_journals()
        if not journals:
            print("no journals found")
        for j in journals:
            print(f"  {j}")
        return 0
    p = cfg.load_profile(args.profile)
    apply_mod.rollback(Path(args.journal), _web_client(p), p, run=args.run)
    return 0


def cmd_export(args) -> int:
    p = cfg.load_profile(args.profile)
    client = _client_for_read(p)
    storage = Path(p.data_dir) / "storage" if p.data_dir else None
    kb = export_mod.build_kb(client, storage if storage and storage.is_dir() else None)
    kb_out = Path(args.kb) if args.kb else (Path(p.data_dir or ".") / "kb" / "library.json")
    export_mod.write_kb_json(kb, kb_out, p.library_id, p.library_type)
    print(f"KB: {len(kb)} items -> {kb_out}")
    if args.vault:
        n, folders = export_mod.write_obsidian(kb, Path(args.vault))
        print(f"Obsidian: {n} notes in {folders} folders -> {Path(args.vault) / 'Literature'}")
    return 0


def cmd_pick(args) -> int:
    kb_path = Path(args.kb)
    if not kb_path.is_file():
        print(f"KB not found: {kb_path} - run `steward export` first")
        return 2
    kb = pick_mod.load_kb(kb_path)
    entries = []
    for query in args.query:
        hits = pick_mod.find(kb, query)
        if not hits:
            print(f"no match for {query!r}")
            return 2
        if len(hits) > 1:
            print(f"{query!r}: {len(hits)} matches; using the first:")
            for e in hits[:6]:
                print(f"  {e['key']}  {e['title'][:70]}")
        entries.append(hits[0])
    if len(entries) == 1:
        dest = pick_mod.stage(entries[0], Path(args.staging))  # handoff/1.0
    else:
        dest = pick_mod.stage_report(entries, Path(args.staging),
                                     report_type=args.report_type,
                                     title=args.report_title)  # handoff/1.1
    print(f"staged: {dest}")
    return 0


def _resolve_pdf(target: str, kb_path: str | None) -> tuple[Path, str]:
    """Resolve a `parse` target into (pdf_path, citekey).

    A target that is an existing file is parsed directly (citekey = its stem).
    Otherwise it is treated as a citekey / Zotero key / title and resolved to a
    local PDF via the library-kb (`--kb`); the given target stays the citekey.
    """
    p = Path(target)
    if p.is_file():
        return p, p.stem
    if not kb_path:
        raise ParseError(
            f"{target!r} is not a file; pass --kb <library.json> to resolve it "
            "as a citekey/key/title, or give a PDF path")
    kb = pick_mod.load_kb(Path(kb_path))
    hits = pick_mod.find(kb, target)
    if not hits:
        raise ParseError(f"no library-kb entry matched {target!r} (key or title)")
    if len(hits) > 1:
        print(f"{target!r}: {len(hits)} matches; using the first:")
        for e in hits[:6]:
            print(f"  {e['key']}  {e['title'][:70]}")
    entry = hits[0]
    pdf = pick_mod._largest_pdf(entry)  # PickError if no local PDF
    return pdf, target


def cmd_parse(args) -> int:
    if args.kb and not Path(args.kb).is_file():
        print(f"KB not found: {args.kb} - run `steward export` first or pass a PDF path")
        return 2
    try:
        pdf, citekey = _resolve_pdf(args.target, args.kb)
    except PickError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    url = parse_mod.grobid_url(args.grobid_url)
    parse_fn = parse_mod.get_parser(args.parser)
    print(f"parsing {pdf.name} with {args.parser} ({url}) -> citekey {citekey}")
    doc = parse_fn(pdf, citekey, url=url)
    out = Path(args.out) if args.out else (Path("parsed") / f"{citekey}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    n_sec = len(doc.get("sections", []))
    n_ref = len(doc.get("references", []))
    title = doc.get("metadata", {}).get("title", "")
    print(f"parsed-paper/1.0 -> {out} ({n_sec} sections, {n_ref} references"
          + (f"; {title[:60]!r}" if title else "") + ")")
    return 0


def _collect_parsed_files(targets: list[str]) -> list[Path]:
    """Expand `--papers` targets into parsed-paper JSON file paths.

    Each target is either a directory (its top-level `*.json` files are taken,
    sorted) or a single JSON file. Order across targets is preserved; the loader
    later de-duplicates on citekey.
    """
    files: list[Path] = []
    for t in targets:
        p = Path(t)
        if p.is_dir():
            files.extend(sorted(p.glob("*.json")))
        elif p.is_file():
            files.append(p)
        else:
            raise LineageError(f"no such file or directory: {t}")
    if not files:
        raise LineageError(
            "no parsed-paper JSON files found "
            f"(looked in: {', '.join(targets)}). Run `steward parse` first.")
    return files


def cmd_lineage(args) -> int:
    files = _collect_parsed_files(args.papers)
    papers = lineage_mod.load_set(files)
    if len(papers) < 2:
        print(f"only {len(papers)} parsed paper(s) in the set; a lineage graph "
              "needs at least 2 to have within-set citation edges.")
    graph = lineage_mod.build_graph(papers, query=args.query or "")
    out = Path(args.out) if args.out else Path("lineage.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8")
    n_cites = sum(1 for e in graph["edges"] if e["relation"] == "cites")
    print(f"lineage-graph/1.0 -> {out} ({len(graph['nodes'])} nodes, "
          f"{n_cites} cites edges; typed relations + clusters are enriched later "
          "by the synthesize-direction skill)")
    return 0


def _load_lineage_graph(path: Path) -> dict:
    """Load a lineage-graph/1.0 JSON, mapping format errors to RenderError."""
    try:
        graph = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise RenderError(f"{path}: not valid JSON ({e})") from e
    if not isinstance(graph, dict):
        raise RenderError(f"{path}: expected a lineage-graph/1.0 object")
    sv = graph.get("schema_version")
    if sv != lineage_render_mod.SCHEMA_VERSION:
        raise RenderError(
            f"{path}: not a {lineage_render_mod.SCHEMA_VERSION} graph "
            f"(schema_version={sv!r}). Run `steward lineage` first.")
    return graph


def cmd_lineage_render(args) -> int:
    graph = _load_lineage_graph(Path(args.graph))
    query = (graph.get("direction") or {}).get("query") or ""
    name = export_mod.slug(query) or "lineage"
    md = lineage_render_mod.render(graph, slug=name)

    if args.out:
        out = Path(args.out)
    elif args.vault:
        out = Path(args.vault) / "Reviews" / f"{name}.lineage.md"  # Reviews/ is tool-owned
    else:
        out = Path(f"{name}.lineage.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")          # idempotent: overwriting our own derived note is fine
    print(f"lineage note -> {out} "
          f"({len(graph.get('nodes') or [])} nodes, {len(graph.get('edges') or [])} edges; "
          "self-contained Mermaid + timeline + edge table)")

    if args.stamp_notes:
        if not args.vault:
            print("--stamp-notes needs --vault (where the per-paper notes live)",
                  file=sys.stderr)
            return 2
        changed = lineage_render_mod.stamp_notes(graph, Path(args.vault))
        print(f"stamped Breadcrumbs frontmatter onto {len(changed)} existing note(s) "
              "(opportunistic; absent notes skipped — lean-vault)")
        for c in changed:
            print(f"  ~ {c}")
    return 0


def _load_reading_note(path: Path) -> dict:
    """Load a reading-note/1.0 JSON, mapping format errors to ReadRenderError."""
    try:
        note = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise ReadRenderError(f"{path}: not valid JSON ({e})") from e
    if not isinstance(note, dict):
        raise ReadRenderError(f"{path}: expected a reading-note/1.0 object")
    sv = note.get("schema_version")
    if sv != read_render_mod.SCHEMA_VERSION:
        raise ReadRenderError(
            f"{path}: not a {read_render_mod.SCHEMA_VERSION} note "
            f"(schema_version={sv!r}). Run the read-paper skill first.")
    return note


def _kb_item_for(kb_path: Path, citekey: str):
    """Find the library-kb item whose citekey matches the note's `id`.

    Tolerant: the library-kb keys items by Zotero `key`, while the reading-note id
    is the Better BibTeX citekey. We match on a `citekey` field if the KB carries
    one, else the Zotero `key`, else a citekey-bearing reuse via pick's loader.
    Returns the item dict, or None when no item matches (caller renders without it).
    """
    items = pick_mod.load_kb(Path(kb_path))  # library-kb/1.0 or 1.1; PickError if malformed
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if citekey in (item.get("citekey"), item.get("key"), item.get("id")):
            return item
    return None


def cmd_read_render(args) -> int:
    note = _load_reading_note(Path(args.note))
    citekey = note.get("id") or ""

    kb_item = None
    if args.kb:
        if not Path(args.kb).is_file():
            print(f"KB not found: {args.kb} - run `steward export` first", file=sys.stderr)
            return 2
        kb_item = _kb_item_for(Path(args.kb), citekey)
        if kb_item is None:
            print(f"note: no library-kb item matched {citekey!r}; "
                  "rendering without title/authors/year enrichment")

    md = read_render_mod.render(note, kb_item=kb_item)

    if args.out:
        out = Path(args.out)
    elif args.vault:
        out = Path(args.vault) / "reading-notes" / f"{citekey}.md"  # tool-owned curated view
    else:
        out = Path(args.note).resolve().parent / f"{citekey}.md"  # alongside the JSON
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")          # idempotent: the .md is a derived projection; the .json is SSoT

    stages = note.get("stages") if isinstance(note.get("stages"), dict) else {}
    rendered = [s for s in ("glance", "close_read", "deep_read", "situate")
                if isinstance(stages.get(s), dict)]
    print(f"reading note -> {out} (stages: {', '.join(rendered) or 'none'}"
          + ("; enriched from --kb" if kb_item else "") + ")")
    return 0


def cmd_read_index(args) -> int:
    rn_dir = Path(args.vault) / "reading-notes"
    notes, warnings = read_index_mod.scan_vault(rn_dir)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if not notes:
        # empty/absent reading-notes dir is not an error: a clear message, no crash,
        # and no _index.md written (nothing to index).
        where = "no reading-notes/ directory" if not rn_dir.is_dir() else "no reading-note/1.0 files"
        print(f"{where} under {rn_dir} - nothing to index "
              "(run the read-paper skill to create reading-notes first)")
        return 0
    kb_map = read_index_mod.load_kb_index(Path(args.kb)) if args.kb else None
    md = read_index_mod.build_index(notes, kb_map)
    out = Path(args.out) if args.out else (rn_dir / "_index.md")  # idempotent overwrite
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")

    counts: dict[str, int] = {}
    for n in notes:
        st = (n.get("read_status") or "").strip() or "(no status)"
        counts[st] = counts.get(st, 0) + 1
    by_status = ", ".join(f"{s}={counts[s]}" for s in sorted(counts))
    print(f"reading index -> {out} ({len(notes)} notes; {by_status})")
    return 0


def cmd_portfolio(args) -> int:
    vault = Path(args.vault)
    out = Path(args.out) if args.out else (vault / "Projects" / "_总纲.md")
    pl = portfolio_mod.plan(vault, out, with_git=args.git, init=args.init)
    print(f"projects: {pl.n_projects} -> {out}")
    if not pl.changed:
        print("snapshot already up to date - nothing to do.")
        return 0
    if not args.run:
        print("DRY RUN - snapshot would change. Re-run with --run to write "
              "(content outside the steward markers is preserved).")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(pl.new_content, encoding="utf-8")
    print(f"refreshed static snapshot in {out}")
    return 0


def cmd_tag(args) -> int:
    p = cfg.load_profile(args.profile)
    if args.tag_cmd == "scaffold":
        if args.db:
            db = Path(args.db)
        else:
            if not p.data_dir:
                print("missing config: data_dir - run `steward setup` or pass --db")
                return 2
            db = Path(p.data_dir) / "zotero.sqlite"
        if not db.is_file():
            print(f"not found: {db}")
            return 2
        vocab = []
        if args.vocab:
            vocab = [ln.strip() for ln in Path(args.vocab).read_text(encoding="utf-8").splitlines()
                     if ln.strip() and not ln.strip().startswith("#")]
        doc = tag_mod.scaffold(db, vocab, only_untagged=not args.all)
        out = Path(args.out)
        if out.exists() and not args.force:
            print(f"refusing to overwrite {out} - pass --force or another --out")
            return 2
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        (out.with_name("TAG-PROMPT.md")).write_text(tag_mod.PROMPT, encoding="utf-8")
        print(f"tag scaffold: {out} ({len(doc['items'])} items, "
              f"{len(vocab)} vocab terms); instructions: {out.with_name('TAG-PROMPT.md')}")
        return 0
    # apply
    doc = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    errors = tag_mod.validate(doc)
    if errors:
        print("invalid tag plan:\n  " + "\n  ".join(errors[:20]), file=sys.stderr)
        return 2
    client = _web_client(p)
    print(f"{len(doc['items'])} items to tag")
    if not args.run:
        print("DRY RUN - nothing written. Re-run with --run to execute.")
        return 0
    tag_mod.execute(doc, client, p, backup_check=not args.no_backup_check)
    return 0


def cmd_review(args) -> int:
    if args.review_cmd == "scaffold":
        since = args.since
        if args.since is not None:
            try:
                date.fromisoformat(args.since)
            except ValueError:
                print(f"--since must be an ISO date (YYYY-MM-DD), got {args.since!r}",
                      file=sys.stderr)
                return 2
        if args.since_days is not None:
            if args.since is not None:
                print("use only one of --since / --since-days", file=sys.stderr)
                return 2
            # align with Zotero dateAdded, which is a UTC instant (…Z)
            today = datetime.now(timezone.utc).date()
            since = (today - timedelta(days=args.since_days)).isoformat()
        if not (args.topic or since or args.unread):
            print("select at least one of --topic / --since / --since-days / --unread",
                  file=sys.stderr)
            return 2
        if args.kb:
            kb = Path(args.kb)
        else:
            p = cfg.load_profile(args.profile)
            if not p.data_dir:
                print("missing config: data_dir - run `steward setup` or pass --kb")
                return 2
            kb = Path(p.data_dir) / "kb" / "library.json"
        if not kb.is_file():
            print(f"KB not found: {kb} - run `steward export` first or pass --kb")
            return 2
        # the what's-new digest (no topic) gets a default display name
        label = "" if args.topic else "库内新进展"
        doc = review_mod.scaffold(kb, args.topic, since=since,
                                  unread=args.unread, label=label)
        crit = args.topic and f"topic {args.topic!r}" or "digest 库内新进展"
        bits = [b for b in (f"since {since}" if since else "",
                            "unread-only" if args.unread else "") if b]
        if bits:
            crit += " (" + ", ".join(bits) + ")"
        # nothing to review: early-return WITHOUT writing review.input.json, so a
        # caller (lit-run.ps1, a cron job, a shell chain) can no-op. A clean exit
        # 0 keeps `&&` chains working; the absent file is the "skip" signal.
        if doc["count"] == 0:
            print(f"nothing to review: no papers matched for {crit} "
                  "(topic boundary is exact: 01_ML != 01_MLX) - no file written")
            return 0
        # --out defaults to a date-stamped path so repeated runs don't clobber.
        out = Path(args.out) if args.out else review_mod.default_scaffold_out()
        if out.exists() and not args.force:
            print(f"refusing to overwrite {out} - pass --force or another --out")
            return 2
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        (out.with_name("REVIEW-PROMPT.md")).write_text(review_mod.PROMPT, encoding="utf-8")
        read = sum(1 for pp in doc["papers"] if pp.get("readStatus") == "Read")
        print(f"review scaffold: {out} ({doc['count']} papers, {read} read) for {crit}")
        print(f"drafting instructions: {out.with_name('REVIEW-PROMPT.md')}")
        return 0
    # assemble
    input_doc = review_mod.load_input(Path(args.input))
    draft = json.loads(Path(args.draft).read_text(encoding="utf-8-sig"))
    errors = review_mod.validate_draft(draft, input_doc["papers"])
    if errors:
        print("invalid review draft:\n  " + "\n  ".join(errors[:20]), file=sys.stderr)
        return 2
    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"refusing to overwrite {out} - pass --force or another --out")
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(review_mod.render(input_doc, draft), encoding="utf-8")
    print(f"review -> {out} ({len(input_doc['papers'])} papers, "
          f"{len(draft['sections'])} themes)")
    return 0


def _client_for_read(p: cfg.Profile) -> ZoteroClient:
    """Prefer local read-only API; fall back to web if creds exist."""
    if p.local or not (p.library_id and p.api_key):
        return ZoteroClient(p, local=True)
    return ZoteroClient(p, local=False)


def cmd_status(args) -> int:
    p = cfg.load_profile(args.profile)
    print(f"steward {__version__}")
    print(f"produces: {', '.join(PRODUCES)}; consumes: {', '.join(CONSUMES)}")
    print(f"config:   {cfg.config_path()} "
          f"({'exists' if cfg.config_path().is_file() else 'not created yet - run `steward setup`'})")
    print(f"profile:  {p.name}")
    print(f"  library:    {p.library_type}/{p.library_id or '(unset)'}")
    print(f"  api key:    {'set' if p.api_key else '(unset - local/read-only)'}")
    print(f"  data dir:   {p.data_dir or '(unset)'}")
    print(f"  backup dir: {p.backup_dir or '(unset)'}")
    last = backup_mod.latest_backup(p)
    if last:
        print(f"last backup: {last['created']} -> {last['path']} "
              f"({last['files']} files, integrity {last['integrity_check']})")
    else:
        print("last backup: none verified")
    return 0


def main(argv=None) -> int:
    _utf8_streams()
    ap = argparse.ArgumentParser(
        prog="steward",
        description="Reference-library governance for Zotero "
                    "(Scriptorium suite). Safe, auditable, reversible.")
    ap.add_argument("--version", action="version", version=f"steward {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("setup", help="interactive configuration wizard")
    sp.add_argument("--profile", default=None)
    sp.set_defaults(fn=cmd_setup)

    sp = sub.add_parser("backup", help="full data-directory backup with verification")
    sp.add_argument("--profile", default=None)
    sp.add_argument("--force", action="store_true",
                    help="proceed despite journal/WAL residue (NOT recommended)")
    sp.add_argument("--tag", default="", help="suffix for the backup directory name")
    sp.set_defaults(fn=cmd_backup)

    sp = sub.add_parser("audit", help="read-only library health report (no credentials needed)")
    sp.add_argument("--profile", default=None)
    sp.add_argument("--db", default=None, help="path to a zotero.sqlite (default: data_dir)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_audit)

    sp = sub.add_parser("propose", help="write a proposal scaffold (zero credentials; "
                                        "fill targets with an LLM/agent/editor)")
    sp.add_argument("--profile", default=None)
    sp.add_argument("--tree", required=True,
                    help="text file: one target collection path per line (# = comment)")
    sp.add_argument("--db", default=None,
                    help="path to a zotero.sqlite, e.g. a backup snapshot (default: data_dir)")
    sp.add_argument("--inbox", default=None,
                    help="prefill every item's target with this path (must be in --tree)")
    sp.add_argument("--out", default="proposal.json")
    sp.add_argument("--force", action="store_true",
                    help="overwrite an existing --out file")
    sp.set_defaults(fn=cmd_propose)

    sp = sub.add_parser("apply", help="validate + plan a proposal (dry-run); "
                                      "--run executes with journal for rollback")
    sp.add_argument("proposal")
    sp.add_argument("--profile", default=None)
    sp.add_argument("--run", action="store_true", help="actually write (default: dry-run)")
    sp.add_argument("--no-backup-check", action="store_true",
                    help="skip the verified-backup requirement (NOT recommended)")
    sp.set_defaults(fn=cmd_apply)

    sp = sub.add_parser("rollback", help="restore item collections from a journal "
                                         "(dry-run by default; --run executes)")
    sp.add_argument("journal", nargs="?", default=None)
    sp.add_argument("--list", action="store_true", help="list available journals")
    sp.add_argument("--run", action="store_true", help="actually write (default: dry-run)")
    sp.add_argument("--profile", default=None)
    sp.set_defaults(fn=cmd_rollback)

    sp = sub.add_parser("tag", help="AI tags + TLDR + reading status (scaffold/apply)")
    sp.add_argument("--profile", default=None)
    tsub = sp.add_subparsers(dest="tag_cmd", required=True)
    ts = tsub.add_parser("scaffold", help="emit a tag plan to fill (zero credentials)")
    ts.add_argument("--db", default=None)
    ts.add_argument("--vocab", default=None, help="controlled vocabulary file (one term/line)")
    ts.add_argument("--all", action="store_true", help="include already ai-tagged items")
    ts.add_argument("--out", default="tag-plan.json")
    ts.add_argument("--force", action="store_true")
    ta = tsub.add_parser("apply", help="write a filled tag plan (--run to execute)")
    ta.add_argument("plan")
    ta.add_argument("--run", action="store_true")
    ta.add_argument("--no-backup-check", action="store_true")
    sp.set_defaults(fn=cmd_tag)

    sp = sub.add_parser("export", help="write KB JSON (library-kb/1.1) + Obsidian vault")
    sp.add_argument("--profile", default=None)
    sp.add_argument("--kb", default=None, help="KB JSON output path (default: <data_dir>/kb/library.json)")
    sp.add_argument("--vault", default=None, help="Obsidian vault dir (writes Literature/ + MOC)")
    sp.set_defaults(fn=cmd_export)

    sp = sub.add_parser("pick", help="stage paper PDF(s) + handoff meta for Lectern")
    sp.add_argument("query", nargs="+",
                    help="item key(s) or title substring(s); one -> handoff/1.0, "
                         "two or more -> multi-paper handoff/1.1")
    sp.add_argument("--kb", required=True, help="KB JSON from `steward export`")
    sp.add_argument("--staging", default="handoff", help="staging dir (default: ./handoff)")
    sp.add_argument("--report-type", choices=["literature", "experiment"],
                    default="literature",
                    help="multi-paper only: report kind (default: literature)")
    sp.add_argument("--report-title", default=None,
                    help="multi-paper only: report title (default: auto-generated)")
    sp.set_defaults(fn=cmd_pick)

    sp = sub.add_parser("parse", help="PDF -> parsed-paper/1.0 via a LOCAL parser "
                                      "(GROBID); structured sections + references")
    sp.add_argument("target",
                    help="a PDF path, or a citekey/key/title to resolve via --kb")
    sp.add_argument("--parser", default="grobid",
                    help="parser back-end (default: grobid; the stdlib-clean default)")
    sp.add_argument("--kb", default=None,
                    help="library-kb JSON, to resolve a citekey/key/title to a local PDF")
    sp.add_argument("--out", default=None,
                    help="output path (default: parsed/<citekey>.json)")
    sp.add_argument("--grobid-url", default=None,
                    help=f"GROBID base URL (default: ${parse_mod.ENV_GROBID_URL} "
                         f"or {parse_mod.DEFAULT_GROBID_URL})")
    sp.set_defaults(fn=cmd_parse)

    sp = sub.add_parser("lineage", help="parsed papers -> lineage-graph/1.0 "
                                        "(own-library citation graph; deterministic)")
    sp.add_argument("--papers", nargs="+", required=True,
                    help="parsed-paper/1.0 file(s) and/or a directory of them "
                         "(e.g. the `parsed/` dir from `steward parse`)")
    sp.add_argument("--query", default=None,
                    help="the research direction these papers answer "
                         "(recorded in direction.query)")
    sp.add_argument("--out", default=None,
                    help="output path (default: lineage.json)")
    sp.set_defaults(fn=cmd_lineage)

    sp = sub.add_parser("lineage-render", help="lineage-graph/1.0 -> a self-contained "
                                              "Reviews/ note (native Mermaid + timeline "
                                              "+ edge table; deterministic)")
    sp.add_argument("--graph", required=True,
                    help="a lineage-graph/1.0 JSON (enriched by synthesize-direction)")
    sp.add_argument("--vault", default=None,
                    help="Obsidian vault dir; default output is <vault>/Reviews/<slug>.lineage.md "
                         "(Reviews/ is the tool-owned derived view)")
    sp.add_argument("--out", default=None,
                    help="explicit output path (overrides the --vault default)")
    sp.add_argument("--stamp-notes", action="store_true",
                    help="ALSO append Breadcrumbs frontmatter onto per-paper notes that "
                         "ALREADY exist under the vault (opt-in; never creates notes; "
                         "merges, never clobbers; needs --vault)")
    sp.set_defaults(fn=cmd_lineage_render)

    sp = sub.add_parser("read-render", help="reading-note/1.0 -> a browsable Obsidian "
                                            "note (frontmatter + per-stage sections + "
                                            "wikilinks; deterministic, idempotent)")
    sp.add_argument("note", help="a reading-note/1.0 JSON (from the read-paper skill)")
    sp.add_argument("--kb", default=None,
                    help="library-kb JSON, to enrich the frontmatter with "
                         "title/authors/year (matched on the note's citekey)")
    sp.add_argument("--vault", default=None,
                    help="Obsidian vault dir; default output is "
                         "<vault>/reading-notes/<id>.md (the tool-owned curated view)")
    sp.add_argument("--out", default=None,
                    help="explicit output path (overrides the --vault default; "
                         "default without --vault is <json-dir>/<id>.md)")
    sp.set_defaults(fn=cmd_read_render)

    sp = sub.add_parser("read-index", help="scan reading-notes/*.json -> a reading "
                                          "overview note (status dashboard: grouped "
                                          "sections + table + Dataview; idempotent)")
    sp.add_argument("--vault", required=True,
                    help="Obsidian vault dir; scans <vault>/reading-notes/*.json")
    sp.add_argument("--kb", default=None,
                    help="library-kb JSON to fill the title/year columns "
                         "(matched on each note's citekey)")
    sp.add_argument("--out", default=None,
                    help="explicit output path (default: <vault>/reading-notes/_index.md)")
    sp.set_defaults(fn=cmd_read_index)

    sp = sub.add_parser("portfolio", help="refresh the 总纲 static snapshot from "
                                          "Projects/*.md (dry-run by default)")
    sp.add_argument("--vault", required=True, help="Obsidian vault dir (reads Projects/)")
    sp.add_argument("--git", action="store_true",
                    help="join each project's linked_repo git state (branch/commit/date)")
    sp.add_argument("--out", default=None,
                    help="dashboard path (default: <vault>/Projects/_总纲.md)")
    sp.add_argument("--init", action="store_true",
                    help="append a fresh managed block to an existing marker-less "
                         "dashboard (default: refuse, to avoid a duplicate snapshot)")
    sp.add_argument("--run", action="store_true", help="actually write (default: dry-run)")
    sp.set_defaults(fn=cmd_portfolio)

    sp = sub.add_parser("review", help="literature review (scaffold/assemble): "
                                       "topic papers -> AI draft -> vault note")
    sp.add_argument("--profile", default=None)
    rsub = sp.add_subparsers(dest="review_cmd", required=True)
    rs = rsub.add_parser("scaffold", help="filter a KB into review.input.json "
                                          "(by topic and/or what's-new; zero credentials)")
    rs.add_argument("--topic", default=None,
                    help="collection-path prefix (exact boundary: 01_ML != 01_MLX)")
    rs.add_argument("--since", default=None,
                    help="R13 what's-new: keep items added on/after YYYY-MM-DD")
    rs.add_argument("--since-days", type=int, default=None,
                    help="R13 what's-new: keep items added in the last N days")
    rs.add_argument("--unread", action="store_true",
                    help="keep only items whose read status is not 'Read'")
    rs.add_argument("--kb", default=None,
                    help="library-kb JSON (default: <data_dir>/kb/library.json)")
    rs.add_argument("--out", default=None,
                    help="output path (default: date-stamped review.input-<date>.json)")
    rs.add_argument("--force", action="store_true", help="overwrite an existing --out")
    ra = rsub.add_parser("assemble", help="assemble a filled draft + KB refs into a "
                                          "vault note")
    ra.add_argument("--input", required=True, help="review.input.json from scaffold")
    ra.add_argument("--draft", required=True, help="review.draft.json (review-draft/1.0)")
    ra.add_argument("--out", required=True,
                    help="output note, e.g. <vault>/Reviews/<name>.md")
    ra.add_argument("--force", action="store_true", help="overwrite an existing note")
    sp.set_defaults(fn=cmd_review)

    sp = sub.add_parser("status", help="show config, paths, and last backup")
    sp.add_argument("--profile", default=None)
    sp.set_defaults(fn=cmd_status)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except tomllib.TOMLDecodeError as e:
        # NB: must precede ValueError (TOMLDecodeError subclasses it)
        print(f"error: config file is not valid TOML ({cfg.config_path()}): {e}",
              file=sys.stderr)
        return 2
    except (BackupError, ZoteroError, ApplyError, ProposalError, TagError, PickError,
            ExportError, PortfolioError, ReviewError, ParseError, LineageError,
            RenderError, ReadRenderError, IndexError_, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"error: file not found: {e.filename or e}", file=sys.stderr)
        return 2
    except sqlite3.DatabaseError as e:
        print(f"error: not a usable SQLite database: {e}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("\naborted - nothing was written", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
