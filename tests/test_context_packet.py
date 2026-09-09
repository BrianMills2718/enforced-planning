"""Verify bounded source-derived context from reviewed and legacy relationships."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from enforced_planning.context_packet import (
    ContextPacketError,
    build_context_packet,
    build_context_packet_with_receipt,
    relationship_specs,
)
from enforced_planning.context_packet import main as context_packet_main


def _write(path: Path, content: str) -> None:
    """Create one source artifact for a real Git-backed packet fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    """Create and stage a compact requirements-to-code relationship fixture."""

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _write(
        repo / "src/service.py",
        '''"""Serve governed requests."""

def authorize(principal: str, resource: str) -> bool:
    """Decide whether a principal can access one resource."""
    return principal == resource
''',
    )
    _write(repo / "docs/requirements.md", "# Requirements\n\n## Purpose\n\nDefine governed request behavior.\n")
    _write(repo / "docs/adr.md", "# Decision\n\n## Decision\n\nKeep authorization at the request boundary.\n")
    _write(repo / "docs/plan.md", "# Plan\n\n## Goal\n\nImplement and verify authorization.\n")
    _write(
        repo / "tests/test_service.py",
        '"""Verify governed request behavior."""\n\ndef test_authorize() -> None:\n    """Reject unrelated principals."""\n',
    )
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    return repo


def _commit(repo: Path) -> str:
    """Commit the staged fixture and return its exact revision."""

    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Context Packet Test",
            "-c",
            "user.email=context-packet@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _relationships() -> dict[str, object]:
    """Return reviewed V2 edges plus one legacy coupling for compatibility."""

    return {
        "relationships": [
            {
                "source": "src/service.py::authorize",
                "target": "docs/requirements.md",
                "relation": "implements",
                "reason": "The function implements the governed-request requirement.",
                "maintenance": "reconcile",
                "archive_effect": "blocks_archive",
            },
            {
                "source": "src/service.py",
                "target": "docs/adr.md",
                "relation": "governed_by",
                "reason": "The decision fixes authorization placement.",
                "maintenance": "block",
            },
            {
                "source": "src/service.py",
                "target": "docs/plan.md",
                "relation": "planned_by",
                "reason": "The active plan owns this implementation.",
                "maintenance": "reconcile",
            },
            {
                "source": "tests/test_service.py",
                "target": "src/service.py::authorize",
                "relation": "tests",
                "reason": "This test module exercises the authorization symbol.",
                "maintenance": "reconcile",
            },
        ],
        "couplings": [
            {
                "sources": ["src/service.py"],
                "docs": ["docs/requirements.md"],
                "description": "Service changes may alter the requirement wording.",
            }
        ],
        "required_reading": {"defaults": []},
    }


def test_symbol_packet_uses_actual_docstrings_and_bidirectional_edges(tmp_path: Path) -> None:
    """A symbol edit gets its docstring plus incoming tests and outgoing requirements."""

    repo = _repo(tmp_path)

    packet = build_context_packet(
        repo,
        "src/service.py",
        _relationships(),
        target_symbol="authorize",
    )

    assert packet.target == "src/service.py::authorize"
    assert packet.schema_version == 2
    by_relation = {(item.relation, item.direction): item for item in packet.items}
    target = by_relation[("self", "self")]
    assert target.summary == "Decide whether a principal can access one resource."
    assert target.summary_source == "python:symbol-docstring"
    assert target.line == 3
    requirement = by_relation[("implements", "outgoing")]
    assert requirement.summary == "Define governed request behavior."
    assert requirement.provenance == "relationships[0]"
    assert requirement.archive_effect == "blocks_archive"
    test = by_relation[("tests", "incoming")]
    assert test.path == "tests/test_service.py"
    assert test.summary == "Verify governed request behavior."


def test_file_packet_includes_explicit_and_legacy_neighbors_in_priority_order(tmp_path: Path) -> None:
    """File context preserves reviewed edges and legacy coupling compatibility."""

    repo = _repo(tmp_path)

    packet = build_context_packet(repo, "src/service.py", _relationships())

    assert [(item.relation, item.path) for item in packet.items] == [
        ("self", "src/service.py"),
        ("governed_by", "docs/adr.md"),
        ("planned_by", "docs/plan.md"),
        ("updates", "docs/requirements.md"),
    ]
    assert packet.items[1].summary == "Keep authorization at the request boundary."


def test_registry_summary_duplication_and_malformed_edges_fail_loudly() -> None:
    """The graph cannot become a second prose authority or accept vague edges."""

    duplicated = {
        "relationships": [
            {
                "source": "src/a.py",
                "target": "docs/a.md",
                "relation": "implements",
                "reason": "link",
                "summary": "copied prose",
            }
        ]
    }
    with pytest.raises(ContextPacketError, match="duplicates source summary prose"):
        relationship_specs(duplicated)

    unsupported = {
        "relationships": [
            {"source": "src/a.py", "target": "docs/a.md", "relation": "sort_of_related", "reason": "vague"}
        ]
    }
    with pytest.raises(ContextPacketError, match="unsupported relation"):
        relationship_specs(unsupported)

    no_reason = {
        "relationships": [
            {"source": "src/a.py", "target": "docs/a.md", "relation": "implements", "reason": ""}
        ]
    }
    with pytest.raises(ContextPacketError, match="must explain why"):
        relationship_specs(no_reason)

    unsupported_archive_effect = {
        "relationships": [
            {
                "source": "src/a.py",
                "target": "docs/a.md",
                "relation": "implements",
                "reason": "The source implements the document.",
                "archive_effect": "probably_safe",
            }
        ]
    }
    with pytest.raises(ContextPacketError, match="unsupported archive effect"):
        relationship_specs(unsupported_archive_effect)


def test_missing_and_legacy_archive_effects_require_review() -> None:
    """Unclassified retention semantics cannot silently become safe or blocking."""

    relationships = _relationships()
    specs = relationship_specs(relationships)

    assert specs[0].archive_effect == "blocks_archive"
    assert specs[1].archive_effect == "review_required"
    assert specs[-1].provenance == "couplings[0]"
    assert specs[-1].archive_effect == "review_required"


def test_packet_budget_is_deterministic_and_reports_omissions(tmp_path: Path) -> None:
    """Budget pressure keeps the target, omits lower-priority neighbors, and says so."""

    repo = _repo(tmp_path)

    first = build_context_packet(repo, "src/service.py", _relationships(), max_items=2, max_chars=2_000)
    second = build_context_packet(repo, "src/service.py", _relationships(), max_items=2, max_chars=2_000)

    assert first.to_json() == second.to_json()
    assert [item.relation for item in first.items] == ["self", "governed_by"]
    assert first.omitted_count == 2
    assert [item.code for item in first.diagnostics] == ["context-budget-omitted"]
    assert first.included_chars <= first.max_chars


def test_v3_compiles_defaults_gates_and_required_edges_as_full_file_atoms(tmp_path: Path) -> None:
    """Applicable mandatory context is exact, revision-bound, and never summary-ranked."""

    repo = _repo(tmp_path)
    _write(repo / "CLAUDE.md", "# Instructions\n\nFollow the governed contract.\n")
    _write(repo / "docs/gate.md", "# Gate\n\nRequired for source edits.\n")
    _write(repo / "docs/required.md", "# Required\n\nRead the whole authority.\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    revision = _commit(repo)
    relationships = _relationships()
    relationships["required_reading"] = {
        "defaults": ["CLAUDE.md"],
        "gates": [
            {
                "id": "source-gate",
                "documents": ["docs/gate.md"],
                "applies_to": ["src/**"],
                "reason": "Source edits require the gate authority.",
            }
        ],
    }
    relationships["relationships"].append(
        {
            "source": "src/**/*.py",
            "target": "docs/required.md",
            "relation": "required_reading",
            "reason": "The full authority is mandatory before source edits.",
            "maintenance": "block",
        }
    )

    packet, receipt = build_context_packet_with_receipt(
        repo,
        "src/service.py",
        relationships,
        required_capacity_bytes=10_000,
        session_id="session-1",
        context_epoch="epoch-1",
        action="edit",
        adapter_id="test-adapter",
        adapter_version="1.0",
    )

    assert packet.schema_version == 3
    assert [atom.path for atom in packet.required_atoms] == [
        "CLAUDE.md",
        "docs/gate.md",
        "docs/required.md",
    ]
    assert all(atom.revision == revision for atom in packet.required_atoms)
    assert all(atom.working_tree_state == "clean" for atom in packet.required_atoms)
    for atom in packet.required_atoms:
        raw = (repo / atom.path).read_bytes()
        assert atom.byte_count == len(raw)
        assert atom.content_sha256 == hashlib.sha256(raw).hexdigest()
        assert atom.content == raw.decode("utf-8")
    assert receipt.visibility == "expected"
    assert receipt.context_epoch == "epoch-1"
    assert receipt.packet_sha256 == hashlib.sha256(packet.to_json().encode("utf-8")).hexdigest()
    receipt_payload = json.loads(receipt.to_json())
    assert all("content" not in atom for atom in receipt_payload["required_atoms"])


def test_v3_authority_change_invalidates_packet_and_receipt_digest(tmp_path: Path) -> None:
    """Working-copy bytes cannot inherit the clean HEAD revision identity."""

    repo = _repo(tmp_path)
    _write(repo / "CLAUDE.md", "first\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    _commit(repo)
    relationships = {"required_reading": {"defaults": ["CLAUDE.md"]}}
    first_packet, first_receipt = build_context_packet_with_receipt(
        repo,
        "src/service.py",
        relationships,
        required_capacity_bytes=1_000,
        session_id="session-1",
        context_epoch="epoch-1",
        action="edit",
        adapter_id="test-adapter",
        adapter_version="1.0",
    )
    _write(repo / "docs/unrelated.md", "unrelated\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    _commit(repo)
    stable_packet, stable_receipt = build_context_packet_with_receipt(
        repo,
        "src/service.py",
        relationships,
        required_capacity_bytes=1_000,
        session_id="session-1",
        context_epoch="epoch-2",
        action="edit",
        adapter_id="test-adapter",
        adapter_version="1.0",
    )
    assert stable_packet.required_atoms[0].revision == first_packet.required_atoms[0].revision
    assert stable_receipt.packet_sha256 == first_receipt.packet_sha256

    _write(repo / "CLAUDE.md", "second\n")

    second_packet, second_receipt = build_context_packet_with_receipt(
        repo,
        "src/service.py",
        relationships,
        required_capacity_bytes=1_000,
        session_id="session-1",
        context_epoch="epoch-3",
        action="edit",
        adapter_id="test-adapter",
        adapter_version="1.0",
    )

    changed = second_packet.required_atoms[0]
    assert changed.revision is None
    assert changed.working_tree_state == "working_copy"
    assert first_receipt.packet_sha256 != second_receipt.packet_sha256
    assert first_packet.required_atoms[0].content_sha256 != changed.content_sha256


def test_v3_missing_or_over_capacity_required_context_blocks(tmp_path: Path) -> None:
    """Required full files cannot be silently omitted or clipped."""

    repo = _repo(tmp_path)
    _commit(repo)
    receipt_args = {
        "session_id": "session-1",
        "context_epoch": "epoch-1",
        "action": "edit",
        "adapter_id": "test-adapter",
        "adapter_version": "1.0",
    }
    missing = {"required_reading": {"defaults": ["docs/missing.md"]}}
    with pytest.raises(ContextPacketError, match="required context file is missing"):
        build_context_packet_with_receipt(
            repo,
            "src/service.py",
            missing,
            required_capacity_bytes=1_000,
            **receipt_args,
        )

    over_capacity = {"required_reading": {"defaults": ["docs/requirements.md"]}}
    with pytest.raises(ContextPacketError, match="required context needs .* bytes but capacity is 5"):
        build_context_packet_with_receipt(
            repo,
            "src/service.py",
            over_capacity,
            required_capacity_bytes=5,
            **receipt_args,
        )


def test_v3_required_capacity_is_separate_from_optional_item_budget(tmp_path: Path) -> None:
    """Optional omission remains legal and cannot clip a required atom."""

    repo = _repo(tmp_path)
    _commit(repo)
    relationships = _relationships()
    relationships["required_reading"] = {"defaults": ["docs/requirements.md"]}

    packet, _receipt = build_context_packet_with_receipt(
        repo,
        "src/service.py",
        relationships,
        max_items=1,
        max_chars=500,
        required_capacity_bytes=10_000,
        session_id="session-1",
        context_epoch="epoch-1",
        action="edit",
        adapter_id="test-adapter",
        adapter_version="1.0",
    )

    assert packet.omitted_count > 0
    assert packet.required_atoms[0].content == (repo / "docs/requirements.md").read_text(encoding="utf-8")
    assert packet.required_bytes == len((repo / "docs/requirements.md").read_bytes())


def test_existing_packet_json_remains_v2_without_receipt_inputs(tmp_path: Path) -> None:
    """The new contract is opt-in and does not alter existing hook payloads."""

    repo = _repo(tmp_path)
    packet = build_context_packet(repo, "src/service.py", _relationships())
    payload = json.loads(packet.to_json())

    assert payload["schema_version"] == 2
    assert "required_atoms" not in payload


def test_cli_v3_writes_expected_receipt_and_prints_packet(tmp_path: Path, capsys) -> None:
    """The existing CLI emits the packet and a separate payload-free receipt."""

    repo = _repo(tmp_path)
    _write(repo / "CLAUDE.md", "# Required instructions\n")
    _write(
        repo / "relationships.yaml",
        "required_reading:\n  defaults:\n    - CLAUDE.md\n",
    )
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    _commit(repo)
    receipt_path = tmp_path / "receipts" / "expected.json"

    code = context_packet_main(
        [
            "src/service.py",
            "--repo-root",
            str(repo),
            "--config",
            "relationships.yaml",
            "--required-capacity-bytes",
            "1000",
            "--receipt-path",
            str(receipt_path),
            "--session-id",
            "session-1",
            "--context-epoch",
            "epoch-1",
            "--action",
            "edit",
            "--adapter-id",
            "context-packet-cli",
            "--adapter-version",
            "3",
        ]
    )

    packet_payload = json.loads(capsys.readouterr().out)
    receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert code == 0
    assert packet_payload["schema_version"] == 3
    assert packet_payload["required_atoms"][0]["content"] == "# Required instructions\n"
    assert receipt_payload["visibility"] == "expected"
    assert "content" not in receipt_payload["required_atoms"][0]


def test_unresolved_neighbor_and_untracked_target_are_explicit(tmp_path: Path) -> None:
    """Broken graph selectors and unknown edit targets never disappear silently."""

    repo = _repo(tmp_path)
    relationships = {
        "relationships": [
            {
                "source": "src/service.py",
                "target": "docs/missing.md",
                "relation": "planned_by",
                "reason": "Expected plan is missing.",
            }
        ]
    }

    packet = build_context_packet(repo, "src/service.py", relationships)

    assert [item.code for item in packet.diagnostics] == ["relationship-target-unresolved"]
    assert packet.diagnostics[0].selector == "docs/missing.md"
    with pytest.raises(ContextPacketError, match="is not Git-tracked"):
        build_context_packet(repo, "src/missing.py", relationships)


def test_untracked_new_file_gets_path_relationship_context_when_allowed(tmp_path: Path) -> None:
    """Write hooks can contextualize a new path without pretending source content exists."""

    repo = _repo(tmp_path)
    relationships = {
        "relationships": [
            {
                "source": "src/**/*.py",
                "target": "docs/requirements.md",
                "relation": "implements",
                "reason": "Source files implement the reviewed requirements.",
            }
        ]
    }

    packet = build_context_packet(
        repo,
        "src/new_service.py",
        relationships,
        allow_untracked_target=True,
    )

    assert packet.items[0].path == "src/new_service.py"
    assert packet.items[0].summary is None
    assert any(item.path == "docs/requirements.md" for item in packet.items)
    assert [diagnostic.code for diagnostic in packet.diagnostics] == [
        "target-untracked-new-file"
    ]


def test_untracked_new_file_cannot_claim_a_symbol(tmp_path: Path) -> None:
    """A symbol selector requires parseable tracked source, not a path-only placeholder."""

    repo = _repo(tmp_path)
    with pytest.raises(ContextPacketError, match="cannot resolve a Python symbol"):
        build_context_packet(
            repo,
            "src/new_service.py",
            {},
            target_symbol="authorize",
            allow_untracked_target=True,
        )


@pytest.mark.parametrize("target", ["/tmp/outside.py", "src/../outside.py"])
def test_target_path_must_remain_repository_relative(tmp_path: Path, target: str) -> None:
    """Context output cannot leak or traverse beyond its governed repository."""

    repo = _repo(tmp_path)
    with pytest.raises(ContextPacketError, match="repository-relative path"):
        build_context_packet(repo, target, {}, allow_untracked_target=True)


def test_packet_json_contains_no_absolute_workspace_path(tmp_path: Path) -> None:
    """Hook payloads remain portable and expose only repository-relative provenance."""

    repo = _repo(tmp_path)

    payload = build_context_packet(repo, "src/service.py", _relationships()).to_json(pretty=True)

    assert str(repo) not in payload
    assert json.loads(payload)["target"] == "src/service.py"


def test_recursive_glob_matches_files_at_root_and_nested_levels(tmp_path: Path) -> None:
    """A conventional ``src/**/*.py`` edge includes zero or more directories."""

    repo = _repo(tmp_path)
    _write(repo / "src/nested/worker.py", '"""Run nested work."""\n')
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    relationships = {
        "relationships": [
            {
                "source": "src/**/*.py",
                "target": "docs/adr.md",
                "relation": "governed_by",
                "reason": "The decision governs all source modules.",
            }
        ]
    }

    root_packet = build_context_packet(repo, "src/service.py", relationships)
    nested_packet = build_context_packet(repo, "src/nested/worker.py", relationships)

    assert [item.path for item in root_packet.items] == ["src/service.py", "docs/adr.md"]
    assert [item.path for item in nested_packet.items] == ["src/nested/worker.py", "docs/adr.md"]


def test_legacy_architecture_current_key_resolves_current_state_context(tmp_path: Path) -> None:
    """Existing governed repos use ``current``; migration cannot silently lose that edge."""

    repo = _repo(tmp_path)
    relationships = {
        "architecture": [
            {
                "sources": ["src/service.py"],
                "current": ["docs/requirements.md"],
            }
        ]
    }

    packet = build_context_packet(repo, "src/service.py", relationships)

    current = next(item for item in packet.items if item.path == "docs/requirements.md")
    assert current.relation == "documents_current"
    assert current.provenance == "architecture[0].current"


def test_architecture_aliases_cannot_be_declared_twice(tmp_path: Path) -> None:
    """Mixed V1/V2 aliases fail loudly instead of producing ambiguous duplicate edges."""

    repo = _repo(tmp_path)
    relationships = {
        "architecture": [
            {
                "sources": ["src/service.py"],
                "current": ["docs/requirements.md"],
                "current_docs": ["docs/requirements.md"],
            }
        ]
    }

    with pytest.raises(ContextPacketError, match="duplicate aliases current_docs, current"):
        build_context_packet(repo, "src/service.py", relationships)
