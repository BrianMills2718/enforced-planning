# Evidence-Bound PR Review Signoff

Status: source runtime contract

## Outcome

A coordinator can freeze one pull-request head, execute the programmatic checks
declared for that change, launch a fresh read-only Codex reviewer against the
same revision, and receive a typed signoff receipt plus a GitHub check-run
payload. A changed head, failed check, incomplete rubric result, malformed
model response, or blocking finding cannot produce success.

Company Planning remains the authority for the outcome, acceptance criteria,
evidence modalities, and semantic rubric. The review specification consumed
here is an execution envelope compiled from that authority; it is not another
planning format and must not invent or weaken criteria.

## Boundary

`scripts/worktree-coordination/pr_review_signoff.py` owns:

1. exact base/head validation in the review worktree;
2. deterministic execution of argument-vector commands without a shell;
3. a fresh ephemeral Codex process in a read-only sandbox;
4. explicit delegation of each semantic review lane to a fresh subagent;
5. schema validation of the combined semantic result;
6. the final deterministic signoff decision and receipt digest; and
7. generation of the exact-head GitHub check-run payload.

It does not publish a GitHub check. Publication belongs to the coordinator-only
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

## Invocation

Run from an isolated worktree already checked out at the frozen head:

```bash
python scripts/worktree-coordination/pr_review_signoff.py \
  --repo-root /absolute/review-worktree \
  --spec /absolute/review-spec.json \
  --receipt /absolute/pr-review-receipt.json \
  --check-payload /absolute/check-run.json
```

The receipt exits successfully only for `signed_off`. The check payload names
the frozen `head_sha`, uses the receipt SHA-256 as `external_id`, and reports
success only when every programmatic and semantic condition passed.

The command omits an explicit model by default so Codex resolves the model
supported by the authenticated execution route. Use `--model` only after that
exact CLI/account route has been verified to support the requested model.

The OpenAI Codex GitHub Action can trigger the same review shape on PR events,
but an ordinary Actions identity is not the coordinator identity. Automatic
authoritative publication therefore requires a coordinator-owned trigger that
runs this command and submits the resulting payload using the bound GitHub App.

## Failure behavior

- Worktree HEAD differs from the frozen head: stop before tests or model use.
- Base is not an ancestor of head: stop before model use.
- Programmatic check fails: retain its output digest and reject signoff.
- Codex fails or emits invalid JSON: fail loud; emit no success payload.
- Semantic result names another head: reject signoff.
- Any criterion fails or is inconclusive: reject signoff.
- Any blocking finding exists: reject signoff even if the model says `pass`.
- PR receives another commit: the old receipt remains historical evidence but
  cannot authorize the new head.
