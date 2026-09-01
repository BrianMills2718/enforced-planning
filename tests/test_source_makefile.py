"""Regression checks for the source repository's self-hosted Make lifecycle."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_source_makefile_exposes_operational_plan_resume() -> None:
    """The source checkout must use its real CLI and forward explicit resume."""
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "WORKTREE_PLAN_READINESS_SCRIPT := scripts/check_plan_readiness.py" in makefile
    assert (PROJECT_ROOT / "scripts" / "check_plan_readiness.py").is_file()
    assert "PLAN_RESUME ?=" in makefile
    assert "$(if $(PLAN_RESUME),--resume,)" in makefile


def test_source_makefile_exposes_owner_bound_session_narrow() -> None:
    """The source repo must expose the same narrow operation installed consumers receive."""

    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "WORKTREE_SESSION_NARROW_SCRIPT :=" in makefile
    assert "session-narrow:" in makefile
    assert '--scope "$(BRANCH)"' in makefile
    assert '$(foreach path,$(SESSION_WRITE_PATHS),--write-path "$(path)")' in makefile
    assert (PROJECT_ROOT / "scripts" / "session_narrow.py").is_file()
