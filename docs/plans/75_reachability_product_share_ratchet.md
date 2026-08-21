# Plan #75: Gate The Reachability Ratchet On The Product Path

**Status:** Planned
**Type:** implementation
**Priority:** Medium
**phase_ref:** "Phase 8"
**goal_ref:** "governed-repo-hygiene"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** exempt-trivial
**Blocked By:** None
**Blocks:** None

## Gap

**Current:** `scripts/check_reachability.py` computes `product_share` — the share
of lines reachable from a repo's declared product entrypoint — prints it with
baseline drift, and never gates on it. The only `if args.check: return 1` sits
inside the `newly_unreachable` branch, which counts modules unreachable from
*any* declared entrypoint. Because `meta-process.yaml` declares
`tests/**/*.py` and `scripts/*.py` as entrypoints, a module with a test file is
"reachable" by definition. No deployed copy of the sensor gates on
`product_share`.

**Target:** `--check` also fails when `product_share` regresses against the
recorded baseline, while staying silent for baselines written before the field
existed.

**Why:** The sensor's own docstring says it exists to catch "work that was
completed, committed, and then never wired to anything." The count it gates on
cannot see that, and the number that can is advisory. Measured in ac15 at
`c3224f6`: `make reachability-check` passed at `unreachable_count` 4/baseline 4
while the product path was 38.0% and 14 of 61 `ac15/` modules — about 4,900
lines including a 945-line unused control-plane skeleton — were held alive only
by their own test files.

## User Outcome

An agent or operator running `make reachability-check` in a governed repo is
told when new code is reachable only from tests and scripts, instead of being
told the repo is clean.

## Canonical Behavioral Example

**Starting input/state:** A governed repo whose `reachability_baseline.json`
records `product_share`, with a module reachable only from its own test file
added since the baseline.

**Action:** Run `python3 scripts/check_reachability.py --project-root . --check`.

**Expected observable result:** Exit code 1, with a message naming the fall from
the baseline share to the current share and the three ways to resolve it (wire
it to the product entrypoint, delete it, or lower the ratchet deliberately).

**Behavioral evidence:** observed real slice — the change was implemented and
verified in ac15 first (PR #12, squash `eb715f4`), where a forced baseline of
45.0% against an actual 40.5% returned exit 1 with that message, an unmodified
baseline returned exit 0, and a baseline with `product_share` removed returned
exit 0.

**Substrate/process evidence:** `tests/` coverage for the regression, silent, and
legacy-baseline branches.

**Failure signal:** `--check` returns 0 while `product_share` sits below the
baseline, or returns 1 on a baseline that has no `product_share` key.

## References Reviewed

- `scripts/check_reachability.py` — the sensor and its ratchet branch
- `CLAUDE.md` — source repo vs installed repo script perspectives
- `scripts/install_governed_repo.py` — how the sensor reaches consumers
- ac15 PR #12 — the verified reference implementation
- `EXECUTION_BRIEF.md` — confirms deterministic validation and governed-repo
  tooling are this repo's purpose, which is the slot this change sits in
- `adr/0009-doc-authority-governance-and-enforcement.md` — documentation
  authority; this change adds no authority surface, so the ADR does not
  constrain it beyond recording the ratchet in the config reference
- `docs/reference/DOC_AUTHORITY_SCHEMA.md` — the authority contract; the
  reachability baseline is a ratchet artifact, not an authority surface, so no
  schema entry is required

## Research Basis For This Slice

None required. The behavior is fully specified by the existing sensor and was
verified in a consumer repo before this plan was written.

## Landscape And Prior Art

**Reason for `exempt-trivial`:** The change is one regression branch inside a
sensor that already computes the value, with no new dependency, interface, or
consumer. Prior art was still checked: the alternatives below were considered
and the implementation was verified in a consumer repo first.

**Alternatives:** Extend the existing sensor (chosen). Rejected: a second
detector, which would duplicate the concern the sensor already owns; and leaving
`product_share` advisory, which is the current state that failed to catch about
4,900 lines in ac15.

**Project implications:** Consumers pick the change up on their next installer
run. Repos whose baseline predates `product_share` are unaffected until they
rewrite a baseline.

**Refresh trigger:** A consumer reporting a false positive on `--check`.

**Decision method:** Resolved from the sensor's stated purpose in its own
docstring.

## Modality Assessment

Command-line exit code and stderr/stdout message. No UI, no service, no model
call.

## Multi-Repo Coordination

Source change only. It reaches 19 governed repos through
`scripts/install_governed_repo.py` on their next install; this plan does not
run an installer against any consumer and does not change any consumer repo.
ac15 already carries the equivalent change locally.

## Capabilities

**Capability adoption:** Extends the existing reachability sensor, which is the
capability owner for module-reachability measurement in governed repos. No new
capability, no supersession, no exception. The intended consumer is the
`reachability-check` Make target, which already calls this script with
`--check`, so adoption is the existing call path rather than a new one.

## Files Affected

- `scripts/check_reachability.py` — add the `product_share` regression branch
- `scripts/meta/check_reachability.py` — byte-identical mirror, if the
  installer-declared lineage requires it
- `tests/` — regression, silent, and legacy-baseline cases
- `docs/reference/CONFIG_REFERENCE.md` — record that the ratchet now covers
  `product_share`

## Plan

1. Add a `SHARE_TOLERANCE` constant covering the baseline's 4-place rounding.
2. Capture `baseline_share` and compute `share_regressed` where the product-path
   line is already printed.
3. After the existing `newly_unreachable` branch, fail under `--check` when
   `share_regressed`, with a message naming both shares and the three remedies.
4. Mirror to `scripts/meta/check_reachability.py` if lineage requires it.
5. Add the three test cases and update the config reference.

## Required Tests

- `--check` exits 1 when `product_share` is below `baseline["product_share"]`
- `--check` exits 0 when `product_share` equals or exceeds the baseline
- `--check` exits 0 when the baseline has no `product_share` key
- existing `newly_unreachable` behavior is unchanged

## Acceptance Criteria

- [ ] The three test cases above pass
- [ ] `python scripts/self_test.py` passes
- [ ] `pytest -q` passes
- [ ] A baseline written by `--write-baseline` still round-trips through `--check`

## Open Questions

- Does the installer-declared lineage require `scripts/meta/check_reachability.py`
  to stay byte-identical with `scripts/check_reachability.py`? The installer map
  currently declares only the `scripts/` target for this file, while consumers
  run it from `scripts/meta/`. Resolve before mirroring.

## Notes

Scope was reduced during planning. An earlier version also proposed removing the
installer's duplicate `scripts/` targets for `check_dead_code`, `audit_dead_code`
and `check_push_safety`. That was withdrawn: the dual targets were added in one
commit (`1845aaa`) and llm_client references the bare `scripts/` path, so
removing them would break a live consumer.
