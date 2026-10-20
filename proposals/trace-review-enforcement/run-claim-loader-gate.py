"""Retain the bounded native coordination regression check."""
import json
from pathlib import Path
import subprocess
import time
import sys
folder = Path(__file__).resolve().parent
root = folder.parents[1]
command = ["/usr/bin/python3", "-m", "pytest", "tests/test_claim_yaml_loading.py", "tests/test_coordination_hook.py", "tests/test_check_coordination_claims.py", "tests/test_prewrite_claim_projection.py", "tests/test_coordination_messages.py::test_codex_lifecycle_hook_does_not_adopt_a_different_session_claim", "tests/test_e2e_sanctioned_entrypoints.py::test_maintenance_worktree_and_session_close_real_subprocess_roundtrip", "-ra"]
prefix = sys.argv[1] if len(sys.argv) > 1 else "claim-loader-gate"
if not prefix or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in prefix):
    raise SystemExit("invalid gate prefix")
started = time.monotonic()
with (folder / f"{prefix}.log").open("x") as log:
    result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
record = {"command": command, "exit_status": result.returncode, "elapsed_seconds": round(time.monotonic() - started, 2)}
with (folder / f"{prefix}.status.json").open("x") as f:
    json.dump(record, f, indent=2)
print(json.dumps(record), flush=True)
raise SystemExit(result.returncode)
