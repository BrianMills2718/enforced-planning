# Plan #50 — Ecosystem Status Renderer

**Status:** Complete
**Priority:** Medium
**Gap:** Operators need a single `make ecosystem-status` command that emits a
machine-readable JSON payload and a rendered Markdown summary of the entire
governed-repo fleet.

## Acceptance Criteria

- [x] `governed_repos.yaml` created at repo root listing all 16 governed repos
- [x] `scripts/ecosystem_status.py` reads the registry, runs per-repo audits,
      loads `generated/plan_registry.json` and `generated/ecosystem_dep_map.json`,
      emits `generated/ecosystem_status.json`
- [x] `docs/ops/ECOSYSTEM_STATUS.md` rendered from the JSON by the same script
- [x] `make ecosystem-status` target added to Makefile
- [x] Repos that do not exist on disk are classified as "not_found" and do not crash the script
- [x] `python scripts/self_test.py` passes after implementation

## Design References

- `docs/designs/ECOSYSTEM_DASHBOARD_STATUS_SURFACES.md`

## Implementation Notes

- `governed_repos.yaml` uses `~`-relative paths; script expands via `Path.expanduser()`
- Audit runs per-repo via subprocess calling `scripts/audit_governed_repo.py --json`
- JSON output parsed for `classification` field; falls back to human-readable parse
- `legacy_count` captures any repo classified as legacy, not_found, or error
- All logic in `scripts/ecosystem_status.py`; Makefile just calls the script
