# Configuration Reference — meta-process.yaml

Complete table of every key in `meta-process.yaml`, which script reads it, and
the default behavior when absent.

**Source of truth:** `templates/meta-process.yaml.example`

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
| `claims.enabled` | bool | `true` | `audit_governed_repo.py` (advisory worktree opt-in audit) | Audit treats missing flag as not opted in |
| `claims.enforce_exclusivity` | bool | `true` | Not enforced by script | No effect |
| `claims.require_for_worktree` | bool | `true` | `audit_governed_repo.py` (advisory sanctioned-entrypoint expectation) | Audit does not expect sanctioned entrypoints unless another worktree signal requires them |
| `claims.enforce_in_ci` | bool | `false` | Not enforced by script | No effect |
| `claims.claims_file` | string | `.claude/active-work.yaml` | Not enforced by script | No effect |

## worktrees

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `worktrees.enabled` | bool | `true` | `audit_governed_repo.py`; `warn-worktree-cwd.sh`, `block-cd-worktree.sh` (via `check-hook-enabled.sh`) | Audit treats repo as not opted in unless other worktree signals require entrypoints; hooks stay active when installed |
| `worktrees.protect_main` | bool | `true` | `check-hook-enabled.sh` | Hook active |
| `worktrees.worktree_dir` | string | `"../worktrees"` | Not enforced by script | No effect |
| `worktrees.safe_remove_only` | bool | `true` | Not enforced by script | No effect |

## commits

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `commits.require_prefix` | bool | `true` | `hooks/git/commit-msg` | Prefix required |
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
| `quality.doc_coupling.enabled` | bool | `true` | `hooks/git/pre-commit` (check #3) | Doc coupling checked |
| `quality.doc_coupling.strict` | bool | `true` | Not read (hardcoded block) | Block |
| `quality.doc_coupling.config_file` | string | `"scripts/relationships.yaml"` | `check_doc_coupling.py` | `scripts/relationships.yaml` |
| `quality.mock_policy.enabled` | bool | `true` | Not enforced by script | No effect |
| `quality.mock_policy.require_mock_ok_comment` | bool | `true` | Not enforced by script | No effect |
| `quality.adr_governance.enabled` | bool | `true` | Not enforced by script | No effect |
| `quality.dead_code.enabled` | bool | `false` | `check_dead_code.py` | Dead code not checked |
| `quality.dead_code.strict` | bool | `false` | `check_dead_code.py` | Warn only |
| `quality.dead_code.min_confidence` | int | `80` | `check_dead_code.py` | 80% confidence threshold |
| `quality.dead_code.paths` | list | `[]` | `check_dead_code.py` | Project root |
| `quality.dead_code.whitelist` | string | `".vulture_whitelist.py"` | `check_dead_code.py` | `.vulture_whitelist.py` |
| `quality.type_checking.enabled` | bool | `true` | Not enforced by script | No effect |
| `quality.type_checking.strict` | bool | `true` | Not enforced by script | No effect |

## acceptance_gates

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `acceptance_gates.enabled` | bool | `false` | Not enforced by script | No effect |
| `acceptance_gates.*` | various | — | Not enforced by script | No effect |

## messaging

| Key | Type | Default | Read By | Default When Absent |
|-----|------|---------|---------|---------------------|
| `messaging.enabled` | bool | `false` | **Not read by any script** 📋 | No effect |
| `messaging.require_ack` | bool | `true` | **Not read by any script** 📋 | No effect |
| `messaging.inbox_dir` | string | `".claude/messages"` | **Not read by any script** 📋 | No effect (`send_message.py` hardcodes this path) |

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
