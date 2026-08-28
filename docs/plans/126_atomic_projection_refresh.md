# Plan #126: Atomic Projection Refresh on Claim Mutations

**Status:** Complete — superseded without implementation
**Type:** framework architecture fix  
**Priority:** Critical (blocks stop-hook, causes recurring projection staleness)  
**Blocks:** None; Plan #127 owns the surviving reader-side crash window
**Gap:** The adopted design incorrectly inferred that claim creation wrote outside the registry lock.

## Final Disposition

Source inspection at the implementation boundary showed that `create_claim()`
already enters `claim_registry_lock()` before reading authority and retains that
outer critical section through `_atomic_write_claim()` and
`refresh_prewrite_authority_projection()`. The branch-only candidate at `c6b3109`
would acquire the same exclusive lock again inside that transaction. It is therefore
rejected rather than integrated.

The real reproduced failure is a replaceable projection left behind after an
interrupted process or legacy/out-of-band mutation. Plan #127 supersedes this design
with a bounded, lock-owning repair for ordinary turn end while keeping pre-write and
`session-close` digest checks strict.

---

## Problem

Current flow:
1. Claim written/released via `_atomic_write_claim()` or `record_claim_mutation()`
2. **Projection NOT refreshed** (caller must do it manually)
3. Stop-hook reads stale projection
4. Stop-hook error: "projection is stale relative to canonical claim registry"

This creates a race condition every session. The projection is the source of truth for pre-write gates, but it's out of sync with the claims it's supposed to represent.

## Solution

Make projection refresh **atomic with claim mutations:**

1. **Identify all claim-mutation paths:**
   - `_atomic_write_claim()` (low-level write)
   - `record_claim_mutation()` (high-level mutation record)
   - Session lifecycle (close, end, finish)
   - Heartbeat/progress updates

2. **Create `refresh_on_mutation` wrapper:**
   ```python
   def _write_claim_with_projection_refresh(path: Path, payload: dict):
       """Write claim and atomically refresh projection."""
       _atomic_write_claim(path, payload)
       refresh_prewrite_authority_projection(path.parent)
   ```

3. **Update all call sites** to use the wrapper instead of manual refresh

4. **Verify atomicity:**
   - Projection digest must match claim registry digest after every mutation
   - Pre-write hook must not see stale state
   - No window where projection lags behind claims

## Implementation

**Phase 1: Identify mutation paths** (low-risk, no production change)
- Grep for `_atomic_write_claim` and `record_claim_mutation` calls
- Document each caller
- Classify as: session-lifecycle, heartbeat, claim-creation, claim-release

**Phase 2: Create refresh wrapper** (low-risk, new function only)
- Add `_write_claim_with_projection_refresh()`
- Add refresh after `record_claim_mutation()` if not already done

**Phase 3: Update call sites** (high-risk, behavior change)
- Replace direct `_atomic_write_claim()` with wrapper
- Update session lifecycle commands
- Test: verify projection digest matches after each call

**Phase 4: Verify stop-hook** (production validation)
- Run stop-hook multiple times in a session with claim mutations
- Confirm no "stale projection" errors
- Verify pre-write gate uses current projection

## Testing

- `pytest -k projection` for unit tests
- `scripts/self_test.py` for framework self-test
- Manual: create/release claim, check stop-hook immediately
- Benchmark: measure projection refresh overhead

## Success Criteria

✅ Stop-hook never reports stale projection  
✅ Projection digest always matches claims digest after mutation  
✅ No performance regression (refresh <100ms)  
✅ All session lifecycle commands work without manual refresh calls  

## Non-Goals

- Caching the projection to avoid repeated reads (separate optimization)
- Changing the projection format or structure
- Removing manual refresh calls from code that already works

---

**Superseded by Plan #127 after source-level falsification of the writer-gap premise.**
