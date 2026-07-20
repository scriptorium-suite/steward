# [SYNTHETIC] XQ-17 fixtures only; no value represents a real paper, author, DOI, or research record.
"""Tests for the reading-note/1.0 -> Obsidian markdown projection (read_render.py).

Renders a representative reading-note/1.0 (inlined, mirroring the shipped
scriptorium-spec example) and asserts the self-contained note carries: YAML
frontmatter (citekey / read_status), one bilingual `## ` section PER FILLED
stage (and none for an absent stage), situate `lineage_refs` rendered as
`[[citekey]]` wikilinks, a links block to the library note, and a footer naming
the JSON SSoT. Plus determinism (same input -> identical output), no clock
(`created` reused), wrong schema_version -> RenderError, and --kb enrichment.
stdlib-only, inline fixtures (no host paths).
"""
import re

import pytest

from steward import read_render


# A representative reading-note/1.0, inlined so the test is self-contained and
# portable (no dependency on a sibling repo's checkout path). Mirrors the example
# shipped with the schema: synthetic paper xq17SyntheticStudy015 with two filled stages.
def _two_stage_note() -> dict:
    return {
        "schema_version": "reading-note/1.0",
        "id": "xq17SyntheticStudy015",
        "zotero_key": "K7M4QX2P",
        "doi": "10.0000/scriptorium-demo-xq17-005",
        "read_status": "In Progress",
        "created": "2026-06-22T10:30:00Z",
        "generated_by": "read-paper skill (Claude Code)",
        "stages": {
            "glance": {
                "tldr": "Synthetic XQ-17 calibration under varying inputs.",
                "tags": ["xq17", "synthetic", "calibration"],
                "key_findings": [
                    "Model M2 reaches about 0.42 synthetic error units.",
                    "A reference-check threshold of 0.28 gates each estimate.",
                ],
            },
            "close_read": {
                "question": "Can one regression remain stable across the synthetic XQ-17 range?",
                "method": "Cross-validated multiple regression over fabricated features.",
                "data": "Fabricated paired observations spanning 0.0001 to 40 demo units.",
                "results": "Model M2 reports 1.5 to 2.9 synthetic error units.",
                "figures": ["Fig. 4 (predicted vs observed signal)", "Fig. 6 (model residuals)"],
            },
        },
        "sources": {
            "annotations": ["PDF++/xq17SyntheticStudy015#highlight-eqn33"],
            "parsed_file": "_parsed/xq17SyntheticStudy015.grobid.json",
            "zotero_uri": "zotero://select/library/items/K7M4QX2P",
        },
    }


def _four_stage_note() -> dict:
    note = _two_stage_note()
    note["stages"]["deep_read"] = {
        "critique": "Strong synthetic coverage; one fabricated feature is assignment-sensitive.",
        "reproducibility": "Regression coefficients are published; dataset partly reconstructable.",
        "limits": "Edge-case synthetic inputs stretch the calibration range.",
        "relation_to_my_work": "This fixture demonstrates the example XQ-17 pipeline.",
    }
    note["stages"]["situate"] = {
        "direction": "Synthetic XQ-17 calibration methods.",
        "lineage_refs": ["xq17SyntheticStudy017", "xq17SyntheticStudy016"],
    }
    return note


def test_absent_optional_fields_never_render_as_none():
    """Regression: a missing optional field must be OMITTED, never emitted as the
    literal string "None" (an absent value used to leak via _oneline(None))."""
    note = {
        "schema_version": "reading-note/1.0",
        "id": "xq17SyntheticStudy025",
        "created": "2026-06-22T00:00:00Z",
        "stages": {"glance": {"tldr": "Bare note: no zotero_key, doi, or sources."}},
    }
    md = read_render.render(note)
    assert "None" not in md
    assert "zotero_key:" not in md and "doi:" not in md and "read_status:" not in md
    # the links block must not surface a `None` source either
    assert "`None`" not in md


def _kb_item() -> dict:
    return {
        "key": "K7M4QX2P",
        "title": "[SYNTHETIC] XQ-17 Study 02",
        "authors": ["[SYNTHETIC] Researcher XQ-17-02"],
        "year": "2008",
    }


# -- render: frontmatter -----------------------------------------------------

def test_render_starts_with_frontmatter_carrying_citekey_and_status():
    md = read_render.render(_two_stage_note())
    assert md.startswith("---\n")
    assert 'citekey: "xq17SyntheticStudy015"' in md
    assert "type: reading-note" in md
    assert 'read_status: "In Progress"' in md
    # the doi / zotero_key the note carries land in the frontmatter too
    assert 'doi: "10.0000/scriptorium-demo-xq17-005"' in md
    assert 'zotero_key: "K7M4QX2P"' in md


def test_render_frontmatter_tags_come_from_glance():
    md = read_render.render(_two_stage_note())
    fm = md.split("---", 2)[1]
    assert 'tags: ["xq17", "synthetic", "calibration"]' in fm


# -- render: a section per FILLED stage --------------------------------------

def test_render_has_a_section_per_filled_stage():
    md = read_render.render(_four_stage_note())
    assert "## 速览 · Glance" in md
    assert "## 精读 · Close read" in md
    assert "## 深读 · Deep read" in md
    assert "## 串联定位 · Situate" in md


def test_render_only_glance_renders_only_the_glance_section():
    note = {
        "schema_version": "reading-note/1.0",
        "id": "xq17SyntheticStudy026",
        "created": "2026-01-01",
        "stages": {"glance": {"tldr": "just a glance"}},
    }
    md = read_render.render(note)
    assert "## 速览 · Glance" in md
    # the other three stages are absent -> their sections must not appear
    assert "## 精读 · Close read" not in md
    assert "## 深读 · Deep read" not in md
    assert "## 串联定位 · Situate" not in md


def test_render_skips_a_section_when_its_stage_is_absent():
    # a note with only close_read renders close_read but not glance/deep/situate
    note = {
        "schema_version": "reading-note/1.0",
        "id": "xq17SyntheticStudy027",
        "created": "2026-01-01",
        "stages": {"close_read": {"question": "q?", "method": "m"}},
    }
    md = read_render.render(note)
    assert "## 精读 · Close read" in md
    assert "## 速览 · Glance" not in md
    assert "Question" in md and "q?" in md


def test_render_close_read_labels_fields_and_lists_figures():
    md = read_render.render(_two_stage_note())
    close = md.split("## 精读 · Close read", 1)[1].split("## ", 1)[0]
    for label in ("Question", "Method", "Data", "Results"):
        assert f"**{label}**" in close
    assert "**Figures**" in close
    assert "- Fig. 4 (predicted vs observed signal)" in close


def test_render_glance_renders_tldr_findings_and_tags():
    md = read_render.render(_two_stage_note())
    glance = md.split("## 速览 · Glance", 1)[1].split("## ", 1)[0]
    assert "Synthetic XQ-17 calibration" in glance
    assert "**Key findings**" in glance
    assert "- Model M2 reaches about 0.42 synthetic error units." in glance
    assert "#xq17" in glance


# -- render: situate -> wikilinks --------------------------------------------

def test_render_situate_lineage_refs_become_wikilinks():
    md = read_render.render(_four_stage_note())
    situate = md.split("## 串联定位 · Situate", 1)[1].split("## ", 1)[0]
    assert "Synthetic XQ-17 calibration methods." in situate
    assert "[[xq17SyntheticStudy017]]" in situate
    assert "[[xq17SyntheticStudy016]]" in situate


# -- render: links block + footer --------------------------------------------

def test_render_links_block_wikilinks_the_library_note_and_lists_sources():
    md = read_render.render(_two_stage_note())
    assert "## 链接 · Links" in md
    assert "Library note: [[xq17SyntheticStudy015]]" in md
    assert "`_parsed/xq17SyntheticStudy015.grobid.json`" in md
    assert "zotero://select/library/items/K7M4QX2P" in md
    assert "PDF++/xq17SyntheticStudy015#highlight-eqn33" in md


def test_render_footer_states_machine_source_of_truth():
    md = read_render.render(_two_stage_note())
    assert ("Machine source of truth: `reading-notes/xq17SyntheticStudy015.json`"
            in md)
    assert "generated_by:" in md


# -- render: --kb enrichment -------------------------------------------------

def test_render_kb_enrichment_adds_title_authors_year():
    md = read_render.render(_two_stage_note(), kb_item=_kb_item())
    fm = md.split("---", 2)[1]
    assert 'title: "[SYNTHETIC] XQ-17 Study 02"' in fm
    assert 'authors: ["[SYNTHETIC] Researcher XQ-17-02"]' in fm
    assert 'year: "2008"' in fm
    # the H1 uses the kb title when present
    assert "# [SYNTHETIC] XQ-17 Study 02" in md


def test_render_without_kb_uses_citekey_as_title_and_omits_biblio():
    md = read_render.render(_two_stage_note())
    fm = md.split("---", 2)[1]
    assert "title:" not in fm
    assert "authors:" not in fm
    assert "year:" not in fm
    assert "# xq17SyntheticStudy015" in md


# -- render: determinism + no clock + validation -----------------------------

def test_render_is_deterministic():
    a = read_render.render(_four_stage_note(), kb_item=_kb_item())
    b = read_render.render(_four_stage_note(), kb_item=_kb_item())
    assert a == b


def test_render_reuses_note_created_not_a_clock():
    md = read_render.render(_two_stage_note())
    # created is COPIED from the note, never regenerated
    assert 'created: "2026-06-22T10:30:00Z"' in md


def test_render_rejects_wrong_schema_version():
    with pytest.raises(read_render.RenderError, match="not a reading-note/1.0"):
        read_render.render({"schema_version": "library-kb/1.0", "id": "x",
                            "created": "2026-01-01"})


def test_render_rejects_absent_schema_version():
    with pytest.raises(read_render.RenderError):
        read_render.render({"id": "x", "created": "2026-01-01"})


def test_render_rejects_non_dict():
    with pytest.raises(read_render.RenderError):
        read_render.render([])  # type: ignore[arg-type]


def test_render_rejects_note_without_id():
    with pytest.raises(read_render.RenderError, match="no `id`"):
        read_render.render({"schema_version": "reading-note/1.0", "created": "2026-01-01"})


# -- render: YAML-safety (a value cannot forge frontmatter or a wikilink) -----

def test_render_frontmatter_values_are_yaml_safe():
    note = {
        "schema_version": "reading-note/1.0",
        "id": "evil",
        "created": "2026-01-01",
        "read_status": "In Progress\nINJECTED: true",
        "stages": {"glance": {"tags": ["a\nb: x"]}},
    }
    md = read_render.render(note)
    fm = md.split("---", 2)[1]
    # the embedded newline is collapsed/escaped; no forged top-level key appears
    assert "\nINJECTED: true" not in fm
    assert re.search(r"^read_status:", fm, re.M)


def test_render_wikilink_target_cannot_be_forged():
    note = {
        "schema_version": "reading-note/1.0",
        "id": "x",
        "created": "2026-01-01",
        "stages": {"situate": {"lineage_refs": ["a]] [[b", "c|d"]}},
    }
    md = read_render.render(note)
    # the `]]`/`[[`/`|` are stripped so a ref can't break out of its wikilink
    situate = md.split("## 串联定位 · Situate", 1)[1]
    assert "[[a b]]" in situate
    assert "[[cd]]" in situate


# -- render: annotations as a real section (Feature 4) -----------------------

def test_render_annotations_get_their_own_section():
    """A non-empty sources.annotations renders a dedicated ## 标注 · Annotations
    section (no longer terse sub-bullets under Links)."""
    md = read_render.render(_two_stage_note())
    assert "## 标注 · Annotations" in md
    # the reference-style annotation (path + #fragment, no spaces) renders as code
    ann = md.split("## 标注 · Annotations", 1)[1].split("## ", 1)[0]
    assert "`PDF++/xq17SyntheticStudy015#highlight-eqn33`" in ann
    # the old terse "- Annotations:" sub-bullet header is gone
    assert "- Annotations:" not in md


def test_render_annotation_highlight_text_is_blockquoted():
    """A plain-text annotation (highlight text, with spaces) inlines as a > blockquote
    so the highlight shows in the note, not just a reference."""
    note = _two_stage_note()
    note["sources"]["annotations"] = [
        "The synthetic XQ-17 model reaches 0.42 demo error units.",
        "zotero://select/library/items/K7M4QX2P/annotations/ABC",
    ]
    md = read_render.render(note)
    ann = md.split("## 标注 · Annotations", 1)[1].split("## ", 1)[0]
    assert "> The synthetic XQ-17 model reaches 0.42 demo error units." in ann
    # a scheme-bearing URI annotation renders as an angle-bracket link, not a quote
    assert "<zotero://select/library/items/K7M4QX2P/annotations/ABC>" in ann


def test_render_no_annotations_section_when_absent():
    note = {
        "schema_version": "reading-note/1.0",
        "id": "xq17SyntheticStudy028",
        "created": "2026-01-01",
        "stages": {"glance": {"tldr": "no annotations here"}},
    }
    md = read_render.render(note)
    assert "## 标注 · Annotations" not in md


def test_render_links_section_no_longer_lists_annotations():
    """The library note / parsed_file / zotero_uri stay in Links; annotations moved out."""
    md = read_render.render(_two_stage_note())
    links = md.split("## 链接 · Links", 1)[1]
    assert "Library note: [[xq17SyntheticStudy015]]" in links
    assert "`_parsed/xq17SyntheticStudy015.grobid.json`" in links
    assert "Annotations" not in links     # annotations are their own section now


# -- render: figure-image embeds (Feature 2) ---------------------------------

def test_render_figure_image_path_becomes_obsidian_embed():
    """A figure entry that looks like an image path renders as ![[path]]; a caption
    string still renders as a `- caption` bullet (render-support, not extraction)."""
    note = _two_stage_note()
    note["stages"]["close_read"]["figures"] = [
        "_parsed/xq17SyntheticStudy007/figures/fig4.png",     # an image path -> embed
        "Fig. 6 (P residuals)",                      # a caption -> bullet
    ]
    md = read_render.render(note)
    close = md.split("## 精读 · Close read", 1)[1].split("## ", 1)[0]
    assert "![[_parsed/xq17SyntheticStudy007/figures/fig4.png]]" in close
    assert "- Fig. 6 (P residuals)" in close


def test_render_figure_caption_mentioning_png_stays_a_bullet():
    """A caption that merely mentions an extension but has spaces is NOT a path —
    it must stay a caption bullet, never an embed."""
    note = _two_stage_note()
    note["stages"]["close_read"]["figures"] = ["Fig. 4 saved as plot.png in the SI"]
    md = read_render.render(note)
    close = md.split("## 精读 · Close read", 1)[1].split("## ", 1)[0]
    assert "- Fig. 4 saved as plot.png in the SI" in close
    assert "![[" not in close


def test_render_figure_embed_target_cannot_forge_a_second_embed():
    """A figure path carrying `]]![[` must not break out into a second `![[ ]]`
    embed (the brackets are stripped, mirroring _wikilink)."""
    note = _two_stage_note()
    note["stages"]["close_read"]["figures"] = ["evil.png]]![[../../secret.png"]
    md = read_render.render(note)
    close = md.split("## 精读 · Close read", 1)[1].split("## ", 1)[0]
    # exactly one embed, brackets stripped from the interior -> no forged 2nd embed
    assert close.count("![[") == 1
    assert "]]![[" not in close


def test_render_annotation_code_span_cannot_be_broken_out():
    """A path-like annotation with a backtick / brackets must not terminate its code
    span or smuggle a forged embed out of it."""
    note = _two_stage_note()
    note["sources"]["annotations"] = ["a/b`x]]![[y"]   # path-like (has /, no spaces)
    md = read_render.render(note)
    ann = md.split("## 标注 · Annotations", 1)[1].split("## ", 1)[0]
    assert "`" in ann                       # it is rendered as a code span
    assert "]]![[" not in ann               # brackets stripped -> no forged embed
    # the stray backtick is removed so the span can't be terminated early
    assert "`a/bx" in ann.replace("]", "").replace("[", "")
