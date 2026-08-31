# Scoped maintenance-worktree authority

This completes the consumer first preserved in PR 266, commit
`eab5a7334ddba00cbe828e7865fa2ba264b38a82`. Its documentation is recorded here
to avoid concurrent edits to the operator guide; this is not a second protocol.

Maintenance creation uses the adapter's strict v2 protocol: the response echoes
the exact root, repository identity, remote, operation (`maintenance_worktree`),
and literal branch. The response's mutation-authority label records eligibility;
it is not an authorization for a different operation. A distinct scoped grant
type cannot satisfy generic v1 authority.

Reviewed feature-branch-only governance may permit worktree creation without
granting general mutation, default-branch publication, merging, or deployment.
Provider and consumer reject default targets, ambiguous fields, mismatched
echoes, and checkout-dependent Git branch shorthand. No v2-to-v1 fallback exists.
Install the v2-capable pinned adapter before activating this consumer.

Initial ownership may be narrowed using the existing `write_paths` request
field. Whole-repository `.` ownership overlaps every repository-relative path
in either direction; a narrow lane cannot bypass a broad owner. Disjoint scopes
may coexist. Fresh remote-default verification, native identity, claim checks,
and transactional rollback remain in force.

Verification includes actual scoped-resolver dispatch, invalid and downgraded
responses, shorthand expansion, and real registry tests for disjoint, exact,
and whole-repository foreign ownership.
