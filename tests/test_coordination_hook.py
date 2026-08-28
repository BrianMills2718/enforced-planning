"""Focused performance-contract tests for repository closeout collection."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from enforced_planning import prewrite_claim_fast, prewrite_claim_projection
from scripts import coordination_hook


def test_repository_statuses_are_collected_concurrently(monkeypatch, tmp_path: Path) -> None:
    repositories = tuple(tmp_path / f"repo-{index}" for index in range(8))
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_status(_repository: Path) -> dict[str, object]:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return {"fingerprint": "same", "dirty": False, "entry_count": 0}

    monkeypatch.setattr(coordination_hook, "_repository_status", fake_status)

    snapshot = coordination_hook._repository_statuses(repositories)

    assert len(snapshot) == len(repositories)
    assert max_active > 1


def test_active_claims_use_digest_bound_projection_without_yaml_parse(
    monkeypatch, tmp_path: Path
) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    claim_path = claims_dir / "claim.yaml"
    claim_path.write_text("status: active\n", encoding="utf-8")
    projection = prewrite_claim_projection.PreWriteAuthorityProjectionV1(
        generated_at=datetime.now(UTC),
        claims_dir=str(claims_dir.resolve()),
        registry_digest=prewrite_claim_fast.registry_digest(claims_dir),
        claims=(
            prewrite_claim_projection.PreWriteAuthorityClaimV1(
                agent="codex",
                projects=("demo",),
                scope="fast-stop",
                claim_type="write",
                session_id="codex:session",
                repo_root=str(tmp_path / "demo"),
                worktree_path=str(tmp_path / "demo" / "worktrees" / "fast-stop"),
                branch="fast-stop",
                write_paths=("src",),
                expires_at=None,
                heartbeat_at=None,
                status="active",
                source_file=str(claim_path),
                source_sha256="a" * 64,
                static_issues=(),
            ),
        ),
    )
    projection_path = prewrite_claim_fast.projection_path_for(claims_dir)
    projection_path.write_text(projection.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        coordination_hook.coordination_claims,
        "check_claims",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("parsed YAML registry")),
    )

    claims = coordination_hook._active_claims(claims_dir)

    assert [claim.scope for claim in claims] == ["fast-stop"]
