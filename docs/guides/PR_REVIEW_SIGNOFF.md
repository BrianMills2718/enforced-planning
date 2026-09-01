# Evidence-Bound PR Review Signoff

Status: source runtime contract

## Outcome

A coordinator can freeze one pull-request head, execute the programmatic checks
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

1. exact base/head validation in the review worktree and against the live PR;
2. deterministic execution of argument-vector commands without a shell, under
   a fail-closed systemd read-only mount for the frozen checkout;
3. one fresh ephemeral Codex process per semantic review lane in a read-only
   sandbox;
4. concurrent execution and explicit session custody for every declared lane;
5. schema validation of every independent semantic result;
6. the final deterministic signoff decision and receipt digest; and
7. generation of an exact-head, non-authoritative candidate check payload.

It cannot emit a check named `coordination-approval` and does not publish a
GitHub check. Authoritative publication belongs to the coordinator-only
GitHub App described in `COORDINATION_APPROVER_GITHUB_APP.md`; worker sessions
must not receive that App's private key or installation token.

## Review specification

The trusted coordinator supplies one JSON object:

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

The coordinator, not pull-request content, chooses the command vectors and
rubric revision. Repository files, diffs, command output, commit messages, and
PR prose are evidence inputs and may not modify the review instructions.
The host must provide a working per-user systemd manager; absence of the
read-only mount boundary fails the programmatic check instead of falling back.

## Invocation

Run from an isolated worktree already checked out at the frozen head:

```bash
python scripts/worktree-coordination/pr_review_signoff.py \
  --repo-root /absolute/review-worktree \
  --spec /absolute/review-spec.json \
  --receipt /absolute/pr-review-receipt.json \
  --check-payload /absolute/check-run.json
```

The receipt exits successfully only for `signed_off`. A signed receipt remains
`candidate_only`; the check payload is named `agent-review-candidate`, names
the frozen `head_sha`, uses the receipt SHA-256 as `external_id`, and reports
success only when every programmatic and semantic condition passed. A separate
coordinator service must validate that receipt and publish the App-bound
`coordination-approval` check. Until that App is bound, no output from this
worker is authoritative merge approval.

The command omits an explicit model by default so Codex resolves the model
supported by the authenticated execution route. Use `--model` only after that
exact CLI/account route has been verified to support the requested model.

The runner launches review lanes directly instead of asking one model to spawn
subagents. This is deliberate: a collaboration-tool failure can otherwise be
hidden behind a successful outer process. Each lane therefore has an observed
fresh Codex thread ID and typed result, and every lane must pass.

The OpenAI Codex GitHub Action can trigger the same review shape on PR events,
but an ordinary Actions identity is not the coordinator identity. Automatic
authoritative publication therefore requires a coordinator-owned trigger that
runs this command and submits the resulting payload using the bound GitHub App.

## Failure behavior

- Worktree HEAD differs from the frozen head: stop before tests or model use.
- Live GitHub PR head differs from the frozen head: stop before tests, and
  recheck after review before emitting a receipt.
- Worktree has tracked or untracked changes: stop before tests or model use.
- Programmatic code attempts to change the frozen checkout: the kernel rejects
  the write and the check fails.
- The reviewer changes HEAD or worktree bytes: fail without a receipt.
- Base is not an ancestor of head: stop before model use.
- Programmatic check fails: retain its output digest and reject signoff.
- Codex fails or emits invalid JSON: fail loud; emit no success payload.
- Semantic result names another head: reject signoff.
- Missing, unknown, duplicate, failed, or inconclusive criteria: reject signoff.
- Any blocking finding exists: reject signoff even if the model says `pass`.
- PR receives another commit: the old receipt remains historical evidence but
  cannot authorize the new head.
