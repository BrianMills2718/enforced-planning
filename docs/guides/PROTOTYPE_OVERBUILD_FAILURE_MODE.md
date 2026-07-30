# Preventing Autonomous Prototype Overbuild

This guide addresses a recurring failure mode in AI-assisted development:
straightforward prototypes consume days or weeks of autonomous agent work while
the integrated product advances slowly. It is written for an operator who may
give broad direction, check in intermittently, and otherwise let coding agents
continue for hours.

The correction is not to abandon quality, planning, or ambitious products. It
is to keep **capability ambition** separate from **delivery maturity**, make the
user-visible demo the primary progress measure, and prevent process work from
silently replacing product work.

## The Failure Mode

**Autonomous prototype overbuild** occurs when an agent interprets an ambitious
outcome or open-ended authorization as a mandate to construct a generalized,
release-grade platform before demonstrating the smallest integrated product.

A common causal chain is:

1. The operator describes the eventual vision, often using terms such as
   “SOTA,” “product,” “autonomous,” or “complete.”
2. No separate delivery-maturity target is frozen, so the agent treats the
   eventual ambition as the current engineering standard.
3. The agent decomposes work into locally defensible components, contracts,
   evaluations, plans, adapters, and safeguards.
4. Each discovered issue creates another generalized mechanism rather than the
   smallest correction to the demonstrated path.
5. Tests, audits, documentation, and infrastructure remain green, but the
   operator cannot point to a materially better product experience.
6. “Continue” authorizes another locally reasonable increment; it does not
   force a strategic reset.
7. The expanding surface creates more regression risk, more verification, and
   more documentation, making every later change slower.

The result is **process capture**: artifacts that support delivery become the
main output of the work.

## Recognizable Symptoms

- The agent works for several hours without improving the canonical demo.
- Status updates lead with tests, schemas, plans, or commits rather than what a
  user can now do.
- Multiple interfaces or demonstrations exist, but no single path integrates
  them.
- A defect in one assumption forces many downstream artifacts to be rebuilt.
- New plans appear more quickly than completed user workflows.
- Broad test suites and documentation checks run after small reversible edits.
- The repository grows by thousands of lines before one real example works.
- The agent repeatedly audits or reorganizes the roadmap because the current
  outcome is difficult to state.
- “Future product,” “SOTA,” or “research rigor” is used to justify work that no
  current demo user needs.
- The operator has difficulty answering “What will I be able to click and see
  after the next two hours?”

## The Crucial Separation: Capability vs. Maturity

These are independent axes:

| Axis | Examples | Governs |
| --- | --- | --- |
| Capability ambition | narrow, competitive, SOTA/SOTA+ | What the system can do |
| Delivery maturity | spike, prototype, paid beta, release | How broadly and reliably it must do it |

A **SOTA-capability prototype** is coherent. It may demonstrate an unusually
rich set of features through one model, one representative corpus, one hosted
service, and one integrated desktop workflow. It does not automatically need:

- empirical superiority studies;
- multiple providers or deployment targets;
- generalized plugin systems;
- every methodology or exchange format;
- publication-grade artifact custody;
- enterprise collaboration or compliance;
- comprehensive scaling and recovery machinery; or
- a separate framework for every potentially reusable operation.

Likewise, commercial intent does not automatically imply release maturity. An
invited or paid beta can use managed authentication and payments, bounded usage,
simple persistence, manual support, and one deployment while demand is being
established.

Unless the operator explicitly selects another maturity, autonomous feature
work should default to **prototype**.

## The Prototype-Default Contract

Before substantial implementation, freeze the following in the conversation or
one existing authority. Do not create a new plan merely to record it.

1. **Outcome:** one sentence describing what the user can accomplish.
2. **Canonical demo:** a five-minute sequence using one real representative
   input and an observable output.
3. **Capability target:** the features the demo must exhibit.
4. **Maturity target:** normally `prototype` unless explicitly promoted.
5. **Effort budget:** expected elapsed work and the mandatory reset point.
6. **Non-goals:** attractive work that does not affect this demonstration.
7. **Acceptance:** what the operator must be able to see or do.

Example:

> In a hosted desktop demo, a visitor uploads interview transcripts, states a
> research goal, runs one analysis, inspects codes and source evidence, and
> downloads an evidence-cited report. The capability target is SOTA+ feature
> coverage for text interviews; the maturity target is prototype. Use one model,
> one deployment, and one representative corpus. Defer broad interoperability,
> collaboration, mobile optimization, generalized evaluation infrastructure,
> and enterprise hardening. Reset if the demo is not materially better within
> four hours.

## Critical-Path Classification

Classify every proposed increment before executing it:

| Class | Definition | Prototype critical path? |
| --- | --- | --- |
| `product_vertical` | Improves the canonical end-to-end user behavior | Yes |
| `direct_blocker` | Removes a reproduced failure preventing that behavior | Yes |
| `enabler` | General machinery that may help future work | No, unless the direct path cannot proceed without it |
| `hardening` | Improves reliability beyond the selected maturity | No |
| `research` | Produces knowledge or comparative evidence | Only if an unresolved decision would change implementation now |
| `process` | Plans, trackers, audits, documentation, or governance | Only at the minimum needed to keep the current work coherent |

Before the canonical demo works, only `product_vertical` and demonstrated
`direct_blocker` work advance product status.

## Thin-Slice Execution Pattern

For an LLM product, prefer this order:

1. One real input reaches one real model call and one validated output.
2. The validated output appears in the actual user interface.
3. The interface steps back to the exact source evidence.
4. The same path handles a small representative multi-document case.
5. Add the next required capability to that path, not as a separate demo.
6. Only after the integrated demonstration works, add the minimum hosting,
   account, payment, persistence, and support controls needed for the next user.

Use typed contracts at real boundaries—untrusted model output, persistence,
customer isolation, external APIs—but do not build a generalized contract
framework before two concrete consumers demonstrate the need.

## Verification Budget

Verification should match the protected decision:

- During implementation, run changed-area tests and inspect the exact LLM trace
  when semantics matter.
- Replay the canonical demo after every material vertical increment.
- Run broad suites, documentation checks, packaging checks, and deployment
  verification once at the terminal checkpoint unless a shared contract change
  specifically invalidates them.
- Reuse unchanged evidence rather than rerunning it because another
  deterministic artifact was produced.
- Do not build a generic evaluation harness when direct inspection of the one
  representative trace answers the prototype decision.

Default prototype gate budget:

- focused checks should take less time than the implementation they protect;
- broad terminal verification should occur once per candidate;
- a second broad pass requires a recorded invalidation of the first candidate;
  and
- verification exceeding 25% of pre-demo effort triggers a scope review.

Safety, privacy, secrets, irreversible actions, and protection against
unbounded provider spending remain mandatory regardless of maturity.

## Autonomous-Run Circuit Breakers

An autonomous agent must reset the approach—not merely write another status
update—when any of these occurs:

- two hours pass without a user-visible improvement or removal of a named demo
  blocker;
- three consecutive increments produce only enablers, process artifacts, or
  hardening;
- actual effort reaches twice the expected effort for the slice;
- four hours of continuous work pass without replaying and reassessing the
  canonical demo;
- more than one active plan or more than one canonical demonstration competes
  for authority;
- the agent proposes a new framework, generalized service, benchmark, or
  documentation hierarchy before the current demo works; or
- the operator expresses confusion about what is being built or why progress is
  slow.

At a reset:

1. replay the current product behavior;
2. state the remaining gap in plain language;
3. classify recent effort as product, blocker, enabler, hardening, research, or
   process;
4. discard or defer work that does not affect the next observable behavior;
5. select the smallest direct vertical; and
6. continue only within a renewed effort budget.

The reset happens in conversation or the existing status authority. It does not
create another retrospective, plan, gate, or approval ceremony.

## Operator Monitoring Without Micromanagement

For agents running unattended, require a compact checkpoint every two hours or
three increments, whichever comes first:

- **Demo delta:** What can a user do now that they could not do before?
- **Canonical replay:** Does the five-minute demo work end to end right now?
- **Effort mix:** Roughly what percentage went to product, blockers, process,
  research, and hardening?
- **Growth:** How many production lines, tests, scripts, documents, and new
  authorities were added?
- **Next visible change:** What specifically will be different within the next
  two hours?
- **Reset decision:** Continue the current approach or narrow it?

The operator does not need to inspect every commit. These questions make
strategic drift visible early.

Useful warning thresholds—not universal hard limits—are:

- more documentation-only commits than behavior-changing commits;
- more test or framework code than product code before the first demo;
- more than one new durable document per distinct decision;
- thousands of production lines before one representative vertical works; or
- a growing test runtime with no corresponding expansion of the demonstrated
  claim.

## Copyable Instruction For Coding Agents

Use this at the start of a prototype or with a goal command:

```text
Build the smallest integrated prototype that demonstrates the requested
capabilities. Capability ambition and delivery maturity are separate: the
capability target may be SOTA/SOTA+, but the maturity target is prototype unless
I explicitly promote it.

Preserve one canonical five-minute demo using a real representative input. Only
user-visible vertical work and reproduced blockers belong on the pre-demo
critical path. Defer generalized frameworks, additional providers, broad
evaluation infrastructure, interoperability, collaboration, mobile polish,
enterprise hardening, and documentation that does not own a distinct current
decision.

Use focused tests during implementation and broad verification once at the
terminal candidate. Every two hours or three increments, report the demo delta,
replay status, effort mix, repository growth, and the next two-hour visible
change. If two hours produce no visible improvement, three increments are only
process/enabling work, or actual effort reaches twice the estimate, reset to the
smallest direct vertical instead of continuing the same strategy.

Do not interpret “continue,” “go,” or commercial intent as permission to expand
delivery maturity or scope. Ask only when a genuinely consequential choice
cannot be defaulted; otherwise choose the simplest reversible implementation.
```

## What Not To Sacrifice

Prototype discipline is not permission for hidden failure or disposable
spaghetti. Retain:

- source and evidence integrity where it is part of product value;
- validation of untrusted model output;
- deterministic identity and accounting;
- customer-data separation when external users are involved;
- bounded model spending and server-side credentials;
- clear errors rather than silent fallback;
- one callable core beneath the UI; and
- enough focused tests to protect the demonstrated path.

The rule is proportionality: build the simplest mechanism that protects the
current user behavior and selected maturity, then stop.

## Observed Case: `qualitative_coding`

At commit `6c302cf` on 2026-07-29, the repository contained approximately
84,800 physical lines of production Python, 63,990 lines of tests, 21,796 lines
of scripts, and 63 Markdown documents. Across the 280 first-parent commits from
`97c8ae9` on 2026-07-22 through that snapshot, Git recorded 189,684 added or
deleted lines; 106 of those commits changed only Markdown files.

The desired product core remained conceptually direct: documents and a research
goal enter a structured LLM pipeline; codes, evidence, profiles, relationships,
and findings become an evidence-cited report and review interface. Important
correctness work—exact evidence, speaker boundaries, structured validation, and
cost controls—was mixed with evaluation protocols, benchmark adapters,
artifact-custody machinery, repeated planning, and release-style verification.
The latter work may have future value, but allowing it onto the prototype
critical path made progress difficult for the operator to observe.

This case supports the bounded lesson, not a universal line-count rule: an
ambitious feature set can still be prototyped thinly, and autonomous agents need
an explicit maturity target, demo-based progress measure, effort budget, and
circuit breaker to keep that path thin.

## Decision Rule

When deciding whether to build something before the prototype demo, ask:

> If this were omitted, could the named user still complete the canonical demo
> and could we still learn whether the product is valuable?

If yes, defer it. If no, implement the smallest version that removes that exact
blocker and replay the demo.
