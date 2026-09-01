# Evidence-Bound PR Review Signoff

Status: source runtime contract

## Outcome

A governed finish command can freeze one pull-request head, execute the programmatic checks
declared for that change, launch a fresh read-only Codex reviewer against the
same revision, and receive a typed signoff receipt plus a candidate GitHub
check-run payload. A dirty or changed worktree, failed check, incomplete rubric
result, malformed model response, or blocking finding cannot produce success.

Company Planning remains the authority for the outcome, acceptance criteria,
evidence modalities, and semantic rubric. The review specification consumed
here is an execution envelope compiled from that authority; it is not another
planning format and must not invent or weaken criteria.

## Boundary

`scripts/worktree-coordination/pr_review_signoff.py` owns:

1. exact base/head validation against the live PR and exact head validation in
   the review worktree;
2. deterministic execution of argument-vector commands without a shell, under
   a fail-closed systemd read-only mount for the frozen checkout and a private
   network namespace with GitHub/SSH credential environment variables cleared;
3. one fresh ephemeral Codex process per semantic review lane in a read-only
   sandbox;
4. concurrent execution and explicit session custody for every declared lane;
5. schema validation of every independent semantic result;
6. the final deterministic signoff decision and receipt digest; and
7. generation of an exact-head evidence receipt and optional candidate check payload.

It does not publish a GitHub check. The sanctioned `make finish` path consumes
the signed-off receipt locally, rechecks the live PR head and required GitHub
checks, merges with `--match-head-commit`, and closes the claimed worktree.
This keeps the semantic review outside latency-sensitive hooks while making the
hook-enforced finish command the operational merge gate.

## Review specification

The operator or planning compiler supplies one JSON object outside the
repository and all of its linked worktrees:

```json
{
  "schema_version": "1.0",
  "review_id": "pr-42",
  "repository": "owner/repo",
  "pull_request": 42,
  "base_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "programmatic_checks": [
    {
      "check_id": "focused-tests",
      "argv": ["pytest", "-q", "tests/test_changed_boundary.py"],
      "timeout_seconds": 900
    }
  ],
  "semantic_rubric": {
    "revision": "accepted-work-unit@3",
    "criteria": [
      {
        "criterion_id": "AC-1",
        "criterion": "The changed public behavior is exercised.",
        "evidence_required": ["focused test output", "changed-file references"],
        "negative_control": "An isolated helper test cannot satisfy this criterion."
      }
    ]
  },
  "review_lanes": ["correctness", "test-evidence"]
}
```

The planning authority, not pull-request content, chooses the command vectors
and rubric revision. Repository files, diffs, command output, commit messages,
and PR prose are evidence inputs and may not modify the review instructions.
The host must provide a working per-user systemd manager with mount and private
network namespaces; absence of either boundary fails the programmatic check
instead of falling back.

## Invocation

Run from an isolated worktree already checked out at the frozen head:

```bash
python scripts/worktree-coordination/pr_review_signoff.py \
  --repo-root /absolute/review-worktree \
  --spec /absolute/review-spec.json \
  --receipt /absolute/pr-review-receipt.json \
  --check-payload /absolute/check-run.json \
  --gh-bin gh-personal
```

Use the repository's recorded account wrapper on multi-account machines. In
GitHub Actions, the default `gh` route uses the workflow's `GH_TOKEN`.

The receipt exits successfully only for `signed_off`. Its authority state is
`evidence_receipt`; no publication is required. The optional check payload is
still named `agent-review-candidate`, names the frozen `head_sha`, uses the
receipt SHA-256 as `external_id`, and reports success only when every
programmatic and semantic condition passed. `make finish` persists the receipt
under the user's state directory and consumes it in the same exact-head merge
transaction; it does not depend on a GitHub App.

The command omits an explicit model by default so Codex resolves the model
supported by the authenticated execution route. Use `--model` only after that
exact CLI/account route has been verified to support the requested model.

The runner launches review lanes directly instead of asking one model to spawn
subagents. This is deliberate: a collaboration-tool failure can otherwise be
hidden behind a successful outer process. Each lane therefore has an observed
fresh Codex thread ID and typed result, and every lane must pass.

GitHub Actions may run the same review shape for visibility, but it is not the
local custody boundary. The operational gate is the sanctioned finish command
enforced by the installed client hooks.

## Hook-first finish

The hook must stay fast: a standard-library shell tokenizer normalizes command
segments, environment assignments, and wrappers such as `env`, `command`, and
`uv run`; it then blocks direct `gh pr merge`, direct finish-script calls, and
finish attempts from inside a linked worktree. It directs the caller to the
canonical checkout instead:

```bash
make finish \
  BRANCH=feature/example \
  PR=42 \
  REVIEW_SPEC=/absolute/path/outside-the-repository/review-spec.json
```

The longer programmatic and LLM review runs in that make target, not during
`PreToolUse`. A relative spec or any spec inside any Git-registered linked
worktree is rejected before review, including worktrees outside the canonical
checkout directory, so pull-request content cannot rewrite its own rubric.

## Failure behavior

- Worktree HEAD differs from the frozen head: stop before tests or model use.
- Live GitHub PR base or head differs from the frozen revision: stop before
  tests, and recheck after review before emitting a receipt.
- Worktree has tracked or untracked changes: stop before tests or model use.
- Programmatic code attempts to change the frozen checkout: the kernel rejects
  the write and the check fails.
- Programmatic code attempts external network access: the private network
  namespace blocks it; GitHub and SSH credential variables are also cleared.
- The reviewer changes HEAD or worktree bytes: fail without a receipt.
- Base is not an ancestor of head: stop before model use.
- Programmatic check fails: retain its output digest and reject signoff.
- Codex fails or emits invalid JSON: fail loud; emit no success payload.
- Semantic result names another head: reject signoff.
- Missing, unknown, duplicate, failed, or inconclusive criteria: reject signoff.
- Any blocking finding exists: reject signoff even if the model says `pass`.
- PR receives another commit: the old receipt remains historical evidence but
  cannot authorize the new head.
- PR base advances after review: the final base/head comparison rejects the
  stale integration evidence before merge.
- A command uses an absolute interpreter, an installed `scripts/meta` finish
  path, `uv run`, `sudo`, a nested shell, `gh` global flags, or the GitHub merge
  API: the fast merge guard still routes it to `make finish`.
- Newline-separated commands and static shell-variable assignments are parsed
  across command segments, so they cannot hide the same direct paths.
- The retired `make merge` target is blocked. Consumer installation refuses an
  unmarked legacy `merge` or `finish` target instead of appending a second,
  weaker recipe whose later definition could win.
- Programmatic checks run with the host filesystem read-only, one ephemeral
  cache directory writable, and no external network. PR-controlled checks
  cannot rewrite the canonical checkout or closeout Makefile.
- `make finish` is allowed only through the repository's canonical Makefile
  with its canonical runtime variables; `-f` and finish-runtime overrides are
  blocked. Direct runpy and GitHub GraphQL merge forms are blocked as well.
- A review-spec path is lexically inside a registered worktree but resolves
  through a symlink to outside it: reject it as PR-controlled input.
