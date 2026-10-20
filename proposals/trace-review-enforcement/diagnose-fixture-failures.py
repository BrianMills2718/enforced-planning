"""Replay failed synthetic fixtures with their otherwise swallowed command results."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
original_run = subprocess.run
diagnostic_path = Path(os.environ["EP_DIAGNOSTIC_RESULTS_FILE"])


def retain(record):
    with diagnostic_path.open("a") as log:
        log.write(json.dumps(record, default=str) + "\n")


def observed_run(*args, **kwargs):
    try:
        result = original_run(*args, **kwargs)
    except subprocess.CalledProcessError as error:
        retain({"command": error.cmd, "cwd": str(kwargs.get("cwd", "")), "exit_status": error.returncode, "stdout": error.stdout, "stderr": error.stderr})
        raise
    if result.returncode:
        retain({"command": result.args, "cwd": str(kwargs.get("cwd", "")), "exit_status": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    return result


subprocess.run = observed_run
raise SystemExit(pytest.main(sys.argv[1:]))
