# Control ablation — 2026-08-23

Every claim below was produced by **executing** the control against the route in
question, not by reading its source. Where a control ships a negative control,
that negative control was run too. Where one did not, a known-bad case was
constructed and run before any green result was trusted.

Scope: the three controls named as highest-value-unverified in
`agentic-engineering-system/docs/handoffs/2026-08-23-session-checkpoint.md` §6.1,
plus the canonical checkout lock merged the same day.

Verdict summary:

| Control | Claimed tier | Observed tier | Binds? |
| --- | --- | --- | --- |
| Read-first gate | Enforced | Enforced, but trivially satisfiable | Partially |
| Canonical checkout lock | Enforced | Enforced when fresh; **silently degrades** | No, on the live repo |
| Pre-write claim gate | Enforced | **Unenforced** | No |
| Landscape / prior-art rule | Measured (report-only) | Measured (report-only) | Yes, as documented |

---

## 1. Read-first gate — Enforced, but satisfiable without reading

Route: `PreToolUse` on `Bash|Read|Grep|Glob|Edit|Write`,
`agent-skills/hooks/read_first_gate.py`.

It does fire. It blocked the first command of this session.

Three defects, each reproduced:

**1a. The first read deadlocks through Bash, and the failure message is wrong
about it.** The message states "Reading by any route counts, including
cat/sed/grep." It does not. `cat ROADMAP.md` — a declared document — was blocked
by the hook *before the read could occur*, as was `cat CLAUDE.md`. Only the
native `Read` tool cleared the gate. Under bypass-permissions mode, where the
operating instruction is to prefer Bash for file reads, the documented recovery
route is the one route that cannot work. The escape hatch named in the failure
message is false.

**1b. It gates on path mention, not on read intent.** This command was blocked:

    for r in .../project-meta .../enforced-planning .../ac16 ...; do
        canonical_lock.py --status "$r"; done

No file was being read; it queried lock state. One path token inside a gated
repo blocked the whole compound command, including the four unrelated
repositories in it. The same happened for a `stat`/mode inspection in
`ecosystem-ops`, whose declared reading is UI stack policy — unrelated to file
permissions.

**1c. A token read satisfies it.** Reading **two lines** of
`ecosystem-ops/ui/registry.yaml` — `version: 1` and `updated: 2026-07-21` —
cleared the gate for the entire repository. The previous session closed the
`echo model.md` basename-substring hole; a genuine two-line `Read` still clears
it. The gate confirms that a file was opened. It cannot confirm that a model was
acquired, which is the behaviour it exists to produce.

Side effect worth noting: clearing it injected ~7,000 tokens of repository
instructions into context as a consequence of a two-line read.

## 2. Canonical checkout lock — correct when fresh, silently degraded in place

Route: `enforced-planning/scripts/worktree-coordination/canonical_lock.py`.

**The mechanism is sound.** Its own `--self-test` / `--self-test-unlocked` pair
is the only honest negative control found in this sweep: locked probes report
`BLOCKED`, unlocked probes report `BREACH`. Both were run and both behaved.

**A freshly locked repository is genuinely protected.** `--reconcile` locked
`ecosystem-ops` during this session; its directories became `dr-xr-xr-x` and
file creation failed with `Permission denied`. Verified immediately after the
lock was applied.

**The live lock on `project-meta` was not protecting it.** Same code, same
receipt, `--status` reporting `"locked": true`:

- all 144 directories recorded in the receipt were mode `0755` (writable);
- tracked files were correctly `0444`;
- creating a new file in the repository root **succeeded**;
- hard-linking a tracked file **succeeded**, proving directory write access and
  therefore that any tracked file could be deleted or renamed;
- only in-place overwrite of a tracked file was blocked.

The lock was blocking the least destructive operation and permitting the most
destructive ones. Corroboration independent of the probe: `git status` in that
repository showed `.doc-coupling-acks` as **deleted** while the repository was
nominally locked.

Root cause is decay, not a defect in `lock_repo()`: something restored directory
write bits after the lock was applied. The important gap is that **nothing ever
re-verifies the boundary**. `--status` checks that a receipt file exists, not
that the modes it recorded still hold, so a lock that has stopped working
reports as healthy indefinitely.

This is the failure class the handoff named — present, configured, and not
producing the behaviour it exists to produce — occurring in the control merged
to prevent it.

Fix implemented in this lane: mode verification, a `degraded` verdict, a
`--verify` flag that exits non-zero, and drift repair in `--reconcile`.

## 3. Pre-write claim gate — Unenforced

Reported as a deployed control. It is not deployed.

**3a. `scripts/prewrite_claim_gate.py` is wired in zero repositories.** No
`settings.json` or `settings.local.json` anywhere under `~/code` references it.
It exists, it has a `--help`, and it is listed in the repository's own command
table, which reads as availability.

**3b. The hook that *is* wired does not deny.** `coordination_hook.py` runs
`PreToolUse` on `Bash|Edit|Write` and its `MUTATION_TOOL_NAMES` does include
`bash`, contrary to the handoff's note that it is `Edit|Write`-only. Executed
directly with a complete payload — a `Write` to `project-meta/PROJECT_GRAPH.json`
from a session holding no claim there — it exits `0` silently.

**3c. Confirmed live, twice.** Using the real `Write` tool:

- a file was created **outside** this lane's declared claim write paths
  (`Makefile`, `templates/…`, `canonical_lock.py`, `tests`) — permitted;
- a file was created in **canonical `project-meta`**, a repository where this
  session holds no claim and three other sessions held live lane claims, and
  whose lock reported `"locked": true` — permitted.

Both probe files were removed; `git status` confirmed no residue.

So the gate enforces neither *whether* a claim is held nor *where* a claim
permits writing. Two independent methods agree: direct hook execution and a live
tool call.

## 4. Landscape / prior-art rule — Measured, and honest about it

`enforced_planning/plan_validation.py` parses a `Landscape disposition` and
reports it. Negative control: a plan authored with no disposition produced

    Landscape disposition: (missing)
    WARNINGS (non-blocking):
      - missing_landscape_disposition: … this is report-only during rollout.

This is a correctly labelled `Measured` control. It does what it claims, and
Plan #101 explicitly designed it to report rather than block.

**The gap is reachability, not honesty.** It runs only against authored numbered
plans. Unplanned maintenance lanes never invoke `validate_plan.py`. The near-miss
it exists to prevent — a shell parser nearly built for a problem the kernel
already solves — happened on the unplanned path, where this check cannot fire.

## 5. Bonus finding — a claim reader that reports the opposite of the truth

Not one of the three controls, but found while establishing ground state, and
the same failure class.

`scripts/worktree-coordination/check_claims.py --list` reports:

    No active claims.
    ...
    lock-integrity-and-unplanned-session-start | !! ACTIVE (no claim)
    !! WARNING: ACTIVE WORKTREES WITHOUT CLAIMS
    Another CC instance may be working in these worktrees!

At that same moment `scripts/check_coordination_claims.py --list` — the
canonical reader — showed seven live claims, including this session's claim on
exactly the lane being flagged as unclaimed.

Cause: `check_claims.py` reads a superseded per-repo store,
`.claude/active-work.yaml`, not the canonical
`~/.claude/coordination/claims/`. It is a legacy tool that still lives in the
same `worktree-coordination/` directory as the current tooling, under a name one
word away from the canonical one.

Why it matters more than an ordinary stale script: an agent that runs it
concludes either that a claimed lane is free to take, or that a phantom instance
is at work. Both readings are wrong and both are actionable. It should fail loud
and redirect to `check_coordination_claims.py`, or be deleted.

The handoff's advice to run a claims listing before assuming a repository is
yours is correct; the hazard is that two commands answer that question and only
one of them is true.

---

## What this changes

The recurring diagnosis holds and extends: a control has three separable
properties — present, configured, and *still* reachable from the route actually
used. The lock adds a fourth, because it is the first control observed to have
been all three and then to have stopped, with no surface reporting the change.

Two rules earned by this sweep:

- **A status flag must report the boundary, not the bookkeeping.** `--status`
  reading a receipt rather than the modes is what let a dead lock look alive.
- **A control's escape hatch must be tested through the route the operator will
  actually use.** The read-first gate's documented recovery is false precisely
  for the tool an agent is instructed to prefer.
