# Plan 70 Progress-Lease Contract Mockup

This is the additive claim/status seam approved for implementation. Existing
claims without these fields remain valid.

## Fresh heartbeat and fresh progress

```yaml
agent: codex
project: onto-canon6
scope: plan0145-step5
status: active
heartbeat_at: "2026-07-15T00:49:00+00:00"
progress_at: "2026-07-15T00:44:57+00:00"
progress_kind: verified_commit
progress_ref: 1f5eed9f9fec1a6f3f73bad91247641e74cc75d7
next_action: add complete V1/V2 coordinate-domain proof
```

Rendered status:

```text
onto-canon6:plan0145-step5 [healthy]
last progress: verified_commit 1f5eed9 (4 minutes ago)
next: add complete V1/V2 coordinate-domain proof
```

## Fresh heartbeat but expired progress lease

```yaml
heartbeat_at: "2026-07-15T06:49:00+00:00"
progress_at: "2026-07-15T00:44:57+00:00"
progress_kind: verified_commit
progress_ref: 1f5eed9f9fec1a6f3f73bad91247641e74cc75d7
next_action: add complete V1/V2 coordinate-domain proof
```

Rendered status with a 60-minute progress deadline:

```text
onto-canon6:plan0145-step5 [stalled: progress_deadline_exceeded]
runtime heartbeat: fresh
last durable progress: verified_commit 1f5eed9 (6 hours ago)
required action: finish the bounded increment, hand off, or release
```

The claim remains active. No file is deleted, no claim is released, and no
other session receives write authority automatically.

## Known long operation

```yaml
progress_at: "2026-07-15T00:44:57+00:00"
progress_kind: verified_commit
progress_ref: 1f5eed9f9fec1a6f3f73bad91247641e74cc75d7
next_action: inspect full-suite result and commit only if green
expected_quiet_until: "2026-07-15T02:15:00+00:00"
quiet_reason: full repository test suite is running
```

Before the declared deadline, status remains `healthy`. The quiet interval does
not change `progress_at`. After it expires, ordinary progress-deadline
classification resumes.

## Explicit progress command

```bash
python scripts/check_coordination_claims.py \
  --progress \
  --agent codex \
  --project onto-canon6 \
  --scope plan0145-step5 \
  --progress-kind blocker \
  --progress-ref ISSUES.md#plan0145-step5-coordinate-domain-proof \
  --next-action "repair the bridge before building the envelope"
```

A heartbeat command never changes any progress field.

