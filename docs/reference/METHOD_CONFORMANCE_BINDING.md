# Method-conformance receipt binding for plan-backed claims

Source: company-planning Plan #48, unit `WU-CP-MCR-002`. Implementation:
`resolve_method_conformance_binding` in `enforced_planning/coordination_claims.py`, called from
`resolve_canonical_work_unit_binding` (claim admission) and
`check_plan_start_readiness` (plan-start gate).

## Ownership

Company Planning owns method profiles, compilation, validation, and the
adoption decision. Its adoption gate is the only writer of a
`PlanningMethodConformanceReceiptV1` (contract:
company-planning `plugins/company-planning/contracts/method-conformance/README.md`).
Enforced Planning only re-resolves the receipt at the exact plan-authority
revision; it does not re-run or copy method rules.

## Rule

`meta-process.yaml` declares the requirement per repository:

```yaml
meta_process:
  plans:
    method_conformance:
      mode: required   # default: off
```

A plan-backed write claim (one bound to a work graph unit) passes
`--method-receipt <repo-relative path>` and `--method-receipt-sha256 <digest>`
from the plan's adoption decision. Admission refuses, with a stable code:

| Code | Condition |
| --- | --- |
| `missing_method_receipt` | mode `required` and no receipt named, or only one of the two flags |
| `method_receipt_missing` | receipt not committed at the plan-authority revision |
| `method_receipt_digest_mismatch` | receipt bytes do not hash to the claimed digest |
| `method_receipt_invalid` | not a `PlanningMethodConformanceReceiptV1` |
| `method_receipt_not_passing` | receipt `result` is not `pass` |
| `method_receipt_plan_mismatch` | receipt binds a different numbered plan |
| `stale_plan_revision` | plan bytes at this revision differ from the receipt's plan digest |
| `method_receipt_not_declared_by_plan` | plan front matter `method_conformance_receipt` names another path |
| `method_receipt_on_unplanned_claim` | an unplanned or goal claim cites a receipt |

With mode `off`, a claim naming no receipt is admitted by the existing rules,
and a cited receipt is verified the same way. Explicitly unplanned maintenance
keeps its separate admission rule and can never cite plan conformance.

The admitted claim retains `method_receipt_ref` and `method_receipt_sha256`
beside its plan, work-graph, and start-revision identities.

Not covered: `session_start`/`make worktree` do not yet forward the two flags,
so in a `required` repository those entrypoints refuse plan-backed claims
(fail closed) until they do.
