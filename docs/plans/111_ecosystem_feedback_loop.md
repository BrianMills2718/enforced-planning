# Plan #111: Portable Ecosystem Feedback Loop

**Status:** In Progress — design adopted; EF-01 ready for implementation
**Status ID:** in_progress
**Type:** implementation
**Priority:** High
**phase_ref:** "Portable ecosystem governance"
**goal_ref:** "empirical-ecosystem-improvement"
**Landscape disposition:** linked
**Blocked By:** None
**Blocks:** evidence-backed policy, skill, instruction, tool, and workflow improvement

`trace_evaluable: false # infrastructure-only`

## Objective

Give an agent or human one portable command that records concrete friction or
an evidence-backed recommendation about a policy, skill, instruction, tool,
project workflow, or unowned ecosystem concern. The entry remains append-only,
privacy-reduced, step-down friendly, and explicitly dispositioned; recording it
never changes policy automatically.

The recurring actor is an agent working anywhere in the governed ecosystem.
The inspectable result is a typed feedback record with a stable ID, evidence
references, routing identity when known, and an open or terminal disposition.

## User Outcome

When Brian or an agent encounters reusable friction or sees an evidence-backed
improvement, one obvious command preserves it with evidence and a stable ID,
even when it is not yet owned by a policy, skill, or project. A later agent can
find its disposition and evidence without reconstructing the original chat.

## Canonical Behavioral Example

```bash
python scripts/ecosystem_feedback.py record \
  --type friction \
  --scope-kind skill \
  --scope-id bounded-design \
  --observation "Design profile 'standard' did not map to the worktree runtime profile." \
  --expected-behavior "The handoff names or mechanically maps the accepted runtime profile." \
  --recommendation "Publish one profile mapping at the planning-to-runtime seam." \
  --evidence-ref "command:make worktree ... WORKTREE_EXECUTION_PROFILE=standard"
```

The command prints one stable feedback ID. `list` returns the original record;
`report` counts it under open skill friction; `disposition` appends a terminal
decision without rewriting the original.

## Gap

Current mechanisms are fragmented:

- Project Meta has a tested policy feedback logger and Markdown register, but
  every entry must name a policy.
- shared skills route defects to a manual Markdown file with no deterministic
  append command or evidence schema;
- Enforced Planning has an append-only feedback contract, but only for an
  artifact-creation gate receipt;
- Project Meta's `issue-concern` preserves general risk but hardcodes Project
  Meta ownership and lacks skill, policy, instruction, tool, session, and
  evidence bindings; and
- the always-loaded workspace instruction does not tell agents how to route
  feedback.

Target state:

```text
always-loaded routing rule
  -> portable ecosystem-feedback command
  -> strict append-only EcosystemFeedbackV1 stream
  -> owner-specific projections and dispositions
  -> periodic evidence-backed triage and evaluation
```

## Research

- `enforced_planning/artifact_creation.py` and
  `scripts/artifact_creation.py` — existing strict append-only feedback and
  disposition pattern, currently receipt-bound.
- `tests/test_artifact_creation.py` — current both-sign and step-down evidence.
- Project Meta `scripts/log_policy_friction.py`, `policy_friction.md`, and
  `skill_feedback.md` — current policy and skill feedback compatibility
  surfaces.
- Project Meta `scripts/log_issue_concern.py` — general risk capture whose
  ownership and schema are too narrow for this outcome.
- `agent-skills/docs/SKILL_OBSERVABILITY_POLICY.md` — centralized skill
  observability and the prohibition on repeated skill-local feedback
  boilerplate.
- Project Meta
  `docs/ops/INSTRUCTION_SURFACE_SYNC_POLICY.md` — canonical/derived instruction
  surface model.

## Landscape And Prior Art

Landscape disposition: linked

- `enforced-planning` owns portable feedback transport, strict contracts,
  append/disposition mechanics, and installed governed-repository adapters.
- `project-meta` owns ecosystem policy meaning, the policy registry, shared
  skill-feedback projection, and cross-ecosystem triage.
- `agent-skills` owns centralized skill-observability policy and must not
  duplicate generic feedback boilerplate in every `SKILL.md`.
- the workspace `.claude/CLAUDE.md` is the canonical always-loaded local
  routing surface; `CLAUDE.md` and `AGENTS.md` are aliases.
- project repositories continue to own ordinary project defects.

The implementation extends Enforced Planning's proven append-only
artifact-feedback pattern rather than building another database or policy
engine.

## Boundaries And Non-Goals

| Boundary | Owns | Must not own |
| --- | --- | --- |
| Portable transport | strict schema, validation, append, query, disposition, stable IDs | policy acceptance, automatic fixes, repository-specific ownership inference |
| Project Meta integration | policy/skill projections, legacy compatibility, triage ownership | a second incompatible feedback schema |
| Workspace routing instruction | concise trigger and one command path | repeated procedures or per-skill boilerplate |
| Existing skill observability | selection/outcome episode evidence | semantic feedback disposition or automatic causal claims |

Non-goals:

- adding a feedback section or logger to every skill or policy document;
- copying prompt text, tool output, credentials, or secret values;
- inferring that loading a skill caused an outcome;
- automatically changing, promoting, or enforcing policy from feedback;
- migrating all historical prose before the new path is proven; or
- requiring a policy, skill, project, or gate receipt for genuinely unowned
  feedback.

## Capabilities

| Capability | Input schema | Output schema | Producer | Consumers | Cost tier |
| --- | --- | --- | --- | --- | --- |
| `record_ecosystem_feedback` | `EcosystemFeedbackCreateV1` | `EcosystemFeedbackV1` | `enforced_planning.ecosystem_feedback` | agents, humans, Project Meta adapters | free/local |
| `list_ecosystem_feedback` | stream path plus optional scope/status filters | ordered `EcosystemFeedbackViewV1` records | `enforced_planning.ecosystem_feedback` | CLI and Project Meta triage | free/local |
| `disposition_ecosystem_feedback` | `EcosystemFeedbackDispositionCreateV1` | `EcosystemFeedbackDispositionV1` | `enforced_planning.ecosystem_feedback` | maintainers and triage workflows | free/local |
| `report_ecosystem_feedback` | validated stream plus filters | `EcosystemFeedbackReportV1` | `enforced_planning.ecosystem_feedback` | Project Meta projections and operators | free/local |

Project Meta consumes these versioned contracts. It may render policy- or
skill-specific views but cannot reinterpret validation, lifecycle, identity,
or disposition semantics.

### Capability Validation

- Strict Pydantic models reject unknown and semantically invalid records.
- The CLI and Python API share the same validation and append implementation.
- Both-sign fixtures cover all six scope kinds and every material corruption or
  contradictory-lifecycle failure.
- A report steps down to exact feedback IDs; a projection never becomes a
  second record authority.

## Contract

### `EcosystemFeedbackV1`

The strict JSONL record contains:

| Field | Contract |
| --- | --- |
| `schema_version` | `1.0` |
| `record_type` | `feedback` |
| `feedback_id` | collision-safe `ecosystem_feedback_<uuid32>` |
| `recorded_at` | timezone-aware UTC timestamp |
| `feedback_type` | `friction` or `recommendation` |
| `scope_kind` | `policy`, `skill`, `instruction`, `tool`, `project`, or `general` |
| `scope_id` | required except for `general`; stable name or path, not prose |
| `observation` | concrete observed behavior or reusable evidence |
| `expected_behavior` | optional expectation; required for `friction` |
| `recommendation` | proposed improvement |
| `evidence_refs` | one or more privacy-safe paths, receipt IDs, episode IDs, commands, or URLs |
| `source` | client plus optional project, task/session ID, and working directory |
| `status` | initially `open` |

`EcosystemFeedbackDispositionV1` appends one terminal or routing decision:
`resolved`, `accepted`, `accepted_risk`, `duplicate`, `superseded`, or
`misrouted`. It references exactly one existing feedback record and carries a
non-empty rationale plus optional successor reference.

Unknown fields fail. Empty or whitespace-only semantic fields fail. A scoped
entry without `scope_id`, a general entry with a fabricated scope, friction
without expected behavior, recommendation without evidence, duplicate record
IDs, dispositions for missing feedback, and multiple contradictory terminal
dispositions all fail loud.

## Runtime And Failure Behavior

The CLI supports:

```text
ecosystem-feedback record
ecosystem-feedback list
ecosystem-feedback disposition
ecosystem-feedback report
```

The default local stream is
`~/.claude/coordination/ecosystem-feedback-v1.jsonl`. Callers may override it
for tests or an approved deployment profile. Appends create the parent
directory, use one JSON object per line, flush before returning success, and
never rewrite an existing record. Reads fail on malformed JSON, unknown record
types, schema-invalid rows, duplicate IDs, or inconsistent dispositions.

The transport stores user-supplied evidence references, never dereferences or
copies their contents. It prints the stable feedback ID and resolved stream
path after a successful append. A failed validation or append returns nonzero
and must not claim that feedback was captured.

Compatibility is additive at the adapter layer: existing Project Meta policy
and skill Markdown files remain readable until projections and migration are
separately accepted. The new core contract rejects unknown fields.

## Both-Sign Fixtures

Positive fixtures:

1. skill friction with expected/actual behavior, session reference, and
   observability episode ID;
2. policy recommendation with a policy ID and evidence reference;
3. general recommendation with no scope ID;
4. one open record followed by one valid disposition.

Negative fixtures:

1. scoped record missing `scope_id`;
2. general record carrying `scope_id`;
3. friction missing `expected_behavior`;
4. empty evidence list or semantic field;
5. malformed or non-object JSONL row;
6. duplicate feedback ID;
7. disposition for an unknown feedback ID; and
8. second conflicting terminal disposition.

## Files Affected

EF-01:

- `enforced_planning/ecosystem_feedback.py`
- `scripts/ecosystem_feedback.py`
- `tests/test_ecosystem_feedback.py`
- `docs/guides/ECOSYSTEM_FEEDBACK.md`
- this plan, its work graph, handoff, and plan index

EF-02 and EF-03 file paths remain bounded by their work-unit conflict surfaces
and will be named exactly when their dependency gates become satisfied.

## Plan

Critical path classification: `vertical`

### Work Units

| Unit | Outcome | Status |
| --- | --- | --- |
| EF-01 | Portable typed feedback transport, CLI, tests, and operator guide in Enforced Planning | Ready |
| EF-02 | Project Meta adapters/projections and explicit legacy-register compatibility | Blocked by EF-01 acceptance |
| EF-03 | Always-loaded workspace routing rule and end-to-end policy/skill/general probe | Blocked by EF-02 acceptance |

The machine-readable decomposition is
`docs/plans/111_ecosystem_feedback_loop_work_graph.json`.

## Acceptance Criteria

- [ ] EF-A1: all six scope kinds can be recorded through one command; `general`
  requires no fabricated owner.
- [ ] EF-A2: strict schema and both-sign fixtures fail for the intended reason.
- [ ] EF-A3: append/disposition/query operations preserve the original record,
  reject corruption and contradiction, and step down from summaries to IDs.
- [ ] EF-A4: no raw prompt, response, tool output, credential, or evidence-file
  content enters the default stream.
- [ ] EF-A5: Project Meta consumes the portable contract without reimplementing
  it and keeps legacy registers explicitly compatible until migration.
- [ ] EF-A6: the canonical workspace bootstrap tells agents when and how to log
  policy, skill, instruction, tool, project, and general feedback without
  adding per-skill boilerplate.
- [ ] EF-A7: one real friction record preserves the planning-profile/runtime-
  profile mismatch observed while creating this plan, and one end-to-end probe
  records, lists, and dispositions a temporary test-stream entry.
- [ ] EF-A8: focused tests, framework self-test, generated AGENTS sync, Project
  Meta feedback tests, and instruction-surface checks pass at their exact
  revisions.

## Disproof And Rollback

The approach is disproved if an agent still must invent a policy/skill owner,
cannot find the command from the always-loaded instruction, loses the original
entry during disposition, or cannot step from a report to evidence identity.
It is also disproved if Project Meta and Enforced Planning create incompatible
schemas or if ordinary feedback causes policy mutation.

Rollback removes adapters and the routing pointer but preserves the append-only
stream as inert evidence. No implementation slice deletes historical feedback
or legacy registers.
