import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_CAPS_SCRIPT = REPO_ROOT / "scripts" / "check_plan_capabilities.py"


def _load_module():
    module_name = "check_plan_capabilities_module"
    spec = importlib.util.spec_from_file_location(module_name, CHECK_CAPS_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def test_warns_when_capability_plan_missing_goal_graph_headers(tmp_path: Path) -> None:
    module = _load_module()
    plan_file = tmp_path / "178_sample.md"
    plan_file.write_text(
        "# Plan #178: Sample\n"
        "**Status:** Planned\n\n"
        "## Capabilities\n\n"
        "| Capability | Input Schema | Output Schema | Producer | Consumer(s) | Cost Tier |\n"
        "|-----------|-------------|---------------|----------|-------------|-----------|\n"
        "| `investigate(question)` | `str` | `Result` | research_v3 | onto-canon6 | expensive |\n",
        encoding="utf-8",
    )

    result = module.check_plan(plan_file)

    assert result["status"] == "warning"
    assert result["has_capabilities"] is True
    assert result["missing_goal_graph_fields"] == ["phase_ref", "goal_ref"]
    assert "goal-graph header fields" in result["message"]


def test_accepts_capability_plan_with_goal_graph_headers(tmp_path: Path) -> None:
    module = _load_module()
    plan_file = tmp_path / "179_sample.md"
    plan_file.write_text(
        "# Plan #179: Sample\n"
        "**Status:** Planned\n"
        "**phase_ref:** \"Phase 2.1\"\n"
        "**goal_ref:** \"research-quality\"\n\n"
        "## Capabilities\n\n"
        "| Capability | Input Schema | Output Schema | Producer | Consumer(s) | Cost Tier |\n"
        "|-----------|-------------|---------------|----------|-------------|-----------|\n"
        "| `investigate(question)` | `str` | `Result` | research_v3 | onto-canon6 | expensive |\n",
        encoding="utf-8",
    )

    result = module.check_plan(plan_file)

    assert result["status"] == "ok"
    assert result["missing_goal_graph_fields"] == []
    assert result["message"] == "Has Capabilities section and goal-graph headers"


def test_cli_json_reports_missing_goal_ref(tmp_path: Path) -> None:
    plan_file = tmp_path / "185_sample.md"
    plan_file.write_text(
        "# Plan #185: Sample\n"
        "**Status:** Planned\n"
        "**phase_ref:** \"Phase 2.1\"\n\n"
        "## Capabilities\n\n"
        "| Capability | Input Schema | Output Schema | Producer | Consumer(s) | Cost Tier |\n"
        "|-----------|-------------|---------------|----------|-------------|-----------|\n"
        "| `route(goal)` | `GoalRequest` | `list[CapabilityMatch]` | ecosystem-ops | moltbot | cheap |\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(CHECK_CAPS_SCRIPT), "--json", str(plan_file)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["warnings"] == 1
    assert payload["results"][0]["missing_goal_graph_fields"] == ["goal_ref"]
    assert payload["results"][0]["status"] == "warning"
