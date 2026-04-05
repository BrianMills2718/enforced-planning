# Plan #17: Governed-Repo Installer Convergence

**Status:** Planned
**Type:** design
**Priority:** High
**Blocked By:** None
**Blocks:** #16

---

## Gap

**Current:** `install.sh` and `scripts/install_governed_repo.py` both describe
how the framework is applied to target repos, but they do not present one
authoritative governed-repo contract. The shell installer still drives most
docs, while the Python installer reflects newer sync/update semantics.

**Target:** The framework has one canonical installer contract, one declared set
of installed files, one upgrade/sync story, and one deprecation boundary for
legacy installation behavior.

**Why:** Installation drift causes documentation drift, test drift, and adoption
confusion. The installer is the root of the governed-repo product surface.

---

## References Reviewed

- `install.sh` - current shell bootstrap path
- `scripts/install_governed_repo.py` - current sync-oriented installer
- `scripts/self_test.py` - installer integrity coverage
- `tests/test_install_governed_repo.py` - current Python installer coverage
- `README.md` - current install guidance
- `GETTING_STARTED.md` - current adoption guidance
- `docs/designs/DOCUMENTATION_SURFACE_ARCHITECTURE.md` - canonical source-vs-installed split

---

## Research Basis For This Slice

- `docs/designs/DOCUMENTATION_SURFACE_ARCHITECTURE.md` - defines the need for one canonical installed-repo model
- No additional research beyond References Reviewed.

---

## Files Affected

- install.sh (modify or deprecate)
- scripts/install_governed_repo.py (modify)
- tests/test_install_governed_repo.py (modify)
- scripts/self_test.py (modify)
- README.md (modify)
- GETTING_STARTED.md (modify)
- docs/guides/NEW_PROJECT_SETUP.md (modify)
- ROADMAP.md (modify if installer authority or phase status language changes)
- docs/plans/17_governed-repo-installer-convergence.md (modify)
- docs/plans/CLAUDE.md (modify)

---

## Plan

### Steps

1. Define the canonical governed-repo contract: file layout, modes, sync/update behavior.
2. Choose the long-term authority:
   - `install.sh` delegates to `scripts/install_governed_repo.py`
   - or `install_governed_repo.py` becomes internal and `install.sh` stays canonical
3. Define how `--minimal`, `--full`, `--pre-commit`, and worktree-only behavior map into the canonical installer.
4. Define whether semantic-review tooling ships to consumers now or remains source-repo-only until later.
5. Update tests and self-test coverage to enforce the chosen installer contract.
6. Rewrite installer-facing docs against the canonical choice.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_install_governed_repo.py` | canonical installer contract tests | The chosen installer path yields the documented file layout and sync semantics |
| `tests/test_self_test.py` or installer self-check surface | installer parity assertions | Source docs and installer outputs remain aligned |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/validate_plan.py --plan-file docs/plans/17_governed-repo-installer-convergence.md --warn-only` | Plan remains valid |
| `python scripts/self_test.py` | Installer references and file integrity remain correct |
| `pytest -q tests/test_install_governed_repo.py` | Installer behavior remains covered |

---

## Acceptance Criteria

- [ ] One installer path is explicitly canonical
- [ ] The non-canonical installer path is either delegated, scoped narrowly, or deprecated
- [ ] The documented installed file layout matches what tests assert
- [ ] Mode semantics (`--minimal`, `--full`, `--pre-commit`, worktree sync) are documented without overlap or ambiguity
- [ ] Installer-facing docs match the chosen authority
- [ ] Declared checks pass

---

## Open Questions

- [ ] Should `install.sh` remain the public entrypoint for ergonomics while delegating all real logic to Python, or should the Python installer become the primary operator surface? — Status: OPEN | Why it matters: affects portability, testability, and future upgrade flow

