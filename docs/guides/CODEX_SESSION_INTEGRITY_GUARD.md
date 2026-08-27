# Codex Session Integrity Guard

`scripts/codex_session_integrity_hook.py` is a portable, non-blocking
SessionStart-compatible diagnostic for malformed Codex JSONL session records.
It is containment, not repair: Codex owns host persistence and the guard never
rewrites, truncates, moves, or deletes a session log.

It detects malformed JSON, invalid UTF-8, embedded NUL bytes, and the
NUL-only records observed in an interrupted resume.  Warnings contain only a
path, line, byte offset, and error category; they never put conversation text
into model context.  A clean or not-yet-locatable session emits no output.

For a one-off metadata-only report:

```bash
printf '%s' '{"session_id":"SESSION_ID","hook_event_name":"SessionStart"}' | \
  python scripts/codex_session_integrity_hook.py \
  --session-file ~/.codex/sessions/.../rollout-...jsonl \
  --report /tmp/codex-session-integrity-report.json
```

The source repo does not install a global `~/.codex/config.toml` hook: that
file is user-host configuration, whereas this repository's installer owns
only repository-local generated hook surfaces.  A local operator who chooses
to enable it can add this command to their existing `[[hooks.SessionStart]]`
list after retaining their current hooks:

```toml
[[hooks.SessionStart.hooks]]
type = "command"
command = "python3 /absolute/path/to/enforced-planning/scripts/codex_session_integrity_hook.py"
timeout = 5
statusMessage = "Checking Codex session integrity"
```

On a warning, preserve the original log and start a fresh session.  The guard
cannot make Codex reload skipped history; it only makes the boundary explicit.
