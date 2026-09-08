# Plan #133: Shared-surface change disclosure at closeout

**Status:** Planned
**Type:** implementation
**Priority:** Medium
**phase_ref:** "Phase 6.2"
**goal_ref:** "trustworthy-agent-reporting"
**adrs_referenced:** []
**research_citations:** ["project-meta/learnings/entries/lrn-20260908T084634735345Z-1c3fbe2304.json", "project-meta/learnings/entries/lrn-20260907T183543209729Z-9c9c2ebb1d.json", "project-meta/learnings/entries/lrn-20260908T082259549240Z-2d094b167d.json"]
**Landscape disposition:** inline
**Blocked By:** None
**Blocks:** None

---

## Gap

An agent reports the state of surfaces other agents can also write, from its own
recollection, with no check that anything changed underneath it.

Measured 2026-09-08 in session `014oLQbB`, where three agents worked the same
repositories and the same Monday board concurrently. The reporting agent stated
"No Slack or Monday writes" in roughly twelve consecutive closeouts while another
session added three items to the board group those closeouts described; committed
evidence reading "all 117 items read" against a board holding 120; recorded a
justification that a test suite was red four hours after another session fixed it;
and produced a roadmap asserting a wiki was unpublished 45 minutes after another
session merged one. It rebased onto those sessions' commits four times without
reading any of them.

Nothing broke, because the changes touched disjoint files. That is the same
accident recorded in `lrn-20260907T183543209729Z-9c9c2ebb1d` a day earlier, where
safety came from unrelated discipline rather than from any control.

Existing controls do not close this. `git` protects the repository — worktrees,
rebases, claim registry — and all of them worked. None of them protects the
**report**, which is the artifact the human acts on. Policy proposal
`shared-surface-state-claims` (project-meta `0cda1bc2f0`, pending) states the rule;
this plan builds the mechanism that makes it observable.

## User Outcome

At the end of a session, Brian is told which shared surfaces changed under the
agent while it was working — as a fact computed from re-reading them, not as
something the agent remembered to mention.

## Canonical Behavioral Example

**Starting input/state:** A session opens at 04:00 having touched
`brians-2nd-brain-integration-work` and read Monday board `18400613402`. While it
runs, another agent merges PR #641 to that repo (`07cdd4b9`, 04:03) and creates
three board items (07:16).

**Action:** The session reaches closeout.

**Expected observable result:** The closing report contains, without the agent
being prompted:

> **Changed under this session:** `brians-2nd-brain-integration-work` — 2 commits
> by another author (`07cdd4b9`, `4ee3c163`). Monday board 18400613402 — 3 items
> created, all in "Brian Mills - Knowledge Layer". Slack — not checked.

**Behavioral evidence:** Unobserved. The scenario above is the reconstructed real
case from session `014oLQbB`; no run has yet produced the line.

**Substrate/process evidence:** `monday_enumeration.py` (`11e2f84e`) already
computes the Monday half of this shape in another repository; the git half is a
single `git log` invocation. Neither substitutes for the closeout emitting it.

**Failure signal:** A closeout that says "No Monday writes" while the board gained
items during the session — the exact output produced roughly twelve times on
2026-09-08 — or a delta section rendered where nothing changed externally.

---

## References Reviewed

- `PLANNING_OPERATING_MODEL.md` — strict dependencies, modality and acceptance-mode
  diagnosis requirements.
- `~/.claude/settings.json` Stop-hook block — four disabled hooks and their reasons.
- `enforced-planning/scripts/session_end.py` — the live `SessionEnd` host.
- `agent-skills/hooks/` — where the live Stop/SessionStart hooks are implemented.
- `brians-2nd-brain-integration-work` `11e2f84e` — `plan/project_state/monday_enumeration.py`,
  a working enumeration-with-provenance and computed-absence implementation.
- project-meta `0cda1bc2f0` — the pending policy proposal this mechanism serves.

## Research Basis For This Slice

Three curated findings constrain the design, and one of them rules out the
obvious implementation.

**`lrn-20260908T084634735345Z-1c3fbe2304`** — a validator requiring a provenance
field to be *present* gives no guarantee it is *true*. Applied here: a closeout
check that asks the agent to *declare* what changed is worthless. It must compute
the delta from the surfaces themselves.

**`lrn-20260907T183543209729Z-9c9c2ebb1d`** — a warn-only canonical-checkout hook
was ignored at a 100% rate across six consecutive commits while a concurrent
session was actively committing. Applied here: shipping this warn-only and
assuming compliance repeats a measured failure. Ignores must be counted from the
first slice, not after.

**`lrn-20260908T082259549240Z-2d094b167d`** — absence distinctions collapse where
they are *displayed*, not where they are modelled. Applied here: "not checked",
"checked and unchanged", and "checked and changed" must render as three distinct
strings, and a test must assert the presenter can emit all three.

## Landscape And Prior Art

**Inline, not linked** — the relevant prior art is all local and the decision it
settles is which local pattern to reuse.

Four Stop hooks in this workspace are disabled. Three carry the same 2026-09-04
reason verbatim: *"string-matched prose to infer semantics; false blocks and false
passes both confirmed. Brian: structured output, an LLM adjudicator, or off."* The
fourth was disabled 2026-09-03 for blocking turn-end on any dirty tree, including
mid-legitimate-work.

That is a measured, four-instance rejection of the obvious design. It leaves three
sanctioned options, and this plan takes the first: **structured output**. The check
never interprets the agent's report — it reads git and board state, computes a
diff, and emits structured data. No adjudication is required because nothing needs
to be inferred. This also sidesteps the 2026-09-03 failure by never blocking.

`monday_enumeration.py` (`11e2f84e`) is the reusable pattern for the non-git legs:
an artifact carrying its own `observed_at`, a count derived from its own items, and
a staleness bound that refuses rather than reassures. **Disposition: extend** —
lift it into a shared module rather than reimplementing it here.

## Modality Assessment

**Hybrid, with an explicit partition.**

- **Deductive / plan-first — the git leg and the Monday leg.** Both are "diff two
  enumerations of a fully enumerable set". Behaviour is entirely predictable, so
  these get contracts and fixtures, not experiments.
- **Exploratory / ladder — the Slack leg.** The reading identity only sees channels
  it was invited to, and the channel directory truncated at 25 rows during the
  session that motivated this plan. There is no complete enumeration, so "what
  changed in Slack" has an unknown coverage ceiling. This needs an instrument and
  a readout before any contract.

## Acceptance Mode

**Mixed, partitioned.**

- **Checked** — git and Monday legs. A fixture with a known delta must produce the
  known report; a fixture with no delta must produce silence; a surface that was
  not consulted must render differently from one consulted and unchanged.
- **Judged** — whether the disclosure is *useful*. The unit of accepted output is
  one closeout read by Brian. The apparatus ceiling is honest and low: one human,
  one report, no panel. Slices 1–2 must not claim usefulness from passing tests.

## Capabilities

Extends the existing closeout capability rather than adding a parallel one.
Canonical seam: `enforced-planning/scripts/session_end.py` (`SessionEnd`, live) for
computation, and the agent's closing report for display. Intended consumer: the
human reading the closeout. Adoption proof: a closeout containing a delta line the
agent did not author from memory.

## Capability Adoption

**Disposition: extend.** Extend the existing closeout seam
(`enforced-planning/scripts/session_end.py`) and lift the enumeration-with-provenance
pattern from `brians-2nd-brain-integration-work` `plan/project_state/monday_enumeration.py`
into a shared module. Do not add a second closeout hook, a new Stop gate, a
report parser, or a parallel session-state store.

## Epistemic Planning Frontier

| Area | State | Current contract | Trigger or stopping rule | Downstream update |
|---|---|---|---|---|
| git delta | fully_specifiable_now | `git log base..origin/main` excluding own author | fixture with a known foreign commit reproduces it | slice 1 tests |
| hook timing | exploration_required | unknown whether `SessionEnd` fires before the report is composed | instrument one session and read the ordering | may move computation to `Stop` |
| base revision for a read-only repo | exploration_required | no rule; likely first observed HEAD | first session that reads without writing | slice 1 contract |
| Monday delta | fully_specifiable_now | enumeration diff by item id, staleness-bounded | fixture with an added item reproduces it | slice 2 tests |
| Monday freshness at closeout | human_decision_required | MCP-only access means a hook cannot re-read | Brian decides whether the agent must re-enumerate before reporting | slice 2 acceptance |
| Slack coverage | exploration_required | directory truncated at 25 rows once; ceiling unknown | measure enumerable fraction and its stability | slice 3 may close as `unbounded` |
| ignore rate | fully_specifiable_now | count emissions and whether the report used them | first ten emissions | decides warn-only vs escalation |

## Reassessment Contract

- **Triggers:** the check needs to read the agent's report text; it blocks or
  refuses a turn; the ignore counter shows emissions unused; or the Slack leg
  needs a new access path rather than a bounded coverage statement.
- **Autonomous action:** narrow to the git leg, keep emission-only, and widen the
  fixtures for the three coverage states.
- **Plan revision required:** moving computation from `SessionEnd` to `Stop`,
  adding a fourth surface, or changing what counts as a shared surface.
- **Human decision required:** escalating from emission to any refusal, requiring
  a Monday re-enumeration before every closeout, or accepting a permanently
  unbounded Slack leg as sufficient.
- **Stopping rule:** the three coverage-state fixtures pass, the non-vacuity
  control goes red when the not-checked/unchanged distinction is collapsed, and
  one real session emits a git delta the report carries. Ten emissions with their
  acknowledgement counted ends slice 1; further surfaces do not extend it.

## Files Affected

- `enforced-planning/scripts/shared_surface_delta.py` — new; computes and renders the delta.
- `enforced-planning/scripts/session_end.py` — call it.
- `enforced-planning/tests/` — fixtures for the three render states.
- `~/.claude/settings.json` — no new hook; reuse the live `SessionEnd` entry.

## Plan

### Critical Path Classification

**Critical-path classification: vertical.** The complete increment is a closeout
that states, from a computed diff, what changed under the session. Slice 1 alone
delivers that for git and covers three of the four observed failures; the Slack
instrument is an enabler and its completion advances no product status.

| Increment | Class | Behavior or named blocker changed |
|-----------|-------|-----------------------------------|
| Slice 1 — git leg emitted at closeout | `vertical` | a closeout states concurrent commits by others; covers 3 of the 4 observed failures |
| Slice 2 — Monday leg | `vertical` | a closeout states concurrent board changes, or refuses to claim they are absent |
| Slice 3 — Slack coverage instrument | `enabler` | measures whether a Slack leg can be bounded at all; completing it advances no product status |

### Steps

**Slice 1 — git leg, deductive, checked.** Record each touched repo's base SHA at
first write. At closeout, list commits on the shared branch authored by anyone else
since that base. Emit structured output; the agent incorporates it. Ship the ignore
counter in this slice: log each emission and whether the subsequent report
mentioned it, so the warn-only failure mode is measured rather than assumed.

**Slice 2 — Monday leg, deductive, checked.** Lift `monday_enumeration.py` into a
shared module. Snapshot the board at first read; re-enumerate at closeout; diff by
item id. **Named constraint:** Monday is MCP-only, so a hook cannot re-read it —
the check can only *require* that a re-read happened and refuse to report an
all-clear without one. Absent a fresh enumeration it emits "not checked", never
"unchanged".

**Slice 3 — Slack leg, exploratory.** Instrument first: measure what fraction of
`#sd-*` the reading identity can actually enumerate, given the directory truncation
observed at 25 rows. **Readout:** coverage fraction and whether it is stable across
runs. **Step-down:** if coverage is partial or unstable, Slack reports `unbounded`
permanently and slice 3 closes — a known-incomplete check is better than a false
all-clear, and worse than an honest refusal.

## Required Tests

### New Tests (TDD)

1. A session with commits by another author on the shared branch emits them, by SHA and author.
2. A session with none emits nothing.
3. A surface not consulted renders differently from one consulted and unchanged — all three states distinguishable in output, asserted against the rendered string.
4. A stale Monday enumeration is refused with its age rather than reported as unchanged.
5. Non-vacuity: collapse the not-checked/unchanged distinction in the presenter and confirm test 3 goes red.

### Existing Tests (Must Pass)

- `enforced-planning` suite.
- `session_end.py`'s existing claim-retirement behaviour, unchanged.

## Acceptance Criteria

1. A closeout in a session with concurrent external change contains that change, computed not recalled.
2. A closeout in a session without it contains no delta section.
3. All three coverage states are distinguishable in rendered output, with a test that fails if two collapse.
4. Nothing blocks: no Stop-hook refusal, no turn-end gate. Emission only.
5. Nothing string-matches the agent's prose. Grep the implementation for regexes over report text; there must be none.
6. Emissions and whether the report acknowledged them are counted, so ignore rate is measurable from slice 1.

## Open Questions

- Does `SessionEnd` fire early enough to inform the closing report, or does the delta need computing at `Stop` and only *recorded* at `SessionEnd`? Settle by instrumenting one session before building slice 1.
- What is the base SHA for a repo the session read but never wrote? Probably the first observed HEAD; unresolved.
- Slice 3 may terminate in "cannot be bounded". That is a legitimate outcome, not a failure.

## Notes

This plan exists because the session that produced it failed this way four times
in one night and did not notice until audited. The mechanism is deliberately
unambitious: it emits a fact and counts whether anyone used it.
