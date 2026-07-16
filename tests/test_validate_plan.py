import json
import subprocess
import sys
from pathlib import Path


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
    assert any(
        warning["code"] == "missing_landscape_disposition"
        for warning in payload["warnings"]
    )


def test_validate_plan_module_uses_repo_root_not_scripts_dir() -> None:
    """Validator modules should resolve the repo root, not scripts/."""

    validate_module = _load_module()
    file_context_module = _load_file_context_module()

    assert validate_module.ROOT == REPO_ROOT
    assert file_context_module.REPO_ROOT == REPO_ROOT


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

    assert any(
        warning["code"] == "missing_research_citations"
        for warning in result.warnings
    )
    payload = result.to_payload()
    assert any(
        warning["code"] == "missing_research_citations"
        for warning in payload["warnings"]
    )


def _landscape_plan(disposition: str, section: str) -> str:
    """Build a structurally valid plan around one landscape test case."""
    return "\n".join(
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
    ) + "\n"


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
    assert not [
        warning for warning in url_result.warnings if "landscape" in warning["code"]
    ]


def test_validate_plan_warns_when_linked_landscape_has_no_reference(tmp_path: Path) -> None:
    result = _validate_landscape(
        tmp_path,
        "linked",
        "We discussed the available choices but did not retain a source.",
    )

    assert any(
        warning["code"] == "missing_landscape_reference"
        for warning in result.warnings
    )


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

    assert any(
        warning["code"] == "incomplete_inline_landscape"
        for warning in result.warnings
    )


def test_validate_plan_accepts_reasoned_trivial_exemption(tmp_path: Path) -> None:
    result = _validate_landscape(
        tmp_path,
        "exempt-trivial",
        "**Reason:** This is a local typo correction with no design choice.",
    )

    assert not [warning for warning in result.warnings if "landscape" in warning["code"]]


def test_validate_plan_warns_on_bare_trivial_exemption(tmp_path: Path) -> None:
    result = _validate_landscape(tmp_path, "exempt-trivial", "Not needed.")

    assert any(
        warning["code"] == "weak_landscape_exemption"
        for warning in result.warnings
    )


def test_validate_plan_warns_on_missing_or_invalid_landscape_disposition(tmp_path: Path) -> None:
    missing = _validate_landscape(tmp_path, "", "**Reason:** no declaration")
    invalid = _validate_landscape(tmp_path, "complete", "**Reason:** unknown state")

    assert any(
        warning["code"] == "missing_landscape_disposition"
        for warning in missing.warnings
    )
    assert any(
        warning["code"] == "invalid_landscape_disposition"
        for warning in invalid.warnings
    )


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

    assert {"docs/plans/55_test.md", "docs/overview/GAP_SUMMARY.md", "EXECUTION_BRIEF.md", "docs/overview/CURRENT_STATE.md"}.issubset(result.missing_strict)


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
