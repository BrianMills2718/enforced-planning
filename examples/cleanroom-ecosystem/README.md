# Clean-Room Ecosystem Example

This directory anchors the canonical source location for the generated
clean-room alpha. `enforced_planning.cleanroom_alpha` currently implements the
fixture generator and deterministic verified loop; generated external
instances are disposable evidence, never source authority.

Use the CLI from the repository root:

```bash
python scripts/cleanroom_alpha.py --root /tmp/loop-engineering-cleanroom plan
python scripts/cleanroom_alpha.py --root /tmp/loop-engineering-cleanroom apply
python scripts/cleanroom_alpha.py --root /tmp/loop-engineering-cleanroom verify
python scripts/cleanroom_alpha.py --root /tmp/loop-engineering-cleanroom run-demo
python scripts/cleanroom_alpha.py --root /tmp/loop-engineering-cleanroom reset
```

For a consumer-owned instance, create a neutral JSON metadata file and pass it
to `plan` and `apply`:

```json
{"instance_id":"acme-alpha","component_source":"git://example/governance","policy_pack_name":"acme-baseline"}
```

```bash
python scripts/cleanroom_alpha.py --consumer-config consumer.json --root /tmp/acme-cleanroom plan
python scripts/cleanroom_alpha.py --consumer-config consumer.json --root /tmp/acme-cleanroom apply
```

The config contains identity and ownership metadata only; it must not contain
absolute home paths, credentials, or a personal project inventory.

`run-demo` starts from one intentional `hello-app` failure, applies the repair
declared in generated `loop-spec.json`, and succeeds only after `make verify`
passes. It writes a canonical receipt under `.loop-engineering/traces/`.

Negative-control modes are agent-drivable too:

```bash
python scripts/cleanroom_alpha.py --root /tmp/loop-engineering-cleanroom run-demo --worker-mode self-certify --max-iterations 1
python scripts/cleanroom_alpha.py --root /tmp/loop-engineering-cleanroom run-demo --worker-mode no-op --max-iterations 1
python scripts/cleanroom_alpha.py --root /tmp/loop-engineering-cleanroom verify-trace --trace-path /tmp/loop-engineering-cleanroom/.loop-engineering/traces/RUN_ID.json
```

Reset and apply again between demo modes because the successful repair changes
the disposable fixture state.
