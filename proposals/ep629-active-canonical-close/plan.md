---
schema_version: "1.0"
artifact_type: design_plan
id: ep629-active-canonical-close
status: proposed
method_conformance_receipt: proposals/ep629-active-canonical-close/plan.receipt.json
goal:
  outcome: "Native close can complete exact-owner active canonical environment maintenance while retaining the checkout, ignored environment and default branch."
  canonical_example: "An active .venv-only claim on a clean canonical main closes through an explicit option and exact digests; its archive says completed while Git refs, environment bytes and sibling custody stay identical."
  forbidden_substitutes: "Abandonment, fabricated runtime end, Git removal attempts, or mocked-only filesystem proof."
  boundaries: "One claimed source worktree; no host storage changes, existing Wiki claim changes, runtime termination, fleet refresh or paid Process Tracing runs."
  done_when: "The focused native CLI run and full local gate trace prove acceptance and refusal behavior; source and shipped CLI mirror agree; changes are committed, pushed and integrated with native lane close."
  do_not_gate_on: "Human review, hosted CI, broad benchmarks, further scholarly controls or other agents finishing."
---

# Retain canonical checkout when closing completed environment maintenance

This plan is the implementation and verification authority for the bounded EP629 repair.
Its consumer is the exact native close CLI and its next operator, not a new planning queue.

## Actor and result

> **CORE-ACTOR-RESULT-EXAMPLE** (blocking): The plan names the actor it serves, the desired result, and one stable, concrete, user-visible example of that result.

Brian's agent doing environment-only maintenance needs to retire its claim without
terminating its still-active runtime. After this repair it supplies
`session-close --retain-canonical-environment` and exact claim/tracker digests.
For the stable example, an active write claim restricted to ignored `.venv` on
clean canonical `main` closes to an archived completed claim. The CLI reports
retained canonical worktree and branch; the environment bytes, Git refs,
checkout registration and an unrelated sibling claim are preserved.

## Success and disproof

> **CORE-SUCCESS-DISPROOF** (blocking): The plan defines the evidence that would show success and a concrete condition that would disprove the approach.

> **CORE-TRACE-REVIEW** (blocking): Every success or acceptance criterion in the plan is judged from the full trace of a run, not only its final outcome: it names the run whose full trace is examined (for example the session, its tool and LLM calls, commits, check output, or messages), where that trace lives, and what must be seen in that trace beyond the final outcome. A criterion that names only an outcome, such as tests passing, a PR merged, a test fixture reproducing the journey, or a status reading succeeded, fails this item. A criterion for which no run exists, such as a pure document edit, passes only when the plan states that exemption and its reason explicitly.

Success is judged from the named EP629 native CLI regression run in
`checks.log` beside this plan, not merely its count: inspect the exact parsed
arguments, native session marker, claim/tracker digests, before/after refs and
worktree membership, archived claim bytes and environment sentinel. That run
must show the example's active-to-completed transition without any call to
worktree removal or branch deletion, for both Codex and Claude ownership.
Its negative cases must show unchanged claim/tracker bytes for wrong actor,
wrong digests, noncanonical/linked paths, dirty source, tracked or unignored
environment, non-.venv write scope, mismatched branch or tracker identity,
non-active status and conflicting mode/path/branch overrides. Ordinary close
on the canonical root must refuse before state changes. The same log retains
the full local gate command, stdout/stderr, counts and exit code, self-test
output, source/mirror equality, integration commit and native lane-close
receipt. Read any failing or surprising test's full traceback before reporting
a cause; existing full-suite failures remain explicit limitations until fixed.
The CLI journey uses real Git and isolated coordination state with the shipped
source entrypoint, not a mock of canonical Git identity. Integration is judged
from the actual remote merge and final canonical/claim/worktree checks recorded
in this session and appended to `checks.log`.
Disproof: any accepted negative case, any mutation of the retained Git or
environment bytes/sibling custody, a fake SessionEnd, or a green claim that
omits a failing gate from the trace. This is code work, so there is no no-run
exemption for acceptance. The operator guide edit is a pure documentation
change: its no-run exemption is limited to wording, checked against the actual
CLI help and behavior in the same regression run.

## System model

> **CORE-SYSTEM-MODEL** (blocking): The plan links the project's system model (a path such as docs/model/ODD.md) or carries the one-line exemption `System model: exempt -- <reason>`, which fits only a project with no stored state and no user-facing view. Unless exempt, the plan names each system-model element (entity, process, record or event, or view) that the work adds, changes, or relies on, and its trace review names, for each such element, what the examined run must show of it (for example an event of that record type with its id, or the view displaying that entity). A plan with neither a model link nor the exemption line fails this item, as does one that lists model elements without saying what the examined run must show of each, or one that names no element without stating that the work touches none and why.

System model: [Coordination Runtime Target Architecture](../../docs/designs/COORDINATION_RUNTIME_TARGET_ARCHITECTURE.md).
Elements relied on: canonical claim/session identity, tracker, native actor,
Git checkout/branch custody, completed archive and CLI receipt view.
The EP629 native CLI regression trace at `checks.log` must show, respectively:
the exact claim key and active-to-completed state; exact matching tracker and
digest; matching ambient Codex/Claude marker plus a rejected foreign actor;
unchanged HEAD, refs and worktree registration; archive ID containing the
original claim binding and retained-root receipt; JSON view reporting retained
filesystem/branch actions. These are extensions of existing entities/processes,
not a new registry or system model. Full trace review follows the Success and
disproof section and includes every named element.

## Authority and non-goals

> **CORE-AUTHORITY-NONGOALS** (blocking): The plan states who holds authority over the work and what it explicitly will not do (non-goals).

Brian requested native EP guidance/fix and then said "proceed" on 2026-10-08.
Workspace authority delegates reversible source repair and normal Brian-owned
integration; Enforced Planning AGENTS.md and its native claimed worktree own
implementation. Non-goals: AES325 critical-section changes, general canonical
source-write permission, manual coordination edits, fake runtime-end events,
existing Wiki or dynamical-lab mutation, environment conversion, host storage
configuration, WSL restart/compaction, installed hot-hook replacement and fleet
rollout. The already-abandoned Wiki claim remains unchanged.

## Irreversible actions and spend

> **CORE-IRREVERSIBLE-SPEND** (blocking): For each irreversible action or spend the plan proposes, it names the boundary, who must authorize it, and how it is contained.

The proposed spend is the mandatory Company Planning semantic check/adoption
call. Boundary: only that existing checker, through the approved shared client
and OpenRouter light-model route. Authorizer: Brian's standing workspace
instruction requiring Company Planning adoption for every non-trivial change,
plus his explicit "proceed" on this repair. Containment: the checker's native
maximum budget of USD 0.05 per item call, cached verdict reuse for unchanged
inputs, no output/timeout override and no product evaluation. No Process
Tracing, CONTROL-003 or A4 paid run is part of this plan. There is no proposed
irreversible operation: Git and claim fixtures are isolated under pytest
temporary storage, retain data and use the canonical lifecycle. Source commits
and integration are revertible. Any action/spend outside this named checker
boundary requires Brian's separate authority before execution.

## Uncertainties

> **CORE-UNCERTAINTIES** (blocking): The plan lists its material uncertainties, and each one has an owner or the evidence that would resolve it.

Exact CLI/mirror compatibility is owned by this lane and resolved by invoking
both parsers plus byte equality. Interaction with sibling claims and ignored
environment files is resolved by real Git before/after assertions. Tracker
drift and path overrides are resolved by refusal tests, preserving the ended
legacy route's existing behavior. Full-suite baseline failures are resolved or
honestly bounded from their full traces; they cannot be hidden by the focused
result. AES325 global lock duration remains owned by its existing issue and is
not evidence against environment preservation. No product choice is pending.

## Activation facts

> **CORE-ACTIVATION-FACTS** (blocking): No activation fact that the plan triggers is declared false. Declaring a fact true when the plan does not strictly need it is acceptable, because it only adds checks; judge only facts declared false. empirical_comparison_proposed is triggered when the plan proposes an A/B test, benchmark, bake-off, or other experiment comparing alternative designs, models, or candidates to choose among them; checking the built result against an expected outcome (an acceptance test, fixture replay, or regression check) is verification and does not trigger it. shared_mechanism is triggered by a new shared mechanism, contract, or algorithm; llm_central by behavior that centrally depends on LLM calls; irreversible_or_spend_action by a proposed irreversible action or spend.

shared_mechanism=true: the close lifecycle and installed CLI contract are
shared. empirical_comparison_proposed=false: regression verification chooses
no alternative architecture/model and is not an experiment or benchmark.
llm_central=false: the product path is deterministic Python/Git, not an LLM;
the mandatory planning checker does not implement the product behavior.
irreversible_or_spend_action=true: the existing light semantic adoption checker
may consume its standing bounded budget, as contained in Irreversible actions
and spend. No new product evaluation or irreversible operation is authorized.

## Prior art and ownership

> **OV-PRIOR-ART-DISPOSITION** (blocking): Existing ownership, internal lineage, and relevant external prior art were searched, and each candidate found is dispositioned as reuse, extend, compose, supersede, or bounded exception.

> **OV-PRIOR-ART-PARALLEL-CHECK** (advisory): The plan names one concrete structural check or consumer-path observation that would detect a silent parallel implementation of the same concern.

Internal search inspected the following candidates and dispositions:
extend close_session and the existing close CLI with an explicit active
environment-only mode; reuse canonical-root reconciliation's Git identity and
digest validator while preserving its genuine session-ended default; reuse
the native prewrite CLI grammar and exact-owner checks; reuse the installer's
source-to-mirror mapping; reuse Plan 138's create/reject/reconcile boundaries
without reopening its completed scope; reuse Project Meta's owner map to keep
claims/session lifecycle in Enforced Planning. Bounded exception:
session-abandon remains the documented historical mitigation, not completed
close proof. Reuse the cross-repo architectural ideas register's existing
claim/lifecycle owner rather than introducing another mechanism.
External prior art searched: Git's primary worktree manual,
https://git-scm.com/docs/git-worktree, read on 2026-10-08. Disposition: reuse
Git's distinction between the single main worktree and removable linked
worktrees; native removal is for a finished linked worktree. The fix retains
the main worktree and extends only the existing coordination metadata owner.
No registry or outside library is superseded or newly introduced.
Structural check: source and installer-declared scripts/meta/session_close.py
must byte-match; real CLI tests must reach the same close_session owner and
archive receipt. This catches a silent consumer-only second close path.
