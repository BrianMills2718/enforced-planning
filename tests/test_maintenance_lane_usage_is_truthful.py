"""The sanctioned unplanned lane must state its real requirements.

`make maintenance-worktree` advertised "BRANCH=<name> is enough" while
create_worktree.py rejected the lane without a write path, and the rejection
named --claim-write-path, a flag the operator never types. Two agents hit this
in one day, in two repositories, once because syncing the newer coordination
surfaces propagated the requirement into a repo whose help text still made the
old promise.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKE_SURFACES = (
    REPO_ROOT / "Makefile",
    REPO_ROOT / "templates" / "Makefile.worktree.block.template",
)
# Both shipped copies matter: the Makefile invokes the scripts/meta/ one, so
# patching only the scripts/ copy leaves the operator-facing message unchanged.
CREATE_WORKTREE_COPIES = (
    REPO_ROOT / "scripts" / "worktree-coordination" / "create_worktree.py",
    REPO_ROOT / "scripts" / "meta" / "worktree-coordination" / "create_worktree.py",
)


@pytest.mark.parametrize("surface", MAKE_SURFACES, ids=lambda p: p.name)
def test_help_text_does_not_promise_branch_is_enough(surface):
    """The lane needs more than BRANCH; saying otherwise sends the operator
    into a rejection whose cause is not in the message they read."""
    line = next(
        l for l in surface.read_text(encoding="utf-8").splitlines()
        if l.startswith("maintenance-worktree:")
    )
    assert "BRANCH=<name> is enough" not in line
    assert "SESSION_WRITE_PATHS" in line, (
        "the help must name the variable whose absence blocks the lane"
    )


@pytest.mark.parametrize(
    "create_worktree", CREATE_WORKTREE_COPIES, ids=lambda p: p.parts[-3]
)
def test_write_path_rejection_names_the_variable_the_operator_sets(create_worktree):
    """--claim-write-path is an internal flag. An operator using the sanctioned
    Make entrypoint sets SESSION_WRITE_PATHS, so the failure must say so.

    Parametrised over both shipped copies: the first version of this fix
    patched only scripts/, while the Makefile invokes scripts/meta/, so the
    message an operator actually saw was unchanged and the test still passed.
    """
    text = create_worktree.read_text(encoding="utf-8")
    match = re.search(
        r"Scoped write-claim enforcement requires at least one --claim-write-path.*?\n\s*\)",
        text,
        re.S,
    )
    assert match, "the write-path rejection message could not be located"
    message = match.group(0)
    assert "SESSION_WRITE_PATHS" in message
    # Steer away from the broad claim that defeats scoped write boundaries.
    assert '"."' in message
