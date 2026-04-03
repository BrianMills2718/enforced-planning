from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_file_context_module():
    import importlib.util
    import sys

    module_path = REPO_ROOT / "scripts" / "file_context.py"
    module_name = "file_context_scope_module"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def test_scope_hard_fails_when_managed_file_not_registered(tmp_path: Path) -> None:
    """Managed files with no explicit governance should fail hard by default."""

    module = _load_file_context_module()
    config = tmp_path / "relationships.yaml"
    config.write_text(
        "\n".join(
            [
                "required_reading:",
                "  defaults: []",
                "governance: []",
                "couplings: []",
                "architecture: []",
                "file_scope:",
                "  managed:",
                "    include: [\"**\"]",
                "    mode: hard-fail",
                "  unmanaged:",
                "    mode: warn",
                "adrs: {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    relationships = module.load_relationships(config_path=config)
    reads_file = tmp_path / "reads.txt"
    result = module.check_required_reads("scripts/new_tool.py", relationships, reads_file)

    assert result.scope_violations == ["scripts/new_tool.py"]
    assert result.scope_warnings == []
    assert result.ok is False


def test_missing_file_scope_disables_scope_policy(tmp_path: Path) -> None:
    """Absent file_scope should not hard-fail unregistered files."""

    module = _load_file_context_module()
    config = tmp_path / "relationships.yaml"
    config.write_text(
        "\n".join(
            [
                "required_reading:",
                "  defaults: []",
                "governance: []",
                "couplings: []",
                "architecture: []",
                "adrs: {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    relationships = module.load_relationships(config_path=config)
    reads_file = tmp_path / "reads.txt"
    result = module.check_required_reads("scripts/new_tool.py", relationships, reads_file)

    assert result.scope_violations == []
    assert result.scope_warnings == []
    assert result.ok is True


def test_scope_warns_when_unmanaged_and_unregistered(tmp_path: Path) -> None:
    """Unmanaged files can be configured to warn instead of fail."""

    module = _load_file_context_module()
    config = tmp_path / "relationships.yaml"
    config.write_text(
        "\n".join(
            [
                "required_reading:",
                "  defaults: []",
                "governance: []",
                "couplings: []",
                "architecture: []",
                "file_scope:",
                "  managed:",
                "    include: [\"src/**\"]",
                "  unmanaged:",
                "    mode: warn",
                "adrs: {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    relationships = module.load_relationships(config_path=config)
    reads_file = tmp_path / "reads.txt"
    result = module.check_required_reads("notes/readme.md", relationships, reads_file)

    assert result.scope_violations == []
    assert result.scope_warnings == ["notes/readme.md"]
    assert result.ok is True


def test_scope_respects_directory_excludes_for_managed_files(tmp_path: Path) -> None:
    """Directory excludes in file_scope should remove managed files from hard enforcement."""

    module = _load_file_context_module()
    config = tmp_path / "relationships.yaml"
    config.write_text(
        "\n".join(
            [
                "required_reading:",
                "  defaults: []",
                "governance: []",
                "couplings: []",
                "architecture: []",
                "file_scope:",
                "  managed:",
                "    include: [\"**\"]",
                "    exclude: [\"generated/**\", \"artifacts/**\"]",
                "    mode: hard-fail",
                "  unmanaged:",
                "    mode: warn",
                "adrs: {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    relationships = module.load_relationships(config_path=config)
    reads_file = tmp_path / "reads.txt"

    result_inside_exclude = module.check_required_reads(
        "generated/outputs/batch_report.txt",
        relationships,
        reads_file,
    )
    result_source = module.check_required_reads("src/tool.py", relationships, reads_file)

    assert result_inside_exclude.scope_violations == []
    assert result_inside_exclude.scope_warnings == ["generated/outputs/batch_report.txt"]
    assert result_source.scope_violations == ["src/tool.py"]


def test_scope_respects_directory_excludes_with_trailing_slash(tmp_path: Path) -> None:
    """A plain directory pattern should still count as managed exclude."""

    module = _load_file_context_module()
    config = tmp_path / "relationships.yaml"
    config.write_text(
        "\n".join(
            [
                "required_reading:",
                "  defaults: []",
                "governance: []",
                "couplings: []",
                "architecture: []",
                "file_scope:",
                "  managed:",
                "    include: [\"**\"]",
                "    exclude: [\"artifacts/\"]",
                "    mode: hard-fail",
                "  unmanaged:",
                "    mode: warn",
                "adrs: {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    relationships = module.load_relationships(config_path=config)
    reads_file = tmp_path / "reads.txt"
    result = module.check_required_reads("artifacts/session/log.txt", relationships, reads_file)

    assert result.scope_violations == []
    assert result.scope_warnings == ["artifacts/session/log.txt"]


def test_registered_file_skips_scope_checks(tmp_path: Path) -> None:
    """A file with explicit governance/coupling/architecture registration is exempt."""

    module = _load_file_context_module()
    config = tmp_path / "relationships.yaml"
    config.write_text(
        "\n".join(
            [
                "required_reading:",
                "  defaults: []",
                "governance: []",
                "couplings:",
                "  - sources: [\"scripts/*.py\"]",
                "    docs: [\"docs/known.md\"]",
                "file_scope:",
                "  managed:",
                "    include: [\"**\"]",
                "    mode: hard-fail",
                "  unmanaged:",
                "    mode: warn",
                "adrs: {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    relationships = module.load_relationships(config_path=config)
    reads_file = tmp_path / "reads.txt"
    result = module.check_required_reads("scripts/register.py", relationships, reads_file)

    assert result.scope_violations == []
    assert result.scope_warnings == []
