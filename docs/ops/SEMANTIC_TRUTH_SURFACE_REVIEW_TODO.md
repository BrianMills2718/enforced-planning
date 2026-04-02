# Semantic Truth-Surface Review TODO

## Sprint Goal

Implement the first optional semantic truth-surface review slice so deterministic and advisory semantic findings can coexist truthfully.

## Ordered TODOs

- [x] Phase A: define the bounded semantic-review sprint tracker
- [x] Phase A: point root `CLAUDE.md` and plan surfaces at the active sprint
- [x] Phase B: add a prompt-backed semantic review entrypoint using `llm_client`
- [x] Phase B: fail loud with a clear message when shared `llm_client` is unavailable
- [x] Phase C: extend rendered truth-surface status with a separate semantic advisory section
- [x] Phase C: record deterministic-promotion candidates in the semantic review output
- [x] Phase D: add tests for structured semantic review output and merged rendering
- [x] Phase D: update Plans #7 and #11 truthfully from implementation evidence
- [x] Verification: run `python scripts/self_test.py`
- [x] Verification: run `python -m pytest tests/test_truth_surface_drift.py tests/test_render_truth_surface_status.py tests/test_semantic_truth_surface_review.py -q`
- [x] Verification: run `git diff --check`
- [x] Phase D: commit the verified semantic-review slice
