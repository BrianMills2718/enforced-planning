"""Tests for the tracked pre-commit hook wiring."""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path


PROJECT_META_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = PROJECT_META_ROOT / "hooks" / "git" / "pre-commit"


def test_pre_commit_hook_invokes_doc_coupling_in_staged_mode(tmp_path: Path) -> None:
    """The hook should gate the staged slice, not the whole branch history."""

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
    (repo_root / ".git").mkdir(exist_ok=True)

    hooks_dir = repo_root / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_copy = hooks_dir / "pre-commit"
    hook_copy.write_text(HOOK_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    hook_copy.chmod(0o755)

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


def test_pre_commit_hook_blocks_mutation_of_frozen_verification_batch(tmp_path: Path) -> None:
    """A failing exact-batch check must stop a new commit before other gates run."""

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
    hooks_dir = repo_root / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_copy = hooks_dir / "pre-commit"
    hook_copy.write_text(HOOK_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    hook_copy.chmod(0o755)

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
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert marker.read_text(encoding="utf-8") == f"--repo-root {repo_root} check"
    assert "frozen for exact terminal verification" in result.stdout
