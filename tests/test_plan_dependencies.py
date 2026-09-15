"""Tests for the Plan #289 plan dependency contract validator."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from enforced_planning.plan_dependencies import (
    PlanFile,
    build_dependency_graph,
    build_known_ids,
    check_cycles,
    parse_plan,
    validate_plan_dependencies,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "plan_dependencies"
SCRIPT = REPO_ROOT / "scripts" / "validate_plan_dependencies.py"
HOOK = REPO_ROOT / "hooks" / "git" / "pre-commit"
PROJECTS = {"alpha": FIXTURES / "alpha", "beta_tools": FIXTURES / "beta"}


def _sources(project_id: str, root: Path) -> list[PlanFile]:
    return [
        PlanFile(project_id, path.relative_to(root).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(root.rglob("*.md"))
    ]


@pytest.fixture(scope="module")
def corpus() -> tuple[list[PlanFile], set[str], dict[str, list[str]]]:
    sources = [source for pid, root in PROJECTS.items() for source in _sources(pid, root)]
    parsed = [plan for plan in (parse_plan(source) for source in sources) if plan is not None]
    return sources, build_known_ids(parsed), build_dependency_graph(parsed)


def _codes_for(filename: str, corpus: tuple[list[PlanFile], set[str], dict[str, list[str]]]) -> list[str]:
    sources, known_ids, graph = corpus
    source = next(s for s in sources if s.relative_path.endswith(filename))
    errors = validate_plan_dependencies([source], known_ids, repo_project_id=source.project_id, graph=graph)
    assert all(error.path == source.relative_path for error in errors)
    return [error.code for error in errors]


def test_valid_plan_with_cross_repo_dependency_on_unconverted_plan(corpus) -> None:
    """alpha#1 depends on beta_tools#7, which has no frontmatter and resolves by derived id."""
    _, known_ids, _ = corpus
    assert "beta-tools#7" in known_ids  # derived from filename number + normalized registry id
    assert _codes_for("01_valid.md", corpus) == []


def test_reviewed_empty_dependencies_pass(corpus) -> None:
    assert _codes_for("02_reviewed_none.md", corpus) == []


def test_missing_dependencies_field_refused(corpus) -> None:
    assert _codes_for("03_missing_dependencies.md", corpus) == ["missing_dependencies"]


def test_empty_dependencies_without_review_date_refused(corpus) -> None:
    assert _codes_for("04_empty_without_review.md", corpus) == ["missing_dependencies_reviewed"]


def test_dependency_without_evidence_refused(corpus) -> None:
    assert _codes_for("05_missing_evidence.md", corpus) == ["missing_dependency_evidence"]


def test_unresolved_dependency_refused(corpus) -> None:
    assert _codes_for("06_unresolved.md", corpus) == ["unresolved_dependency"]


def test_two_plan_cycle_refused_with_path(corpus) -> None:
    sources, known_ids, graph = corpus
    cycle_a = next(s for s in sources if s.relative_path.endswith("07_cycle_a.md"))
    errors = validate_plan_dependencies([cycle_a], known_ids, repo_project_id="alpha", graph=graph)
    assert [error.code for error in errors] == ["dependency_cycle"]
    assert errors[0].message == "dependency cycle: alpha#7 -> alpha#8 -> alpha#7"


def test_check_cycles_returns_first_cycle_and_none_for_dag() -> None:
    assert check_cycles({"a": ["b"], "b": ["a"]}) == ["a", "b", "a"]
    assert check_cycles({"a": ["a"]}) == ["a", "a"]
    assert check_cycles({"a": ["b"], "b": ["c"], "c": []}) is None
    # A cycle elsewhere is not attributed to a node outside it.
    assert check_cycles({"x": ["a"], "a": ["b"], "b": ["a"]}, through=["x"]) is None


def test_closed_unconverted_plan_is_exempt(corpus) -> None:
    assert _codes_for("09_closed_unconverted.md", corpus) == []


def test_plan_without_status_refused(corpus) -> None:
    assert _codes_for("10_no_status.md", corpus) == ["missing_status"]


def test_plan_id_for_another_project_refused(corpus) -> None:
    assert _codes_for("11_wrong_plan_id.md", corpus) == ["plan_id_mismatch"]


def test_unconverted_open_plan_refused(corpus) -> None:
    assert _codes_for("12_unconverted_open.md", corpus) == ["missing_plan_id", "missing_dependencies"]


# --- CLI and hook, through real git repositories ---------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Create a registered git repo `alpha` (valid plans only) plus `beta`, and a graph."""
    alpha = tmp_path / "alpha"
    plans = alpha / "docs" / "plans"
    plans.mkdir(parents=True)
    for name in ("01_valid.md", "02_reviewed_none.md", "12_unconverted_open.md"):
        shutil.copy(FIXTURES / "alpha" / "docs" / "plans" / name, plans / name)
    shutil.copytree(FIXTURES / "beta", tmp_path / "beta")
    _git(alpha, "init", "-q")
    _git(alpha, "-c", "user.name=t", "-c", "user.email=t@example.com", "add", ".")
    _git(alpha, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--no-verify", "-m", "seed")
    graph = tmp_path / "PROJECT_GRAPH.json"
    graph.write_text(
        json.dumps(
            [
                {"id": "alpha", "path": str(alpha), "status": "active"},
                {"id": "beta_tools", "path": str(tmp_path / "beta"), "status": "active"},
            ]
        ),
        encoding="utf-8",
    )
    return alpha, graph


def _status_only_edit(alpha: Path) -> None:
    plan = alpha / "docs" / "plans" / "12_unconverted_open.md"
    plan.write_text(plan.read_text(encoding="utf-8").replace("**Status:** Planned", "**Status:** In Progress"))
    _git(alpha, "add", "docs/plans/12_unconverted_open.md")


def test_staged_cli_refuses_status_only_edit_to_unconverted_plan(tmp_path: Path) -> None:
    alpha, graph = _workspace(tmp_path)
    _status_only_edit(alpha)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(alpha), "--staged", "--project-graph", str(graph)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "[missing_plan_id]" in result.stdout


def test_staged_cli_passes_valid_staged_plan_and_reads_index_not_worktree(tmp_path: Path) -> None:
    alpha, graph = _workspace(tmp_path)
    plan = alpha / "docs" / "plans" / "01_valid.md"
    plan.write_text(plan.read_text(encoding="utf-8").replace("In Progress", "Planned"))
    _git(alpha, "add", "docs/plans/01_valid.md")
    # An unstaged break must not affect the staged verdict.
    plan.write_text(plan.read_text(encoding="utf-8").replace('plan_id: "alpha#1"\n', ""))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(alpha), "--staged", "--project-graph", str(graph)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_pre_commit_hook_runs_validator_on_status_only_plan_change(tmp_path: Path) -> None:
    """The installed hook shape invokes the real validator and refuses in block mode."""
    alpha, graph = _workspace(tmp_path)
    (alpha / "hooks").mkdir()
    hook = alpha / "hooks" / "pre-commit"
    hook.write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8")
    (alpha / "scripts" / "meta").mkdir(parents=True)
    shutil.copy(SCRIPT, alpha / "scripts" / "meta" / "validate_plan_dependencies.py")
    (alpha / "enforced_planning").symlink_to(REPO_ROOT / "enforced_planning")
    _status_only_edit(alpha)
    env = {
        **os.environ,
        "ALLOW_CANONICAL_CHECKOUT_COMMIT": "1",
        "ENFORCED_PLANNING_HOOK_MODE": "block",
        "PROJECT_GRAPH_PATH": str(graph),
        "PYTHON_BIN": sys.executable,
    }
    result = subprocess.run(["bash", str(hook)], cwd=alpha, env=env, capture_output=True, text=True, check=False)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "Checking plan dependency contract..." in result.stdout
    assert "[missing_plan_id]" in result.stdout


def test_corpus_report_counts_open_converted_and_errors(tmp_path: Path) -> None:
    _, graph = _workspace(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--corpus", "--project-graph", str(graph), "--active-within-days", "0"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    repos = {repo["project_id"]: repo for repo in report["repos"]}
    assert repos["alpha"]["open_plans"] == 3
    assert repos["alpha"]["converted_open_plans"] == 2
    assert repos["alpha"]["errors_by_type"] == {"missing_dependencies": 1, "missing_plan_id": 1}
    assert repos["beta_tools"]["errors_by_type"] == {"missing_dependencies": 1, "missing_plan_id": 1}
