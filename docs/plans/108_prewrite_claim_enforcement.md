# Plan #108: Low-Friction Pre-Write Claim Enforcement

**Status:** In Progress — PW-01 accepted; PW-02 latency-blocked
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Phase 9"
**goal_ref:** "coordination-integrity"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** linked
**Blocked By:** None
**Blocks:** truthful cross-client write ownership

---

## Gap

**Current:** Claim creation, worktree creation, commits, pushes, and lane
closeout are checked, but a Codex or Claude editing tool can still mutate a
governed repository before the next downstream check. The existing Claude
`gate-edit.sh` enforces required reading, not claim ownership. Codex lifecycle
hooks currently deliver mailbox notices but do not authorize writes.

**Target:** Every supported native agent write in an explicitly opted-in
governed repository is checked before mutation against the exact live session,
repository, worktree, branch, and claimed path. Valid writes proceed quietly;
invalid writes are denied before the file changes and leave a typed audit
receipt.

**Why:** A claim registry is not reliable ownership enforcement if agents can
write first and discover the violation only at commit or push time.

---

## User Outcome

An agent working in a governed repository cannot change a repository file
outside its exact live claimed worktree and path scope, while correctly claimed
writes continue with negligible measured delay.

---

## Canonical Behavioral Example

**Starting input/state:** A DIGIMON linked worktree is governed in enforcement
mode. The active Codex session either has no live claim for that worktree or has
a claim that does not include `digimon/query/runtime.py`.

**Action:** Codex `apply_patch` or Claude `Edit` attempts to change
`digimon/query/runtime.py`.

**Expected observable result:** The native pre-tool hook returns a typed denial,
names the failed ownership invariant and recovery command, records a receipt,
and the target file hash remains unchanged. With an exact healthy claim for the
same session/worktree/branch/path, the same write is allowed.

**Behavioral evidence:** Unobserved

**Substrate/process evidence:** Both-sign adapter fixtures, claim-resolution
tests, hook-wiring tests, latency receipts, and a real positive/negative
worktree probe.

**Failure signal:** Any unclaimed or out-of-scope native edit changes the target
file; any compliant edit is blocked; or the enforcement decision cannot be
stepped down to an exact claim and invariant.

---

## References Reviewed

- `CLAUDE.md` — coordinated worktree and fail-loud policy.
- `docs/plans/107_claim_readiness_and_merge_closeout_enforcement.md` — current
  claim-boundary and merged-lane enforcement.
- `enforced_planning/coordination_claims.py` — canonical claim schema,
  normalization, liveness, path overlap, and readiness bindings.
- `enforced_planning/hook_wiring.py` — current Claude and Codex hook generation.
- `hooks/claude/gate-edit.sh` — current required-reading pre-edit hook.
- `enforced_planning/push_safety.py` — downstream push-time ownership checks.
- `docs/reference/CONFIG_REFERENCE.md` — current opt-in claim/worktree settings.
- `/home/brian/.codex/config.toml` — host currently has lifecycle hooks but no
  pre-write ownership hook (values were not copied into this plan).
- Required memory lookup attempt: `agent-memory recall 'pre-write claim enforcement hooks Codex Claude governed repositories' --project enforced-planning` — unavailable;
  the embedding request failed loudly with provider quota exhaustion on
  2026-07-27.
- [Official Codex hooks reference](https://developers.openai.com/codex/config-advanced#hooks)
  — `PreToolUse` can synchronously deny `apply_patch`; its canonical tool name
  is `apply_patch`, its patch is in `tool_input.command`, and `Edit|Write` are
  supported matcher aliases. The same reference warns that specialized tools
  may opt out, so this remains a native-hook guardrail rather than an OS
  security boundary.

---

## Research Basis For This Slice

No additional external research is required. This extends the repository's
existing claim authority and native hook adapters. Prior native Codex hook
evidence retained under `docs/evidence/` observed roughly 31 ms for one existing
command hook; that supports feasibility but does not prove this gate's latency.

---

## Landscape And Prior Art

This plan extends Plans #31, #32, #74, #105, and #107 rather than introducing a
second ownership system. The native client hook protocols are the enforcement
point; `coordination_claims.py` remains the sole ownership authority.

**Alternatives:** Commit/push-only checks were rejected because they permit
dirty unauthorized state. Mandatory auto-claiming was rejected because it
would silently manufacture authority. OS-level filesystem isolation is stronger
but is outside the cross-client agent-tool boundary and would add substantial
operational friction. The selected design is a small typed policy evaluator
behind native pre-tool adapters, with explicit repository opt-in and measured
observe-to-enforce promotion.

**Project implications:** Hook wiring, governed-repository audit, configuration
documentation, and tests must distinguish `off`, `observe`, and `enforce`.

**Refresh trigger:** A supported client changes its hook payload or blocking
contract, or evidence shows a material write path bypassing native hooks.

---

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|------|------|-----|--------------------|
| Ownership decision | Deductive | Session, repo, worktree, branch, path, and claim invariants are known. | Strict typed contract and both-sign fixtures. |
| Native payload extraction | Hybrid | Supported payload shapes are knowable, but actual client event names and fields must be observed. | Fixture adapters plus retained live payload receipts; unknown writes fail loud in enforce mode. |
| Overhead and false-block rate | Exploratory | Real hook latency and client behavior must be measured. | Observe mode, latency histogram, concrete receipt step-down, then promotion. |

**Exploratory readout:** On deterministic and live representative writes, every
decision is attributable to one exact invariant, compliant writes have zero
false blocks, and local evaluator p95 is under 100 ms and p99 under 200 ms.

**Step-down path:** Every aggregate latency or decision count links to a receipt
containing client, event, session, repository, worktree, branch, normalized
target paths, matched claim source, decision, reason code, and elapsed time.

---

## Boundary And Contracts

### Boundaries

| Boundary | Owns | Must not own |
|---|---|---|
| Native adapter | Parse a supported pre-tool payload into normalized target paths and return the client's allow/deny shape. | Claim policy or implicit path inference from arbitrary shell prose. |
| Claim policy evaluator | Resolve repository identity and exact live claim; evaluate session/worktree/branch/path and health invariants. | Creating, extending, or repairing claims. |
| Receipt store | Append typed decisions and latency locally with bounded retention. | Authorization or hidden fallback. |
| Hook installer/auditor | Preserve unrelated hooks and install the configured mode idempotently. | Enabling hard enforcement in repos that did not opt in. |

### Typed contract

`PreWriteRequestV1` contains schema version, client, hook event, tool name,
session ID, current working directory, and one or more candidate target paths.
The adapter rejects unknown fields at the internal evaluator seam after
normalizing the client payload.

`PreWriteDecisionV1` contains decision (`allow`, `observe_violation`, or
`deny`), mode, reason code, normalized repository/worktree/branch/path identity,
matched claim identity when present, recovery guidance, elapsed milliseconds,
and receipt ID.

The portable configuration is `claims.prewrite_mode` in `meta-process.yaml`
with enum `off | observe | enforce` and default `off`. No environment variable
may silently promote that value. The local append-only receipt path is
`~/.claude/coordination/prewrite-events-v1.jsonl`; records contain hashes and
normalized identities, never patch contents, command contents, or secrets.

The evaluator allows a write only when all of these are true:

1. the repository has explicitly selected `observe` or `enforce`;
2. the session ID is real and equals the live claim session;
3. repository root, linked worktree, and current branch equal the claim;
4. every target is contained by at least one normalized claimed write path;
5. the claim is live, healthy, and has no high-severity enforcement issue.

`off` performs no claim lookup. `observe` records the decision but allows the
tool. `enforce` denies any known write that fails an invariant. Missing or
malformed identity fails loud in `enforce`; it never silently degrades to
observe. Reads are outside the hook matcher and unaffected.

### Cache

Only successful normalized authority snapshots may be cached. The process-safe
cache lives under `~/.claude/coordination/prewrite-cache-v1/`. The key binds
session ID, canonical repo/worktree path, branch, target path set, claim source
path, claim file stat/digest, and mode. Cache entries expire quickly and are
invalidated by any claim-file metadata or branch change. Denials and malformed
requests are not reused across distinct requests. The cache is an optimization,
not an authority.

### Failure, recovery, and rollback

- Missing registry, unreadable claim, malformed payload, unknown supported
  write event, or inconsistent Git identity: typed denial in `enforce`, visible
  observe violation in `observe`.
- Codex `apply_patch` paths are parsed from unified-diff file headers in
  `tool_input.command`; malformed or pathless patches deny in enforce mode.
  Claude `Edit|Write` uses `tool_input.file_path`.
- Shell/`exec_command` calls are not path-authorized in the first slice:
  arbitrary shell mutation is an explicit coverage gap. Deterministically
  recognized file-writing shell operations may be adapted only with both-sign
  fixtures; ordinary test and inspection commands must not be blocked merely
  because they use Bash.
- Rollback is repository mode `enforce -> observe -> off`; it preserves
  receipts and does not alter claims.
- No bypass silently grants authority. Any emergency override must be an
  explicit configured policy action with a reason-bearing receipt; it is not
  part of the first slice.

### Non-goals and non-claims

- Preventing writes by arbitrary local processes, editors, or a root user.
- Automatically creating or widening claims.
- Parsing arbitrary shell commands as natural language.
- Enabling hard enforcement for continuous-light or unregistered repositories.
- Proving all future client tools are covered by today's adapter fixtures.

---

## Capabilities

| Capability | Input Schema | Output Schema | Producer | Consumer(s) | Cost Tier |
|---|---|---|---|---|---|
| `evaluate_prewrite(request)` | `PreWriteRequestV1` | `PreWriteDecisionV1` | `enforced_planning.prewrite_claim_gate` | Codex and Claude pre-tool adapters in governed repositories | free/local |
| `record_prewrite_decision(decision)` | `PreWriteDecisionV1` | `PreWriteReceiptV1` | `enforced_planning.prewrite_claim_gate` | local audit/calibration query and operator diagnostics | free/local |

### Capability Validation

- [ ] Input/output/receipt schemas are strict Pydantic models with described
  fields and rejected unknowns.
- [ ] The CLI is the single adapter boundary; shell hooks do not duplicate
  claim policy.
- [ ] Claude and Codex fixtures validate into the same request contract and
  produce the same decision semantics.
- [ ] No journey notebook is required: this is a synchronous governance hook,
  and its canonical executable surface is the fixture/live-hook probe.

---

## Files Affected

- `enforced_planning/prewrite_claim_gate.py` (create)
- `scripts/prewrite_claim_gate.py` (create)
- `hooks/claude/prewrite-claim-gate.sh` (create)
- `hooks/codex/prewrite-claim-gate.sh` (create)
- `enforced_planning/hook_wiring.py` (modify)
- `enforced_planning/governed_repo_audit.py` (modify)
- `docs/reference/CONFIG_REFERENCE.md` (modify)
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` (modify)
- `tests/test_prewrite_claim_gate.py` (create)
- `tests/test_generate_hook_wiring.py` (modify)
- `tests/test_audit_governed_repo.py` (modify)
- this plan, work graph, plan index, and roadmap

Host configuration or consumer-repository rollout is a separately evidenced
integration action; framework implementation must not edit it implicitly.

---

## Plan

### Critical Path Classification

| Increment | Class | Behavior or named blocker changed |
|---|---|---|
| PW-01 typed evaluator and native adapters | `vertical` | Known native write events receive an attributable pre-write decision. |
| PW-02 observe-mode calibration and installer/auditor | `vertical` | Real client wiring is measurable without blocking work. |
| PW-03 enforce-mode promotion and live negative control | `vertical` | An unauthorized native edit is stopped before mutation. |

### Thin slices

1. **PW-01 — evaluator walking skeleton.** Write failing positive and negative
   fixtures first, then implement the typed evaluator, receipt, Claude adapter,
   Codex adapter, and cache. Demonstrate allow and deny decisions without
   editing host configuration.
2. **PW-02 — observe and measure.** Extend preserving hook generation and audit,
   install only an exact reviewed observe-mode candidate, exercise supported
   native payloads, and retain decision/latency receipts. Stop if payload
   identity is insufficient or the latency/false-block readout misses its bar.
3. **PW-03 — promote one governed repository.** Change only the explicit repo's
   configured mode to enforce, prove an unclaimed/out-of-scope edit leaves the
   file hash unchanged, prove an exact claimed edit succeeds, and retain the
   rollback command and receipts.

The machine-readable units are in
`docs/plans/108_prewrite_claim_enforcement_work_graph.json`.

### PW-01 Evidence

PW-01 is accepted at source revision `f16bc6653cf1031e66da915ac7adc5ba7a1d9cab`.
The retained contract probe is
`docs/evidence/plan108_pw01_contract_probe.json`. It records one real exact-claim
`allow`, one out-of-scope `deny`, exactly two terminal receipts, and the receipt
set digest. The code-diff review was a non-independent second pass; it found and
repaired a missing canonical-`repo_root` comparison, and the original
wrong-repository counterexample now denies.

Verification at the accepted slice:

- `pytest -q tests/test_prewrite_claim_gate.py tests/test_check_coordination_claims.py tests/test_session_cli.py` — 85 passed before the review fix.
- `pytest -q tests/test_prewrite_claim_gate.py` — 13 passed after the review fix.
- Ruff and strict mypy passed on the evaluator, CLI, and tests.
- `python scripts/self_test.py` passed.
- PW-01 licenses `contract_tested` for the local library boundary only. It does
  not license installed, enforced, or deployment-verified status.

### PW-02 Calibration Readout

PW-02 implemented opt-in preserving hook wiring, portable `off | observe |
enforce` configuration, governed-repo audit coverage, and the nested real
`meta-process.yaml` loader repair at revision `24806e8`. The retained readout is
`docs/evidence/plan108_pw02_observe_calibration.json`.

The full fresh-subprocess hook path classified all 50 authorized and 10
violation controls correctly with zero false blocks, but measured p95 796.655 ms
and p99 1051.962 ms. Both exceed the approved p95 <100 ms and p99 <200 ms bars.
Therefore no repository or host configuration was promoted to `enforce`.

#### Dependency Subplan: lower-latency native decision path

**Blocks:** PW-02 acceptance and PW-03 enforcement promotion.

**Current stub:** The typed evaluator, adapters, generator, and audit are
correct but start a fresh Python/Pydantic/Git process for each write.

**Unknowns:** Whether a minimal stdlib fast path with claim-digest validation or
a small long-lived local decision service can meet the latency bar without
creating a second claim authority or silently allowing on service failure.

**Instrument:** Implement the cheapest replaceable candidate behind the same
`PreWriteRequestV1 -> PreWriteDecisionV1` contract, then rerun the identical
50-authorized/10-violation full subprocess calibration.

**Readout:** Zero false blocks, exact receipt step-down, p95 <100 ms, and p99
<200 ms.

**Promotion:** Update the adapter/runtime boundary and PW-02 evidence, mark
PW-02 accepted, then make PW-03 ready.

**Cleanup:** Remove the slower duplicate path or retain it only as a diagnostic
reference; do not keep two policy evaluators.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|---|---|---|
| `tests/test_prewrite_claim_gate.py` | `test_exact_live_claim_allows_write` | Exact session/worktree/branch/path is allowed. |
| same | `test_missing_or_wrong_claim_denied_before_write` | Missing/wrong ownership denies and target hash is unchanged. |
| same | `test_out_of_scope_and_unhealthy_claim_denied` | Path and claim-health invariants fail loud. |
| same | `test_observe_mode_records_but_allows` | Calibration cannot accidentally block. |
| same | `test_malformed_or_unknown_write_payload_fails_loud_in_enforce` | No silent coverage gap. |
| same | `test_cache_is_bound_to_claim_and_branch_identity` | Cached allow cannot survive authority change. |
| `tests/test_generate_hook_wiring.py` | adapter wiring cases | Existing hooks are preserved and generation is idempotent. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| `tests/test_check_coordination_claims.py` | Claim truth remains canonical. |
| `tests/test_session_cli.py` | Session identity and claim refresh remain compatible. |
| `tests/test_generate_hook_wiring.py` | Existing Claude/Codex wiring remains compatible. |
| `tests/test_governed_repo_audit.py` | Governed audit reports configuration truthfully. |

---

## Acceptance Criteria

- [ ] A known unclaimed, wrong-session, wrong-worktree, wrong-branch,
  out-of-scope, stale, or merged-active native write is denied before mutation
  in enforce mode with an exact reason and recovery action.
- [x] An exact healthy claimed write succeeds without extra user interaction.
- [x] Observe mode records the same decision inputs but never blocks.
- [ ] The evaluator's deterministic/local calibration has p95 under 100 ms and
  p99 under 200 ms, and representative compliant native writes have zero false
  blocks before promotion.
- [ ] Receipts step down every aggregate to an exact request, claim, decision,
  and latency without storing file contents or secrets.
- [ ] Hook generation and audit preserve unrelated user/repository hooks and
  are idempotent.
- [ ] Existing claim, session, mailbox, and read-gating tests remain intact.
- [ ] One real positive and one real negative governed-worktree probe prove the
  file changes only on the authorized path.
- [ ] Documentation states the native-agent boundary honestly and does not
  claim OS-level write prevention.

## Stop Conditions

- A native client does not expose session identity and target paths before a
  write: retain observe-only status for that client and record a bounded adapter
  dependency; do not infer authority.
- Local p95 is at least 100 ms, p99 is at least 200 ms, or any compliant write
  is falsely blocked: do not promote enforce mode; use receipts to repair and
  recalibrate.
- A preserving installer cannot prove unrelated hooks remain byte-equivalent in
  meaning: stop before host or consumer write.
- A write class cannot be identified deterministically: expose it as a coverage
  gap rather than advertising full enforcement.
