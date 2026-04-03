# Enforced Planning — Deferred Features Backlog

Features parked here are technically sound but have no near-term consumer or
unresolved dependencies that make implementation premature. Each entry states
the blocking condition; re-evaluate when the blocker resolves.

---

## Visibility Grammar

**What:** Bazel-style `__pkg__` / `__subpackages__` scoping for doc governance.
Allows a coupling rule to declare "this applies to all files under `src/auth/`"
rather than listing each file explicitly.

**Why deferred:** No consuming project has needed cross-directory scope control
yet. File-level coupling declarations have been sufficient for all repos in the
current ecosystem.

**Blocker:** A repo with ≥ 2 distinct teams each owning a subdirectory,
where file-level coupling lists have become unmanageable.

**Would unblock:** Distributed governance (see below); large monorepo adoption.

**Re-evaluation trigger:** First governed monorepo where a team finds `paths:`
lists in `relationships.yaml` too verbose to maintain.

---

## Distributed Governance

**What:** Per-directory `.governance.yaml` files (Buck2 `BUCK` / `BUILD` pattern).
Each directory owns its governance declarations; the framework aggregates them
at CI time rather than requiring a single root-level `relationships.yaml`.

**Why deferred:** Requires visibility grammar first (needs a scope model before
per-directory declarations make sense). Also requires a repo with ≥ 3
subdirectory teams each needing independent governance.

**Blocker:** Visibility grammar (above) + a monorepo with multi-team governance
needs.

**Would unblock:** Cross-team governance in monorepos without requiring a
centralized `relationships.yaml` editor.

**Re-evaluation trigger:** Visibility grammar is implemented AND a consumer repo
exists with ≥ 3 teams needing independent governance scopes.

---

## Notes

- Items are listed in dependency order (visibility grammar must precede
  distributed governance).
- Removing items from this backlog requires resolving the stated blocker AND
  writing a plan doc before implementation begins.
- Deferred items should **not** appear in active roadmap phase tables — they
  create false urgency and clutter prioritization.
