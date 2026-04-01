#!/usr/bin/env python3
"""Self-test for the meta-process framework.

Verifies internal consistency:
1. File existence - all files referenced by install.sh actually exist
2. Link checker - all markdown cross-references resolve
3. Install test - install to temp dir, make a commit, verify hooks work

Usage:
    python meta-process/scripts/self_test.py              # All checks
    python meta-process/scripts/self_test.py --files       # File existence only
    python meta-process/scripts/self_test.py --links       # Link checker only
    python meta-process/scripts/self_test.py --install     # Install test only
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse


def find_framework_root() -> Path:
    """Find meta-process/ directory relative to this script or CWD."""
    # If running from within meta-process/scripts/
    script_dir = Path(__file__).resolve().parent
    if script_dir.name == "scripts" and (script_dir.parent / "install.sh").exists():
        return script_dir.parent

    # If running from repo root
    cwd = Path.cwd()
    if (cwd / "meta-process" / "install.sh").exists():
        return cwd / "meta-process"

    print("ERROR: Cannot find meta-process/ directory")
    sys.exit(2)


# --- Check 1: File Existence ---


def check_file_existence(root: Path) -> list[str]:
    """Verify all files referenced by install.sh exist."""
    errors: list[str] = []

    # Core scripts (from install.sh CORE_SCRIPTS array)
    core_scripts = [
        "check_plan_tests.py",
        "check_plan_blockers.py",
        "check_dead_code.py",
        "complete_plan.py",
        "parse_plan.py",
        "sync_plan_status.py",
        "merge_pr.py",
        "pr_auto.py",
        "generate_quiz.py",
    ]
    for s in core_scripts:
        if not (root / "scripts" / s).exists():
            errors.append(f"Missing core script: scripts/{s}")

    # Full mode scripts
    full_scripts = [
        "check_doc_coupling.py",
        "sync_governance.py",
        "check_mock_usage.py",
        "check_locked_files.py",
    ]
    for s in full_scripts:
        if not (root / "scripts" / s).exists():
            errors.append(f"Missing full-mode script: scripts/{s}")

    # Worktree coordination scripts
    wt_scripts = [
        "check_claims.py",
        "safe_worktree_remove.py",
        "finish_pr.py",
        "meta_status.py",
        "check_messages.py",
        "send_message.py",
    ]
    for s in wt_scripts:
        if not (root / "scripts" / "worktree-coordination" / s).exists():
            errors.append(
                f"Missing worktree script: scripts/worktree-coordination/{s}"
            )

    # Git hooks
    for hook in ["pre-commit", "commit-msg", "post-commit"]:
        if not (root / "hooks" / "git" / hook).exists():
            errors.append(f"Missing git hook: hooks/git/{hook}")

    # Core Claude hooks
    core_hooks = [
        "protect-main.sh",
        "check-hook-enabled.sh",
        "check-references-reviewed.sh",
        "track-reads.sh",
        "gate-edit.sh",
        "post-edit-quiz.sh",
    ]
    for h in core_hooks:
        if not (root / "hooks" / "claude" / h).exists():
            errors.append(f"Missing core Claude hook: hooks/claude/{h}")

    # Worktree coordination Claude hooks
    wt_hooks = [
        "protect-main.sh",
        "block-cd-worktree.sh",
        "block-worktree-remove.sh",
        "check-cwd-valid.sh",
        "warn-worktree-cwd.sh",
        "check-file-scope.sh",
        "enforce-make-merge.sh",
        "check-inbox.sh",
        "notify-inbox-startup.sh",
    ]
    for h in wt_hooks:
        p = root / "hooks" / "claude" / "worktree-coordination" / h
        if not p.exists():
            errors.append(
                f"Missing worktree Claude hook: hooks/claude/worktree-coordination/{h}"
            )

    # Templates
    templates = [
        "meta-process.yaml.example",
        "plan.md.template",
        "plans-index.md.template",
        "issues.md.template",
        "Makefile.meta",
        "CLAUDE.md.root",
        "CLAUDE.md.scripts",
        "CLAUDE.md.tests",
        "CLAUDE.md.docs-adr",
        "doc_coupling.yaml.example",
        "acceptance_gate.yaml.example",
    ]
    for t in templates:
        if not (root / "templates" / t).exists():
            errors.append(f"Missing template: templates/{t}")

    # Key documentation files
    for doc in ["README.md", "GETTING_STARTED.md", "CLAUDE.md", "ISSUES.md"]:
        if not (root / doc).exists():
            errors.append(f"Missing documentation: {doc}")

    # Pattern index
    if not (root / "patterns" / "01_README.md").exists():
        errors.append("Missing pattern index: patterns/01_README.md")

    return errors


# --- Check 2: Markdown Link Checker ---

# Match [text](path) but not [text](https://...) or [text](http://...)
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
# Match fenced code blocks (``` ... ```)
CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


def _in_code_block(content: str, pos: int) -> bool:
    """Check if position is inside a fenced code block."""
    for block in CODE_BLOCK_RE.finditer(content):
        if block.start() <= pos < block.end():
            return True
    return False


def check_markdown_links(root: Path) -> list[str]:
    """Verify all relative markdown links resolve to existing files."""
    errors: list[str] = []

    for md_file in root.rglob("*.md"):
        content = md_file.read_text(errors="replace")
        rel_path = md_file.relative_to(root)

        for match in LINK_RE.finditer(content):
            link_text = match.group(1)
            link_target = match.group(2)

            # Skip external URLs
            parsed = urlparse(link_target)
            if parsed.scheme in ("http", "https", "mailto"):
                continue

            # Skip anchor-only links
            if link_target.startswith("#"):
                continue

            # Skip links inside code blocks (examples, not real refs)
            if _in_code_block(content, match.start()):
                continue

            # Strip anchor from path
            target_path = link_target.split("#")[0]
            if not target_path:
                continue

            # Skip links that resolve outside the framework (to parent repo)
            resolved = (md_file.parent / target_path).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                # Link goes outside meta-process/ — can't validate
                continue

            if not resolved.exists():
                line_num = content[: match.start()].count("\n") + 1
                errors.append(
                    f"{rel_path}:{line_num}: broken link [{link_text}]({link_target})"
                )

    return errors


# --- Check 3: Install Test ---


def check_install(root: Path) -> list[str]:
    """Install to temp dir, make a commit, verify hooks work."""
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="meta-process-test-") as tmpdir:
        tmp = Path(tmpdir)
        project = tmp / "test-project"
        project.mkdir()

        # Initialize git repo
        _run(["git", "init", str(project)])
        _run(["git", "-C", str(project), "config", "user.email", "test@test.com"])
        _run(["git", "-C", str(project), "config", "user.name", "Test"])

        # Create initial commit so we have a branch
        readme = project / "README.md"
        readme.write_text("# Test Project\n")
        _run(["git", "-C", str(project), "add", "README.md"])
        _run(
            [
                "git",
                "-C",
                str(project),
                "commit",
                "--no-verify",
                "-m",
                "Initial commit",
            ]
        )

        # Run minimal install
        install_script = str(root / "install.sh")
        result = subprocess.run(
            ["bash", install_script, str(project), "--minimal"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            errors.append(f"install.sh --minimal failed:\n{result.stderr}")
            return errors

        # Verify expected files exist
        expected_files = [
            "meta-process.yaml",
            "hooks/pre-commit",
            "hooks/commit-msg",
            "hooks/post-commit",
            "docs/plans/TEMPLATE.md",
            "docs/plans/CLAUDE.md",
            "CLAUDE.md",
            "ISSUES.md",
            "scripts/meta/parse_plan.py",
            ".claude/settings.json",
            ".claude/hooks/track-reads.sh",
            ".claude/hooks/gate-edit.sh",
            ".claude/hooks/post-edit-quiz.sh",
        ]
        for f in expected_files:
            if not (project / f).exists():
                errors.append(f"Minimal install missing: {f}")

        # Verify git hooks path is set
        result = subprocess.run(
            ["git", "-C", str(project), "config", "core.hooksPath"],
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() != "hooks":
            errors.append(
                f"Git hooks path not set correctly: '{result.stdout.strip()}'"
            )

        # Test 1: Good commit message should succeed
        test_file = project / "test.txt"
        test_file.write_text("hello\n")
        _run(["git", "-C", str(project), "add", "test.txt"])
        result = subprocess.run(
            ["git", "-C", str(project), "commit", "-m", "[Trivial] Test commit"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            errors.append(
                f"Good commit blocked by hooks:\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )

        # Test 2: Bad commit message should be rejected
        test_file.write_text("hello again\n")
        _run(["git", "-C", str(project), "add", "test.txt"])
        result = subprocess.run(
            ["git", "-C", str(project), "commit", "-m", "bad message no prefix"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            errors.append("Bad commit message was NOT rejected by commit-msg hook")

        # Test 3: Full install
        project2 = tmp / "test-project-full"
        project2.mkdir()
        _run(["git", "init", str(project2)])
        _run(["git", "-C", str(project2), "config", "user.email", "test@test.com"])
        _run(["git", "-C", str(project2), "config", "user.name", "Test"])
        readme2 = project2 / "README.md"
        readme2.write_text("# Test\n")
        _run(["git", "-C", str(project2), "add", "README.md"])
        _run(
            [
                "git",
                "-C",
                str(project2),
                "commit",
                "--no-verify",
                "-m",
                "Initial",
            ]
        )

        result = subprocess.run(
            ["bash", install_script, str(project2), "--full"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            errors.append(f"install.sh --full failed:\n{result.stderr}")
            return errors

        full_expected = [
            "acceptance_gates/EXAMPLE.yaml",
            "scripts/relationships.yaml",
            ".claude/hooks/protect-main.sh",
            ".claude/hooks/check-references-reviewed.sh",
            ".claude/hooks/worktree-coordination/block-cd-worktree.sh",
            "scripts/meta/check_doc_coupling.py",
            "scripts/meta/worktree-coordination/check_claims.py",
            "docs/meta-patterns/01_README.md",
            "docs/meta-patterns/worktree-coordination/18_claim-system.md",
            "docs/adr/CLAUDE.md",
        ]
        for f in full_expected:
            if not (project2 / f).exists():
                errors.append(f"Full install missing: {f}")

    return errors


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a command, raising on failure."""
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


# --- Main ---


def main() -> None:
    """Parse CLI flags and run selected self-test checks."""
    parser = argparse.ArgumentParser(description="Meta-process framework self-test")
    parser.add_argument("--files", action="store_true", help="File existence check only")
    parser.add_argument("--links", action="store_true", help="Link checker only")
    parser.add_argument("--install", action="store_true", help="Install test only")
    args = parser.parse_args()

    # If no flags, run all
    run_all = not (args.files or args.links or args.install)

    root = find_framework_root()
    print(f"Framework root: {root}")
    print()

    all_errors: list[str] = []

    if run_all or args.files:
        print("=== File Existence Check ===")
        errors = check_file_existence(root)
        _report(errors)
        all_errors.extend(errors)

    if run_all or args.links:
        print("=== Markdown Link Check ===")
        errors = check_markdown_links(root)
        _report(errors)
        all_errors.extend(errors)

    if run_all or args.install:
        print("=== Install Test ===")
        errors = check_install(root)
        _report(errors)
        all_errors.extend(errors)

    print()
    if all_errors:
        print(f"FAILED: {len(all_errors)} error(s)")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")


def _report(errors: list[str]) -> None:
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
    else:
        print("  OK")
    print()


if __name__ == "__main__":
    main()
