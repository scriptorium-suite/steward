---
name: review-fill
description: >-
  Fill a Steward review.input.json scaffold and write a sibling
  review.draft.json conforming to review-draft/1.0. Use interactively between
  steward review scaffold and steward review assemble for themed prose, gaps,
  and priority reads grounded only in the supplied papers.
---

# Review fill (literature-review draft)

Turn ONE `review.input.json` into the `review.draft.json` that `steward review
assemble` is waiting for. The deterministic halves — selecting the papers
(`review scaffold`) and assembling the vault note + the **authoritative reference
table** (`review assemble`) — are done by the steward package, which **never
calls an LLM**. The drafting between them is the one non-deterministic step, and
it is YOU. No LLM API is wired into steward — you are the intelligence (same
precedent as Provenance's `session-summary` skill: the agent synthesizes; the
code does not).

You are given the path to a `review.input.json` (schema `review-input/1.0`).
Write a sibling `review.draft.json` (schema `review-draft/1.0`) in the SAME
directory, then stop.

## Steps

1. **Read the input** at the given path. It carries `topic` / `label` /
   `selection` and `papers` — each with `key`, `title`, `authors`, `year`,
   `doi`, `tldr`, `aiTags`, `readStatus`, and a truncated `abstract`. (A
   what's-new digest has `label: "库内新进展"` and no `topic`; the `selection`
   field records the since/unread filters.)
2. **Read the sibling `REVIEW-PROMPT.md`** if present — it is the authoritative
   `review-draft/1.0` contract written by `review scaffold`. The rules below
   reproduce it; if they ever differ, `REVIEW-PROMPT.md` wins.
3. **Produce the draft** from the papers (rules below). Facts only — no invention.
4. **Write `review.draft.json`** next to the input, containing ONLY the JSON
   object. Do not print commentary, do not write any other file.

## Workflow

1. Cluster the papers into 3-6 coherent themes.
2. Draft each theme as a short prose section, citing the papers it covers by
   `key` in `covered_keys`.
3. Write an `intro` (the topic's / digest's arc and why it matters) and
   `gaps_future` (research gaps + concrete next steps).
4. Pick the handful of papers a newcomer should read first (`priority_reads`).

## Rules (anti-fabrication — enforce strictly)

- Cite ONLY as "Author Year" in prose. Do NOT write DOIs or a reference list —
  steward builds the authoritative table from the KB so citations cannot be
  fabricated.
- Do NOT invent papers. Every `key` in `covered_keys` / `priority_reads` must be
  a real `key` from `review.input.json` (steward rejects an unknown key).
- Be honest about evidence: most items are unread and many have only an
  abstract. Say when a claim is abstract-confirmable vs. needs close reading,
  and flag abstract-less classics as lowest-confidence.
- This is a reading roadmap, not a close-reading summary. Do not state specific
  numeric results as established conclusions.
- For a what's-new digest, treat it as a short orientation to the week's new /
  still-unread arrivals, not a full survey.

## review-draft/1.0 contract

```json
{
  "schema_version": "review-draft/1.0",
  "title": "optional display name (defaults to the topic / digest label)",
  "framing": "one sentence orienting the reader to the review's angle",
  "intro": "introduction prose (the arc and why it matters)",
  "sections": [
    {"title": "theme name", "body": "prose", "covered_keys": ["KEY1", "KEY2"]}
  ],
  "gaps_future": "research gaps and concrete next steps",
  "priority_reads": ["KEY3", "KEY1"]
}
```

Then steward runs:
`steward review assemble --input review.input.json --draft review.draft.json --out <vault>/Reviews/<name>.md`

## Guardrails

- **One output only:** the sibling `review.draft.json`. Nothing else.
- **Language:** the draft content matches the library's working language
  (Chinese by default here); the JSON keys stay exactly as in the contract.
- No network, no telemetry; read only the input + REVIEW-PROMPT.md.
