# ChatGPT + Remote Desktop Commander governed lanes

This compatibility surface lets a ChatGPT session operating through Remote
Desktop Commander use the same typed worktree, claim, tracker, and canonical-lock
transactions as the framework's native clients without pretending to be Codex,
Claude Code, or OpenClaw.

## Trust boundary

Remote Desktop Commander currently exposes no native per-conversation identifier
to the remote shell. The caller therefore supplies `CHATGPT_SESSION_ID`, a
non-secret lane identifier that remains stable for one ChatGPT work lane. It is
ownership metadata, not authentication material. Do not place tokens, passwords,
API keys, or other credentials in it.

A suitable value is an opaque label such as:

```sh
export CHATGPT_SESSION_ID=rdc-20260906-cybernetic-review
```

The compatibility process registers `chatgpt:<CHATGPT_SESSION_ID>` only in that
process. It does not add ChatGPT to native hook-client dispatch, and it does not
borrow another client's session identity.

## Safety surface

`scripts/chatgpt_rdc.py` accepts only these canonical claim-bootstrap operations:

- `maintenance_worktree`
- `goal_worktree`
- `session_start_or_update`
- `heartbeat`
- `progress`

The adapter deliberately excludes local integration, delegated maintenance,
workspace file moves, deployment, merge, force-push, and arbitrary shell
execution. The request is otherwise validated by the existing strict
`claim_bootstrap` schema, including duplicate-key rejection and exact worktree
request shapes.

## Prerequisite: GitHub transport

Maintenance and goal worktrees establish a fresh remote-default revision before
creating a lane. For private repositories, the machine therefore needs working
noninteractive Git authentication for the repository owner or another identity
with the required access. Verify that separately before invoking the bridge.
The compatibility adapter never reads, exports, creates, or repairs credentials.

## Example maintenance lane

Run from the governed repository root with a stable `CHATGPT_SESSION_ID`:

```sh
/usr/bin/python3 scripts/chatgpt_rdc.py --request-json '{
  "schema_version":"1.0",
  "operation":"maintenance_worktree",
  "agent":"chatgpt",
  "project":"example-project",
  "scope":"chatgpt/review-example",
  "repo_root":"/absolute/path/to/example-project",
  "branch":"chatgpt/review-example",
  "claim_type":"program",
  "write_paths":["src","tests"]
}'
```

The returned JSON includes the canonical transaction receipt plus
`"transport": "remote-desktop-commander"`. Use that worktree for edits and the
repository's canonical verification command (normally `make check`) before any
commit or PR.

If the repository requires a whole-repository bootstrap scope, use the existing
`["."]` contract and narrow the claim through the framework's sanctioned
narrowing path before the first repository write. The compatibility layer does
not weaken that requirement.

## Recommended operating pattern

Treat GitHub as source of truth, create a governed ChatGPT lane from a fresh
remote default, edit only inside the claimed worktree, run the repository's
canonical verification, commit the verified change, and publish a branch/draft
PR when Git authentication is valid. Keep merge and deployment as separate,
explicitly authorized actions.
