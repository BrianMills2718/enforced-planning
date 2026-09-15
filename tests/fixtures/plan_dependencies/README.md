Fixture corpus for `tests/test_plan_dependencies.py` (project-meta Plan #289).

- `alpha/` is registered as project id `alpha`; each plan exercises one contract rule.
- `beta/` is registered as `beta_tools` (folder name differs from the id) and holds
  one unconverted plan that `alpha#1` depends on through its derived id `beta-tools#7`.
