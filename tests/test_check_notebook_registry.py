import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_notebook_registry.py"


def _load_module():
    module_name = "check_notebook_registry_module"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _write_notebook(
    path: Path,
    *,
    journey_id: str,
    notebook_mode: str,
    phase_ids: list[str],
    phase_blocks: list[str],
) -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Demo Journey\n",
                    f"Journey Name: {journey_id}\n",
                    "Journey Purpose: Validate notebook registry behavior.\n",
                    f"Notebook Mode: {notebook_mode}\n",
                    "Related Docs:\n",
                    "- demo/docs/plan.md\n",
                    "Related Code:\n",
                    "- demo/src/runtime.py\n",
                    "Related Tests:\n",
                    "- demo/tests/test_runtime.py\n",
                    "Related Evidence:\n",
                    "- demo/docs/evidence.md\n",
                ],
            },
            *[
                {"cell_type": "markdown", "metadata": {}, "source": [block]}
                for block in phase_blocks
            ],
        ],
        "metadata": {
            "journey_meta": {
                "journey_id": journey_id,
                "notebook_mode": notebook_mode,
                "phase_ids_in_order": phase_ids,
            }
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(notebook, indent=2), encoding="utf-8")


def _valid_registry_text() -> str:
    return """
version: 1
journeys:
  - journey_id: demo_journey
    title: demo_journey
    purpose: Demo journey for tests.
    notebook: demo/notebooks/demo.ipynb
    notebook_mode: mixed
    deep_dive_notebooks:
      - demo/notebooks/deep_dive.ipynb
    related_docs:
      - demo/docs/plan.md
    related_code:
      - demo/src/runtime.py
    related_tests:
      - demo/tests/test_runtime.py
    related_evidence:
      - demo/docs/evidence.md
    phases:
      - phase_id: phase_one
        title: Phase One
        purpose: Demonstrate one live phase.
        input_artifact: raw_input
        output_artifact: live_output
        acceptance:
          - Contract is visible.
        status: proven
        execution_mode: live
        proof_critical: true
        docs:
          - demo/docs/plan.md
        code:
          - demo/src/runtime.py
        tests:
          - demo/tests/test_runtime.py
        evidence:
          - demo/docs/evidence.md
      - phase_id: phase_two
        title: Phase Two
        purpose: Demonstrate one stub phase.
        input_artifact: live_output
        output_artifact: stub_output
        acceptance:
          - Stub artifact is explicit.
        status: planned
        execution_mode: stub
        proof_critical: false
        docs:
          - demo/docs/plan.md
"""


def _create_demo_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace_root = tmp_path / "workspace"
    demo_root = workspace_root / "demo"
    (demo_root / "notebooks").mkdir(parents=True)
    (demo_root / "docs").mkdir()
    (demo_root / "src").mkdir()
    (demo_root / "tests").mkdir()

    (demo_root / "docs" / "plan.md").write_text("# plan\n", encoding="utf-8")
    (demo_root / "docs" / "evidence.md").write_text("# evidence\n", encoding="utf-8")
    (demo_root / "src" / "runtime.py").write_text('"""runtime"""\n', encoding="utf-8")
    (demo_root / "tests" / "test_runtime.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )

    phase_blocks = [
        "## Phase 1: Phase One\n"
        "Purpose: Demonstrate one live phase.\n"
        "Input -> Output: raw_input -> live_output\n"
        "Acceptance Criteria:\n"
        "- Contract is visible.\n"
        "Status: proven\n"
        "Execution Mode: live\n",
        "## Phase 2: Phase Two\n"
        "Purpose: Demonstrate one stub phase.\n"
        "Input -> Output: live_output -> stub_output\n"
        "Acceptance Criteria:\n"
        "- Stub artifact is explicit.\n"
        "Status: planned\n"
        "Execution Mode: stub\n",
    ]
    _write_notebook(
        demo_root / "notebooks" / "demo.ipynb",
        journey_id="demo_journey",
        notebook_mode="mixed",
        phase_ids=["phase_one", "phase_two"],
        phase_blocks=phase_blocks,
    )
    _write_notebook(
        demo_root / "notebooks" / "deep_dive.ipynb",
        journey_id="demo_journey_deep_dive",
        notebook_mode="planning",
        phase_ids=[],
        phase_blocks=[],
    )

    registry_path = workspace_root / "enforced-planning" / "notebooks" / "notebook_registry.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(_valid_registry_text(), encoding="utf-8")
    return workspace_root, registry_path


def test_validate_notebook_registry_accepts_valid_registry(tmp_path: Path) -> None:
    module = _load_module()
    workspace_root, registry_path = _create_demo_workspace(tmp_path)
    module.WORKSPACE_ROOT = workspace_root

    registry = module.load_notebook_registry(registry_path)
    result = module.validate_notebook_registry(registry, registry_path=registry_path)

    assert result.ok
    assert result.errors == []
    assert result.journeys_checked == ["demo_journey"]


def test_validate_notebook_registry_accepts_repo_relative_paths(tmp_path: Path) -> None:
    module = _load_module()
    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "repo"
    (repo_root / "notebooks").mkdir(parents=True)
    (repo_root / "docs").mkdir()
    (repo_root / "src").mkdir()
    (repo_root / "tests").mkdir()

    (repo_root / "docs" / "plan.md").write_text("# plan\n", encoding="utf-8")
    (repo_root / "docs" / "evidence.md").write_text("# evidence\n", encoding="utf-8")
    (repo_root / "src" / "runtime.py").write_text('"""runtime"""\n', encoding="utf-8")
    (repo_root / "tests" / "test_runtime.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )
    _write_notebook(
        repo_root / "notebooks" / "demo.ipynb",
        journey_id="repo_relative_journey",
        notebook_mode="mixed",
        phase_ids=["phase_one"],
        phase_blocks=[
            "## Phase 1: Phase One\n"
            "Purpose: Demonstrate one repo-relative phase.\n"
            "Input -> Output: raw_input -> live_output\n"
            "Acceptance Criteria:\n"
            "- Contract is visible.\n"
            "Status: planned\n"
            "Execution Mode: stub\n",
        ],
    )
    registry_path = repo_root / "notebooks" / "notebook_registry.yaml"
    registry_path.write_text(
        """
version: 1
journeys:
  - journey_id: repo_relative_journey
    title: repo_relative_journey
    notebook: notebooks/demo.ipynb
    notebook_mode: mixed
    related_docs:
      - docs/plan.md
    related_code:
      - src/runtime.py
    related_tests:
      - tests/test_runtime.py
    related_evidence:
      - docs/evidence.md
    phases:
      - phase_id: phase_one
        title: Phase One
        purpose: Demonstrate one repo-relative phase.
        input_artifact: raw_input
        output_artifact: live_output
        acceptance:
          - Contract is visible.
        status: planned
        execution_mode: stub
        docs:
          - docs/plan.md
        code:
          - src/runtime.py
        tests:
          - tests/test_runtime.py
        evidence:
          - docs/evidence.md
    """,
        encoding="utf-8",
    )

    module.WORKSPACE_ROOT = workspace_root
    result = module.validate_notebook_registry(
        module.load_notebook_registry(registry_path),
        registry_path=registry_path,
    )

    assert result.ok
    assert result.errors == []


def test_validate_notebook_registry_rejects_invalid_phase_status(tmp_path: Path) -> None:
    module = _load_module()
    workspace_root, registry_path = _create_demo_workspace(tmp_path)
    module.WORKSPACE_ROOT = workspace_root

    broken = registry_path.read_text(encoding="utf-8").replace("status: planned", "status: invalid")
    registry_path.write_text(broken, encoding="utf-8")

    registry = module.load_notebook_registry(registry_path)
    result = module.validate_notebook_registry(registry, registry_path=registry_path)

    assert not result.ok
    assert any("invalid status" in error for error in result.errors)


def test_validate_notebook_registry_rejects_missing_phase_contract_cell(tmp_path: Path) -> None:
    module = _load_module()
    workspace_root, registry_path = _create_demo_workspace(tmp_path)
    module.WORKSPACE_ROOT = workspace_root

    notebook_path = workspace_root / "demo" / "notebooks" / "demo.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    notebook["cells"] = notebook["cells"][:-1]
    notebook_path.write_text(json.dumps(notebook, indent=2), encoding="utf-8")

    registry = module.load_notebook_registry(registry_path)
    result = module.validate_notebook_registry(registry, registry_path=registry_path)

    assert not result.ok
    assert any("missing explicit section for phase 'Phase Two'" in error for error in result.errors)


def test_detect_workspace_root_handles_worktree_checkout(tmp_path: Path) -> None:
    # Built under tmp_path: detection resolves symlinks, so a hardcoded maintainer
    # path answered differently on a host where that workspace is a symlink.
    module = _load_module()
    workspace = tmp_path.resolve() / "projects"

    main_checkout = workspace / "enforced-planning"
    sibling_worktree = workspace / "enforced-planning_worktrees" / "plan-77-wave4-notebook-subtree"
    nested_worktree = main_checkout / "worktrees" / "plan-77-wave4-notebook-subtree"

    assert module._detect_workspace_root(main_checkout) == workspace
    assert module._detect_workspace_root(sibling_worktree) == workspace
    assert module._detect_workspace_root(nested_worktree) == workspace


def test_check_notebook_registry_cli_validates_demo_registry(tmp_path: Path) -> None:
    _, registry_path = _create_demo_workspace(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(
                [
                    "import importlib.util",
                    "import json",
                    "import pathlib",
                    "import sys",
                    f"script_path = pathlib.Path({str(SCRIPT_PATH)!r})",
                    f"registry_path = pathlib.Path({str(registry_path)!r})",
                    f"workspace_root = pathlib.Path({str(registry_path.parent.parent.parent)!r})",
                    "spec = importlib.util.spec_from_file_location('check_notebook_registry_module', script_path)",
                    "assert spec is not None and spec.loader is not None",
                    "module = importlib.util.module_from_spec(spec)",
                    "sys.modules['check_notebook_registry_module'] = module",
                    "spec.loader.exec_module(module)",
                    "module.WORKSPACE_ROOT = workspace_root",
                    "sys.argv = [str(script_path), '--config', str(registry_path), '--journey-id', 'demo_journey', '--json']",
                    "raise SystemExit(module.main())",
                ]
            ),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["journeys_checked"] == ["demo_journey"]
    assert payload["registry_path"] == str(registry_path)
