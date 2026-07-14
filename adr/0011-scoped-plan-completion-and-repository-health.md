# META-ADR-0011: Separate Plan Completion From Repository Health

**Status:** Accepted
**Date:** 2026-07-14

## Context

`scripts/complete_plan.py` currently makes a bounded plan inherit every failure
in the repository-wide non-E2E suite. That conflates two distinct questions:

1. Did this change satisfy its declared acceptance criteria without a relevant
   regression?
2. Is the entire repository healthy?

The distinction became concrete in project-meta Plan #219. Its governed
Foundation schema fixtures and focused publication checks passed, while the
completion command found 12 remaining failures outside the changed surface.
Six reproduced on the canonical checkout and six came from worktree-root
assumptions; none exercised the plan's files. Repairing them would have
expanded a bounded contract plan into unrelated repository maintenance.

META-ADR-0003 already distinguishes plan completion from a functional
acceptance gate. The implementation had drifted beyond that decision by making
global repository health a prerequisite for every plan regardless of scope.

## Decision

Plan completion has two separately reported verdicts.

### 1. Change gate (always blocking)

The plan's governed required-test manifest, applicable E2E checks, doc/code
coupling checks, and explicit acceptance criteria must pass. Missing or failing
required tests block completion.

### 2. Repository health (always visible, conditionally blocking)

The repository-wide non-E2E suite still runs. If it passes, the plan records a
repository-green completion. If it fails, the completion tool reruns the same
suite at the merge base in a detached sibling worktree, using the same Python
interpreter and command, then compares machine-readable test identities.

- A failure absent from the baseline blocks completion as a new regression.
- A baseline failure whose test file changed in the plan blocks completion;
  lexical identity alone cannot prove the failure is unchanged.
- An unchanged failure reproduced in the same worktree layout remains visible
  repository debt but does not block the bounded plan.
- A missing, timed-out, or unparsable baseline is `unavailable`, not a pass, and
  blocks completion.

The resulting completion label is either:

- `Complete` — change gate passed and the repository suite is green; or
- `Complete (scoped; repository baseline degraded)` — change gate passed and
  only unchanged baseline failures remain.

There is no implicit force flag or silent waiver for new or overlapping
failures. A future waiver mechanism must require a durable decision reference
and record it in completion evidence before adoption.

Release, promotion, and periodic repository-health gates may still require a
fully green suite. They are stronger claims than bounded plan completion and
must be configured as such rather than inferred from the word "complete."

## Alternatives Considered

### Keep the unconditional full-green gate

Rejected because it makes unrelated repository debt an unbounded dependency of
every plan. It encourages false closure, bypasses, or scope expansion instead
of honest evidence.

### Stop running the repository-wide suite

Rejected because required-test manifests can be incomplete. The global run is
valuable regression visibility even when its pre-existing failures are not all
owned by the current plan.

### Mark every known failure `xfail`

Rejected as the default because it edits product test semantics to accommodate
workflow state and can make a degraded repository appear green. Pytest itself
describes non-strict xfail as a manual quarantine that can be dangerous when
left permanently.

### Store a hand-maintained failure allowlist

Rejected for the first implementation because it can become stale, be widened
after results are known, and fail to reproduce path-sensitive worktree errors.
A same-command run at the merge base is the stronger comparison.

### Allow `--force` to bypass repository failures

Rejected because it would erase the distinction between evidence and operator
intent. Uncertain comparisons remain blocking until a governed waiver contract
is designed.

## Consequences

### Positive

- Bounded plans can close without absorbing unrelated cleanup.
- Repository degradation remains explicit in the plan evidence and status.
- New failures remain blocking, including failures in changed baseline test
  files.
- Worktree-path assumptions are compared under symmetric directory layout.
- The implementation realigns with META-ADR-0003's plan/gate hierarchy.

### Negative

- A degraded current run costs a second suite execution.
- Test identity comparison cannot prove two failures have the same root cause;
  the changed-test-file rule is a conservative partial guard.
- Source changes can alter the cause of an unchanged test failure without
  changing its test identity. Required-test selection and future impact mapping
  remain important.
- Non-pytest repositories need a separate result adapter before they can use
  baseline comparison.

## Revisit Triggers

Revisit this decision if any of the following occurs:

1. A plan introduces a regression that the required tests omit and the
   baseline comparison classifies as unchanged.
2. Baseline worktrees routinely cannot reproduce consumer environments.
3. Suite runtime makes same-commit comparison disproportionate; a signed,
   expiring baseline artifact may then be preferable.
4. Impact mapping becomes reliable enough to classify affected failures beyond
   direct test-file overlap.
5. A non-pytest result contract becomes a required portable capability.

## Research Basis

| Source | Relevance |
|---|---|
| `project-meta/policy_friction.md`, “Bounded documentation plan cannot close against unrelated global failures” | Concrete failure case and recommended scoped/baseline split. |
| [Pytest JUnit XML output](https://docs.pytest.org/en/stable/how-to/output.html#creating-junitxml-format-files) | Stable built-in machine-readable result surface used for comparison. |
| [Pytest skip/xfail guidance](https://docs.pytest.org/en/stable/how-to/skipping.html) | Alternative expected-failure mechanism and its reporting tradeoffs. |
| [Git worktree documentation](https://git-scm.com/docs/git-worktree.html) | Supported detached sibling checkout mechanism for the merge-base control run. |
| `adr/0003-plan-gate-hierarchy.md` | Existing authority separating plan completion from stronger E2E acceptance gates. |

