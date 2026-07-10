# Plan #62 User-Neutral Instantiation Evidence

Status: implementation wedge complete; full plan remains in progress.

## Verified

- `pytest -q tests/test_cleanroom_alpha.py tests/test_check_notebook_registry.py` — 33 passed.
- Consumer metadata is rendered into `consumer-config.json`.
- Personal sentinel input fails with `personal_config_leak`.
- Consumer project ids and root-relative paths are validated for duplicates and traversal.
- Make/shell metacharacters and multiline YAML injection inputs fail before rendering.
- `policy_pack_name` labels the rendered policy pack and registry.
- Notebook registry validation and `git diff --check` pass.

## Honest Grades

| Criterion | Grade | Evidence |
|---|---|---|
| User-neutral metadata contract | A | importable implementation, non-default inventory, and negative controls |
| Isolation and personal-data exclusion | A | positive materialization and sentinel negative control |
| Deterministic rendering | A | non-default inventory materializes matching deterministic placeholder projects |
| Independent onboarding | C | fresh external-root CLI exercise; still run from the maintainer test suite |

## Remaining Gap

Non-default inventories now materialize matching placeholder projects and pass
the root verifier. Real project source/build adapters and a genuinely external
human onboarding exercise remain before the plan can close.
