#!/usr/bin/env python3
"""Sync governance headers in source files from relationships.yaml."""

from __future__ import annotations

import argparse
import os
import py_compile
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml  # type: ignore[import-untyped]


GOVERNANCE_START = "# --- GOVERNANCE START (do not edit) ---"
GOVERNANCE_END = "# --- GOVERNANCE END ---"
GOVERNANCE_PATTERN = re.compile(
    rf"{re.escape(GOVERNANCE_START)}.*?{re.escape(GOVERNANCE_END)}",
    re.DOTALL,
)


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML config file into a dictionary."""
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _parse_adr(raw: Any) -> int | None:
    """Parse ADR references from int or ADR-0001-style strings."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    if text.upper().startswith("ADR-"):
        text = text[4:]
    try:
        return int(text)
    except ValueError:
        return None


def _to_list(value: Any) -> list[Any]:
    """Normalize scalar or list values into a list."""
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _coerce_legacy_governance(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize older governance formats into the current relationships shape."""
    governance: list[dict[str, Any]] = []
    for entry in data.get("governance", []) or []:
        if not isinstance(entry, dict):
            continue
        adr_num = _parse_adr(entry.get("adr"))
        for source in _to_list(entry.get("applies_to")):
            governance.append(
                {
                    "source": str(source),
                    "adrs": [adr_num] if adr_num else [],
                    "context": f"ADR-{adr_num:04d}: {entry.get('title', '')}".strip(": "),
                }
            )
    return governance


def _resolve_config_path(config_arg: str) -> Path:
    """Resolve the config path across relationships/governance legacy names."""
    requested = Path(config_arg)
    if requested.exists():
        return requested
    if requested.name == "relationships.yaml":
        legacy = Path("scripts/governance.yaml")
        if legacy.exists():
            return legacy
    if requested.name == "governance.yaml":
        legacy = Path("scripts/relationships.yaml")
        if legacy.exists():
            return legacy
    return requested


@dataclass
class GovernanceConfig:
    """Normalized governance config for file header synchronization."""

    files: dict[str, list[int]]
    file_context: dict[str, str]
    adrs: dict[int, dict[str, Any]]

    @classmethod
    def load(cls, path: Path) -> "GovernanceConfig":
        """Load and normalize governance config from relationships or legacy YAML."""
        data = _load_yaml(path)

        governance_raw: list[dict[str, Any]] | list[Any] = []
        adrs_raw = data.get("adrs", {})
        if isinstance(data, dict) and "governance" in data:
            governance_raw = data.get("governance", [])
        elif isinstance(data, dict) and isinstance(data.get("files"), dict):
            legacy = data
            adrs_raw = legacy.get("adrs", {}) or {}
            governance_raw = []
            for source, cfg in legacy.get("files", {}).items():
                cfg = cfg if isinstance(cfg, dict) else {}
                governance_raw.append(
                    {
                        "source": source,
                        "adrs": _to_list(cfg.get("adrs", [])),
                        "context": cfg.get("context", ""),
                    }
                )
        else:
            governance_raw = _coerce_legacy_governance(
                data if isinstance(data, dict) else {}
            )

        files: dict[str, list[int]] = {}
        for entry in governance_raw:
            if not isinstance(entry, dict):
                continue
            source = str(entry.get("source", "")).strip()
            if not source:
                continue
            file_adrs: list[int] = []
            for adr in _to_list(entry.get("adrs", [])):
                adr_num = _parse_adr(adr)
                if adr_num is not None:
                    file_adrs.append(adr_num)
            files[source] = sorted(set(file_adrs))

        adrs: dict[int, dict[str, Any]] = {}
        if isinstance(adrs_raw, dict):
            for key, value in adrs_raw.items():
                num = _parse_adr(key)
                if num is None:
                    continue
                info = value if isinstance(value, dict) else {"title": str(value)}
                info["title"] = str(info.get("title", f"ADR-{num:04d}"))
                info["file"] = str(info.get("file", ""))
                adrs[num] = info

        file_context: dict[str, str] = {}
        for path_key, adr_list in files.items():
            file_context[path_key] = "\n".join(
                f"ADR-{num:04d}: {adrs.get(num, {}).get('title', '')}".rstrip(": ")
                for num in adr_list
            )

        return cls(files=files, file_context=file_context, adrs=adrs)

    def get_adr_title(self, adr_num: int) -> str:
        """Return the human-readable title for one ADR number."""
        return self.adrs.get(adr_num, {}).get("title", f"ADR-{adr_num:04d}")

    def resolve_adr_file(self, adr_num: int, repo_root: Path) -> Optional[Path]:
        """Resolve the physical ADR file path for one ADR reference."""
        if adr_num not in self.adrs:
            return None
        rel = self.adrs[adr_num].get("file")
        if not rel:
            return None
        candidates = [
            repo_root / "docs" / "adr" / rel,
            repo_root / "meta-process" / "adr" / rel,
            repo_root / rel,
        ]
        for path in candidates:
            if path.exists():
                return path
        return None

    def validate(self, repo_root: Path) -> list[str]:
        """Validate config references against the current repo root."""
        errors: list[str] = []
        for file_path, adr_nums in self.files.items():
            for adr_num in adr_nums:
                if adr_num not in self.adrs:
                    errors.append(f"{file_path}: references unknown ADR {adr_num}")
                elif self.resolve_adr_file(adr_num, repo_root) is None:
                    title = self.get_adr_title(adr_num)
                    errors.append(
                        f"ADR-{adr_num:04d} ({title}): file not found: "
                        f"{self.adrs[adr_num].get('file')}"
                    )
        for file_path in self.files:
            if not (repo_root / file_path).exists():
                errors.append(f"GOVERNED file not found: {file_path}")
        return errors


def find_files_from_rules(repo_root: Path, files: dict[str, list[int]]) -> list[str]:
    """Expand configured file rules into a concrete, unique file list."""
    resolved: list[str] = []
    for pattern in files:
        if any(ch in pattern for ch in "*?[]"):
            matches = sorted(
                str(path.relative_to(repo_root))
                for path in repo_root.glob(pattern)
                if path.is_file()
            )
            resolved.extend(matches)
        else:
            resolved.append(pattern)
    return sorted(dict.fromkeys(resolved))


def generate_governance_block(config: GovernanceConfig, file_path: str) -> str:
    """Render the canonical governance block for one governed source file."""
    adrs = config.files.get(file_path, [])
    context = config.file_context.get(file_path, "")
    lines = [GOVERNANCE_START]
    for adr_num in sorted(adrs):
        lines.append(f"# ADR-{adr_num:04d}: {config.get_adr_title(adr_num)}")
    if context:
        lines.append("#")
        for line in str(context).splitlines():
            lines.append(f"# {line}" if line.strip() else "#")
    lines.append(GOVERNANCE_END)
    return "\n".join(lines)


def find_docstring_end(content: str) -> Optional[int]:
    """Find the end offset of a leading module docstring if present."""
    stripped = content.lstrip()
    offset = len(content) - len(stripped)
    for quote in ['"""', "'''"]:
        if stripped.startswith(quote):
            end_pos = stripped.find(quote, len(quote))
            if end_pos != -1:
                return offset + end_pos + len(quote)
    return None


def update_file_content(content: str, governance_block: str) -> tuple[str, bool]:
    """Insert or replace the governed block in one source file's content."""
    if GOVERNANCE_START in content:
        match = GOVERNANCE_PATTERN.search(content)
        if match:
            old_block = match.group(0)
            if old_block == governance_block:
                return content, False
            return (
                content[: match.start()] + governance_block + content[match.end() :],
                True,
            )

    docstring_end = find_docstring_end(content)
    if docstring_end is not None:
        before = content[:docstring_end]
        after = content[docstring_end:]
        if not before.endswith("\n"):
            before += "\n"
        return before + "\n" + governance_block + "\n" + after.lstrip("\n"), True

    lines = content.split("\n")
    insert_at = 0
    for index, line in enumerate(lines):
        if line.startswith("#!") or line.startswith("# -*-") or line.startswith("# coding"):
            insert_at = index + 1
        else:
            break
    before = "\n".join(lines[:insert_at])
    after = "\n".join(lines[insert_at:])
    if before:
        return before + "\n\n" + governance_block + "\n\n" + after, True
    return governance_block + "\n\n" + after, True


def validate_python_syntax(path: Path) -> bool:
    """Validate that a modified Python file still compiles."""
    try:
        py_compile.compile(str(path), doraise=True)
        return True
    except py_compile.PyCompileError:
        return False


def is_git_dirty() -> bool:
    """Return whether the current repo has uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False


def sync_file(
    file_path: Path,
    config: GovernanceConfig,
    apply: bool = False,
    backup: bool = False,
) -> tuple[bool, str]:
    """Sync one governed file and optionally write the updated content."""
    if not file_path.exists():
        return False, f"SKIP: {file_path} not found"

    content = file_path.read_text(encoding="utf-8")
    governance_block = generate_governance_block(config, str(file_path))
    new_content, changed = update_file_content(content, governance_block)

    if not changed:
        return False, f"OK: {file_path}"

    if not apply:
        return True, f"WOULD UPDATE: {file_path}"

    if backup:
        file_path.with_suffix(file_path.suffix + ".bak").write_text(content)

    fd, temp_path = tempfile.mkstemp(suffix=".py", dir=file_path.parent)
    try:
        os.write(fd, new_content.encode())
        os.close(fd)
        if file_path.suffix == ".py" and not validate_python_syntax(Path(temp_path)):
            os.unlink(temp_path)
            return (
                True,
                f"ERROR: {file_path} - syntax error after modification, original unchanged",
            )
        os.replace(temp_path, file_path)
        return True, f"UPDATED: {file_path}"
    except Exception as exc:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        return True, f"ERROR: {file_path} - {exc}"


def main() -> int:
    """Run governance sync in dry-run, check, or apply mode."""
    parser = argparse.ArgumentParser(
        description="Sync governance headers in source files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check only, exit 1 if files are out of sync",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default is dry-run)",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create .bak files before modifying (requires --apply)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Apply even if repo is dirty",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("scripts/relationships.yaml"),
        help="Path to relationships.yaml (falls back to governance.yaml)",
    )

    args = parser.parse_args()

    if args.backup and not args.apply:
        parser.error("--backup requires --apply")

    if args.apply and not args.force and is_git_dirty():
        print("ERROR: Git working tree has uncommitted changes.")
        print("Use --force to override this check.")
        return 1

    config_path = _resolve_config_path(str(args.config))
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        return 1

    config = GovernanceConfig.load(config_path)
    repo_root = Path.cwd()

    errors = config.validate(repo_root)
    if errors:
        print("Configuration errors:")
        for error in errors:
            print(f"  - {error}")
        return 1

    if not args.apply and not args.check:
        print("DRY RUN (use --apply to modify files, --check to verify)\n")

    expanded_files = find_files_from_rules(repo_root, config.files)
    changed_count = 0
    outcomes: list[str] = []

    for file_path in expanded_files:
        needs_change, message = sync_file(
            repo_root / file_path,
            config,
            apply=args.apply,
            backup=args.backup,
        )
        outcomes.append(message)
        if needs_change:
            changed_count += 1

    for message in outcomes:
        print(message)

    print()
    if changed_count == 0:
        print("All governed files are in sync.")
        return 0
    if args.check:
        print(f"FAILED: {changed_count} file(s) out of sync.")
        return 1
    if args.apply:
        print(f"Updated {changed_count} file(s).")
    else:
        print(f"{changed_count} file(s) would be updated.")
        print("Run with --apply to modify files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
