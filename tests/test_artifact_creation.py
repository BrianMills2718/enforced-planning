"""Tests for observable artifact creation and directory policy enforcement."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

import yaml

from enforced_planning.artifact_creation import audit_repository
from enforced_planning.artifact_creation import build_report
from enforced_planning.artifact_creation import evaluate_paths
from enforced_planning.artifact_creation import _path_glob_matches
from enforced_planning.artifact_creation import record_feedback
from enforced_planning.artifact_creation import record_feedback_disposition


def _git(repo: Path, *args: str) -> None:
    """Run one fixture-local Git mutation."""

    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _write_yaml(path: Path, payload: object) -> None:
    """Write deterministic fixture YAML."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _repo(tmp_path: Path, *, mode: str = "enforce") -> Path:
    """Create one minimal repository with Markdown directory rules."""

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "Fixture")
    _write_yaml(
        repo / "meta-process.yaml",
        {
            "meta_process": {
                "artifact_creation": {
                    "mode": mode,
                    "policy_file": "scripts/artifact_directory_policy.yaml",
                    "registry_file": "scripts/relationships.yaml",
                }
            }
        },
    )
    _write_yaml(
        repo / "scripts" / "artifact_directory_policy.yaml",
        {
            "schema_version": 1,
            "controlled_globs": ["**/*.md"],
            "directory_rules": [
                {
                    "id": "docs",
                    "path_globs": ["docs/**/*.md", "docs/*.md"],
                    "allowed_kinds": ["plan", "status"],
                    "allowed_authorities": ["canonical", "none"],
                },
                {
                    "id": "generated",
                    "path_globs": ["generated/**/*.md", "generated/*.md"],
                    "allowed_kinds": ["generated"],
                    "allowed_authorities": ["none"],
                    "generated_only": True,
                },
                {
                    "id": "misc",
                    "path_globs": ["misc/**/*.md", "misc/*.md"],
                    "allowed_kinds": ["temporary"],
                    "allowed_authorities": ["none"],
                    "quarantine": True,
                    "max_ttl_days": 14,
                },
            ],
        },
    )
    _write_yaml(repo / "scripts" / "relationships.yaml", {"schema_version": 2, "artifacts": []})
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo


def test_repository_globs_do_not_let_single_star_cross_directories() -> None:
    """Root and one-level rules must not swallow more specific nested paths."""

    assert _path_glob_matches("README.md", "*.md")
    assert not _path_glob_matches("docs/README.md", "*.md")
    assert _path_glob_matches("docs/README.md", "docs/*.md")
    assert not _path_glob_matches("docs/nested/README.md", "docs/*.md")
    assert _path_glob_matches("docs/README.md", "docs/**/*.md")
    assert _path_glob_matches("docs/nested/README.md", "docs/**/*.md")
    assert _path_glob_matches("docs/a/b/README.md", "docs/**/*.md")


def _intent(path: str, *, concern: str = "current-status", authority: str = "canonical") -> dict[str, object]:
    """Return one complete human-authored artifact intent fixture."""

    return {
        "artifact_id": f"fixture:{path}",
        "path": path,
        "kind": "status",
        "owner": "repository-governance",
        "concern_id": concern,
        "authority": authority,
        "creation_justification": "Own the current status question.",
        "separate_file_reason": "No existing artifact owns this distinct concern.",
        "lifecycle": {
            "status": "active",
            "retirement_condition": "Supersede after a reviewed replacement is accepted.",
        },
        "review_triggers": ["status changes"],
        "alignment": {"consumer_refs": ["README.md"]},
    }


def _set_artifacts(repo: Path, artifacts: list[dict[str, object]]) -> None:
    """Replace the fixture intent list."""

    _write_yaml(repo / "scripts" / "relationships.yaml", {"schema_version": 2, "artifacts": artifacts})


def test_registered_distinct_document_is_allowed(tmp_path: Path) -> None:
    """A complete intent in an allowed directory should pass enforcement."""

    repo = _repo(tmp_path)
    _set_artifacts(repo, [_intent("docs/status.md")])
    decision = evaluate_paths(
        repo_root=repo,
        target_paths=("docs/status.md",),
        client="test",
        tool_name="create",
        write_receipt=False,
    )
    assert decision.decision == "allow"
    assert decision.target_decisions[0].reason_code == "registered_creation_allowed"


def test_missing_intent_is_denied_in_enforce_and_observed_in_observe(tmp_path: Path) -> None:
    """Observe and enforce should preserve one semantic finding but differ in effect."""

    repo = _repo(tmp_path)
    enforced = evaluate_paths(
        repo_root=repo,
        target_paths=("docs/new.md",),
        client="test",
        tool_name="create",
        write_receipt=False,
    )
    observed = evaluate_paths(
        repo_root=repo,
        target_paths=("docs/new.md",),
        client="test",
        tool_name="create",
        mode="observe",
        write_receipt=False,
    )
    assert enforced.decision == "deny"
    assert observed.decision == "observe_violation"
    assert enforced.target_decisions[0].reason_code == observed.target_decisions[0].reason_code == "intent_missing"


def test_duplicate_canonical_concern_is_denied(tmp_path: Path) -> None:
    """Two active canonical files cannot own the same concern."""

    repo = _repo(tmp_path)
    _set_artifacts(
        repo,
        [
            _intent("docs/old.md"),
            _intent("docs/new.md"),
        ],
    )
    decision = evaluate_paths(
        repo_root=repo,
        target_paths=("docs/new.md",),
        client="test",
        tool_name="create",
        write_receipt=False,
    )
    assert decision.decision == "deny"
    assert "already owned" in " ".join(decision.target_decisions[0].details)


def test_misc_requires_non_authoritative_bounded_quarantine(tmp_path: Path) -> None:
    """The escape hatch must expire and cannot become authority."""

    repo = _repo(tmp_path)
    intent = _intent("misc/note.md", authority="canonical")
    intent.update(
        {
            "kind": "temporary",
            "destination": "docs/status.md",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        }
    )
    _set_artifacts(repo, [intent])
    denied = evaluate_paths(
        repo_root=repo,
        target_paths=("misc/note.md",),
        client="test",
        tool_name="create",
        write_receipt=False,
    )
    assert denied.decision == "deny"
    details = " ".join(denied.target_decisions[0].details)
    assert "authority: none" in details
    assert "14-day" in details

    intent["authority"] = "none"
    intent["expires_at"] = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    _set_artifacts(repo, [intent])
    allowed = evaluate_paths(
        repo_root=repo,
        target_paths=("misc/note.md",),
        client="test",
        tool_name="create",
        write_receipt=False,
    )
    assert allowed.decision == "allow"


def test_generated_artifact_requires_generator(tmp_path: Path) -> None:
    """Generated directories cannot hide unexplained hand-authored files."""

    repo = _repo(tmp_path)
    intent = _intent("generated/report.md", authority="none")
    intent["kind"] = "generated"
    _set_artifacts(repo, [intent])
    denied = evaluate_paths(
        repo_root=repo,
        target_paths=("generated/report.md",),
        client="test",
        tool_name="create",
        write_receipt=False,
    )
    assert denied.decision == "deny"
    intent["alignment"] = {"generated_by": "scripts/render_report.py"}
    _set_artifacts(repo, [intent])
    allowed = evaluate_paths(
        repo_root=repo,
        target_paths=("generated/report.md",),
        client="test",
        tool_name="create",
        write_receipt=False,
    )
    assert allowed.decision == "allow"


def test_existing_and_uncontrolled_paths_are_not_blocked(tmp_path: Path) -> None:
    """The initial ratchet must not import legacy edits or conventional source files."""

    repo = _repo(tmp_path)
    (repo / "docs").mkdir()
    (repo / "docs" / "existing.md").write_text("existing\n", encoding="utf-8")
    _git(repo, "add", "docs/existing.md")
    _git(repo, "commit", "-m", "existing")
    decision = evaluate_paths(
        repo_root=repo,
        target_paths=("docs/existing.md", "src/new.py"),
        client="test",
        tool_name="create",
        write_receipt=False,
    )
    assert decision.decision == "allow"
    assert [item.reason_code for item in decision.target_decisions] == [
        "existing_path",
        "outside_controlled_globs",
    ]


def test_report_steps_down_to_receipts_and_feedback(tmp_path: Path) -> None:
    """Aggregate observability should retain exact decision and feedback identity."""

    repo = _repo(tmp_path, mode="observe")
    receipts = tmp_path / "receipts.jsonl"
    feedback_path = tmp_path / "feedback.jsonl"
    decision = evaluate_paths(
        repo_root=repo,
        target_paths=("docs/new.md",),
        client="test",
        tool_name="create",
        receipt_path=receipts,
    )
    feedback = record_feedback(
        feedback_type="friction",
        receipt_id=decision.receipt_id,
        observation="The concern was already owned under an alias.",
        recommendation="Surface alias owners in the denial.",
        feedback_path=feedback_path,
    )
    report = build_report(
        receipt_path=receipts,
        feedback_path=feedback_path,
        repo_root=repo,
    )
    assert report["decision_counts"] == {"observe_violation": 1}
    assert report["feedback_counts"] == {"friction": 1}
    assert report["open_feedback"][0]["feedback_id"] == feedback.feedback_id
    assert report["step_down"]["receipt_ids"] == [decision.receipt_id]
    assert json.loads(receipts.read_text(encoding="utf-8"))["target_decisions"][0]["path"] == "docs/new.md"

    record_feedback_disposition(
        feedback_id=feedback.feedback_id,
        disposition="resolved",
        resolution="Alias owners are now returned by the target-bound lookup.",
        feedback_path=feedback_path,
    )
    resolved_report = build_report(
        receipt_path=receipts,
        feedback_path=feedback_path,
        repo_root=repo,
    )
    assert resolved_report["open_feedback"] == []
    assert resolved_report["disposition_counts"] == {"resolved": 1}
    assert resolved_report["resolved_feedback"][0]["feedback"]["feedback_id"] == feedback.feedback_id


def test_audit_detects_expired_retained_misc(tmp_path: Path) -> None:
    """Quarantine expiry remains enforceable after the creation event."""

    repo = _repo(tmp_path)
    intent = _intent("misc/note.md", authority="none")
    intent.update(
        {
            "kind": "temporary",
            "destination": "docs/status.md",
            "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        }
    )
    _set_artifacts(repo, [intent])
    (repo / "misc").mkdir()
    (repo / "misc" / "note.md").write_text("temporary\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "temporary")
    audit = audit_repository(repo)
    assert audit.finding_count == 1
    assert audit.findings[0].reason_code == "retained_artifact_invalid"
