"""Verify report-only document lifecycle coverage and archive blockers."""

from __future__ import annotations

import json
import hashlib
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


def _archive_manifest(path: str, source: Path, repo: Path) -> dict[str, object]:
    """Bind one archive disposition to exact source bytes."""

    return {
        "schema_version": "archive-disposition-v1",
        "repo_root": str(repo),
        "candidates": [
            {
                "path": path,
                "expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "disposition": "superseded",
                "rationale": "Current authority replaced this historical document.",
                "replacement_or_recovery": "docs/current.md",
                "extracted_live_claims": "none",
                "relationships": [],
            }
        ],
    }


def _hash_path(path: Path) -> str:
    """Produce the executor-compatible hash used by directory fixtures."""

    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
        return digest.hexdigest()
    for child in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(child.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(child.read_bytes())
    return digest.hexdigest()


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


def test_hash_bound_archive_manifest_selects_candidate_without_editing_source(tmp_path: Path) -> None:
    """One transition manifest supplies candidate state without changing evidence."""

    repo = _repo(tmp_path)
    source = repo / "docs/unowned.md"
    manifest_path = repo / "archive-manifest.json"
    manifest_path.write_text(
        json.dumps(_archive_manifest("docs/unowned.md", source, repo)),
        encoding="utf-8",
    )

    report = build_archive_lifecycle_report(
        repo,
        {"documents": [_document("docs/unowned.md")]},
        archive_manifest=manifest_path,
    )

    candidate = report.candidates[0]
    assert candidate.lifecycle == "archive_candidate"
    assert candidate.readiness == "semantic_review_required"
    assert candidate.blockers == ()
    assert source.read_text(encoding="utf-8").startswith("# Unowned")


def test_directory_manifest_candidate_reviews_tracked_markdown_descendants(
    tmp_path: Path,
) -> None:
    """One mixed bundle stays byte-bound while lifecycle reviews its documents."""

    repo = _repo(tmp_path)
    _write(repo / "legacy/report.md", "# Historical report\n")
    _write(repo / "legacy/evidence.csv", "claim,source\none,old\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    payload = _archive_manifest("legacy", repo / "legacy/report.md", repo)
    payload["candidates"][0]["expected_source_sha256"] = _hash_path(repo / "legacy")  # type: ignore[index]
    manifest_path = repo / "archive-manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    report = build_archive_lifecycle_report(
        repo,
        {"documents": [_document("legacy/report.md")]},
        archive_manifest=manifest_path,
    )

    assert [candidate.path for candidate in report.candidates] == ["legacy/report.md"]
    assert report.candidates[0].lifecycle == "archive_candidate"
    assert report.candidates[0].readiness == "semantic_review_required"

    _write(repo / "legacy/evidence.csv", "claim,source\ntwo,changed\n")
    with pytest.raises(ArchiveLifecycleError, match="expected_source_sha256 mismatch"):
        build_archive_lifecycle_report(
            repo,
            {"documents": [_document("legacy/report.md")]},
            archive_manifest=manifest_path,
        )


def test_non_document_manifest_candidate_does_not_select_unrelated_documents(
    tmp_path: Path,
) -> None:
    """A data-only candidate is accepted without turning every document into a candidate."""

    repo = _repo(tmp_path)
    _write(repo / "legacy/data.csv", "claim,source\none,old\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    payload = _archive_manifest("legacy/data.csv", repo / "legacy/data.csv", repo)
    manifest_path = repo / "archive-manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    report = build_archive_lifecycle_report(
        repo,
        {"documents": [_document("docs/old.md")]},
        archive_manifest=manifest_path,
    )

    assert report.candidate_count == 0
    assert report.candidates == ()


def test_explicit_archive_candidate_status_is_terminal_for_active_use(tmp_path: Path) -> None:
    """A source-local candidate status reaches review without becoming a move approval."""

    repo = _repo(tmp_path)
    _write(repo / "docs/old.md", "# Old plan\n\n**Status:** Archive candidate\n")

    candidate = build_archive_lifecycle_report(
        repo,
        {"documents": [_document("docs/old.md")]},
        candidates=("docs/old.md",),
    ).candidates[0]

    assert candidate.lifecycle == "archive_candidate"
    assert candidate.readiness == "semantic_review_required"


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (
            lambda payload: payload["candidates"][0].__setitem__(
                "expected_source_sha256", "0" * 64
            ),
            "expected_source_sha256 mismatch",
        ),
        (
            lambda payload: payload["candidates"][0].__setitem__(
                "disposition", "active"
            ),
            "disposition must be",
        ),
        (
            lambda payload: payload.__setitem__("repo_root", "/wrong/repository"),
            "repo_root does not match",
        ),
    ],
)
def test_archive_manifest_rejects_unbound_or_invalid_candidate_state(
    tmp_path: Path,
    mutation: object,
    error: str,
) -> None:
    """The external interpretation cannot evade its exact evidence boundary."""

    repo = _repo(tmp_path)
    source = repo / "docs/unowned.md"
    payload = _archive_manifest("docs/unowned.md", source, repo)
    mutation(payload)  # type: ignore[operator]
    manifest_path = repo / "archive-manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ArchiveLifecycleError, match=error):
        build_archive_lifecycle_report(
            repo,
            {"documents": [_document("docs/unowned.md")]},
            archive_manifest=manifest_path,
        )


def test_archive_manifest_requires_candidate_list(tmp_path: Path) -> None:
    """Malformed transition records fail as lifecycle errors rather than key errors."""

    repo = _repo(tmp_path)
    manifest_path = repo / "archive-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "archive-disposition-v1",
                "repo_root": str(repo),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ArchiveLifecycleError, match="candidates must be"):
        build_archive_lifecycle_report(
            repo,
            {"documents": [_document("docs/unowned.md")]},
            archive_manifest=manifest_path,
        )


def test_archive_manifest_does_not_bypass_relationship_archive_blocks(tmp_path: Path) -> None:
    """The transition record cannot override the relationship graph's safeguards."""

    repo = _repo(tmp_path)
    source = repo / "docs/unowned.md"
    manifest_path = repo / "archive-manifest.json"
    manifest_path.write_text(
        json.dumps(_archive_manifest("docs/unowned.md", source, repo)),
        encoding="utf-8",
    )

    candidate = build_archive_lifecycle_report(
        repo,
        {
            "documents": [_document("docs/unowned.md")],
            "relationships": [
                {
                    "source": "docs/current.md",
                    "target": "docs/unowned.md",
                    "relation": "updates",
                    "reason": "The current document still depends on this source.",
                    "archive_effect": "blocks_archive",
                }
            ],
        },
        archive_manifest=manifest_path,
    ).candidates[0]

    assert candidate.lifecycle == "archive_candidate"
    assert candidate.readiness == "blocked"
    assert [blocker.code for blocker in candidate.blockers] == ["archive-edge-blocks"]


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


def test_cli_accepts_the_repo_relative_archive_manifest(tmp_path: Path) -> None:
    """The portable entry point consumes the ecosystem transition record."""

    repo = _repo(tmp_path)
    _write(
        repo / "scripts/relationships.yaml",
        """documents:
  - path: docs/unowned.md
    role: historical_evidence
    justification:
      anchored_to: docs/current.md
      reason: The current authority explains why this history is retained.
    lifecycle_source: document_status
""",
    )
    manifest = _archive_manifest("docs/unowned.md", repo / "docs/unowned.md", repo)
    _write(repo / "archive-manifest.json", json.dumps(manifest))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    script = Path(__file__).parents[1] / "scripts/archive_lifecycle.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo),
            "--archive-manifest",
            "archive-manifest.json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["candidates"][0]["lifecycle"] == "archive_candidate"
    assert payload["candidates"][0]["readiness"] == "semantic_review_required"


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
