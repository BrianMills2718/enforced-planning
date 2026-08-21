# Ecosystem Feedback Operator Guide

Use this transport to preserve one concrete ecosystem friction or one
evidence-backed recommendation that a later operator can inspect and
disposition. It is the portable evidence intake for policies, skills,
instructions, tools, project workflows, and genuinely unowned concerns.

This transport does not own reusable operational findings or procedural
lessons; those remain in Project Meta's immutable `learning/v2` register. It
also does not accept policy, create policy proposals, or change an instruction,
skill, tool, or project. Those actions stay with their canonical owners.

## Record Feedback

Run the repository command directly:

```bash
python scripts/ecosystem_feedback.py record \
  --type friction \
  --scope-kind skill \
  --scope-id bounded-design \
  --observation "The accepted planning profile did not map to the runtime profile." \
  --expected-behavior "The handoff names or mechanically maps the runtime profile." \
  --recommendation "Publish one profile mapping at the planning-to-runtime seam." \
  --evidence-ref "receipt:example-planning-run"
```

`--type` is either `friction` or `recommendation`. `--scope-kind` is one of
`policy`, `skill`, `instruction`, `tool`, `project`, or `general`.

- A non-general scope requires `--scope-id`.
- A general scope rejects `--scope-id`; it does not invent an owner.
- Friction requires `--expected-behavior`.
- Every entry requires a non-empty `--recommendation` and at least one
  `--evidence-ref`. Repeat `--evidence-ref` to supply more than one identity.

The success document contains the resolved `feedback_path` and the complete
validated record in `payload`, including its stable `feedback_id`. Unknown
fields, empty semantic values, duplicate evidence references, and invalid
scope/type combinations fail before append.

## Source Identity And Data Boundary

The CLI sets only the constant client identity `cli` by default. Override it
with `--source-client` when another stable client name is useful. Optional
`--source-project`, `--source-task-id`, `--source-session-id`, and
`--source-working-directory` values are stored only when the caller explicitly
passes them.

The transport never automatically captures prompts, responses, tool output,
credentials, the current working directory, session state, or evidence
contents. An evidence reference is an inert string. The transport never opens,
fetches, tests, or copies what it names, so a reference to a missing file or
external receipt remains valid. Callers are responsible for supplying only
privacy-safe semantic fields and reference identities.

## Stream Location

The default stream is:

```text
~/.claude/coordination/ecosystem-feedback-v1.jsonl
```

Every command accepts `--feedback-path PATH` for a repository, test, or
deployment profile. The writer creates a missing parent directory. Tests and
probes should always use a temporary path rather than the default durable
stream.

## Inspect And Report

List validated lifecycle views in append order:

```bash
python scripts/ecosystem_feedback.py list \
  --scope-kind skill \
  --status open
```

Summarize the same validated selection:

```bash
python scripts/ecosystem_feedback.py report \
  --type friction \
  --scope-kind skill
```

Both commands accept optional `--type`, `--scope-kind`, `--scope-id`, and
`--status` filters. Reports include counts and the exact `feedback_ids`,
`open_feedback_ids`, and `dispositioned_feedback_ids`, so every aggregate steps
down to its source records. Filtering never hides corruption: the complete
stream is validated before a filtered result is returned.

## Disposition Once

Append one terminal decision without rewriting the original feedback line:

```bash
python scripts/ecosystem_feedback.py disposition \
  --feedback-id ecosystem_feedback_0123456789abcdef0123456789abcdef \
  --disposition resolved \
  --rationale "The accepted profile mapping is now enforced." \
  --successor-ref "commit:example"
```

Disposition values are `resolved`, `accepted`, `accepted_risk`, `duplicate`,
`superseded`, and `misrouted`. The rationale is required; the successor
reference is optional. A feedback ID may receive exactly one terminal
disposition of any kind. An unknown ID or second disposition fails without an
append.

Disposition records are evidence about triage state. They do not themselves
change or accept policy, skills, instructions, tools, or project behavior.

## Failure And Recovery

The JSONL stream is an append-only authority. Each write locks the stream,
validates all existing rows, appends exactly one complete JSON object, flushes,
and synchronizes the file before reporting success. Concurrent writers use the
same lock; two concurrent dispositions for one feedback ID cannot both succeed.

Reads and writes fail loud on malformed or non-object JSON, blank or
unterminated rows, unknown record types, schema-invalid rows, duplicate
feedback or disposition IDs, orphaned dispositions, dispositions that predate
their feedback, or any second terminal disposition. The CLI exits `2`, writes
a concise error to stderr, and emits no success JSON on these failures.

Do not repair a corrupt durable stream by deleting or rewriting history. Copy
it for diagnosis, identify the canonical owner, and preserve the exact failing
bytes as evidence before applying an explicitly governed recovery.
