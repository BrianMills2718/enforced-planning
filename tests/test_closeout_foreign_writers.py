"""Closeout must not blame a session for another live writer's uncommitted work.

The check fingerprints a whole repository against a baseline taken at session
start, so a second session editing that repo mid-run is attributed to whichever
session closes out first. That session cannot commit the change (not its work),
cannot discard it (destructive), and had no way to disclaim it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

_SPEC = importlib.util.spec_from_file_location(
    "coordination_hook_under_test", _ROOT / "scripts" / "coordination_hook.py"
)
assert _SPEC and _SPEC.loader
hook = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hook)


class _Claim:
    def __init__(self, session_id: str | None, repo_root: str | None) -> None:
        self.session_id = session_id
        self.repo_root = repo_root


def _patch_claims(monkeypatch: pytest.MonkeyPatch, claims: list[_Claim]) -> None:
    import types

    module = types.SimpleNamespace(list_claims=lambda: claims)
    monkeypatch.setitem(sys.modules, "enforced_planning.coordination_claims", module)
    package = types.SimpleNamespace(coordination_claims=module)
    monkeypatch.setitem(sys.modules, "enforced_planning", package)


def test_another_sessions_claim_marks_the_repo_foreign(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "shared-repo"
    repo.mkdir()
    _patch_claims(monkeypatch, [_Claim("codex-other-session", str(repo))])
    assert str(repo.resolve()) in hook._repositories_with_foreign_live_claims("mine")


def test_my_own_claim_does_not_exempt_me(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A session must still answer for the repo it claimed itself."""
    repo = tmp_path / "my-repo"
    repo.mkdir()
    _patch_claims(monkeypatch, [_Claim("mine", str(repo))])
    assert hook._repositories_with_foreign_live_claims("mine") == set()


def test_repo_with_no_claim_is_still_enforced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The ordinary single-writer case is unchanged - this is the whole point."""
    _patch_claims(monkeypatch, [])
    assert hook._repositories_with_foreign_live_claims("mine") == set()


def test_claim_without_repo_root_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_claims(monkeypatch, [_Claim("other", None)])
    assert hook._repositories_with_foreign_live_claims("mine") == set()


def test_unreadable_claim_registry_never_blocks_closeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail open here: a broken registry must not strand every session."""
    import types

    def _boom() -> list[_Claim]:
        raise RuntimeError("registry unreadable")

    module = types.SimpleNamespace(list_claims=_boom)
    monkeypatch.setitem(sys.modules, "enforced_planning.coordination_claims", module)
    monkeypatch.setitem(
        sys.modules, "enforced_planning", types.SimpleNamespace(coordination_claims=module)
    )
    assert hook._repositories_with_foreign_live_claims("mine") == set()
