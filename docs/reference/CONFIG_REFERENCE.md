# Configuration Reference — meta-process.yaml

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

## plans

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `plans.enabled` | bool | `true` | `check_plan_tests.py`, `check_plan_blockers.py` | Plans enforced |
| `plans.require_tests` | bool | `true` | `check_plan_tests.py` | Tests required |
| `plans.require_references_reviewed` | bool | `true` | Not enforced by script | No effect |
| `plans.trivial_threshold_lines` | int | `20` | **Not read by any script** 📋 | Reference only; Pattern 15 uses this as the canonical threshold definition |
| `plans.trivial_block_src` | bool | `true` | **Not read by any script** 📋 | No effect |
| `plans.plans_dir` | string | `"docs/plans"` | `check_plan_tests.py` (CLI arg), `complete_plan.py` (CLI arg) | `docs/plans` |

## claims

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `claims.enabled` | bool | `false` | `audit_governed_repo.py` (mechanical worktree opt-in requirement) | Audit treats missing flag as not opted in |
| `claims.enforce_exclusivity` | bool | `true` | Not enforced by script | No effect |
| `claims.require_for_worktree` | bool | `false` | `audit_governed_repo.py` (mechanical sanctioned-entrypoint expectation) | Audit does not expect sanctioned entrypoints unless another worktree signal requires them |
| `claims.prewrite_mode` | enum `off \| observe \| enforce` | `off` | native pre-write adapters, hook generator, governed-repo audit | No pre-write wiring or lookup; `observe` records without blocking; `enforce` denies unauthorized supported native writes |
| `claims.enforce_in_ci` | bool | `false` | Not enforced by script | No effect |
| `claims.claims_file` | string | `.claude/active-work.yaml` | Not enforced by script | No effect |

Session lifecycle note: sanctioned session bootstrap and heartbeat do **not**
require tool-specific config keys in `meta-process.yaml`. Codex and Claude Code
resolve runtime identity through their adapters and populate the same claim and
tracker contract.

Pre-write enforcement is explicit and staged. Use `observe` first and retain
latency/decision receipts. Promote to `enforce` only after representative
compliant edits have zero false blocks and the approved latency bar passes.
Promotion also requires every sanctioned claim-mutating client to refresh the
digest-bound projection; a legacy writer can otherwise make the projection
stale, which is visible in `observe` and correctly denied in `enforce`.
The current adapters cover Claude `Edit|Write` and Codex `apply_patch`; they do
not provide OS-level protection or infer arbitrary shell write targets.

## worktrees

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `worktrees.enabled` | bool | `false` | `audit_governed_repo.py`; `warn-worktree-cwd.sh`, `block-cd-worktree.sh` (via `check-hook-enabled.sh`) | Audit requires sanctioned worktree entrypoints and scripts only when explicitly enabled |
| `worktrees.protect_main` | bool | `false` | `check-hook-enabled.sh` | Main-checkout protection is opt-in |
| `worktrees.worktree_dir` | string | `"../worktrees"` | Not enforced by script | No effect |
| `worktrees.safe_remove_only` | bool | `true` | Not enforced by script | No effect |

Operational note: when `worktrees.enabled` is true and the sanctioned Makefile
block is installed, governed repos are expected to expose `session-start`,
`session-heartbeat`, `session-status`, and `session-finish` alongside the
worktree targets.

## commits

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `commits.require_prefix` | bool | `false` | `hooks/git/commit-msg` | Prefix not required |
| `commits.valid_prefixes` | list | `["\\[Plan #\\d+\\]", "\\[Trivial\\]", "\\[Unplanned\\]"]` | `hooks/git/commit-msg` | Framework defaults |

## planning

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `planning.question_driven_planning` | enum | `"advisory"` | **Not read by any script** 📋 | No effect |
| `planning.uncertainty_tracking` | enum | `"advisory"` | **Not read by any script** 📋 | No effect |
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
