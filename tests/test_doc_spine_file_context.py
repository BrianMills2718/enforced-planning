from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_file_context_module():
    import importlib.util
    import sys

    module_path = REPO_ROOT / "scripts" / "file_context.py"
    module_name = "doc_spine_file_context_module"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_doc_spine_fixture(repo_root: Path) -> None:
    _write(repo_root / "EXECUTION_BRIEF.md", "brief\n")
    _write(repo_root / "PLANNING_OPERATING_MODEL.md", "north star\n")
    _write(repo_root / "docs/overview/CURRENT_STATE.md", "current\n")
    _write(repo_root / "docs/overview/GAP_SUMMARY.md", "gap\n")
    _write(repo_root / "docs/plans/55_test.md", "plan\n")
    _write(repo_root / "scripts/doc_authority.yaml", _authority_config())
    _write(repo_root / "scripts/relationships.yaml", _relationships_config())
    _write(repo_root / "src/module.py", "print('x')\n")


def _relationships_config() -> str:
    return "\n".join(
        [
            "required_reading:",
            "  defaults:",
            "    - CLAUDE.md",
            "couplings: []",
            "governance: []",
            "architecture: []",
            "adrs: {}",
        ]
    ) + "\n"


def _authority_config() -> str:
    return """schema_version: 2
indexed_authority_surfaces: []
doc_spine:
  root_doc: EXECUTION_BRIEF.md
  required_concerns: [execution_brief, north_star, current_state, gap_summary]
role_budgets: {}
docs:
  - path: EXECUTION_BRIEF.md
    authority: canonical
    doc_status: active
    concerns: [execution_brief]
    role: execution_brief
    primary_parent: null
  - path: PLANNING_OPERATING_MODEL.md
    authority: canonical
    doc_status: active
    concerns: [north_star]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
  - path: docs/overview/CURRENT_STATE.md
    authority: canonical
    doc_status: active
    concerns: [current_state]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
  - path: docs/overview/GAP_SUMMARY.md
    authority: canonical
    doc_status: active
    concerns: [gap_summary]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
    required_context:
      - path: docs/overview/CURRENT_STATE.md
        reason: Gap needs current state.
      - path: PLANNING_OPERATING_MODEL.md
        reason: Gap needs north star.
  - path: docs/plans/55_test.md
    authority: canonical
    doc_status: active
    concerns: []
    role: plan
    primary_parent: docs/overview/GAP_SUMMARY.md
code_surfaces:
  - paths: [src/module.py]
    primary_spec: docs/plans/55_test.md
"""


def test_collect_context_includes_doc_spine_primary_spec_and_ancestor_chain(tmp_path: Path) -> None:
    module = _load_file_context_module()
    repo_root = tmp_path / "demo"
    _write_doc_spine_fixture(repo_root)

    relationships = module.load_relationships(repo_root=repo_root, config_path="scripts/relationships.yaml")
    context = module.collect_context(
        "src/module.py",
        relationships,
        repo_root=repo_root,
        authority_config_path=repo_root / "scripts/doc_authority.yaml",
    )

    assert context.doc_spine_primary_spec == "docs/plans/55_test.md"
    assert context.doc_spine_ancestor_chain == ["docs/overview/GAP_SUMMARY.md", "EXECUTION_BRIEF.md"]
    assert "docs/plans/55_test.md" in context.doc_spine_reads
    assert "docs/overview/GAP_SUMMARY.md" in context.doc_spine_reads
    assert "EXECUTION_BRIEF.md" in context.doc_spine_reads


def test_collect_context_includes_required_context_with_reason(tmp_path: Path) -> None:
    module = _load_file_context_module()
    repo_root = tmp_path / "demo"
    _write_doc_spine_fixture(repo_root)

    relationships = module.load_relationships(repo_root=repo_root, config_path="scripts/relationships.yaml")
    context = module.collect_context(
        "src/module.py",
        relationships,
        repo_root=repo_root,
        authority_config_path=repo_root / "scripts/doc_authority.yaml",
    )

    required_context = {entry["path"]: entry["reason"] for entry in context.doc_spine_required_context}
    assert required_context == {
        "docs/overview/CURRENT_STATE.md": "Gap needs current state.",
        "PLANNING_OPERATING_MODEL.md": "Gap needs north star.",
    }
    assert "docs/overview/CURRENT_STATE.md" in context.required_reads
    assert "PLANNING_OPERATING_MODEL.md" in context.required_reads
