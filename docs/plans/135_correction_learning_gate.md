# Plan #135: Correction-Aware Learning Gate

**Status:** In Progress — typed audit and deterministic Stop verifier
implemented; native classifier remains manual/off pending representative native
evidence
**Type:** implementation
**Priority:** High
**phase_ref:** "Phase 9: Fleet Adoption and Framework Maintenance"
**goal_ref:** "correction-aware-agent-learning"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Blocked By:** None
**Blocks:** None

`trace_evaluable: true`

---

## Gap

**Current:** The installed Codex, Claude Code, and OpenClaw completion gate
requires a closing `Learnings` disposition and can verify a cited immutable
learning. It cannot tell whether Brian corrected an agent earlier in the
session, so an agent can incorrectly report `None` after a mistake. The check
also runs on a three-second Stop-hook path, which cannot safely perform model
adjudication. Existing regex-based prose classification has produced confirmed
false blocks and false passes.

**Target:** A client-neutral, typed session audit identifies user corrections
with a light model through `llm_client`, records privacy-reduced correction
receipts, and reconciles each correction to an immutable Project Meta learning
from the same native session. Classification runs outside the Stop hot path.
The completion hook only reads validated receipts. Rollout progresses from
fixture evaluation to observe-only native canaries and then to blocking only
after explicit both-sign thresholds pass.

**Why:** Prompt policy expresses the right behavior but does not prove it
happened. A durable correction receipt plus an independently verified learning
entry turns the behavior into an inspectable control without returning to
string matching or adding another learning store.

## User Outcome

When Brian corrects an agent's mistake, the agent records the reusable lesson
in the shared learning register during that session, and a missed record becomes
visible and eventually prevents a false “done” closeout after the canary proves
the detector is safe.

## Canonical Behavioral Example

**Starting input/state:** A native transcript contains an assistant claim that
Taulant is a shared Second Brain implementation, followed by Brian's correction
that it is a set of specialized Claude Code agent definitions. No learning from
that session exists yet.

**Action:** Run the correction audit, record the learning with the learned
skill, then run the audit and completion verification again.

**Expected observable result:** The first audit emits one typed
`correction_unresolved` receipt referencing only event hashes and a bounded
privacy-reduced rationale. After the learning is recorded with this session's
`source_ref`, the next audit emits `correction_resolved` and names the immutable
learning ID. The Stop verifier accepts the resolved receipt and rejects an
unresolved receipt only when block mode is explicitly enabled.

**Behavioral evidence:** Partial. Typed Codex and Claude transcript fixtures,
same-session semantic learning reconciliation, and both-sign Stop replays pass.
A real Codex transcript audit exposed and drove repair of an unrelated-learning
false resolution. The corrected native rerun then exceeded the intended
lifecycle latency and ended in a structured-result error, so no host wiring or
blocking mode was activated.

**Substrate/process evidence:** Existing native transcript resolvers, the
Project Meta `learning/v3` register, `llm_client` structured output and trace
logs, and content-free hook receipts.

**Failure signal:** A pure scope change is classified as a correction; the
Taulant example is missed; a receipt claims resolution without an immutable
same-session learning; model failure blocks a turn; or semantic classification
runs inside the Stop hook.

## References Reviewed

- `CLAUDE.md` — repository workflow, claimed-worktree, validation, and closeout
  authority.
- `scripts/learning_capture_hook.py` and
  `tests/test_learning_capture_hook.py` — installed disposition gate and its
  deterministic receipt behavior.
- `enforced_planning/coordination_claims.py::session_transcript_path` — existing
  client-neutral resolution of Codex and Claude native transcripts.
- `scripts/session_end.py` — existing client-neutral closeout seam.
- `docs/plans/111_ecosystem_feedback_loop.md` — sole actionable feedback
  transport; reusable lessons remain owned by Project Meta learning/v3.
- `docs/plans/127_turn_end_safety_and_hook_feedback.md` — Stop paths must remain
  bounded and recurring hook failures route through Plan #111.
- `docs/plans/133_shared-surface-change-disclosure.md` — measured rejection of
  prose regex and precedent for structured output, model adjudication, or off.
- `docs/plans/132_overbroad_claim_narrowing.md` — strict claim-surface authority
  for the implementation lane.
- Project Meta learning entries
  `lrn-20260911T191710248178Z-cd8a3f4fc7` and
  `lrn-20260911T192757844201Z-c45c554f56` — concrete same-session correction
  and tool-checking lessons; these are learning/v3 evidence, not episodic
  memory citations.
- `llm_client/CLAUDE.md` and `llm_client/README.md` — required task, trace, and
  budget tags plus Pydantic structured output.
- `/home/brian/.codex/config.toml` and `/home/brian/.claude/settings.json` — live
  three-second learning Stop hooks and native SessionEnd wiring.
- Memory recall for `correction learning gate user correction classifier` in
  `enforced-planning` — unavailable because the installed command could not
  import its Python package; no findings were inferred.

## Research Basis For This Slice

Official OpenAI documentation was searched on 2026-09-11 for Codex
`UserPromptSubmit` hook payload and asynchronous behavior, but no page defining
that schema was found. Therefore this plan does not assume asynchronous Codex
prompt hooks. It uses the repository's existing transcript resolver and requires
an authentic native payload/transcript canary before host activation.

## Landscape And Prior Art

| Alternative | Disposition | Reason |
|---|---|---|
| Prompt instruction only | Retain, insufficient alone | Already active and useful, but cannot prove that a correction produced a record. |
| Regex-match correction phrases | Rejected | Prior hooks produced false blocks and false passes; workspace policy forbids semantic prose inference with regex. |
| Model call in Stop | Rejected | Stop has a three-second budget and must fail predictably even when the model route is unavailable. |
| Model audit of the completed native transcript, with deterministic receipt verification | Selected | Supplies both sides of the exchange, keeps model latency off the hot path, and makes enforcement evidence inspectable. |
| Separate correction database | Rejected | Project Meta learning/v3 already owns durable lessons; hook receipts own enforcement episodes. |

**Alternatives:** The selected design extends existing transcript, learning,
receipt, and feedback owners. It does not introduce a parallel knowledge store.

**Project implications:** Add one typed audit module and thin CLI, extend the
existing learning Stop verifier to consume validated correction receipts, and
extend installed hook generation only after observe-mode evidence passes.

**Refresh trigger:** Revisit if native transcript formats change, Codex publishes
a prompt-hook contract that safely supports asynchronous classification, or the
classifier exceeds the measured false-positive or latency budget.

**Decision method:** Both-sign fixtures and native canaries decide promotion.
No comparative model bakeoff is needed unless the first sanctioned light route
misses the acceptance threshold.

## Modality Assessment

**Hybrid.** Receipt schemas, register reconciliation, and Stop behavior are
deductive and test-first. Correction classification is empirical and must pass
a held-out both-sign set plus native observe-only canaries before enforcement.

## Acceptance Mode

**Mixed.** Deterministic contracts are checked. Semantic classifications are
judged against labeled examples and traced native executions. Promotion to
blocking requires no false positives in at least 20 negative examples, at least
90% recall across at least 10 positive examples, and five native corrected or
uncorrected sessions with no unexplained classification.

## Capabilities

Extends the existing `learning_capture_hook.py`, `session_end.py`, transcript
resolver, hook receipts, Project Meta learning/v3 register, and Plan #111
feedback route. The classifier uses `llm_client.call_llm_structured` with a
Pydantic response model, prompt asset, stable trace ID, and a per-audit maximum
budget of $0.05. Model or transcript failure emits an observable audit error and
never blocks completion.

## Capability Adoption

**Disposition: extend.** The authentic consumers are the configured Codex and
Claude Code SessionEnd/Stop paths. Source-only fixtures do not prove adoption.
Host activation requires a generated wiring change, a live check, and retained
native receipts from both clients; OpenClaw remains observe-only until its
transcript boundary is separately demonstrated.

## Epistemic Planning Frontier

| Area | State | Current contract | Trigger or stopping rule | Downstream update |
|---|---|---|---|---|
| Transcript extraction | exploration_required | Existing resolver locates files; correction-pair extraction is not yet shared | Parse one current Codex and one current Claude transcript without retaining raw prose | fixtures and adapters |
| Semantic classification | exploration_required | Structured light-model verdict | Stop after threshold set passes or route is rejected | observe/block mode |
| Learning reconciliation | fully_specifiable_now | `learning/v3.source_ref` equals native session identity and `recorded_at` follows correction | both-sign tests | deterministic verifier |
| Stop behavior | fully_specifiable_now | receipt reads only; model/audit failure cannot block | native-shaped replay | hook extension |
| Host activation | fully_specifiable_now | Brian said “proceed” in this session; promotion is bounded by the acceptance thresholds | both client canaries pass before block mode | generated hook wiring |

## Reassessment Contract

- **Triggers:** any false-positive native correction, model cost above $0.05 per
  audit, missing transcript provenance, or Stop latency above 250 ms attributable
  to this check.
- **Autonomous action:** remain or return to observe mode, record the failure
  through Plan #111, and improve fixtures or extraction without weakening
  provenance.
- **Plan revision required:** moving semantic inference into Stop, creating a
  new learning store, or changing the Project Meta learning schema.
- **Human decision required:** accepting a lower precision threshold or raising
  the per-audit budget above $0.05.
- **Stopping rule:** source tests, authentic traced classification, native
  Codex/Claude observe receipts, block-mode both-sign replay, self-test, and
  installed live check all pass.

## Files Affected

- `docs/plans/135_correction_learning_gate.md`
- `docs/plans/135_correction_learning_gate_work_graph.json`
- `enforced_planning/correction_learning.py` (create)
- `scripts/correction_learning_audit.py` (create)
- `scripts/learning_capture_hook.py`
- `scripts/session_end.py`
- `enforced_planning/hook_wiring.py`
- `tests/test_correction_learning.py` (create)
- `tests/test_learning_capture_hook.py`
- `tests/test_generate_hook_wiring.py`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `prompts/correction_learning/` (create, if the shared client can load a
  repository-owned prompt asset; otherwise use the sanctioned shared prompt
  registry and revise this list before editing)

## Plan

### Critical Path Classification

**Critical-path classification: vertical.** One correction must travel from a
real transcript through a structured verdict, an immutable learning lookup, a
receipt, and the existing Stop verifier. Wiring more clients before this path
works would only multiply an unproven control.

### Steps

1. Add privacy-reducing transcript adapters that emit typed adjacent
   user/assistant event pairs and hashes for current Codex and Claude formats.
2. Add a strict Pydantic correction verdict and repository-owned prompt asset;
   call it through `llm_client` with required trace and budget metadata.
3. Evaluate labeled positive, negative, and ambiguous fixtures. Ambiguous and
   runtime errors are observable but never enforcement-positive.
4. Reconcile positive corrections against immutable Project Meta entries whose
   `source_ref` matches the native session and whose timestamp follows the
   correction; persist a content-minimized correction receipt.
5. Extend the Stop verifier to read receipts only. Observe mode reports but
   allows; block mode rejects only a validated unresolved correction. Re-fired
   Stop remains non-recursive.
6. Launch the audit from the existing SessionEnd seam without extending its
   blocking latency. Add generated hook wiring only if a separate launcher is
   actually required.
7. Run one traced Codex and one traced Claude observe canary. Compare verdicts
   with the source transcripts and measure cost and latency.
8. Enable block mode only after the stated thresholds pass; otherwise retain
   observe mode and leave the exact failing evidence in the plan.

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|---|---|---|
| `tests/test_correction_learning.py` | `test_known_correction_is_unresolved_without_learning` | Positive fixture produces an unresolved typed receipt. |
| `tests/test_correction_learning.py` | `test_scope_change_is_not_a_correction` | A changed request does not become enforcement-positive. |
| `tests/test_correction_learning.py` | `test_same_session_newer_learning_resolves_correction` | Exact durable provenance resolves the receipt. |
| `tests/test_correction_learning.py` | `test_other_session_or_older_learning_does_not_resolve` | Unrelated learning cannot satisfy the gate. |
| `tests/test_correction_learning.py` | `test_model_failure_is_visible_and_non_blocking` | Runtime failure fails observable, not closed. |
| `tests/test_learning_capture_hook.py` | `test_block_mode_requires_resolved_correction_receipt` | Stop blocks only on a validated unresolved receipt. |
| `tests/test_learning_capture_hook.py` | `test_observe_mode_never_blocks_unresolved_correction` | Canary mode cannot interrupt work. |
| `tests/test_generate_hook_wiring.py` | `test_correction_audit_wiring_is_generated_for_supported_clients` | Adopted native wiring stays reproducible. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| `tests/test_learning_capture_hook.py` | Existing closing disposition behavior remains intact. |
| `tests/test_session_cli.py` | Session closeout and claim retirement remain bounded. |
| `tests/test_generate_hook_wiring.py` | Generated client hook contracts remain valid. |

## Acceptance Criteria

- [x] The Taulant correction fixture is detected and a pure scope change is not.
- [x] Same-session immutable learning provenance is required for resolution.
- [x] No model call or transcript parsing occurs in the Stop hot path.
- [x] Model/transcript failure is visible and cannot block completion.
- [ ] The labeled set meets the stated precision and recall thresholds.
- [x] One authentic traced structured call stays within the $0.05 audit budget.
- [ ] Codex and Claude Code each emit a verified native observe receipt.
- [x] Block-mode native-shaped both-sign replays pass before host promotion.
- [x] Focused tests and `python scripts/self_test.py` pass.
- [ ] Installed hook checking reports the activated mode accurately.

## Open Questions

- [ ] Which exact current transcript event shapes carry user and assistant text
  for Codex and Claude Code? — **Status: PARTIAL**; current Codex extraction is
  proven from a native transcript and Claude extraction is fixture-covered, but
  a privacy-preserving native Claude canary remains.
- [ ] Can `session_end.py` launch the audit durably without adding a new native
  hook entry? — **Status: OPEN**; prefer extension, prove process lifetime with
  a native canary.
- [ ] Does the first sanctioned light-model route meet the threshold? —
  **Status: PARTIAL, NOT PROMOTABLE**; subscription-backed Haiku was unreliable
  and slow. A stripped Sonnet route passed the frozen synthetic threshold, but
  independent sign-off rejected promotion because no representative native
  held-out corpus established generalization. The route remains manual/off.

## Notes

Brian explicitly authorized proceeding in the conversation that created this
plan. Authorization covers reversible implementation and native observe
canaries. Blocking activation remains conditional on the plan's measured safety
thresholds, not on another approval checkpoint.

Implementation checkpoint (2026-09-11):

- 35 focused correction-audit and learning-hook tests pass, including an
  unrelated later same-session learning as a negative control.
- The audit CLI imports the claimed worktree implementation when executed
  directly; it does not silently import an installed package copy.
- The configured host retains only the existing learning-disposition gate.
  Correction audit wiring and correction blocking remain uninstalled/off.
- Native Codex trace
  `correction-learning/codex/01a09111-50bc-7b21-944b-1e597e6247ce/1c2488daa252b5f95631`
  exposed the unrelated-learning false resolution. Corrected trace
  `correction-learning/codex/01a09111-50bc-7b21-944b-1e597e6247ce/3f819cac1da3e2246883`
  ended in an audit error after one slow successful batch; both remain
  non-blocking evidence against activation.

### Classifier pilot pre-registration

**Claim and decision:** On the frozen synthetic pilot set, the stripped
subscription-backed Sonnet route can return a complete typed classification
with zero enforcement-positive false positives across 20 held-out ordinary
non-corrections and at least 90% recall across 10 held-out corrections. A pass
permits work on native observe-only audit launching; it does not permit Stop
blocking. A failed or invalid run keeps the classifier manual/off and triggers
route or prompt revision on a fresh held-out set.

**Unit and population:** One adjacent assistant/user exchange in Brian's coding
agent conversations. The versioned cases cover factual, action, constraint,
status, ownership, and interpretation corrections; approvals, continuations,
new questions, added scope, preference changes, status requests, and topic
switches; plus ambiguous dissatisfaction. Synthetic cases are a pilot and do
not establish real-world prevalence or production accuracy.

**System and controls:** `prompts/correction_learning/pilot_cases_v1.json` is
frozen before execution. `dev-positive-taulant` and `dev-negative-proceed` are
known development controls and excluded from the held-out score. Every other
positive/negative case is held out from prompt iteration. Ambiguous cases must
not be classified as corrections but are a separately reported boundary group.
The system is `claude-code/sonnet`, low reasoning, six cases per batch, at most
two agent turns, no ordinary tools, no loaded setting sources, and the existing
strict Pydantic schema. Haiku is the rejected baseline: one-turn output was
schema-invalid and a repaired one-exchange result took about 31 seconds.

**Readout:** Primary metrics are held-out false-positive count and positive
recall. Secondary metrics are ambiguous enforcement-positive count, exact
event-ID coverage, total wall time, per-call latency, and route/schema errors.
Any missing/duplicate verdict, route error, schema error, or changed case bytes
invalidates the run. The artifact SHA-256, source commit, prompt bytes, schema,
model, trace IDs, and call metadata are retained for replay. Maximum execution
is one frozen-set run before any prompt change; post-run analysis is diagnostic
only. Any promotion decision requires independent `eval-decision-signoff`.

**Pilot result:** The frozen run at source revision `8a7df95` returned exact
coverage for 36/36 cases, detected 10/10 synthetic held-out corrections, falsely
flagged 0/20 synthetic held-out non-corrections, and treated 0/4 ambiguous cases
as corrections. Six calls took 125.347 seconds in aggregate (12.304–38.928
seconds each). The privacy-reduced result is
`prompts/correction_learning/pilot_result_v1.json`; traces are
`correction-learning/pilot-v1/sonnet/batch-1` through `batch-6`.

**Independent sign-off: REJECTED.** A fresh verifier confirmed artifact hashes,
case counts, deterministic harness checks, route availability, and one
independent three-sign live control (22.664 seconds). It rejected the promotion
decision because all scored cases were hand-authored synthetic examples and no
fresh native cases unseen during prompt/route selection established
representativeness or generalization. Therefore the classifier remains
manual/off; native launching, Stop blocking, and host wiring are not authorized
by this pilot. The next valid evidence is a frozen authentically sampled native
corpus with replayable per-case verdicts and another independent sign-off.
