"""Thin host admission over the explicitly pinned Company Planning provider.

The provider owns review semantics. Disabled and missing-cursor paths stay
observable as uncovered; they are never reported as enforced.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

import yaml


def configuration(root: Path) -> dict[str, Any]:
    path = root / "meta-process.yaml"
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("trace review host configuration must be a mapping")
    data = data.get("meta_process", data)
    if not isinstance(data, dict):
        raise ValueError("meta_process must be a mapping")
    settings = data.get("trace_review", {})
    if not isinstance(settings, dict):
        raise ValueError("trace_review must be a mapping")
    mode = settings.get("mode", "enforce" if (root / ".company-planning/active-execution.json").exists() else "off")
    if mode is False:
        mode = "off"
    if mode not in {"off", "observe", "enforce"}:
        raise ValueError("trace_review.mode must be off, observe or enforce")
    return {**settings, "mode": mode}


def trusted_command(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) != 2 or value[0] != "/usr/bin/python3" or not isinstance(value[1], str):
        raise ValueError("trace_review.command must pin /usr/bin/python3 and one installed provider")
    script = Path(value[1])
    cache = (Path.home() / ".codex/plugins/cache/inside-success/company-planning").resolve()
    if not script.is_absolute() or script.resolve() != script or not script.is_file():
        raise ValueError("trace review provider must be a canonical installed file")
    relative = script.relative_to(cache)
    if len(relative.parts) != 3 or relative.parts[1:] != ("scripts", "validate_trace_review.py"):
        raise ValueError("trace review provider is outside the installed Company Planning layout")
    manifest = json.loads((cache / relative.parts[0] / ".codex-plugin/plugin.json").read_text())
    if not isinstance(manifest, dict) or manifest.get("name") != "company-planning" or manifest.get("version") != relative.parts[0]:
        raise ValueError("trace review provider pin does not match its installed manifest")
    return list(value)


def admit(root: Path, operation: str, session_id: str, claims_dir: Path,
          *, expected_review_plan: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    mode = "enforce"
    try:
        settings = configuration(root)
        mode = settings["mode"]
        if mode == "off":
            return {"mode": mode, "disposition": "uncovered", "valid": False,
                    "errors": ["trace review admission is disabled"]}
        command = trusted_command(settings.get("command"))
        command += ["--repo-root", str(root), "--admission", operation,
                    "--session-id", session_id, "--claims-dir", str(claims_dir)]
        if operation == "completion":
            if not expected_review_plan:
                raise ValueError("completion requires the exact requested review plan")
            command += ["--expected-review-plan", expected_review_plan]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        record = json.loads(result.stdout)
        if (not isinstance(record, dict) or type(record.get("valid")) is not bool
            or record.get("operation") != operation or not isinstance(record.get("errors"), list)):
            raise ValueError("trace review provider returned an invalid admission result")
        valid = record["valid"] and result.returncode == 0 and record.get("exit_status") == 0
        return {"mode": mode, "disposition": ("allow" if valid else "deny") if mode == "enforce" else "observed",
                "valid": valid, "command": command, "provider": record,
                "stdout": result.stdout, "stderr": result.stderr, "exit_status": result.returncode,
                "errors": record.get("errors", [])}
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        return {"mode": mode, "disposition": "deny" if mode == "enforce" else "uncovered",
                "valid": False, "errors": [f"trace review admission unavailable: {exc}"]}
