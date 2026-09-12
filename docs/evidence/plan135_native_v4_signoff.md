# Plan 135 native v4 independent sign-off

Revision reviewed: `d7949af566021eca4f1dccf3dbf866a867f868f9`

Verdict: **REJECTED** for the proposed composite decision; **accepted** for the
narrower decision to classify v4 invalid/no-score, retain manual/off, and spend
no further fresh holdout until the evaluation mechanism changes.

The verifier independently reproduced 128 selected exchanges across 16 Codex
and 16 Claude Code sessions, 123 blind-label agreements, five adjudications,
29 corrections, 97 non-corrections, two ambiguous boundaries, exact-source
loading, privacy-reduced artifact ordering, and the focused test suite. Read-only
telemetry showed eight completed calls followed by batch nine failing with
`ResultError`; therefore v4 has no valid classifier score.

The harness repair generalizes durable invalid-result retention to both batch
ID mismatches and evaluation exceptions at unit-test level. It has not yet been
exercised by an authentic post-fix failing replay. The verifier correctly
rejected declaring the cursor circuit-broken because its canonical state records
two same-boundary failures against a maximum of three. The supervisor selected
`repair`, not `circuit_break`.

Required next action: repair the evaluation mechanism using v4 only as
development evidence, validate the changed route on contaminated cases, and
preserve unseen holdouts until that validation passes. The active execution
cursor must receive a lawful machine-owned disposition before PR integration.
