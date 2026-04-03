"""Tests for build_ecosystem_dep_map.py — cross-repo dependency map builder."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_ecosystem_dep_map import build_dep_map, format_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_inferred(gen_dir: Path, repo: str, edges: list[dict]) -> None:
    """Write a minimal inferred_<repo>.json file."""
    data = {"repo": repo, "edges": edges}
    (gen_dir / f"inferred_{repo}.json").write_text(json.dumps(data))


def cross_edge(source: str, target_repo: str, edge_type: str = "python_import") -> dict:
    """Build a cross-project edge dict."""
    return {
        "source": source,
        "target": f"[cross-project:{target_repo}]",
        "type": edge_type,
    }


def local_edge(source: str, target: str, edge_type: str = "markdown_link") -> dict:
    """Build a local (intra-repo) edge dict."""
    return {"source": source, "target": target, "type": edge_type}


# ---------------------------------------------------------------------------
# build_dep_map
# ---------------------------------------------------------------------------

class TestBuildDepMap:
    def test_empty_gen_dir(self, tmp_path):
        result = build_dep_map(tmp_path)
        assert result["repos"] == []
        assert result["total_edges"] == 0
        assert result["cross_repo_edges"] == 0
        assert result["dep_graph"] == {}
        assert result["reverse_graph"] == {}

    def test_single_repo_no_cross_deps(self, tmp_path):
        make_inferred(tmp_path, "my-repo", [
            local_edge("a.py", "b.py"),
            local_edge("b.py", "c.py"),
        ])
        result = build_dep_map(tmp_path)
        assert result["repos"] == ["my-repo"]
        assert result["total_edges"] == 2
        assert result["cross_repo_edges"] == 0
        assert result["dep_graph"]["my-repo"]["depends_on"] == {}

    def test_single_repo_with_cross_dep(self, tmp_path):
        make_inferred(tmp_path, "consumer", [
            local_edge("a.py", "b.py"),
            cross_edge("a.py", "llm_client"),
            cross_edge("b.py", "llm_client"),
        ])
        result = build_dep_map(tmp_path)
        assert result["cross_repo_edges"] == 2
        assert result["dep_graph"]["consumer"]["depends_on"] == {"llm_client": 2}
        assert result["dep_graph"]["consumer"]["cross_repo_edges"] == 2

    def test_reverse_graph_built(self, tmp_path):
        make_inferred(tmp_path, "consumer", [
            cross_edge("a.py", "llm_client"),
        ])
        result = build_dep_map(tmp_path)
        assert "llm_client" in result["reverse_graph"]
        assert result["reverse_graph"]["llm_client"]["consumer"] == 1

    def test_multiple_repos_cross_deps(self, tmp_path):
        make_inferred(tmp_path, "repo-a", [
            cross_edge("a.py", "llm_client"),
            cross_edge("b.py", "llm_client"),
        ])
        make_inferred(tmp_path, "repo-b", [
            cross_edge("x.py", "llm_client"),
            cross_edge("x.py", "data_contracts"),
        ])
        result = build_dep_map(tmp_path)
        assert result["cross_repo_edges"] == 4
        assert result["dep_graph"]["repo-a"]["depends_on"] == {"llm_client": 2}
        assert result["dep_graph"]["repo-b"]["depends_on"] == {"llm_client": 1, "data_contracts": 1}
        assert set(result["reverse_graph"]["llm_client"].keys()) == {"repo-a", "repo-b"}

    def test_repos_sorted_alphabetically(self, tmp_path):
        make_inferred(tmp_path, "zebra", [local_edge("a", "b")])
        make_inferred(tmp_path, "alpha", [local_edge("a", "b")])
        result = build_dep_map(tmp_path)
        assert result["repos"] == ["alpha", "zebra"]

    def test_total_edges_includes_local(self, tmp_path):
        make_inferred(tmp_path, "repo", [
            local_edge("a.py", "b.py"),
            local_edge("b.py", "c.py"),
            cross_edge("a.py", "llm_client"),
        ])
        result = build_dep_map(tmp_path)
        assert result["total_edges"] == 3
        assert result["cross_repo_edges"] == 1
        assert result["dep_graph"]["repo"]["total_edges"] == 3

    def test_ignores_non_inferred_files(self, tmp_path):
        """Files not named inferred_*.json are skipped."""
        (tmp_path / "plan_registry.json").write_text('{"edges": []}')
        make_inferred(tmp_path, "good-repo", [local_edge("a", "b")])
        result = build_dep_map(tmp_path)
        assert result["repos"] == ["good-repo"]

    def test_handles_malformed_json(self, tmp_path):
        """Malformed JSON files are silently skipped."""
        (tmp_path / "inferred_broken.json").write_text("NOT JSON")
        make_inferred(tmp_path, "good-repo", [local_edge("a", "b")])
        result = build_dep_map(tmp_path)
        assert result["repos"] == ["good-repo"]

    def test_cross_project_prefix_stripped(self, tmp_path):
        """[cross-project:llm_client] target becomes 'llm_client' in depends_on."""
        make_inferred(tmp_path, "consumer", [
            {"source": "f.py", "target": "[cross-project:llm_client]", "type": "python_import"}
        ])
        result = build_dep_map(tmp_path)
        assert "llm_client" in result["dep_graph"]["consumer"]["depends_on"]


# ---------------------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------------------

class TestFormatSummary:
    def _make_dep_map(self, **overrides):
        base = {
            "repos": ["a", "b"],
            "total_edges": 10,
            "cross_repo_edges": 3,
            "dep_graph": {
                "a": {"total_edges": 5, "cross_repo_edges": 2, "depends_on": {"llm_client": 2}},
                "b": {"total_edges": 5, "cross_repo_edges": 1, "depends_on": {"llm_client": 1}},
            },
            "reverse_graph": {"llm_client": {"a": 2, "b": 1}},
        }
        base.update(overrides)
        return base

    def test_contains_repo_count(self):
        summary = format_summary(self._make_dep_map())
        assert "2" in summary  # 2 repos

    def test_contains_cross_repo_edge_count(self):
        summary = format_summary(self._make_dep_map())
        assert "3" in summary  # 3 cross-repo edges

    def test_contains_most_depended_on(self):
        summary = format_summary(self._make_dep_map())
        assert "llm_client" in summary

    def test_isolated_repos_section(self):
        dep_map = {
            "repos": ["a", "b"],
            "total_edges": 5,
            "cross_repo_edges": 0,
            "dep_graph": {
                "a": {"total_edges": 3, "cross_repo_edges": 0, "depends_on": {}},
                "b": {"total_edges": 2, "cross_repo_edges": 0, "depends_on": {}},
            },
            "reverse_graph": {},
        }
        summary = format_summary(dep_map)
        assert "Isolated" in summary
        assert "a" in summary
        assert "b" in summary
