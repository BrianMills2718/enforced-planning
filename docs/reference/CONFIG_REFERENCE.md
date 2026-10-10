# Configuration Reference — meta-process.yaml

Status: active

Complete table of every key in `meta-process.yaml`, which script reads it, and
the default behavior when absent.

**Live starter source of truth:** `templates/meta-process.yaml.example`

Consumer-facing quickstarts intentionally show only keys with script effect
today. The template also carries planned/advisory vocabulary, which is labeled
below when it is not yet enforced.

`templates/meta-process.yaml.example` is the minimal functional starter
surface. `templates/meta-process.future.yaml.example` carries broader reserved
or advisory vocabulary for repos that want to document future policy without
pretending it is mechanically enforced today.

---

## Governance Defaults: Opt-Out Model

As of this version, the framework defaults to **governance enabled** (opt-out):

- **`governance.enabled: true`** — master switch, defaulting to true when absent.
  Set false for disposable experimentation. This forces governed controls and
  derived-wiki checks effectively off without deleting installed files or
  rewriting configured modes; setting true restores those modes.
- **`knowledge_navigation.enabled: true`** — deterministic derived navigation is
  available by default. `knowledge_navigation.freshness_mode` accepts
  `off | observe | enforce` and defaults to `observe`. Generated pages are
  navigation, never authority.

- **`claims.enabled: true`** — Coordination claims tracked by default. To disable
  for a specific repository, set to `false`.
  Completed-claim maintenance accepts `--agent`, `--project`, and `--scope`
  together with `--prune-completed`; the script adapter forwards those exact
  selectors to the canonical package implementation and never broadens them.
- **`plans.integrity.mode: enforce`** — Structural plan integrity enforced by
  default. To disable, set to `off`.

These controls are enabled by default because the framework assumes repositories
benefit from coordinated planning and claim tracking. Repositories that do not
need coordination can explicitly opt-out by setting these values to their
disabled states (`false` and `off` respectively).

### Deprecation Path for Opt-In Configs

Legacy configurations that relied on opt-in (enabled only when explicitly set)
are deprecated:

| Old Pattern | New Pattern | Migration |
|---|---|---|
| `claims.enabled: false` (opt-in) | `claims.enabled: true` (opt-out) | Set to `false` to disable |
| `plans.integrity.mode: off` (opt-in) | `plans.integrity.mode: enforce` (opt-out) | Set to `off` to disable |

Existing repositories with old-style opt-in configs will continue to work with
explicitly disabled settings, but new installations ship with governance enabled
by default.

---

## plans

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `plans.enabled` | bool | `true` | `check_plan_tests.py`, `check_plan_blockers.py` | Plans enforced |
| `plans.require_tests` | bool | `true` | `check_plan_tests.py` | Tests required |
| `plans.require_references_reviewed` | bool | `true` | Not enforced by script | No effect |
| `plans.trivial_threshold_lines` | int | `20` | **Not read by any script** 📋 | Reference only; Pattern 15 uses this as the canonical threshold definition |
| `plans.trivial_block_src` | bool | `true` | **Not read by any script** 📋 | No effect |
| `plans.plans_dir` | string | `"docs/plans"` | `check_plan_tests.py` (CLI arg), `complete_plan.py` (CLI arg) | `docs/plans` |
| `plans.integrity.mode` | enum `off \| observe \| enforce` | `enforce` | plan validator, plan-start readiness, canonical plan-bound claim binding | Structural plan admission enforced; to disable set to `off` |
| `plans.integrity.contract_version` | string | `"1.0.0"` | plan validator and admission boundaries | `1.0.0`; an explicitly unsupported version fails structurally |
| `plans.method_conformance.mode` | enum `off \| required` | `off` | `resolve_method_conformance_binding` in `enforced_planning/coordination_claims.py` via canonical plan-bound claim binding and plan-start readiness | With `required`, every plan-backed write claim must name the plan's passing Company Planning method-conformance receipt (`--method-receipt`, `--method-receipt-sha256`); see `docs/reference/METHOD_CONFORMANCE_BINDING.md` |
| `plans.integrity.minimum_plan_number` | positive int | `1` | plan validator and admission boundaries | Plans below the floor are `not_applicable`; plans at/above it use the configured mode |

Planning Integrity 1.0.0 validates exact Git-object plan/config bytes when a
lane or plan-bound claim starts. It requires an authored user outcome,
four-field canonical example, explicit critical-path and capability-adoption
declarations, a classified epistemic-frontier table, and a reassessment
contract. Duplicate YAML keys, placeholders, ambiguous numeric plan files, and
unreadable or unsupported inputs fail visibly. `--warn-only` can downgrade
legacy documentation-coupling gaps, but never an `enforce` integrity failure.

A structural `PASS` means the declared Planning Integrity fields conform. It
does not establish that the author named every material area or selected an
optimal plan; the typed result and downstream AES projection retain that
non-claim verbatim.

For a qualified plan owned by another repository, Plan #130 reads that plan
and its integrity configuration from an explicit plan-authority root/revision;
the work graph and execution start remain in the target repository. The
invocation inputs `PLAN_REPO_ROOT` / `PLAN_START_POINT` (CLI
`--plan-repo-root` / `--plan-start-point`) are **not configuration keys** and
do not enable discovery or change either repository's enforcement mode.
Even when the authority's structural integrity mode is `off`, the claim must
bind exactly one committed plan and its digest. See the operator guide's
cross-repository plan-authority contract for the complete invocation rules.

## claims

### Registry read implementation

Claim YAML uses the provisioned compiled safe parser with a safe Python
fallback; malformed input preserves the original diagnostic text. This is an
implementation choice and adds no configuration key. The registry writer's
five-second contention limit and the hook repair's 1.5-second limit remain.
A completed repair artifact may be used after a transport timeout only when
its typed snapshot is current and bound to the exact registry. Recovery is
recorded separately in the existing daily hook receipt, including that same
snapshot's digest; it cannot imply a successful child exit.

### Trace review admission

`meta_process.trace_review.mode` accepts `off`, `observe`, or `enforce`. If
absent, a Company Planning active cursor selects `enforce`; otherwise coverage
is explicitly uncovered. Enforcement requires `trace_review.command` to pin
`/usr/bin/python3` and one canonical installed Company Planning
`scripts/validate_trace_review.py`, whose manifest version matches its cache
directory. No latest-version fallback is allowed.
If no local command is configured, the adapter reuses AES's existing
machine-owned `~/.config/aes/trace-review.json` command pin. It validates the
same installed identity; this supplies a provider, not an enrollment claim.

An installed native pre-write adapter invokes admission for ordinary writes
independently of `claims.prewrite_mode`, using the actual target worktree and
native session. Read-only diagnosis and narrowly validated retention commands
remain available. Cross-worktree shell writes cannot borrow the selected
worktree's review. Completion passes the exact requested plan path and refuses
an unrelated cursor's review. Missing providers or invalid target bindings
fail closed in enforce mode. A configuration file alone does not install a
hook or establish project coverage; both clients must exercise the boundary.
The final trace denial controls the exit status even when outcome admission
allowed the request. Disabled targets retain an explicit uncovered disposition
in both the host decision and its receipt.
The host records its combined claim and trace decision once, before optional
outcome correlation. Direct component calls still record their own receipts;
only the enclosing host defers that component write.
An explicit shell working directory determines trace admission even when claim
checking is disabled. Enforced admission refuses an unprovable shell destination.
Relative shell targets resolve against the captured native launch directory,
which remains separate from the claimed worktree selected during admission.

### Host read-target state

Workspace-root clients may select one session-bound repository for instruction
context without a claim. State lives under
`~/.claude/coordination/read-targets-v1/`; it is not a `meta-process.yaml`
setting and prewrite admission ignores it. See the operator guide for semantics.

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `claims.enabled` | bool | `true` | `audit_governed_repo.py` (mechanical worktree opt-in requirement) | Coordination claims enabled; to disable set to `false` |
| `claims.enforce_exclusivity` | bool | `true` | Not enforced by script | No effect |
| `claims.require_for_worktree` | bool | `false` | `audit_governed_repo.py` (mechanical sanctioned-entrypoint expectation) | Audit does not expect sanctioned entrypoints unless another worktree signal requires them |
| `claims.prewrite_mode` | enum `off \| observe \| enforce` | `off` | native pre-write adapters, hook generator, governed-repo audit | No pre-write wiring or lookup; `observe` records without blocking; `enforce` denies unauthorized supported native writes |
| `claims.outcome_admission_mode` | enum `off \| enforce_selected` | `off` | session start/heartbeat and native pre-write adapter | `off`; malformed configured values fail visibly instead of degrading to off |
| `claims.enforce_in_ci` | bool | `false` | Not enforced by script | No effect |
| `claims.claims_file` | string | `.claude/active-work.yaml` | Not enforced by script | No effect |

No key here configures the malformed-claim-file diagnostic (a `.yaml` claim
that fails to parse is always warned about and always surfaced via
`malformed_claim_files()`/`--list --json`, unconditionally, same as the
existing `unregistered_claim_files` wrong-extension surface) -- see the
operator guide's "A claim file with invalid YAML does not silently vanish".

Session lifecycle note: sanctioned session bootstrap and heartbeat do **not**
require tool-specific config keys in `meta-process.yaml`. Codex and Claude Code
resolve runtime identity through their adapters and populate the same claim and
tracker contract.

Cross-client recovery is also a fixed lifecycle contract rather than a config
key. `session-resume --successor-agent` may transfer only an explicit `handoff`
or `session_ended` claim: both prove the predecessor runtime is quiescent. Live
and stale-heartbeat claims retain the fenced transfer path.

Claim-registry writer contention is also not configurable. Mutations acquire
`~/.claude/coordination/.claims.lock` for at most five seconds by default. If
the lock remains owned, `ClaimRegistryLockTimeout` reports the lock path,
confirms that no claim state changed, and directs the caller to retry after the
current writer releases it. The lock file's age is not ownership evidence;
inspect the live `flock` holder rather than deleting the file.

An unused claimed lane remains active when its branch tip is exactly its retained
`start_revision`, even if an unrelated default-branch commit makes that tip an
ancestor of the current default. This is lifecycle identity, not a configurable
policy: no task work exists to close. Both claim-health implementations compare
the lane tip with its retained start revision before classifying it as merged.

Pre-write enforcement is explicit and staged. Use `observe` first and retain
latency/decision receipts. Promote to `enforce` only after representative
compliant edits have zero false blocks and the approved latency bar passes.
Promotion also requires every sanctioned claim-mutating client to refresh the
digest-bound projection; a legacy writer can otherwise make the projection
stale, which is visible in `observe` and correctly denied in `enforce`.
The current adapters cover Claude `Edit|Write` and Codex `apply_patch`; they do
not provide OS-level protection or infer arbitrary shell write targets.
Provably read-only Bash is classified before repository or claim admission.
Every component of a compound command or pipeline must be in the bounded read
grammar; this includes safe `date`, `git ls-remote`, GitHub CLI query, and `jq`
forms. Clock-setting, upload-pack overrides, GitHub mutations, redirection,
substitution, and unbounded interpreter commands remain claim-required.
Claim-classification JSON serializes typed session-activity timestamps as
ISO-8601 strings or `null`, so admitted read-only `jq` pipelines never receive
Python datetime objects.

### Host repository-authority provider

Workspace-root mutation bootstrap uses a host-level provider configuration at
`~/.config/enforced-planning/repository-authority-provider-v1.json`; it is not a
`meta-process.yaml` key. The strict v1 object contains only:

```json
{"schema_version":"1.0","provider_path":"/absolute/executable","provider_sha256":"<64 lowercase hex>"}
```

The config and executable must not be group/world writable, and the executable
must match the pinned digest. Invalid configuration or an unbound provider
response fails closed before lane creation. Provider policy belongs outside the
portable framework; see the operator guide for the runtime contract.

The host pre-write adapter also admits the canonical runtime mailbox CLI without
a repository claim only when its command is uncomposed, has no root or claims
override, carries one strict inline JSON request, and the request's caller and
sender match the ambient native session. The mailbox itself still resolves the
recipient against the claims registry and fails closed on invalid authority.

The adapter does not bind a runtime to its launch repository or to a singleton
claim. A session may own claims in multiple repositories; an absolute file
target or one supported literal Bash `-C <worktree>` target selects the matching
healthy claim. Relative mutation with multiple possible claims remains denied
as ambiguous.
For the literal `env`, `/bin/env`, or `/usr/bin/env` wrapper, only the final `-C` or `--chdir`
directory selects claim and trace-review authority. A relative final directory
resolves from the command's launch directory; earlier directory options do not
change that base.
An early payload or projection error cannot waive independently enforced
trace review, even when ordinary claim enforcement is `off` or `observe`.

`outcome_admission_mode: enforce_selected` is a separate, stricter source
continuation gate. It requires ordinary `prewrite_mode: enforce`, derives the
exact selected outcome from the claim-linked tracker, and records admission
before session renewal, heartbeat mutation, or supported native write success.
It cannot be disabled by omitting a CLI flag or by passing a weaker ordinary
mode. A new lane must enter through `make outcome-bootstrap`, whose complete
claim is restricted to one uniquely identified Plan's plan, graph, allocation
fixtures, index, and roadmap. This mode is enabled only in the Enforced
Planning source repository as of Plan #123; the installer does not configure or
activate it in downstream repositories. The public bootstrap resolves the
remote-default revision once and passes it into session activation, so the new
claim and tracker retain exact `start_revision` custody before the claim can be
bound to a selected work unit. Existing tracked claims without that evidence
remain legacy records and are not backfilled.

## worktrees

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `worktrees.enabled` | bool | `false` | `audit_governed_repo.py`; `warn-worktree-cwd.sh`, `block-cd-worktree.sh` (via `check-hook-enabled.sh`) | Audit requires sanctioned worktree entrypoints and scripts only when explicitly enabled |
| `worktrees.protect_main` | bool | `false` | `check-hook-enabled.sh` | Main-checkout protection is opt-in |
| `worktrees.worktree_dir` | string | `"../worktrees"` | Not enforced by script | No effect |
| `worktrees.safe_remove_only` | bool | `true` | Not enforced by script | No effect |

### Tracker lock location (environment, not config)

| Variable | Default | Read By | Why it exists |
|----------|---------|---------|---------------|
| `ENFORCED_PLANNING_LOCK_DIR` | `$XDG_RUNTIME_DIR/enforced-planning/tracker-locks`, falling back to `~/.cache/...` | `session_contracts.tracker_lock_path` | The session-tracker mutation lock is deliberately **not** a sibling of the tracker file. A lock beside a tracker inside a canonical checkout that a live claim has made read-only cannot be created, so the lane can never be closed. Locks are process coordination, not repository content. |

The lock file is named for the sha256 of the resolved tracker path, so two
trackers never share one and every worktree asking about the same tracker
computes the same lock. Derive it with `session_contracts.tracker_lock_path`;
never construct the path by hand, or a reader and a writer can disagree about
where the lock is and silently stop serialising.

## artifact_creation

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `artifact_creation.mode` | enum `off \| observe \| enforce` | `off` | native artifact-creation hooks, staged candidate check, hook generator | No artifact-creation hook is installed and no new-file decision is recorded |
| `artifact_creation.policy_file` | path | `scripts/artifact_directory_policy.yaml` | `scripts/artifact_creation.py` | Uses the default repository-owned directory policy path |
| `artifact_creation.registry_file` | path | `scripts/relationships.yaml` | `scripts/artifact_creation.py` | Uses the existing relationship/intent registry |

Artifact creation is a ratchet, not a legacy-corpus rewrite. A repository first
selects bounded `controlled_globs` in its directory policy and runs `observe`.
For a controlled new path, the registry entry must exist before file creation
and must declare its concern, authority role, owner, separate-file need,
lifecycle, discoverability, and retirement behavior. `enforce` denies missing
or invalid intent, duplicate canonical concern ownership, disallowed directory
classes, generator-free generated output, and invalid temporary quarantine
records. Existing-file edits are outside this gate.

The native hooks and staged candidate check append content-free local receipts
to `~/.claude/coordination/artifact-creation-events-v1.jsonl`. Use
`python scripts/artifact_creation.py report` to inspect decisions, reason codes,
frequent paths, latency, and linked feedback. Use the `feedback` subcommand to
bind a friction or recommendation record to an exact receipt, then use
`resolve-feedback` to append a `resolved`, `accepted_risk`, or `superseded`
disposition without rewriting history. Neither feedback nor observe-mode
findings change policy automatically.

Tests and isolated probes may set `ARTIFACT_CREATION_RECEIPT_PATH` to redirect
content-free receipts. This variable cannot change the configured enforcement
mode or policy inputs.

Repositories that do not use the read-gating stack can install only this
boundary with `scripts/generate_hook_wiring.py --profile artifact-creation`.
That profile requires the relationship registry and an explicit non-`off`
mode; it does not install mailbox or read-context hooks.

Operational note: when `worktrees.enabled` is true and the sanctioned Makefile
block is installed, governed repos are expected to expose `session-start`,
`session-heartbeat`, `session-status`, and `session-finish` alongside the
worktree targets. Claim-runtime schema v6 also requires `session-narrow`; a
generated consumer that lacks that entrypoint is not compatible with typed
bootstrap broad claims.

Claim-runtime installer profiles also carry
`scripts/meta/apply_blocker_disposition.py` plus
`enforced_planning/blocker_policy.py`. This is a fixed lifecycle contract, not
a configuration switch: it re-evaluates the current canonical claim and graph
snapshot under the registry lock, records an immutable disposition-application
receipt, and limits any handoff/session-end mutation to the named root and its
descendants. Unrelated roots remain live.

`make maintenance-worktree` serializes its bounded inputs into the typed
`maintenance_worktree` claim-bootstrap operation; Make does not independently
create or roll back the claim, worktree, or tracker. Omitted
`SESSION_WRITE_PATHS` creates the temporary repository-wide `.` bootstrap claim
and supplies its typed broad-scope mode, reason, and target worktree. An
explicit nonempty `SESSION_WRITE_PATHS` value is already narrow authority: the
entrypoint forwards those exact paths and the typed operation omits bootstrap
metadata. Generated consumers use the synchronized
`scripts/meta/claim_bootstrap.py` wrapper; host admission accepts the Make target
only when the rendered worktree block and installed wrapper/module digests match
the canonical runtime.

The typed maintenance request's `new_files` field is a transaction contract,
not a configuration switch. It can create at most 16 explicitly declared new
top-level files in the linked worktree, narrows before returning, and persists
the declaration in the claim so health checks remain deterministic while the
canonical checkout does not yet contain those files.

`session-status` is the sole Python-backed lifecycle command classified as
claimless read-only. The classifier accepts only the fixed installed script,
its declared query arguments, and an optional absolute `/usr/bin/env -C`
worktree binding. This is a command contract rather than a configuration knob;
it does not admit generic Python or change `claims.prewrite_mode`.

## commits

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `commits.require_prefix` | bool | `false` | `hooks/git/commit-msg` | Prefix not required |
| `commits.valid_prefixes` | list | `["\\[Plan #\\d+\\]", "\\[Goal [a-z0-9][a-z0-9._:-]*\\]", "\\[Trivial\\]", "\\[Unplanned\\]"]` | `hooks/git/commit-msg` | Framework defaults |

## planning

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `planning.question_driven_planning` | enum | `"advisory"` | **Not read by any script** 📋 | No effect |
| `planning.uncertainty_tracking` | enum | `"advisory"` | **Not read by any script** 📋 | Authoring-only legacy guidance; live structural uncertainty admission is `plans.integrity` |
| `planning.dependency_probe_policy` | enum | `"strict"` | **Not read by any script** 📋 | No effect |

## capability_ownership

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `capability_ownership.enabled` | bool | `false` | **Not read by any script** 📋 | No effect |
| `capability_ownership.*` | various | — | **Not read by any script** 📋 | No effect |

## quality

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `quality.doc_coupling.enabled` | bool | `false` | the coupling checker when explicitly installed or invoked | Doc coupling is opt-in |
| `ENFORCED_PLANNING_HOOK_MODE` | `off \| warn \| block` | `warn` | `hooks/git/pre-commit` | Findings remain visible but do not block; an immutable terminal-verification freeze still blocks |
| `quality.hook_modes.<check name>` | `off \| warn \| block` | unset | `hooks/git/pre-commit` | That check follows `ENFORCED_PLANNING_HOOK_MODE` |
| `quality.doc_coupling.config_file` | string | `"scripts/relationships.yaml"` | `check_doc_coupling.py` | `scripts/relationships.yaml` |
| `quality.mock_policy.enabled` | bool | `true` | Not enforced by script | No effect |
| `quality.mock_policy.require_mock_ok_comment` | bool | `true` | Not enforced by script | No effect |
| `quality.adr_governance.enabled` | bool | `true` | Not enforced by script | No effect |
| `quality.dead_code.enabled` | bool | `false` | `check_dead_code.py` | Dead code not checked |
| `quality.dead_code.strict` | bool | `false` | `check_dead_code.py` | Warn only |
| `quality.dead_code.min_confidence` | int | `80` | `check_dead_code.py` | 80% confidence threshold |
| `quality.dead_code.paths` | list | `[]` | `check_dead_code.py` | Project root |
| `quality.dead_code.whitelist` | string | `".vulture_whitelist.py"` | `check_dead_code.py` | `.vulture_whitelist.py` |
| `quality.dead_code.audit_file` | string | `"dead_code_audit.json"` | `check_dead_code.py`, `audit_dead_code.py`, `validate_dead_code_audit.py` | `dead_code_audit.json` |
| `quality.type_checking.enabled` | bool | `true` | Not enforced by script | No effect |
| `quality.type_checking.strict` | bool | `true` | Not enforced by script | No effect |
| `quality.reachability.enabled` | bool | `false` | `check_reachability.py` | Reachability reports "disabled in meta-process.yaml" |
| `quality.reachability.packages` | list | `[]` | `check_reachability.py`, `repo_stats_block.py` (package-root fallback) | Config error (no packages configured) |
| `quality.reachability.entrypoints` | list | `[]` | `check_reachability.py` | No files treated as entrypoints |
| `quality.reachability.product_entrypoints` | list | `[]` | `check_reachability.py` | Product-path share not computed (falls back to the full reachable set); when set, `--check` also fails if `product_share` regresses against the baseline |
| `quality.reachability.dynamic` | list | `[]` | `check_reachability.py` | No `importlib`-string-imported modules treated as reachable |
| `quality.reachability.ignore` | list | `[]` | `check_reachability.py` | No modules excluded from the corpus |
| `quality.reachability.baseline` | string | `"reachability_baseline.json"` | `check_reachability.py` | `reachability_baseline.json` |
| `product_share` (baseline key, not a config key) | float | absent | `check_reachability.py` | Written by `--write-baseline`. When present, `--check` fails on a regression below it; when absent, the product-path ratchet stays silent so baselines predating the key keep passing |
| `REACHABILITY_RATCHET` | `on \| off` | `on` (env var, not a config key) | `hooks/git/pre-commit` | Ratchet enforced; `off` is a named, logged bypass for the first tuning pass on a repo (see `ACCRETION_DETECTOR_ROLLOUT_BRIEF.md` §10a in `project-meta`) |


### `quality.hook_modes` — making one check blocking

`ENFORCED_PLANNING_HOOK_MODE` is global: every pre-commit check warns, or every
one blocks. That is the wrong granularity when checks differ in whether they
can run at all.

Measured in this repository on 2026-08-24: the doc-coupling check correctly
detected a staged change to `enforced_planning/coordination_claims.py` whose
coupled operator guide was untouched, printed the exact documents to update,
and exited 1 — and the commit landed, because the mode was `warn`. It could not
be switched to `block`, because the dead-code check needs `vulture`, which is
not installed, so a global `block` would have refused every commit in the repo.
**One unavailable check was holding every working check advisory.**

`quality.hook_modes` declares the mode for individual checks, keyed by the check
name the hook prints:

```yaml
quality:
  hook_modes:
    "doc-coupling check": block
```

Anything not listed follows the global mode. A check listed here is blocking
even when the global mode is `warn`, and the failure message says so, naming the
config rather than the environment variable — the escape hatch belongs where the
block happens.

A run in which any check warned now reports `Pre-commit checks completed with N
warned (not passed)` and names them, rather than `Pre-commit checks passed!`. A
summary that says everything passed when a check failed is the thing that let
this drift go unnoticed.

## acceptance_gates

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `acceptance_gates.enabled` | bool | `false` | Not enforced by script | No effect |
| `acceptance_gates.*` | various | — | Not enforced by script | No effect |

## messaging

The canonical mailbox is enabled when installed and derives its storage root
from the canonical claims directory (`../messages-v1`). It has no independent
identity or enablement registry. Message TTL and acknowledgement disposition
are typed request fields. Legacy `messaging.enabled`, `messaging.require_ack`,
and `messaging.inbox_dir` values are ignored compatibility residue; the legacy
Markdown inbox is not an authority.

## ci

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `ci.allow_disable_file` | bool | `true` | CI workflow templates | Disable file honored |
| `ci.jobs.*` | bool | `true` | CI workflow templates | Jobs enabled |
| `ci.change_detection` | bool | `true` | CI workflow templates | Change detection on |

---

## Legend

- **✅ Functional** — actively read by at least one script/hook
- **📋 Planned** — key exists but no script reads it; setting has no effect
- **Not enforced** — key is parsed but behavior isn't implemented end-to-end
