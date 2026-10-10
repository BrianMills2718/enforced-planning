"""Run the broad local source gate detached and retain each actual outcome."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[2]
folder = Path(__file__).resolve().parent
prefix = sys.argv[1] if len(sys.argv) > 1 else "host-gate"
if not prefix or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in prefix):
    raise SystemExit("Gate prefix must be a portable identifier")
status = folder / f"{prefix}.status.json"
if status.exists():
    raise SystemExit("Refusing to overwrite a retained gate")
revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
steps = []
diagnostics = folder / f"{prefix}.commands.jsonl"
with diagnostics.open("x"):
    pass
with (folder / f"{prefix}.log").open("x") as log:
    for command in (
        ["ruff", "check", "scripts/", "tests/", "--ignore=F401"],
        ["/usr/bin/python3", str(folder / "diagnose-fixture-failures.py"), "tests/", "-q"],
    ):
        started = time.monotonic()
        print(json.dumps({"revision": revision, "command": command}), file=log, flush=True)
        env = dict(os.environ, EP_DIAGNOSTIC_RESULTS_FILE=str(diagnostics))
        result = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
        step = {"command": command, "exit_status": result.returncode,
                "elapsed_seconds": round(time.monotonic() - started, 2)}
        steps.append(step)
        print(json.dumps(step), file=log, flush=True)
        if result.returncode:
            break
outcome = {"revision": revision, "steps": steps,
           "exit_status": steps[-1]["exit_status"]}
status.write_text(json.dumps(outcome, indent=2) + "\n")
raise SystemExit(outcome["exit_status"])
