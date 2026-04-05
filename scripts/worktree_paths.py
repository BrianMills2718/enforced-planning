"""Resolve shared workspace and canonical repo roots for worktree checkouts.

These helpers keep meta-process tools truthful when they run from a
``*_worktrees/<branch>`` checkout. The active worktree remains the write target,
but canonical source files may still live in the main repo root when they are
intentionally untracked in git, such as ``project-meta/research_texts``.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning.worktree_paths import detect_workspace_root
from enforced_planning.worktree_paths import resolve_canonical_repo_root
