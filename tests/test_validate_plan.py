import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_PLAN_SCRIPT = REPO_ROOT / "scripts" / "validate_plan.py"


def _load_module():
    import importlib.util
    import sys

    module_path = REPO_ROOT / "scripts" / "validate_plan.py"
    module_name = "validate_plan_module"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _load_file_context_module():
    import importlib.util
    import sys

    module_path = REPO_ROOT / "scripts" / "file_context.py"
    module_name = "file_context_module"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _relationships_config() -> str:
    return """governance:
  - source: "src/*.py"
    adrs:
      - 101
    context: "Source file governance mapping"

couplings:
  - sources:
      - "src/*.py"
    docs:
      - "docs/coupled_soft.md"
    soft: true

architecture:
  - source_patterns:
      - "src/*.py"
    current_docs:
      - "docs/current.md"
    gap_docs:
      - "docs/gaps.md"
    plan_refs:
      - "docs/plan-ref.md"

adrs:
  "101":
    title: "Track implementation context"
    file: "adrs/adr-0101.md"
"""


def _relationships_config_empty() -> str:
    return """required_reading:
  defaults: []
governance: []
couplings: []
architecture: []
adrs: {}
"""


def _valid_integrity_plan() -> str:
    return """# Plan #1: Exact integrity fixture

## User Outcome

An operator can start one governed lane from an inspectable complete plan.

## Canonical Behavioral Example

**Starting state:** A committed plan and configuration select enforcement.
**Action:** The operator starts the governed implementation lane.
**Expected result:** Admission returns a digest-bound structural pass.
**Failure signal:** Any missing declared field is named before mutation.

## Capability Adoption

**Disposition:** reuse

Reuse the canonical plan admission seam.

## Plan

**Critical-path classification: vertical.** Prove the admission boundary.

## Acceptance Criteria

1. The incomplete plan is rejected before coordination mutation.

## Epistemic Planning Frontier

| Area | State | Current contract | Trigger or stopping rule | Downstream update |
|---|---|---|---|---|
| Exact admission | fully_specifiable_now | Parse committed plan bytes | Stop after both signs discriminate | Update the admission receipt |
| Consumer variance | exploration_required | Inspect one installed consumer | Stop after one exact installed run | Update the consumer plan |

## Reassessment Contract

- **Triggers:** A plan assumption fails or the consumer differs.
- **Autonomous action:** Change reversible implementation tactics.
- **Plan revision required:** Change the outcome, contract, or declared frontier.
- **Human decision required:** Cross a scope, authority, irreversible, or spend boundary.
- **Stopping rule:** Stop after one installed both-sign proof.
"""


def test_validate_plan_detects_missing_strict_docs_and_adr(tmp_path: Path) -> None:
    module = _load_module()
    plan_file = tmp_path / "01_sample.md"
    config_file = tmp_path / "relationships.yaml"
    config_file.write_text(_relationships_config(), encoding="utf-8")

    plan_file.write_text(
        "\n".join(
            [
                "# Sample Plan",
                "**Status:** Draft",
                "",
                "## Files Affected",
                "- src/module.py",
                "",
                "## References Reviewed",
                "- docs/current.md",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.validate_plan(
        plan_file=plan_file,
        plan_number=1,
        relationships=module.load_relationships(config_path=config_file),
    )

    assert result.missing_strict == {"docs/gaps.md", "docs/plan-ref.md"}
    assert result.missing_soft == {"docs/coupled_soft.md"}
    assert result.missing_adrs == [(101, "Track implementation context")]


def test_validate_plan_accepts_file_when_references_and_adr_mentioned(tmp_path: Path) -> None:
    module = _load_module()
    plan_file = tmp_path / "02_sample.md"
    config_file = tmp_path / "relationships.yaml"
    config_file.write_text(_relationships_config(), encoding="utf-8")

    plan_file.write_text(
        "\n".join(
            [
                "# Sample Plan",
                "**Status:** In progress",
                "",
                "## Files Affected",
                "- src/module.py",
                "",
                "## References Reviewed",
                "- docs/current.md",
                "- docs/gaps.md",
                "- docs/plan-ref.md",
                "",
                "We considered ADR-0101 before implementing.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.validate_plan(
        plan_file=plan_file,
        plan_number=2,
        relationships=module.load_relationships(config_path=config_file),
    )

    assert result.missing_strict == set()
    assert result.missing_soft == {"docs/coupled_soft.md"}
    assert result.missing_adrs == []


def test_validate_plan_cli_warn_only_honors_non_blocking_exit(tmp_path: Path) -> None:
    plan_file = tmp_path / "03_sample.md"
    config_file = tmp_path / "relationships.yaml"
    config_file.write_text(_relationships_config(), encoding="utf-8")

    plan_file.write_text(
        "# Sample Plan\n"
        "**Status:** Draft\n\n"
        "## Files Affected\n"
        "- src/module.py\n\n"
        "## References Reviewed\n"
        "- docs/current.md\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATE_PLAN_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--plan-file",
            str(plan_file),
            "--config",
            str(config_file),
            "--warn-only",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "GAPS FOUND" in result.stdout


def test_validate_plan_cli_emits_json_payload(tmp_path: Path) -> None:
    plan_file = tmp_path / "04_sample.md"
    config_file = tmp_path / "relationships.yaml"
    config_file.write_text(_relationships_config(), encoding="utf-8")

    plan_file.write_text(
        "# Sample Plan\n"
        "**Status:** Draft\n\n"
        "## Gap\n"
        "Current: missing feature. Target: have feature.\n\n"
        "## Files Affected\n"
        "- src/module.py\n\n"
        "## References Reviewed\n"
        "- docs/current.md\n"
        "- docs/gaps.md\n"
        "- docs/plan-ref.md\n"
        "ADR-0101 is the related governance ADR.\n\n"
        "## Acceptance Criteria\n"
        "- [ ] Feature works end to end\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATE_PLAN_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--plan-file",
            str(plan_file),
            "--config",
            str(config_file),
            "--json",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["plan_file"] == str(plan_file)
    assert payload["required_docs"]["strict"] == [
        "docs/current.md",
        "docs/gaps.md",
        "docs/plan-ref.md",
    ]
    assert payload["required_docs"]["soft"] == ["docs/coupled_soft.md"]
    assert payload["missing_adrs"] == []
    assert payload["landscape"] == {"disposition": None, "references": []}
    assert any(warning["code"] == "missing_landscape_disposition" for warning in payload["warnings"])


def test_validate_plan_module_uses_repo_root_not_scripts_dir() -> None:
    """Validator modules should resolve the repo root, not scripts/."""

    validate_module = _load_module()
    file_context_module = _load_file_context_module()

    assert validate_module.ROOT == REPO_ROOT
    assert file_context_module.REPO_ROOT == REPO_ROOT


def test_parse_plan_status_strips_markdown_emphasis() -> None:
    module = _load_module()

    cases = {
        "# Plan\n**Status:** Working plan\n": "Working plan",
        "# Plan\n**Status**: Complete\n": "Complete",
        "# Plan\n*Status:* Draft\n": "Draft",
        "# Plan\nStatus: Planned\n": "Planned",
    }

    for content, expected in cases.items():
        _, status = module.parse_plan_status(content)
        assert status == expected


def test_validate_plan_reports_research_citation_warnings(tmp_path: Path) -> None:
    module = _load_module()
    plan_file = tmp_path / "05_sample.md"
    config_file = tmp_path / "relationships.yaml"
    config_file.write_text(_relationships_config(), encoding="utf-8")

    plan_file.write_text(
        "\n".join(
            [
                "# Sample Plan",
                "**Status:** Draft",
                "**research_citations:** [bad-entry, bad-entry]",
                "",
                "## Gap",
                "Current: something. Target: better. Why: provenance matters.",
                "",
                "## Files Affected",
                "- src/module.py",
                "",
                "## References Reviewed",
                "- docs/current.md",
                "- Memory context: `agent-memory recall 'topic' --project repo` — 2 findings",
                "",
                "## Acceptance Criteria",
                "- [ ] Document provenance",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.validate_plan(
        plan_file=plan_file,
        plan_number=5,
        relationships=module.load_relationships(config_path=config_file),
    )

    warning_codes = {warning["code"] for warning in result.warnings}
    assert "invalid_research_citation_entry" in warning_codes
    assert "duplicate_research_citation" in warning_codes
    assert "missing_research_citations" not in warning_codes
    assert result.research_citations == ["bad-entry", "bad-entry"]


def test_validate_plan_warns_when_prior_session_provenance_lacks_citations(tmp_path: Path) -> None:
    module = _load_module()
    plan_file = tmp_path / "06_sample.md"
    config_file = tmp_path / "relationships.yaml"
    config_file.write_text(_relationships_config(), encoding="utf-8")

    plan_file.write_text(
        "\n".join(
            [
                "# Sample Plan",
                "**Status:** Draft",
                "**research_citations:** []",
                "",
                "## Gap",
                "Current: something. Target: better. Why: provenance matters.",
                "",
                "## Files Affected",
                "- src/module.py",
                "",
                "## References Reviewed",
                "- docs/current.md",
                "- confirmed via direct DB query in prior session",
                "",
                "## Acceptance Criteria",
                "- [ ] Document provenance",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.validate_plan(
        plan_file=plan_file,
        plan_number=6,
        relationships=module.load_relationships(config_path=config_file),
    )

    assert any(warning["code"] == "missing_research_citations" for warning in result.warnings)
    payload = result.to_payload()
    assert any(warning["code"] == "missing_research_citations" for warning in payload["warnings"])


def test_validate_plan_reports_missing_outcome_first_contract(tmp_path: Path) -> None:
    """Outcome omissions are visible without becoming legacy-plan hard failures."""

    module = _load_module()
    plan_file = tmp_path / "07_sample.md"
    config_file = tmp_path / "relationships.yaml"
    config_file.write_text(_relationships_config_empty(), encoding="utf-8")
    plan_file.write_text(
        "# Sample Plan\n"
        "**Status:** Draft\n"
        "**Landscape disposition:** linked\n\n"
        "## Gap\nCurrent: no behavior. Target: behavior. Why: users need it.\n\n"
        "## References Reviewed\n- `src/module.py`\n\n"
        "## Plan\n### Steps\n1. Add infrastructure\n\n"
        "## Acceptance Criteria\n- [ ] Tests pass\n",
        encoding="utf-8",
    )

    result = module.validate_plan(
        plan_file=plan_file,
        plan_number=7,
        relationships=module.load_relationships(config_path=config_file),
    )

    warning_codes = {warning["code"] for warning in result.warnings}
    assert {
        "missing_user_outcome",
        "missing_canonical_behavioral_example",
        "missing_critical_path_classification",
        "missing_capability_adoption",
    } <= warning_codes
    assert result.missing_sections == []


def test_validate_plan_accepts_outcome_first_contract(tmp_path: Path) -> None:
    """A concrete outcome, example, and classification remove rollout warnings."""

    module = _load_module()
    plan_file = tmp_path / "08_sample.md"
    config_file = tmp_path / "relationships.yaml"
    config_file.write_text(_relationships_config_empty(), encoding="utf-8")
    plan_file.write_text(
        "# Sample Plan\n"
        "**Status:** Draft\n"
        "**Landscape disposition:** linked\n\n"
        "## Gap\nCurrent: names split. Target: linked mentions. Why: retrieval.\n\n"
        "## User Outcome\nA reader can retrieve every passage about Jane.\n\n"
        "## Canonical Behavioral Example\n"
        "Input: Jane introduces herself, then says I later. Action: query Jane. "
        "Result: both passages are returned.\n\n"
        "## References Reviewed\n- `src/module.py`\n\n"
        "## Capability Adoption\n"
        "Disposition: none. No existing capability owns this bounded concern.\n\n"
        "## Plan\n### Critical Path Classification\n"
        "| Increment | Class | Change |\n|---|---|---|\n"
        "| Coreference path | `vertical` | Query works |\n\n"
        "## Acceptance Criteria\n- [ ] Example works end to end\n",
        encoding="utf-8",
    )

    result = module.validate_plan(
        plan_file=plan_file,
        plan_number=8,
        relationships=module.load_relationships(config_path=config_file),
    )

    warning_codes = {warning["code"] for warning in result.warnings}
    assert "missing_user_outcome" not in warning_codes
    assert "missing_canonical_behavioral_example" not in warning_codes
    assert "missing_critical_path_classification" not in warning_codes
    assert "missing_capability_adoption" not in warning_codes
    assert "missing_capability_adoption_disposition" not in warning_codes


def test_validate_plan_exempts_trivial_change_from_outcome_first_contract(tmp_path: Path) -> None:
    """A declared trivial local change is not forced into product-plan ceremony."""

    module = _load_module()
    plan_file = tmp_path / "09_sample.md"
    config_file = tmp_path / "relationships.yaml"
    config_file.write_text(_relationships_config_empty(), encoding="utf-8")
    plan_file.write_text(
        "# Sample Plan\n"
        "**Status:** Draft\n"
        "**Landscape disposition:** exempt-trivial\n\n"
        "## Gap\nCurrent: typo. Target: fixed typo. Why: clarity.\n\n"
        "## References Reviewed\n- `README.md`\n\n"
        "## Landscape And Prior Art\nReason: one local documentation typo.\n\n"
        "## Acceptance Criteria\n- [ ] Typo is fixed\n",
        encoding="utf-8",
    )

    result = module.validate_plan(
        plan_file=plan_file,
        plan_number=9,
        relationships=module.load_relationships(config_path=config_file),
    )

    warning_codes = {warning["code"] for warning in result.warnings}
    assert "missing_user_outcome" not in warning_codes
    assert "missing_canonical_behavioral_example" not in warning_codes
    assert "missing_critical_path_classification" not in warning_codes


def test_validate_plan_exempts_design_plan_from_behavioral_contract(tmp_path: Path) -> None:
    """Design plans do not claim implemented behavior and need no runnable example."""

    module = _load_module()
    plan_file = tmp_path / "10_sample.md"
    config_file = tmp_path / "relationships.yaml"
    config_file.write_text(_relationships_config_empty(), encoding="utf-8")
    plan_file.write_text(
        "# Design Plan\n"
        "**Status:** Draft\n"
        "**Type:** design\n"
        "**Landscape disposition:** linked\n\n"
        "## Gap\nCurrent: unclear boundary. Target: a decision. Why: scope.\n\n"
        "## References Reviewed\n- `src/module.py`\n\n"
        "## Acceptance Criteria\n- [ ] Boundary decision is recorded\n",
        encoding="utf-8",
    )

    result = module.validate_plan(
        plan_file=plan_file,
        plan_number=10,
        relationships=module.load_relationships(config_path=config_file),
    )

    warning_codes = {warning["code"] for warning in result.warnings}
    assert "missing_user_outcome" not in warning_codes
    assert "missing_canonical_behavioral_example" not in warning_codes
    assert "missing_critical_path_classification" not in warning_codes


def _landscape_plan(disposition: str, section: str) -> str:
    """Build a structurally valid plan around one landscape test case."""
    return (
        "\n".join(
            [
                "# Landscape Plan",
                "**Status:** Draft",
                f"**Landscape disposition:** {disposition}",
                "",
                "## Gap",
                "Current: landscape is implicit. Target: landscape is explicit.",
                "",
                "## References Reviewed",
                "- CLAUDE.md",
                "",
                "## Landscape And Prior Art",
                section,
                "",
                "## Acceptance Criteria",
                "- [ ] Landscape disposition is visible",
            ]
        )
        + "\n"
    )


def _validate_landscape(tmp_path: Path, disposition: str, section: str):
    """Validate one landscape fixture with an empty relationship graph."""
    module = _load_module()
    plan_file = tmp_path / "landscape.md"
    config_file = tmp_path / "relationships.yaml"
    plan_file.write_text(_landscape_plan(disposition, section), encoding="utf-8")
    config_file.write_text(_relationships_config_empty(), encoding="utf-8")
    return module.validate_plan(
        plan_file=plan_file,
        plan_number=101,
        relationships=module.load_relationships(config_path=config_file),
    )


def test_validate_plan_accepts_linked_landscape_and_projects_it_to_json(tmp_path: Path) -> None:
    result = _validate_landscape(
        tmp_path,
        "linked",
        "- `docs/research/runtime-landscape.md` - compared available runtimes",
    )

    assert result.landscape_disposition == "linked"
    assert result.landscape_references == ["docs/research/runtime-landscape.md"]
    assert not [warning for warning in result.warnings if "landscape" in warning["code"]]
    assert result.to_payload()["landscape"] == {
        "disposition": "linked",
        "references": ["docs/research/runtime-landscape.md"],
    }

    url_result = _validate_landscape(
        tmp_path,
        "linked",
        "- https://example.com/runtime-prior-art - external comparison",
    )
    assert url_result.landscape_references == ["https://example.com/runtime-prior-art"]
    assert not [warning for warning in url_result.warnings if "landscape" in warning["code"]]


def test_validate_plan_warns_when_linked_landscape_has_no_reference(tmp_path: Path) -> None:
    result = _validate_landscape(
        tmp_path,
        "linked",
        "We discussed the available choices but did not retain a source.",
    )

    assert any(warning["code"] == "missing_landscape_reference" for warning in result.warnings)


def test_validate_plan_accepts_complete_inline_landscape(tmp_path: Path) -> None:
    result = _validate_landscape(
        tmp_path,
        "inline",
        "**Alternatives:** adopt, extend, or build.\n\n"
        "**Project implications:** adopt the stable interface and retain an adapter.",
    )

    assert not [warning for warning in result.warnings if "landscape" in warning["code"]]


def test_validate_plan_warns_when_inline_landscape_omits_implications(tmp_path: Path) -> None:
    result = _validate_landscape(
        tmp_path,
        "inline",
        "**Alternatives:** adopt, extend, or build.",
    )

    assert any(warning["code"] == "incomplete_inline_landscape" for warning in result.warnings)


def test_validate_plan_accepts_reasoned_trivial_exemption(tmp_path: Path) -> None:
    result = _validate_landscape(
        tmp_path,
        "exempt-trivial",
        "**Reason:** This is a local typo correction with no design choice.",
    )

    assert not [warning for warning in result.warnings if "landscape" in warning["code"]]


def test_validate_plan_warns_on_bare_trivial_exemption(tmp_path: Path) -> None:
    result = _validate_landscape(tmp_path, "exempt-trivial", "Not needed.")

    assert any(warning["code"] == "weak_landscape_exemption" for warning in result.warnings)


def test_validate_plan_warns_on_missing_or_invalid_landscape_disposition(tmp_path: Path) -> None:
    missing = _validate_landscape(tmp_path, "", "**Reason:** no declaration")
    invalid = _validate_landscape(tmp_path, "complete", "**Reason:** unknown state")

    assert any(warning["code"] == "missing_landscape_disposition" for warning in missing.warnings)
    assert any(warning["code"] == "invalid_landscape_disposition" for warning in invalid.warnings)


def test_file_context_includes_required_reading_defaults(tmp_path: Path) -> None:
    """File context should include repo-wide required-reading defaults."""

    file_context_module = _load_file_context_module()
    config_file = tmp_path / "relationships.yaml"
    config_file.write_text(
        "\n".join(
            [
                "required_reading:",
                "  defaults:",
                "    - CLAUDE.md",
                "couplings: []",
                "governance: []",
                "architecture: []",
                "adrs: {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    context = file_context_module.collect_context(
        "scripts/example.py",
        file_context_module.load_relationships(config_path=config_file),
    )

    assert context.required_reads == ["CLAUDE.md"]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _doc_spine_authority_config() -> str:
    return """schema_version: 2
indexed_authority_surfaces: []
doc_spine:
  root_doc: EXECUTION_BRIEF.md
  required_concerns: [execution_brief, current_state, gap_summary]
role_budgets: {}
docs:
  - path: EXECUTION_BRIEF.md
    authority: canonical
    doc_status: active
    concerns: [execution_brief]
    role: execution_brief
    primary_parent: null
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
        reason: Gap summary needs current state.
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


def test_validate_plan_requires_doc_spine_closure_for_managed_surface(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    config_file = repo_root / "relationships.yaml"
    authority_file = repo_root / "scripts/doc_authority.yaml"
    plan_file = repo_root / "docs/plans/07_sample.md"

    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(_relationships_config_empty(), encoding="utf-8")
    authority_file.parent.mkdir(parents=True, exist_ok=True)
    authority_file.write_text(_doc_spine_authority_config(), encoding="utf-8")
    _write(repo_root / "EXECUTION_BRIEF.md", "brief\n")
    _write(repo_root / "docs/overview/CURRENT_STATE.md", "current\n")
    _write(repo_root / "docs/overview/GAP_SUMMARY.md", "gap\n")
    _write(repo_root / "docs/plans/55_test.md", "plan\n")
    _write(repo_root / "src/module.py", "code\n")

    plan_file.write_text(
        "\n".join(
            [
                "# Sample Plan",
                "**Status:** Draft",
                "",
                "## Gap",
                "Current: something. Target: better. Why: needed.",
                "",
                "## Files Affected",
                "- src/module.py",
                "",
                "## References Reviewed",
                "- src/module.py",
                "",
                "## Acceptance Criteria",
                "- [ ] Implement closure",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.validate_plan(
        plan_file=plan_file,
        plan_number=7,
        relationships=module.load_relationships(config_path=config_file),
        repo_root=repo_root,
        authority_config_path=authority_file,
    )

    assert {
        "docs/plans/55_test.md",
        "docs/overview/GAP_SUMMARY.md",
        "EXECUTION_BRIEF.md",
        "docs/overview/CURRENT_STATE.md",
    }.issubset(result.missing_strict)


def test_validate_plan_accepts_plan_when_doc_spine_closure_is_cited(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    config_file = repo_root / "relationships.yaml"
    authority_file = repo_root / "scripts/doc_authority.yaml"
    plan_file = repo_root / "docs/plans/08_sample.md"

    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(_relationships_config_empty(), encoding="utf-8")
    authority_file.parent.mkdir(parents=True, exist_ok=True)
    authority_file.write_text(_doc_spine_authority_config(), encoding="utf-8")
    _write(repo_root / "EXECUTION_BRIEF.md", "brief\n")
    _write(repo_root / "docs/overview/CURRENT_STATE.md", "current\n")
    _write(repo_root / "docs/overview/GAP_SUMMARY.md", "gap\n")
    _write(repo_root / "docs/plans/55_test.md", "plan\n")
    _write(repo_root / "src/module.py", "code\n")

    plan_file.write_text(
        "\n".join(
            [
                "# Sample Plan",
                "**Status:** Draft",
                "",
                "## Gap",
                "Current: something. Target: better. Why: needed.",
                "",
                "## Files Affected",
                "- src/module.py",
                "",
                "## References Reviewed",
                "- src/module.py",
                "- docs/plans/55_test.md",
                "- docs/overview/GAP_SUMMARY.md",
                "- EXECUTION_BRIEF.md",
                "- docs/overview/CURRENT_STATE.md",
                "",
                "## Acceptance Criteria",
                "- [ ] Implement closure",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.validate_plan(
        plan_file=plan_file,
        plan_number=8,
        relationships=module.load_relationships(config_path=config_file),
        repo_root=repo_root,
        authority_config_path=authority_file,
    )

    assert result.missing_strict == set()


def test_extract_inline_paths_preserves_multi_dot_filenames() -> None:
    """Validator path extraction should keep dotted template filenames intact."""

    module = _load_module()
    line = "- templates/CLAUDE.md.docs-adr (modify)"

    paths = module.extract_inline_paths(line)

    assert "templates/CLAUDE.md.docs-adr" in paths


def test_planning_integrity_complete_declared_structure_passes() -> None:
    module = _load_module()
    plan_bytes = _valid_integrity_plan().encode("utf-8")
    result = module.evaluate_plan_integrity_bytes(
        plan_bytes=plan_bytes,
        plan_path="docs/plans/1_fixture.md",
        plan_number=1,
        repository_id="fixture",
        config=module.PlanningIntegrityConfigV1(mode="enforce"),
        config_sha256="a" * 64,
    )

    assert result.disposition == "pass"
    assert result.findings == []
    assert [row.state for row in result.frontier] == [
        "fully_specifiable_now",
        "exploration_required",
    ]
    assert result.acceptance_criteria == ["The incomplete plan is rejected before coordination mutation."]
    assert result.coverage_nonclaim == module.PLANNING_INTEGRITY_COVERAGE_NONCLAIM
    assert result.plan_sha256 == hashlib.sha256(plan_bytes).hexdigest()


@pytest.mark.parametrize(
    ("mutated", "expected_code"),
    [
        (
            _valid_integrity_plan().replace("## Epistemic Planning Frontier", "## Omitted Frontier"),
            "missing_epistemic_frontier",
        ),
        (
            _valid_integrity_plan().replace("exploration_required", "invented_state", 1),
            "invalid_frontier_state",
        ),
        (
            _valid_integrity_plan().replace("| Consumer variance |", "| Exact admission |"),
            "duplicate_frontier_area",
        ),
        (
            _valid_integrity_plan().replace("- **Stopping rule:**", "- **Missing stop:**"),
            "invalid_reassessment_contract",
        ),
        (
            _valid_integrity_plan().replace(
                "## Acceptance Criteria\n\n1. The incomplete plan is rejected before coordination mutation.\n\n",
                "",
            ),
            "missing_acceptance_criteria",
        ),
    ],
)
def test_planning_integrity_malformed_contracts_discriminate(
    mutated: str,
    expected_code: str,
) -> None:
    module = _load_module()
    result = module.evaluate_plan_integrity_bytes(
        plan_bytes=mutated.encode("utf-8"),
        plan_path="docs/plans/1_fixture.md",
        plan_number=1,
        repository_id="fixture",
        config=module.PlanningIntegrityConfigV1(mode="enforce"),
        config_sha256="b" * 64,
    )

    assert result.disposition == "fail"
    assert expected_code in {item.code for item in result.findings}


@pytest.mark.parametrize(
    ("mutated", "expected_code"),
    [
        (
            _valid_integrity_plan() + "\n## User Outcome\n\nA conflicting later outcome silently replaces nothing.\n",
            "duplicate_governed_heading",
        ),
        (
            _valid_integrity_plan()
            + "\n   ## User Outcome ##\n\nA closing-hash heading is still the same governed section.\n",
            "duplicate_governed_heading",
        ),
        (
            _valid_integrity_plan().replace(
                "**Failure signal:** Any missing declared field is named before mutation.",
                "**Failure signal:** Any missing declared field is named before mutation.\n"
                "**Failure signal:** A second declaration must not be silently accepted.",
            ),
            "duplicate_governed_field",
        ),
    ],
)
def test_planning_integrity_rejects_ambiguous_governed_structure(
    mutated: str,
    expected_code: str,
) -> None:
    module = _load_module()
    result = module.evaluate_plan_integrity_bytes(
        plan_bytes=mutated.encode("utf-8"),
        plan_path="docs/plans/1_fixture.md",
        plan_number=1,
        repository_id="fixture",
        config=module.PlanningIntegrityConfigV1(mode="enforce"),
        config_sha256="b" * 64,
    )

    assert result.disposition == "fail"
    assert expected_code in {item.code for item in result.findings}


def test_planning_integrity_retains_legacy_inline_disposition_compatibility() -> None:
    """Existing plans may retain the old inline-bold value while templates use the canonical field form."""

    module = _load_module()
    plan = _valid_integrity_plan().replace(
        "**Disposition:** reuse\n\nReuse the canonical plan admission seam.",
        "**Disposition: reuse.** Reuse the canonical plan admission seam.",
    )

    result = module.evaluate_plan_integrity_bytes(
        plan_bytes=plan.encode("utf-8"),
        plan_path="docs/plans/1_fixture.md",
        plan_number=1,
        repository_id="fixture",
        config=module.PlanningIntegrityConfigV1(mode="enforce"),
        config_sha256="b" * 64,
    )

    assert result.disposition == "pass"
    assert result.capability_disposition == "reuse"


def test_unfilled_canonical_plan_template_cannot_pass_integrity() -> None:
    module = _load_module()
    template = (REPO_ROOT / "templates" / "plan.md.template").read_bytes()
    result = module.evaluate_plan_integrity_bytes(
        plan_bytes=template,
        plan_path="docs/plans/1_template.md",
        plan_number=1,
        repository_id="fixture",
        config=module.PlanningIntegrityConfigV1(mode="enforce"),
        config_sha256="c" * 64,
    )

    assert result.disposition == "fail"
    assert {
        "missing_user_outcome",
        "invalid_canonical_behavioral_example",
        "missing_critical_path_classification",
        "missing_capability_adoption_disposition",
        "missing_acceptance_criteria",
        "invalid_frontier_row",
        "invalid_reassessment_contract",
    } <= {item.code for item in result.findings}


def test_planning_integrity_rejects_duplicate_config_keys() -> None:
    module = _load_module()
    config = b"""meta_process:
  plans:
    integrity:
      mode: off
      mode: enforce
      contract_version: 1.0.0
      minimum_plan_number: 1
"""

    with pytest.raises(module.PlanningIntegrityError, match="duplicate YAML key"):
        module.parse_planning_integrity_config_bytes(config)


def test_planning_integrity_rejects_coerced_config_types() -> None:
    module = _load_module()
    config = b"""meta_process:
  plans:
    integrity:
      mode: enforce
      contract_version: 1.0.0
      minimum_plan_number: "1"
"""

    with pytest.raises(module.PlanningIntegrityError, match="minimum_plan_number"):
        module.parse_planning_integrity_config_bytes(config)


@pytest.mark.parametrize("plans_dir", ["/tmp/plans", "../plans", "docs/../../plans", "C:/plans"])
def test_planning_integrity_rejects_nonportable_plan_directories(plans_dir: str) -> None:
    module = _load_module()
    config = (
        "meta_process:\n"
        "  plans:\n"
        f"    plans_dir: {plans_dir}\n"
        "    integrity:\n"
        "      mode: enforce\n"
        "      contract_version: 1.0.0\n"
        "      minimum_plan_number: 1\n"
    ).encode()

    with pytest.raises(module.PlanningIntegrityError, match="repository-relative"):
        module.parse_planning_integrity_config_bytes(config)


@pytest.mark.parametrize("mode", ["off", "observe", "enforce"])
def test_planning_integrity_preserves_configured_mode(mode: str) -> None:
    module = _load_module()
    result = module.evaluate_plan_integrity_bytes(
        plan_bytes=b"# Incomplete\n",
        plan_path="docs/plans/1_incomplete.md",
        plan_number=1,
        repository_id="fixture",
        config=module.PlanningIntegrityConfigV1(mode=mode),
        config_sha256="d" * 64,
    )

    assert result.mode == mode
    assert result.disposition == ("not_applicable" if mode == "off" else "fail")


def test_planning_integrity_preserves_adoption_floor_compatibility() -> None:
    module = _load_module()
    result = module.evaluate_plan_integrity_bytes(
        plan_bytes=b"# Historical incomplete plan\n",
        plan_path="docs/plans/124_historical.md",
        plan_number=124,
        repository_id="fixture",
        config=module.PlanningIntegrityConfigV1(
            mode="enforce",
            minimum_plan_number=125,
        ),
        config_sha256="e" * 64,
    )

    assert result.disposition == "not_applicable"
    assert result.findings == []


def test_planning_integrity_rejects_unsupported_contract_version() -> None:
    module = _load_module()
    result = module.evaluate_plan_integrity_bytes(
        plan_bytes=_valid_integrity_plan().encode(),
        plan_path="docs/plans/1_complete.md",
        plan_number=1,
        repository_id="fixture",
        config=module.PlanningIntegrityConfigV1(
            mode="enforce",
            contract_version="2.0.0",
        ),
        config_sha256="f" * 64,
    )

    assert result.disposition == "fail"
    assert {item.code for item in result.findings} == {"unsupported_contract_version"}


def test_plan_digest_binds_raw_bytes_before_newline_decoding() -> None:
    module = _load_module()
    config = module.PlanningIntegrityConfigV1(mode="enforce")
    lf = _valid_integrity_plan().encode("utf-8")
    crlf = lf.replace(b"\n", b"\r\n")

    lf_result = module.evaluate_plan_integrity_bytes(
        plan_bytes=lf,
        plan_path="docs/plans/1_fixture.md",
        plan_number=1,
        repository_id="fixture",
        config=config,
        config_sha256="d" * 64,
    )
    crlf_result = module.evaluate_plan_integrity_bytes(
        plan_bytes=crlf,
        plan_path="docs/plans/1_fixture.md",
        plan_number=1,
        repository_id="fixture",
        config=config,
        config_sha256="d" * 64,
    )

    assert lf_result.disposition == crlf_result.disposition == "pass"
    assert lf_result.plan_sha256 != crlf_result.plan_sha256
    assert lf_result.validator_source_sha256 == crlf_result.validator_source_sha256


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_revision_validation_ignores_complete_dirty_worktree_bytes(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "docs/plans").mkdir(parents=True)
    (repo / "meta-process.yaml").write_text(
        "meta_process:\n  plans:\n    plans_dir: docs/plans\n    integrity:\n      mode: enforce\n      contract_version: 1.0.0\n      minimum_plan_number: 1\n",
        encoding="utf-8",
    )
    plan_path = repo / "docs/plans/1_fixture.md"
    committed_bytes = b"# Incomplete committed plan\n"
    plan_path.write_bytes(committed_bytes)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "incomplete plan")
    plan_path.write_text(_valid_integrity_plan(), encoding="utf-8")

    result = module.validate_plan_integrity_at_revision(
        repo_root=repo,
        repository_id="fixture",
        plan_number=1,
        start_point="HEAD",
    )

    assert result.disposition == "fail"
    assert result.plan_sha256 == hashlib.sha256(committed_bytes).hexdigest()
    assert "missing_epistemic_frontier" in {item.code for item in result.findings}


def test_revision_validation_rejects_ambiguous_numeric_plan_files(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "docs/plans").mkdir(parents=True)
    (repo / "meta-process.yaml").write_text(
        "meta_process:\n  plans:\n    integrity:\n      mode: enforce\n      contract_version: 1.0.0\n      minimum_plan_number: 1\n",
        encoding="utf-8",
    )
    for name in ("1_first.md", "01_duplicate.md"):
        (repo / "docs/plans" / name).write_text(_valid_integrity_plan(), encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "ambiguous plans")

    result = module.validate_plan_integrity_at_revision(
        repo_root=repo,
        repository_id="fixture",
        plan_number=1,
    )

    assert result.disposition == "fail"
    assert result.findings[0].code == "ambiguous_plan_identity"


def test_warn_only_cannot_neutralize_enforced_integrity(tmp_path: Path) -> None:
    plan_file = tmp_path / "docs/plans/1_incomplete.md"
    plan_file.parent.mkdir(parents=True)
    plan_file.write_text("# Incomplete plan\n", encoding="utf-8")
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n  plans:\n    integrity:\n      mode: enforce\n      contract_version: 1.0.0\n      minimum_plan_number: 1\n",
        encoding="utf-8",
    )
    relationships = tmp_path / "relationships.yaml"
    relationships.write_text(_relationships_config_empty(), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATE_PLAN_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--plan-file",
            str(plan_file),
            "--plan",
            "1",
            "--config",
            str(relationships),
            "--warn-only",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "missing_user_outcome" in result.stdout
