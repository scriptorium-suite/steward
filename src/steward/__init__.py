"""Steward - reference-library governance for Zotero (Scriptorium suite)."""

__version__ = "0.2.0"

# Exchange formats (scriptorium-spec) this tool produces/consumes.
LIBRARY_KB_SCHEMAS = ("library-kb/1.0", "library-kb/1.1")

PRODUCES = ["library-kb/1.1", "handoff/1.1", "handoff/1.0", "proposal/1.0",
            "parsed-paper/1.0", "lineage-graph/1.0"]
CONSUMES = ["proposal/1.0", "tag-plan/1.0", "project/1.0",
            *LIBRARY_KB_SCHEMAS, "review-draft/1.0"]
