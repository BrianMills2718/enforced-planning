"""The apparatus-ratio gate must fail in every state a judged project can reach.

The gate exists because supporting material grows without anyone deciding to
grow it. A gate that passes in its own failure states would hide exactly the
drift it is for, so each state below is asserted rather than assumed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_apparatus_ratio import main


def _repo(tmp_path: Path, *, accepted_words: int, apparatus_words: int,
          ceiling: float = 8, config: dict | None = None) -> Path:
    (tmp_path / "manuscript" / "locked").mkdir(parents=True)
    if accepted_words:
        (tmp_path / "manuscript" / "locked" / "a.md").write_text(
            " ".join(["word"] * accepted_words), encoding="utf-8")
    (tmp_path / "PLAN.md").write_text(
        " ".join(["plan"] * apparatus_words), encoding="utf-8")
    (tmp_path / "apparatus-ratio.json").write_text(json.dumps(config or {
        "unit": "words approved",
        "accepted": ["manuscript/locked/**/*.md"],
        "apparatus": ["*.md"],
        "ceiling": ceiling,
    }), encoding="utf-8")
    return tmp_path


def test_within_ceiling_passes(tmp_path):
    repo = _repo(tmp_path, accepted_words=100, apparatus_words=200)
    assert main([str(repo)]) == 0


def test_breach_fails(tmp_path):
    repo = _repo(tmp_path, accepted_words=10, apparatus_words=500)
    assert main([str(repo)]) == 1


def test_zero_accepted_fails_rather_than_passing_vacuously(tmp_path):
    """The state this gate exists for. A ratio over zero is not 'within
    ceiling'; it is unbounded, and reporting it as a pass would be the drift
    itself going green."""
    repo = _repo(tmp_path, accepted_words=0, apparatus_words=500)
    assert main([str(repo)]) == 1


def test_missing_declaration_fails(tmp_path):
    (tmp_path / "PLAN.md").write_text("x", encoding="utf-8")
    assert main([str(tmp_path)]) == 2


def test_invalid_declaration_fails(tmp_path):
    repo = _repo(tmp_path, accepted_words=10, apparatus_words=10,
                 config={"unit": "x", "accepted": [], "apparatus": ["*.md"],
                         "ceiling": 8})
    assert main([str(repo)]) == 2


def test_unknown_key_is_rejected(tmp_path):
    """extra='forbid': a typo in a declaration must not silently disable a
    control the plan claims is running."""
    repo = _repo(tmp_path, accepted_words=10, apparatus_words=10,
                 config={"unit": "x", "accepted": ["**/*.md"],
                         "apparatus": ["*.md"], "ceiling": 8, "celing": 99})
    assert main([str(repo)]) == 2
