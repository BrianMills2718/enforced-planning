# Sprint: Full Documentation & Technical Debt Resolution
**Date:** 2026-04-03
**Duration:** 24-hour autonomous execution
**Authority:** Brian — "run continuously until all are done, NEVER STOP"

## Mission Statement

Resolve every issue identified in the 2026-04-03 documentation audit:
inconsistencies, stale references, ambiguities, adoption gaps, test coverage
gaps, and the single highest-leverage architectural improvement (pre-commit
migration). Every phase has unambiguous acceptance criteria. Stop only for
irreversible actions affecting shared state.

## Acceptance Criteria (session-level)

- [ ] `python -m pytest tests/ -q` passes with ≥ 288 tests (no regressions)
- [ ] `make test` is green
- [ ] No `grep -r "from llm_client import complete"` matches in scripts/
- [ ] ISSUES.md contains only enforced-planning issues (no agent_ecology2 refs)
- [ ] docs/plans/12_cross-repo-plan-registry.md exists
- [ ] README.md has explicit Claude-Code-specific disclaimer
- [ ] meta-process.yaml.example has no unimplemented config keys (or all marked [planned])
- [ ] Pattern 15 defines "trivial" with concrete threshold
- [ ] docs/migration/V1_TO_V2.md exists
- [ ] docs/guides/NEW_PROJECT_SETUP.md exists (15-minute path)
- [ ] Pattern 42 is ≤ 400 words and links to PLANNING_OPERATING_MODEL.md
- [ ] `.pre-commit-hooks.yaml` exists at repo root
- [ ] `templates/pre-commit-config.yaml.example` exists
- [ ] install.sh supports `--pre-commit` mode
- [ ] parse_plan.py has test coverage (≥ 10 tests)
- [ ] sync_plan_status.py has test coverage (≥ 8 tests)
- [ ] check_plan_tests.py has test coverage (≥ 8 tests)
- [ ] Phase 8 roadmap written in ROADMAP.md
- [ ] All changes committed and pushed

---

## Phase 1: Critical Bug Fixes

**Duration:** ~45 min
**Risk:** Low — fixes broken code to match existing spec

### 1a. Fix verify_coupling.py — llm_client API mismatch

**Problem:** `_load_llm_client()` imports `from llm_client import complete` which
doesn't exist. Same bug that was fixed in `review_truth_surfaces.py` today.

**Fix:** Replace with `call_llm_structured` pattern. The call must use
`response_model=VerificationJudgment` instead of `response_format=json_schema`.
The function returns `(model_instance, LLMCallResult)` — unpack accordingly.
Delete the manual `json.loads(result.content)` parse chain.

**Tests to update:** Any test that mocks `_load_llm_client` to return a mock
with `.content = json.dumps(...)` — update to return
`(VerificationJudgment_instance, MagicMock())`.

**Acceptance:** `grep "from llm_client import complete"` returns no matches.
All tests pass.

### 1b. Create Plan #12 file

**Problem:** `docs/plans/CLAUDE.md` index lists Plan #12 as complete but
`docs/plans/12_cross-repo-plan-registry.md` does not exist. Framework violates
its own convention.

**Fix:** Create the plan file documenting what was built:
- `build_plan_registry.py` — cross-repo plan table parser
- `build_ecosystem_dep_map.py` — cross-repo dependency aggregator
- `make plan-registry`, `make infer-all`, `make ecosystem-deps` targets

**Acceptance:** File exists with correct plan metadata.

### 1c. Replace ISSUES.md

**Problem:** Current ISSUES.md tracks issues for agent_ecology2 — it references
`Plan #247`, `Plan #248`, `genesis/`, `src/simulation/runner.py`. These are
not enforced-planning artifacts. The framework's own issue tracker tracks
someone else's bugs.

**Fix:** Archive the old file to `docs/ops/ISSUES_LEGACY_agent_ecology2.md`.
Write a new ISSUES.md with:
- Real enforced-planning issues from the audit
- MP-001: Plan #12 file missing (now fixed)
- MP-002: verify_coupling.py API mismatch (now fixed)
- MP-003: Large scripts untested (complete_plan.py, parse_plan.py, etc.)
- MP-004: Claude-Code-specific hooks not disclosed in README
- MP-005: meta-process.yaml has unimplemented config keys
- MP-006: TRAYCER_COMPARISON.md at wrong location
- MP-007: Planning hierarchy defined in 3 places with variations
- MP-008: docs/ops/ has 9 stale sprint documents cluttering root

**Acceptance:** ISSUES.md contains no agent_ecology2 references.

---

## Phase 2: Documentation Cleanup

**Duration:** ~2 hours
**Risk:** Low — moving/editing docs, no code changes

### 2a. Archive docs/ops/ sprint documents

**Problem:** 9 sprint/TODO documents in docs/ops/ are closed work artifacts.
They create noise when reading the ops directory.

**Fix:** Move all `OVERNIGHT_SPRINT_*.md` and `TRUTH_SURFACE_*_TODO.md` files
to `docs/ops/archive/`. Keep only `semantic_review_findings.yaml`,
`verification_log.yaml`, `escalations.yaml`, and the new sprint doc.

**Acceptance:** `ls docs/ops/*.md | wc -l` ≤ 2.

### 2b. Move TRAYCER_COMPARISON.md

**Problem:** Research document sitting at repo root with framework docs.

**Fix:** Move to `docs/research/TRAYCER_COMPARISON.md`. Update any references.

**Acceptance:** File in correct location. Root has no TRAYCER_COMPARISON.md.

### 2c. Add Claude-Code-specific disclaimer to README and GETTING_STARTED

**Problem:** README says "portable" and "Claude Code, etc." but the "etc." is
empty — the framework only works with Claude Code (`.claude/hooks/`, CLAUDE.md
convention).

**Fix:** Add to README (near top, in a callout):
```
> **Tool compatibility:** Currently Claude Code only. Hooks (.claude/hooks/),
> CLAUDE.md convention, and read-gating are Claude Code-specific. Cursor/Windsurf
> support is planned (Phase 8). Patterns and git hooks are tool-agnostic.
```

Same note in GETTING_STARTED.md Prerequisites section.

**Acceptance:** README and GETTING_STARTED both have explicit tool disclaimer.

### 2d. Audit and fix meta-process.yaml.example

**Problem:** Several config keys in meta-process.yaml.example are not read by
any script. Adopters copy them and get placebo configuration.

**Verification needed:** Check which keys are actually consumed by scripts:
- `plans.trivial_threshold_lines` — check if any script reads this
- `planning.question_driven_planning` — check if enforced anywhere
- `planning.uncertainty_tracking` — check if enforced anywhere
- `planning.dependency_probe_policy` — check if enforced anywhere
- `capability_ownership.*` — check if enforced anywhere
- `messaging.*` — check if worktree-coordination scripts read this

**Fix:** For each unimplemented key, add `# [PLANNED - not yet enforced]`
comment. This is honest and prevents silent misconfiguration.

**Acceptance:** Every key in meta-process.yaml.example is either verified
functional or marked `# [PLANNED]`.

### 2e. Define "trivial" concretely in Pattern 15 and plan template

**Problem:** The Trivial Exemption in Pattern 15 says "< 20 lines" but doesn't
define what counts as a line, what files are exempt, or how to handle edge cases.

**Canonical definition to use** (from meta-process.yaml.example which does have
`trivial_threshold_lines: 20`):
```
[Trivial] is exempt from Plan requirement if ALL of:
- ≤ 20 lines changed (diff stat)
- No changes to src/ or production code directories  
- No new public APIs, schemas, or behavioral changes
- Reviewer judgment confirms it's genuinely minor
```

**Fix:** Add this definition verbatim to Pattern 15 "Trivial Exemption" section
and to `templates/plan.md.template` as a comment near the top.

**Acceptance:** Pattern 15 has explicit multi-condition definition.

### 2f. Create V1→V2 migration guide

**File:** `docs/migration/V1_TO_V2.md`

**Content:**
- What V1 relationships.yaml looks like (example)
- What V2 adds (version: 2, coupling_types, type field)
- Why you'd migrate (locked coupling enforcement, validated coupling agent protocol)
- Step-by-step: back up, run `make migrate-rels REPO=.`, review output, commit
- What breaks: nothing — V1 files still work, V2 adds capabilities

**Acceptance:** File exists with V1 example, V2 example, migration steps.

---

## Phase 3: Planning Hierarchy Consolidation

**Duration:** ~1.5 hours

### 3a. Make PLANNING_OPERATING_MODEL.md explicitly canonical

**Fix:** Add to the top of PLANNING_OPERATING_MODEL.md:
```
> **Canonical source.** This document defines the authoritative planning hierarchy.
> Pattern 42 (planning-hierarchy) and Pattern 15 (plan-workflow) are compressed
> views of this document. When they conflict, this document wins.
```

**Acceptance:** POM has explicit "canonical source" statement.

### 3b. Reduce Pattern 42 to a summary

**Problem:** Pattern 42 (143 lines) duplicates PLANNING_OPERATING_MODEL.md.
Subtle variations create confusion.

**Fix:** Reduce to: (1) one-paragraph summary of each layer, (2) "full detail:
see PLANNING_OPERATING_MODEL.md," (3) quick-reference table. Target: ≤ 300 words.

**Acceptance:** Pattern 42 ≤ 400 words, links to POM.

### 3c. Update GETTING_STARTED.md to lead with POM

**Problem:** GETTING_STARTED.md buries PLANNING_OPERATING_MODEL.md. Step 1 is
"install hooks" not "read the operating model."

**Fix:** Add to the top of the "Before You Start" section:
```
Read PLANNING_OPERATING_MODEL.md first — it defines the planning hierarchy
that governs all work in this framework. Everything else in this guide is
an implementation of that model.
```

**Acceptance:** GETTING_STARTED.md references POM prominently in the first screen.

---

## Phase 4: New Adopter Experience

**Duration:** ~1.5 hours

### 4a. Write "New Project Setup" guide

**File:** `docs/guides/NEW_PROJECT_SETUP.md`

**Goal:** A developer with no prior knowledge of this framework should be able to
go from zero to their first governed commit in 15 minutes.

**Sections:**
1. Prerequisites (git, Python, Claude Code, what version)
2. Install (run install.sh, choose --minimal or --full, what gets copied where)
3. Verify (run `make test-quick`, commit a test file to verify hooks)
4. Configure (which meta-process.yaml keys to set first, and what they do)
5. First plan (create a plan file from template, make a `[Plan #1]` commit)
6. What breaks and how to fix it (top 5 errors new adopters hit)

**Acceptance:** Guide exists, is <500 lines, contains actual commands that work.

### 4b. Document which meta-process.yaml keys are functional

As part of the guide: a table listing every config key, which script reads it,
and the default behavior if the key is absent. This is the honest version of
the example file.

**Acceptance:** Table exists in NEW_PROJECT_SETUP.md or in a separate
`docs/reference/CONFIG_REFERENCE.md`.

---

## Phase 5: pre-commit Framework Migration

**Duration:** ~3-4 hours
**Risk:** Medium — changes install interface for adopting repos
**Architecture decision:** Yes, do it. pre-commit is the industry standard for
pre-commit hook management. Raw bash hooks are not maintainable.

### What pre-commit gives us

The `pre-commit` Python tool (https://pre-commit.com/) provides:
- Declarative `.pre-commit-config.yaml` instead of bash
- Versioned hooks (repos pin to hook versions)
- `pre-commit run --all-files` for CI
- `pre-commit autoupdate` for version management
- Automatic isolation and caching
- Used by 100k+ projects

### 5a. Create `.pre-commit-hooks.yaml` at enforced-planning repo root

This defines enforced-planning AS a pre-commit hook provider. Adopters can
reference this repo in their `.pre-commit-config.yaml`.

**Entries to define:**
- `commit-msg-format` — runs commit-msg hook (require prefix)
- `locked-couplings` — runs check_locked_couplings.py
- `plan-capabilities` — runs check_plan_capabilities.py on staged plan files
- `doc-coupling` — runs check_doc_coupling.py
- `plan-status` — runs sync_plan_status.py

**Format:** Standard pre-commit hook definition YAML.

### 5b. Create `templates/pre-commit-config.yaml.example`

Example `.pre-commit-config.yaml` that an adopting project copies:
```yaml
repos:
  - repo: https://github.com/BrianMills2718/enforced-planning
    rev: v1.0.0  # pin to a version
    hooks:
      - id: commit-msg-format
      - id: locked-couplings
      - id: plan-capabilities
      # etc.
```

### 5c. Update install.sh to support --pre-commit mode

Add a `--pre-commit` install flag that:
1. Creates `.pre-commit-config.yaml` instead of copying bash hooks to `hooks/`
2. Runs `pip install pre-commit` and `pre-commit install`
3. Adds `.pre-commit-config.yaml` to the installed files

The `--minimal` and `--full` modes continue to work (backward compatible).
`--pre-commit` is the recommended modern mode.

### 5d. Update GETTING_STARTED.md and README

Document that `--pre-commit` is the recommended installation mode.
Keep `--minimal` and `--full` as alternatives for environments where
pre-commit cannot be installed.

**Acceptance:**
- `.pre-commit-hooks.yaml` exists with ≥ 4 hook entries
- `templates/pre-commit-config.yaml.example` exists with usage instructions
- `install.sh --pre-commit` runs without error in a test environment
- README documents both installation modes

---

## Phase 6: Test Coverage for Large Untested Scripts

**Duration:** ~5 hours
**Risk:** Low if well-isolated (mock git, GitHub interactions)

### Scripts to cover

| Script | Lines | Priority | Testing strategy |
|--------|-------|----------|-----------------|
| `parse_plan.py` | 438 | High | Pure parsing functions; no git needed; test isolated |
| `sync_plan_status.py` | 456 | High | Mostly pure; some git reads; mock git calls |
| `check_plan_tests.py` | 552 | Medium | Mostly parsing + file checking; mock git |
| `complete_plan.py` | 597 | Low | Heavy git/GitHub; test pure helpers only |

### 6a. Tests for parse_plan.py

**Target:** 15+ tests covering plan file parsing.
**What to test:** extract_plan_number(), extract_status(), extract_section(),
parse_plan_file(), edge cases (missing sections, malformed markdown).

### 6b. Tests for sync_plan_status.py

**Target:** 10+ tests.
**What to test:** status extraction from plan files, index table update logic,
consistency check logic. Mock git diff output.

### 6c. Tests for check_plan_tests.py

**Target:** 10+ tests.
**What to test:** Required Tests section parsing, test file existence check,
gap detection. Use tmp_path fixtures.

**Acceptance:** All three test files exist. `pytest tests/test_parse_plan.py
tests/test_sync_plan_status.py tests/test_check_plan_tests.py` passes.

---

## Phase 7: Phase 8 Roadmap

**Duration:** ~45 min

### 7a. Add Phase 8 to ROADMAP.md

**Title:** Phase 8: Multi-Tool Support and Ecosystem Observability

**Gate:** Framework adopted by ≥ 3 different teams using different AI tools.

**Items:**
- Multi-tool hook support (Cursor, Windsurf, Cline, Copilot)
- Adoption automation: governed repo registry + `make upgrade-framework`
- Ecosystem dashboard: aggregate plan status and dep map across all repos
- Framework self-measurement: define and instrument success metrics
- Phase 6 deferred items: Bazel-style visibility grammar, distributed governance

### 7b. Document deferred items with explicit blockers

For each deferred item, add one line: why it's deferred and what would unblock it.

**Acceptance:** ROADMAP.md has Phase 8 section. All deferred items have explicit
rationale.

---

## Execution Order

Execute phases strictly in order. Each phase commits before the next begins.
If a phase reveals new information that changes a later phase, update this
document before continuing.

1. Phase 1 (bugs) — commit after each sub-phase
2. Phase 2 (doc cleanup) — one commit per sub-phase
3. Phase 3 (consolidation) — one commit
4. Phase 4 (adopter guide) — one commit
5. Phase 5 (pre-commit) — one commit per sub-phase
6. Phase 6 (tests) — one commit per script
7. Phase 7 (roadmap) — one commit

Push after every phase.

## NEVER STOP Policy (enforced for this sprint)

Per root CLAUDE.md canonical NEVER STOP definition:
- A completed phase → update this doc and continue to next
- A passing test run → commit and continue
- Uncertainty about file location → check the file, proceed
- Uncertainty about approach → pick the more conservative option, document it
- Tool failure (transient) → retry once, then proceed with next phase
- STOP ONLY FOR: irreversible action on shared state OR genuine architectural
  decision not pre-made in this plan

All architectural decisions are pre-made above. There are no legitimate
stop conditions in this sprint.
