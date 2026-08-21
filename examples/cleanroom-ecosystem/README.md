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
{"instance_id":"acme-alpha","component_source":"git://example/governance","policy_pack_name":"acme-baseline","projects":[{"project_id":"shared-lib","relative_path":"projects/shared-lib"},{"project_id":"hello-app","relative_path":"projects/hello-app"}]}
```

```bash
python scripts/cleanroom_alpha.py --consumer-config consumer.json --root /tmp/acme-cleanroom plan
python scripts/cleanroom_alpha.py --consumer-config consumer.json --root /tmp/acme-cleanroom apply
```

A copy-ready neutral template lives in `consumer-template/consumer.json`.

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

## Authentic Governed-Delivery Vertical

Plan 113 adds a separate real-agent path on top of the same clean-room. Prepare
the default fixture first, then install the governed `hello-app` task:

```bash
cleanroom_root="$(mktemp -d)/cleanroom"
python scripts/cleanroom_alpha.py --root "$cleanroom_root" apply
python scripts/governed_delivery.py prepare \
  --cleanroom-root "$cleanroom_root" \
  --framework-root .
python scripts/governed_delivery.py probe \
  --task-root "$cleanroom_root/projects/hello-app"
```

The first probe is expected to fail because `--name Ada` is not implemented.
The coding agent works only in the generated `hello-app`: it reads
`governed-task.json` and `CLAUDE.md`, creates one bounded plan, changes the
declared source/docs/plan paths, runs `make verify`, and commits the result.
Completion is then checked independently:

```bash
python scripts/governed_delivery.py verify \
  --task-root "$cleanroom_root/projects/hello-app" \
  --agent-session-id "codex:SESSION_ID"
```

Two unchanged failing probes return `course_correction_required`. Before
probing again, use the `checkpoint` command to name the prior assumption, the
changed assumption, and the next tactic. A worker-authored completion report is
never an input to the terminal verdict.
