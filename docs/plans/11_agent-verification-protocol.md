# Plan #11: Agent Verification Protocol for Validated Couplings

**Status:** Planned
**Type:** design
**Priority:** High
**Blocked By:** None
**Blocks:** #7 — LLM semantic review is a specialization of this pattern

---

## Gap

**Current:** The V2 `relationships.yaml` defines a `validated` coupling type, but
there is no mechanism to actually invoke an agent when a `validated` coupling fires.
The type exists in schema; the enforcement loop does not.

**Target:** A portable, invocable agent verification protocol that:
1. Accepts a changed source file + coupled doc as input
2. Produces a structured verdict (CURRENT / STALE / UNCERTAIN)
3. Takes concrete action: proposes fix, creates escalation task, or marks verified
4. Can run as a CI step, a post-merge hook, or on-demand CLI

**Why:** Without Layer 3, `validated` couplings are no different from old `soft: warn`
couplings — they produce findings but require humans to read them. The whole point of
V2 is to replace "warn and hope" with "agent fixes or escalates."

---

## References Reviewed

- `docs/designs/RELATIONSHIPS_V2_DESIGN.md` — Layer 3 description + coupling types
- `scripts/infer_dependencies.py` — how edges are discovered (Layer 1)
- `relationships.yaml` (enforced-planning) — V2 schema with `validated` coupling examples
- `llm_client/scripts/relationships.yaml` — live V2 file after adoption pilot
- `PLANNING_OPERATING_MODEL.md` — programmatic/agent/human actor model
- `~/projects/.claude/CLAUDE.md` — "Programmatic for coverage + agents for judgment + humans for direction"

---

## Design Decisions (pre-made)

These decisions are locked before implementation begins. Each narrows the
implementation space; the implementer should not re-open them.

### D1: Invocation trigger

`validated` couplings are **NOT blocking**. They do not block commits. They run:
- In CI as a post-merge step (primary)
- On-demand via `make verify-couplings` (secondary)
- NOT as a pre-commit hook (cost + latency would make it intolerable)

Rationale: blocking commits on LLM judgment introduces non-deterministic gate
behavior. Async post-merge fits the cognitive economics model.

### D2: Context package (what the agent receives)

The agent receives a bounded context package — NOT raw full file contents:

```
source_change: diff of the changed source file (≤200 lines, truncated with note if longer)
coupled_doc: full text of the coupled doc (≤500 lines, truncated with note if longer)
coupling_description: the description field from relationships.yaml
coupling_type_policy: "validated couplings require agent verification..."
```

Rationale: full files balloon cost. Diffs are what actually changed. The doc
text is needed for judgment. Truncation with explicit notes is better than
silent truncation.

### D3: Verdict schema

```python
class VerificationJudgment(BaseModel):
    verdict: Literal["CURRENT", "STALE", "UNCERTAIN"]
    confidence: Literal["high", "medium", "low"]
    evidence: str  # ≤200 chars, what in the diff triggered this verdict
    proposed_fix: str | None  # populated when verdict==STALE, None otherwise
    escalate: bool  # True when UNCERTAIN + agent cannot resolve
```

`CURRENT`: source changed but coupled doc remains accurate — no action needed.
`STALE`: doc is definitely wrong given the diff — agent proposes inline fix.
`UNCERTAIN`: agent cannot determine without more context — escalates to human.

### D4: Actions after verdict

| Verdict | Action | Actor |
|---------|--------|-------|
| `CURRENT` | Mark coupling verified for this commit in verification log | Script |
| `STALE` + proposed_fix | Apply fix to coupled doc and commit `[Governance] auto-fix validated coupling` | Script |
| `STALE` + no fix | Create escalation task (GitHub issue, file note, or Linear ticket) | Script |
| `UNCERTAIN` | Create escalation task with agent's evidence | Script |

### D5: Persistence model

Verification results are appended to `docs/ops/verification_log.yaml`:

```yaml
- coupling_id: "patterns/15_plan-workflow.md → PLANNING_OPERATING_MODEL.md"
  commit: abc123
  verdict: CURRENT
  confidence: high
  evidence: "Change added a new pattern variant; doc still covers the general workflow."
  verified_at: 2026-04-02T17:00:00Z
  agent: claude-sonnet-4-6
```

This file is git-tracked. Staleness SLA: if a `validated` coupling has no
verification entry within 30 days of its last source change, CI warns.

### D6: Cost ceiling

`max_budget=0.05` per coupling verification (one LLM call). Default model:
`gemini/gemini-2.5-flash` for speed. Override via `VERIFY_COUPLING_MODEL` env var.

### D7: Escalation output

When escalating, write a structured finding to `docs/ops/escalations.yaml`
(not GitHub issues — this is framework-portable; consuming repos may route
escalations to their own tracker). Format:

```yaml
- coupling_id: "..."
  commit: "..."
  verdict: STALE|UNCERTAIN
  evidence: "..."
  proposed_fix: "..." | null
  created_at: "..."
  resolved_at: null
```

---

## Capabilities

| Capability | Input Schema | Output Schema | Producer | Consumer(s) | Cost Tier |
|-----------|-------------|---------------|----------|-------------|-----------|
| `verify_coupling(source_diff, coupled_doc, description)` | `VerificationRequest` | `VerificationJudgment` | enforced-planning | CI hook, make target | cheap (0.05/call) |
| `apply_coupling_fix(judgment, doc_path)` | `VerificationJudgment` | `FixResult` | enforced-planning | post-merge CI | free |
| `log_verification(judgment, coupling_id, commit)` | `VerificationJudgment + metadata` | None (side effect) | enforced-planning | all consumers | free |

### Capability Validation

- [ ] `VerificationRequest` and `VerificationJudgment` defined as Pydantic models with `Field(description=...)`
- [ ] Verdict field uses `Literal["CURRENT", "STALE", "UNCERTAIN"]` — no free-text variants
- [ ] `proposed_fix` is `None` when verdict is `CURRENT` (enforced by schema)
- [ ] `escalate` is `True` when verdict is `UNCERTAIN` (enforced by schema validator)

---

## Files Affected

- `scripts/verify_coupling.py` (create) — main entrypoint
- `scripts/apply_coupling_fix.py` (create) — applies proposed fixes
- `prompts/verify_coupling.yaml` (create) — Jinja2 prompt template
- `docs/ops/verification_log.yaml` (create, initially empty)
- `docs/ops/escalations.yaml` (create, initially empty)
- `Makefile` — add `verify-couplings` target
- `ROADMAP.md` — update Phase 4 status

---

## Plan

### Steps

1. **Write the Pydantic schemas** (`VerificationRequest`, `VerificationJudgment`, `FixResult`)
   and unit-test them for field constraints.

2. **Write the prompt template** (`prompts/verify_coupling.yaml`) — system + user turn.
   System: role definition, coupling type policy, verdict taxonomy.
   User: diff, doc text, description, truncation notes if applicable.
   Goal over rules: "Determine if this documentation still accurately describes
   the behavior shown in the diff."

3. **Implement `verify_coupling.py`** — reads a coupling from relationships.yaml,
   retrieves the git diff for the source file(s), reads the coupled doc, builds
   the context package, calls LLM via llm_client with `json_schema` response_format,
   returns `VerificationJudgment`.

4. **Implement `apply_coupling_fix.py`** — for `STALE` verdicts with a `proposed_fix`,
   applies the fix to the coupled doc and commits with `[Governance]` prefix.
   For escalations, appends to `docs/ops/escalations.yaml`.

5. **Add `make verify-couplings` target** — runs `verify_coupling.py` for all
   `validated` couplings in `relationships.yaml` that have changed source files
   since last verification entry.

6. **Add a staleness check** to `check_truth_surface_drift.py` (or a new script):
   fail if any `validated` coupling has a source change with no verification
   entry within 30 days.

7. **Run self-test and full test suite.**

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_verify_coupling.py` | `test_judgment_schema_current` | CURRENT verdict has `proposed_fix=None` |
| `tests/test_verify_coupling.py` | `test_judgment_schema_stale_requires_evidence` | STALE verdict has non-empty evidence |
| `tests/test_verify_coupling.py` | `test_uncertain_sets_escalate` | UNCERTAIN verdict forces `escalate=True` |
| `tests/test_verify_coupling.py` | `test_context_truncation` | Diffs > 200 lines are truncated with a note |
| `tests/test_verify_coupling.py` | `test_cost_ceiling_kwarg` | verify_coupling passes `max_budget=0.05` to llm_client |
| `tests/test_apply_coupling_fix.py` | `test_fix_appends_to_escalations` | UNCERTAIN verdict writes to escalations.yaml |
| `tests/test_apply_coupling_fix.py` | `test_fix_skipped_for_current` | CURRENT verdict does not modify any files |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/self_test.py` | Framework file/template integrity |
| `python -m pytest tests/ -q` | All existing validators still green |

---

## Acceptance Criteria

- [ ] `verify_coupling.py` runs end-to-end on at least one real `validated` coupling
      from `enforced-planning/relationships.yaml` using a real LLM call
- [ ] Judgment schema is `json_schema` enforced — no free-text verdicts possible
- [ ] STALE verdicts with `proposed_fix` produce a committed doc update
- [ ] UNCERTAIN verdicts produce an entry in `docs/ops/escalations.yaml`
- [ ] `make verify-couplings` exits 0 on a clean repo and 1 when unchecked escalations exist
- [ ] All new tests pass
- [ ] Full test suite passes

---

## Open Questions

- [ ] **Fix authorship**: Should auto-fixes commit under the agent's name or the repo's git config? Recommendation: use git config but add `[Governance] auto-fix` prefix in message. — Status: OPEN
- [ ] **Partial diffs**: If a source file has 500 lines changed, the 200-line truncation may miss the relevant part. Should we use file-section heuristics (function boundaries)? — Status: OPEN, deferring to implementation
- [ ] **Cross-project `validated` couplings**: Can a coupling reference a doc in a different repo? If so, git diff won't work across repos. — Status: OPEN, defer to cross-repo governance phase

---

## Notes

This plan creates the execution spine for Layer 3. Plan #7 (LLM semantic truth-surface
review) is a specialization: instead of verifying a single coupling per call, #7 reviews
all truth surfaces in batch. Once this plan's `VerificationJudgment` schema is stable,
#7 reuses it with a different context package (rendered truth surface instead of diff).

The design deliberately avoids GitHub-specific APIs for escalation routing. `escalations.yaml`
is the portable format; consuming repos wire it to their own tracker.
