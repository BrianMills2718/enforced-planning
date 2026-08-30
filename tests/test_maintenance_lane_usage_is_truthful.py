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
    assert "SESSION_WRITE_PATHS" not in line


@pytest.mark.parametrize(
    "surface", MAKE_SURFACES, ids=lambda p: p.name
)
def test_bootstrap_scope_is_declared_by_the_maintainer_surface(surface):
    """The caller cannot accidentally select a broader or narrower path."""
    text = surface.read_text(encoding="utf-8")
    assert "MAINTENANCE_BOOTSTRAP_WRITE_PATHS = ." in text
    assert 'SESSION_WRITE_PATHS="$(MAINTENANCE_BOOTSTRAP_WRITE_PATHS)"' in text
