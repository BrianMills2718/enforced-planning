import subprocess
import sys
from pathlib import Path


PROJECT_META_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_META_ROOT / "scripts" / "check_markdown_links.py"


def _run_checker(target: Path, repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(target),
            "--repo-root",
            str(repo_root),
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def test_markdown_link_checker_passes_valid_links(tmp_path: Path) -> None:
    a_md = tmp_path / "a.md"
    b_md = tmp_path / "b.md"
    a_md.write_text(
        "# Top\n\n- [B](b.md)\n- [Section](b.md#section-one)\n- [Self](#top)\n",
        encoding="utf-8",
    )
    b_md.write_text("# Section One\n", encoding="utf-8")

    proc = _run_checker(a_md, tmp_path)
    assert proc.returncode == 0
    assert "Markdown link integrity OK" in proc.stdout


def test_markdown_link_checker_fails_missing_file(tmp_path: Path) -> None:
    a_md = tmp_path / "a.md"
    a_md.write_text("# Doc\n\n[Missing](missing.md)\n", encoding="utf-8")

    proc = _run_checker(a_md, tmp_path)
    assert proc.returncode == 1
    assert "MARKDOWN_LINK_MISSING_TARGET" in proc.stdout


def test_markdown_link_checker_fails_missing_anchor(tmp_path: Path) -> None:
    a_md = tmp_path / "a.md"
    b_md = tmp_path / "b.md"
    a_md.write_text("# Doc\n\n[Bad Anchor](b.md#does-not-exist)\n", encoding="utf-8")
    b_md.write_text("# Present\n", encoding="utf-8")

    proc = _run_checker(a_md, tmp_path)
    assert proc.returncode == 1
    assert "MARKDOWN_LINK_MISSING_ANCHOR" in proc.stdout


def test_markdown_link_checker_expands_tilde_paths(tmp_path: Path, monkeypatch) -> None:
    home_dir = tmp_path / "home"
    target_md = home_dir / "projects" / "enforced-planning" / "patterns" / "15_plan-workflow.md"
    target_md.parent.mkdir(parents=True, exist_ok=True)
    target_md.write_text("# Plan Workflow\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home_dir))

    a_md = tmp_path / "a.md"
    a_md.write_text(
        "# Doc\n\n[Pattern](~/projects/enforced-planning/patterns/15_plan-workflow.md)\n",
        encoding="utf-8",
    )

    proc = _run_checker(a_md, tmp_path)
    assert proc.returncode == 0
    assert "Markdown link integrity OK" in proc.stdout
