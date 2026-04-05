# Design: Phase 8 Tool Support Matrix

**Date:** 2026-04-04
**Status:** Accepted

## Purpose

Define one support-tier vocabulary for `enforced-planning` so "portable" and
"supported" mean the same thing across the framework docs.

## Support Tiers

| Tier | Meaning | Required Evidence |
|------|---------|-------------------|
| `native-interactive` | Tool has verified interactive enforcement parity for the canonical governed-repo experience, including read-gating or equivalent edit-time control. | Documented hook/event integration, installer path, and committed evidence artifact |
| `portable-governed` | Tool can consume the governed-repo contract through generated `AGENTS.md`, plan/ADR docs, CLI scripts, and deterministic validators, but does not have verified native interactive read-gating parity. | Verified install/audit path plus committed evidence that the tool can navigate the repo and run the deterministic governance surfaces |
| `legacy-compatible` | Surface still exists for compatibility or migration, but it is not the canonical sync path and should not be treated as the long-term product contract. | Documented compatibility mode and explicit scoping in installer/docs |
| `unsupported` | No verified support claim. The framework does not promise that the workflow is ready or safe for that tool class yet. | None; this is the default until evidence exists |

## Current Matrix

| Tool / Surface Class | Tier | Notes |
|----------------------|------|-------|
| Claude Code | `native-interactive` | Canonical read-gating path via `.claude/hooks/` |
| Terminal/CLI agents that can read repo files and run scripts | `portable-governed` | Use `AGENTS.md`, plan docs, and deterministic validators |
| Generated `AGENTS.md` consumers without hook parity | `portable-governed` | Governance is portable, but interactive read-gating is not |
| `install.sh --full` / `install.sh --pre-commit` rollout | `legacy-compatible` | Compatibility surfaces, not canonical sync authority |
| Tools without documented integration evidence | `unsupported` | Do not claim support until evidence is committed |

## Feature Mapping By Tier

| Feature | native-interactive | portable-governed | legacy-compatible | unsupported |
|---------|--------------------|-------------------|-------------------|-------------|
| `CLAUDE.md` / source governance docs | yes | yes | yes | maybe |
| generated `AGENTS.md` | yes | yes | yes | maybe |
| deterministic validators and CLI scripts | yes | yes | yes | maybe |
| canonical installer / audit path | yes | yes | partial | no claim |
| interactive read-gating parity | yes | no | partial/legacy | no |
| semantic review workflow | source-repo CLI | source-repo CLI | legacy wrapper possible | no claim |

## Promotion Rules

A tool or tool class only moves upward in support tier when all of these are
true:

1. a concrete workflow is documented
2. the workflow is exercised against a real governed repo
3. the evidence artifact is committed in this repo
4. top-level docs are updated to match the claim

Until then, default to the lower tier or to `unsupported`.

## Documentation Rules

- `README.md` explains the tier vocabulary at the framework-source level
- `GETTING_STARTED.md` explains what installed-consumer users get by tier
- `hooks/README.md` explains the hook boundary by tier
- no doc should claim named-tool support beyond the evidence currently committed
