"""Verify bounded source-derived context from reviewed and legacy relationships."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from enforced_planning.context_packet import ContextPacketError
from enforced_planning.context_packet import build_context_packet
from enforced_planning.context_packet import relationship_specs


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
    by_relation = {(item.relation, item.direction): item for item in packet.items}
    target = by_relation[("self", "self")]
    assert target.summary == "Decide whether a principal can access one resource."
    assert target.summary_source == "python:symbol-docstring"
    assert target.line == 3
    requirement = by_relation[("implements", "outgoing")]
    assert requirement.summary == "Define governed request behavior."
    assert requirement.provenance == "relationships[0]"
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
