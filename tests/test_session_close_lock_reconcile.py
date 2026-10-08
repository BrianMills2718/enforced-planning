"""Closing a lane must reconcile the canonical lock it justified.

close_session() releases the claim, but nothing re-derived lock state from the
claim registry afterwards, so every closed lane left the canonical checkout
read-only behind a claim that no longer existed. Observed three times in one
session: the next agent met a bare "Permission denied" from git with no live
lane to explain it.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_COPIES = (
    REPO_ROOT / "scripts" / "session_close.py",
    REPO_ROOT / "scripts" / "meta" / "session_close.py",
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script", SHIPPED_COPIES, ids=lambda p: p.parent.name)
def test_every_shipped_copy_reconciles_on_close(script):
    """Both shipped copies must call the reconcile, not just the one a given
    repo layout happens to invoke."""
    text = script.read_text(encoding="utf-8")
    assert "_reconcile_canonical_lock" in text, f"{script} never reconciles"
    assert "--reconcile" in text
    assert text.count(
        "_reconcile_canonical_lock(args.scope, canonical_lock_module)"
    ) == 1


@pytest.mark.parametrize("script", SHIPPED_COPIES, ids=lambda p: p.parent.name)
def test_reconcile_resolves_the_module_from_either_script_depth(script):
    """The two copies sit at different depths (scripts/ and scripts/meta/) and
    the coordination module is installed beside whichever one a repo uses.
    Resolving only one layout fails closed and SILENTLY -- the stale lock this
    function exists to clear simply stays, and nothing reports it.

    This must exercise the module's own resolver. An earlier version of this
    test recomputed the lookup in the test body and passed against a
    single-path implementation, which is the exact defect it was written to
    catch.
    """
    module = _load(script, f"session_close_{script.parent.name}")
    resolved = module._resolve_canonical_lock_module()
    assert resolved is not None, (
        f"{script} cannot reach canonical_lock.py from its own depth; "
        "the reconcile would silently do nothing"
    )
    assert resolved.name == "canonical_lock.py"
    assert resolved.exists()


def test_reconcile_actually_clears_a_stale_lock(tmp_path):
    """End-to-end against the real locker: a lock with no live lane claim must
    be gone after the reconcile the closeout now runs."""
    lock_script = REPO_ROOT / "scripts" / "worktree-coordination" / "canonical_lock.py"
    repo = tmp_path / "canonical"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "a.txt").write_text("v1", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"], check=True,
    )
    subprocess.run(
        [sys.executable, str(lock_script), "--lock", str(repo), "--quiet"], check=True
    )
    try:
        verify = subprocess.run(
            [sys.executable, str(lock_script), "--verify", str(repo)],
            capture_output=True, text=True, check=False,
        )
        assert '"locked"' in verify.stdout

        # No claim was ever created for this repo, so reconcile must treat the
        # lock as stale and release it.
        subprocess.run(
            [sys.executable, str(lock_script), "--reconcile", "--quiet", "--json",
             "--repo", str(repo)],
            capture_output=True, text=True, check=False,
        )
        after = subprocess.run(
            [sys.executable, str(lock_script), "--verify", str(repo)],
            capture_output=True, text=True, check=False,
        )
        assert '"unlocked"' in after.stdout, after.stdout
        # And the boundary is really gone, not just the bookkeeping.
        (repo / "b.txt").write_text("written", encoding="utf-8")
    finally:
        subprocess.run(
            [sys.executable, str(lock_script), "--unlock", str(repo), "--quiet"],
            check=False,
        )


@pytest.mark.parametrize(
    ("script_directory", "helper_relative_path"),
    (
        (Path("scripts"), Path("scripts/worktree-coordination/canonical_lock.py")),
        (Path("scripts/meta"), Path("scripts/worktree-coordination/canonical_lock.py")),
        (Path("scripts/meta"), Path("scripts/meta/canonical_lock.py")),
    ),
)
def test_resolver_returns_executable_helper_outside_disposable_worktree(
    script_directory: Path,
    helper_relative_path: Path,
    tmp_path: Path,
) -> None:
    """The retained helper must still execute after the lane is removed."""

    module = _load(
        SHIPPED_COPIES[0],
        f"session_close_durable_{str(script_directory).replace('/', '_')}",
    )
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    subprocess.run(["git", "init", "-q", str(canonical)], check=True)
    helper = canonical / helper_relative_path
    helper.parent.mkdir(parents=True)
    helper.write_text("print('durable-helper')\n", encoding="utf-8")
    script = canonical / script_directory / "session_close.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(canonical), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(canonical),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    worktree = tmp_path / "lane"
    subprocess.run(
        ["git", "-C", str(canonical), "worktree", "add", "-qb", "lane", str(worktree)],
        check=True,
    )

    resolved = module._resolve_canonical_lock_module(
        repo_root=worktree,
        script_path=worktree / script_directory / "session_close.py",
    )
    assert resolved == helper
    subprocess.run(
        ["git", "-C", str(canonical), "worktree", "remove", str(worktree)],
        check=True,
    )
    executed = subprocess.run(
        [sys.executable, str(resolved)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert executed.returncode == 0
    assert executed.stdout.strip() == "durable-helper"


@pytest.mark.parametrize("script", SHIPPED_COPIES, ids=lambda p: p.parent.name)
def test_main_resolves_reconcile_helper_before_close_removes_worktree(
    script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The closeout must retain the helper path across worktree deletion."""

    module = _load(script, f"session_close_order_{script.parent.name}")
    helper = tmp_path / "canonical_lock.py"
    helper.write_text("# retained path\n", encoding="utf-8")
    durable_root = tmp_path / "canonical"
    events: list[str] = []
    args = SimpleNamespace(
        project="enforced-planning",
        scope="lane",
        branch="lane",
        merge_commit=None,
        json=False,
        repo_root=tmp_path / "downstream",
    )

    monkeypatch.setattr(module, "parse_args", lambda _argv: args)
    def range_basis(*_args, repo_root: Path) -> tuple[None, str]:
        events.append("range")
        assert repo_root == durable_root
        return None, "merge_base"

    monkeypatch.setattr(module, "_lane_range_basis", range_basis)
    monkeypatch.setattr(module, "_supported_closeout_kwargs", lambda _args: {})

    def resolve_durable_root(root: Path) -> Path:
        events.append("durable-root")
        assert root == args.repo_root
        return durable_root

    monkeypatch.setattr(module, "_resolve_durable_repo_root", resolve_durable_root)
    monkeypatch.setattr(
        module,
        "_materialize_shared_ref_history",
        lambda root: events.append("materialize") or None,
    )
    monkeypatch.setattr(
        module,
        "_resolve_canonical_lock_module",
        lambda: events.append("resolve") or helper,
    )

    def close_session(**_kwargs):
        events.append("close")
        helper.unlink()
        return {
            "action": "closed",
            "worktree_action": "removed",
            "branch_action": "deleted",
            "disposition": "merged",
            "released": True,
            "merge_commit": "abc123",
        }

    monkeypatch.setattr(module.session_lifecycle, "close_session", close_session)

    def reconcile(scope: str, module_path: Path | None = None) -> None:
        events.append("reconcile")
        assert scope == "lane"
        assert module_path == helper

    monkeypatch.setattr(module, "_reconcile_canonical_lock", reconcile)

    def report(_since_revision, _basis, lane_refs, *, repo_root: Path) -> None:
        events.append("report")
        assert repo_root == durable_root
        assert lane_refs == ("lane", "abc123")

    monkeypatch.setattr(module, "_report_shared_ref_movement", report)

    assert module.main([]) == 0
    assert events == [
        "durable-root",
        "materialize",
        "range",
        "resolve",
        "close",
        "reconcile",
        "report",
    ]


@pytest.mark.parametrize("script", SHIPPED_COPIES, ids=lambda p: p.parent.name)
def test_parse_args_accepts_explicit_repo_root(script: Path, tmp_path: Path) -> None:
    module = _load(script, f"session_close_repo_root_args_{script.parent.name}")
    args = module.parse_args(
        [
            "--agent", "codex",
            "--project", "consumer",
            "--scope", "lane",
            "--repo-root", str(tmp_path),
        ]
    )
    assert args.repo_root == str(tmp_path)


@pytest.mark.parametrize("script", SHIPPED_COPIES, ids=lambda p: p.parent.name)
def test_closeout_retains_lane_history_after_deleting_its_branch(
    script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load(script, f"session_close_deleted_branch_{script.parent.name}")
    repo = tmp_path / "consumer"
    repo.mkdir()

    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "closeout@example.invalid")
    git("config", "user.name", "Closeout Test")
    (repo / "base").write_text("base\n")
    git("add", "base")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    git("checkout", "-qb", "lane")
    (repo / "owned").write_text("owned\n")
    git("add", "owned")
    git("commit", "-qm", "own lane content")
    git("checkout", "-q", "main")
    (repo / "foreign").write_text("foreign\n")
    git("add", "foreign")
    git("commit", "-qm", "other writer content")
    git("merge", "--no-ff", "-qm", "integrate lane", "lane")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    args = SimpleNamespace(
        project="consumer", scope="lane", branch="lane", merge_commit=None,
        json=False, repo_root=str(repo),
    )
    monkeypatch.setattr(module, "parse_args", lambda _argv: args)
    monkeypatch.setattr(module, "_materialize_shared_ref_history", lambda _root: None)
    monkeypatch.setattr(module, "_lane_range_basis", lambda *_args, **_kwargs: (base, "start_revision"))
    monkeypatch.setattr(module, "_supported_closeout_kwargs", lambda _args: {})
    monkeypatch.setattr(module, "_resolve_canonical_lock_module", lambda: None)
    monkeypatch.setattr(module, "_reconcile_canonical_lock", lambda *_args: None)

    def close_session(**_kwargs):
        git("branch", "-D", "lane")
        return {
            "action": "closed", "worktree_action": "removed", "branch_action": "deleted",
            "disposition": "merged", "released": True, "merge_commit": None,
        }

    monkeypatch.setattr(module.session_lifecycle, "close_session", close_session)
    assert module.main([]) == 0
    report = capsys.readouterr().err
    assert "other writer content" in report
    assert "own lane content" not in report


@pytest.mark.parametrize("script", SHIPPED_COPIES, ids=lambda p: p.parent.name)
def test_lane_range_basis_uses_the_target_repository(
    script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A central framework wrapper must walk the consumer repo's refs."""

    module = _load(script, f"session_close_target_range_{script.parent.name}")
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(consumer)], check=True)
    (consumer / "seed.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(consumer), "add", "seed.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(consumer), "-c", "user.email=test@example.com",
         "-c", "user.name=Test", "commit", "-m", "base"],
        check=True,
        capture_output=True,
        text=True,
    )
    base = subprocess.run(
        ["git", "-C", str(consumer), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(consumer), "update-ref", "refs/remotes/origin/main", base],
        check=True,
    )
    subprocess.run(["git", "-C", str(consumer), "checkout", "-qb", "lane"], check=True)
    (consumer / "seed.txt").write_text("lane\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(consumer), "add", "seed.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(consumer), "-c", "user.email=test@example.com",
         "-c", "user.name=Test", "commit", "-m", "lane"],
        check=True,
        capture_output=True,
        text=True,
    )
    monkeypatch.setattr(module.coordination_claims, "_load_claims", lambda: [])

    result = module._lane_range_basis(
        "consumer",
        "lane",
        "lane",
        repo_root=consumer,
    )

    assert result == (base, module.concurrent_writers.BASIS_MERGE_BASE)


def test_session_close_make_target_passes_repo_root() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert '--repo-root "$(WORKTREE_REPO_ROOT)"' in makefile


@pytest.mark.parametrize("script", SHIPPED_COPIES, ids=lambda p: p.parent.name)
def test_shared_ref_history_is_fetched_through_an_advertised_branch(
    script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not lazy-fetch a deleted lane's start object by raw object id."""

    module = _load(script, f"session_close_materialize_{script.parent.name}")
    observed: list[list[str]] = []

    def run(command, **_kwargs):
        observed.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module._materialize_shared_ref_history(tmp_path) is None
    assert observed == [
        [
            "git",
            "-C",
            str(tmp_path),
            "fetch",
            "--quiet",
            "--no-tags",
            "origin",
            "+refs/heads/main:refs/remotes/origin/main",
        ]
    ]


@pytest.mark.parametrize("script", SHIPPED_COPIES, ids=lambda p: p.parent.name)
def test_shared_ref_history_refresh_failure_preserves_closeout_fallback(
    script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load(script, f"session_close_materialize_failure_{script.parent.name}")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="network unavailable"
        ),
    )
    assert module._materialize_shared_ref_history(tmp_path) == "network unavailable"
