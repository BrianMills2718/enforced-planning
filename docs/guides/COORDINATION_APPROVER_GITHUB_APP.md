# Dedicated Coordination Approver GitHub App

Status: operator guide

## Outcome

`coordination-approval` is authoritative only when a completed successful check
run names the exact pull-request head and comes from the one non-null GitHub App
ID bound to that context in branch protection. Ordinary worker credentials,
another App reusing the name, and a success from an older head cannot approve a
merge.

This is the terminal identity boundary described by
`WORKTREE_COORDINATION_OPERATOR_GUIDE.md`. The source implementation is
`scripts/worktree-coordination/finish_pr.py`; this guide does not create a
parallel approval system.

## Human-owned setup action

While signed in as `BrianMills2718`, create the private GitHub App
`brian-coordination-approver`, install it only on `enforced-planning`, and place
its App ID, installation ID, and generated private key in a coordinator-only
credential service that worker sessions cannot read.

Use these App settings:

- Repository permission: Checks — read and write.
- Repository permission: Pull requests — read-only.
- Repository permission: Metadata — read-only (implicit).
- Subscribe to no events and configure no webhook unless a later reviewed
  producer explicitly needs delivery.
- Keep the App private and limit its installation to the one repository.

The credential location is part of the boundary. Do not store the private key
in the repository, a shared worker environment, or the shared agent key file.
The coordinator producer should receive only a short-lived installation token;
workers should receive neither the private key nor that token.

## Producer custody and liveness

GitHub authenticates the account or App that created an approval; it does not
authenticate the native Codex or Claude session that instructed a shared
credential.  An approval producer therefore needs separate exact-session
custody before it may use either compatibility credentials or the dedicated
App service.

`enforced_planning.coordination_approval` is the canonical custody contract and
`scripts/worktree-coordination/publish_coordination_approval.py` is its operator
entrypoint.  One lease is keyed by repository and pull request and binds all of
these facts for its lifetime:

- exact repository, PR URL, base branch, and 40-character head revision;
- exact candidate sign-off receipt SHA-256;
- compatibility-status versus GitHub-App mode and the protected App ID;
- exact native owner session, revision, heartbeat, expiry, and predecessor
  lease digest.

The lifecycle is deliberately small:

1. `acquire` creates custody only when no lease exists.
2. `heartbeat` is exact-owner and compare-and-swap bound.
3. `transfer` requires the exact owner and retains every target fact.
4. `takeover` requires expiry plus the latest lease digest. Mailbox prose, a
   session ID, or a stale cached lease is insufficient.
5. `release` is exact-owner and leaves an immutable terminal receipt.

Every transition is serialized under one state-root lock and writes an
immutable digest-bound receipt. The short lease means a vanished coordinator
delays integration only until expiry; it can no longer freeze the repository
indefinitely. A healthy owner cannot be taken over.

Before publication, the producer reloads the lease, re-reads the live PR and
branch-protection binding, and refuses a moved head, expired or wrong-session
lease, stale observation, or `coordination-approval-frozen` context. After
publication it re-reads both live PR facts and the exact provider record and
persists one publication receipt. The producer never changes branch protection
and never merges the PR; `finish_pr.py` remains the final live-provenance and
exact-head merge consumer.

Compatibility mode remains migration-only. It accepts a status only when the
creator is the repository owner and `target_url` is the exact PR URL. App mode
accepts only the bound non-null App ID. The CLI publishes compatibility statuses
only; App publication stays inside the coordinator-only credential service.

## Automated verification after setup

The readiness command is read-only:

```bash
python scripts/worktree-coordination/coordination_app_readiness.py \
  --repo BrianMills2718/enforced-planning \
  --branch main \
  --app-id "$COORDINATION_APPROVER_APP_ID" \
  --head-sha "$(git rev-parse HEAD)" \
  --gh-command gh-personal \
  --json
```

It fails unless all of these are true:

1. branch protection binds exactly one `coordination-approval` check to the
   expected positive App ID;
2. required checks are strict and administrator enforcement is enabled;
3. when `--head-sha` is supplied, that exact head has a completed successful
   check from the bound App;
4. deterministic negative probes reject the same check name from another App
   and reject a success attached to an older SHA.

The command never changes repository settings. Capture its JSON output as the
rollout receipt. The `finish_pr.py` compatibility status arm is automatically
disabled once branch protection exposes a non-null App binding, so an ordinary
owner token cannot bypass the App boundary.

## Rollback

Before changing protection, capture the current protection JSON with the
documented personal-account wrapper. If rollout fails, restore that exact
reviewed snapshot, remove the App-bound required check, and keep merging
blocked until the compatibility policy is explicitly selected. Removing the
required check without restoring a reviewed protection state is not a valid
rollback.

Deleting or rotating a key is a GitHub/credential-system action, not a Git
rollback. Revoke the compromised key first, then issue a replacement only to
the coordinator-only credential service and rerun the readiness check.
