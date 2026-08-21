"""Detect whether a consumer installs enforced-planning rather than vendoring it."""

from __future__ import annotations

import tomllib
from pathlib import Path

DISTRIBUTION_NAMES = ("enforced-planning", "enforced_planning")


def declares_installed_framework(repo_root: Path) -> bool:
    """Return whether the consumer declares enforced-planning as a dependency.

    A consumer that declares the framework owns its copy through that pin, not
    through the installer. Copying ``enforced_planning/*`` into such a repo
    silently re-vendors the tree the consumer deliberately removed, so the next
    upgrade run undoes the conversion without saying so.

    The signal is the consumer's own declaration rather than an installer flag,
    so it cannot drift out of step with what the repository actually does.
    """

    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    project = data.get("project")
    if not isinstance(project, dict):
        return False
    requirements: list[str] = []
    declared = project.get("dependencies")
    if isinstance(declared, list):
        requirements.extend(str(entry) for entry in declared)
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        for group in optional.values():
            if isinstance(group, list):
                requirements.extend(str(entry) for entry in group)
    canonical = {name.replace("_", "-") for name in DISTRIBUTION_NAMES}
    for requirement in requirements:
        name = requirement.split(";")[0].split("@")[0].strip()
        name = name.split("[")[0].strip().casefold().replace("_", "-")
        if name in canonical:
            return True
    return False


def drop_vendored_package_files(files: dict[str, str], repo_root: Path) -> dict[str, str]:
    """Remove ``enforced_planning/*`` targets when the consumer installs the package."""

    if not declares_installed_framework(repo_root):
        return files
    return {
        target: source
        for target, source in files.items()
        if not target.startswith("enforced_planning/")
    }
