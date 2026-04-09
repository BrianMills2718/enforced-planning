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


def test_extract_inline_paths_preserves_multi_dot_filenames() -> None:
    """Validator path extraction should keep dotted template filenames intact."""

    module = _load_module()
    line = "- templates/CLAUDE.md.docs-adr (modify)"

    paths = module.extract_inline_paths(line)

    assert "templates/CLAUDE.md.docs-adr" in paths
