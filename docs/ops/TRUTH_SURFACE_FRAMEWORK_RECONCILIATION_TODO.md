# Framework Truth-Surface Reconciliation TODO

## Sprint Goal

Make the framework's onboarding, installer behavior, and internal truth surfaces agree before the next adoption or semantic-review wave.

## Ordered TODOs

- [x] Phase A: define the bounded reconciliation plan and sprint tracker
- [x] Phase A: plan index references this sprint via Plan #10 in CLAUDE.md
- [x] Phase B: reconcile installer behavior with README and getting-started guidance
      (install.sh now copies truth-surface scripts in --full mode; GETTING_STARTED.md updated)
- [x] Phase B: make truth-surface template guidance generic for consumer reuse
      (truth_surface_drift.yaml.example now copied in --full mode)
- [x] Phase C: truthfully close the scoped-validation TODO/tracker surfaces
      (TRUTH_SURFACE_SCOPE_TODO.md checkbox corrected — commit did happen as Plan #9)
- [x] Phase C: update Plans #6 and #8 with scoped follow-on notes
- [x] Phase D: restate Plan #1 in current capability/boundary vocabulary
- [x] Phase D: define the next bounded follow-on after this cleanup
      (Next: cross-repo governance — Phase 6 of ROADMAP, after V2 proven in 3+ repos)
- [x] Verification: run `python scripts/self_test.py` — 2 pre-existing broken links (not from this sprint)
- [x] Verification: run `git diff --check`
- [x] Phase D: commit the verified reconciliation slice
