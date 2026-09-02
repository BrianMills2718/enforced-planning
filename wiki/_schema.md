---
title: Wiki Schema
type: system
schema_version: 1
created: 2026-09-01
updated: 2026-09-01
---

# Wiki schema

This file is the durable contract for the compiled wiki. Change it deliberately through `wiki-configure`, then record the change as an event.

## Layers and ownership

| Layer | Default owner | Rule |
| --- | --- | --- |
| `data/`, `inbox/`, `notes/` | Human | Read freely; edit only on an explicit request. |
| `raw/sources/` | Capture tool | Append only. Originals live under each envelope's `original/`; changed content or provenance becomes a new source/capture variant. |
| `raw/derived/` | Agent/tool | OCR, transcripts, and normalized text; always trace back to raw. |
| `wiki/` | Agent | Maintain coherent, interlinked synthesis with source IDs. |
| `outputs/` | Agent | Reports and other deliverables; never primary evidence. |
| `.wiki/` | System | Configuration, events, transactions, and rebuildable state. |
| `.obsidian/` | Human/app | Optional Obsidian settings; do not change unless explicitly requested. |

## Page properties

Use portable YAML frontmatter properties:

```yaml
---
title: Page title
aliases: [Alternate name]
type: concept
domains: [work]
status: current
authority: derived
classification: internal
created: YYYY-MM-DD
updated: YYYY-MM-DD
as_of: YYYY-MM-DD
review_after: YYYY-MM-DD
confidence: medium
sources: [src-web-0123456789ab]
---
```

Required for new knowledge pages: `title`, `type`, `created`, `updated`, and `sources`. A governed workspace should also require `authority: derived` so the compiled wiki cannot compete with native plans, ADRs, policy, code, or evidence as an independent authority. Use standard `aliases`, not custom fields alone, so alternate-title links remain portable across tools. Preserve the legacy `also` field when encountered until an explicit migration.

Recommended controlled values:

- `status`: `draft`, `current`, `needs-review`, `conflicted`, `superseded`, `archived`
- `classification`: `public`, `personal`, `internal`, `confidential`, `restricted`
- `confidence`: `high`, `medium`, `low`, `unknown`

Add domain-specific properties only after documenting their meaning here. For metrics, record definition, unit, window, timezone, filters, system of record, and `as_of`. For decisions, distinguish the decision, owner, rationale, date, and later outcome.

## Page types

Let folders emerge from content. Prefer these stable types when applicable:

- `entity`: person, team, organization, customer, product, system, dataset, or place
- `concept`: a reusable idea, method, policy, or mental model
- `project`: goal, scope, ownership, state, milestones, decisions, and outcomes
- `process`: an operational flow, responsibility boundary, or runbook
- `decision`: context, options, evidence, choice, rationale, and consequences
- `metric`: exact definition, lineage, time semantics, caveats, and observed values
- `comparison`: evidence-backed comparison along explicit dimensions
- `synthesis`: a substantial cross-source answer or evolving thesis
- `timeline`: dated events whose sequence matters

Create a page when the subject is central to one source, appears in multiple sources, or is a durable link target. Do not create empty stubs for passing mentions. Split pages that mix distinct subjects or become difficult to navigate.

## Evidence and citations

Every material factual, numeric, personal, or decision claim must trace to a raw source ID. Cite at claim or paragraph level when precision matters:

```markdown
Payment conversion was 18.4% as of 2026-06-30.[^src-report-a1b2-p12] ^claim-7f3a

[^src-report-a1b2-p12]: `src-report-a1b2`, p. 12, captured 2026-07-14.
```

Use a stable locator when available: page, line, heading, block, timestamp, message ID, row key, query ID, or commit SHA. Derived pages must cite raw evidence, not only another generated summary. Keep `sources` in frontmatter as the complete source-ID set used by the page.

For an in-place migration of an established wiki whose older `sources` values
are paths or URIs, set `governance.legacy_source_references` to `preserve`.
Lint then reports the preserved-reference count as compatibility telemetry while
still requiring registered source IDs on every new `authority: derived` page.
This is a migration boundary, not permission to create more legacy citations.

## Integration rules

1. Read `_index.md` or `_catalog.md`, then search before opening page bodies.
2. Read every page immediately before editing it.
3. Integrate new evidence into the right section; do not append a chronological dump.
4. Update `updated`, sources, aliases, related links, conflicts, and `as_of` where relevant.
5. Preserve attributed human statements as quotations or clearly labeled observations. Keep agent interpretation distinguishable.
6. Keep both sides of a contradiction with dates and sources. Resolve only from source authority, recency, or explicit human judgment.
7. Prefer marking `superseded` or archiving over hard deletion.
8. When a source replaces earlier evidence, capture it with `supersedes`; do not delete the prior envelope or present both revisions as co-equal current evidence.
9. Update the curated `_index.md` after page edits; rebuild generated catalog/backlinks and reverse provenance only at the end.

## Markdown and link conventions

- Use `[[wikilinks]]` for durable internal relationships and standard `aliases` for alternate titles.
- Use heading or block anchors for stable claim locations when useful.
- Keep filenames lowercase kebab-case where practical; titles and aliases may be Chinese or multilingual.
- Keep YAML frontmatter portable. When Obsidian is used, keep it compatible with Properties and Bases; Dataview may be added as an optional view layer but is never required for correctness.
- Keep generated files prefixed with `_` and exclude them from normal knowledge-page counts.

## Writing standard

Lead with the answer or definition. Write neutral, concrete prose organized by theme. Synthesize across sources instead of listing source summaries. Use dates, units, owners, and attributed statements in place of vague adjectives. State evidence gaps and uncertainty plainly. A page should explain why its subject matters within this wiki, not reproduce a generic encyclopedia entry.

## Language

- Answer and report in the user's language.
- For new persistent knowledge, honor an explicit workspace language. When the workspace language is `auto`, use the established primary language of non-generated knowledge; if none exists, use the user's language.
- Do not infer the primary language from system scaffolds, property names, generated indexes, or raw quotations. In a mixed-language workspace, preserve the target page's language and ask only when the choice would materially affect a new page.
- Keep quotations, source titles, proper names, and existing knowledge in their original language unless translation is requested.
- Do not translate or rewrite existing knowledge solely for language consistency without explicit authorization.

## Schema evolution

Change the smallest necessary rule. Preserve backward compatibility or document a migration. Run a read-only lint before and after a migration. Lint may emit machine-readable `proposal-only` schema or instruction refinements; those are evidence for an owner to review, never authorization to edit canonical policy or agent instructions automatically. Never mix a schema migration with unrelated content edits, and never silently recategorize or delete human-authored material.

## Enforced Planning project contract

- `wiki/README.md` is the primary compiled orientation page reached from the
  authentic root README.
- Graph traversal is the first navigation method. Keyword/vector search is a
  bounded secondary fallback; repeated fallback use creates a link-repair task.
- Human-owned goals and requirements come only from repository instructions,
  accepted plans/decisions, and explicit human authority. Code and tests can
  verify implementation but cannot reconstruct missing intent.
- Plans, ADRs, capabilities, config, runtime state, and evidence retain their
  native lifecycle and authority. The wiki links to them; it does not copy
  their mutable status as an independent source of truth.
- Completed and superseded development history stays outside default wiki
  navigation. Recovery is through Git or an explicitly on-demand archive.
- Every goal or requirement ambiguity is recorded in the Plan 254 concern
  queue with consequence, recommendation, confidence, importance, tradeoffs,
  alternatives, and cleanup safety.
- Safe subtraction is part of maintenance. A new wiki with unchanged active
  sprawl cannot claim documentation improvement.
