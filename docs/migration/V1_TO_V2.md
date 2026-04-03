# V1 → V2 relationships.yaml Migration Guide

**Applies to:** Any repo using a `relationships.yaml` without `version: 2`

---

## What Changed

### V1 Format

```yaml
# No version field
required_reading:
  defaults:
    - CLAUDE.md

couplings:
  - sources: ["src/core.py"]
    docs: ["docs/architecture.md"]
    description: "Core module documented in architecture doc"
    soft: false            # hard coupling — was the only enforcement option

  - sources: ["src/api.py"]
    docs: ["docs/api.md"]
    soft: true             # soft/warn — just a warning, no block

verify_sync:
  - check: "generated/schema.json matches src/schema.py"
    command: "python scripts/check_schema.py"
```

### V2 Format

```yaml
version: 2    # required

coupling_types:
  locked:
    action: block
    actor: programmatic
  generated:
    action: regenerate
    actor: programmatic
  validated:
    action: agent_verify
    actor: agent

required_reading:
  defaults:
    - CLAUDE.md

couplings:
  - sources: ["src/core.py"]
    docs: ["docs/architecture.md"]
    description: "Core module documented in architecture doc"
    type: locked           # replaces soft: false → programmatic block at commit

  - sources: ["src/api.py"]
    docs: ["docs/api.md"]
    description: "API behavior described in api.md"
    type: validated        # replaces soft: true → agent verifies on change

  - sources: ["src/schema.py"]
    docs: ["generated/schema.json"]
    description: "JSON schema generated from Python models"
    type: generated
    regenerate_cmd: "python scripts/gen_schema.py"
```

---

## What V2 Adds

| V1 | V2 | What Changes |
|----|----|-------------|
| `soft: false` | `type: locked` | `check_locked_couplings.py` blocks commit if doc not staged |
| `soft: true` | `type: validated` | `verify_coupling.py` agent verifies doc is still accurate |
| `verify_sync` | `type: generated` | `apply_coupling_fix.py` can auto-regenerate |
| No version field | `version: 2` | Enables V2 tooling |

**V1 files still work.** V2 adds capabilities without breaking V1 behavior.

---

## Why Migrate?

1. **Locked couplings block commits** — `soft: false` was advisory in practice. `type: locked` fires `check_locked_couplings.py` at commit time: if you change `src/core.py`, you must also stage `docs/architecture.md`. No more "forgot to update the doc."

2. **Validated couplings get agent review** — `soft: true` was a warning nobody read. `type: validated` fires `verify_coupling.py` which produces a structured verdict (CURRENT / STALE / UNCERTAIN) and can propose fixes or escalate to human review.

3. **Generated couplings auto-regenerate** — `verify_sync` needed manual running. `type: generated` integrates with `apply_coupling_fix.py` to run the regeneration command automatically.

---

## Migration Steps

### Option A: Automated (recommended)

```bash
# Back up first
cp relationships.yaml relationships.yaml.v1.bak

# Dry run to see what will change
python scripts/migrate_relationships.py relationships.yaml --dry-run

# Apply migration
python scripts/migrate_relationships.py relationships.yaml

# Review the output — migration maps soft: false → locked, soft: true → validated
# Adjust types if the defaults aren't right for specific couplings

# Run tests
python -m pytest tests/ -q

# Commit
git add relationships.yaml
git commit -m "[Plan #N] migrate relationships.yaml to V2"
```

### Option B: Manual

1. Add `version: 2` at the top
2. Add the `coupling_types` block (copy from template above)
3. Replace `soft: false` with `type: locked` on each coupling
4. Replace `soft: true` with `type: validated` on each coupling
5. Move `verify_sync` entries to couplings with `type: generated` and `regenerate_cmd:`
6. Remove the old `verify_sync:` top-level key

---

## What Breaks

**Nothing breaks automatically.** V1 files parse without error. The new tooling activates only when `version: 2` is present and `coupling_types` is defined.

After migrating:
- `check_locked_couplings.py` will start blocking commits at `type: locked` couplings — this is intentional
- `verify_coupling.py` will activate for `type: validated` couplings in CI — review the first few runs

---

## Type Selection Guide

| Situation | Type to use |
|-----------|------------|
| Doc must be updated whenever code changes (contract, ADR) | `locked` |
| Doc is LLM-written prose that should stay accurate | `validated` |
| File is auto-generated from code (JSON schema, API spec) | `generated` |
| Doc is aspirational/reference, not contract-critical | `validated` (soft enforcement) |

---

## Reference

- `scripts/migrate_relationships.py` — automated migration script
- `scripts/check_locked_couplings.py` — V2 locked coupling enforcement
- `scripts/verify_coupling.py` — V2 validated coupling agent verification
- `scripts/apply_coupling_fix.py` — automated fix application
- `docs/designs/RELATIONSHIPS_V2_DESIGN.md` — full V2 design rationale
