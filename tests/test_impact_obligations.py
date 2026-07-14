"""Verify deterministic post-edit reconciliation obligations and dispositions."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from enforced_planning.impact_obligations import ImpactObligationError
from enforced_planning.impact_obligations import ReconciliationDisposition
from enforced_planning.impact_obligations import build_impact_report
from enforced_planning.impact_obligations import changed_paths
from enforced_planning.impact_obligations import load_dispositions
from enforced_planning.impact_obligations import review_revision


def _write(path: Path, content: str) -> None:
    """Create one fixture source while preserving exact review text."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _repo(tmp_path: Path) -> tuple[Path, str]:
    """Create a committed graph fixture and return its exact review revision."""

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    _write(repo / "src/service.py", '"""Serve requests."""\n')
    _write(repo / "docs/requirements.md", "# Requirements\n\n## Purpose\n\nDefine request behavior.\n")
    _write(repo / "docs/current.md", "# Current State\n\n## Status\n\nRequests are served.\n")
    _write(repo / "docs/successor.md", "# Successor\n\n## Purpose\n\nCarry newer truth.\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True)
    revision = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, revision


def _relationships() -> dict[str, object]:
    """Declare one maintenance edge and one lineage-only edge."""

    return {
        "relationships": [
            {
                "source": "src/**/*.py",
                "target": "docs/requirements.md",
                "relation": "implements",
                "reason": "Source changes may alter the requirement implementation claim.",
                "maintenance": "reconcile",
            },
            {
                "source": "src/**/*.py",
                "target": "docs/current.md",
                "relation": "documents_current",
                "reason": "Current-state lineage helps readers but does not gate this slice.",
                "maintenance": "lineage_only",
            },
        ]
    }


def test_changed_source_creates_unresolved_obligation_with_stable_id(tmp_path: Path) -> None:
    """A changed source and unchanged linked requirement produce visible debt."""

    repo, revision = _repo(tmp_path)

    first = build_impact_report(repo, ("src/service.py",), _relationships(), revision=revision)
    second = build_impact_report(repo, ("src/service.py",), _relationships(), revision=revision)

    assert first.to_json() == second.to_json()
    assert first.obligation_count == 1
    assert first.unresolved_count == 1
    obligation = first.obligations[0]
    assert obligation.obligation_id.startswith("obl_")
    assert obligation.related_path == "docs/requirements.md"
    assert obligation.status == "unresolved"
    assert obligation.provenance == "relationships[0]"


def test_linked_artifact_changed_in_same_diff_satisfies_automatically(tmp_path: Path) -> None:
    """A coupled source and target update is mechanically visible as reconciled."""

    repo, revision = _repo(tmp_path)

    report = build_impact_report(
        repo,
        ("docs/requirements.md", "src/service.py"),
        _relationships(),
        revision=revision,
    )

    assert report.unresolved_count == 0
    assert report.obligations[0].status == "updated"
    assert report.obligations[0].disposition_reason == "Linked artifact changed in the same comparison."


def test_verified_unchanged_requires_exact_revision_and_reason(tmp_path: Path) -> None:
    """A review disposition is bound to the exact revision, not a floating claim."""

    repo, revision = _repo(tmp_path)
    initial = build_impact_report(repo, ("src/service.py",), _relationships(), revision=revision)
    obligation_id = initial.obligations[0].obligation_id
    disposition = ReconciliationDisposition(
        obligation_id=obligation_id,
        status="verified_unchanged",
        reason="The public behavior and requirement wording are unchanged.",
        reviewed_revision=revision,
    )

    report = build_impact_report(
        repo,
        ("src/service.py",),
        _relationships(),
        revision=revision,
        dispositions=(disposition,),
    )

    assert report.unresolved_count == 0
    assert report.obligations[0].status == "verified_unchanged"
    stale = ReconciliationDisposition(
        obligation_id=obligation_id,
        status="verified_unchanged",
        reason="Reviewed earlier.",
        reviewed_revision="0" * 40,
    )
    with pytest.raises(ImpactObligationError, match="expected current"):
        build_impact_report(
            repo,
            ("src/service.py",),
            _relationships(),
            revision=revision,
            dispositions=(stale,),
        )


def test_superseded_disposition_requires_tracked_successor(tmp_path: Path) -> None:
    """Supersession points to a real tracked authority rather than free text."""

    repo, revision = _repo(tmp_path)
    initial = build_impact_report(repo, ("src/service.py",), _relationships(), revision=revision)
    obligation_id = initial.obligations[0].obligation_id
    valid = ReconciliationDisposition(
        obligation_id=obligation_id,
        status="superseded",
        reason="The successor carries the current requirement claim.",
        reviewed_revision=revision,
        successor="docs/successor.md",
    )

    report = build_impact_report(
        repo,
        ("src/service.py",),
        _relationships(),
        revision=revision,
        dispositions=(valid,),
    )

    assert report.obligations[0].status == "superseded"
    assert report.obligations[0].successor == "docs/successor.md"
    invalid = ReconciliationDisposition(
        obligation_id=obligation_id,
        status="superseded",
        reason="Points nowhere.",
        reviewed_revision=revision,
        successor="docs/missing.md",
    )
    with pytest.raises(ImpactObligationError, match="successor is not Git-tracked"):
        build_impact_report(
            repo,
            ("src/service.py",),
            _relationships(),
            revision=revision,
            dispositions=(invalid,),
        )


def test_duplicate_disposition_ids_fail_loudly(tmp_path: Path) -> None:
    """Two reviews cannot compete silently for one deterministic obligation."""

    repo, revision = _repo(tmp_path)
    initial = build_impact_report(repo, ("src/service.py",), _relationships(), revision=revision)
    obligation_id = initial.obligations[0].obligation_id
    disposition = ReconciliationDisposition(
        obligation_id=obligation_id,
        status="verified_unchanged",
        reason="Reviewed once.",
        reviewed_revision=revision,
    )

    with pytest.raises(ImpactObligationError, match="duplicate obligation_id"):
        build_impact_report(
            repo,
            ("src/service.py",),
            _relationships(),
            revision=revision,
            dispositions=(disposition, disposition),
        )


def test_stale_disposition_id_not_in_change_set_fails_loudly(tmp_path: Path) -> None:
    """Old review records cannot disappear silently when the edge set changes."""

    repo, revision = _repo(tmp_path)
    stale = ReconciliationDisposition(
        obligation_id="obl_not_in_this_report",
        status="verified_unchanged",
        reason="This belongs to an older edge set.",
        reviewed_revision=revision,
    )

    with pytest.raises(ImpactObligationError, match="not present in this change set"):
        build_impact_report(
            repo,
            ("src/service.py",),
            _relationships(),
            revision=revision,
            dispositions=(stale,),
        )


def test_disposition_file_rejects_empty_or_unknown_resolutions(tmp_path: Path) -> None:
    """Timestamp-only and invented resolution states do not satisfy obligations."""

    empty = tmp_path / "empty.yaml"
    _write(
        empty,
        "dispositions:\n  - obligation_id: obl_x\n    status: verified_unchanged\n    reason: ''\n    reviewed_revision: abc\n",
    )
    with pytest.raises(ImpactObligationError, match="requires reason"):
        load_dispositions(empty)

    invented = tmp_path / "invented.yaml"
    _write(
        invented,
        "dispositions:\n  - obligation_id: obl_x\n    status: ignored\n    reason: no\n    reviewed_revision: abc\n",
    )
    with pytest.raises(ImpactObligationError, match="unsupported status"):
        load_dispositions(invented)


def test_changed_paths_reads_real_staged_git_diff(tmp_path: Path) -> None:
    """CLI change discovery uses a NUL-safe real Git comparison."""

    repo, _revision = _repo(tmp_path)
    _write(repo / "src/service.py", '"""Serve changed requests."""\n')
    _write(repo / "odd name.txt", "new\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)

    assert changed_paths(repo, base="HEAD", staged=True) == ("odd name.txt", "src/service.py")


def test_review_revision_changes_when_staged_diff_changes_without_new_head(tmp_path: Path) -> None:
    """A disposition cannot float across edits merely because HEAD is unchanged."""

    repo, head = _repo(tmp_path)
    _write(repo / "src/service.py", '"""Serve changed requests."""\n')
    subprocess.run(["git", "-C", str(repo), "add", "src/service.py"], check=True)
    first = review_revision(repo, base="HEAD", staged=True)
    _write(repo / "src/service.py", '"""Serve differently changed requests."""\n')
    subprocess.run(["git", "-C", str(repo), "add", "src/service.py"], check=True)
    second = review_revision(repo, base="HEAD", staged=True)

    assert first.startswith("review_")
    assert first != second
    assert subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == head


def test_unresolved_edge_target_counts_as_strict_debt(tmp_path: Path) -> None:
    """A dangling relationship selector cannot yield a falsely clean report."""

    repo, revision = _repo(tmp_path)
    relationships = {
        "relationships": [
            {
                "source": "src/service.py",
                "target": "docs/missing.md",
                "relation": "updates",
                "reason": "Expected authority is absent.",
                "maintenance": "reconcile",
            }
        ]
    }

    report = build_impact_report(repo, ("src/service.py",), relationships, revision=revision)

    assert report.obligation_count == 0
    assert report.unresolved_count == 1
    assert report.diagnostics == ("relationships[0]: no tracked target resolves from docs/missing.md",)


def test_deleted_linked_target_is_not_treated_as_updated(tmp_path: Path) -> None:
    """Deleting a coupled document requires disposition instead of auto-satisfying."""

    repo, revision = _repo(tmp_path)
    (repo / "docs/requirements.md").unlink()

    report = build_impact_report(
        repo,
        ("docs/requirements.md", "src/service.py"),
        _relationships(),
        revision=revision,
    )

    assert report.unresolved_count == 1
    assert report.obligations[0].status == "unresolved"
    assert "missing" in (report.obligations[0].disposition_reason or "")
