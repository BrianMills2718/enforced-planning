---
schema_version: "1.0"
artifact_type: design_plan
id: registry-lock-busy-holder
status: proposed
method_conformance_receipt: docs/plans/registry-lock-busy-holder.receipt.json
trace_review_criteria:
  - criterion_id: outcome
    expected_outcome: pass
goal:
  outcome: "When the claim registry lock is busy, claim_registry_lock waits a bounded time while naming who holds it, and on timeout raises ClaimRegistryLockTimeout carrying the holder and a structured busy result with state_changed false; the lock is never forced or deleted."
  canonical_example: "A second writer contending with holder pid 1234 gets ClaimRegistryLockTimeout whose message names pid 1234 and 'no claim state changed', and whose to_dict() is {status: busy, state_changed: false, holder: {pid: 1234, ...}}; if the holder releases during the wait, the waiter acquires and proceeds."
  forbidden_substitutes: "claiming success from a check's last line or exit status alone; a change outside the listed files; a commit without the saved check output"
  boundaries: "only enforced_planning/coordination_claims.py and tests/test_check_coordination_claims.py plus this plan's records; the flock stays the only authority; nothing forces, unlinks or truncates another writer's lock; no irreversible action and no spend"
  done_when: "pytest tests/test_check_coordination_claims.py -k registry_lock, saved with its full output on the parent commit and the change commit in docs/plans/registry-lock-busy-holder.check.txt, shows the contention test asserting the holder pid, 'no claim state changed' and the to_dict busy result, a release-mid-wait test succeeding, and the env-override cap test passing; the full tests/test_check_coordination_claims.py passes on the change commit."
  do_not_gate_on: "Brian's review of the plan page; adoption by downstream installed repos"
---

# Busy claim-registry lock names its holder and waits observably

## Actor and result

**Actor:** Brian, through the feedback loop's weekly fix-owner run, on behalf of every agent that runs a claim lifecycle command (session-close, maintenance-worktree, claim create/narrow/heartbeat).

**Request (verbatim):** Feedback loop (fix owner run for Brian) 2026-10-12, AES issue #413: "Make registry-backed lifecycle operations return a structured busy result with the actual writer and provide a bounded observable release-and-retry path while preserving the no-state-change guarantee and never forcing or deleting the lock."

**Desired result:** When the claim registry lock is busy, `claim_registry_lock` waits a bounded, environment-overridable (hard-capped) time while printing one stderr line every few seconds naming the holder, and on timeout raises `ClaimRegistryLockTimeout` with `lock_path`, `waited_seconds`, `holder` (pid, alive, command, session id, acquired_at, held seconds) and a `to_dict()` busy result `{"status":"busy","state_changed":false,...}`.

**Stable example:** a second writer contending with holder pid 1234 gets `ClaimRegistryLockTimeout` whose message names pid 1234 and "no claim state changed", and whose `to_dict()` is `{"status":"busy","state_changed":false,"holder":{"pid":1234,...}}`; if the holder releases during the wait, the waiter acquires and proceeds.

## Requirements

| Id | Requirement | Source | Check | Status |
| --- | --- | --- | --- | --- |
| R1 | On timeout the error names the actual holder (pid, command, session) and exposes a structured busy result with `state_changed: false`. | asked (AES #413) | `test_registry_lock_contention_returns_bounded_retry_and_then_succeeds` asserts the pid in the message and the `to_dict()` fields; output in `docs/plans/registry-lock-busy-holder.check.txt` | planned, not yet run |
| R2 | Bounded observable release-and-retry: the waiter keeps retrying within the bound, reports the holder while waiting, and succeeds when the holder releases mid-wait. | asked (AES #413) | new test `test_registry_lock_waiter_succeeds_when_holder_releases_mid_wait` | planned, not yet run |
| R3 | The bound is overridable by `CLAIM_REGISTRY_LOCK_TIMEOUT_SECONDS` but capped. | implied by "bounded" | new test `test_registry_lock_timeout_env_override_is_capped` | planned, not yet run |
| R4 | No claim state changes on timeout, and the lock file is never forced, unlinked or truncated by a waiter. | asked ("preserving the no-state-change guarantee and never forcing or deleting the lock") | contention test asserts the claims dir was not created; the holder record is written only by the lock owner after acquiring | planned, not yet run |
| R5 | Existing callers that catch `ClaimRegistryLockTimeout` / `TimeoutError` keep working. | implied (shared lock) | the class stays a `TimeoutError` subclass; full `tests/test_check_coordination_claims.py` passes | planned, not yet run |

## Success and disproof

**Success evidence:** `pytest tests/test_check_coordination_claims.py -k registry_lock`: the contention test asserts the timeout message names the holder pid and "no claim state changed", that `to_dict()` reports `status` busy, `state_changed` false and the holder pid, and that the claims dir was not created; the release-mid-wait test asserts the waiter acquires after the holder releases inside the bound; the cap test asserts an oversized env value is clamped. Then the full test file passes.

**Disproof:** the timeout error does not name the holding pid or lacks the structured busy result, or a waiter fails even though the holder released within the wait, or any existing claim-lock test fails.

**Trace review:** two runs of the success check are judged from their full output: one on the parent commit before the change (it must fail, proving the check detects the defect) and one on the change commit (the success run). No model, agent or LLM pipeline runs under this plan. The trace is the check's complete output with the exact command and exit status, saved as `docs/plans/registry-lock-busy-holder.check.txt` and committed with the change, each run headed by its commit. What must be seen beyond the final result: each named test appears with its result and none is skipped, the exit status matches, and the before run fails on the holder/to_dict assertions rather than on an unrelated error.

## When a run fails or surprises us

This procedure is separate from the anticipated failure named in the disproof. For any run that fails or surprises us: preserve the failed run and its trace id (the run is the pytest check; its trace id is the commit sha plus the saved output section heading in `docs/plans/registry-lock-busy-holder.check.txt`, and the failed output is kept, never overwritten). Before selecting a fix, read the full inputs (the test file and the changed source at that commit), the prompts (none: no model runs), each tool call's arguments and results (the exact pytest command line and every test's reported result and traceback), the intermediate stages (each failing assertion's compared values and any captured stderr, including the holder lines the waiter printed) and the final output (summary line and exit status). Cite the observed divergence and classify it as evidence absent, evidence returned but unused or contradicted, invalid expectation, or unresolved. An unresolved diagnosis permits only further investigation and cannot authorize a causal repair. A targeted repair is linked to a new traced verification run saved alongside, while the original failure is retained. Every failing or surprising item and a sample of passes is reviewed; review completeness is judged separately from the run verdict. Criterion `outcome` covers the entire success check.

## System model

**System model:** `docs/model/ODD.md`, a file in this repository describing this repository only (not a shared model), reachable from the documentation entry point `wiki/index.md`, which links it.

**Model elements this change adds, changes or relies on, and what the saved check output must show of each:**

- none -- docs/model/ODD.md scopes the model to the repository inventory and docstring wiki and states claims are out of scope; this change alters claim-lock contention reporting only, adds no stored field and no view

**Views, freshness and reconciliation:** the applicable view is the requirement-to-verification link in the Requirements table; no other view applies because the change adds, changes or relies on no modelled entity, process, record, event or view. Freshness: the model's drift tests (`tests/test_relationship_context.py`, `tests/test_docstring_wiki.py`) run in `make check` before merge. If a modelled element were touched it would be reconciled in the same commit; otherwise the model needs no update because no element changes meaning.

## Capability reuse

Checked against the capability catalogue in agentic-capability-architecture-canonical (`reuse_candidates.yml` and `capability_registry.yml`):

- No catalogue entry fits, because this changes the contention reporting of an existing repository-local lock (`claim_registry_lock`) rather than adding a cross-project capability; the work needs edits to this repository's own source, which no catalogue entry provides.

## Authority and non-goals

**Authority:** Brian, via the feedback loop's fix-owner run, in his own repository; one agent makes the change under the claimed maintenance lane `registry-lock-busy-holder`.

**Non-goals:** no lock stealing, forcing, unlinking or stale-lock breaking; no change to which operations take the lock; no change to CLI exit codes or output formats of lifecycle commands; no installer propagation to downstream repos in this plan.

## Irreversible actions and spend

None proposed. The change is code plus tests in one repository, reverted by `git revert` of the merge commit; it spends nothing.

## Uncertainties

| Material uncertainty | Owner or resolving evidence |
| --- | --- |
| Whether writing a holder record into the lock file can confuse a concurrent waiter reading it mid-write | Resolved by design: the waiter treats an unparseable record as `holder: unknown` and keeps waiting; the record is advisory, the flock is the authority; covered by the contention test |
| Whether the longer default wait (30 s) slows any test or hook path | Resolved by evidence: tests pass explicit `timeout_seconds`; the full test file timing in the saved check output shows no regression |
| Whether the change needs files beyond the two listed | Resolved before commit: `git diff --stat` in the worktree must list only the two source files plus this plan's records |

## Activation facts

- `shared_mechanism`: true -- the registry lock is used by session lifecycle, outcome portfolio and integration authority, and this adds a busy-result contract to it.
- `empirical_comparison_proposed`: false -- no alternatives are compared; the success check verifies the one change.
- `llm_central`: false -- the change makes no model call.
- `irreversible_or_spend_action`: false -- reverted by `git revert`, spends nothing.
- `claims_external_standard`: false -- conforms only to this repository's own contracts.
- `aes_governed_target`: false -- this repository has no `.aes/target.yaml`.

## Prior art and ownership

Searched internal ownership and lineage (`grep -rn` for holder/lock-holder records, `fcntl.flock` and `ClaimRegistryLockTimeout` across `enforced_planning/` and `scripts/`, plus the earlier deferral design on AES #413) and external prior art (git's `index.lock` failure message naming the lock and telling the user another process may be running; `flock(1)` with `-w` bounded waits; pidfile conventions that write the holder pid into the lock file, as systemd and many daemons do; and the "steal stale lock" option of tools like `lockfile-progs`). Each candidate's disposition:

- `claim_registry_lock` in `enforced_planning/coordination_claims.py` (the single internal owner of the registry lock; no other holder-record mechanism exists): **extend** in place.
- Pidfile holder record and `flock -w` bounded wait: **compose** as an advisory holder record written by the owner next to the kernel flock, which remains the authority.
- git `index.lock` style message: **reuse** its pattern of naming the lock path and the likely holder in the error.
- Stale-lock stealing (`lockfile-progs`-style forced break): **bounded exception** -- deliberately not adopted, because the request forbids forcing or deleting the lock; the flock is released by the kernel when the holder process exits, so no stealing is needed.
- A separate holder registry file: **bounded exception** -- not adopted, because it would be a parallel mechanism to the lock file itself.

**Parallel-implementation check:** `grep -rn "fcntl.flock" enforced_planning scripts` must show the registry lock only in `claim_registry_lock`; a second flock on the claims lock path would be a silent parallel implementation.

## Vertical and reset

One vertical over `enforced_planning/coordination_claims.py` and `tests/test_check_coordination_claims.py` (plus the saved check output `docs/plans/registry-lock-busy-holder.check.txt`). It is done when the success check above holds. Make the change, run the success check before and after it, commit, run `make check`, merge. Reset: `git revert` of the merge commit. Not pursued: anything outside these files. No work-unit graph, review contract or release ceremony.
