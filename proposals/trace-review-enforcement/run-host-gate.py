"""Run the broad local source gate detached and retain each actual outcome."""
import json
from pathlib import Path
import subprocess
import time

root = Path(__file__).resolve().parents[2]
folder = Path(__file__).resolve().parent
status = folder / "host-gate.status.json"
if status.exists():
    raise SystemExit("Refusing to overwrite a retained gate")
revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
steps = []
with (folder / "host-gate.log").open("x") as log:
    for command in (
        ["ruff", "check", "scripts/", "tests/", "--ignore=F401"],
        ["/usr/bin/python3", "-m", "pytest", "tests/", "-q"],
    ):
        started = time.monotonic()
        print(json.dumps({"revision": revision, "command": command}), file=log, flush=True)
        result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=False)
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
