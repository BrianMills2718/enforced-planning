"""Tests for rename-safe merge helper cleanup behavior."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
MODULE_PATH = SCRIPTS_DIR / "merge_pr.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("merge_pr_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def completed_process(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """Build a CompletedProcess[str] matching the helper contract."""
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_find_existing_script_returns_first_existing(tmp_path: Path) -> None:
    """Helper should prefer the first existing script in priority order."""
    module = _load()
    second = tmp_path / "second.py"
    first = tmp_path / "first.py"
    second.write_text("# second\n", encoding="utf-8")
    first.write_text("# first\n", encoding="utf-8")

    found = module.find_existing_script(  # type: ignore[attr-defined]
        [str(first), str(second)]
    )

    assert found == first


def test_find_existing_script_returns_none_when_missing(tmp_path: Path) -> None:
    """Helper should return None when no candidate path exists."""
    module = _load()

    found = module.find_existing_script(  # type: ignore[attr-defined]
        [str(tmp_path / "missing-a.py"), str(tmp_path / "missing-b.py")]
    )

    assert found is None


def test_get_pr_merge_commit_requires_merged_state(monkeypatch) -> None:
    """Only GitHub's immutable merged-PR receipt may license squash closeout."""

    module = _load()
    monkeypatch.setattr(
        module,
        "run_cmd",
        lambda cmd, check=True, capture=True: completed_process(
            cmd,
            stdout='{"state":"MERGED","mergeCommit":{"oid":"abc123"}}',
        ),
    )

    assert module.get_pr_merge_commit(107) == "abc123"


def test_cleanup_worktree_uses_safe_remove_script_with_discovered_path(
    monkeypatch, tmp_path
) -> None:
    """Cleanup should follow the discovered worktree path, not branch-derived layout."""
    module = _load()
    monkeypatch.chdir(tmp_path)
    safe_remove = (
        tmp_path
        / "scripts"
        / "meta"
        / "worktree-coordination"
        / "safe_worktree_remove.py"
    )
    safe_remove.parent.mkdir(parents=True)
    safe_remove.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    discovered_path = tmp_path / "worktrees" / "tmp-plan-69-llm-client-resync"
    observed_calls: list[list[str]] = []

    monkeypatch.setattr(
        module, "find_worktree_for_branch", lambda branch: discovered_path
    )
    monkeypatch.setattr(module, "release_claim_for_branch", lambda branch: True)

    def fake_run_cmd(
        cmd, check: bool = True, capture: bool = True
    ) -> subprocess.CompletedProcess[str]:
        observed_calls.append(cmd)
        return completed_process(cmd)

    monkeypatch.setattr(module, "run_cmd", fake_run_cmd)

    assert (
        module.cleanup_worktree("codex/llm-client-worktree-block-resync") is True
    )
    assert observed_calls == [
        [
            "python",
            "scripts/meta/worktree-coordination/safe_worktree_remove.py",
            str(discovered_path),
        ]
    ]


def test_cleanup_worktree_falls_back_to_make_when_safe_remove_missing(
    monkeypatch, tmp_path
) -> None:
    """Fallback should preserve the old make-based path only when no safe remover exists."""
    module = _load()
    monkeypatch.chdir(tmp_path)

    discovered_path = tmp_path / "worktrees" / "branch-dir"
    observed_calls: list[list[str]] = []

    monkeypatch.setattr(
        module, "find_worktree_for_branch", lambda branch: discovered_path
    )
    monkeypatch.setattr(module, "release_claim_for_branch", lambda branch: True)

    def fake_run_cmd(
        cmd, check: bool = True, capture: bool = True
    ) -> subprocess.CompletedProcess[str]:
        observed_calls.append(cmd)
        return completed_process(cmd)

    monkeypatch.setattr(module, "run_cmd", fake_run_cmd)

    assert module.cleanup_worktree("codex/example") is True
    assert observed_calls == [["make", "worktree-remove", "BRANCH=codex/example"]]


def test_cleanup_worktree_reports_manual_safe_remove_command_on_failure(
    monkeypatch, tmp_path, capsys
) -> None:
    """Failure output should guide operators to the path-based cleanup command."""
    module = _load()
    monkeypatch.chdir(tmp_path)
    safe_remove = (
        tmp_path
        / "scripts"
        / "meta"
        / "worktree-coordination"
        / "safe_worktree_remove.py"
    )
    safe_remove.parent.mkdir(parents=True)
    safe_remove.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    discovered_path = tmp_path / "worktrees" / "tmp-plan-69-llm-client-resync"

    monkeypatch.setattr(
        module, "find_worktree_for_branch", lambda branch: discovered_path
    )
    monkeypatch.setattr(module, "release_claim_for_branch", lambda branch: True)
    monkeypatch.setattr(
        module,
        "run_cmd",
        lambda cmd, check=True, capture=True: completed_process(
            cmd, returncode=1, stderr="cleanup failed"
        ),
    )

    assert (
        module.cleanup_worktree("codex/llm-client-worktree-block-resync") is False
    )
    captured = capsys.readouterr()
    assert "cleanup failed" in captured.out
    assert (
        "Run manually: python scripts/meta/worktree-coordination/safe_worktree_remove.py "
        f"{discovered_path}"
    ) in captured.out


def test_cleanup_without_worktree_still_records_session_close(
    monkeypatch, tmp_path
) -> None:
    """A missing local worktree must not silently leave merged ownership active."""

    module = _load()
    monkeypatch.chdir(tmp_path)
    session_close = tmp_path / "scripts" / "session_close.py"
    session_close.parent.mkdir(parents=True)
    session_close.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_THREAD_ID", "test-thread")
    monkeypatch.setattr(module, "find_worktree_for_branch", lambda _branch: None)
    monkeypatch.setattr(
        module,
        "resolve_claim_identity",
        lambda _branch, *, agent, worktree_path: ("actual-project", "actual-scope"),
    )
    observed_calls: list[list[str]] = []

    def fake_run_cmd(
        cmd, check: bool = True, capture: bool = True
    ) -> subprocess.CompletedProcess[str]:
        observed_calls.append(cmd)
        return completed_process(cmd)

    monkeypatch.setattr(module, "run_cmd", fake_run_cmd)

    assert module.cleanup_worktree("plan-107-landed") is True
    assert observed_calls == [
        [
            "python",
            "scripts/session_close.py",
            "--agent",
            "codex",
            "--project",
            "actual-project",
            "--scope",
            "actual-scope",
            "--branch",
            "plan-107-landed",
        ]
    ]


def test_resolve_claim_identity_uses_registry_project_and_scope(monkeypatch, tmp_path) -> None:
    """Branch cleanup must use claim identity, not the worktree directory name."""

    module = _load()
    claims_script = tmp_path / "scripts" / "check_coordination_claims.py"
    claims_script.parent.mkdir(parents=True)
    claims_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    worktree = tmp_path / "worktrees" / "feature"
    payload = {
        "claims": [
            {
                "agent": "codex",
                "branch": "feature",
                "status": "active",
                "projects": ["enforced-planning"],
                "scope": "claim-scope",
                "worktree_path": str(worktree),
            }
        ]
    }
    monkeypatch.setattr(
        module,
        "run_cmd",
        lambda cmd, check=True, capture=True: completed_process(
            cmd,
            stdout=json.dumps(payload),
        ),
    )

    assert module.resolve_claim_identity(
        "feature",
        agent="codex",
        worktree_path=worktree,
    ) == ("enforced-planning", "claim-scope")


def test_canonical_repo_root_uses_git_common_dir(monkeypatch, tmp_path) -> None:
    """Merge closeout must run outside the linked worktree being removed."""

    module = _load()
    common_dir = tmp_path / "canonical" / ".git"
    monkeypatch.setattr(
        module,
        "run_cmd",
        lambda cmd, check=True, capture=True: completed_process(
            cmd,
            stdout=f"{common_dir}\n",
        ),
    )

    assert module.canonical_repo_root() == common_dir.parent


def test_reject_self_removing_invocation_inside_target_worktree(
    monkeypatch, tmp_path, capsys
) -> None:
    """The merge must not invalidate the parent tool runner's working directory."""

    module = _load()
    canonical_root = tmp_path / "canonical"
    worktree = canonical_root / "worktrees" / "feature"
    invocation_cwd = worktree / "src"
    invocation_cwd.mkdir(parents=True)
    monkeypatch.setattr(module, "find_worktree_for_branch", lambda _branch: worktree)
    monkeypatch.setattr(module, "canonical_repo_root", lambda: canonical_root)

    assert module.reject_self_removing_invocation(
        "feature",
        invocation_cwd=invocation_cwd,
        pr_number=315,
    )

    output = capsys.readouterr().out
    assert "parent tool runner would retain this cwd" in output
    assert (
        f"cd {canonical_root} && python scripts/merge_pr.py 315"
        in output
    )


def test_merge_refuses_self_removing_caller_before_github_mutation(
    monkeypatch, tmp_path, capsys
) -> None:
    """Unsafe invocation is rejected before fetch, mergeability, or GitHub writes."""

    module = _load()
    worktree = tmp_path / "worktrees" / "feature"
    worktree.mkdir(parents=True)
    observed_calls: list[list[str]] = []
    monkeypatch.setattr(module, "get_pr_branch", lambda _pr: "feature")
    monkeypatch.setattr(module, "find_worktree_for_branch", lambda _branch: worktree)
    monkeypatch.setattr(module, "canonical_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        module,
        "run_cmd",
        lambda cmd, check=True, capture=True: (
            observed_calls.append(cmd) or completed_process(cmd)
        ),
    )

    assert not module.merge_pr(
        315,
        invocation_cwd=worktree,
    )
    assert observed_calls == []
    assert "refusing to merge" in capsys.readouterr().out


def test_merge_reports_high_failure_when_post_merge_closeout_fails(
    monkeypatch, capsys
) -> None:
    """A successful GitHub merge is not a successful command until closeout succeeds."""

    module = _load()
    monkeypatch.setattr(module, "get_pr_branch", lambda _pr: "plan-107-landed")
    monkeypatch.setattr(module, "check_pr_mergeable", lambda _pr: (True, "OK"))

    def reject_closeout(_branch, *, merge_commit=None, execute=True) -> bool:
        assert execute is True
        return False

    monkeypatch.setattr(
        module,
        "cleanup_worktree",
        reject_closeout,
    )
    monkeypatch.setattr(module, "get_pr_merge_commit", lambda _pr: "merge-commit")
    monkeypatch.setattr(
        module,
        "run_cmd",
        lambda cmd, check=True, capture=True: completed_process(cmd),
    )

    assert module.merge_pr(107) is False
    assert "HIGH: PR merged, but claim/worktree closeout failed" in capsys.readouterr().out


def test_deferred_closeout_prints_exact_session_close_without_executing(
    monkeypatch, tmp_path, capsys
) -> None:
    """Deferred mode must retain ownership and print one exact receipt-bound command."""

    module = _load()
    monkeypatch.chdir(tmp_path)
    session_close = tmp_path / "scripts" / "session_close.py"
    session_close.parent.mkdir(parents=True)
    session_close.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    worktree = tmp_path / "worktrees" / "feature"
    canonical_root = tmp_path
    monkeypatch.setenv("CODEX_THREAD_ID", "test-thread")
    monkeypatch.setattr(module, "find_worktree_for_branch", lambda _branch: worktree)
    monkeypatch.setattr(module, "canonical_repo_root", lambda: canonical_root)
    monkeypatch.setattr(
        module,
        "resolve_claim_identity",
        lambda _branch, *, agent, worktree_path: ("actual-project", "actual-scope"),
    )
    observed_calls: list[list[str]] = []
    monkeypatch.setattr(
        module,
        "run_cmd",
        lambda cmd, check=True, capture=True: (
            observed_calls.append(cmd) or completed_process(cmd)
        ),
    )

    assert (
        module.cleanup_worktree(
            "feature",
            merge_commit="merge-oid",
            execute=False,
        )
        is True
    )

    assert observed_calls == []
    output = capsys.readouterr().out
    assert "MERGED; CLOSEOUT DEFERRED" in output
    assert "claim and worktree remain live" in output
    assert (
        f"cd {canonical_root} && python scripts/session_close.py "
        "--agent codex --project actual-project "
        "--scope actual-scope --branch feature "
        f"--worktree-path {worktree} --merge-commit merge-oid"
    ) in output


def test_deferred_closeout_rejects_missing_runtime_identity(
    monkeypatch, tmp_path, capsys
) -> None:
    """Deferred mode cannot guess claim identity through the make fallback."""

    module = _load()
    monkeypatch.chdir(tmp_path)
    session_close = tmp_path / "scripts" / "session_close.py"
    session_close.parent.mkdir(parents=True)
    session_close.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    worktree = tmp_path / "worktrees" / "feature"
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SSE_PORT", raising=False)
    monkeypatch.delenv("OPENCLAW_SESSION_ID", raising=False)
    monkeypatch.delenv("OPENCLAW_RUN_ID", raising=False)
    monkeypatch.setattr(module, "find_worktree_for_branch", lambda _branch: worktree)

    assert not (
        module.cleanup_worktree(
            "feature",
            merge_commit="merge-oid",
            execute=False,
        )
    )

    output = capsys.readouterr().out
    assert "requires an exact runtime identity" in output
    assert "Then run" not in output


def test_deferred_closeout_rejects_missing_session_close(
    monkeypatch, tmp_path, capsys
) -> None:
    """A legacy remover cannot stand in for atomic receipt-bound closeout."""

    module = _load()
    monkeypatch.chdir(tmp_path)
    worktree = tmp_path / "worktrees" / "feature"
    safe_remove = (
        tmp_path
        / "scripts"
        / "meta"
        / "worktree-coordination"
        / "safe_worktree_remove.py"
    )
    safe_remove.parent.mkdir(parents=True)
    safe_remove.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_THREAD_ID", "test-thread")
    monkeypatch.setattr(module, "find_worktree_for_branch", lambda _branch: worktree)

    assert not module.cleanup_worktree(
        "feature",
        merge_commit="merge-oid",
        execute=False,
    )

    output = capsys.readouterr().out
    assert "requires the sanctioned session-close entrypoint" in output
    assert "safe_worktree_remove.py" not in output


def test_merge_defers_closeout_after_canonical_merge_receipt(
    monkeypatch, capsys
) -> None:
    """Explicit deferred mode merges first and prepares, but does not execute, closeout."""

    module = _load()
    monkeypatch.setattr(module, "get_pr_branch", lambda _pr: "feature")
    monkeypatch.setattr(module, "check_pr_mergeable", lambda _pr: (True, "OK"))
    monkeypatch.setattr(module, "get_pr_merge_commit", lambda _pr: "merge-oid")
    observed_closeouts: list[tuple[str, str | None, bool]] = []
    monkeypatch.setattr(
        module,
        "cleanup_worktree",
        lambda branch, *, merge_commit=None, execute=True: (
            observed_closeouts.append((branch, merge_commit, execute)) or True
        ),
    )
    monkeypatch.setattr(
        module,
        "run_cmd",
        lambda cmd, check=True, capture=True: completed_process(cmd),
    )

    assert module.merge_pr(146, defer_closeout=True) is True
    assert observed_closeouts == [("feature", "merge-oid", False)]
    output = capsys.readouterr().out
    assert "closeout was explicitly deferred and remains mandatory" in output
    assert "Done!" not in output


def test_deferred_closeout_does_not_bypass_missing_merge_receipt(
    monkeypatch, capsys
) -> None:
    """No closeout mode succeeds without GitHub's immutable merge receipt."""

    module = _load()
    monkeypatch.setattr(module, "get_pr_branch", lambda _pr: "feature")
    monkeypatch.setattr(module, "check_pr_mergeable", lambda _pr: (True, "OK"))
    monkeypatch.setattr(module, "get_pr_merge_commit", lambda _pr: None)
    monkeypatch.setattr(
        module,
        "run_cmd",
        lambda cmd, check=True, capture=True: completed_process(cmd),
    )

    assert module.merge_pr(146, defer_closeout=True) is False
    assert "did not return a canonical merge commit" in capsys.readouterr().out


def test_merge_refuses_missing_branch_before_github_mutation(
    monkeypatch, capsys
) -> None:
    """A missing branch identity cannot produce a resumable closeout command."""

    module = _load()
    observed_calls: list[list[str]] = []
    monkeypatch.setattr(module, "get_pr_branch", lambda _pr: None)
    monkeypatch.setattr(
        module,
        "run_cmd",
        lambda cmd, check=True, capture=True: (
            observed_calls.append(cmd) or completed_process(cmd)
        ),
    )

    assert module.merge_pr(146, defer_closeout=True) is False
    assert observed_calls == []
    assert "head branch could not be resolved" in capsys.readouterr().out


def test_main_passes_defer_closeout_flag(monkeypatch, tmp_path) -> None:
    """The public CLI must preserve explicit deferred-closeout intent."""

    module = _load()
    observed: list[tuple[int, bool, bool, Path | None]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "canonical_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        module,
        "merge_pr",
        lambda pr, dry_run=False, *, defer_closeout=False, invocation_cwd=None: (
            observed.append((pr, dry_run, defer_closeout, invocation_cwd)) or True
        ),
    )
    monkeypatch.setattr(sys, "argv", ["merge_pr.py", "146", "--defer-closeout"])

    assert module.main() == 0
    assert observed == [(146, False, True, tmp_path)]
