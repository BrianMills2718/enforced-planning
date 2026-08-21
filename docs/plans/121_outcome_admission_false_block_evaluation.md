# Plan #121: Representative Outcome-Admission False-Block Evaluation

**Status:** In Progress — evaluation pre-registered; implementation and run pending
**Type:** evaluation and decision-support implementation
**Priority:** Critical
**phase_ref:** "Progress-bound coding-agent continuation"
**goal_ref:** "outcome-admission-evaluation"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Execution profile:** pilot
**Overlays:** empirical evaluation, repository governance
**Blocked By:** #120
**Blocks:** mandatory first-consumer outcome admission for new and renewed plans, claims, worktrees, sessions, heartbeats, and writes

---

## Decision And Falsifiable Claim

**Claim:** For the first Enforced Planning consumer, one deterministic
outcome-admission overlay can reject every unallocated, over-WIP, inactive,
circular, or tampered new/renewed write operation while allowing every exact
active outcome, bounded recovery, passive inspection, exact replay, evidence
preservation, and clean closeout case in the frozen Plan #121 suite.

**Decision:** Continue to hard first-consumer implementation only if every
scored case and both-sign control matches its pre-registered disposition and
reason, the corruption control is rejected, evidence coverage passes, and a
fresh independent execution-based sign-off accepts the result. Otherwise
revise the candidate, freeze fresh held-out cases, and rerun before promotion.

**Unit of analysis:** One attempted operation at a sanctioned plan, claim,
worktree, session, heartbeat, pre-write, commit, allocation-bootstrap, passive,
or closeout boundary.

**Population and intended users:** Brian-owned non-trivial coding-agent work
using Enforced Planning's sanctioned coordination lifecycle. The frozen
population snapshot contains 11 live claims and preserves the structural
patterns that can create false blocks: same-repository root/child work,
same-goal cross-repository work, stale legacy duplicates, independent roots,
and the first-consumer control lane.

**Baseline:** Current ordinary authority alone. If the existing claim/write
gate allows an operation, the baseline allows it without reading outcome
allocation or continuation state.

**Minimum useful quality:** Zero critical false blocks, zero critical false
allows, zero unexpected scored defers, 100 percent recall for policy-required
safe operations, 100 percent rejection for circular/bypass cases, both-sign
controls correct, and the evaluator detecting its own corruption control.

**Continue / revise / stop rule:**

- Continue to independent sign-off when every threshold passes on the frozen
  suite and repeated execution reproduces the same readout bytes.
- Revise when any scored result mismatches or the corruption control is not
  detected. Any changed rule or label requires a new suite revision and fresh
  held-out cases; the current result remains retained.
- Stop promotion when infrastructure is unavailable, the candidate cannot be
  executed, the population/suite digest changes, or a cross-repository case is
  silently counted as supported.

**Non-claims:** Fleet or installer adoption; cross-repository allocation
membership; semantic truth of progress receipts; cryptographic resistance to
a bypass by the shared OS identity; selection of Brian's one active product;
and cost- or elapsed-time authorization.

## Gap

Plan #120 hard-gates explicit allocation and classed selection, but ordinary
plan, claim, worktree, session, heartbeat, and write entrypoints remain
outcome-agnostic. Promoting the gate without calibration risks two symmetric
failures:

1. continuing the same circular work because an ordinary claim remains valid;
2. blocking legitimate child work, bounded recovery, inspection, evidence
   preservation, or closeout because each operation is treated as a new
   product.

The current allocation command also requires a live claim and files inside its
worktree. A gate that requires allocation before claim/worktree creation would
therefore deadlock its own bootstrap unless it provides a narrow admission-only
path that cannot carry product writes. That case is critical, not an
implementation detail.

## Research

No web research is needed. The uncertainty is local and executable. Planning
reviewed the approved policy at
`project-meta@f6091b6b:policy/proposals/2026-08-20-outcome-continuation-lease-hard-gate.yaml`,
the cross-project history calibration at
`project-meta@a2349842:investigations/cross-project/2026-08-20-recurring-project-failure-modes.md`,
Plan #120 and its accepted allocation/selection evidence at framework revision
`4340a261`, the current continuation and portfolio source owners, and the exact
live-claim snapshot retained by this plan.

## Landscape And Prior Art

| Candidate | Observed or deduced consequence | Disposition |
|---|---|---|
| Ordinary authority only | Allows claimed circular motion, unallocated starts, and stale outcome continuation. | Baseline only. |
| One new allocation per claim | Blocks legitimate root/child claims for the same outcome and consumes WIP by task decomposition. | Rejected. |
| First writer auto-allocates | Lets task ordering choose Brian's product slot and recreates Plan #120's rejected accidental allocator. | Rejected. |
| Deny every operation on stalled or parked state | Blocks inspection, exact replay, evidence preservation, and closeout required to recover or stop cleanly. | Rejected. |
| Require Plan #120 allocation before any claim/worktree | Deadlocks because Plan #120 allocation currently requires a live claimed worktree. | Rejected without a narrow bootstrap. |
| Compose ordinary authority, safe operations, bounded bootstrap, exact allocation, and continuation state | Separates existing authority from evidence-bound continuation while preserving required escape and closeout paths. | Candidate under evaluation. |

**Alternatives:** The table covers ordinary-only admission, per-claim
allocation, accidental auto-allocation, blanket terminal denial, the current
bootstrap deadlock, and the composed candidate.

**Project implications:** Enforced Planning remains the first live consumer.
The evaluation adds no second registry and cannot authorize installer or
downstream-repository rollout. Promotion must extend the existing owners and
retain the cross-repository membership gap explicitly.

The candidate is a reversible first-consumer overlay, not a parallel control
plane. It must reuse the existing allocation, selection, continuation, and
ordinary-claim owners when promoted.

## User Outcome

Brian gets a decision-ready, per-case answer to whether mandatory outcome
admission will stop circular continuation without trapping genuine progress or
safe recovery/closeout work. A passing result licenses only the first
Enforced Planning consumer and names the unsupported cross-repository boundary
instead of laundering it into a fleet claim.

## Canonical Behavioral Example

**Starting state:** The ordinary authority gate would allow a selected claimed
write. One case has an exact active graph-bound allocation and an active
in-scope outcome. A paired negative case has the same ordinary authority and
allocation but its outcome lease requires recovery after repeated non-outcome
increments. A third case requests passive inspection of a stalled outcome.

**Action:** Run the frozen suite through the candidate admission overlay and
then run a corruption control that changes an expected result only in memory.

**Expected observable result:** The active write is allowed, the circular
continuation is denied despite approval or cost context, passive inspection is
allowed, every remaining scored case matches its frozen reason, and the
corrupted expectation causes a detected mismatch. The same suite rerun emits
the same result digest.

**Failure signal:** Any unallocated, competing, disposed, mismatched, stalled,
or unbounded-recovery write is allowed; any active progress, bounded recovery,
inspection, replay, preservation, or closeout case is denied; ordinary denial
is overridden; the bootstrap path carries product writes; corruption is not
detected; or calibration-only cross-repository membership is reported as
supported.

## Evaluation Stage And Why It Is Warranted

**Stage: pilot.** The approved policy explicitly requires representative
false-block and bypass evidence before hard promotion. This is a genuine
empirical uncertainty: the current live claim population contains structures
that a deductively simple one-claim/one-allocation rule would block. The result
changes the promotion decision, and a deterministic case replay is cheaper
than hardening and rolling back every lifecycle entrypoint.

This is not a model or implementation bakeoff. One reversible candidate is
tested against its required behavior and the current ordinary-authority
baseline.

## System Under Test And Baseline Contract

The candidate composes, in order:

1. the existing ordinary authority decision, which can deny but cannot be
   overridden by outcome state;
2. explicit safe-operation and time-bounded legacy-cutover rules;
3. a narrow allocation-bootstrap rule that cannot request product writes;
4. exact active portfolio allocation state for new or renewed mutations; and
5. the existing continuation decision for active in-scope work or one bounded
   recovery action.

The candidate returns `allow`, `deny`, or `defer` plus one stable reason. A
`defer` is valid only for a declared calibration case outside the first-
consumer promotion scope. The baseline returns the ordinary decision alone.

## Capabilities

| Capability | Input | Output | Producer | Consumer |
|---|---|---|---|---|
| frozen-input validation | exact suite and population files | strict models plus exact file digests or visible invalid-run error | `outcome_admission_evaluation` loader | evaluation CLI |
| candidate admission decision | ordinary, scope, portfolio, and continuation state | typed allow/deny/defer with stable reason | candidate overlay | per-case scorer |
| decision-ready scoring | frozen cases plus exact candidate revision/source digest | per-case baseline/candidate results and threshold metrics | evaluation runner | independent verifier and promotion decision |
| corruption detection | in-memory inversion of one control label | explicit mismatch receipt | corruption control | run-validity gate |
| reproducible public run | portable fixture paths and candidate revision | canonical JSON result and digest | evaluation CLI | operators, tests, and sign-off |

These capabilities extend the existing deterministic outcome-control seam.
They do not duplicate the live allocation or claim registries and do not
activate enforcement.

## Case-Set Provenance, Taxonomy, And Leakage Control

Frozen inputs:

- framework baseline: `4340a2611d6c3bd98a9da2fc182b89e6e44605d0`;
- population fixture:
  `evals/outcome_admission/plan121_population_snapshot.json`;
- population fixture file digest: `cd773a78a412be6c09814dd712d0b745de10611a0b600dc7608b55938c94e55d`;
- normalized live-claim snapshot digest:
  `5a5ba83c84badd0b273cc5b0b7e5dcd116bd0756ded956e01fa635666b9c0e0f`;
- frozen suite: `evals/outcome_admission/plan121_cases.json`;
- suite file digest:
  `2ca787a98645d28004dd5abdf02cb82c1dc1afc6462c0a66981ebd09b47a383f`.

The 30 cases comprise one positive control, one negative control, 16
validation cases, 11 held-out boundary cases, and one calibration-only
cross-repository case. Taxonomy classes cover:

- genuine product, maintenance, external-obligation, child, blocker-repair,
  decision-learning, and bounded-recovery work;
- unallocated or over-WIP starts, disposed/tampered bindings, circular
  approval, equivalent-successor laundering, unbounded recovery, and ordinary
  authority denial;
- passive inspection, exact replay, evidence preservation, and closeout;
- admission bootstrap and bootstrap-scope bypass; and
- legacy cutover, stale legacy state, and unsupported cross-repository
  allocation membership.

Cases are unique by `case_id`. The suite and expected labels are committed
before candidate implementation. No post-run exclusion is allowed. A changed
candidate may be evaluated against this retained suite for regression, but a
failed promotion attempt needs fresh held-out cases before a new promotion
decision.

Selection bias is explicit: repository names and structural relations come
from one current snapshot, while progress-state and adversarial cases are
policy-derived because live claims do not yet retain mandatory outcome state.
The pilot therefore supports first-consumer behavior, not a fleet false-block
rate estimate.

## Controls And Validity

| Control | Construction | Required readout | Invalid-run behavior |
|---|---|---|---|
| Positive | ordinary allow + exact active allocation + active in-scope lease | allow / `outcome_admission_active` | invalidate run |
| Negative | same ordinary authority + active allocation + recovery-required lease | deny / `recovery_required` | invalidate run |
| Corruption | invert one scored expected disposition in memory | scorer reports a mismatch | invalidate run |
| Build adequacy | strict fixture load and all cases produce typed decisions | 30 decisions, no missing ids | invalidate run |

Readiness binds the exact framework revision, the two fixture file digests,
Python dependency import, and the candidate source revision. Missing,
malformed, partial, or digest-mismatched fixtures invalidate the run; they are
not low scores.

## Metrics And Pre-Registered Readout

| Construct | Method and scale | Threshold | Uncertainty | Failure action |
|---|---|---|---|---|
| critical false blocks | expected `allow`, candidate not `allow`; count | 0 | exact per-case deterministic result | revise; no promotion |
| critical false allows | expected `deny`, candidate not `deny`; count | 0 | exact per-case deterministic result | revise; no promotion |
| unexpected defers | scored non-calibration case returns `defer`; count | 0 | exact | revise scope or candidate |
| safe-operation recall | allowed safe cases / all safe cases | 1.0 | exact small-N | revise; no promotion |
| circular/bypass rejection | denied circular/bypass cases / all such cases | 1.0 | exact small-N | revise; no promotion |
| control validity | positive, negative, corruption booleans | all true | exact | invalidate run |
| baseline delta | baseline versus candidate mismatches by case | descriptive | no comparative significance claim | retain for decision context |

No aggregate average can offset a critical failure. Per-case results are
retained. There is no statistical confidence interval because the candidate is
deterministic and the sample is a bounded structural pilot, not a random fleet
sample.

## Execution Matrix And Artifacts

| Run | Input | Output | Purpose |
|---|---|---|---|
| build adequacy | frozen suite and population fixture | typed load receipt | system and inputs exist |
| candidate + baseline | all 30 cases | per-case decisions and metrics | primary readout |
| corruption | one in-memory expected inversion | detected mismatch receipt | evaluator can fail |
| reproduction | unchanged inputs and candidate | identical canonical result digest | deterministic replay |

Planned commands:

```bash
python scripts/evaluate_outcome_admission.py \
  --cases evals/outcome_admission/plan121_cases.json \
  --population evals/outcome_admission/plan121_population_snapshot.json

python scripts/evaluate_outcome_admission.py \
  --cases evals/outcome_admission/plan121_cases.json \
  --population evals/outcome_admission/plan121_population_snapshot.json \
  --corruption-control
```

The accepted result will be retained at
`docs/evidence/plan121_outcome_admission_evaluation.json` with exact source,
fixture, per-case, metric, control, and reproduction digests. No LLM stage or
trace contract applies. Runtime and cost are telemetry only and do not affect
the decision.

## Files Affected

- `enforced_planning/outcome_admission_evaluation.py`
- `scripts/evaluate_outcome_admission.py`
- `tests/test_outcome_admission_evaluation.py`
- `evals/outcome_admission/plan121_cases.json`
- `evals/outcome_admission/plan121_population_snapshot.json`
- `docs/evidence/plan121_outcome_admission_evaluation.json`
- `docs/plans/121_outcome_admission_false_block_evaluation.md`
- `docs/plans/121_outcome_admission_false_block_evaluation_work_graph.json`
- `docs/plans/CLAUDE.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `ROADMAP.md`

## Work Unit OAEV-01 — Freeze, execute, and independently sign off admission evaluation

Implement one strict deterministic evaluator and public read-only CLI against
the frozen suite. Retain the result, grade acceptance evidence, and hand the
exact run to an independent verifier before any hard-gate decision.

Pass when:

- fixture and case digests match the pre-registration;
- the positive, negative, and corruption controls all work;
- all scored thresholds pass with per-case evidence and byte-stable replay;
- the calibration case remains explicitly outside promotion scope;
- evidence coverage reports every acceptance criterion at target grade; and
- independent execution-based sign-off accepts or rejects the promotion on the
  retained artifacts rather than the implementer's summary.

## Acceptance Criteria

| ID | Criterion | Current grade | Target grade | Producer | Verification |
|---|---|---|---|---|---|
| OAEV01-A1 | Frozen population, taxonomy, labels, splits, thresholds, and non-claims precede implementation | designed | accepted | plan + fixtures | file digests and Git history |
| OAEV01-A2 | Candidate and baseline emit typed per-case decisions without overriding ordinary denial | absent | accepted | evaluator | focused tests + full suite run |
| OAEV01-A3 | Positive, negative, and corruption controls prove both-sign evaluator behavior | absent | accepted | evaluator | control run |
| OAEV01-A4 | Zero critical false blocks/allows and full safe/circular thresholds reproduce byte-identically | absent | accepted | result artifact | two exact runs |
| OAEV01-A5 | Coverage grading and fresh independent execution sign-off precede promotion | absent | accepted | coverage auditor + verifier | retained reports |

## Promotion Boundary

A passing Plan #121 result licenses design and implementation of the hard
first-consumer gate only. It does not itself activate any hook. The downstream
promotion must preserve the allocation-bootstrap exception, ordinary-authority
precedence, active-child reuse, bounded recovery, passive operations, legacy
cutover, and clean closeout demonstrated here. Cross-repository allocation
membership remains a named calibration gap and prevents a fleet claim.

## Trace Evaluation

`trace_evaluable: false # deterministic local contracts; no LLM stage`

## Terminal Closeout

Commit this plan and its fixtures before evaluator source. After the run,
retain all failed as well as passing case results, run evidence coverage and an
independent sign-off, then either merge the decision-ready evaluation or record
the exact revision trigger for redesign. Do not activate hard admission inside
this evaluation plan.
