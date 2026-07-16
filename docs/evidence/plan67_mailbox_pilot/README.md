# Plan 67 bidirectional mailbox pilot

Observed at 2026-07-16T00:20:57Z through 2026-07-16T00:21:21Z using
the source CLI wrappers on the Plan 67 Slice 2 worktree.

Two isolated live claim identities were created:

- `codex:pilot-67`
- `claude-code:pilot-67`

The Codex identity sent `msg_01f0211632f09dce3753f8c3babee87d` to the
Claude identity. The Claude-facing inbox CLI observed it and appended
`rcpt_fe186f00a99414b7185317800c5ae1c7`; the recipient then explicitly
acknowledged it with `rcpt_410b542bbddc14bc840bd01a664955cc`.

The Claude identity sent `msg_353d54355bb0be31632037954588e792` in the
reverse direction. The Codex-facing inbox CLI observed it and appended
`rcpt_cf88cc8616e22905d5a993e0e0879a20`; the recipient then explicitly
acknowledged it with `rcpt_1161c14a3def45f2060eed22cfe29b55`.

Both final status projections were `acknowledged`, with distinct observation
and acknowledgement receipts. The exact identity claims and integrity-wrapped
source records are retained beside this file.

This is observed cross-process CLI and storage evidence. The identities are
bounded pilot identities, not two independently reasoning model sessions. It
proves that the shared adapters preserve bidirectional message, observation,
and acknowledgement semantics; it does not prove event-driven interruption of
an arbitrary existing Claude or Codex TUI.
