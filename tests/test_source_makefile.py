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
