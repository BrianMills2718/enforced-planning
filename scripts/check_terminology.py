#!/usr/bin/env python3
"""Terminology linter — scans files for deprecated/legacy terms and reports violations.

Reads ``generated/vocab_pack.jsonl`` (or a custom path) and checks target files
for any string in a term's ``do_not_use`` list. Exits 1 if violations are found,
0 if clean.

Excluded by default:
- ``vision/archive/``, ``docs/plans/archive/``
- ``tests/fixtures/``, ``tests/fixtures``
- Any ``*.jsonl`` file (the pack itself)
- The ``## Legacy / Do Not Use`` section of the canonical glossary

Usage::

    python scripts/check_terminology.py --files vision/04_ROADMAP.md CLAUDE.md
    python scripts/check_terminology.py --glob "**/*.md"
    python scripts/check_terminology.py --files vision/ --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VOCAB_PACK = REPO_ROOT / "generated" / "vocab_pack.jsonl"
DEFAULT_GLOSSARY = REPO_ROOT / "vision" / "06_GLOSSARY.md"

# Path prefixes/patterns that are always excluded
EXCLUDED_PATH_PREFIXES = (
    "vision/archive/",
    "docs/plans/archive/",
    "tests/fixtures/",
    "generated/",
    ".git/",
)


def _is_excluded(path: Path, repo_root: Path) -> bool:
    """Return True if path should be excluded from checks."""
    # Exclude JSONL files (vocab pack itself, etc.)
    if path.suffix == ".jsonl":
        return True
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return False
    rel_str = str(rel).replace("\\", "/")
    return any(rel_str.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES)


def _load_vocab_pack(pack_path: Path) -> list[dict]:
    """Load all records from the vocab pack JSONL file."""
    if not pack_path.exists():
        return []
    records = []
    with pack_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _build_do_not_use_index(records: list[dict]) -> dict[str, str]:
    """Return mapping of deprecated_term -> canonical_term (case-insensitive keys)."""
    index: dict[str, str] = {}
    for rec in records:
        canonical = rec.get("term", "")
        for dnu in rec.get("do_not_use", []):
            if dnu:
                index[dnu.lower()] = canonical
                index[dnu] = canonical  # keep original case key too
    return index


def _strip_legacy_section(text: str) -> str:
    """Remove the '## Legacy / Do Not Use' section from glossary text before scanning."""
    # Find the section and strip it out so the glossary itself doesn't self-violate
    match = re.search(r"\n## Legacy / Do Not Use\b", text)
    if match:
        return text[: match.start()]
    return text


def scan_file(
    path: Path,
    dnu_index: dict[str, str],
    glossary_path: Path,
) -> list[dict]:
    """Scan a single file for deprecated terms. Returns list of violation dicts."""
    violations = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    # Strip legacy section from glossary to avoid self-violations
    if path.resolve() == glossary_path.resolve():
        text = _strip_legacy_section(text)

    lines = text.splitlines()
    for lineno, line in enumerate(lines, start=1):
        for dnu_term, canonical in dnu_index.items():
            # Case-sensitive word-boundary match
            # Use regex word boundaries; also handle multi-word terms
            pattern = r"(?<!\w)" + re.escape(dnu_term) + r"(?!\w)"
            if re.search(pattern, line):
                violations.append(
                    {
                        "file": str(path),
                        "line": lineno,
                        "deprecated_term": dnu_term,
                        "canonical": canonical,
                        "context": line.strip()[:120],
                    }
                )
                break  # One violation per line is enough

    return violations


def collect_files(paths: list[str], repo_root: Path) -> list[Path]:
    """Expand file paths and globs into a deduplicated list of Path objects."""
    collected: list[Path] = []
    seen: set[Path] = set()

    for raw in paths:
        p = Path(raw)
        if not p.is_absolute():
            p = repo_root / p

        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix in (".md", ".txt", ".yaml", ".yml", ".py", ".sh"):
                    if f not in seen and not _is_excluded(f, repo_root):
                        collected.append(f)
                        seen.add(f)
        elif p.is_file():
            if p not in seen and not _is_excluded(p, repo_root):
                collected.append(p)
                seen.add(p)

    return collected


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--files",
        nargs="+",
        default=[],
        help="Files or directories to scan",
    )
    parser.add_argument(
        "--glob",
        metavar="PATTERN",
        help="Glob pattern relative to repo root (e.g. '**/*.md')",
    )
    parser.add_argument(
        "--vocab-pack",
        type=Path,
        default=DEFAULT_VOCAB_PACK,
        help="Path to vocab_pack.jsonl",
    )
    parser.add_argument(
        "--glossary",
        type=Path,
        default=DEFAULT_GLOSSARY,
        help="Path to canonical glossary (excluded from self-check violations)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root for relative path resolution",
    )
    args = parser.parse_args(argv)

    if not args.vocab_pack.exists():
        msg = f"Vocab pack not found: {args.vocab_pack}. Run: python scripts/generate_vocab_pack.py"
        if args.json:
            print(json.dumps({"ok": False, "error": msg}))
        else:
            print(f"ERROR: {msg}", file=sys.stderr)
        return 1

    records = _load_vocab_pack(args.vocab_pack)
    dnu_index = _build_do_not_use_index(records)

    # Collect files to scan
    file_inputs = list(args.files)
    if args.glob:
        for match in sorted(args.repo_root.rglob(args.glob.lstrip("/"))):
            if match.is_file():
                file_inputs.append(str(match))

    if not file_inputs:
        if args.json:
            print(json.dumps({"ok": True, "violations": [], "files_scanned": 0}))
        else:
            print("No files to scan.")
        return 0

    files = collect_files(file_inputs, args.repo_root)

    all_violations: list[dict] = []
    for f in files:
        violations = scan_file(f, dnu_index, args.glossary)
        all_violations.extend(violations)

    ok = len(all_violations) == 0

    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "violations": all_violations,
                    "files_scanned": len(files),
                    "violation_count": len(all_violations),
                }
            )
        )
    else:
        if all_violations:
            print(f"Terminology violations found ({len(all_violations)}):")
            for v in all_violations:
                try:
                    rel = Path(v["file"]).relative_to(args.repo_root)
                except ValueError:
                    rel = Path(v["file"])
                print(f"  {rel}:{v['line']}: '{v['deprecated_term']}' → use '{v['canonical']}'")
                print(f"    {v['context']}")
        else:
            print(f"Terminology OK ({len(files)} files scanned, 0 violations).")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
