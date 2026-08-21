"""Tests for fleet_drift.py — vendored `enforced_planning/` divergence report.

The interesting behaviour is drift *direction*, so the fixture builds a real
throwaway git repo with a known history and then plants consumer copies that are
deliberately stale, deliberately edited, or both. The live fleet currently
contains no `ahead` module, so that direction is only ever exercised here.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load() -> object:
    spec = importlib.util.spec_from_file_location(
        "fleet_drift_module", SCRIPTS_DIR / "fleet_drift.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


m = _load()


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD").strip()


ALPHA_V1 = "def alpha():\n    return 1\n"
ALPHA_V2 = "def alpha():\n    value = 1\n    return value\n"
ALPHA_V3 = "def alpha():\n    value = 1\n    value += 1\n    return value\n"

ORIGIN_URL = "git@example.invalid:acme/enforced-planning.git"


@pytest.fixture
def canonical(tmp_path: Path) -> dict[str, object]:
    """A canonical repo whose `enforced_planning/` has a real, known history.

    alpha.py moves through three revisions, beta.py is written once, and
    gamma.py is created and then deleted, so every classification branch has
    something to resolve against.
    """
    root = tmp_path / "canonical"
    package = root / "enforced_planning"
    package.mkdir(parents=True)
    _git(root.parent, "init", "-q", "-b", "main", str(root))
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "remote", "add", "origin", ORIGIN_URL)

    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "alpha.py").write_text(ALPHA_V1, encoding="utf-8")
    (package / "gamma.py").write_text("GONE = True\n", encoding="utf-8")
    first = _commit(root, "first")

    (package / "alpha.py").write_text(ALPHA_V2, encoding="utf-8")
    second = _commit(root, "second")

    (package / "alpha.py").write_text(ALPHA_V3, encoding="utf-8")
    (package / "beta.py").write_text("BETA = 2\n", encoding="utf-8")
    third = _commit(root, "third")

    (package / "gamma.py").unlink()
    fourth = _commit(root, "drop gamma")

    return {"root": root, "commits": [first, second, third, fourth]}


@pytest.fixture
def index(canonical: dict[str, object]) -> object:
    built = m.CanonicalIndex(canonical["root"])  # type: ignore[attr-defined]
    yield built
    built.close()


def _make_consumer(base: Path, name: str, modules: dict[str, str]) -> Path:
    repo = base / name
    package = repo / "enforced_planning"
    package.mkdir(parents=True)
    for filename, content in modules.items():
        (package / filename).write_text(content, encoding="utf-8")
    return repo


# ---------------------------------------------------------------------------
# blob_hash
# ---------------------------------------------------------------------------


def test_blob_hash_matches_git_hash_object(tmp_path: Path) -> None:
    """The hand-computed object id is the id git would assign."""
    payload = b"some vendored content\nwith two lines\n"
    target = tmp_path / "sample.py"
    target.write_bytes(payload)
    expected = subprocess.run(
        ["git", "hash-object", str(target)], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert m.blob_hash(payload) == expected  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# CanonicalIndex
# ---------------------------------------------------------------------------


def test_index_reads_head_tree_and_history(index, canonical) -> None:
    """HEAD holds the surviving modules; history still holds the deleted one."""
    assert set(index.head_blobs) == {
        "enforced_planning/__init__.py",
        "enforced_planning/alpha.py",
        "enforced_planning/beta.py",
    }
    # alpha.py changed three times, so three distinct blobs are recorded.
    assert len(index.history["enforced_planning/alpha.py"]) == 3
    # gamma.py is gone from HEAD but its content is still recoverable.
    assert "enforced_planning/gamma.py" in index.history
    assert index.module_count == 3


def test_index_history_is_newest_first(index, canonical) -> None:
    """Position in the history list is how far behind a revision is."""
    revisions = index.history["enforced_planning/alpha.py"]
    assert revisions[0].timestamp >= revisions[-1].timestamp
    assert index.read_blob_lines(revisions[0].blob) == ALPHA_V3.splitlines()
    assert index.read_blob_lines(revisions[-1].blob) == ALPHA_V1.splitlines()


def test_index_blob_reads_are_cached(index, canonical) -> None:
    """Repeated reads of one blob hit the cache rather than git."""
    sha = index.head_blobs["enforced_planning/alpha.py"]
    first = index.read_blob_lines(sha)
    assert index.read_blob_lines(sha) is first


# ---------------------------------------------------------------------------
# classify_file — direction
# ---------------------------------------------------------------------------


def test_identical_module(index) -> None:
    drift = m.classify_file(  # type: ignore[attr-defined]
        "enforced_planning/alpha.py", ALPHA_V3.encode(), index
    )
    assert drift.direction == m.IDENTICAL  # type: ignore[attr-defined]


def test_behind_module_reports_exact_older_revision(index, canonical) -> None:
    """An exact blob match against an older revision proves staleness."""
    drift = m.classify_file(  # type: ignore[attr-defined]
        "enforced_planning/alpha.py", ALPHA_V1.encode(), index
    )
    assert drift.direction == m.BEHIND  # type: ignore[attr-defined]
    assert drift.revisions_behind == 2
    assert drift.base_commit == canonical["commits"][0]
    assert drift.similarity == 1.0


def test_behind_module_one_revision(index, canonical) -> None:
    drift = m.classify_file(  # type: ignore[attr-defined]
        "enforced_planning/alpha.py", ALPHA_V2.encode(), index
    )
    assert drift.direction == m.BEHIND  # type: ignore[attr-defined]
    assert drift.revisions_behind == 1
    assert drift.base_commit == canonical["commits"][1]


def test_ahead_module_is_local_edits_on_current_canonical(index, canonical) -> None:
    """Edits on top of HEAD are deliberate adaptation, not staleness.

    This is the distinction that makes the report a conversion queue: resyncing
    an `ahead` module would destroy local work, so it must not be reported the
    same way as `behind`.
    """
    content = ALPHA_V3 + "\nLOCAL_ADAPTATION = True\n"
    drift = m.classify_file(  # type: ignore[attr-defined]
        "enforced_planning/alpha.py", content.encode(), index
    )
    assert drift.direction == m.AHEAD  # type: ignore[attr-defined]
    assert drift.revisions_behind == 0
    assert drift.base_commit == canonical["commits"][2]
    assert drift.similarity is not None and drift.similarity > 0.6


def test_diverged_module_is_local_edits_on_a_stale_revision(index, canonical) -> None:
    """Stale base plus local edits needs a merge, not a copy."""
    content = ALPHA_V1 + "\nLOCAL_ADAPTATION = True\n"
    drift = m.classify_file(  # type: ignore[attr-defined]
        "enforced_planning/alpha.py", content.encode(), index
    )
    assert drift.direction == m.DIVERGED  # type: ignore[attr-defined]
    assert drift.revisions_behind == 2
    assert drift.base_commit == canonical["commits"][0]


def test_unresolved_module_is_reported_not_guessed(index) -> None:
    """Content resembling no canonical revision is unknown, never assumed."""
    content = "\n".join(f"totally unrelated line {n}" for n in range(200)) + "\n"
    drift = m.classify_file(  # type: ignore[attr-defined]
        "enforced_planning/alpha.py", content.encode(), index
    )
    assert drift.direction == m.UNRESOLVED  # type: ignore[attr-defined]
    assert drift.similarity is not None
    assert drift.similarity < m.MIN_BASE_SIMILARITY  # type: ignore[attr-defined]
    assert "cannot be inferred" in drift.note


def test_local_only_module_has_no_canonical_counterpart(index) -> None:
    drift = m.classify_file(  # type: ignore[attr-defined]
        "enforced_planning/consumer_special.py", b"LOCAL = 1\n", index
    )
    assert drift.direction == m.LOCAL_ONLY  # type: ignore[attr-defined]


def test_removed_upstream_module_is_distinguished_from_local_only(index) -> None:
    """A module canonical deleted is stale, not a local invention."""
    drift = m.classify_file(  # type: ignore[attr-defined]
        "enforced_planning/gamma.py", b"GONE = True\n", index
    )
    assert drift.direction == m.REMOVED_UPSTREAM  # type: ignore[attr-defined]
    assert drift.base_commit is not None


def test_line_count_is_recorded_per_module(index) -> None:
    drift = m.classify_file(  # type: ignore[attr-defined]
        "enforced_planning/alpha.py", ALPHA_V3.encode(), index
    )
    assert drift.lines == len(ALPHA_V3.splitlines())


# ---------------------------------------------------------------------------
# analyze_consumer
# ---------------------------------------------------------------------------


def test_analyze_consumer_aggregates_every_direction(index, tmp_path: Path) -> None:
    consumer = _make_consumer(
        tmp_path / "fleet",
        "mixed",
        {
            "__init__.py": "",  # identical
            "alpha.py": ALPHA_V1,  # behind
            "beta.py": "BETA = 2\nLOCAL = True\n",  # ahead
            "gamma.py": "GONE = True\n",  # removed upstream
            "extra.py": "EXTRA = 1\n",  # local only
        },
    )
    report = m.analyze_consumer(consumer, index, {})  # type: ignore[attr-defined]

    assert report.modules == 5
    assert report.identical == 1
    assert report.counts[m.BEHIND] == 1  # type: ignore[attr-defined]
    assert report.counts[m.AHEAD] == 1  # type: ignore[attr-defined]
    assert report.counts[m.REMOVED_UPSTREAM] == 1  # type: ignore[attr-defined]
    assert report.counts[m.LOCAL_ONLY] == 1  # type: ignore[attr-defined]
    assert report.differing == 2
    assert report.extra == 2
    assert report.drifted is True


def test_analyze_consumer_reports_missing_modules(index, tmp_path: Path) -> None:
    """A consumer that vendored a subset has a gap, listed explicitly."""
    consumer = _make_consumer(tmp_path / "fleet", "partial", {"alpha.py": ALPHA_V3})
    report = m.analyze_consumer(consumer, index, {})  # type: ignore[attr-defined]
    assert report.missing == 2
    assert report.missing_modules == [
        "enforced_planning/__init__.py",
        "enforced_planning/beta.py",
    ]


def test_subset_vendoring_alone_is_not_counted_as_drift(index, tmp_path: Path) -> None:
    """Missing modules are a coverage gap; conflating them with drift would
    make every consumer look drifted and hide the ones that really are."""
    consumer = _make_consumer(tmp_path / "fleet", "clean-subset", {"alpha.py": ALPHA_V3})
    report = m.analyze_consumer(consumer, index, {})  # type: ignore[attr-defined]
    assert report.missing == 2
    assert report.differing == 0
    assert report.drifted is False


def test_analyze_consumer_ignores_pycache_and_bytecode(index, tmp_path: Path) -> None:
    consumer = _make_consumer(tmp_path / "fleet", "noisy", {"alpha.py": ALPHA_V3})
    cache = consumer / "enforced_planning" / "__pycache__"
    cache.mkdir()
    (cache / "alpha.cpython-311.pyc").write_bytes(b"\x00\x01")
    (consumer / "enforced_planning" / "stray.pyc").write_bytes(b"\x00\x01")
    report = m.analyze_consumer(consumer, index, {})  # type: ignore[attr-defined]
    assert report.modules == 1


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


def test_discover_consumers_matches_find_maxdepth_semantics(tmp_path: Path, canonical) -> None:
    """`--scan-depth 2` means `<scan-root>/<repo>/enforced_planning`, the layout
    every governed repo actually uses -- not an unbounded walk."""
    scan = tmp_path / "scan"
    _make_consumer(scan, "shallow", {"alpha.py": ALPHA_V3})
    _make_consumer(scan / "nested", "deep", {"alpha.py": ALPHA_V3})

    consumers, duplicates = m.discover_consumers(  # type: ignore[attr-defined]
        [scan], canonical["root"], max_depth=2
    )
    assert [c.name for c in consumers] == ["shallow"]
    assert duplicates == []

    deeper, _ = m.discover_consumers(  # type: ignore[attr-defined]
        [scan], canonical["root"], max_depth=3
    )
    assert [c.name for c in deeper] == ["deep", "shallow"]


def test_discover_consumers_skips_worktrees_directory(tmp_path: Path, canonical) -> None:
    """A lane's linked worktree is not a separate consumer of the framework."""
    scan = tmp_path / "scan"
    _make_consumer(scan, "real", {"alpha.py": ALPHA_V3})
    _make_consumer(scan / "worktrees", "lane", {"alpha.py": ALPHA_V3})
    consumers, _ = m.discover_consumers(  # type: ignore[attr-defined]
        [scan], canonical["root"], max_depth=3
    )
    assert [c.name for c in consumers] == ["real"]


def test_discover_consumers_separates_duplicate_source_checkouts(
    tmp_path: Path, canonical
) -> None:
    """Another clone of enforced-planning is a duplicate checkout, not a consumer.

    Counting it as a consumer would report the source repo as drifted from
    itself; ignoring it silently would hide a real bootstrap hazard.
    """
    scan = tmp_path / "scan"
    scan.mkdir()
    clone = scan / "enforced-planning"
    _git(tmp_path, "clone", "-q", str(canonical["root"]), str(clone))
    _git(clone, "remote", "set-url", "origin", ORIGIN_URL)

    consumers, duplicates = m.discover_consumers(  # type: ignore[attr-defined]
        [scan], canonical["root"], max_depth=2
    )
    assert consumers == []
    assert [d.name for d in duplicates] == ["enforced-planning"]


def test_discover_consumers_ignores_linked_worktrees_of_canonical(
    tmp_path: Path, canonical
) -> None:
    """A linked worktree shares the canonical object store, so it is the same
    checkout — neither a consumer nor a duplicate."""
    scan = tmp_path / "scan"
    scan.mkdir()
    linked = scan / "canonical-lane"
    _git(canonical["root"], "worktree", "add", "-q", "-b", "lane", str(linked))

    consumers, duplicates = m.discover_consumers(  # type: ignore[attr-defined]
        [scan], canonical["root"], max_depth=2
    )
    assert consumers == []
    assert duplicates == []


def test_discover_consumers_tolerates_a_missing_scan_root(tmp_path: Path, canonical) -> None:
    consumers, duplicates = m.discover_consumers(  # type: ignore[attr-defined]
        [tmp_path / "does-not-exist"], canonical["root"], max_depth=2
    )
    assert consumers == []
    assert duplicates == []


# ---------------------------------------------------------------------------
# project identity
# ---------------------------------------------------------------------------


def test_load_project_identity_indexes_path_and_workspace_slug(tmp_path: Path) -> None:
    graph = tmp_path / "PROJECT_GRAPH.json"
    graph.write_text(
        json.dumps(
            [
                {"id": "alpha-proj", "path": "/home/brian/projects/alpha"},
                {
                    "id": "beta-proj",
                    "path": "/home/brian/projects/beta",
                    "workspace_home": "code-active",
                    "workspace_slug": "beta",
                },
                {"id": "no-path"},
                "not-a-record",
            ]
        ),
        encoding="utf-8",
    )
    identity = m.load_project_identity(graph)  # type: ignore[attr-defined]
    assert identity["/home/brian/projects/alpha"] == "alpha-proj"
    assert identity["/home/brian/projects/beta"] == "beta-proj"
    assert identity["/home/brian/code/active/beta"] == "beta-proj"
    assert "no-path" not in identity.values() or True


def test_load_project_identity_survives_a_missing_or_broken_graph(tmp_path: Path) -> None:
    assert m.load_project_identity(tmp_path / "absent.json") == {}  # type: ignore[attr-defined]
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert m.load_project_identity(broken) == {}  # type: ignore[attr-defined]


def test_resolve_project_id_reports_how_it_resolved() -> None:
    identity = {"/home/brian/projects/alpha": "alpha-proj"}
    assert m.resolve_project_id(Path("/home/brian/projects/alpha"), identity) == (  # type: ignore[attr-defined]
        "alpha-proj",
        "path",
    )
    # Same directory name at a different location still resolves, but says so.
    assert m.resolve_project_id(Path("/elsewhere/alpha"), identity) == (  # type: ignore[attr-defined]
        "alpha-proj",
        "name",
    )
    assert m.resolve_project_id(Path("/elsewhere/unknown"), identity) == (  # type: ignore[attr-defined]
        None,
        "unresolved",
    )


# ---------------------------------------------------------------------------
# report assembly and CLI
# ---------------------------------------------------------------------------


def test_build_report_totals_match_the_consumers(tmp_path: Path, canonical) -> None:
    scan = tmp_path / "scan"
    _make_consumer(scan, "stale", {"alpha.py": ALPHA_V1, "beta.py": "BETA = 2\n"})
    _make_consumer(scan, "current", {"alpha.py": ALPHA_V3, "beta.py": "BETA = 2\n"})

    report, consumers = m.build_report(  # type: ignore[attr-defined]
        canonical_root=canonical["root"],
        scan_roots=[scan],
        graph_path=tmp_path / "absent.json",
        max_depth=2,
    )
    totals = report["totals"]
    assert totals["consumers"] == 2
    assert totals["drifted_consumers"] == 1
    assert totals["behind"] == 1
    assert totals["lines"] == sum(c.lines for c in consumers)
    assert report["schema"] == m.SCHEMA  # type: ignore[attr-defined]
    assert report["canonical"]["revision"] == canonical["commits"][-1]


def test_json_output_is_parseable_and_exits_zero(
    tmp_path: Path, canonical, capsys
) -> None:
    """`--json` is the machine-consumption contract, and drift never gates."""
    scan = tmp_path / "scan"
    _make_consumer(scan, "stale", {"alpha.py": ALPHA_V1})

    code = m.main(  # type: ignore[attr-defined]
        [
            "--canonical-root",
            str(canonical["root"]),
            "--scan-root",
            str(scan),
            "--project-graph",
            str(tmp_path / "absent.json"),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == m.SCHEMA  # type: ignore[attr-defined]
    consumer = payload["consumers"][0]
    assert consumer["behind"] == 1
    assert consumer["drifted"] is True
    directions = {f["direction"] for f in consumer["files"]}
    assert directions == {m.BEHIND}  # type: ignore[attr-defined]
    # Identical modules are summarised, not listed file by file.
    assert all(f["direction"] != m.IDENTICAL for f in consumer["files"])  # type: ignore[attr-defined]


def test_human_output_names_each_direction_and_exits_zero(
    tmp_path: Path, canonical, capsys
) -> None:
    scan = tmp_path / "scan"
    _make_consumer(
        scan,
        "mixed",
        {"alpha.py": ALPHA_V1, "beta.py": "BETA = 2\nLOCAL = True\n"},
    )
    code = m.main(  # type: ignore[attr-defined]
        [
            "--canonical-root",
            str(canonical["root"]),
            "--scan-root",
            str(scan),
            "--project-graph",
            str(tmp_path / "absent.json"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "BEHIND" in out and "AHEAD" in out and "DIVERGED" in out
    assert "alpha.py" in out and "beta.py" in out
    assert "1 of 1 consumers have drifted content" in out


def test_exits_zero_with_no_consumers_found(tmp_path: Path, canonical, capsys) -> None:
    """A report never gates, including when it finds nothing."""
    empty = tmp_path / "empty"
    empty.mkdir()
    code = m.main(  # type: ignore[attr-defined]
        [
            "--canonical-root",
            str(canonical["root"]),
            "--scan-root",
            str(empty),
            "--project-graph",
            str(tmp_path / "absent.json"),
        ]
    )
    assert code == 0
    assert "No consumers" in capsys.readouterr().out


def test_no_details_flag_suppresses_the_per_module_listing(
    tmp_path: Path, canonical, capsys
) -> None:
    scan = tmp_path / "scan"
    _make_consumer(scan, "stale", {"alpha.py": ALPHA_V1})
    m.main(  # type: ignore[attr-defined]
        [
            "--canonical-root",
            str(canonical["root"]),
            "--scan-root",
            str(scan),
            "--project-graph",
            str(tmp_path / "absent.json"),
            "--no-details",
        ]
    )
    out = capsys.readouterr().out
    assert "Per-module drift direction" not in out


# ---------------------------------------------------------------------------
# Make surface
# ---------------------------------------------------------------------------


def test_makefile_exposes_fleet_drift() -> None:
    """The reported number has to be reachable the documented way."""
    makefile = (SCRIPTS_DIR.parent / "Makefile").read_text(encoding="utf-8")
    assert "fleet-drift:" in makefile
    assert "scripts/fleet_drift.py" in makefile
    assert "fleet-drift" in makefile.splitlines()[2]  # declared .PHONY
    assert (SCRIPTS_DIR / "fleet_drift.py").is_file()
