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


def test_npx_backed_recipes_use_a_per_user_npm_cache() -> None:
    """Every recipe that reaches npm must carry its own cache, keyed by uid.

    npm keys its cache on HOME rather than on the user, so when root has already populated
    `$HOME/.npm` the next user hits root-owned directories it cannot mkdir into. That surfaced
    as `lockstep check arch check` reporting the diagram invalid in the nightly fresh-clone run
    (2026-11-18) when the real cause was the shared cache.
    """

    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "NPM_CACHE ?= $(HOME)/.cache/enforced-planning/npm-$(shell id -u)" in makefile

    npx_backed = ("lockstep check arch check", "scripts/check_dead_code.py")
    recipes = [
        line
        for line in makefile.splitlines()
        if line.startswith("\t") and any(command in line for command in npx_backed)
    ]
    assert len(recipes) == len(npx_backed), recipes
    for recipe in recipes:
        assert 'npm_config_cache="$(NPM_CACHE)"' in recipe, recipe
