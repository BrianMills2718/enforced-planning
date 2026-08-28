# Hook Lifecycle and Feedback

Native lifecycle events describe different boundaries. Treating them as synonyms
creates false denials and hides unfinished work.

- **Turn end** (`Stop`) is an ordinary response-yield check. Derived claim state is
  repaired within a 1.5-second internal attempt, leaving margin inside the native
  hook timeout; projection-only unavailability warns and allows
  the response. Known dirty state and active mailbox requests still deny the turn.
- **Progress checkpoint** records durable advancement while the same lane continues.
- **Agent rotation / handoff** transfers or preserves custody for another runtime.
- **Lane close** is the explicit `session-close` transaction. It remains fail closed
  on claim, mailbox, Git, or recovery-evidence errors.
- **Goal complete** is an evidence-backed outcome decision, not a synonym for a clean
  turn or a merged commit.

`SessionStart` is advisory and read-only with respect to the claim registry: it does
not heartbeat claims or rebuild the derived projection synchronously.

Run `make hook-feedback-report` to group existing content-free completed receipts by
hook, version, event, decision, and reason. Each group retains exact receipt IDs. When
a recurrent group merits ecosystem action, use those IDs as evidence for Plan #111's
`make ecosystem-feedback ARGS='record ...'` workflow. The report never copies prompt,
response, session, or tool-input content and does not create a second feedback store.

Historical `repository_closeout_*` reason codes remain reportable as evidence from
older hook revisions; new ordinary-turn reasons use `turn_end_*` vocabulary.
