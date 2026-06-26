# Git Enforcement Stack

<!-- doc-role: operational-reference -->
<!-- authority: enforced-planning -->
<!-- plan-ref: Plan #191 (temporal-memory enforcement) -->

The enforcement stack converts Git discipline norms (documented in `AGENTS.md` and
Plans #189–#190) into machine-checked gates. This doc defines what runs where and
how to install the local layer.

---

## Enforcement Layers

| Layer | Tool | When | Purpose |
|-------|------|------|---------|
| Local pre-commit | `git hooks/pre-commit` | Every `git commit` | Block staging errors at authorship time |
| Local pre-push | (not yet deployed) | Every `git push` | Block force-push of runtime exhaust to main |
| CI / GitHub Actions | (not yet deployed) | PR merge | Structural checks — linting, tests, parity |
| GitHub Rulesets | GitHub API/UI | Branch protect | PR required, linear history, required status checks |
| Fleet debt surface | `check_ahead_of_origin.py` | On-demand / cron | Surface "ahead-of-origin" memory debt across all repos |

---

## Local Pre-Commit Checks

The shared policy checks run via a per-repo tracked hook at `hooks/pre-commit`
(symlinked or installed into `.git/hooks/pre-commit` via `make install-hooks`).

### Universal checks (every staged `.py` file)

| Check | What it catches | Outcome |
|-------|----------------|---------|
| `check_llm_client_usage.py` | Direct `anthropic`/`openai`/`subprocess claude` calls bypassing `llm_client` | Warning (will become hard block after all violations cleared) |

### Ecosystem-ops-specific checks

| Check | What it catches | Outcome |
|-------|----------------|---------|
| Runtime-path staging rejection | Staging `assessments/_*`, `generated/runtime/`, runtime exhaust paths defined in Plan #189 | Hard block with actionable message |
| API parity | HTML route added without a `/api/` JSON counterpart | Hard block |
| INDEX.md sync | Plan file staged without INDEX.md status emoji sync | Auto-fix + re-stage |

---

## Installation

For any repo with a tracked `hooks/pre-commit`:

```bash
make install-hooks
# or manually:
cp hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

To verify the hook is installed and runs:
```bash
ls -la .git/hooks/pre-commit
git diff --cached | head -5  # stage something then run:
git commit --dry-run
```

---

## Runtime-Path Staging Rejection

Ecosystem-ops' hook rejects staged paths that match the runtime-class patterns
defined in Plan #189:

```
assessments/_anomalies_*
assessments/_health_*
assessments/_digest_*
assessments/_enrichment_*
assessments/_freshness_*
generated/runtime/
repair_uncertainty_records/
governed_experiments/
```

If you intentionally want to promote a runtime artifact to a snapshot
(e.g., curate an assessment), explicitly rename or move it out of the `_`-prefixed
zone before staging.

---

## Fleet Ahead-of-Origin Debt

Run `check_ahead_of_origin.py` to surface repos with unpushed commits:

```bash
python ~/projects/project-meta/scripts/check_ahead_of_origin.py
python ~/projects/project-meta/scripts/check_ahead_of_origin.py --json
python ~/projects/project-meta/scripts/check_ahead_of_origin.py --warn-threshold 3
```

This script reads `PROJECT_GRAPH.json`, iterates each active repo, and counts
commits ahead of origin on the default branch. Repos with `ahead_count >= warn_threshold`
(default 1) are flagged as memory debt — work that has been done but not pushed
to the durable record.

See `project-meta/scripts/check_ahead_of_origin.py` for the full implementation.

---

## GitHub Rulesets Policy

See `project-meta/docs/ops/GITHUB_RULESET_POLICY.md` for the canonical ruleset
definition and per-repo pilot status.

---

## References

- `~/projects/project-meta/docs/plans/189_git-temporal-memory-operating-model.md` — taxonomy
- `~/projects/project-meta/docs/plans/190_repo-state-separation-and-clean-main-rollout.md` — clean-main rollout
- `~/projects/project-meta/docs/plans/191_temporal-memory-enforcement-hooks-and-rulesets.md` — this plan
- `~/projects/project-meta/docs/ops/GITHUB_RULESET_POLICY.md` — remote ruleset policy
- `~/projects/project-meta/scripts/check_ahead_of_origin.py` — fleet debt checker
- `~/projects/ecosystem-ops/docs/ops/PRE_COMMIT_POLICY.md` — ecosystem-ops local hook policy
