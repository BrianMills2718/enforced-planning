---
schema_version: "1.0"
artifact_type: design_plan
id: PROBE-research-first
status: proposed
method_conformance_receipt: plugins/company-planning/docs/evidence/method-conformance/canonical-probe/research-first.receipt.json
---

# Session resume note (research-first variant)

Canonical Plan #48 probe fixture. Route: `bounded-design`, `durable_solo`.

## Actor and result

**Actor:** the next agent session that picks up a half-finished Company Planning
task after the previous session ended.

**Desired result:** that session can resume from a structured resume note that
the planning plugin writes when a session closes, instead of re-reading the
whole conversation.

**Stable example:** a session stops after adopting a bounded design but before
claiming the first work unit. The next session runs the resume command and sees
one note stating: the adopted plan path and digest, the next work unit
(`WU-…-001`), and the single open question. It claims the unit without
re-reading the transcript.

## Authority and non-goals

**Authority:** Brian owns the Company Planning plugin and has authorized
reversible repository changes to it. The single owning agent for this plan
decides implementation details inside that authority. No other team or
repository owner is involved.

**Non-goals:**

- no change to the claim registry or worktree lifecycle (Enforced Planning owns
  those);
- no new shared state service, dashboard, or MCP server;
- no publication or organization-wide rollout of the plugin;
- no migration of existing session records.

This plan proposes no irreversible action and no spend beyond ordinary
development.

## Success and disproof

**Success evidence:** in the stable example above, a fresh session that runs the
resume command reaches the correct next work unit and open question using only
the resume note; a test fixture reproduces that journey from a recorded note.

**Disproof:** the approach is wrong if a fresh session given only the note
picks a different next unit than a session that re-read the transcript, or if
the note needs fields the existing handoff contract cannot express.

## Prior art and ownership

Searched before designing anything new:

- **Existing ownership:** `NextSkillHandoffV1`
  (`contracts/next-skill-handoff.schema.json`) already carries "what to do next"
  between skills, and the session-work snapshot
  (`contracts/session-work/`) already records a session's open items.
  Disposition: **extend** — the resume note is a projection of these two, not a
  new contract.
- **Internal lineage:** Enforced Planning's `session_resume.py` resumes claimed
  lanes. Disposition: **reuse** for lane state; the note links to it rather
  than copying claim state.
- **External prior art:** Architecture Decision Record "status + consequences"
  sections and the Keep a Changelog "Unreleased" convention. Disposition:
  **bounded exception** — useful naming only; neither expresses a next
  work unit.

**Parallel-implementation check:** a test asserts that the resume note is
generated only from `NextSkillHandoffV1` plus the session-work snapshot, and
fails if any other module writes a file with the resume-note record type.

## Uncertainties

| Uncertainty | Owner or resolving evidence |
| --- | --- |
| Whether the session-work snapshot always names the open question | Resolved by the fixture replay of three recorded sessions in the first slice |
| Whether Codex exposes a session-close event to trigger the note | Owner: the implementing agent; resolved by reading the installed Codex hook list before slice 2 |

## Design approach

The format is decided from first principles and the prior art above: the note
is a typed projection of `NextSkillHandoffV1` plus the session-work snapshot,
with exactly three fields (adopted plan path and digest, next work unit, open
question). Every field already exists in those contracts, so no format choice
remains that an experiment could change. No A/B comparison, benchmark, or
model bake-off is proposed: the remaining uncertainties are factual and are
resolved by the fixture replay and the hook-list check named above.

## Evaluation

No comparative evaluation. Verification is the success evidence above: the
fixture replay of three recorded sessions, plus the parallel-implementation
test.
