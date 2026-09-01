from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from enforced_planning.pr_review_signoff import (
    ProgrammaticCheckResult,
    ReviewFinding,
    SemanticReviewResult,
    build_check_run_payload,
    build_codex_command,
    evaluate_signoff,
    load_review_spec,
    run_review,
)

HEAD = "a" * 40
BASE = "b" * 40


def _write_spec(path: Path) -> Path:
    payload = {
        "schema_version": "1.0",
        "review_id": "pr-42-review",
        "repository": "owner/repo",
        "pull_request": 42,
        "base_sha": BASE,
        "head_sha": HEAD,
        "programmatic_checks": [
            {"check_id": "focused-tests", "argv": ["pytest", "-q", "tests/test_feature.py"]}
        ],
        "semantic_rubric": {
            "revision": "rubric-v1",
            "criteria": [
                {
                    "criterion_id": "AC-1",
                    "criterion": "The changed behavior is tested at its public boundary.",
                    "evidence_required": ["test output", "changed-file references"],
                    "negative_control": "An isolated helper test cannot satisfy the criterion.",
                }
            ],
        },
        "review_lanes": ["correctness", "test-evidence"],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_review_spec_preserves_programmatic_and_semantic_modalities(tmp_path: Path) -> None:
    spec = load_review_spec(_write_spec(tmp_path / "spec.json"))

    assert spec.head_sha == HEAD
    assert spec.programmatic_checks[0].argv[0] == "pytest"
    assert spec.semantic_rubric.criteria[0].negative_control
    assert spec.review_lanes == ("correctness", "test-evidence")


def test_semantic_result_rejects_a_non_sha_revision() -> None:
    with pytest.raises(ValidationError):
        SemanticReviewResult(
            schema_version="1.0",
            head_sha="latest",
            verdict="pass",
            criterion_results=[],
            findings=[],
            summary="No blocking defects found.",
        )


def test_failed_programmatic_check_cannot_be_signed_off() -> None:
    semantic = SemanticReviewResult(
        schema_version="1.0",
        head_sha=HEAD,
        verdict="pass",
        criterion_results=[],
        findings=[],
        summary="No blocking defects found.",
    )
    checks = (
        ProgrammaticCheckResult(
            check_id="focused-tests",
            argv=("pytest", "-q"),
            exit_code=1,
            output_sha256="c" * 64,
            output_excerpt="one failed",
        ),
    )

    receipt = evaluate_signoff(
        expected_head=HEAD,
        observed_head=HEAD,
        rubric_revision="rubric-v1",
        reviewer_session_id="codex:fresh-reviewer",
        checks=checks,
        semantic=semantic,
    )

    assert receipt.verdict == "rejected"
    assert "programmatic checks failed" in receipt.reasons


def test_stale_semantic_result_cannot_approve_new_head() -> None:
    semantic = SemanticReviewResult(
        schema_version="1.0",
        head_sha="d" * 40,
        verdict="pass",
        criterion_results=[],
        findings=[],
        summary="Pass on an older revision.",
    )

    receipt = evaluate_signoff(
        expected_head=HEAD,
        observed_head=HEAD,
        rubric_revision="rubric-v1",
        reviewer_session_id="codex:fresh-reviewer",
        checks=(),
        semantic=semantic,
    )

    assert receipt.verdict == "rejected"
    assert "semantic review is bound to a different head" in receipt.reasons


def test_blocking_finding_cannot_be_hidden_behind_pass_verdict() -> None:
    semantic = SemanticReviewResult(
        schema_version="1.0",
        head_sha=HEAD,
        verdict="pass",
        criterion_results=[],
        findings=[
            ReviewFinding(
                finding_id="F-1",
                severity="blocking",
                summary="Changed code bypasses the required boundary.",
                evidence_refs=("src/feature.py:20",),
            )
        ],
        summary="Pass despite a blocking finding.",
    )

    receipt = evaluate_signoff(
        expected_head=HEAD,
        observed_head=HEAD,
        rubric_revision="rubric-v1",
        reviewer_session_id="codex:fresh-reviewer",
        checks=(),
        semantic=semantic,
    )

    assert receipt.verdict == "rejected"
    assert "semantic review reported blocking findings" in receipt.reasons


def test_clean_exact_head_evidence_is_signed_off() -> None:
    semantic = SemanticReviewResult(
        schema_version="1.0",
        head_sha=HEAD,
        verdict="pass",
        criterion_results=[],
        findings=[],
        summary="No blocking defects found.",
    )
    receipt = evaluate_signoff(
        expected_head=HEAD,
        observed_head=HEAD,
        rubric_revision="rubric-v1",
        reviewer_session_id="codex:fresh-reviewer",
        checks=(),
        semantic=semantic,
    )

    assert receipt.verdict == "signed_off"
    assert receipt.reasons == ()


def test_codex_command_is_ephemeral_read_only_and_schema_bound(tmp_path: Path) -> None:
    command = build_codex_command(
        codex_bin="codex",
        repo_root=tmp_path,
        output_schema=Path("contracts/pr-review-signoff.schema.json"),
        output_path=tmp_path / "semantic.json",
        model="gpt-5.6",
        effort="high",
    )

    assert command[:2] == ("codex", "exec")
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--output-schema") + 1].endswith("pr-review-signoff.schema.json")
    assert command[command.index("--output-last-message") + 1].endswith("semantic.json")


def test_codex_command_uses_authenticated_route_default_when_model_is_omitted(
    tmp_path: Path,
) -> None:
    command = build_codex_command(
        codex_bin="codex",
        repo_root=tmp_path,
        output_schema=Path("contracts/pr-review-signoff.schema.json"),
        output_path=tmp_path / "semantic.json",
        model=None,
        effort="high",
    )

    assert "--model" not in command


def test_check_payload_is_success_only_for_signed_exact_head() -> None:
    semantic = SemanticReviewResult(
        schema_version="1.0",
        head_sha=HEAD,
        verdict="pass",
        criterion_results=[],
        findings=[],
        summary="No blocking defects found.",
    )
    receipt = evaluate_signoff(
        expected_head=HEAD,
        observed_head=HEAD,
        rubric_revision="rubric-v1",
        reviewer_session_id="codex:fresh-reviewer",
        checks=(),
        semantic=semantic,
    )

    payload = build_check_run_payload(receipt, name="coordination-approval")

    assert payload["head_sha"] == HEAD
    assert payload["conclusion"] == "success"
    assert payload["external_id"] == receipt.receipt_sha256()


def test_runner_executes_checks_and_fresh_schema_bound_reviewer(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "feature.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    (repo / "feature.txt").write_text("base\nchanged\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "change"], cwd=repo, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    spec_payload = {
        "schema_version": "1.0",
        "review_id": "integration-review",
        "repository": "owner/repo",
        "pull_request": 7,
        "base_sha": base,
        "head_sha": head,
        "programmatic_checks": [
            {"check_id": "smoke", "argv": [sys.executable, "-c", "print('pass')"]}
        ],
        "semantic_rubric": {
            "revision": "rubric-v1",
            "criteria": [
                {
                    "criterion_id": "AC-1",
                    "criterion": "The change is reviewable.",
                    "evidence_required": ["diff"],
                    "negative_control": "No evidence is a failure.",
                }
            ],
        },
        "review_lanes": ["correctness"],
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec_payload), encoding="utf-8")
    fake_codex = tmp_path / "fake-codex"
    semantic = {
        "schema_version": "1.0",
        "head_sha": head,
        "verdict": "pass",
        "criterion_results": [
            {
                "criterion_id": "AC-1",
                "outcome": "pass",
                "evidence_refs": ["feature.txt"],
                "rationale": "The exact diff was inspected.",
            }
        ],
        "findings": [],
        "summary": "Exact-head review passed.",
    }
    fake_codex.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "out = pathlib.Path(args[args.index('--output-last-message') + 1])\n"
        f"out.write_text({json.dumps(json.dumps(semantic))}, encoding='utf-8')\n"
        "print(json.dumps({'type': 'thread.started', 'thread_id': 'fresh-123'}))\n",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    receipt_path = tmp_path / "receipt.json"
    check_path = tmp_path / "check.json"

    receipt = run_review(
        load_review_spec(spec_file),
        repo_root=repo,
        output_schema=Path(__file__).parents[1] / "contracts" / "pr-review-signoff.schema.json",
        receipt_path=receipt_path,
        check_payload_path=check_path,
        codex_bin=str(fake_codex),
    )

    assert receipt.verdict == "signed_off"
    assert receipt.reviewer_session_id == "codex:fresh-123"
    assert receipt.programmatic_checks[0].exit_code == 0
    assert json.loads(receipt_path.read_text())["head_sha"] == head
    assert json.loads(check_path.read_text())["conclusion"] == "success"


def test_runner_refuses_to_spend_on_a_nonmatching_worktree_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "feature.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    spec_file = _write_spec(tmp_path / "spec.json")
    payload = json.loads(spec_file.read_text())
    payload["base_sha"] = actual
    payload["head_sha"] = "f" * 40
    spec_file.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="does not match frozen head"):
        run_review(
            load_review_spec(spec_file),
            repo_root=repo,
            output_schema=Path("unused.json"),
            receipt_path=tmp_path / "receipt.json",
            check_payload_path=tmp_path / "check.json",
            codex_bin=str(tmp_path / "must-not-run"),
        )
