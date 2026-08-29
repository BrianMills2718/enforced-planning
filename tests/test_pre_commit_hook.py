"""Tests for the tracked pre-commit hook wiring."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path


PROJECT_META_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = PROJECT_META_ROOT / "hooks" / "git" / "pre-commit"


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


def _install_effective_profile_runtime(repo_root: Path) -> None:
    """Copy the installed-consumer profile entrypoint and its package owner."""

    package = repo_root / "enforced_planning"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "effective_project_profile.py").write_text(
        (PROJECT_META_ROOT / "enforced_planning" / "effective_project_profile.py").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    scripts_meta = repo_root / "scripts" / "meta"
    scripts_meta.mkdir(parents=True)
    (scripts_meta / "effective_project_profile.py").write_text(
        (PROJECT_META_ROOT / "scripts" / "effective_project_profile.py").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )


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
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert marker.read_text(encoding="utf-8") == f"--staged --strict --ack-file {ack_file}"


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
        env={**os.environ, "ENFORCED_PLANNING_HOOK_MODE": "block"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "failed in explicit block mode" in result.stdout


def test_pre_commit_master_off_skips_blocks_and_reenable_restores_them(
    tmp_path: Path,
) -> None:
    """The native hook must consume the same reversible master profile."""

    repo_root, hook_copy = _hook_repo(tmp_path)
    _install_effective_profile_runtime(repo_root)
    marker = repo_root / "doc-coupling-called"
    (repo_root / "scripts" / "meta" / "check_doc_coupling.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('called')\nraise SystemExit(1)\n",
        encoding="utf-8",
    )
    config_path = repo_root / "meta-process.yaml"
    config_path.write_text(
        "meta_process:\n  governance:\n    enabled: false\n",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "ENFORCED_PLANNING_HOOK_MODE": "block",
        "ALLOW_CANONICAL_CHECKOUT_COMMIT": "1",
        "CANONICAL_CHECKOUT_HATCH_OVERRIDE": "fixture repository",
    }
    disabled = subprocess.run(
        ["bash", str(hook_copy)],
        cwd=repo_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert disabled.returncode == 0
    assert "Governance checks disabled by meta_process.governance.enabled: false" in disabled.stdout
    assert not marker.exists()

    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("enabled: false", "enabled: true"),
        encoding="utf-8",
    )
    restored = subprocess.run(
        ["bash", str(hook_copy)],
        cwd=repo_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert restored.returncode == 1
    assert marker.read_text(encoding="utf-8") == "called"


def test_pre_commit_hook_rejects_unknown_mode(tmp_path: Path) -> None:
    """A misspelled enforcement mode must not silently select a behavior."""

    repo_root, hook_copy = _hook_repo(tmp_path)
    result = subprocess.run(
        ["bash", str(hook_copy)],
        cwd=repo_root,
        env={**os.environ, "ENFORCED_PLANNING_HOOK_MODE": "strictest"},
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
        env={**os.environ, "ENFORCED_PLANNING_HOOK_MODE": "off"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert marker.read_text(encoding="utf-8") == f"--repo-root {repo_root} check"
    assert "frozen for exact terminal verification" in result.stdout
