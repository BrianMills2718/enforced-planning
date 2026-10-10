"""Retain the focused reviewer and host compatibility gate with its exit status."""
from pathlib import Path
import json
import subprocess
import time
folder = Path(__file__).resolve().parent
root = folder.parents[1]
command = ["/usr/bin/python3", "-m", "pytest", "tests/test_pr_review_signoff.py", "tests/test_finish_pr.py", "tests/test_trace_review_guards.py", "tests/test_generate_hook_wiring.py::test_installed_prewrite_runtime_projects_and_classifies_native_payloads", "tests/test_outcome_prewrite_observation.py::test_cli_no_option_is_unchanged_and_both_signs_preserve_ordinary_allow", "-q"]
started = time.monotonic()
with (folder / "reviewer-retention-gate.log").open("x") as log:
    result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
record = {"command": command, "exit_status": result.returncode, "elapsed_seconds": round(time.monotonic()-started,2)}
with (folder / "reviewer-retention-gate.status.json").open("x") as f:
    json.dump(record, f, indent=2)
print(json.dumps(record), flush=True)
raise SystemExit(result.returncode)
