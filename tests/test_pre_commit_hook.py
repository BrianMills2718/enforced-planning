"""Tests for the tracked pre-commit hook wiring."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

PROJECT_META_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = PROJECT_META_ROOT / "hooks" / "git" / "pre-commit"


def test_source_repo_ignores_ephemeral_doc_coupling_ack_file() -> None:
    """The source repository must not make its one-commit scratch file trackable by default."""

    ignore_entries = (PROJECT_META_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".doc-coupling-acks" in ignore_entries


def _hook_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create the minimum repository needed to execute the tracked hook."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
    hooks_dir = repo_root / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_copy = hooks_dir / "pre-commit"
    hook_copy.write_text(HOOK_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    hook_copy.chmod(0o755)
    return repo_root, hook_copy


def _hook_env(**overrides: str) -> dict[str, str]:
    """Run hook-unit fixtures through their intentionally canonical test repositories."""

    return {**os.environ, "ALLOW_CANONICAL_CHECKOUT_COMMIT": "1", **overrides}


def test_pre_commit_hook_invokes_doc_coupling_in_staged_mode(tmp_path: Path) -> None:
    """The hook should inspect the staged slice, not the whole branch history."""

    repo_root, hook_copy = _hook_repo(tmp_path)
    scripts_meta = repo_root / "scripts" / "meta"
    scripts_meta.mkdir(parents=True, exist_ok=True)
    marker = repo_root / "doc_coupling_args.txt"
    stub = scripts_meta / "check_doc_coupling.py"
    stub.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            from pathlib import Path
            import sys

            marker = Path({str(marker)!r})
            marker.write_text(" ".join(sys.argv[1:]), encoding="utf-8")
            sys.exit(0 if "--staged" in sys.argv else 1)
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(hook_copy)],
        cwd=repo_root,
        env=_hook_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert marker.read_text(encoding="utf-8") == "--staged --strict"


def test_pre_commit_hook_passes_ephemeral_doc_coupling_ack_file(tmp_path: Path) -> None:
    """A justified acknowledgement should reach the portable checker."""

    repo_root, hook_copy = _hook_repo(tmp_path)
    scripts_meta = repo_root / "scripts" / "meta"
    scripts_meta.mkdir(parents=True, exist_ok=True)
    marker = repo_root / "doc_coupling_args.txt"
    ack_file = repo_root / ".doc-coupling-acks"
    ack_file.write_text("- path: README.md\n  reason: Unchanged public contract.\n", encoding="utf-8")
    stub = scripts_meta / "check_doc_coupling.py"
    stub.write_text(
        textwrap.dedent(
            f"""\
            from pathlib import Path
            import sys

            Path({str(marker)!r}).write_text(" ".join(sys.argv[1:]), encoding="utf-8")
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(hook_copy)],
        cwd=repo_root,
        env=_hook_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert marker.read_text(encoding="utf-8") == f"--staged --strict --ack-file {ack_file}"


def test_pre_commit_hook_rejects_tracked_doc_coupling_ack_file(tmp_path: Path) -> None:
    """A consumed acknowledgement must not become part of the commit tree."""

    repo_root, hook_copy = _hook_repo(tmp_path)
    ack_file = repo_root / ".doc-coupling-acks"
    ack_file.write_text("- path: README.md\n  reason: Unchanged public contract.\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".doc-coupling-acks"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    result = subprocess.run(
        ["bash", str(hook_copy)],
        cwd=repo_root,
        env=_hook_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert ".doc-coupling-acks is ephemeral but is tracked" in result.stdout


def test_post_commit_hook_removes_ephemeral_doc_coupling_ack_file(tmp_path: Path) -> None:
    """A one-commit acknowledgement must not leak into the next commit."""

    repo_root, _ = _hook_repo(tmp_path)
    ack_file = repo_root / ".doc-coupling-acks"
    ack_file.write_text("- path: README.md\n  reason: Unchanged public contract.\n", encoding="utf-8")
    hook = PROJECT_META_ROOT / "hooks" / "git" / "post-commit"

    result = subprocess.run(
        ["bash", str(hook)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert not ack_file.exists()


def test_pre_commit_hook_warns_by_default_on_governance_failure(tmp_path: Path) -> None:
    """Reversible development commits should retain findings without blocking."""

    repo_root, hook_copy = _hook_repo(tmp_path)
    scripts_meta = repo_root / "scripts" / "meta"
    scripts_meta.mkdir(parents=True, exist_ok=True)
    stub = scripts_meta / "check_doc_coupling.py"
    stub.write_text("raise SystemExit(1)\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(hook_copy)],
        cwd=repo_root,
        env=_hook_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "commit continues in warn mode" in result.stdout


def test_pre_commit_hook_blocks_when_explicitly_requested(tmp_path: Path) -> None:
    """Pilot and release candidates can opt into strict blocking."""

    repo_root, hook_copy = _hook_repo(tmp_path)
    scripts_meta = repo_root / "scripts" / "meta"
    scripts_meta.mkdir(parents=True, exist_ok=True)
    stub = scripts_meta / "check_doc_coupling.py"
    stub.write_text("raise SystemExit(1)\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(hook_copy)],
        cwd=repo_root,
        env=_hook_env(ENFORCED_PLANNING_HOOK_MODE="block"),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "failed in explicit block mode" in result.stdout


def test_pre_commit_hook_rejects_unknown_mode(tmp_path: Path) -> None:
    """A misspelled enforcement mode must not silently select a behavior."""

    repo_root, hook_copy = _hook_repo(tmp_path)
    result = subprocess.run(
        ["bash", str(hook_copy)],
        cwd=repo_root,
        env=_hook_env(ENFORCED_PLANNING_HOOK_MODE="strictest"),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "must be off, warn, or block" in result.stdout


def test_pre_commit_hook_does_not_generate_or_stage_plan_index(tmp_path: Path) -> None:
    """A check hook must not mutate or stage generated planning state."""

    repo_root, hook_copy = _hook_repo(tmp_path)
    scripts_meta = repo_root / "scripts" / "meta"
    scripts_meta.mkdir(parents=True, exist_ok=True)
    marker = repo_root / "generator-called.txt"
    generator = scripts_meta / "generate_plan_index.py"
    generator.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('called')\n",
        encoding="utf-8",
    )
    plan = repo_root / "docs" / "plans" / "01_example.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")
    subprocess.run(["git", "add", str(plan)], cwd=repo_root, check=True)

    result = subprocess.run(
        ["bash", str(hook_copy)],
        cwd=repo_root,
        env=_hook_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert not marker.exists()
    assert "git fetch" not in HOOK_SCRIPT.read_text(encoding="utf-8")


def test_pre_commit_hook_blocks_mutation_of_frozen_verification_batch(tmp_path: Path) -> None:
    """A failing exact-batch check must stop a new commit before other gates run."""

    repo_root, hook_copy = _hook_repo(tmp_path)
    scripts_meta = repo_root / "scripts" / "meta"
    scripts_meta.mkdir(parents=True, exist_ok=True)
    marker = repo_root / "verification_batch_called.txt"
    stub = scripts_meta / "verification_batch.py"
    stub.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            from pathlib import Path
            import sys

            Path({str(marker)!r}).write_text(" ".join(sys.argv[1:]), encoding="utf-8")
            print("ERROR: verification batch invalid", file=sys.stderr)
            raise SystemExit(1)
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(hook_copy)],
        cwd=repo_root,
        env=_hook_env(ENFORCED_PLANNING_HOOK_MODE="off"),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert marker.read_text(encoding="utf-8") == f"--repo-root {repo_root} check"
    assert "frozen for exact terminal verification" in result.stdout


def test_every_variable_the_hook_dereferences_is_defined() -> None:
    """An undefined variable in a command position makes a check silently not run.

    `$PYTHON` was used in three command positions and assigned nowhere. Under
    `set -e` without `set -u` it expands to the empty string, bash reports
    "command not found", the surrounding `if !` reads that as the check failing,
    and in this repository's default warn mode it prints a warning and continues.
    So the topic-tag gate had never executed once -- it had only ever failed to
    start, which looks the same from outside as a check that ran and found
    nothing worth blocking.

    This asserts the class rather than the instance: every variable the template
    dereferences must be assigned in the template, carry a `${VAR:-default}`, or
    be a declared environment input.
    """

    import re

    source = HOOK_SCRIPT.read_text(encoding="utf-8")

    # Environment inputs the hook is entitled to read without assigning.
    environment_inputs = {
        "PYTHON_BIN",
        "ENFORCED_PLANNING_HOOK_MODE",
        "HOME",
        "PATH",
        "PWD",
        "USER",
        "BASH_SOURCE",
        "PIPESTATUS",
        "FUNCNAME",
        "IFS",
    }

    assigned = set(re.findall(r"^\s*(?:local\s+|export\s+)?([A-Z_][A-Z0-9_]*)=", source, re.MULTILINE))
    assigned |= set(re.findall(r"^\s*for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b", source, re.MULTILINE))
    assigned |= set(re.findall(r"([A-Z_][A-Z0-9_]*)\+=\(", source))
    # `${VAR:-...}` and `${VAR+...}` supply their own value.
    defaulted = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)(?::-|:\+|\+|-)", source))

    used = set(re.findall(r'"\$([A-Z_][A-Z0-9_]*)"', source))
    used |= set(re.findall(r'\$\{([A-Z_][A-Z0-9_]*)\[', source))

    undefined = sorted(used - assigned - defaulted - environment_inputs)
    assert not undefined, (
        f"the hook dereferences variables nothing assigns: {undefined}. "
        "In a command position that makes the check fail to start, which this "
        "repository's warn mode reports the same way as a check that ran."
    )
