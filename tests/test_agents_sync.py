"""Tests for generated AGENTS.md rendering and drift detection."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RENDER_SCRIPT = REPO_ROOT / "scripts" / "render_agents_md.py"
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_agents_sync.py"


def _load_render_module():
    """Load the AGENTS renderer module directly from disk."""

    module_name = "render_agents_md_test_module"
    spec = importlib.util.spec_from_file_location(module_name, RENDER_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _write_repo_scaffold(repo_root: Path) -> None:
    """Create a minimal governed repo for renderer and sync tests."""

    (repo_root / "scripts").mkdir(parents=True, exist_ok=True)
    (repo_root / "CLAUDE.md").write_text(
        "# Sample Repo\n"
        "\n"
        "This repo proves AGENTS rendering.\n"
        "\n"
        "---\n"
        "\n"
        "## Commands\n"
        "\n"
        "```bash\n"
        "pytest -q\n"
        "```\n"
        "\n"
        "## Principles\n"
        "\n"
        "1. Fail loud.\n"
        "2. Keep one canonical source.\n"
        "\n"
        "## Workflow\n"
        "\n"
        "### Planning\n"
        "- Validate plans before implementation.\n"
        "\n"
        "## References\n"
        "\n"
        "| Doc | Purpose |\n"
        "|-----|---------|\n"
        "| `docs/ARCH.md` | Architecture |\n",
        encoding="utf-8",
    )
    (repo_root / "scripts" / "relationships.yaml").write_text(
        "governance: []\n",
        encoding="utf-8",
    )


def _write_repo_scaffold_with_heading_aliases(repo_root: Path) -> None:
    """Create a governed repo scaffold that uses supported CLAUDE heading aliases."""

    (repo_root / "scripts").mkdir(parents=True, exist_ok=True)
    (repo_root / "CLAUDE.md").write_text(
        "# Sample Repo\n"
        "\n"
        "This repo proves AGENTS rendering with heading aliases.\n"
        "\n"
        "---\n"
        "\n"
        "## Quick Reference - Commands\n"
        "\n"
        "```bash\n"
        "pytest -q\n"
        "```\n"
        "\n"
        "## Design Principles\n"
        "\n"
        "1. Fail loud.\n"
        "2. Keep one canonical source.\n"
        "\n"
        "## Workflow\n"
        "\n"
        "### Planning\n"
        "- Validate plans before implementation.\n"
        "\n"
        "## References\n"
        "\n"
        "| Doc | Purpose |\n"
        "|-----|---------|\n"
        "| `docs/ARCH.md` | Architecture |\n",
        encoding="utf-8",
    )
    (repo_root / "scripts" / "relationships.yaml").write_text(
        "governance: []\n",
        encoding="utf-8",
    )


def test_render_agents_markdown_includes_canonical_sources(tmp_path: Path) -> None:
    """Renderer should emit provenance and canonical-source guidance."""

    module = _load_render_module()
    _write_repo_scaffold(tmp_path)
    inputs = module.resolve_inputs(repo_root=tmp_path)

    rendered = module.render_agents_markdown(inputs)

    assert "<!-- GENERATED FILE: DO NOT EDIT DIRECTLY -->" in rendered
    assert "canonical_claude: CLAUDE.md" in rendered
    assert "canonical_relationships: scripts/relationships.yaml" in rendered
    assert "canonical_relationships_sha256:" in rendered
    assert "This repo proves AGENTS rendering." in rendered
    assert "## Machine-Readable Governance" in rendered
    assert "This generated file does not inline that graph" in rendered


def test_render_agents_markdown_default_template_resolves_to_existing_path() -> None:
    """The renderer should discover a usable default template on clean master."""

    module = _load_render_module()

    assert module.DEFAULT_TEMPLATE.exists()
    assert module.DEFAULT_TEMPLATE.name == "agents.md.template"


def test_render_agents_markdown_accepts_supported_heading_aliases(
    tmp_path: Path,
) -> None:
    """Renderer should accept common CLAUDE heading variants used in governed repos."""

    module = _load_render_module()
    _write_repo_scaffold_with_heading_aliases(tmp_path)
    inputs = module.resolve_inputs(repo_root=tmp_path)

    rendered = module.render_agents_markdown(inputs)

    assert "This repo proves AGENTS rendering with heading aliases." in rendered
    assert "pytest -q" in rendered
    assert "Keep one canonical source." in rendered


def test_render_agents_markdown_falls_back_when_overview_is_missing(
    tmp_path: Path,
) -> None:
    """Renderer should emit a deterministic overview when CLAUDE has no intro block."""

    module = _load_render_module()
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "CLAUDE.md").write_text(
        "# No Overview Repo\n"
        "\n"
        "---\n"
        "\n"
        "## Quick Reference - Commands\n"
        "\n"
        "```bash\n"
        "pytest -q\n"
        "```\n"
        "\n"
        "## Design Principles\n"
        "\n"
        "1. Fail loud.\n"
        "\n"
        "## Workflow\n"
        "\n"
        "- Validate plans before implementation.\n"
        "\n"
        "## References\n"
        "\n"
        "| Doc | Purpose |\n"
        "|-----|---------|\n"
        "| `docs/ARCH.md` | Architecture |\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "relationships.yaml").write_text(
        "governance: []\n",
        encoding="utf-8",
    )

    inputs = module.resolve_inputs(repo_root=tmp_path)
    rendered = module.render_agents_markdown(inputs)

    assert (
        "No Overview Repo uses `CLAUDE.md` as canonical repo governance and "
        "workflow policy."
    ) in rendered


def test_check_agents_sync_detects_relationships_graph_drift(tmp_path: Path) -> None:
    """Sync checker should fail when relationships.yaml changes after render."""

    _write_repo_scaffold(tmp_path)
    subprocess.run(
        [
            sys.executable,
            str(RENDER_SCRIPT),
            "--repo-root",
            str(tmp_path),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )

    (tmp_path / "scripts" / "relationships.yaml").write_text(
        "governance:\n  - source: src/runtime.py\n",
        encoding="utf-8",
    )

    check_result = subprocess.run(
        [
            sys.executable,
            str(CHECK_SCRIPT),
            "--check",
            "--repo-root",
            str(tmp_path),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert check_result.returncode == 1
    assert "AGENTS.md drift detected." in check_result.stdout
    assert "canonical_relationships_sha256" in check_result.stdout


def test_check_agents_sync_detects_stale_generated_file(tmp_path: Path) -> None:
    """Sync checker should fail loudly when AGENTS.md drifts."""

    _write_repo_scaffold(tmp_path)
    render_result = subprocess.run(
        [
            sys.executable,
            str(RENDER_SCRIPT),
            "--repo-root",
            str(tmp_path),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert render_result.returncode == 0

    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text(agents_path.read_text(encoding="utf-8") + "\nmanual drift\n", encoding="utf-8")

    check_result = subprocess.run(
        [
            sys.executable,
            str(CHECK_SCRIPT),
            "--check",
            "--repo-root",
            str(tmp_path),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert check_result.returncode == 1
    assert "AGENTS.md drift detected." in check_result.stdout
    assert "manual drift" in check_result.stdout


def test_check_agents_sync_accepts_clean_generated_file(tmp_path: Path) -> None:
    """Sync checker should pass when AGENTS.md matches canonical inputs."""

    _write_repo_scaffold(tmp_path)
    subprocess.run(
        [
            sys.executable,
            str(RENDER_SCRIPT),
            "--repo-root",
            str(tmp_path),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )

    check_result = subprocess.run(
        [
            sys.executable,
            str(CHECK_SCRIPT),
            "--check",
            "--repo-root",
            str(tmp_path),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert check_result.returncode == 0
    assert "AGENTS.md is in sync" in check_result.stdout


def test_render_agents_md_refuses_symlinked_output_to_claude(tmp_path: Path) -> None:
    """Renderer should fail loudly when AGENTS.md points at CLAUDE.md."""

    _write_repo_scaffold(tmp_path)
    (tmp_path / "AGENTS.md").symlink_to(tmp_path / "CLAUDE.md")

    render_result = subprocess.run(
        [
            sys.executable,
            str(RENDER_SCRIPT),
            "--repo-root",
            str(tmp_path),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert render_result.returncode == 1
    assert "AGENTS output path is a symlink to CLAUDE.md" in render_result.stdout
