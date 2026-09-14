"""The sanctioned unplanned lane must state its real requirements.

`make maintenance-worktree` advertises a bounded maintenance bootstrap.  It
must therefore provide its own temporary program write scope rather than
asking an operator for a low-level claim flag the documented command omits.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKE_SURFACES = (
    REPO_ROOT / "Makefile",
    REPO_ROOT / "templates" / "Makefile.worktree.block.template",
)
@pytest.mark.parametrize("surface", MAKE_SURFACES, ids=lambda p: p.name)
def test_help_text_promises_a_self_sufficient_bootstrap(surface):
    """The documented branch-only entrypoint must not demand a hidden path."""
    line = next(
        l for l in surface.read_text(encoding="utf-8").splitlines()
        if l.startswith("maintenance-worktree:")
    )
    assert "needs BRANCH" in line
    if surface == REPO_ROOT / "Makefile":
        # The source Makefile refuses an undeclared scope, so its help must say so.
        assert "SESSION_WRITE_PATHS" in line
    else:
        assert "SESSION_WRITE_PATHS" not in line


@pytest.mark.parametrize(
    "surface", MAKE_SURFACES, ids=lambda p: p.name
)
def test_bootstrap_scope_is_declared_by_the_maintainer_surface(surface):
    """The surface supplies the bootstrap default without discarding an override.

    The repo-root default is what makes the branch-only entrypoint usable: a
    bootstrapping lane may not know its targets yet.  But hardcoding it made
    every maintenance lane claim the whole repository and therefore conflict
    with every other active lane by construction, so an explicit
    SESSION_WRITE_PATHS must win over the default.
    """
    text = surface.read_text(encoding="utf-8")
    fallback = (
        "$(error SESSION_WRITE_PATHS is required."
        if surface == REPO_ROOT / "Makefile"
        # Installed consumers still default an undeclared scope to the repo root.
        else "."
    )
    assert (
        "MAINTENANCE_BOOTSTRAP_WRITE_PATHS = "
        "$(if $(strip $(SESSION_WRITE_PATHS)),$(SESSION_WRITE_PATHS)," + fallback
    ) in text
    assert '"write_paths":sys.argv[5:]' in text
    expected_script = (
        "scripts/claim_bootstrap.py"
        if surface == REPO_ROOT / "Makefile"
        else "scripts/meta/claim_bootstrap.py"
    )
    assert f"{expected_script} --request-json" in text
