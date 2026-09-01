from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from enforced_planning.pr_review_signoff import (
    CriterionResult,
    ProgrammaticCheck,
    ProgrammaticCheckResult,
    PullRequestRevision,
    ReviewerSession,
    ReviewFinding,
    SemanticCriterion,
    SemanticReviewResult,
    SemanticRubric,
    build_check_run_payload,
    build_codex_command,
    evaluate_signoff,
    load_review_spec,
    run_programmatic_checks,
    run_review,
)

HEAD = "a" * 40
BASE = "b" * 40


RUBRIC = SemanticRubric(
    revision="rubric-v1",
    criteria=(
        SemanticCriterion(
            criterion_id="AC-1",
            criterion="The changed behavior is tested at its public boundary.",
            evidence_required=("test output",),
            negative_control="An isolated helper test cannot satisfy the criterion.",
        ),
    ),
)
LANES = ("correctness",)
SESSIONS = (ReviewerSession(review_lane="correctness", session_id="codex:fresh-reviewer"),)
CHECK_SPECS = (ProgrammaticCheck(check_id="focused-tests", argv=("pytest", "-q")),)
PASSING_CHECKS = (
    ProgrammaticCheckResult(
        check_id="focused-tests",
        argv=("pytest", "-q"),
        exit_code=0,
        output_sha256="c" * 64,
        output_excerpt="one passed",
    ),
)


def _passing_criterion() -> CriterionResult:
    return CriterionResult(
        criterion_id="AC-1",
        outcome="pass",
        evidence_refs=("tests/test_feature.py",),
        rationale="The public-boundary test passed.",
    )


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


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("programmatic_checks", [], "at least 1 item"),
        ("review_lanes", ["correctness", "correctness"], "review lanes must be unique"),
    ],
)
def test_review_spec_rejects_vacuous_or_duplicate_orchestration(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    spec_path = _write_spec(tmp_path / "spec.json")
    payload = json.loads(spec_path.read_text())
    payload[field] = value
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match=message):
        load_review_spec(spec_path)


def test_review_spec_rejects_duplicate_rubric_criteria(tmp_path: Path) -> None:
    spec_path = _write_spec(tmp_path / "spec.json")
    payload = json.loads(spec_path.read_text())
    payload["semantic_rubric"]["criteria"].append(
        payload["semantic_rubric"]["criteria"][0]
    )
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="criterion IDs must be unique"):
        load_review_spec(spec_path)


def test_semantic_result_rejects_a_non_sha_revision() -> None:
    with pytest.raises(ValidationError):
        SemanticReviewResult(
            schema_version="1.0",
            review_lane="correctness",
            head_sha="latest",
            verdict="pass",
            criterion_results=[_passing_criterion()],
            findings=[],
            summary="No blocking defects found.",
        )


def test_codex_output_schema_types_every_const_and_enum() -> None:
    schema_path = Path(__file__).parents[1] / "contracts" / "pr-review-signoff.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    missing: list[str] = []

    def walk(value: object, pointer: str = "") -> None:
        if isinstance(value, dict):
            if ("const" in value or "enum" in value) and "type" not in value:
                missing.append(pointer or "/")
            for key, child in value.items():
                walk(child, f"{pointer}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{pointer}/{index}")

    walk(schema)
    assert missing == []


def test_failed_programmatic_check_cannot_be_signed_off() -> None:
    semantic = SemanticReviewResult(
        schema_version="1.0",
        review_lane="correctness",
        head_sha=HEAD,
        verdict="pass",
        criterion_results=[_passing_criterion()],
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
        expected_rubric=RUBRIC,
        expected_checks=CHECK_SPECS,
        expected_lanes=LANES,
        reviewer_sessions=SESSIONS,
        checks=checks,
        semantics=(semantic,),
    )

    assert receipt.verdict == "rejected"
    assert "programmatic checks failed" in receipt.reasons


def test_stale_semantic_result_cannot_approve_new_head() -> None:
    semantic = SemanticReviewResult(
        schema_version="1.0",
        review_lane="correctness",
        head_sha="d" * 40,
        verdict="pass",
        criterion_results=[_passing_criterion()],
        findings=[],
        summary="Pass on an older revision.",
    )

    receipt = evaluate_signoff(
        expected_head=HEAD,
        observed_head=HEAD,
        expected_rubric=RUBRIC,
        expected_checks=CHECK_SPECS,
        expected_lanes=LANES,
        reviewer_sessions=SESSIONS,
        checks=PASSING_CHECKS,
        semantics=(semantic,),
    )

    assert receipt.verdict == "rejected"
    assert "is bound to a different head" in receipt.reasons[-1]


def test_blocking_finding_cannot_be_hidden_behind_pass_verdict() -> None:
    semantic = SemanticReviewResult(
        schema_version="1.0",
        review_lane="correctness",
        head_sha=HEAD,
        verdict="pass",
        criterion_results=[_passing_criterion()],
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
        expected_rubric=RUBRIC,
        expected_checks=CHECK_SPECS,
        expected_lanes=LANES,
        reviewer_sessions=SESSIONS,
        checks=PASSING_CHECKS,
        semantics=(semantic,),
    )

    assert receipt.verdict == "rejected"
    assert "reported blocking findings" in receipt.reasons[-1]


def test_clean_exact_head_evidence_is_signed_off() -> None:
    semantic = SemanticReviewResult(
        schema_version="1.0",
        review_lane="correctness",
        head_sha=HEAD,
        verdict="pass",
        criterion_results=[_passing_criterion()],
        findings=[],
        summary="No blocking defects found.",
    )
    receipt = evaluate_signoff(
        expected_head=HEAD,
        observed_head=HEAD,
        expected_rubric=RUBRIC,
        expected_checks=CHECK_SPECS,
        expected_lanes=LANES,
        reviewer_sessions=SESSIONS,
        checks=PASSING_CHECKS,
        semantics=(semantic,),
    )

    assert receipt.verdict == "signed_off"
    assert receipt.reasons == ()


def test_empty_programmatic_results_fail_loud() -> None:
    semantic = SemanticReviewResult(
        schema_version="1.0",
        review_lane="correctness",
        head_sha=HEAD,
        verdict="pass",
        criterion_results=[_passing_criterion()],
        findings=[],
        summary="Unsupported pass.",
    )

    with pytest.raises(ValueError, match="must not be empty"):
        evaluate_signoff(
            expected_head=HEAD,
            observed_head=HEAD,
            expected_rubric=RUBRIC,
            expected_checks=CHECK_SPECS,
            expected_lanes=LANES,
            reviewer_sessions=SESSIONS,
            checks=(),
            semantics=(semantic,),
        )


def test_substituted_programmatic_command_cannot_be_signed_off() -> None:
    semantic = SemanticReviewResult(
        schema_version="1.0",
        review_lane="correctness",
        head_sha=HEAD,
        verdict="pass",
        criterion_results=[_passing_criterion()],
        findings=[],
        summary="Semantic review passed.",
    )
    substituted = (
        ProgrammaticCheckResult(
            check_id="focused-tests",
            argv=("true",),
            exit_code=0,
            output_sha256="c" * 64,
            output_excerpt="",
        ),
    )

    receipt = evaluate_signoff(
        expected_head=HEAD,
        observed_head=HEAD,
        expected_rubric=RUBRIC,
        expected_checks=CHECK_SPECS,
        expected_lanes=LANES,
        reviewer_sessions=SESSIONS,
        checks=substituted,
        semantics=(semantic,),
    )

    assert receipt.verdict == "rejected"
    assert "command vectors differ" in receipt.reasons[-1]


def test_missing_or_unknown_rubric_result_cannot_be_signed_off() -> None:
    semantic = SemanticReviewResult(
        schema_version="1.0",
        review_lane="correctness",
        head_sha=HEAD,
        verdict="pass",
        criterion_results=[
            CriterionResult(
                criterion_id="NOT-AC-1",
                outcome="pass",
                evidence_refs=("unrelated.txt",),
                rationale="A different criterion passed.",
            )
        ],
        findings=[],
        summary="Passed a substituted criterion.",
    )

    receipt = evaluate_signoff(
        expected_head=HEAD,
        observed_head=HEAD,
        expected_rubric=RUBRIC,
        expected_checks=CHECK_SPECS,
        expected_lanes=LANES,
        reviewer_sessions=SESSIONS,
        checks=PASSING_CHECKS,
        semantics=(semantic,),
    )

    assert receipt.verdict == "rejected"
    assert "exactly the required rubric criteria" in receipt.reasons[-1]


def test_criterion_result_requires_concrete_evidence() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        CriterionResult(
            criterion_id="AC-1",
            outcome="pass",
            evidence_refs=(),
            rationale="Unsupported pass.",
        )

    with pytest.raises(ValidationError, match="must be non-blank"):
        CriterionResult(
            criterion_id="AC-1",
            outcome="pass",
            evidence_refs=("   ",),
            rationale="Unsupported pass.",
        )


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
        review_lane="correctness",
        head_sha=HEAD,
        verdict="pass",
        criterion_results=[_passing_criterion()],
        findings=[],
        summary="No blocking defects found.",
    )
    receipt = evaluate_signoff(
        expected_head=HEAD,
        observed_head=HEAD,
        expected_rubric=RUBRIC,
        expected_checks=CHECK_SPECS,
        expected_lanes=LANES,
        reviewer_sessions=SESSIONS,
        checks=PASSING_CHECKS,
        semantics=(semantic,),
    )

    payload = build_check_run_payload(receipt)

    assert payload["head_sha"] == HEAD
    assert payload["name"] == "agent-review-candidate"
    assert receipt.authority_state == "candidate_only"
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
        "review_lanes": ["correctness", "test-evidence"],
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec_payload), encoding="utf-8")
    fake_codex = tmp_path / "fake-codex"
    semantic = {
        "schema_version": "1.0",
        "review_lane": "correctness",
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
        "prompt = sys.stdin.read()\n"
        "lane = 'test-evidence' if '\"review_lane\": \"test-evidence\"' in prompt else 'correctness'\n"
        "args = sys.argv[1:]\n"
        "out = pathlib.Path(args[args.index('--output-last-message') + 1])\n"
        f"semantic = {semantic!r}\n"
        "semantic['review_lane'] = lane\n"
        "out.write_text(json.dumps(semantic), encoding='utf-8')\n"
        "print(json.dumps({'type': 'thread.started', 'thread_id': 'fresh-' + lane}))\n",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    receipt_path = tmp_path / "receipt.json"
    check_path = tmp_path / "check.json"

    pr_head_observations: list[tuple[str, int]] = []

    def resolve_pr_revision(repository: str, pull_request: int) -> PullRequestRevision:
        pr_head_observations.append((repository, pull_request))
        return PullRequestRevision(base_sha=base, head_sha=head)

    receipt = run_review(
        load_review_spec(spec_file),
        repo_root=repo,
        output_schema=Path(__file__).parents[1] / "contracts" / "pr-review-signoff.schema.json",
        receipt_path=receipt_path,
        check_payload_path=check_path,
        codex_bin=str(fake_codex),
        pr_revision_resolver=resolve_pr_revision,
    )

    assert receipt.verdict == "signed_off"
    assert {session.session_id for session in receipt.reviewer_sessions} == {
        "codex:fresh-correctness",
        "codex:fresh-test-evidence",
    }
    assert {review.review_lane for review in receipt.semantic_reviews} == {
        "correctness",
        "test-evidence",
    }
    assert receipt.programmatic_checks[0].exit_code == 0
    assert json.loads(receipt_path.read_text())["head_sha"] == head
    assert json.loads(check_path.read_text())["conclusion"] == "success"
    assert pr_head_observations == [("owner/repo", 7), ("owner/repo", 7)]


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


def test_runner_refuses_live_pr_base_mismatch_before_checks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "feature.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    spec_file = _write_spec(tmp_path / "spec.json")
    payload = json.loads(spec_file.read_text())
    payload["base_sha"] = head
    payload["head_sha"] = head
    spec_file.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="live pull-request revision"):
        run_review(
            load_review_spec(spec_file),
            repo_root=repo,
            output_schema=Path("unused.json"),
            receipt_path=tmp_path / "receipt.json",
            check_payload_path=tmp_path / "check.json",
            codex_bin=str(tmp_path / "must-not-run"),
            pr_revision_resolver=lambda _repository, _pull_request: PullRequestRevision(
                base_sha="f" * 40,
                head_sha=head,
            ),
        )


def test_runner_refuses_dirty_worktree_before_checks_or_model(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "feature.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    (repo / "untracked.txt").write_text("not frozen\n", encoding="utf-8")
    spec_path = _write_spec(tmp_path / "spec.json")
    payload = json.loads(spec_path.read_text())
    payload["base_sha"] = head
    payload["head_sha"] = head
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="dirty during preflight"):
        run_review(
            load_review_spec(spec_path),
            repo_root=repo,
            output_schema=Path("unused.json"),
            receipt_path=tmp_path / "receipt.json",
            check_payload_path=tmp_path / "check.json",
            codex_bin=str(tmp_path / "must-not-run"),
        )


def test_programmatic_check_cannot_mutate_frozen_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "feature.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    spec_path = _write_spec(tmp_path / "spec.json")
    payload = json.loads(spec_path.read_text())
    payload["base_sha"] = head
    payload["head_sha"] = head
    payload["programmatic_checks"] = [
        {
            "check_id": "mutating-check",
            "argv": [sys.executable, "-c", "open('mutation.txt', 'w').write('changed')"],
        }
    ]
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    results = run_programmatic_checks(load_review_spec(spec_path), repo_root=repo)

    assert results[0].exit_code != 0
    assert results[0].execution_boundary == "systemd-read-only-private-network"
    assert not (repo / "mutation.txt").exists()


def test_programmatic_check_has_no_external_network(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "feature.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    spec_path = _write_spec(tmp_path / "spec.json")
    payload = json.loads(spec_path.read_text())
    payload["base_sha"] = head
    payload["head_sha"] = head
    payload["programmatic_checks"] = [
        {
            "check_id": "network-probe",
            "argv": [
                sys.executable,
                "-c",
                "import socket; socket.create_connection(('github.com', 443), timeout=2)",
            ],
        }
    ]
    spec_path.write_text(json.dumps(payload), encoding="utf-8")

    results = run_programmatic_checks(load_review_spec(spec_path), repo_root=repo)

    assert results[0].exit_code != 0
    assert results[0].execution_boundary == "systemd-read-only-private-network"
