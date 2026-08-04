# Governance Friction Log

Workspace-wide policy feedback is authored in
`~/projects/project-meta/policy_friction.md`; do not append new entries here.
Use `make -C ~/projects/project-meta policy-friction POLICY=<id>
FRICTION=<text> RECOMMENDATION=<text>`. This file is retained only as a legacy
pointer for older Enforced Planning references.

## Entries

<!-- Append new entries below this line -->

### 2026-07-30 — claude-code — unknown
**Friction:** Plan-bound claim enforcement rejected the canonical Inside Success PP-5 work graph because the roadmap goal and filename use PP-5/pp5_ rather than a numbered Plan #N/N_ prefix.
**Impact:** A valid machine work graph could not be claimed through its canonical binding; execution required the explicit allow-unplanned escape hatch, weakening the otherwise valid plan-to-claim linkage.
**Suggestion:** Accept stable nonnumeric goal IDs and verify the declared work graph by repository path plus unit ID, or provide a governed migration that renames canonical goal graphs without breaking references.
**Severity:** medium
