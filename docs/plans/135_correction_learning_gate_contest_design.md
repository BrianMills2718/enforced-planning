---
plan_id: "enforced-planning#135"
dependencies: []
dependencies_reviewed: "2026-09-15"
---
# Design: contest/rebuttal loop for the correction-mode gate

**Status:** Design complete — Slice 1 (schema + deterministic re-fire check) is implementation-ready; Slices 2-3 await the human decision and canary run named in section 9. Implementation authority stays with Plan #135.

**Goal:** `design-contest-rebuttal-loop` (roadmap handoff:
[`135_correction_learning_gate_roadmap_goal_handoff.json`](135_correction_learning_gate_roadmap_goal_handoff.json))
**Design depth:** Standard (changes a shared receipt schema consumed by a
Stop-event gate used by both Claude Code and Codex)
**Execution profile overlay:** `runtime_state`

## 1. Objective, non-goals, current/target delta

**Objective** (preserved from the roadmap handoff, unchanged): a Claude
Code/Codex agent that leaves a self-noticed or user-flagged correction
unrecorded is prevented from ending its turn until it either records the
correction or successfully contests the finding, without a new user message
forcing the retry.

**Non-goals** (unchanged from handoff): reviving whole-transcript semantic
classification as the sole detector; a general-purpose agent negotiation
protocol beyond this one gate.

**Current state, verified directly (not assumed):**

- `learning_capture_hook.py`'s `--correction-mode block` path already hard-
  blocks a Stop event when a `CorrectionAuditReceiptV1` has
  `status: correction_unresolved` (`decision = "block_unresolved_correction"`),
  and this is tested (`tests/test_learning_capture_hook.py`, 4 cases).
- **New finding, changes the design:** on the *re-fired* Stop event
  (`stop_hook_active: true`), the hook currently does an unconditional
  `return 0` — it allows the turn to end regardless of whether the
  underlying problem was actually fixed. The comment says this is
  deliberate ("the first refusal already delivered the recovery
  instruction"). This means today's "block" is a single forced nudge, not
  a block-until-resolved loop. Closing this gap is the actual core of this
  design, not the receipt schema by itself.
- The receipt has no state representing "the agent contested this and was
  right." Its four states (`no_corrections`, `correction_unresolved`,
  `correction_resolved`, `audit_error`) only cover comply-or-not.
- The hook already has a *separate*, cheaper, already-built path for
  detecting "did the agent just record a learning": `classify_report()` /
  `report_field()` parse the literal `Learnings: recorded <lrn-id>` marker
  out of the response text. This is deterministic, already reliable, and
  costs no LLM call. It is currently used only for the unrelated
  closing-format gate, not wired into the correction-mode re-fire check.

**Target delta:** the re-fire path stops blanket-allowing. It checks, in
order: (1) did this turn's own response carry a valid `Learnings: recorded`
marker for the flagged event — cheap, deterministic, no LLM call; (2) if
not, did the response carry a structured contest marker — if so, run one
bounded adjudication call; (3) otherwise, block again with the same reason.

## 2. Domain rules and schema delta

**Schema disposition: extend `CorrectionAuditReceiptV1`.**

Add exactly one new status, not two: `correction_contest_accepted`. A
contest that is *rejected* is not a new status — it is a normal
`correction_unresolved` receipt carrying one additional field
(`contest_rejection_reason_hash`) so the next block message can explain why
the rebuttal didn't work, instead of repeating the original reason verbatim.

Rationale for one new status, not a `correction_contested` (pending) state
too: the adjudication call is designed to run synchronously, inline, during
the same re-fired Stop event that carries the rebuttal — there is no
window where a contest sits "pending" between turns. Avoiding that state
avoids inventing an async lifecycle this gate does not need yet.

```
status: no_corrections | correction_unresolved | correction_resolved
        | correction_contest_accepted | audit_error   # + one new value

# new, only meaningful when status == correction_unresolved and a contest
# was attempted and rejected:
contest_rejection_reason_hash: str | None = None
contest_attempt_count: int = 0   # see circuit breaker, section 4
```

`correction_contest_accepted` carries `correction_event_hashes` (which
event was contested) and a new `contest_rationale_hash` (privacy-reduced
hash of the adjudicator's accept reasoning) — structurally parallel to how
`correction_resolved` already carries `rationale_hashes`/`learning_ids`.

## 3. The re-fire flow (the actual behavior change)

```
Stop fires (first time)
  -> receipt.status == correction_unresolved
  -> block, deliver reason (existing behavior, unchanged)

Agent generates again (forced continuation, no new user turn)
  -> either records a learning (Learnings: recorded <lrn-id>)
  -> or emits a structured contest marker with rebuttal text
  -> or does neither (ignores the block)

Stop re-fires (stop_hook_active: true)
  -> NEW: no longer a blanket return 0. Check in order:
     1. classify_report() finds "Learnings: recorded <lrn-id>" in THIS
        response, matching the flagged event -> allow (cheap, deterministic,
        zero LLM cost -- this is the common case and needs no adjudicator)
     2. a structured contest marker is present -> run ONE adjudication call
        (see section 5) on the rebuttal + the original flagged exchange
        -> accepted: write correction_contest_accepted, allow
        -> rejected: write contest_rejection_reason_hash, increment
           contest_attempt_count, re-block with the adjudicator's reason
     3. neither -> re-block with the original reason, unchanged
```

This closes the gap found in section 1 without needing the offline
`correction_learning_audit.py` sweep to catch up first: the common "agent
complied" case is verified the same turn, synchronously, for free.

## 4. Circuit breaker — revised 2026-09-14 with real measured evidence

**The `harness-refire-ceiling` unknown is now resolved, empirically, not
assumed.** Isolated test: a throwaway directory with its own
`.claude/settings.local.json` registering a Stop hook that unconditionally
returns `block`, run via `claude -p "say hi"` under a 60-second wall-clock
safety bound. Reproduced identically on two independent runs:

```
fire=1 stop_hook_active=False
fire=2 stop_hook_active=True
fire=3 stop_hook_active=True
fire=4 stop_hook_active=True
```

The process exited cleanly (exit 0, no model output, 27.9s wall time on the
timed run — well under the 60s bound, confirming a natural harness exit,
not a timeout kill). **Claude Code's own harness hard-caps at exactly 3
forced re-fires (4 Stop events total) before giving up silently: no error,
no output, nothing that would tell a caller why nothing happened.**

This also corrects an assumption in section 3: `stop_hook_active` stays
`true` across *every* re-fire in the chain, not just the second one. A gate
that does `if stop_hook_active: return 0` (today's behavior) discards this
signal on all three re-fires, not only the first.

**Revised recommendation, per Brian's explicit disposition (2026-09-14):
do not cap contest attempts at one.** Brian's stated reasoning: a bound of
one gives the tuning feedback loop too little signal to optimize from.
Start high and tune down from observed friction, not up from an
under-informed guess. But "high" is now bounded by a real number, not
arbitrary: **cap at 3 contest attempts**, matching the harness's own
measured ceiling exactly. Anything above 3 is not actually "higher" — the
harness silently exits at the 4th Stop event regardless of what
`contest_attempt_count` says, so a configured limit of, say, 10 would
produce indistinguishable silent harness give-ups mixed in with genuine
"ran out of attempts" blocks, which would corrupt exactly the tuning
signal Brian wants to collect. 3 is the highest value that stays fully
inside the design's own control.

Each of the 3 allowed attempts should log a durable, distinguishable event
(via `coordination_messages.py` or the existing receipt/telemetry path) so
the promised feedback loop has real data to tune from: how often 1 attempt
would have sufficed, how often it took 2 or 3, and how often even 3 wasn't
enough (which would be the actual signal to consider raising further,
bounded by whatever new harness behavior a future test would need to
re-verify at that point).

## 5. The adjudication call (justifies itself per the LLM-systems test)

Distinct input from the original (rejected) classifier: the agent's
rebuttal text plus the one flagged exchange's rationale hash and event
hash — not the whole multi-turn transcript. Distinct decision: "is this
specific rebuttal a valid reason the flagged event isn't a correction,"
not "scan this conversation for any correction." Distinct independence
gained: Plan #135's rejected classifier had to generalize across arbitrary
conversational shapes with no bound on ambiguity; adjudicating one named,
already-produced rebuttal against one already-identified event is a
narrower, more tractable judgment, which is the whole basis for reusing
the same classifier machinery (`correction_learning_audit.py`) at a
materially lower error cost than its original, rejected use.

Model/route, exact cost bound, and retry/timeout behavior are the
`contest-adjudication-model-and-cost` material unknown carried over from
the roadmap handoff unchanged — this design does not invent a number for
that, per the standing rule against inventing budgets. Recommend a live
canary run (one representative accepted rebuttal, one representative
rejected rebuttal, both replayed against the frozen Plan #135 evidence
shape) before wiring this into a real Stop event, matching Plan #135's own
prior pre-registration discipline.

## 6. Non-claims (carried from the handoff, restated for this artifact)

- This does not claim the underlying classifier's raw recall/precision
  improved over Plan #135's measured numbers. It claims the contest path
  bounds the cost of a wrong call enough to make blocking tolerable, which
  is a different, narrower claim.
- This does not claim Codex-readiness without its own native-format
  replay; Plan #135 measured materially worse Codex recall than Claude
  Code recall, and nothing here re-measures that.
- This does not claim the one-contest-attempt bound is empirically
  correct — it is a recommended default pending Brian's disposition and
  real observed friction.

## 7. Risk-ordered slice horizon

1. **`fully_specifiable_now`** — extend `CorrectionAuditReceiptV1` (one new
   status, two new fields) and its `coherent_status` validator; add the
   re-fire check's step 1 (deterministic `Learnings: recorded` check) to
   `learning_capture_hook.py`. No LLM call in this slice. Fully speced above.
2. **`exploration_required`** — the adjudication call itself (step 2):
   needs the canary run named in section 5 before it can be considered
   speced, not just designed.
3. **`human_decision_required`** — the one-attempt circuit-breaker bound
   (section 4) and the harness-refire-ceiling investigation.
4. **`deliberately_deferred`** — Codex-side native replay and any UI/visible
   surface for a contest exchange beyond the Stop-hook message itself.

Slice 1 is the valuable first vertical: it already closes the single-shot
gap found in section 1 for the overwhelmingly common case (agent complies)
with zero new LLM cost, and is independently testable against the existing
4-case test suite plus new cases for the re-fire path.

## 8. Verification this design licenses

- Extend `tests/test_learning_capture_hook.py`: a case where
  `stop_hook_active: true` and the response carries a valid
  `Learnings: recorded` marker must now `allow`, not silently pass through
  the old blanket `return 0` (regression-proves the fix, not just the
  feature).
- A case where `stop_hook_active: true` and the response carries neither a
  Learnings marker nor a contest marker must still block (proves the gap
  is closed, not just made cosmetic).
- The contest-adjudication slice needs its own frozen pilot cases (one
  clear-accept, one clear-reject, one boundary) before any live wiring,
  matching Plan #135's own classifier pilot discipline exactly.

## 9. Next action

Slice 1 (schema + deterministic re-fire check) is implementation-ready with
no further design ambiguity. Recommend handing it to
`evidence-first-development` directly rather than `work-unit-graph` --
this is one person, one repository, one sequential change with no
independent parallel lanes.

Slices 2-3 need the human decision and the canary run named above before
they are equally ready.
