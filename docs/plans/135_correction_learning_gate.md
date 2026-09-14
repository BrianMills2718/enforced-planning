# Plan #135: Correction-Aware Learning Gate

**Status:** In Progress — Prompt 1.2/Sonnet promotion route rejected by signed
native evidence; classifier remains manual/off pending a materially different
detection design
**Type:** implementation
**Priority:** High
**phase_ref:** "Phase 9: Fleet Adoption and Framework Maintenance"
**goal_ref:** "correction-aware-agent-learning"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Blocked By:** A materially different correction-detection design with new
evidence; further retuning or holdouts on the rejected route are not ready work
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

Official OpenAI hook documentation was rechecked on 2026-09-11 after the
refresh trigger below fired. It now defines Codex `UserPromptSubmit` payloads
with `prompt` and `turn_id`, and permits a hook to return
`hookSpecificOutput.additionalContext`. It also documents asynchronous command
hooks, while warning that they cannot steer the event that launched them, and
describes `transcript_path` as an unstable convenience interface. The current
authority is <https://learn.chatgpt.com/docs/hooks>.

The revised thin slice therefore uses the stable prompt event only to inject an
immediate learning checkpoint and retain a privacy-reduced attention receipt. It
does not classify the prompt, depend on transcript bytes, or claim that an
asynchronous classifier completed before Stop. Semantic blocking remains off.

The installed-health check now treats Codex configuration presence and runtime
eligibility as separate facts. For each exact learning hook slot it reproduces
Codex's normalized command-hook fingerprint and requires both an enabled state
and a matching `trusted_hash`; a configured but disabled, untrusted, or modified
hook makes `live` false. Claude Code and OpenClaw retain their native structural
checks because they do not expose the same per-slot trust contract.

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

- `.gitignore` (allow the execution-loop cursor to remain durable)
- `docs/evidence/plan135_native_corpus_outcome.json`
- `docs/evidence/plan135_native_corpus_allocation.json`
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
  **Status: UNKNOWN ON REPRESENTATIVE NATIVE CORRECTIONS**;
  subscription-backed Haiku was unreliable and slow. A stripped Sonnet route
  passed the synthetic threshold, but the first native corpus was invalidated
  by population and label defects. The route remains manual/off; any revised
  mechanism needs a correctly frozen fresh holdout and independent sign-off.

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
- Prompt-time attention and Stop disposition hooks are installed for Codex and
  Claude Code. Direct native-shaped canaries emitted privacy-reduced attention
  receipts for both clients. Codex's exact prompt and Stop slots were enabled
  and trusted through its config API; the install checker now rejects stale
  trust fingerprints and explicitly disabled slots instead of equating text
  presence with operational liveness.

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

### Native corpus pre-registration

The labels in `prompts/correction_learning/native_corpus_v1.json` were frozen at
commit `2434017` before any classifier replay. The scored population is every
post-pilot exchange from three already-active substantive Codex sessions: nine
cases across three sessions, with two corrections, six non-corrections, and one
ambiguous boundary. Five additional post-pilot one-exchange Claude Code sessions
are native-format negative controls only; they exercise current extraction but
are not represented as human-conversation evidence. The manifest retains home-
relative source locators, timestamps, event IDs, and content-derived hashes, but
no assistant or user prose. Replay must resolve the exact local event hashes and
emit only classifications plus rationale hashes. A passing run advances only to
fresh independent sign-off; it cannot authorize block mode by itself.

**Native result: INVALID FOR DECISION.** The single pre-registered replay at
source revision `ce5dfff` resolved all 14/14 frozen events across eight sessions
and the three calls completed without retry or schema error. However, fresh
sign-off found that the manifest omitted an in-scope event and that its only
claimed post-pilot correction (`cx-brain-01`) actually scored the subsequent
`$audit` command after the assistant had acknowledged an earlier correction.
The `cx-aes-03` negative label is also materially contestable. Consequently the
reported 1/2 recall and false-positive counts cannot diagnose classifier
generalization. `docs/evidence/plan135_native_corpus_signoff.md` records the
rejected sign-off. The classifier remains manual/off as the safety default, not
as an eval-validated decision; this holdout may now inform diagnosis but cannot
be reused as fresh promotion evidence.

**Root-cause repair after invalidation:** Transcript extraction now uses native
message metadata rather than prose heuristics: Codex user records with explicit
content kinds are eligible only when they include `user.text`, and Claude Code
`isMeta` user records are excluded. Native corpus schema 1.1 adds explicit
scored source declarations and rejects any scored population that is incomplete
or overinclusive between the pilot cutoff and freeze time. Prompt version 1.1
also makes the adjacent-turn boundary explicit: an assistant's own admission
does not make the next user command a correction, and process questions without
a clear dispute are ambiguous rather than enforcement-positive. A diagnostic
three-case development probe classified the known correction as correction, the
contested process challenge as ambiguous, and the subsequent `$audit` command
as not-correction under trace
`correction-learning/dev-v2/adjacent-and-process/batch-1` (29.656 seconds, no
retry or error, recorded marginal cost `$0.00`). This is development evidence,
not a fresh holdout or promotion result.

### Native corpus v2 pre-registration

This is a single-system product evidence gate, not a comparative benchmark.
The falsifiable claim is that prompt 1.1 plus typed native-message admission can
identify Brian's corrections in previously unseen authentic adjacent exchanges
with at least 90% recall and no enforcement-positive false positives. Passing
may authorize a reversible native observe-only launch; it cannot authorize Stop
blocking. Failure or invalid evidence retains manual/off and triggers a new
mechanism revision on development data only.

The source sample was frozen in
`docs/evidence/plan135_native_v2_candidates.json` before annotation or replay.
It excludes every v1/development session and covers eight Codex plus eight
Claude Code sessions. Eligible transcript windows run from 2026-09-07 through
the prompt-1.1 commit time. Within each client, transcript paths with at least
four eligible user-authored adjacent exchanges are ordered by SHA-256 of the
fixed seed, client, and home-relative path; the lowest eight are selected, and
a hash-derived contiguous four-exchange window is retained. This yields 64
cases without inspecting their prose during selection.

Two blind annotators independently label every exact adjacent pair using only
information available to the classifier. A third blind adjudicator resolves
disagreements. Agreement and disagreements are reported; model rationales and
conversation prose are not retained in the corpus. If fewer than ten adjudicated
corrections exist, classifier replay is forbidden: selection must be extended
using the next paths in the same deterministic order and all added labels frozen
before replay. Otherwise the one permitted held-out run uses the committed
prompt, typed schema, stripped Sonnet route, six cases per batch, no tools or
setting sources, and a `$0.05` maximum marginal budget.

The initial blind annotations contained only five unanimously labeled
corrections (six from one annotator before adjudication), below the frozen
ten-positive floor. Before any classifier replay, the next eight paths per
client in the same hash order and their hash-derived four-exchange windows were
therefore frozen as
`docs/evidence/plan135_native_v2_extension1_candidates.json`. The original 64
cases remain in the combined population; none were removed or relabeled to meet
the floor.

Blind annotation completed with agreement on 120/128 cases (93.75%); a third
blind annotator adjudicated all eight disagreements. The frozen combined corpus
contains 14 corrections, 113 non-corrections, and one ambiguous boundary across
32 native session windows. `prompts/correction_learning/native_corpus_v2.json`
contains only exact source/event provenance and final labels;
`docs/evidence/plan135_native_v2_annotation_summary.json` retains selection and
annotation hashes. Local provenance replay resolved the exact complete 128/128
population. The corpus and labels are now frozen; no prompt or admission change
is allowed before the single held-out replay.

**Native v2 result: VALID FAIL.** The one frozen replay resolved 128/128 exact
events and completed 22 subscription-backed Sonnet calls with no route/schema
error or retry. It detected 10/14 corrections (71.4% recall), produced one
enforcement-positive false positive across 113 non-corrections, and produced no
enforcement-positive verdict for the one ambiguous boundary. Claude Code recall
was 4/5; Codex recall was 6/9 and contained the false positive. Calls totaled
691.101 seconds of model latency (9.542–80.942 seconds) at recorded marginal
cost `$0.00`. The frozen privacy-reduced result is
`prompts/correction_learning/native_result_v2.json`; traces are under the
legacy-named but unique prefix `correction-learning/native-v1/65f20a8e2c23/`.

The class-level diagnosis separates semantic errors from extraction, which had
already passed exact typed admission and population checks. Misses cluster in
imperative continuation/resumption messages that also correct the prior status
or impose required repairs: the model overweights their task-directive form and
underweights the disputed earlier handling. A shorter factual/name correction
paired with a recurrence-prevention request was also missed. Conversely, terse
clarification or critical questions remain a boundary class: the sole false
positive inferred a correction from a question whose adjudicated label did not
assert prior error, while three other non-corrections became ambiguous. No
prompt, label, threshold, or admission change was made after this result. The
classifier remains manual/off pending fresh adversarial sign-off on that
decision; any future semantic repair must treat v2 as development data and use
a new unseen holdout.

**Native v2 sign-off: REJECTED.** Round one rejected manually expanded,
nonexistent Git revisions and missing annotation/selection reconstruction.
Evidence-only repair made revision, selection, final-label, trace, and diagnosis
checks executable. Round two accepted all of those except historical blind-label
provenance: the privacy-reduced A/B rows were committed after the result, while
the original pre-result files contain rationales the privacy contract forbids
retaining. `docs/evidence/plan135_native_v2_signoff_r1.md` and
`plan135_native_v2_signoff_r2.md` preserve both reviews. Rather than weaken
privacy to rescue the run, v2 is development evidence only. A v3 holdout must
commit privacy-reduced independent labels and adjudications before replay.

### Native corpus v3 pre-registration

Prompt 1.2 and the revision-validating replay harness were frozen at
`29ab33b8bd31e86929518b35f8b98c8a2c51e5f7` before v3 source selection. V3 uses
the next unseen rank window (`16:32`) from the unchanged deterministic v2
source-ranking rule. The eligible universe contained 16 further Codex and nine
further Claude Code session windows, yielding 100 exact cases across 25 native
sessions in `docs/evidence/plan135_native_v3_candidates.json`. No source prose
was inspected during selection and no v1/v2/development session is eligible.

The v2 claim, thresholds, invalid-run rules, six-case batches, model, tools,
budget, and sign-off requirement remain unchanged. Two blind annotators and a
third disagreement adjudicator must emit privacy-reduced event-ID/label records
that are committed before the final corpus and before replay. If fewer than ten
adjudicated corrections are present, the next available Codex ranks must be
frozen and annotated before replay; cases may not be removed after annotation.

V3 annotation produced 91/100 independent agreement and nine blindly
adjudicated disagreements, yielding 17 corrections and 83 non-corrections. The
candidate, both privacy-reduced label sets, and privacy-reduced adjudication were
committed in that order before `native_corpus_v3.json` was assembled. Run
`docs/evidence/plan135_native_v3_annotation_check.py` to recompute the final
labels, and `plan135_native_v2_selection.py` to reproduce the rank-16:32 source
sample. The corpus is frozen; the next permitted action is its one held-out
replay from the exact Git revision containing these bytes.

The primary gates are at least 90% correction recall, zero correction verdicts
among adjudicated non-corrections, and zero correction verdicts among ambiguous
boundaries. Missing/duplicate IDs, provenance mismatch, incomplete source
windows, admission of typed meta/protocol records, route/schema errors, label
leakage, or annotation below the ten-positive floor invalidates the run. Exact
coverage, agreement, subgroup results by client, call latency/cost, prompt and
corpus hashes, and trace IDs are secondary readouts. Any consequential decision
requires fresh adversarial `eval-decision-signoff`.

**Native v3 result: INVALID.** The single replay dispatched 17
subscription-backed Sonnet calls with no route/schema error or retry, but batch
four returned only five verdicts for its six frozen event IDs. The missing ID
was `c76f54d31b2d26e76e9d8753`; no unexpected ID was returned. Because the
pre-run contract makes any missing verdict invalidating, no accuracy metric or
promotion claim is valid. The privacy-reduced invalid-run record reconstructed
from the durable traces is
`prompts/correction_learning/native_result_v3.json`; traces are under
`correction-learning/correction-learning-native-v3/14d8820e9e4f/`.

The harness defect was that it checked the combined ID set only after every
batch, then raised before writing any result. It now validates each batch's
exact event-ID set immediately and atomically preserves a privacy-reduced
invalid result before returning failure. V3 remains development evidence and
must not be retried or scored. A consequential decision still requires a fresh,
precommitted holdout run followed by independent adversarial sign-off.

### Native corpus v4 pre-registration

V4 draws an unseen sample from the disjoint interval 2026-08-31 through
2026-09-06. `plan135_native_v4_selection.py` deterministically ranks eligible
sessions with seed `plan135-native-v4`, selects 16 sessions per client, and
selects one four-exchange window per session without inspecting prose. The
selection implementation and this contract must be committed before the
candidate manifest is generated. The candidate manifest, two independent
privacy-reduced label sets, adjudication of every disagreement, and the final
corpus must then be committed in that order before replay.

Prompt 1.2, the v3 decision thresholds and invalidation rules, exact-source
replay, and independent adversarial sign-off remain unchanged. V4 uses
four-case batches with the per-batch exact-ID guard. The smaller batch bounds
wasted calls after a malformed response; it does not relax any quality gate.
If adjudication yields fewer than ten corrections, an extension selected by a
precommitted deterministic rule is required before replay. V4 permits one
held-out replay only and may not be retried or retuned.

V4 annotation produced 123/128 independent agreement and five blindly
adjudicated disagreements, yielding 29 corrections, 97 non-corrections, and two
ambiguous boundaries. The exact-source loader resolved all 128 frozen events from
32 sessions. Candidate selection, privacy-reduced A/B labels, privacy-reduced
adjudication, and the corpus were committed in the preregistered order before
replay.

**Native v4 result: INVALID.** The one replay completed eight four-case batches,
then the ninth call failed after both permitted `StructuredOutput` attempts
returned a rationale longer than the model-facing schema's 240-character
maximum. The trace contains eight completed calls and one failed call, with no
retry and `$0.00` recorded marginal cost. Completed-call model latency totaled
176.677 seconds (13.580–38.632 seconds). Because route failure is explicitly
invalidating, no accuracy score or promotion claim is valid and v4 may not be
retried. The privacy-reduced reconstructed result is
`prompts/correction_learning/native_result_v4.json`; traces are under
`correction-learning/correction-learning-native-v4/0445e448dc70/`.

The second harness defect was that only verdict-ID mismatches were converted to
durable invalid results; provider, route, and schema exceptions escaped before
artifact creation. Batch execution now wraps every evaluation exception with
its batch index and privacy-safe exception type, then uses the same atomic
invalid-result path. This fixes evidence retention but does not make v4 valid.

Independent sign-off accepted v4's invalidation, sample reconstruction,
privacy-reduced commit ordering, and the manual/off decision. It rejected the
proposal to declare the execution cursor circuit-broken: the cursor records two
failures at the same runtime-integrity boundary against a cap of three. It also
required a mechanism change before any further fresh holdout. The exact v4
trace shows the same unsupported rationale length constraint failed twice; the
turn limit was the terminal symptom, not the root cause. The classifier schema
now keeps rationale non-empty but unbounded because rationale prose is transient
and only its hash crosses the privacy boundary. An authentic development canary
on the contaminated failing batch must pass before another unseen holdout is
selected.

The post-repair development canary replayed only the contaminated four-event v4
batch nine from the exact repair revision. It returned all four required IDs in
one 29.767-second call with no error or retry and `$0.00` recorded marginal
cost. `plan135_native_v4_schema_canary.json` retains only IDs and classifications.
This passes the mechanism-repair boundary but does not score v4 or establish
full-run reliability. A new unseen holdout is now the next permitted evaluation
action.

### Native corpus v5 pre-registration

V5 is the first holdout after the structured-schema repair. It samples the
disjoint, previously uninspected interval 2026-08-24 through 2026-08-30.
`plan135_native_v5_selection.py` deterministically ranks eligible sessions with
seed `plan135-native-v5`, selects 16 sessions per client, and selects one
four-exchange window per session without inspecting prose. This selector and
contract must be committed before candidate generation. Candidate, independent
A/B labels, blind disagreement adjudication, and final corpus must be committed
in that order before replay.

Prompt 1.2, four-case batches, exact-ID and exception invalidation, the v3/v4
quality thresholds, and fresh independent decision sign-off remain unchanged.
Fewer than ten adjudicated corrections requires a precommitted extension. V5
permits one held-out replay only and may not be retried or retuned.

V5 annotation produced 117/128 independent agreement and 11 blindly
adjudicated disagreements. Executable reconstruction yields 34 corrections,
88 non-corrections, and six ambiguous boundaries. The exact-source loader
resolved all 128 events across the 32 frozen sessions. Candidate selection,
privacy-reduced A/B labels, privacy-reduced adjudication, and the final corpus
were committed in the preregistered order before replay.

**Native v5 result: VALID FAIL.** The one frozen replay returned exact verdict
coverage for all 128 events without an invalidating route or schema error. It
detected 24/34 corrections (70.6% recall), produced three enforcement-positive
false positives across 88 adjudicated non-corrections, and produced no
enforcement-positive verdict across six ambiguous boundaries. Codex recall was
12/18 with all three false positives; Claude Code recall was 12/16 with zero
false positives. The result fails both the 90% recall gate and the zero-false-
positive gate, so the classifier remains manual/off. No prompt, labels,
threshold, or admission rule changed after the run. The frozen privacy-reduced
result is `prompts/correction_learning/native_result_v5.json`; a fresh
independent verifier must sign off before any final decision or integration.

Post-result harness review found that successful-run status still required
every prediction to be acceptable even though the preregistered correction
recall threshold is 90%. It also retained a Claude-specific native-format
metric name after controls became client-neutral. Neither defect changes v5's
failure. Future result schema 1.1 now computes the declared 90%-recall,
zero-false-positive, zero-ambiguous-positive, and zero-control-positive gate
directly and uses `native_format_control_false_positives`.

**Native v5 sign-off: ACCEPTED.** Independent verification reproduced source
selection, exact event loading, annotation reconstruction, Git ordering,
privacy boundaries, all 128 predictions, and 32 successful trace calls. The
signed decision rejects the unchanged Prompt 1.2/Sonnet route for promotion,
retains correction learning as manual/off, and stops further holdout spend or
retuning on this route. This is a negative promotion decision, not activation or
proof that the broader correction-learning objective is complete. The signed
artifact is `docs/evidence/plan135_native_v5_signoff.md`.

### Prompt-time attention vertical

The published Codex prompt contract enables a materially earlier intervention
without reviving the rejected classifier. The shared learning hook now accepts
`UserPromptSubmit`, injects a direct instruction to assess the immediately
preceding turn for a correction, and writes a privacy-reduced receipt containing
only hashed session/event identity and timing. The existing Stop disposition
receipt counts those checkpoints so the control can be audited end to end.

This is a compliance aid, not a semantic detector: it proves the agent received
the checkpoint, not that the agent classified the user's meaning correctly.
The Prompt 1.2/Sonnet route remains rejected and block mode remains off. Host
promotion requires generated client wiring plus native Codex and Claude
`UserPromptSubmit` canaries; a later semantic route still needs fresh evidence
against the existing threshold before it can block.

Source evidence at this revision: 40 focused learning/prose-safety tests and
the framework self-test pass. A native-shaped Codex prompt replay emitted the
additional context and a privacy-reduced receipt with no retained prompt prose.
This proves the adapter boundary only; installed-host adoption remains pending.

### 2026-09-14: contest/rebuttal design increment selected (Company Planning)

Brian supplied the human decision this plan's own Reassessment Contract was
waiting on: accept a materially lower per-call precision bar, because a new
design constraint (the blocked agent can contest a verdict rather than being
silently stuck) bounds the cost of a wrong classifier call. This does not
retry the rejected classifier unchanged -- it changes what "good enough"
means for it, by adding a real recourse path.

Selection recorded via Company Planning's `initiative-roadmap` skill:
[`135_correction_learning_gate_roadmap_goal_handoff.json`](135_correction_learning_gate_roadmap_goal_handoff.json)
(`project_id: correction-mode-contest-gate`, `goal_id:
design-contest-rebuttal-loop`). Routed to `bounded-design` for the contest/
rebuttal mechanism's design ambiguity (new receipt status, adjudication flow,
circuit-breaker bound) -- not a fresh classifier-accuracy attempt.

Standard design completed via `bounded-design`:
[`135_correction_learning_gate_contest_design.md`](135_correction_learning_gate_contest_design.md),
result record
[`135_correction_learning_gate_design_packet_result.json`](135_correction_learning_gate_design_packet_result.json).
Real finding that changed the design: the existing block only forces one
retry today (blanket-allows on Stop re-fire regardless of whether the
problem was fixed) -- closing that, not just adding a schema field, is the
actual work. Two concerns left explicitly assigned, not silently decided:
the one-contest-attempt circuit-breaker bound (Brian's disposition) and
whether Claude Code's own Stop-hook re-fire has an independent ceiling
(needs a real test, not an assumption). Slice 1 (schema extension +
deterministic re-fire check, zero LLM cost) is implementation-ready now.
