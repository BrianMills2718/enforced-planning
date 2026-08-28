# Codex Session Integrity Guard

`scripts/codex_session_integrity_hook.py` is a portable, fail-closed
SessionStart-compatible diagnostic and recovery-bundle generator for malformed
Codex JSONL session records. It is containment, not host-persistence repair:
the guard never rewrites, truncates, moves, or deletes a live session log.

It detects malformed JSON, invalid UTF-8, embedded NUL bytes, and the
NUL-only records observed in an interrupted resume.  Warnings contain only a
path, line, byte offset, and error category; they never put conversation text
into model context. A clean or not-yet-locatable session emits no output. A
malformed session gets one content-addressed bundle under
`~/.codex/recovery/<session-id>/auto-<digest>/` containing the untouched
snapshot, sanitized JSONL archive, readable user/assistant transcript,
metadata-only integrity report, and fresh-thread handoff. Repeated starts reuse
the same bundle instead of copying the log again. On corruption, the hook
returns Codex's supported `continue: false` SessionStart result, surfaces the
warning in the UI, and ends the current turn before more model work can proceed
against untrustworthy resumed history.

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

On a warning, start a fresh session from the generated handoff. The guard cannot
make Codex reload skipped history or prevent an interrupted host write; it makes
corruption visible, stops the damaged thread from continuing, and produces a
safe continuation surface automatically.
