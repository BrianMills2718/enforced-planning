# Plan 135 native v5 independent sign-off

Revision reviewed: `4864d15be6e44e557925d6271a05e8cccccb1cbc`

Verdict: **ACCEPTED**.

Supported decision: reject Prompt 1.2 with the `claude-code/sonnet` route for
promotion, retain correction learning as manual/off, and stop spending further
holdouts or retuning on this unchanged route. This does not authorize blocking
mode or native hook activation.

The verifier independently reproduced the candidate SHA-256, exact 128/128
source population, 32-session and two-client coverage, prediction event IDs,
classifications, rationale hashes, Git artifact ordering, and privacy-reduced
annotation reconstruction. V5 contains 34 corrections, 88 non-corrections, and
six ambiguous boundaries. It detected 24 corrections, missed ten, produced
three false positives, and produced no enforcement-positive ambiguous verdict.
Codex recall was 12/18 with all three false positives; Claude Code recall was
12/16 with no false positives.

Telemetry showed 32/32 successful calls, zero errors, zero retries, `$0.00`
recorded marginal cost, and 643.348 seconds aggregate model latency. The v4
structured-schema repair therefore generalized operationally across the full
holdout; it did not improve classifier semantics, and no such claim is made.

The documented promotion gates fail independently: 70.6% recall is below 90%,
and three false positives exceed zero. V5 alone supports route rejection; v2 is
corroborative development evidence only. More holdouts of the unchanged route
would measure a rejected candidate rather than resolve a decision uncertainty.

The verifier identified two future-result contract defects: success status used
100% accuracy instead of the declared 90% recall threshold, and a Claude-named
control metric was vacuous when no control rows existed. Both were corrected
after the frozen result in the separately committed schema 1.1 harness change;
they do not alter v5 or this sign-off.

Limitations: this corpus covers Brian's Codex and Claude Code sessions, not
other users or OpenClaw. Durable artifacts prove independent label files and
commit ordering but do not independently preserve annotator identity receipts.
