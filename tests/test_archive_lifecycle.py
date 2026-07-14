"""Verify report-only document lifecycle coverage and archive blockers."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from enforced_planning.archive_lifecycle import ArchiveLifecycleError
from enforced_planning.archive_lifecycle import build_archive_lifecycle_report


def _write(path: Path, content: str) -> None:
    """Create one exact source artifact for a real Git-backed fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    """Create a tracked documentation corpus with terminal and active documents."""

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _write(repo / "docs/current.md", "# Current authority\n\n**Status:** Active\n\n## Purpose\n\nOwn current meaning.\n")
    _write(repo / "docs/old.md", "# Old plan\n\n**Status:** Complete\n\n## Outcome\n\nRecord completed work.\n")
    _write(repo / "docs/ambiguous.md", "# Ambiguous history\n\n**Status:** Superseded\n\n## Summary\n\nRecord history.\n")
    _write(repo / "docs/unowned.md", "# Unowned\n\n## Purpose\n\nExpose declaration debt.\n")
    _write(repo / "src/service.py", '"""Serve the current authority."""\n')
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    return repo


def _document(path: str, *, role: str = "historical_evidence") -> dict[str, object]:
    """Return one exact-path document declaration with a purpose-bearing anchor."""

    return {
        "path": path,
        "role": role,
        "justification": {
            "anchored_to": "docs/current.md",
            "reason": "The current authority explains why this history is retained.",
        },
        "lifecycle_source": "document_status",
    }


def test_lineage_only_reaches_semantic_review_without_claiming_eligibility(tmp_path: Path) -> None:
    """Clear mechanics still require a semantic promotion and disposition judgment."""

    repo = _repo(tmp_path)
    relationships = {
        "documents": [_document("docs/old.md")],
        "relationships": [
            {
                "source": "docs/current.md",
                "target": "docs/old.md",
                "relation": "supersedes",
                "reason": "The current authority preserves the historical lineage.",
                "maintenance": "lineage_only",
                "archive_effect": "lineage_only",
            }
        ],
    }

    report = build_archive_lifecycle_report(repo, relationships, candidates=("docs/old.md",))
    candidate = report.candidates[0]

    assert candidate.lifecycle == "completed"
    assert candidate.readiness == "semantic_review_required"
    assert candidate.blockers == ()
    assert candidate.declarations[0].anchored_to == "docs/current.md"
    assert candidate.declarations[0].reason.startswith("The current authority")
    assert candidate.edge_impacts[0].archive_effect == "lineage_only"
    assert candidate.edge_impacts[0].direction == "incoming"
    assert "eligible" not in report.to_json()
    assert "reviewed_revision" not in report.to_json()
    assert "content_hash" not in report.to_json()


@pytest.mark.parametrize(
    ("archive_effect", "blocker_code"),
    [
        ("blocks_archive", "archive-edge-blocks"),
        ("redirect_before_archive", "archive-redirect-required"),
        ("review_required", "archive-effect-review-required"),
    ],
)
def test_edge_effects_produce_distinct_mechanical_blockers(
    tmp_path: Path,
    archive_effect: str,
    blocker_code: str,
) -> None:
    """Operational, navigation, and ambiguous edges cannot collapse together."""

    repo = _repo(tmp_path)
    relationships = {
        "documents": [_document("docs/old.md")],
        "relationships": [
            {
                "source": "docs/current.md",
                "target": "docs/old.md",
                "relation": "updates",
                "reason": "The current document refers to the historical document.",
                "archive_effect": archive_effect,
            }
        ],
    }

    candidate = build_archive_lifecycle_report(
        repo,
        relationships,
        candidates=("docs/old.md",),
    ).candidates[0]

    assert candidate.readiness == "blocked"
    assert [blocker.code for blocker in candidate.blockers] == [blocker_code]


def test_missing_effect_and_undeclared_documents_remain_visible(tmp_path: Path) -> None:
    """Legacy ambiguity and missing ownership are explicit negative controls."""

    repo = _repo(tmp_path)
    relationships = {
        "documents": [_document("docs/ambiguous.md")],
        "relationships": [
            {
                "source": "docs/current.md",
                "target": "docs/ambiguous.md",
                "relation": "updates",
                "reason": "The legacy edge has not been semantically classified.",
            }
        ],
    }

    report = build_archive_lifecycle_report(repo, relationships)
    by_path = {candidate.path: candidate for candidate in report.candidates}

    assert report.tracked_document_count == 4
    assert report.declared_document_count == 1
    assert report.undeclared_documents == (
        "docs/current.md",
        "docs/old.md",
        "docs/unowned.md",
    )
    assert [blocker.code for blocker in by_path["docs/ambiguous.md"].blockers] == [
        "archive-effect-review-required"
    ]
    assert "document-undeclared" in {blocker.code for blocker in by_path["docs/unowned.md"].blockers}


def test_active_lifecycle_and_unresolved_justification_anchor_block(tmp_path: Path) -> None:
    """Declared purpose cannot override active use or point to a missing authority."""

    repo = _repo(tmp_path)
    declaration = _document("docs/current.md", role="authority")
    declaration["justification"] = {
        "anchored_to": "docs/missing.md",
        "reason": "This deliberately unresolved anchor is a negative control.",
    }

    candidate = build_archive_lifecycle_report(
        repo,
        {"documents": [declaration]},
        candidates=("docs/current.md",),
    ).candidates[0]

    assert candidate.readiness == "blocked"
    assert {blocker.code for blocker in candidate.blockers} == {
        "lifecycle-not-terminal",
        "justification-anchor-unresolved",
    }


def test_report_is_byte_deterministic_and_workspace_neutral(tmp_path: Path) -> None:
    """Repeated reports contain no path, time, or ordering volatility."""

    repo = _repo(tmp_path)
    relationships = {"documents": [_document("docs/old.md")]}

    first = build_archive_lifecycle_report(repo, relationships).to_json(pretty=True)
    second = build_archive_lifecycle_report(repo, relationships).to_json(pretty=True)

    assert first == second
    assert str(repo) not in first
    payload = json.loads(first)
    assert "generated_at" not in payload


def test_cli_emits_the_same_report_only_boundary(tmp_path: Path) -> None:
    """The agent-drivable wrapper exposes candidate reporting without approval state."""

    repo = _repo(tmp_path)
    _write(
        repo / "scripts/relationships.yaml",
        """documents:
  - path: docs/old.md
    role: historical_evidence
    justification:
      anchored_to: docs/current.md
      reason: The current authority explains why this history is retained.
    lifecycle_source: document_status
""",
    )
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    script = Path(__file__).parents[1] / "scripts/archive_lifecycle.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo),
            "--candidate",
            "docs/old.md",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["candidates"][0]["readiness"] == "semantic_review_required"
    assert "eligible" not in result.stdout


def test_malformed_document_declarations_fail_loudly(tmp_path: Path) -> None:
    """The coverage graph cannot accept vague roles or empty justification."""

    repo = _repo(tmp_path)
    malformed = {
        "documents": [
            {
                "path": "docs/old.md",
                "role": "maybe_useful",
                "justification": {"anchored_to": "docs/current.md", "reason": ""},
            }
        ]
    }

    with pytest.raises(ArchiveLifecycleError, match="unsupported role"):
        build_archive_lifecycle_report(repo, malformed)

    self_anchored = _document("docs/old.md")
    self_anchored["justification"] = {
        "anchored_to": "docs/old.md",
        "reason": "A circular declaration cannot establish purpose.",
    }
    with pytest.raises(ArchiveLifecycleError, match="cannot point to itself"):
        build_archive_lifecycle_report(repo, {"documents": [self_anchored]})
