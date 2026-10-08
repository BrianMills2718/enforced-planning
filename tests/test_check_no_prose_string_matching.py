"""Controls for the no-prose-string-matching policy check.

The check is name-based, so its own failure mode is the one it exists to catch:
a vocabulary that does not intersect the corpus reports a clean run while
matching nothing. Every test here is written against that, not against the happy
path.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import check_no_prose_string_matching as checker  # noqa: E402


def _write(tmp_path: Path, body: str, name: str = "module.py") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_regex_on_a_hook_payload_field_is_a_violation(tmp_path: Path) -> None:
    """The shape that disabled three Stop gates on 2026-09-04."""

    path = _write(
        tmp_path,
        "import re\n"
        "def classify(payload):\n"
        "    report = payload['last_assistant_message']\n"
        "    return bool(re.search(r'passes|green|works', report))\n",
    )
    result = checker.scan_paths([path])
    assert [v.operation for v in result.violations] == ["re.search"]
    assert result.violations[0].name == "report"


def test_taint_follows_a_parameter_name(tmp_path: Path) -> None:
    """Prose arrives as an argument as often as it is read from a payload."""

    path = _write(
        tmp_path,
        "def classify(report):\n"
        "    return report.startswith('Done')\n",
    )
    assert [v.operation for v in checker.scan_paths([path]).violations] == [".startswith"]


def test_membership_test_against_prose_is_a_violation(tmp_path: Path) -> None:
    """`'traceback' in report` is the same inference with different syntax."""

    path = _write(
        tmp_path,
        "def classify(report):\n"
        "    return 'Traceback' in report\n",
    )
    assert [v.operation for v in checker.scan_paths([path]).violations] == ["in"]


def test_an_exemption_needs_a_reason(tmp_path: Path) -> None:
    """A bare marker is the silent pass this policy exists to remove.

    Allowing `# prose-matching-exempt:` with nothing after it would let the
    exception be taken without anyone having to say why, which is how a policy
    becomes decoration.
    """

    reasoned = _write(
        tmp_path,
        "def classify(report):\n"
        "    return 'Done' in report  # prose-matching-exempt: approved 2026-09-06, fixture only\n",
        name="reasoned.py",
    )
    bare = _write(
        tmp_path,
        "def classify(report):\n"
        "    return 'Done' in report  # prose-matching-exempt:\n",
        name="bare.py",
    )
    assert checker.scan_paths([reasoned]).violations == ()
    assert len(checker.scan_paths([bare]).violations) == 1


def test_ordinary_string_work_is_not_flagged(tmp_path: Path) -> None:
    """The policy is about prose, not about strings.

    Without this, the check would be rejected on its first run against a real
    repository and the policy would go the way of the gates it replaces.
    """

    path = _write(
        tmp_path,
        "import re\n"
        "def parse(filename, config):\n"
        "    if filename.endswith('.py'):\n"
        "        return re.search(r'v(\\d+)', filename)\n"
        "    return 'debug' in config\n",
    )
    assert checker.scan_paths([path]).violations == ()


def test_a_corpus_with_no_prose_name_is_not_checked(tmp_path: Path) -> None:
    """Exit 2, not 0. A vocabulary that matches nothing has proven nothing.

    Observed for real while writing this: the first run excluded any path
    containing `worktrees`, matched absolute path parts, and so scanned zero
    files from inside a lane under `worktrees/`. Without this guard it printed
    'No prose string-matching found' and exited 0 over an empty corpus.
    """

    _write(tmp_path, "def add(a, b):\n    return a + b\n")
    completed = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_no_prose_string_matching.py"), "--roots", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr
    assert "NOT_CHECKED" in completed.stderr


def test_the_vocabulary_still_intersects_a_real_hook() -> None:
    """Bind the check to live code, so a renamed field is caught here.

    `PROSE_NAMES` is a list of names, and a list of names rots. This asserts the
    check still finds a prose heuristic in live code. It was written against the
    learning capture hook, which 597f4d9 repaired; the evidence sample hook's
    regex over the closing `report` is the next real one. If that hook is
    repaired, replace this with the next real one rather than deleting it.
    """

    hook = REPO / "scripts" / "evidence_sample_hook.py"
    if not hook.is_file():
        pytest.skip("the evidence sample hook is not present in this checkout")
    result = checker.scan_paths([hook])
    assert result.violations, (
        "the check no longer finds the prose heuristic it was written against; "
        "either the hook was repaired, or PROSE_NAMES has drifted from the code"
    )


def test_named_roots_that_read_nothing_are_not_checked(tmp_path: Path) -> None:
    """Roots named, zero files read, exit 2 -- and `--allow-vacuous` cannot mute it.

    Observed during this check's own first commit: the pre-commit block printed
    "No prose string-matching found in 0 file(s)" over three staged Python files
    and exited 0. A scanner that reports success over nothing is exactly the
    defect the policy is about, so a resolution failure is loud in every mode.
    """

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "check_no_prose_string_matching.py"),
            "--allow-vacuous",
            "--roots",
            str(tmp_path / "does_not_exist.py"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr
    assert "no file was read" in completed.stderr


def test_git_hook_environment_does_not_move_the_repository_root(tmp_path: Path) -> None:
    """`GIT_DIR` in the environment must not redirect path resolution.

    Git hooks export GIT_DIR and GIT_INDEX_FILE, and `rev-parse --show-toplevel`
    answers about that environment rather than the working directory. Inside the
    pre-commit hook the root resolved to the scripts directory, every staged path
    then resolved under `<repo>/scripts/scripts/...`, and the scan read zero
    files while exiting 0 -- a clean report over nothing, which is the defect the
    policy exists to stop.
    """

    import os

    environment = dict(os.environ)
    environment["GIT_DIR"] = str(REPO / ".git")
    environment["GIT_INDEX_FILE"] = str(REPO / ".git" / "index")
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "check_no_prose_string_matching.py"),
            "--allow-vacuous",
            "--roots",
            "scripts/check_no_prose_string_matching.py",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "in 1 file(s)" in completed.stdout
