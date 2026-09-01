# Hook-First Integration Authority

The sanctioned `make finish` path is the only merge entrypoint. Its existing
canonical branch claim is the integration lease; no second owner registry or
transfer protocol is created. The path emits an assertion before review and
validates it again under the claim-registry lock after the exact-head review
and required-check re-read.

Authority comes from the canonical branch claim, not a shared coordinator
label or a GitHub status. The caller must be the native exact session that owns
one active, healthy, unexpired claim for the PR branch. The assertion binds the
repository, PR, base and head revisions, branch, claim bytes, owner session,
and current lease digest.

The assertion lasts at most ten minutes and cannot transfer ownership. If the
process dies, a sanctioned claim transfer or takeover gives the successor a
new native session; the successor must rerun the review and emit a new
assertion. A stale assertion, changed claim, changed PR target, changed review
spec, stalled/weak claim, or wrong session fails closed.

The assertion does not replace exact-head review, GitHub required CI, branch
protection, or post-merge verification. It only serializes the small protected
merge window without introducing a permanent single-owner coordinator.
