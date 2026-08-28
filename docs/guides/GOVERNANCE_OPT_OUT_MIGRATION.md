# Governance Opt-Out Defaults — Migration Guide

## Overview

The enforced-planning framework now defaults governance controls to **enabled** (opt-out model) instead of disabled (opt-in model). This change makes coordinated planning and claim tracking the default behavior for all governed repositories.

**Timeline:** New installations as of this framework version receive opt-out defaults. Existing repositories are not automatically migrated.

## What Changed

Two key settings now default to governance-enabled:

| Setting | Old Default | New Default | Meaning |
|---------|------------|-------------|---------|
| `claims.enabled` | `false` | `true` | Coordination claims tracking enabled by default |
| `plans.integrity.mode` | `"off"` | `"enforce"` | Structural plan integrity enforced by default |

## Why This Change

The opt-out model reflects the framework's design principle: repositories benefit from coordinated planning and claim tracking. Requiring explicit opt-in meant many repositories accidentally disabled these safeguards.

With opt-out defaults:
- **Coordinated planning** is the standard behavior
- **Structured claims and tracking** provide observability by default
- Repositories that don't need coordination can explicitly opt-out

## How to Migrate Existing Repositories

### Scenario 1: You Want the New Defaults (Governance-Enabled)

Update your `meta-process.yaml` in the repository root to match the new template:

```yaml
meta_process:
  claims:
    enabled: true                 # <- Changed from false
    require_for_worktree: false
    prewrite_mode: "off"

  plans:
    integrity:
      mode: "enforce"             # <- Changed from "off"
      contract_version: "1.0.0"
      minimum_plan_number: 1
```

Then run:
```bash
python scripts/install_governed_repo.py --repo-root . --write
```

This installs updated hooks and configuration to match the framework's new expectations.

### Scenario 2: You Want to Opt-Out (Keep Governance Disabled)

If your repository doesn't use coordinated planning or claims, explicitly disable these:

```yaml
meta_process:
  claims:
    enabled: false                # <- Explicitly set to false
    require_for_worktree: false
    prewrite_mode: "off"

  plans:
    integrity:
      mode: "off"                 # <- Explicitly set to "off"
      contract_version: "1.0.0"
      minimum_plan_number: 1
```

Then run:
```bash
python scripts/install_governed_repo.py --repo-root . --write
```

### Scenario 3: Gradual Adoption (Observe Mode)

To test governance without enforcement, use observe mode as an intermediate step:

```yaml
meta_process:
  claims:
    enabled: true
    prewrite_mode: "observe"      # <- Observe claims without blocking

  plans:
    integrity:
      mode: "observe"              # <- Report plan issues without blocking
```

Observe mode:
- Records all decisions in audit logs
- Warns about violations without blocking
- Allows you to calibrate policies before enforcing
- Run the report tools to review findings

### Scenario 4: Partial Adoption (Enable Only Claims OR Plans)

You can enable governance selectively:

**Claims only** (no plan integrity):
```yaml
meta_process:
  claims:
    enabled: true
    prewrite_mode: "enforce"      # <- Enforce claim tracking
  plans:
    integrity:
      mode: "off"                  # <- Keep plans uncontrolled
```

**Plans only** (no claims):
```yaml
meta_process:
  claims:
    enabled: false                 # <- No claim coordination
  plans:
    integrity:
      mode: "enforce"              # <- Enforce plan structure
```

## Testing Your Migration

After updating `meta-process.yaml`:

1. Run the framework audit:
   ```bash
   python scripts/audit_governed_repo.py --repo-root . --strict-governed
   ```

2. Run self-tests:
   ```bash
   python scripts/self_test.py
   ```

3. Verify hooks are installed correctly:
   ```bash
   .github/hooks/check-hook-enabled.sh
   ```

## Rollback

If you need to revert to opt-in behavior (the old default), explicitly set:

```yaml
meta_process:
  claims:
    enabled: false
  plans:
    integrity:
      mode: "off"
```

This is fully reversible and doesn't affect any committed work.

## FAQs

**Q: Will this break my existing repository?**

A: No. Existing repositories continue working as configured. Only new installations and explicitly migrated repositories adopt the opt-out defaults.

**Q: What happens if I don't migrate?**

A: Your repository remains in its current state. You should migrate when you have time to test the changes. The framework will support both old and new configs indefinitely.

**Q: Can I migrate just the framework and defer config changes?**

A: Yes. You can upgrade the framework code while keeping your existing `meta-process.yaml` config unchanged. Your settings take precedence.

**Q: What's the performance impact of enabling claims?**

A: Minimal. Claim tracking adds negligible overhead—it's just file I/O for session metadata. Plans integrity checking runs only at session boundaries.

**Q: Can I enable claims but keep prewrite_mode off?**

A: Yes. This is a valid configuration (Scenario 4). Claims are tracked but not enforced on writes.

## Next Steps

1. Review your current `meta-process.yaml` configuration
2. Decide whether you want to adopt the new defaults (Scenario 1/2)
3. Make the change and test with `audit_governed_repo.py`
4. Verify hooks are working: commit a test and verify claim tracking
5. If using observe mode, review audit logs weekly
6. When confident, promote from observe to enforce mode

## Questions or Issues?

If you encounter issues migrating:
- Check `docs/reference/CONFIG_REFERENCE.md` for the full config reference
- Review `PLANNING_OPERATING_MODEL.md` for governance concepts
- Run `audit_governed_repo.py --strict-governed` for detailed diagnostics
