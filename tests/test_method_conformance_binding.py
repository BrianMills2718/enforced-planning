"""Company Planning Plan #48 WU-CP-MCR-002: plan-backed claims bind the passing receipt."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from enforced_planning import claim_mutation_receipts
from enforced_planning.coordination_claims import (
    MethodConformanceRefusal,
    resolve_method_conformance_binding,
)

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_coordination_claims.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "method_conformance"
PLAN_PATH = "docs/plans/7_resume_note.md"
RECEIPT_PATH = "docs/plans/supporting/7_resume_note.receipt.json"
GRAPH_PATH = "docs/plans/7_resume_note_work_graph.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_coordination_claims_mcr", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_coordination_claims_mcr"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _isolate_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claim_mutation_receipts, "DEFAULT_EVENTS_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(
        claim_mutation_receipts, "DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH", tmp_path / "archive.jsonl"
    )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit(root: Path, files: dict[str, str | bytes], message: str) -> str:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        _git(root, "add", relative)
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _plan_text(extra: str = "") -> str:
    return (
        f"---\nmethod_conformance_receipt: {RECEIPT_PATH}\n---\n\n# Plan 7: resume note\n\nBody.\n{extra}"
    )


def _receipt(plan_text: str, *, result: str = "pass") -> bytes:
    record = {
        "schema_version": "planning-method-conformance-receipt.v1",
        "record_type": "planning_method_conformance_receipt",
        "receipt_id": "RECEIPT-7_resume_note-abc",
        "plan": {"plan_ref": PLAN_PATH, "plan_sha256": hashlib.sha256(plan_text.encode()).hexdigest()},
        "route": "durable_solo",
        "profile": {"revision": "bounded-design@1"},
        "checklist": {"definition_sha256": "a" * 64},
        "result": result,
    }
    return (json.dumps(record, indent=2) + "\n").encode()


def _repo(tmp_path: Path, *, mode: str | None = "required", result: str = "pass") -> tuple[Path, str]:
    root = tmp_path / "demo"
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    plan = _plan_text()
    files: dict[str, str | bytes] = {
        PLAN_PATH: plan,
        RECEIPT_PATH: _receipt(plan, result=result),
        GRAPH_PATH: json.dumps({"units": [{
            "id": "WU-7-001", "status": "ready",
            "readiness": {"status": "ready", "approvals": [], "failed_guards": []},
        }]}),
    }
    if mode is not None:
        files["meta-process.yaml"] = yaml.safe_dump({"meta_process": {"plans": {"method_conformance": {"mode": mode}}}})
    revision = _commit(root, files, "plan, receipt, graph")
    return root, revision


def _receipt_sha(root: Path) -> str:
    return hashlib.sha256((root / RECEIPT_PATH).read_bytes()).hexdigest()


def _claim(module, root: Path, tmp_path: Path, scope: str = "wu-7-001", **kwargs):
    return module.create_claim(
        agent="codex", project="demo", scope=scope, intent="implement WU-7-001",
        plan_ref="Plan #7", claim_type="write", write_paths=["src/resume.py"],
        repo_root=str(root), worktree_path=str(root / "worktrees" / "wu-7-001"), branch="wu-7-001",
        session_id="codex:test", session_name="resume", broader_goal="resume note",
        work_graph_path=GRAPH_PATH, work_unit_id="WU-7-001", **kwargs,
    )


@pytest.fixture
def claims(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    return module, claims_dir


# --- AC-CP-MCR-002-1: refusals ---------------------------------------------------


def test_missing_receipt_refused_when_repository_requires_it(tmp_path: Path, claims) -> None:
    module, claims_dir = claims
    root, _ = _repo(tmp_path)
    with pytest.raises(MethodConformanceRefusal) as error:
        _claim(module, root, tmp_path)
    assert error.value.code == "missing_method_receipt"
    assert not claims_dir.exists()


def test_digest_mismatch_refused(tmp_path: Path, claims) -> None:
    module, claims_dir = claims
    root, _ = _repo(tmp_path)
    with pytest.raises(MethodConformanceRefusal) as error:
        _claim(module, root, tmp_path, method_receipt_ref=RECEIPT_PATH, method_receipt_sha256="0" * 64)
    assert error.value.code == "method_receipt_digest_mismatch"
    assert not claims_dir.exists()


def test_stale_plan_revision_refused(tmp_path: Path, claims) -> None:
    module, claims_dir = claims
    root, _ = _repo(tmp_path)
    sha = _receipt_sha(root)
    _commit(root, {PLAN_PATH: _plan_text("\nEdited after adoption.\n")}, "edit plan without re-adoption")
    with pytest.raises(MethodConformanceRefusal) as error:
        _claim(module, root, tmp_path, method_receipt_ref=RECEIPT_PATH, method_receipt_sha256=sha)
    assert error.value.code == "stale_plan_revision"
    assert not claims_dir.exists()


def test_non_passing_receipt_refused(tmp_path: Path, claims) -> None:
    module, _ = claims
    root, _ = _repo(tmp_path, result="fail")
    with pytest.raises(MethodConformanceRefusal) as error:
        _claim(module, root, tmp_path, method_receipt_ref=RECEIPT_PATH, method_receipt_sha256=_receipt_sha(root))
    assert error.value.code == "method_receipt_not_passing"


def test_unplanned_maintenance_stays_separate_and_cannot_cite_conformance(tmp_path: Path, claims) -> None:
    module, claims_dir = claims
    root, _ = _repo(tmp_path)
    common = {
        "agent": "codex", "project": "demo", "intent": "fix typo", "plan_ref": "UNPLANNED", "claim_type": "write",
        "write_paths": ["src/typo.py"], "repo_root": str(root), "branch": "typo", "session_id": "codex:test",
        "worktree_path": str(root / "worktrees" / "typo"),
        "session_name": "typo", "broader_goal": "typo",
    }
    with pytest.raises(MethodConformanceRefusal) as error:
        module.create_claim(scope="typo-cited", method_receipt_ref=RECEIPT_PATH,
                            method_receipt_sha256=_receipt_sha(root), **common)
    assert error.value.code == "method_receipt_on_unplanned_claim"
    ok, _message = module.create_claim(scope="typo", **common)
    assert ok is True
    payload = yaml.safe_load((claims_dir / "codex_demo_typo.yaml").read_text())
    assert "method_receipt_sha256" not in payload


# --- AC-CP-MCR-002-2: a valid plan-backed claim -----------------------------------


def test_valid_claim_retains_exact_plan_graph_and_receipt_identity(tmp_path: Path, claims) -> None:
    module, claims_dir = claims
    root, revision = _repo(tmp_path)
    sha = _receipt_sha(root)
    ok, _message = _claim(module, root, tmp_path, method_receipt_ref=RECEIPT_PATH, method_receipt_sha256=sha)
    assert ok is True
    payload = yaml.safe_load((claims_dir / "codex_demo_wu-7-001.yaml").read_text())
    assert payload["method_receipt_ref"] == RECEIPT_PATH
    assert payload["method_receipt_sha256"] == sha
    assert payload["start_revision"] == revision
    graph_bytes = subprocess.run(["git", "-C", str(root), "show", f"{revision}:{GRAPH_PATH}"],
                                 check=True, capture_output=True).stdout
    assert payload["work_graph_sha256"] == hashlib.sha256(graph_bytes).hexdigest()


def test_optional_mode_still_verifies_a_cited_receipt(tmp_path: Path, claims) -> None:
    module, _ = claims
    root, _ = _repo(tmp_path, mode=None)
    ok, _ = _claim(module, root, tmp_path)  # not required, none cited: existing rule unchanged
    assert ok is True
    with pytest.raises(MethodConformanceRefusal):
        _claim(module, root, tmp_path, scope="wu-7-001-cited", method_receipt_ref=RECEIPT_PATH,
               method_receipt_sha256="1" * 64)


def test_consumes_the_real_company_planning_receipt_shape(tmp_path: Path) -> None:
    """Consumer contract: the producer's committed canonical-probe receipts."""

    root = tmp_path / "cp"
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    passing = json.loads((FIXTURES / "research-first.receipt.json").read_text())
    refused = json.loads((FIXTURES / "ab-comparison.receipt.json").read_text())
    prefix = "plugins/company-planning/docs/evidence/method-conformance/canonical-probe/"
    revision = _commit(root, {
        passing["plan"]["plan_ref"]: (FIXTURES / "plan-research-first.md").read_bytes(),
        prefix + "research-first.receipt.json": (FIXTURES / "research-first.receipt.json").read_bytes(),
        prefix + "ab-comparison.receipt.json": (FIXTURES / "ab-comparison.receipt.json").read_bytes(),
    }, "producer fixtures")
    binding = resolve_method_conformance_binding(
        plan_root=root, plan_revision=revision, plan_number=None,
        receipt_ref=prefix + "research-first.receipt.json",
        receipt_sha256=hashlib.sha256((FIXTURES / "research-first.receipt.json").read_bytes()).hexdigest(),
    )
    assert binding is not None
    assert binding.plan_sha256 == passing["plan"]["plan_sha256"]
    assert binding.checklist_definition_sha256 == passing["checklist"]["definition_sha256"]
    assert refused["result"] == "fail"
    with pytest.raises(MethodConformanceRefusal) as error:
        resolve_method_conformance_binding(
            plan_root=root, plan_revision=revision, plan_number=None,
            receipt_ref=prefix + "ab-comparison.receipt.json",
            receipt_sha256=hashlib.sha256((FIXTURES / "ab-comparison.receipt.json").read_bytes()).hexdigest(),
        )
    assert error.value.code == "method_receipt_not_passing"
