# Plan 63 Evidence: `onto-canon6` Report-Only Pilot

**Date:** 2026-07-14  
**Consumer revision:** `90f46bb65ccf2b3340c293748fbe19b09506f246`  
**Framework revision:** `c8d71e4`  
**Mode:** report-only; no consumer governance or source files changed

## Decision

Keep relationship context visible but do **not** enable repository-wide hard
enforcement yet. The compiler and hook adapter are ready for report-only use.
The consumer relationship graph is useful for plan/document work but lacks the
code-to-plan/test/ADR edges required to keep implementation plans current.

## Observed Results

| Surface | Result | Evidence grade |
|---|---|---|
| Exact inventory | 1,465 tracked artifacts represented; 803 summarized | B: observed consumer run |
| Runtime | inventory 0.94 s; plan packet 1.00 s; wiki 0.91 s | B: observed consumer run |
| Plan edit packet | 12 bounded items, 7,151 item chars, 0 omitted/diagnostics after compatibility repair | B: observed consumer run |
| Plan relationships | target Plan 0141 + ADR-0032/33/34 + six related plans + master plan + `CLAUDE.md` | B: observed consumer run |
| Code edit packet | module-local docstring + `CLAUDE.md` only | F for cross-artifact code context |
| Prior real commit impact | five changed files, zero obligations | F for plan-maintenance enforcement |
| Wiki | deterministic check passed; 10,494 lines / 858,524 bytes | B: observed consumer run |
| Existing docstring debt | 363 findings across 75 Python files | B: observed consumer run; not enforcement-ready |

The relationship compiler resolved seven normalized declarations:
three `governed_by`, two `planned_by`, one `documents_current`, and one
`required_reading`. Six are `reconcile`; one is `lineage_only`. The source
configuration has no `couplings` and no source-code selectors.

## Commands And Key Output

```text
python scripts/relationship_context.py --repo-root <pilot>
tracked_count=1465 summarized_count=803 diagnostic_count=365
diagnostic_codes={python-docstring-missing: 363,
                  markdown-title-missing: 1,
                  tracked-symlink-not-read: 1}
```

```text
python scripts/context_packet.py --repo-root <pilot> \
  docs/plans/0141_holistic_document_graph_semantic_authoring.md
included_chars=7151 omitted_count=0 diagnostics=[]
```

```text
python scripts/impact_obligations.py --repo-root <pilot> --base HEAD^
changed_paths=[Makefile, docs/planning/manifest.yaml,
  docs/plans/0142_unified_project_goal_map.md,
  scripts/check_planning_manifest.py,
  tests/meta/test_check_planning_manifest.py]
obligation_count=0 unresolved_count=0
```

```text
python scripts/docstring_wiki.py --repo-root <pilot> --write
python scripts/docstring_wiki.py --repo-root <pilot> --check
docstring wiki current
10494 lines, 858524 bytes
```

## Defects Found And Fixed

1. A `Write` hook can target an untracked new file. The compiler now supports
   an explicit `allow_untracked_target` mode, marks the target as path-derived,
   and still resolves matching relationships. Symbol claims remain forbidden
   until source exists.
2. Installed wrappers under `scripts/meta/` previously derived the wrong import
   root. All four wrappers now support both canonical and installed layouts;
   an installer integration test executes the installed packet CLI.
3. The consumer uses the V1 architecture key `current`; the compiler recognized
   only `current_docs`. It now supports reviewed V1/V2 aliases and rejects
   duplicate alias declarations. This restored the master-plan
   `documents_current` edge.

## Calibration And Next Gate

Do not convert the 363 existing docstring findings into a hard gate. Much of
the debt is in tests, where requiring prose for every test method would create
noise rather than maintained context. First define classification-specific
coverage rules and a reviewed baseline.

Do not run impact obligations in strict mode for `onto-canon6` yet. First add
and review a small set of high-value code-to-plan/current-state/test edges,
then replay real diffs and measure false obligations. Hard enforcement is
eligible only when a changed implementation with a declared edge reliably
creates the intended obligation and unrelated changes do not.

## Post-Merge Audit Addendum

The original focused suite proved public symbol extraction but did not test the
stronger whole-codebase wiki claim. A full AST comparison found 407 documented
private callables absent from the framework inventory. After repair, the same
comparison reports `omitted_private_docstrings=0`; undocumented private helpers
remain visible without becoming mandatory coverage debt.

The original installer integration test also ran under the host interpreter,
masking whether a consumer `.venv` contained PyYAML. New negative controls give
the target a Python executable that rejects `import yaml`; both hook generation
and full installation now fail before writes with `cannot import PyYAML`.

Finally, automated edit injection is certified only for the installed Claude
Code hook. Codex can invoke the same context packet through CLI/JSON, but no
Codex-native automatic pre-edit adapter was built or observed in this pilot.

## Bounded Consumer Rollout Addendum

The post-pilot rollout audit found that the default installer would synchronize
21 unrelated framework files in the calibrated consumer. The hook-only
generator avoided that churn but did not install the impact/wiki CLIs or Make
targets. The new bounded mode was therefore exercised against a disposable
checkout of onto-canon6 `573c819`:

```text
python scripts/install_governed_repo.py \
  --repo-root /tmp/onto-context-rollout-audit \
  --relationship-context-only --json
blockers=[]
actions=11
drift_files=[]
```

The 11 actions were exactly four runtime modules, four installed wrappers, the
marked Make block, and two changed hook files. After applying them, the local
semantic-authoring packet contained 5 items / 2,827 characters with no
diagnostics, impact reporting executed, and both `make docstring-wiki` and
`make docstring-wiki-check` passed. No plan, `AGENTS.md`, validator, or unrelated
framework mirror was changed. The integration test additionally preserves
deliberately drifted unrelated files and runs all five generated Make targets.

## Artifacts Consulted

- `onto-canon6/scripts/relationships.yaml`
- `onto-canon6/docs/plans/0141_holistic_document_graph_semantic_authoring.md`
- `onto-canon6/docs/DOCUMENT_GRAPH_TO_MULTI_DOCUMENT_KG_MASTER_PLAN.md`
- `onto-canon6/CLAUDE.md`
- `enforced-planning/docs/plans/63_relationship_context_and_docstring_wiki.md`
- `enforced-planning/docs/designs/RELATIONSHIP_CONTEXT_CONTRACT.md`
