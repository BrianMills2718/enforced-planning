#!/usr/bin/env python3
"""Self-test for the enforced-planning framework.

Verifies internal consistency:
1. File existence - referenced framework files exist
2. Link checker - markdown cross-references resolve
3. Install test - canonical installer bootstraps a governed repo cleanly

Usage:
    python enforced-planning/scripts/self_test.py              # All checks
    python enforced-planning/scripts/self_test.py --files      # File existence only
    python enforced-planning/scripts/self_test.py --links      # Link checker only
    python enforced-planning/scripts/self_test.py --install    # Install test only
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
    """Find the enforced-planning repo root relative to this script or CWD."""
    # If running from within enforced-planning/scripts/
    script_dir = Path(__file__).resolve().parent
    if script_dir.name == "scripts" and (script_dir.parent / "install.sh").exists():
        return script_dir.parent

    # If running from repo root
    cwd = Path.cwd()
    if (cwd / "install.sh").exists() and (cwd / "scripts").is_dir():
        return cwd

    print("ERROR: Cannot find enforced-planning repo root")
    sys.exit(2)


# --- Check 1: File Existence ---


def check_file_existence(root: Path) -> list[str]:
    """Verify the key framework files referenced by install flows exist."""
    errors: list[str] = []

    # Core scripts from the legacy shell bootstrap and source repo
    core_scripts = [
        "install_governed_repo.py",
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
        "relationships.yaml.example",
        "truth_surface_drift.yaml.example",
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
# Match inline code spans (`...`)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def _in_code_block(content: str, pos: int) -> bool:
    """Check if position is inside a fenced code block or inline code span."""
    for block in CODE_BLOCK_RE.finditer(content):
        if block.start() <= pos < block.end():
            return True
    for span in INLINE_CODE_RE.finditer(content):
        if span.start() <= pos < span.end():
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
                # Link goes outside enforced-planning/ — can't validate
                continue

            if not resolved.exists():
                line_num = content[: match.start()].count("\n") + 1
                errors.append(
                    f"{rel_path}:{line_num}: broken link [{link_text}]({link_target})"
                )

    return errors


# --- Check 3: Install Test ---


def check_install(root: Path) -> list[str]:
    """Install to temp dirs and verify the canonical installer contract."""
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="meta-process-test-") as tmpdir:
        tmp = Path(tmpdir)
        project = tmp / "test-project"
        project.mkdir()

        # Initialize git repo
        _run(["git", "init", str(project)])
        canonical_claude = project / "CLAUDE.md"
        canonical_claude.write_text(
            "# Test Project\n\n"
            "## Commands\n\n"
            "```bash\npytest -q\n```\n\n"
            "## Principles\n\n"
            "1. Fail loud.\n\n"
            "## Workflow\n\n"
            "1. Read governance first.\n\n"
            "## References\n\n"
            "- `CLAUDE.md` - canonical governance\n",
            encoding="utf-8",
        )

        install_script = str(root / "install.sh")
        canonical_installer = str(root / "scripts" / "install_governed_repo.py")
        result = subprocess.run(
            [
                sys.executable,
                canonical_installer,
                "--repo-root",
                str(project),
                "--write",
                "--strict-governed",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            errors.append(
                "canonical install_governed_repo.py failed:\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
            return errors

        # Verify expected files exist
        expected_files = [
            "AGENTS.md",
            "meta-process.yaml",
            "scripts/relationships.yaml",
            "docs/plans/TEMPLATE.md",
            "docs/plans/CLAUDE.md",
            "CLAUDE.md",
            "Makefile",
            "scripts/meta/check_agents_sync.py",
            "scripts/meta/check_doc_coupling.py",
            "scripts/meta/file_context.py",
            "scripts/meta/render_agents_md.py",
            "scripts/meta/sync_plan_status.py",
            "scripts/meta/validate_plan.py",
            ".claude/settings.json",
            ".claude/hooks/track-reads.sh",
            ".claude/hooks/gate-edit.sh",
        ]
        for f in expected_files:
            if not (project / f).exists():
                errors.append(f"Canonical install missing: {f}")

        sync_result = subprocess.run(
            [
                sys.executable,
                str(project / "scripts" / "meta" / "check_agents_sync.py"),
                "--repo-root",
                str(project),
                "--check",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if sync_result.returncode != 0:
            errors.append(
                "check_agents_sync.py failed after canonical install:\n"
                f"stdout: {sync_result.stdout}\n"
                f"stderr: {sync_result.stderr}"
            )

        file_context_result = subprocess.run(
            [
                sys.executable,
                str(project / "scripts" / "meta" / "file_context.py"),
                "--json",
                "CLAUDE.md",
            ],
            cwd=str(project),
            capture_output=True,
            text=True,
            check=False,
        )
        if file_context_result.returncode != 0:
            errors.append(
                "file_context.py failed after canonical install:\n"
                f"stdout: {file_context_result.stdout}\n"
                f"stderr: {file_context_result.stderr}"
            )

        # Verify the shell wrapper delegates to the canonical installer.
        project_wrapper = tmp / "test-project-wrapper"
        project_wrapper.mkdir()
        _run(["git", "init", str(project_wrapper)])
        (project_wrapper / "CLAUDE.md").write_text(
            canonical_claude.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        wrapper_result = subprocess.run(
            ["bash", install_script, str(project_wrapper)],
            capture_output=True,
            text=True,
            check=False,
        )
        if wrapper_result.returncode != 0:
            errors.append(
                "install.sh default wrapper failed:\n"
                f"stdout: {wrapper_result.stdout}\n"
                f"stderr: {wrapper_result.stderr}"
            )
        elif "Delegating to canonical Python installer" not in wrapper_result.stdout:
            errors.append("install.sh default path did not announce canonical delegation")

        # Legacy full bootstrap remains supported as a compatibility surface.
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

        legacy_result = subprocess.run(
            ["bash", install_script, str(project2), "--full"],
            capture_output=True,
            text=True,
        )
        if legacy_result.returncode != 0:
            errors.append(
                "install.sh --full failed:\n"
                f"stdout: {legacy_result.stdout}\n"
                f"stderr: {legacy_result.stderr}"
            )
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
    parser = argparse.ArgumentParser(description="Enforced-planning framework self-test")
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
