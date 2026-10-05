"""Importable workspace and canonical-repo path helpers."""

from __future__ import annotations

from pathlib import Path


def detect_workspace_root(project_root: Path) -> Path:
    """Resolve the shared workspace root from main or worktree checkouts."""
    resolved_project_root = project_root.resolve()
    parent = resolved_project_root.parent
    if parent.name == "worktrees":
        return parent.parent.parent
    if parent.name.endswith("_worktrees"):
        return parent.parent
    return resolved_project_root.parent


def _canonical_root_from_gitfile(worktree_root: Path) -> Path | None:
    """Return the main checkout named by a linked worktree's ``.git`` gitfile.

    ``git worktree add`` writes ``<worktree>/.git`` as a one-line file,
    ``gitdir: <main>/.git/worktrees/<name>`` (absolute, or relative to the
    worktree), and that admin directory holds a ``commondir`` file pointing at
    the shared ``.git``. Linked worktrees may live anywhere on disk, so this is
    the only reliable owner signal. Submodule gitfiles point at
    ``.git/modules/<name>`` instead and are deliberately not treated as linked
    worktrees of the superproject.
    """

    git_marker = worktree_root / ".git"
    if not git_marker.is_file():
        return None
    try:
        marker = git_marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not marker.startswith("gitdir:"):
        return None
    gitdir = Path(marker.split(":", 1)[1].strip()).expanduser()
    if not gitdir.is_absolute():
        gitdir = worktree_root / gitdir
    gitdir = gitdir.resolve()

    common_dir: Path | None = None
    commondir_file = gitdir / "commondir"
    if commondir_file.is_file():
        try:
            raw_common = commondir_file.read_text(encoding="utf-8").strip()
        except OSError:
            raw_common = ""
        if raw_common:
            common_candidate = Path(raw_common).expanduser()
            if not common_candidate.is_absolute():
                common_candidate = gitdir / common_candidate
            common_dir = common_candidate.resolve()
    if common_dir is None and gitdir.parent.name == "worktrees":
        common_dir = gitdir.parent.parent
    if common_dir is None or common_dir.name != ".git":
        return None
    canonical_repo_root = common_dir.parent.resolve()
    if canonical_repo_root == worktree_root or not common_dir.is_dir():
        return None
    return canonical_repo_root


def resolve_canonical_repo_root(repo_root: Path) -> Path:
    """Return the canonical repo root for a main checkout or linked worktree.

    Git's own linked-worktree pointer (the ``.git`` gitfile) wins when present;
    directory naming conventions are the fallback for paths that are already
    gone (idempotent closeout) or were never git checkouts.
    """
    resolved_repo_root = repo_root.resolve()
    from_gitfile = _canonical_root_from_gitfile(resolved_repo_root)
    if from_gitfile is not None:
        return from_gitfile
    # Branches containing "/" create nested paths such as
    # <repo>/worktrees/feat/name. The target may already be absent during an
    # idempotent closeout, so resolve lexically through every ancestor rather
    # than relying on the immediate parent or an existing .git file.
    for ancestor in (resolved_repo_root, *resolved_repo_root.parents):
        if ancestor.name == "worktrees":
            canonical_repo_root = ancestor.parent.resolve()
            if (canonical_repo_root / ".git").exists():
                return canonical_repo_root
            # Claude Code harness worktrees (EnterWorktree) live at
            # <repo>/.claude/worktrees/<name>; the owning repo is one level up.
            if ancestor.parent.name == ".claude":
                canonical_repo_root = ancestor.parent.parent.resolve()
                if (canonical_repo_root / ".git").exists():
                    return canonical_repo_root
        if ancestor.name.endswith("_worktrees"):
            workspace_root = ancestor.parent
            canonical_name = ancestor.name.removesuffix("_worktrees")
            canonical_repo_root = (workspace_root / canonical_name).resolve()
            if (canonical_repo_root / ".git").exists():
                return canonical_repo_root
    return resolved_repo_root


def resolve_canonical_target_path(*, target_path: Path, repo_root: Path) -> Path | None:
    """Map a missing worktree-local path to the canonical repo root when safe.

    This only applies when the candidate path is lexically inside the active
    repo root. Paths outside the repo root are left alone because they may be
    genuine workspace-relative or sibling-repo targets.
    """
    resolved_repo_root = repo_root.resolve()
    canonical_repo_root = resolve_canonical_repo_root(resolved_repo_root)
    if canonical_repo_root == resolved_repo_root:
        return None

    candidate = target_path.expanduser()
    try:
        relative_target = candidate.relative_to(resolved_repo_root)
    except ValueError:
        return None

    canonical_target = (canonical_repo_root / relative_target).resolve(strict=False)
    if canonical_target.exists():
        return canonical_target
    return None


__all__ = [
    "detect_workspace_root",
    "resolve_canonical_repo_root",
    "resolve_canonical_target_path",
]
