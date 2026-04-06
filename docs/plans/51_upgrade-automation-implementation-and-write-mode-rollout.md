# Plan #51: Upgrade Automation Implementation and Write-Mode Rollout

**Status:** ✅ Complete (implementation shipped 2026-04-05; write-mode rollout deferred pending Mac mini pilot)
**Type:** implementation
**Priority:** High
**Blocked By:** Plan #20 (design)
**Blocks:** Phase 9 write-mode fleet rollout

---

## Gap

**Current (as of Plan #20 completion):** The design for upgrade automation was complete, but
no implementation existed. The framework had `install_governed_repo.py` for single-repo installs
and `audit_governed_repo.py` for single-repo audits, but no script for fleet-wide operations.

**Target:** `scripts/upgrade_governed_repos.py` orchestrates install + audit across all registered
repos. Dry-run is safe and default; write-mode requires clean working trees. A 16/16 dry-run
pass is the trigger for write-mode rollout consideration.

---

## Implementation (2026-04-05)

`scripts/upgrade_governed_repos.py` was implemented and verified on 2026-04-05.

### What it does

1. Reads `governed_repos.yaml` — authoritative fleet registry
2. For each repo: verifies it exists, checks for local dirt (blocks `--write` if present)
3. Runs `install_governed_repo.py` (dry or write mode)
4. Runs `audit_governed_repo.py --json` to classify the repo
5. Emits per-repo result with classification, blockers, and exit code

### Safety model

| Condition | Behavior |
|-----------|----------|
| Repo path missing | SKIP with reason |
| Local dirt in `--write` mode | SKIP with reason |
| Missing root `CLAUDE.md` | Hard blocker; classify as `legacy`, SKIP |
| Install fails | Mark FAIL; continue other repos |
| Audit fails | Mark FAIL; report blockers |

### Flags

| Flag | Effect |
|------|--------|
| `--dry-run` | Default; never modifies files |
| `--write` | Apply changes (blocked if repo has local dirt) |
| `--repo REPO_ID` | Upgrade one repo by ID |
| `--json` | Machine-readable JSON output |
| `--registry PATH` | Path to governed_repos.yaml (default: governed_repos.yaml) |

---

## Verification Results (2026-04-05)

Dry-run across 16 registered repos:

```
upgrade_governed_repos — DRY-RUN mode — 16 repo(s)
Result: 16 ok, 0 skipped, 0 failed of 16 total
```

All 16 repos passed dry-run with correct classification and no unexpected blockers.

---

## Acceptance Criteria

- [x] `scripts/upgrade_governed_repos.py` exists and is executable
- [x] Reads `governed_repos.yaml` without error (handles both `id`/`path` and `repo_id`/`repo_root` key formats)
- [x] `--dry-run` is the default; never modifies files
- [x] `--write` mode blocks if local dirt detected
- [x] Missing root `CLAUDE.md` is a hard blocker, repo classified as `legacy`
- [x] Per-repo results include classification and blockers
- [x] `--json` flag produces machine-readable output
- [x] 16/16 governed repos pass dry-run
- [ ] Write-mode rollout executed and verified — **deferred to Mac mini pilot** (Phase 9 trigger)

---

## Write-Mode Rollout (Phase 9 — Deferred)

Write-mode rollout is **not yet executed**. The trigger is the Mac mini continuous-automation
pilot (see ROADMAP.md Phase 9). Rollout sequence when triggered:

1. Run `python scripts/upgrade_governed_repos.py --registry governed_repos.yaml --write --repo <one repo>` on a low-risk repo first
2. Verify audit passes and no unexpected mutations
3. Roll out repo-by-repo for the remaining 15 repos
4. Operators must manually approve each write if the repo has any active worktrees or claims

**Gate for automated rollout:** Mac mini pilot results show the dry-run pipeline running
unattended without producing false positives.

---

## References

- Design: `docs/designs/GOVERNED_REPO_UPGRADE_AUTOMATION.md`
- Predecessor: `docs/plans/20_governed-repo-upgrade-automation.md` (design-only)
- Registry: `governed_repos.yaml`
- Primitives: `scripts/install_governed_repo.py`, `scripts/audit_governed_repo.py`
