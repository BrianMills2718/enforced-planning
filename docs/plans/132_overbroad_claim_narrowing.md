# Plan #132: Overbroad Claim Narrowing and False-Serialization Repair

**Status:** Complete
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Phase 9: Fleet Adoption and Framework Maintenance"
**goal_ref:** "claim-granularity-and-safe-narrowing"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Blocked By:** None
**Blocks:** Project Meta wiki/documentation-context dogfood editing under `docs/wiki`

`trace_evaluable: false # deterministic claim-registry and Git-state behavior`

---

## Gap

**Current:** Parent/child write-path overlap correctly blocks concurrent
ownership, but admission treats a broad parent path such as `docs` exactly like
an exact file path. The maintenance entrypoint deliberately bootstraps with `.`
and says the lane must narrow before implementation, yet there is no dedicated
atomic narrowing operation or pre-write enforcement of that transition. An
owner can therefore retain a broad claim indefinitely, and a disjoint child
lane receives only a generic conflict.

**Target:** New broad write claims are explicit and typed. Temporary bootstrap
claims cannot authorize ordinary repository writes until the owner atomically
narrows them. Deliberately bounded broad claims must state why their entire
parent scope is required and remain bounded by the existing claim expiry. A
first-class owner-only narrowing operation replaces the mutation-authority
paths and projection under one registry lock, with rollback on projection
failure and an immediately following append-only audit receipt. Conflict output
distinguishes exact contention from a broad-parent reservation without
weakening either denial.

**Why:** Claims are advance reservations for future writes; current Git diffs
cannot safely override them. The repair belongs in claim declaration and
lifecycle semantics, not in a bypass around `_paths_overlap`.

---

## User Outcome

An agent whose exact files are disjoint from another lane's actual work can ask
that owner to narrow an accidentally broad reservation, observe the atomic
change, and immediately acquire its own claim without risking simultaneous
ownership of the same file.

---

## Canonical Behavioral Example

**Starting input/state:** Lane A owns `docs` but is changing only
`docs/plans/132_...md` and `docs/ops/ACTIVE_PLAN_QUEUE.md`; lane B requests
`docs/wiki/index.md` and `docs/wiki/wiki-system.md`.

**Action:** Lane B's initial claim attempt is denied and classified as an
owner-parent broad reservation. Lane A runs the sanctioned narrow operation
with its exact two paths. Lane B retries the unchanged request.

**Expected observable result:** Lane A's claim and digest-bound pre-write
projection commit the narrower paths as one fail-atomic locked transition; an
append-only mutation receipt then records that committed transition and whether
the projection is current. Lane B is admitted. Replacing Lane A's paths with
any path outside `docs`, or invoking the operation from another session, fails
without changing the claim or projection.

**Behavioral evidence:** Observed in
`docs/evidence/plan132_claim_narrowing.json`: the generated consumer denied the
pre-narrow write, narrowed `.` to `CLAUDE.md`, admitted the unchanged write,
and closed the clean lane through installed entrypoints.

**Substrate/process evidence:** Both-sign claim tests, projection digest checks,
mutation-receipt checks, source/generated parity, and framework self-test.

**Failure signal:** Lane B remains denied after a successful narrow, Lane A can
expand or escape its old paths through the narrow command, a bootstrap-broad
claim authorizes an ordinary write, or parent/child overlap stops blocking.

**Post-completion lifecycle integration (2026-09-02):** The real gate now also
permits a different exact native runtime to terminally reconcile a preserved
`session_ended` linked worktree through `session-close
--reconcile-session-ended`, but only with byte-exact claim/tracker digests and
the existing merge or durable-recovery preflight. This does not weaken Plan
132's ownership rules or transfer write custody; it removes already-finished
ownerless residue that would otherwise prevent a new narrow goal-bound claim.
Verified 2026-09-12: the wrapper also materializes the advertised remote-main
history before terminal cleanup, while the exact claim still owns repository
writes, so a partial clone does not lose the start-revision range when the lane
ref is deleted. An unavailable refresh preserves the explicit `NOT CHECKED`
closeout result.

---

## References Reviewed

- `enforced_planning/coordination_claims.py:441-519` — current normalized claim
  and interaction records.
- `enforced_planning/coordination_claims.py:1726-1734` — intentional
  parent/child overlap rule.
- `enforced_planning/coordination_claims.py:1825-1858` — declared write-path
  overlap and ownership semantics.
- `enforced_planning/coordination_claims.py:2082-2155` — hard-conflict
  evaluation and current interaction payload.
- `enforced_planning/coordination_claims.py:2181-2410` — candidate validation
  and locked claim creation.
- `enforced_planning/coordination_claims.py:2539-2605` — locked heartbeat and
  projection-refresh precedent.
- `enforced_planning/session_lifecycle.py:498-745` — existing-session upsert
  can replace `write_paths`, but it is a broad session operation rather than a
  constrained narrowing contract.
- `enforced_planning/session_lifecycle.py:1657-1775` — heartbeat already polls
  the canonical mailbox.
- `enforced_planning/claim_mutation_receipts.py` — typed append-only mutation
  evidence; no `narrow` operation exists.
- `enforced_planning/prewrite_claim_projection.py` and
  `enforced_planning/prewrite_claim_fast.py` — digest-bound hot-path authority.
- `Makefile` and `templates/Makefile.worktree.block.template` — maintenance
  bootstrap currently claims `.` and promises later narrowing.
- `scripts/install_governed_repo.py` — canonical source-to-consumer lineage.
- `tests/test_check_coordination_claims.py:244-339` — parent/child denial and
  writable-path continuation controls.
- `docs/plans/67_cross_client_mailbox_and_acknowledgement.md` and
  `docs/plans/100_codex_mailbox_lifecycle_delivery.md` — reuse the existing
  message lifecycle; do not create a second coordination channel.
- `docs/plans/110_no_passive_waiting_enforcement.md` — a path-local wait is not
  a whole-goal blocker and idle claims must narrow, hand off, or end.
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` and
  `docs/reference/CONFIG_REFERENCE.md` — current operator and configuration
  authority.
- `project-meta:policy/proposals/2026-08-31-overbroad-claims-require-narrowing.yaml`
  at `b5033793e735acba0d98cd1ff1fb92f810cce49e` — approved planning input;
  proposal remains pending policy rather than active enforcement authority.
- Memory context: `agent-memory recall 'overbroad claims narrow write_paths
  coordination false serialization atomic narrowing' --project
  enforced-planning` — three results, none described this failure; repository
  and live-claim evidence remain primary.

---

## Implementation-readiness audit corrections

An implementation-readiness audit at
`82a9451a318e41b1a642623a774bc3e86d6faf48` traced the public maintenance
bootstrap through `claim_bootstrap.py`, `session_start.py`, the host gate,
`session_target.py`, and `create_worktree.py`; those canonical ingresses were
missing from the v1 work graph. It also reproduced the mixed-version and
receipt-ordering gaps below. The following corrections are part of the adopted
design, not optional follow-up:

1. `claim_bootstrap.py` is the canonical workspace-root ingress and must create
   the typed claim before worktree residue. Direct Make/session creation must
   propagate the same mode, reason, and exact target.
2. Navigation/target identity remains distinct from mutation authority.
   Schema v6 adds `target_worktree_path`. A bootstrap claim retains the real
   target there while its legacy-visible `worktree_path` is a deterministic
  non-Git authority-disabled sentinel. New instruction/read resolution may
   verify `source_file` against the projection's existing `source_sha256`, read
   the exact target from that canonical claim YAML, and accept only the typed
   bootstrap authority-disabled issue for read context. Old or new ordinary
   pre-write readers cannot mistake the bootstrap claim for authority in the
   real worktree. Successful narrowing atomically makes
   `worktree_path == target_worktree_path`.
3. The projection wire contract stays v1 and keeps its exact field set. A new
   generator expresses bootstrap denial through the existing `static_issues`
   list, so an older fast reader of a newer projection also fails closed.
   Downgrade/install checks must reject a prior runtime while any live v6 broad
   claim exists; the authority-disabled worktree binding remains a second
   fail-closed control if an older projection writer runs.
4. Claim YAML and projection replacement form the locked fail-atomic
   transaction. The append-only receipt is necessarily post-commit. Receipt
   persistence failure raises the existing truthful post-mutation audit error
   and may not claim that registry mutation was rolled back.
5. `session-narrow` is a narrowly parsed, native-session-bound host
   coordination command. The host gate admits exactly that grammar so a
   bootstrap claim cannot block its own only recovery operation.
6. The installed proof must cover the complete source/installer manifest
   closure and the public workspace-root bootstrap, deny, narrow, allow, and
   close journey. Project Meta and fleet mutation remain conditional.

---

## Research Basis For This Slice

No external research is needed. This is a reproduced local coordination failure
with an existing canonical owner, exact registry transaction precedent, and an
approved policy-direction proposal.

---

## Landscape And Prior Art

**Alternatives:**

- **Weaken parent/child overlap:** rejected. It permits simultaneous ownership
  of a directory and its descendant.
- **Infer authority from the current Git diff:** rejected as an admission
  source. A diff describes past/current edits, not the owner's authorized future
  writes. Retain it only as advisory conflict evidence.
- **Forbid every directory claim:** rejected. Repository-wide migrations and
  genuinely multi-file bounded work sometimes need a parent reservation.
- **Use session-start as the narrowing command:** rejected as the operator
  seam. It can replace or expand several session fields and does not express the
  subset invariant.
- **Extend the existing claim registry with typed broad modes and an atomic
  narrow operation:** selected. It preserves one authority model, one lock, one
  projection, and one receipt stream.

**Project implications:** Claim schema advances compatibly; source and installed
entrypoints gain one narrow command; maintenance bootstrap becomes structurally
unable to write before narrowing; conflict receipts become more explanatory but
hard-conflict decisions remain unchanged.

**Refresh trigger:** Revisit classification only if an authentic governed repo
cannot distinguish a top-level file from a directory using its declared
`repo_root`, or if the hot-path projection cannot carry bootstrap mode within
the existing latency budget.

---

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|---|---|---|---|
| atomic narrowing | Deductive | subset, owner, lock, claim/projection rollback, and post-commit receipt invariants are exact | specify transaction and both-sign tests first |
| broad-path classification | Deductive with bounded compatibility observation | `repo_root` and existing filesystem type are inspectable; legacy claims lack new metadata | strict rules for new claims; legacy read compatibility and explicit diagnostic |
| conflict explanation | Deductive | parent direction and current worktree diff are inspectable | typed interaction fields; Git diff is advisory only |
| Project Meta rollout | Conditional | exact source revision does not exist until source acceptance | disposable consumer first; target-repo graph and rollout only after source merge |

**Exploratory readout:** None. If classification encounters an unresolved
single-component missing path, fail as `broad_scope_ambiguous` rather than guess.

**Step-down path:** Every broad/conflict result names the normalized declared
path pair, which side is the ancestor, the owner claim/session, broad mode, and
the concrete changed paths observed from Git when available.

---

## Design Contract

### Claim schema v6

Add three optional fields to `ClaimRecord` and persisted YAML:

| Field | Type | Rule |
|---|---|---|
| `broad_scope_mode` | `bootstrap | bounded | null` | Required on every new write-owning claim containing a broad path; forbidden when no broad path remains. |
| `broad_scope_reason` | non-empty string or null | Required exactly when `broad_scope_mode` is present. |
| `target_worktree_path` | absolute path or null | Required for bootstrap claims and equal to the intended exact session target. For ordinary/bounded claims it is null or equal to `worktree_path`. |

A path is broad when it is `.` or resolves, under the claim's declared
`repo_root`, to an existing top-level directory. New write-owning claims require
`repo_root`; an absent root or an unresolved single-component path fails loud as
ambiguous rather than being treated as narrow. Existing schema v1-v5 claims
remain readable and retain their current authority; status/conflict surfaces
label broad legacy records `legacy_unclassified` until they narrow or perform a
material upsert.

No new numeric timeout is invented. `bootstrap` has the structural deadline
`before_first_repo_write`; `bounded` uses the claim's existing `expires_at` as
its terminal deadline. Heartbeat does not silently extend claim expiry.

### Broad-mode rules

- `bootstrap` permits claim/worktree/session construction and sanctioned claim
  mutation only. It stores the real target in `target_worktree_path` and an
  authority-disabled non-Git sentinel in legacy-visible `worktree_path`.
  Session instruction/read resolution verifies and reads the target field from
  the projection-digest-bound source claim; the projection wire shape remains
  unchanged. Pre-write authority remains bound to `worktree_path` and therefore
  denies ordinary repository writes until a successful narrow makes the two
  paths equal.
- `bounded` authorizes the declared broad parent until existing expiry and
  makes that deliberate reservation visible in conflicts.
- New broad claims without both fields fail before claim or worktree residue.
- Narrow claims with either field fail as stale/contradictory metadata.
- Maintenance worktree creation supplies the canonical bootstrap reason; all
  other broad use is explicit at its calling boundary.

### Atomic narrow operation

`narrow_claim(agent, project, scope, session_id, write_paths)` runs under the
existing registry lock and:

1. resolves exactly one live claim owned by the native session;
2. normalizes and deduplicates a non-empty replacement set;
3. requires every replacement path to be equal to or beneath at least one old
   path and requires at least one strict reduction;
4. re-evaluates live conflicts from the same locked registry snapshot;
5. clears broad metadata when no broad path remains, otherwise requires the
   retained paths to satisfy the existing declared mode;
6. for bootstrap mode, verifies the target Git identity and replaces the
   authority-disabled `worktree_path` with `target_worktree_path`;
7. replaces claim YAML and refreshes the digest-bound projection as one
   rollback-capable locked transition;
8. appends one `operation: narrow` receipt to the version-isolated
   `claim-narrow-events-v1.jsonl` ledger for the committed transition; the
   existing shared claim-mutation v1 ledger and its closed operation enum stay
   byte-contract compatible with older readers. A narrow-receipt failure
   reports post-commit audit failure rather than pretending the claim mutation
   did not occur;
9. returns old/new paths, cleared/retained broad mode, projection digest, and
   mailbox observation summary.

Any failed guard or projection refresh leaves claim bytes and projection bytes
unchanged. Receipt failure occurs after a successful commit and is reported
with the existing applied-state audit-error semantics. General
session upsert remains capable of legitimate expansion, but must apply the same
broad-mode admission rules; it cannot masquerade as the narrow operation.

### Operator boundary

Add `scripts/session_narrow.py`, `make session-narrow`, and installed
`scripts/meta/session_narrow.py`. Inputs are the existing exact branch/scope and
`SESSION_WRITE_PATHS`; native session identity is mandatory. Conflict output
classifies overlap as `exact`, `candidate_parent`, or `owner_parent`. An
`owner_parent` interaction whose owner path is broad is rendered as an
`overbroad_reservation` or `deliberate_bounded_reservation`, names the owner-only
narrow command, and retains hard denial.

When the owner's worktree is readable, one interactive conflict probe may show
whether current changed paths are disjoint. That field is advisory, explicitly
`true | false | unknown`, and never changes severity. Mailbox coordination
reuses the existing request/observe/acknowledge path; Plan 132 adds an
integration fixture proving the next owner heartbeat observes a narrowing
request rather than adding another message store.

### Compatibility and rollback

- Schema v1-v5 claims load unchanged; no eager registry rewrite or migration.
- Every schema-version gate in the existing outcome-admission/session-activation
  path accepts v6 with the same authority semantics as v5; unsupported future
  versions still fail closed. A v6 claim must never become unusable merely
  because it is waiting for its tracker attachment.
- Narrow new claims serialize as v6 without broad fields.
- Projection schema 1.0 and its exact claim field set remain unchanged;
  bootstrap denial uses the existing `static_issues` list. Older fast readers
  therefore fail closed when consuming a projection produced by v6 code.
- A live v6 bootstrap claim keeps its legacy-visible `worktree_path` detached
  from the real target, so an older projection writer cannot promote it to
  ordinary worktree authority merely by ignoring unknown fields.
- Source implementation and disposable installed consumer land before any real
  Project Meta installation.
- Narrow receipts never enter the older shared mutation ledger, so installing
  a pre-v6 reader cannot make historical shared receipts unreadable.
- Downgrade/reinstall to a pre-v6 runtime fails while any live v6 broad claim
  exists. After narrowing or closing those claims, rollback is the source
  commit revert plus reinstall of the prior accepted version; v6 narrow claims
  retain v5-compatible authority semantics.

---

## Capabilities

| Capability | Input Schema | Output Schema | Producer | Consumer(s) | Cost Tier |
|---|---|---|---|---|---|
| `classify_broad_write_paths` | repo root + normalized paths | broad paths + reason codes | `coordination_claims` | claim creation/upsert, projection, conflict renderer | free |
| `narrow_claim` | exact owner/session + replacement paths | atomic mutation result | `coordination_claims` | session lifecycle and CLI | free |
| `session-narrow` | branch/scope + `SESSION_WRITE_PATHS` | human or JSON receipt | source/installed CLI | Codex, Claude Code, operators | free |

### Capability Validation

- [x] Claim schema v6 round-trips through source and installed readers.
- [x] New broad claims require typed mode/reason while legacy claims remain readable.
- [x] Narrowing enforces owner, exact session, subset, strict reduction, and no-change-on-denial.
- [x] Projection and mutation receipts bind the same post-narrow registry digest.
- [x] An installed consumer uses the canonical source seam; no parallel claim model appears.

## Capability Adoption

**Disposition: extend.** Extend the existing claim/session/projection/receipt
seam. Do not add another lock, registry, lease, mailbox, or policy store.

---

## Multi-Repo Coordination

| Repo | Files Modified | Merge Strategy |
|---|---|---|
| `enforced-planning` | source runtime, CLI, Make template, installer, tests, operator docs, Plan 132 evidence | Implement and merge first. |
| disposable installed consumer | generated/copied claim runtime and Make entrypoint | Recreated from the candidate source revision; never canonical. |
| `project-meta` | installed claim runtime/entrypoint plus focused dogfood receipt | Conditional after source acceptance; use a target-owned work graph bound to accepted Enforced Planning Plan 132. |

**Coordination notes:** The source slice does not claim or mutate Project Meta.
Project Meta rollout begins only after an immutable accepted source revision and
must use the cross-repository plan-authority contract from Plan 130.

**Write-claim footprint:** The ready source unit owns only the Enforced Planning
paths listed in its work graph. A later Project Meta unit owns its installed
copies and dogfood evidence in a separate target repository claim.

---

## Epistemic Planning Frontier

| Area | State | Current contract | Trigger or stopping rule | Downstream update |
|---|---|---|---|---|
| schema/classifier/narrow transaction | fully_specifiable_now | existing lock, normalized paths, projection and receipts | focused both-sign tests pass | claim runtime and operator docs |
| maintenance bootstrap enforcement | fully_specifiable_now | current `.` bootstrap promise is unenforced | first-write denial then narrow/admit replay passes | Make source/template and pre-write projection |
| conflict diagnostics | fully_specifiable_now | exact pair and owner worktree are available or honestly unknown | advisory diff never changes denial | CLI/JSON interaction contract |
| disposable install | fully_specifiable_now | installer owns copied surfaces | clean generated consumer replay passes | installer parity evidence |
| Project Meta rollout | conditional | requires accepted source revision and target-owned graph | source unit accepted and installed replay green | Project Meta graph/claim and dogfood receipt |
| fleet enforcement | deliberately_deferred | no representative fleet calibration exists | explicit later rollout decision after Project Meta | separate rollout plan |

---

## Reassessment Contract

- **Triggers:** narrowing requires a second registry/lock, current-diff evidence
  would affect authority, schema v1-v5 cannot remain readable, or the pre-write
  hot path needs a Git subprocess.
- **Autonomous action:** keep authority declaration-based, move Git diff only to
  interactive diagnostics, and preserve the one-lock mutation transaction.
- **Plan revision required:** change broad-path classification, add a numeric
  deadline, allow narrowing to expand paths, or combine source implementation
  with real Project Meta mutation.
- **Human decision required:** weaken parent/child exclusion, automatically
  revoke another live owner's claim, or enable fleet-wide hard enforcement.
- **Stopping rule:** source both-sign tests, framework self-test, disposable
  installed deny -> narrow -> admit replay, and one bounded hot-path timing
  comparison pass; no broad fleet suite or rollout is required.

---

## Files Affected

- `enforced_planning/coordination_claims.py`
- `enforced_planning/claim_mutation_receipts.py`
- `enforced_planning/claim_bootstrap.py`
- `enforced_planning/session_lifecycle.py`
- `enforced_planning/session_target.py`
- `enforced_planning/prewrite_claim_projection.py`
- `enforced_planning/prewrite_claim_fast.py`
- `scripts/session_narrow.py` (create)
- `scripts/session_start.py`
- `scripts/check_coordination_claims.py`
- `scripts/prewrite_claim_gate.py`
- `scripts/worktree-coordination/create_worktree.py`
- `Makefile`
- `templates/Makefile.worktree.block.template`
- `scripts/install_governed_repo.py`
- `scripts/relationships.yaml`
- `tests/test_check_coordination_claims.py`
- `tests/test_claim_mutation_receipts.py`
- `tests/test_claim_bootstrap.py`
- `tests/test_session_lifecycle.py`
- `tests/test_session_cli.py`
- `tests/test_session_target.py`
- `tests/test_prewrite_claim_fast.py`
- `tests/test_prewrite_claim_projection.py`
- `tests/test_host_prewrite_claim_gate.py`
- `tests/test_create_worktree.py`
- `tests/test_makefile_worktree_targets.py`
- `tests/test_source_makefile.py`
- `tests/test_install_governed_repo.py`
- `CLAUDE.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/reference/CONFIG_REFERENCE.md`
- `GETTING_STARTED.md`
- `docs/plans/125_planning_integrity_loop.md`
- `docs/evidence/plan132_claim_narrowing.json` (create)
- `docs/plans/132_overbroad_claim_narrowing.md`
- `docs/plans/132_overbroad_claim_narrowing_work_graph.json`
- `docs/plans/CLAUDE.md`
- `ROADMAP.md`

---

## Plan

### Critical Path Classification

**Critical-path classification: vertical.** The implementation is complete only
when the public deny -> narrow -> admit journey works through a generated
consumer; schema and command substrate alone are not completion.

| Increment | Class | Behavior or named blocker changed |
|---|---|---|
| schema v6 + atomic narrow + exact conflict classification | `vertical` | an owner can safely narrow and a disjoint waiting lane can retry successfully |
| bootstrap broad-mode pre-write denial and Make/installer propagation | `direct_blocker` | maintenance entrypoint's existing “must narrow” promise becomes true |
| disposable installed replay and source closeout | `vertical` | a real generated consumer exercises deny -> narrow -> admit |
| Project Meta rollout | `conditional` | wiki dogfood proceeds only after accepted source revision and target graph |

### Risk-Ordered Thin Slices

1. **CN132-01 — Source atomic narrowing vertical (`fully_specifiable_now`).** Add
   schema v6 compatibility, broad classification, owner-only `narrow_claim`,
   mutation receipt, interaction classification, CLI/Make seam, and focused
   temporary-registry replay. This is one implementation unit because the lock,
   claim bytes, projection rollback, post-commit receipt, and command must be
   verified as one public lifecycle.
2. **CN132-02 — Bootstrap and installed-consumer integration
   (`fully_specifiable_now`, same unit/batch).** Carry broad mode through the
   unchanged v1 projection wire shape, deny bootstrap-broad ordinary writes,
   preserve target-versus-mutation-authority separation, update the canonical Make
   template and installer, and replay the canonical example in a disposable
   installed repo. Batch any directly observed parity repairs before rerunning
   the fixed-cost installed proof.
3. **CN132-03 — Project Meta dogfood rollout (`conditional`).** After the source
   unit is accepted, create a target-owned graph bound to the exact Plan 132
   digest, install only the claim-narrowing lineage, and replay the original
   `docs` versus `docs/wiki` scenario. This slice is not claimable from this
   source graph and does not authorize Project Meta mutation.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|---|---|---|
| `tests/test_check_coordination_claims.py` | `test_new_broad_claim_requires_mode_and_reason` | broad admission fails before residue without typed intent |
| same | `test_atomic_narrow_replaces_subset_and_refreshes_projection` | one-lock claim/projection transition |
| same | `test_atomic_narrow_rejects_escape_expansion_and_foreign_session_without_change` | both-sign ownership and subset invariants |
| same | `test_narrow_projection_failure_restores_exact_claim_and_projection_bytes` | fail-atomic rollback on derived-state failure |
| same | `test_broad_classifier_handles_root_file_missing_component_and_symlink_escape` | root-bound classification cannot guess or escape |
| same | `test_bounded_broad_claim_remains_authorized_without_heartbeat_expiry_extension` | deliberate broad authority and terminal lease stay truthful |
| same | `test_parent_child_conflict_classifies_owner_parent_without_weakening_denial` | explanatory receipt retains hard conflict |
| same | `test_legacy_broad_claim_remains_readable_and_is_diagnostic` | compatibility without silent promotion |
| `tests/test_claim_mutation_receipts.py` | `test_narrow_mutation_receipt_binds_post_change_projection` | append-only audit provenance |
| same | `test_narrow_receipt_failure_reports_applied_projection_current` | post-commit audit failure never claims rollback |
| `tests/test_prewrite_claim_fast.py` | `test_bootstrap_broad_claim_denies_repo_write_until_narrowed` | structural first-write deadline |
| `tests/test_prewrite_claim_projection.py` | `test_bootstrap_uses_v1_static_issue_without_projection_shape_drift` | old-reader/new-projection compatibility |
| `tests/test_session_target.py` | `test_bootstrap_target_resolves_for_context_without_mutation_authority` | navigation target remains distinct from mutation binding |
| `tests/test_session_cli.py` | `test_session_narrow_json_deny_narrow_admit_journey` | public operator journey and failure output |
| `tests/test_outcome_admission.py` | `test_selection_pending_accepts_schema_v6_without_weakening_binding_guards` | the new claim schema remains activatable while later unknown versions fail closed |
| `tests/test_session_lifecycle.py` | `test_heartbeat_observes_narrowing_request_without_extending_expiry` | existing mailbox and lease semantics are reused |
| `tests/test_claim_bootstrap.py` | `test_workspace_bootstrap_creates_authority_disabled_target_then_requires_narrow` | canonical JSON bootstrap has no residue on failure and no pre-narrow write authority |
| `tests/test_host_prewrite_claim_gate.py` | `test_native_session_narrow_command_is_exactly_parsed_and_self_recovery_admissible` | only the native bounded recovery grammar bypasses ordinary write admission |
| `tests/test_create_worktree.py` | `test_bootstrap_claim_validates_exact_target_without_granting_worktree_authority` | worktree construction honors the separated target |
| `tests/test_makefile_worktree_targets.py` | `test_maintenance_worktree_propagates_bootstrap_mode_reason_and_target` | Make ingress matches the canonical transaction |
| `tests/test_source_makefile.py` | `test_session_narrow_target_and_arguments_are_canonical` | source target is present and shell-safe |
| `tests/test_install_governed_repo.py` | `test_installed_consumer_includes_narrowing_runtime_and_make_target` | source/generated lineage |
| same | `test_downgrade_rejected_while_live_v6_broad_claim_exists` | rollback cannot silently promote bootstrap authority |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| parent/child and writable-continuation tests in `test_check_coordination_claims.py` | true overlap must still deny |
| claim locking/projection tests | transaction and hot-path authority remain coherent |
| session lifecycle and CLI focused suites | owner/session behavior remains compatible |
| installer focused suite and `scripts/self_test.py` | portable lineage stays truthful |

---

## Acceptance Criteria

- [x] The canonical `docs` -> exact paths narrowing example produces deny ->
  atomic narrow -> admit with no interval of duplicate ownership.
- [x] New broad claims require mode/reason; `bootstrap` cannot authorize an
  ordinary repository write and `bounded` remains limited by existing expiry.
- [x] Narrowing is owner/session bound, strictly subset-only, fail-atomic, and
  commits claim plus projection with rollback; its post-commit receipt
  truthfully reports the applied state even if audit persistence fails.
- [x] Bootstrap instruction/read context resolves the exact target worktree
  while both old and new pre-write readers lack mutation authority until
  successful narrowing.
- [x] Parent/child overlap remains a hard conflict; advisory Git-diff evidence
  never changes admission.
- [x] Existing schema v1-v5 claims remain readable and honestly diagnostic.
- [x] The source and installed command/Make/runtime surfaces are byte-lineage
  consistent and a disposable installed consumer passes the canonical journey.
- [x] Project Meta and fleet rollout remain excluded until their explicit
  source-revision and target-graph gates are satisfied.

---

## Concerns and Failure Modes

| Failure mode | Containment |
|---|---|
| broad classifier mistakes a root file for a directory | require declared repo root and inspect existing filesystem type; fail ambiguous missing paths |
| “narrow” expands into a sibling | subset relation checked under the registry lock before any write |
| projection refresh fails after claim replacement | restore the exact prior claim and projection bytes before releasing the registry lock; inject failure in tests |
| audit receipt append fails after commit | raise the existing post-mutation audit error with `applied_projection_current`; never report not-applied or silently rollback committed authority |
| an old reader or projection writer sees a v6 bootstrap claim | keep projection v1, add an existing-format static issue, and keep legacy-visible `worktree_path` authority-disabled until narrow |
| bootstrap mode blocks its own remediation | treat the sanctioned claim-mutation CLI as host coordination, not a repository write |
| diff looks disjoint and is treated as permission | advisory field cannot influence `severity` or admission result |
| implementation duplicates mailbox machinery | reuse heartbeat polling and existing message status contracts |
| source works but installed copies drift | installer manifest/parity test plus disposable generated consumer |
| broad hard enforcement reaches fleet prematurely | source and disposable consumer only; Project Meta and fleet are explicit later gates |

---

## Non-Claims

- This plan does not eliminate legitimate waiting on a deliberately broad live
  migration claim.
- It does not infer an owner's future writes from Git status.
- It does not automatically revoke, steal, expire, or rewrite another session's
  claim.
- It does not implement Project Meta rollout or fleet enforcement.
- A passing fixture proves claim lifecycle behavior at the tested revision; it
  does not prove every repository has installed that revision.

## Post-Plan Lifecycle Compatibility Note (2026-09-01)

The source/installed CLI lineage now also carries the bounded
`--reconcile-canonical-root` closeout mode for legacy `session_ended` claims
whose recorded worktree is the canonical checkout. That maintenance path is
not broad claim authority: it requires exact claim/tracker digests and a clean
main-worktree identity, archives only coordination metadata, and retains the
filesystem and branch. Focused lifecycle controls prove the removal helpers are
never invoked for this case.

The same source/installed lifecycle lineage now includes two bounded closeout
and transfer controls without changing Plan 132 claim authority. A merged child
claim may be terminalized only when its exact live parent retains the same
repository, worktree, and branch; the parent then closes normally. A
cross-session Codex resume must fence one exact predecessor PID whose session,
start-tick generation, Codex executable, and current worktree match the
transferring claim. Fence state binds the exact pre-transfer claim digest, and
the immutable process-fence receipt is then bound into the custody-transfer
receipt before reporting success. Installer import-closure tests execute the installed
`session_resume.py` adapter with source `PYTHONPATH` removed.

Last verified 2026-09-13 against Plan 110's NPW-03 lifecycle extension. The
new blocker-disposition application path reuses the same canonical registry
lock, projection writer, exact-native-owner guard, and installed manifest
closure. Its root-plus-descendants handoff/session-end operation does not widen
or bypass Plan 132 narrowing authority, and its negative fixture preserves an
unrelated root plus dirty worktree bytes.

## Post-Plan Target-Repository Closeout Note (2026-09-30)

The source and installed `session_close.py` entrypoints accept `--repo-root`
for callers managing a lane in another repository. The `session-close` Make
target passes `WORKTREE_REPO_ROOT`; closeout now uses that target for advertised
`origin/main` refresh, merge-base calculation, and shared-ref range reporting.
The regression coverage is in
`tests/test_session_close_lock_reconcile.py`, including an independent Git
consumer repository fixture.
