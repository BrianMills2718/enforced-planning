#!/usr/bin/env python3
"""Report vendored `enforced_planning/` drift across the consumer fleet.

`enforced-planning` ships an installable Python package, but no consumer
installs it. Every governed repo instead carries a copy of `enforced_planning/`
made at bootstrap and never resynced. Nothing measured that, so the divergence
was invisible: each individual copy looks fine, and the cost only exists in
aggregate.

This counts it. For every consumer carrying a vendored tree it reports how many
modules match canonical, how many differ, and -- for each differing module --
which *direction* it drifted:

    behind     the exact file content is an older canonical revision, so the
               consumer is simply stale. Safe to resync.
    ahead      the file is canonical HEAD plus local edits. Deliberate local
               adaptation, not staleness. Resyncing would destroy work.
    diverged   the file is an *older* canonical revision plus local edits: both
               stale and modified. Needs a merge, not a copy.
    unresolved the content does not resemble any canonical revision of that
               path closely enough to infer a base. Reported as unknown rather
               than guessed.

Direction is decided from the canonical repo's own git history: the vendored
file's blob hash is looked up against every historical blob of that path. An
exact hit is decisive (`behind`). Only when there is no exact hit does the
report fall back to similarity against each historical revision to infer the
base the consumer forked from, and it records that similarity so the inference
is auditable.

This is a report, not a gate. It always exits 0.

    python scripts/fleet_drift.py
    python scripts/fleet_drift.py --json
    make fleet-drift
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCHEMA = "fleet_drift/v1"
PACKAGE_DIR = "enforced_planning"
NULL_BLOB = "0" * 40

_HOME = Path.home()
#: `~/code` is the flat workspace root; `~/projects` and `~/code/active` are the
#: legacy layouts. Overlaps are de-duplicated by realpath in discover_consumers.
DEFAULT_SCAN_ROOTS = (
    str(_HOME / "projects"),
    str(_HOME / "code" / "active"),
    str(_HOME / "code"),
)
DEFAULT_SCAN_DEPTH = 2
DEFAULT_PROJECT_GRAPH = "/home/brian/code/active/project-meta/PROJECT_GRAPH.json"

SKIP_DIR_NAMES = frozenset({"__pycache__", ".git", "worktrees"})
SKIP_SUFFIXES = (".pyc", ".pyo")

#: Below this line-similarity against the best-matching canonical revision, the
#: base is reported as unresolved rather than inferred. A vendored file that
#: shares less than this with every revision of its path is not a fork of it in
#: any useful sense.
MIN_BASE_SIMILARITY = 0.60

BEHIND = "behind"
AHEAD = "ahead"
DIVERGED = "diverged"
UNRESOLVED = "unresolved"
LOCAL_ONLY = "local-only"
REMOVED_UPSTREAM = "removed-upstream"
IDENTICAL = "identical"

#: Directions that mean "this module differs from canonical HEAD".
DRIFT_DIRECTIONS = (BEHIND, AHEAD, DIVERGED, UNRESOLVED)


# ---------------------------------------------------------------------------
# git plumbing
# ---------------------------------------------------------------------------


def blob_hash(data: bytes) -> str:
    """Git's object id for `data` as a blob, computed without invoking git."""
    digest = hashlib.sha1()
    digest.update(b"blob %d\0" % len(data))
    digest.update(data)
    return digest.hexdigest()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@dataclass(frozen=True)
class Revision:
    """One historical content state of one canonical path."""

    commit: str
    timestamp: int
    blob: str

    @property
    def short(self) -> str:
        return self.commit[:8]

    @property
    def date(self) -> str:
        return datetime.fromtimestamp(self.timestamp, tz=UTC).strftime("%Y-%m-%d")


class CanonicalIndex:
    """Canonical `enforced_planning/` content at HEAD plus its full blob history.

    The history index is what makes drift *direction* answerable. Without it a
    differing file is just "different"; with it, an exact blob match against an
    older revision proves the consumer is stale rather than customised.
    """

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.revision = _git(repo_root, "rev-parse", "HEAD").strip()
        self.head_blobs = self._read_head_tree()
        self.history = self._read_history()
        self._blob_cache: dict[str, list[str]] = {}
        self._cat_file: subprocess.Popen[bytes] | None = None

    # -- construction -------------------------------------------------------

    def _read_head_tree(self) -> dict[str, str]:
        blobs: dict[str, str] = {}
        out = _git(self.repo_root, "ls-tree", "-r", "HEAD", "--", PACKAGE_DIR)
        for line in out.splitlines():
            if "\t" not in line:
                continue
            meta, path = line.split("\t", 1)
            fields = meta.split()
            if len(fields) < 3 or fields[1] != "blob":
                continue
            blobs[path] = fields[2]
        return blobs

    def _read_history(self) -> dict[str, list[Revision]]:
        """Every blob every canonical path has ever held, newest first.

        `--full-history` is deliberate: with default history simplification git
        drops commits whose change came in through a merge, and those dropped
        blobs are exactly the ones a consumer may be sitting on.
        """
        out = _git(
            self.repo_root,
            "log",
            "--full-history",
            "--raw",
            "--no-abbrev",
            "--format=C%H %ct",
            "--",
            PACKAGE_DIR,
        )
        history: dict[str, list[Revision]] = {}
        commit = ""
        timestamp = 0
        for line in out.splitlines():
            if line.startswith("C"):
                head, _, tail = line[1:].partition(" ")
                if len(head) == 40 and tail.strip().isdigit():
                    commit, timestamp = head, int(tail.strip())
                continue
            if not line.startswith(":") or "\t" not in line:
                continue
            meta, path = line.split("\t", 1)
            fields = meta.split()
            if len(fields) < 4:
                continue
            new_blob = fields[3]
            if new_blob == NULL_BLOB:
                continue
            entries = history.setdefault(path, [])
            if any(entry.blob == new_blob for entry in entries):
                continue
            entries.append(Revision(commit=commit, timestamp=timestamp, blob=new_blob))
        return history

    # -- blob reads ---------------------------------------------------------

    def read_blob_lines(self, sha: str) -> list[str]:
        """Text lines of a canonical blob, cached across consumers.

        The same handful of canonical blobs is compared against many consumers,
        so a persistent `git cat-file --batch` plus a cache turns what would be
        thousands of subprocesses into one.
        """
        cached = self._blob_cache.get(sha)
        if cached is not None:
            return cached
        proc = self._ensure_cat_file()
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(f"{sha}\n".encode())
        proc.stdin.flush()
        header = proc.stdout.readline().decode().strip()
        parts = header.split()
        if len(parts) != 3:
            raise RuntimeError(f"git cat-file --batch returned {header!r} for {sha}")
        size = int(parts[2])
        payload = proc.stdout.read(size)
        proc.stdout.read(1)  # trailing newline git appends after the object
        lines = payload.decode("utf-8", errors="replace").splitlines()
        self._blob_cache[sha] = lines
        return lines

    def _ensure_cat_file(self) -> subprocess.Popen[bytes]:
        if self._cat_file is None or self._cat_file.poll() is not None:
            self._cat_file = subprocess.Popen(
                ["git", "cat-file", "--batch"],
                cwd=self.repo_root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
        return self._cat_file

    def close(self) -> None:
        if self._cat_file is not None and self._cat_file.poll() is None:
            if self._cat_file.stdin is not None:
                self._cat_file.stdin.close()
            self._cat_file.wait(timeout=10)
        self._cat_file = None

    # -- convenience --------------------------------------------------------

    @property
    def module_count(self) -> int:
        return len(self.head_blobs)

    def line_count(self) -> int:
        total = 0
        for sha in self.head_blobs.values():
            total += len(self.read_blob_lines(sha))
        return total


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------


@dataclass
class FileDrift:
    """Drift verdict for one vendored module."""

    module: str
    direction: str
    lines: int
    revisions_behind: int | None = None
    base_commit: str | None = None
    base_date: str | None = None
    similarity: float | None = None
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "module": self.module,
            "direction": self.direction,
            "lines": self.lines,
            "revisions_behind": self.revisions_behind,
            "base_commit": self.base_commit,
            "base_date": self.base_date,
            "similarity": round(self.similarity, 4) if self.similarity is not None else None,
            "note": self.note,
        }


def classify_file(
    module: str,
    data: bytes,
    index: CanonicalIndex,
) -> FileDrift:
    """Decide how one vendored file relates to canonical.

    `module` is the path relative to the consumer's repo root, e.g.
    `enforced_planning/push_safety.py`.
    """
    text_lines = data.decode("utf-8", errors="replace").splitlines()
    lines = len(text_lines)
    sha = blob_hash(data)
    head_blob = index.head_blobs.get(module)
    revisions = index.history.get(module, [])

    if head_blob is None:
        if revisions:
            newest = revisions[0]
            return FileDrift(
                module=module,
                direction=REMOVED_UPSTREAM,
                lines=lines,
                base_commit=newest.commit,
                base_date=newest.date,
                note="canonical deleted this module; the consumer still carries it",
            )
        return FileDrift(
            module=module,
            direction=LOCAL_ONLY,
            lines=lines,
            note="no canonical counterpart at HEAD or anywhere in canonical history",
        )

    if sha == head_blob:
        return FileDrift(module=module, direction=IDENTICAL, lines=lines)

    for position, revision in enumerate(revisions):
        if revision.blob != sha:
            continue
        return FileDrift(
            module=module,
            direction=BEHIND,
            lines=lines,
            revisions_behind=position,
            base_commit=revision.commit,
            base_date=revision.date,
            similarity=1.0,
            note="exact match to an older canonical revision",
        )

    return _classify_modified(module, text_lines, lines, index, revisions)


def _classify_modified(
    module: str,
    text_lines: list[str],
    lines: int,
    index: CanonicalIndex,
    revisions: list[Revision],
) -> FileDrift:
    """Infer the canonical base a locally edited file forked from.

    No exact blob matched, so the content never existed in canonical. Find the
    canonical revision it most resembles: if that is HEAD the consumer edited
    current canonical (`ahead`); if it is older the consumer edited a stale
    canonical (`diverged`).
    """
    if not revisions:
        return FileDrift(
            module=module,
            direction=UNRESOLVED,
            lines=lines,
            note="module exists at canonical HEAD but has no recorded history to compare against",
        )

    best: tuple[float, int, Revision] | None = None
    for position, revision in enumerate(revisions):
        ratio = difflib.SequenceMatcher(
            None, text_lines, index.read_blob_lines(revision.blob)
        ).quick_ratio()
        if best is None or ratio > best[0]:
            best = (ratio, position, revision)
    assert best is not None
    similarity, position, revision = best

    if similarity < MIN_BASE_SIMILARITY:
        return FileDrift(
            module=module,
            direction=UNRESOLVED,
            lines=lines,
            base_commit=revision.commit,
            base_date=revision.date,
            similarity=similarity,
            note=(
                "no canonical revision resembles this file "
                f"(best {similarity:.0%} < {MIN_BASE_SIMILARITY:.0%}); base cannot be inferred"
            ),
        )

    if position == 0:
        return FileDrift(
            module=module,
            direction=AHEAD,
            lines=lines,
            revisions_behind=0,
            base_commit=revision.commit,
            base_date=revision.date,
            similarity=similarity,
            note="local edits on top of current canonical",
        )

    return FileDrift(
        module=module,
        direction=DIVERGED,
        lines=lines,
        revisions_behind=position,
        base_commit=revision.commit,
        base_date=revision.date,
        similarity=similarity,
        note="local edits on top of a stale canonical revision",
    )


# ---------------------------------------------------------------------------
# consumer discovery
# ---------------------------------------------------------------------------


def _iter_vendored_dirs(scan_root: Path, max_depth: int):
    """Yield `enforced_planning/` directories at most `max_depth` below root."""
    if not scan_root.is_dir():
        return
    frontier = [(scan_root, 0)]
    while frontier:
        current, depth = frontier.pop()
        if depth >= max_depth:
            continue
        try:
            children = sorted(current.iterdir())
        except (PermissionError, OSError):
            continue
        for child in children:
            if not child.is_dir() or child.is_symlink():
                continue
            if child.name in SKIP_DIR_NAMES or child.name.endswith("-mega"):
                continue
            if child.name == PACKAGE_DIR:
                yield child
                continue
            frontier.append((child, depth + 1))


def _origin_url(repo_root: Path) -> str | None:
    try:
        return _git(repo_root, "remote", "get-url", "origin").strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def _object_store(repo_root: Path) -> str | None:
    """Realpath of the repo's shared object store.

    Linked worktrees share this with their main checkout, so it identifies the
    whole checkout family in one value. A separately cloned copy of the same
    remote has its own store and is therefore *not* matched here -- which is the
    point: that is a duplicate checkout, not the same checkout.
    """
    try:
        raw = _git(repo_root, "rev-parse", "--git-common-dir").strip()
    except (subprocess.CalledProcessError, OSError):
        return None
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = repo_root / path
    return os.path.realpath(path)


def discover_consumers(
    scan_roots: list[Path],
    canonical_root: Path,
    max_depth: int = DEFAULT_SCAN_DEPTH,
) -> tuple[list[Path], list[Path]]:
    """Find repos carrying a vendored tree.

    Returns `(consumers, duplicate_checkouts)`. A directory that is another
    clone of enforced-planning itself is not a consumer -- it is a duplicate
    source checkout, which is its own problem and is reported separately.
    """
    canonical_real = Path(os.path.realpath(canonical_root))
    canonical_origin = _origin_url(canonical_root)
    canonical_store = _object_store(canonical_root)

    consumers: list[Path] = []
    duplicates: list[Path] = []
    seen: set[Path] = set()

    for scan_root in scan_roots:
        for vendored in _iter_vendored_dirs(scan_root, max_depth):
            repo_root = Path(os.path.realpath(vendored.parent))
            if repo_root in seen:
                continue
            seen.add(repo_root)
            if repo_root == canonical_real:
                continue
            if canonical_store is not None and _object_store(repo_root) == canonical_store:
                # The canonical checkout itself, or one of its linked worktrees.
                continue
            if canonical_origin is not None and _origin_url(repo_root) == canonical_origin:
                duplicates.append(repo_root)
                continue
            consumers.append(repo_root)

    return sorted(consumers), sorted(duplicates)


def load_project_identity(graph_path: Path) -> dict[str, str]:
    """Map filesystem path -> canonical project id from PROJECT_GRAPH.json.

    Records carry both a `path` and, for relocated repos, a
    `workspace_home`/`workspace_slug` pair naming where the repo now lives.
    Both are indexed because consumers are found at either location.
    """
    if not graph_path.is_file():
        return {}
    try:
        records = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(records, list):
        return {}

    homes = {"code-active": "/home/brian/code/active", "projects": "/home/brian/projects"}
    identity: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        project_id = record.get("id")
        if not isinstance(project_id, str):
            continue
        candidates: list[str] = []
        path = record.get("path")
        if isinstance(path, str) and path:
            candidates.append(path)
        home = homes.get(str(record.get("workspace_home") or ""))
        slug = record.get("workspace_slug")
        if home and isinstance(slug, str) and slug:
            candidates.append(f"{home}/{slug}")
        for candidate in candidates:
            identity.setdefault(os.path.realpath(candidate), project_id)
    return identity


def resolve_project_id(
    repo_root: Path, identity: dict[str, str]
) -> tuple[str | None, str]:
    """Resolve a consumer to a project id, reporting how it was resolved."""
    exact = identity.get(str(repo_root))
    if exact is not None:
        return exact, "path"
    for declared_path, project_id in identity.items():
        if Path(declared_path).name == repo_root.name:
            return project_id, "name"
    return None, "unresolved"


# ---------------------------------------------------------------------------
# per-consumer analysis
# ---------------------------------------------------------------------------


@dataclass
class ConsumerDrift:
    """Aggregate vendored-tree verdict for one consumer repo."""

    path: str
    project_id: str | None
    id_source: str
    declared_path_match: bool
    modules: int = 0
    lines: int = 0
    identical: int = 0
    missing: int = 0
    counts: Counter = field(default_factory=Counter)
    files: list[FileDrift] = field(default_factory=list)
    missing_modules: list[str] = field(default_factory=list)

    @property
    def differing(self) -> int:
        return sum(self.counts[direction] for direction in DRIFT_DIRECTIONS)

    @property
    def extra(self) -> int:
        return self.counts[LOCAL_ONLY] + self.counts[REMOVED_UPSTREAM]

    @property
    def drifted(self) -> bool:
        """True when vendored content disagrees with canonical.

        Deliberately excludes `missing`: a consumer that vendored a subset of
        the package has a coverage gap, not a divergence, and conflating the two
        makes every consumer look drifted and hides which ones actually are.
        """
        return self.differing > 0 or self.extra > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "project_id": self.project_id,
            "project_id_source": self.id_source,
            "declared_path_match": self.declared_path_match,
            "modules": self.modules,
            "lines": self.lines,
            "identical": self.identical,
            "differing": self.differing,
            "behind": self.counts[BEHIND],
            "ahead": self.counts[AHEAD],
            "diverged": self.counts[DIVERGED],
            "unresolved": self.counts[UNRESOLVED],
            "local_only": self.counts[LOCAL_ONLY],
            "removed_upstream": self.counts[REMOVED_UPSTREAM],
            "missing": self.missing,
            "missing_modules": self.missing_modules,
            "drifted": self.drifted,
            "files": [drift.to_dict() for drift in self.files if drift.direction != IDENTICAL],
        }


def _vendored_files(vendored_root: Path) -> list[Path]:
    found: list[Path] = []
    for path in sorted(vendored_root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.name.endswith(SKIP_SUFFIXES):
            continue
        found.append(path)
    return found


def analyze_consumer(
    repo_root: Path,
    index: CanonicalIndex,
    identity: dict[str, str],
) -> ConsumerDrift:
    """Classify every file in one consumer's vendored tree."""
    project_id, id_source = resolve_project_id(repo_root, identity)
    declared = identity.get(str(repo_root)) is not None
    report = ConsumerDrift(
        path=str(repo_root),
        project_id=project_id,
        id_source=id_source,
        declared_path_match=declared,
    )

    vendored_root = repo_root / PACKAGE_DIR
    present: set[str] = set()
    for path in _vendored_files(vendored_root):
        module = f"{PACKAGE_DIR}/{path.relative_to(vendored_root).as_posix()}"
        present.add(module)
        drift = classify_file(module, path.read_bytes(), index)
        report.modules += 1
        report.lines += drift.lines
        report.counts[drift.direction] += 1
        if drift.direction == IDENTICAL:
            report.identical += 1
        else:
            report.files.append(drift)

    report.missing_modules = sorted(set(index.head_blobs) - present)
    report.missing = len(report.missing_modules)
    return report


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def _short(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path


_COLUMNS = (
    ("MOD", lambda c: c.modules),
    ("SAME", lambda c: c.identical),
    ("BEHIND", lambda c: c.counts[BEHIND]),
    ("AHEAD", lambda c: c.counts[AHEAD]),
    ("DIVERGED", lambda c: c.counts[DIVERGED]),
    ("UNKNOWN", lambda c: c.counts[UNRESOLVED]),
    ("EXTRA", lambda c: c.extra),
    ("MISSING", lambda c: c.missing),
    ("LINES", lambda c: c.lines),
)


def render_human(report: dict[str, object], consumers: list[ConsumerDrift], details: bool) -> str:
    canonical = report["canonical"]
    totals = report["totals"]
    out: list[str] = []

    out.append(
        f"Vendored governance drift: {totals['consumers']} consumers carry a copy of "
        f"{PACKAGE_DIR}/, 0 install the package"
    )
    out.append(
        f"Canonical: {_short(str(canonical['path']))} @ {str(canonical['revision'])[:8]} "
        f"({canonical['modules']} modules, {canonical['lines']:,} lines)"
    )
    out.append("")

    name_width = max([len(_short(c.path)) for c in consumers] + [len("CONSUMER")])
    id_width = max([len(c.project_id or "-") for c in consumers] + [len("PROJECT")])
    header = f"{'CONSUMER':<{name_width}}  {'PROJECT':<{id_width}}"
    for label, _ in _COLUMNS:
        header += f"  {label:>{max(len(label), 7)}}"
    out.append(header)
    out.append("-" * len(header))

    for consumer in consumers:
        row = f"{_short(consumer.path):<{name_width}}  {consumer.project_id or '-':<{id_width}}"
        for label, getter in _COLUMNS:
            value = getter(consumer)
            text = f"{value:,}" if label == "LINES" else str(value)
            row += f"  {text:>{max(len(label), 7)}}"
        out.append(row)

    out.append("-" * len(header))
    total_row = f"{'TOTAL':<{name_width}}  {'':<{id_width}}"
    for label, getter in _COLUMNS:
        value = sum(getter(c) for c in consumers)
        text = f"{value:,}" if label == "LINES" else str(value)
        total_row += f"  {text:>{max(len(label), 7)}}"
    out.append(total_row)
    out.append("")

    out.append(
        f"{totals['drifted_consumers']} of {totals['consumers']} consumers have drifted content. "
        f"{totals['lines']:,} vendored lines across the fleet, from a "
        f"{canonical['lines']:,}-line canonical package."
    )
    out.append(
        f"{totals['missing']} canonical module copies are missing across the fleet "
        "(subset vendoring, counted separately from drift)."
    )

    duplicates = report.get("duplicate_canonical_checkouts") or []
    if duplicates:
        out.append("")
        out.append("Duplicate canonical checkouts (not consumers; a repo bootstrapped from")
        out.append("one of these ships without recent canonical fixes):")
        for duplicate in duplicates:
            out.append(f"  {_short(str(duplicate))}")

    if details:
        drifted = [c for c in consumers if c.files]
        if drifted:
            out.append("")
            out.append("Per-module drift direction")
            out.append("=" * len(header))
        for consumer in drifted:
            out.append("")
            out.append(f"{_short(consumer.path)}  ({consumer.project_id or 'unresolved project'})")
            for drift in sorted(consumer.files, key=lambda d: (d.direction, d.module)):
                detail = ""
                if drift.direction in (BEHIND, DIVERGED):
                    detail = f"{drift.revisions_behind} rev behind, base {drift.base_commit[:8]} {drift.base_date}"
                elif drift.direction == AHEAD:
                    detail = f"local edits on HEAD ({drift.similarity:.0%} similar)"
                elif drift.direction == UNRESOLVED:
                    detail = drift.note
                elif drift.direction == REMOVED_UPSTREAM:
                    detail = "deleted upstream"
                elif drift.direction == LOCAL_ONLY:
                    detail = "no canonical counterpart"
                module = drift.module.split("/", 1)[1]
                out.append(f"  {drift.direction:<16} {module:<44} {detail}")

    out.append("")
    out.append(
        "behind = stale copy of an older canonical revision, safe to resync. "
        "ahead = local edits on current canonical."
    )
    out.append(
        "diverged = local edits on a stale revision, needs a merge. "
        "unknown = base could not be inferred from canonical history."
    )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------


def build_report(
    canonical_root: Path,
    scan_roots: list[Path],
    graph_path: Path,
    max_depth: int = DEFAULT_SCAN_DEPTH,
) -> tuple[dict[str, object], list[ConsumerDrift]]:
    index = CanonicalIndex(canonical_root)
    try:
        consumer_roots, duplicates = discover_consumers(scan_roots, canonical_root, max_depth)
        identity = load_project_identity(graph_path)
        consumers = [analyze_consumer(root, index, identity) for root in consumer_roots]
        canonical_lines = index.line_count()
        canonical_revision = index.revision
        canonical_modules = index.module_count
    finally:
        index.close()

    totals = {
        "consumers": len(consumers),
        "drifted_consumers": sum(1 for c in consumers if c.drifted),
        "modules": sum(c.modules for c in consumers),
        "lines": sum(c.lines for c in consumers),
        "identical": sum(c.identical for c in consumers),
        "differing": sum(c.differing for c in consumers),
        "behind": sum(c.counts[BEHIND] for c in consumers),
        "ahead": sum(c.counts[AHEAD] for c in consumers),
        "diverged": sum(c.counts[DIVERGED] for c in consumers),
        "unresolved": sum(c.counts[UNRESOLVED] for c in consumers),
        "local_only": sum(c.counts[LOCAL_ONLY] for c in consumers),
        "removed_upstream": sum(c.counts[REMOVED_UPSTREAM] for c in consumers),
        "missing": sum(c.missing for c in consumers),
    }

    report: dict[str, object] = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "canonical": {
            "path": str(Path(os.path.realpath(canonical_root))),
            "revision": canonical_revision,
            "modules": canonical_modules,
            "lines": canonical_lines,
        },
        "scan_roots": [str(root) for root in scan_roots],
        "scan_depth": max_depth,
        "project_graph": str(graph_path),
        "duplicate_canonical_checkouts": [str(path) for path in duplicates],
        "totals": totals,
        "consumers": [c.to_dict() for c in consumers],
    }
    return report, consumers


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--canonical-root",
        default=str(ROOT),
        help="enforced-planning source checkout to compare against (default: this repo).",
    )
    parser.add_argument(
        "--scan-root",
        action="append",
        dest="scan_roots",
        help=f"Directory to scan for consumers; repeatable (default: {', '.join(DEFAULT_SCAN_ROOTS)}).",
    )
    parser.add_argument(
        "--scan-depth",
        type=int,
        default=DEFAULT_SCAN_DEPTH,
        help="How many levels below each scan root to look for a vendored tree.",
    )
    parser.add_argument(
        "--project-graph",
        default=DEFAULT_PROJECT_GRAPH,
        help="PROJECT_GRAPH.json used to resolve consumer paths to project ids.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="Summary table only; omit the per-module drift listing.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    scan_roots = [Path(root) for root in (args.scan_roots or list(DEFAULT_SCAN_ROOTS))]
    report, consumers = build_report(
        canonical_root=Path(args.canonical_root).resolve(),
        scan_roots=scan_roots,
        graph_path=Path(args.project_graph),
        max_depth=args.scan_depth,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    elif not consumers:
        print("No consumers carrying a vendored enforced_planning/ tree were found.")
        print(f"Scanned: {', '.join(str(root) for root in scan_roots)}")
    else:
        print(render_human(report, consumers, details=not args.no_details))
    # Always 0: this reports drift, it does not gate on it.
    return 0


if __name__ == "__main__":
    sys.exit(main())
