# Pattern: Agent-Drivable UI

## Problem

Interactive UIs often become the only place a critical workflow can be
exercised. That creates predictable failures:

1. Basic flow breakage is discovered only when a human clicks through it
2. Async failures look like “nothing happened” because no machine-readable
   pending or error surface exists
3. Browser/UI regressions are hard to reproduce because the workflow has no
   seeded or scriptable execution path
4. Agents can verify backend logic but cannot prove the real user path works
5. Teams confuse “the UI renders” with “the workflow is operational”

Without an agent-drivable path, human playtesting ends up catching transport,
permission, orchestration, or loading-state bugs that should have failed much
earlier in automation.

## Solution

Treat every UI as a presentation layer over a machine-drivable control surface.

The goal is not to make every UI pleasant for agents. The goal is to ensure an
agent can execute and verify the same critical workflows a user depends on.

### Required Layers

For any non-trivial interactive surface, design four layers explicitly:

1. **Domain engine**
   - the underlying logic
   - no UI assumptions
2. **Control surface**
   - the verbs the user actually performs
   - create, submit, inspect, acknowledge, advance, export, etc.
3. **Human UI**
   - browser, desktop, TUI, notebook, or other presentation surface
4. **Agent harness**
   - a machine path that drives the control surface and verifies results

The critical invariant is:

> If a human can perform a critical workflow, an agent must be able to drive
> and verify that workflow too.

### Backend-First Requirement

This pattern is backend-first.

It does **not** require screenshot testing for every project.

It **does** require:

- one machine-drivable path for each critical user flow
- surfaced pending, success, and error states for async actions
- an inspectable state surface so the agent can prove progress

For browser-heavy projects, screenshots and DOM capture are useful extras.
For backend-first projects, HTTP/CLI/WebSocket verification may be sufficient.

### Sufficient Machine Paths

Any of these can satisfy the pattern if they cover the critical flow:

- HTTP/API driver
- WebSocket session driver
- CLI harness
- Browser automation over the real UI

The browser itself does not need to be the only test surface.

### Minimum Verification Surface

Every critical UI workflow should expose:

- **action surface**
  - the user command or UI event
- **pending state**
  - something machine-readable that says the action started
- **success state**
  - something machine-readable that says the action completed
- **error state**
  - something machine-readable that says why it failed
- **state inspection**
  - a way to prove the system changed, not just that the button was clicked

### Standard Commands

Prefer repo-local Make targets with consistent names:

- `make smoke-ui`
- `make smoke-ui-headless`
- `make smoke-api`
- `make debug-session`

If a repo has no browser, `smoke-ui` can be a CLI or TUI harness.

### Reproducibility

Agent-driven UI verification is much more valuable when the repo supports:

- seeded randomness
- fixture-driven sessions
- debug mode
- replayable traces

This is what lets an agent say “this exact workflow passed” instead of “I
clicked around and it seemed okay.”

## Files

| File | Purpose |
|------|---------|
| `docs/ops/GOVERNED_REPO_CONTRACT.md` | Ecosystem-level requirement for UI-bearing repos |
| `meta-process/patterns/39_agent-harness-engineering.md` | Related long-running harness guidance |
| `Makefile` | Standard smoke and debug targets |
| repo-local `README.md` | Documents the machine-drivable UI path for the project |

## Setup

To apply this pattern in a new project:

1. Identify the critical user workflows.
2. Define the control-surface verbs those workflows require.
3. Expose one machine-drivable path for those verbs.
4. Add a smoke target for the critical flow.
5. Add a debug or seeded mode when timing or stochastic behavior matters.
6. Make async UI actions surface pending, success, and error states.
7. Document the path in the project `README.md` and project-local `CLAUDE.md`.

## Usage

Typical verification loop:

```bash
make smoke-api
make smoke-ui-headless
make debug-session
```

Typical browser-oriented flow:

1. create or join session
2. submit action
3. verify pending state appears
4. verify success or error state appears
5. inspect resulting state or event log

Typical backend-first flow:

1. call the same API or CLI verbs the UI uses
2. verify the resulting state transition
3. verify surfaced failure semantics

## Customization

- For backend-first repos, browser automation may be optional if the UI is a
  thin client over a well-exercised API.
- For rich browser apps, add screenshots, DOM snapshots, and network capture
  only when they materially improve diagnosis.
- For real-time systems, prefer seeded or replayable session fixtures over
  brittle timing-only checks.

## Limitations

- This pattern does not solve visual design quality, UX elegance, or layout
  coherence.
- It does not replace human playtesting.
- It adds setup cost for projects that previously relied on ad hoc manual UI
  testing.
- Browser automation is helpful but not universally required; the requirement
  is machine-drivable verification, not a specific tool.

## Origin

Formalized after repeated cases where agents could verify backend logic but the
real interactive workflow still failed because submission paths, async states,
or orchestration errors were only exercised manually.
