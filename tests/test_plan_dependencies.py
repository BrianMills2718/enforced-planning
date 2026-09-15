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
    CLOSED_STATUS_WORDS,
    PlanFile,
    build_dependency_graph,
    build_known_ids,
    check_cycles,
    is_plan_path,
    iter_plan_paths,
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


# --- open-plan detection: status forms, non-plan files, duplicate ids -----------

CONVERTED_NONE = '---\nplan_id: "{pid}"\ndependencies: []\ndependencies_reviewed: "2026-09-15"\n---\n'


def _plan(body: str, relative_path: str = "docs/plans/20_example.md", project_id: str = "alpha") -> PlanFile:
    return PlanFile(project_id, relative_path, body)


STATUS_FORMS = [
    "**Status:** {s}\n",
    "## Status: {s}\n",
    "> Status: {s}\n",
    "> **Status:** {s}\n",
    "* **Status:** {s}\n",
    "- **Status:** {s}\n",
    "Status: {s}\n",
]


@pytest.mark.parametrize("form", STATUS_FORMS)
@pytest.mark.parametrize(
    ("status", "expected_open"),
    [
        ("Complete", False),
        ("✅ COMPLETED (2026-09-01)", False),
        ("🟢 shipped in PR #12", False),
        ("Superseded by Plan #30", False),
        ("In Progress", True),
        ("Planned", True),
        ("🚧 Current", True),
        ("Partially complete", True),
    ],
)
def test_status_forms_classify_open_and_closed(form: str, status: str, expected_open: bool) -> None:
    body = "# Plan #20: Example\n\n" + form.format(s=status) + "\n## Gap\n"
    parsed = parse_plan(_plan(body))
    assert parsed is not None
    assert parsed.status is not None, form
    assert parsed.is_open is expected_open, (form, status)


@pytest.mark.parametrize(("status", "expected_open"), [("done", False), ("Abandoned", False), ("active", True)])
def test_yaml_frontmatter_status_classifies(status: str, expected_open: bool) -> None:
    body = f"---\nstatus: {status}\n---\n# Plan #20: Example\n\n## Gap\n"
    parsed = parse_plan(_plan(body))
    assert parsed is not None and parsed.status == status and parsed.is_open is expected_open


def test_every_closed_word_closes_a_plan() -> None:
    assert {"implemented", "executed", "built", "merged", "dormant", "closed"} <= CLOSED_STATUS_WORDS
    for word in sorted(CLOSED_STATUS_WORDS):
        parsed = parse_plan(_plan(f"# Plan #20: Example\n\n**Status:** {word.title()}\n"))
        assert parsed is not None and parsed.is_open is False, word


def test_closed_plan_in_heading_form_is_exempt_from_contract() -> None:
    source = _plan("# Plan #20: Example\n\n## Status: Complete\n\n## Gap\n")
    assert validate_plan_dependencies([source], {}, repo_project_id="alpha") == []


def test_step_status_below_header_does_not_override_plan_status() -> None:
    body = "# Plan #20: Example\n\n**Status:** Complete\n\n## Steps\n\n- **Status:** In Progress\n"
    parsed = parse_plan(_plan(body))
    assert parsed is not None and parsed.is_open is False


def test_status_added_over_existing_closed_status_conflicts() -> None:
    """A conversion that adds 'In Progress' above a real '## Status: Complete' is refused."""
    body = CONVERTED_NONE.format(pid="alpha#20") + "# Plan #20: Example\n\n**Status:** In Progress\n## Status: Complete\n"
    source = _plan(body)
    parsed = parse_plan(source)
    assert parsed is not None and parsed.is_open is True
    errors = validate_plan_dependencies([source], build_known_ids([parsed]), repo_project_id="alpha")
    assert [e.code for e in errors] == ["conflicting_status"]


@pytest.mark.parametrize(
    "relative_path",
    [
        "docs/plans/INDEX.md",
        "docs/plans/CLAUDE.md",
        "docs/plans/AGENTS.md",
        "docs/plans/README.md",
        "docs/plans/TEMPLATE.md",
        "docs/plans/TEMPLATE_batch.md",
        "docs/plans/_01_draft.md",
        "docs/plans/ROADMAP.md",
        "docs/plans/COMPLETION_LOG.md",
        "claude_code_planning/ADR-001-choice.md",
        "docs/plans/goals/30_goal.md",
        "docs/plans/progress/30_progress.md",
    ],
)
def test_non_plan_files_are_ignored(relative_path: str) -> None:
    assert is_plan_path(relative_path) is False
    assert parse_plan(_plan("# Plan #30: Looks like a plan\n\n**Status:** Planned\n", relative_path)) is None


def test_plan_discovery_skips_non_plan_files(tmp_path: Path) -> None:
    plans = tmp_path / "docs" / "plans"
    (plans / "goals").mkdir(parents=True)
    for name in ("INDEX.md", "README.md", "TEMPLATE_plan.md", "_scratch.md", "ROADMAP.md", "goals/05_goal.md"):
        (plans / name).write_text("# Plan #5: not a plan\n\n**Status:** Planned\n", encoding="utf-8")
    for name in ("05_real.md", "0.3-tier.md", "2026-08-22_dated.md"):
        (plans / name).write_text("# Real\n\n**Status:** Planned\n", encoding="utf-8")
    found = sorted(path.name for path in iter_plan_paths(tmp_path))
    assert found == ["0.3-tier.md", "05_real.md", "2026-08-22_dated.md"]


def _two_plan_corpus(first_status: str, second_status: str) -> list[PlanFile]:
    return [
        _plan(CONVERTED_NONE.format(pid="alpha#30") + f"# A\n\n**Status:** {first_status}\n", "docs/plans/30_a.md"),
        _plan(f"# B\n\n**Status:** {second_status}\n", "docs/plans/030-b.md"),
    ]


def _known(sources: list[PlanFile]):
    return build_known_ids([plan for plan in (parse_plan(source) for source in sources) if plan is not None])


def test_two_open_plans_with_one_id_are_duplicates_naming_both() -> None:
    sources = _two_plan_corpus("Planned", "In Progress")
    errors = [
        e for e in validate_plan_dependencies(sources, _known(sources), repo_project_id="alpha")
        if e.code == "duplicate_plan_id"
    ]
    assert sorted(e.path for e in errors) == ["docs/plans/030-b.md", "docs/plans/30_a.md"]
    for error in errors:
        assert "docs/plans/30_a.md" in error.message and "docs/plans/030-b.md" in error.message


def test_open_plan_sharing_id_with_closed_plan_is_not_duplicate() -> None:
    sources = _two_plan_corpus("Planned", "Complete")
    assert validate_plan_dependencies(sources, _known(sources), repo_project_id="alpha") == []


def test_dependency_on_ambiguous_id_is_reported() -> None:
    sources = _two_plan_corpus("Planned", "Complete")
    dependent = _plan(
        '---\nplan_id: "alpha#31"\ndependencies: ["alpha#30"]\n'
        'dependency_evidence:\n  "alpha#30": "Blocked By: Plan #30"\n---\n# C\n\n**Status:** Planned\n',
        "docs/plans/31_c.md",
    )
    errors = validate_plan_dependencies([dependent], _known([*sources, dependent]), repo_project_id="alpha")
    assert [e.code for e in errors] == ["ambiguous_dependency"]
    assert "docs/plans/30_a.md" in errors[0].message and "docs/plans/030-b.md" in errors[0].message
