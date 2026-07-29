# Plan #109: Artifact Creation and Directory Policy Enforcement

**Status:** 🚧 In Progress — portable mechanism and consumer observe pilot implemented; publication and observation window pending
**Type:** implementation
**Priority:** High
**phase_ref:** "Phase 9"
**goal_ref:** "documentation-integrity"
**Blocked By:** None
**Blocks:** truthful anti-proliferation enforcement in governed repositories

## Outcome

When an agent proposes a new controlled tracked file, the repository either
accepts it under an allowed directory and durable intent record or rejects it
before mutation with an exact reason, receipt, recovery path, and feedback
route. Existing files, conventional source/tests outside selected globs, and
legacy corpus debt are not silently brought into scope.

## Canonical Example

With a repository configured to control `docs/**/*.md`, creation of
`docs/new-status.md` without an exact registry record is denied before write.
After the registry records its distinct concern, authority, lifecycle,
discoverability, and separate-file need, the same creation is allowed. A
temporary `misc/note.md` is allowed only as non-authoritative quarantine with
an intended destination and a timezone-aware expiry inside the configured TTL.

## Contracts

- Repository configuration selects `off | observe | enforce`, a directory
  policy, and the existing relationship/intent registry.
- Directory rules define controlled globs, allowed kinds and authorities,
  generated-only roots, and an optional expiring quarantine.
- Every controlled new artifact requires one exact intent record before file
  creation. Canonical concern ownership is unique among active records.
- Native Claude/Codex hooks and the staged-candidate check share one evaluator.
- Content-free local JSONL receipts record decisions, reason codes, target
  paths, latency, and step-down identity. Feedback is a separate receipt-bound
  stream with append-only dispositions and never changes policy automatically.
- The bounded installation profile adds only artifact-creation support; it does
  not require or refresh read-gating and mailbox machinery.
- Observe mode always permits the write while preserving the decision that
  enforcement would have made. Enforce mode denies deterministic violations.

## Capabilities

- **Repository policy selection:** each consumer declares controlled globs,
  allowed directory classes, and an explicit `off | observe | enforce` mode.
- **Pre-mutation client enforcement:** Claude and Codex adapters normalize
  native write events into one deterministic decision contract.
- **Bypass-resistant candidate enforcement:** staged and audit paths reuse the
  evaluator for writes that did not traverse a supported native hook.
- **Operational learning:** content-free receipts, aggregate latency/reason
  reports, and append-only feedback dispositions support calibrated promotion
  and visible step-down.

## Thin Slices

1. **Portable mechanism:** typed evaluator, native hooks, installer support,
   staged check, report, feedback, both-sign fixtures, and reference docs.
2. **Inside Success observe pilot:** control newly created human-authored
   Markdown under its declared planning, roadmap, docs, wiki, generated, and
   misc roots; inspect false positives and p95 latency.
3. **Promotion:** enable blocking only for the calibrated Markdown class. Keep
   broader code/data classes in observe or outside scope until similarly
   evidenced.
4. **Fleet rollout:** install only after repository-owned directory policies
   exist; do not infer them from generic path names.

## Acceptance

- Positive registered creation passes.
- Missing intent, wrong directory class, duplicate canonical concern,
  generator-free generated output, and invalid quarantine all fail loudly.
- Observe and enforce return the same semantic finding but different mutation
  decisions.
- Existing files and paths outside controlled globs remain unaffected.
- Every aggregate report steps down to exact receipt IDs.
- Friction and recommendations can be recorded against exact receipts and later
  dispositioned without erasing the original evidence.
- Hook generation preserves existing hooks and remains idempotent.
- Installed Claude and Codex adapters pass a real registered-creation control
  and deny a missing-intent control through their native payload boundaries.
- The consumer pilot publishes decision counts, reason counts, latency, and
  feedback before promotion.

## Failure and rollback

Malformed policy, registry, or native payload fails loud. A false-positive
cluster returns the consumer to `observe`; receipts remain evidence and the
policy is narrowed rather than bypassed silently. Removing the explicit config
or selecting `off` removes hook wiring on the next installer refresh.

## Non-goals

- Classifying or rewriting every legacy artifact.
- Reading patch or document contents into observability logs.
- Replacing claim ownership, read-gating, coupling checks, or human review.
- Treating `misc/` as durable authority or allowing production dependencies on
  quarantined artifacts.
