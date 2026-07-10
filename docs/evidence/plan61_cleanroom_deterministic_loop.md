# Plan #61 Deterministic Loop Evidence

Status: Complete (2026-07-09).

## Coverage Baseline

| Grade | Count |
|---|---:|
| A | 0 |
| B | 0 |
| C | 0 |
| D | 7 |
| F | 0 |

The implementation and controls raise all seven requirements to A (source plus
automated positive and negative controls), with one explicit alpha limitation:
the worker is deterministic and local, not a hostile-code sandbox or signed
supply-chain boundary.

## Final Evidence

| Requirement | Grade | Evidence |
|---|---|---|
| A5 verified repair loop | A | repair-loop test and fresh external run |
| Independent success certification | A | self-certification negative control |
| Bounded stop conditions | A | no-op and zero-budget tests |
| Canonical trace checksum integrity | A | unrecomputed mutation and transition-order tests |
| Verifier integrity | A | guarded verifier-script tamper test plus verifier-selector (loop-spec) tamper test |
| Interruption truthfulness | A | interrupted receipt test |
| Generic runner boundary | A | source scan and declarative loop-spec |

## Commands Run

- `pytest -q tests/test_cleanroom_alpha.py tests/test_check_notebook_registry.py` — 23 passed.
- notebook registry validation — passed.
- Plan #61 validation — passed.
- `python scripts/self_test.py` — all checks passed.
- `git diff --check` — passed.
- Fresh external root apply/verify/run-demo/reset — passed.

## Disposition

This proves portable state, worker, verifier, stop, budget, trace checksums, reset,
tamper, and interruption contracts. Production security, authentication,
signed provenance, hostile-code isolation, and a real agent adapter remain
explicitly deferred.

The trace and install-receipt digests are unkeyed checksums. They detect
accidental or unilateral mutation, not an adversary who can rewrite the artifact
and recompute its digest; no cryptographic tamper-resistance is claimed.

## 2026-07-09 Audit Follow-Up: Verifier Trust-Chain Anchor

An adversarial audit found that the original verifier-integrity guard was
asymmetric: `_verify_guarded_files` hashed the verifier *scripts* (Makefiles),
but `loop-spec.json` — which selects the verifier command *and* declares the
guarded-file hash list — was itself anchored by nothing. Editing the unguarded
selector (`verifier.command -> ["true"]`, `require_initial_failure -> false`)
produced a passing `run-demo` and a passing `verify-trace` while the real
`make verify` still failed.

Fix: the install receipt now records `owned_file_digests` for every generated
file. `run_demo_loop` verifies the `loop-spec.json` digest before trusting the
spec (`loop_spec_integrity_failed`), and `verify_cleanroom` reports a tampered
selector as `verifier_chain_integrity`. Negative controls
`test_run_demo_rejects_tampered_loop_spec` and
`test_verify_flags_tampered_loop_spec` cover both surfaces. The digest anchor is
still an unkeyed checksum (an editor who also rewrites the receipt and recomputes
its digest is out of scope, as above), but the leaf-vs-selector asymmetry is
closed: tampering any link in the verifier trust chain is now detected.
