"""Report what landed on a shared ref while a lane was open.

Policy ``shared-surface-state-claims`` (project-meta registry, promoted
2026-09-08) requires that before a session asserts the state of a surface other
agents can write, it checks whether that surface changed during the session.
This module answers that for a git default branch at session close.

It deliberately does not try to answer *who* changed it. Two measurements taken
on this repository's real history on 2026-09-08 rule both candidate identities
out:

* Author email cannot separate two agent sessions -- every session commits as
  the same operator, and every squash-merge through ``gh`` rewrites the author
  to the GitHub noreply address regardless of which session produced it.
* A ``Claude-Session`` commit trailer appears on 1 of the 60 most recent commits,
  so filtering on it would report ~98% of ordinary history as foreign.

Either discriminator would have produced a notice that is wrong almost every
time, which is the documented way these notices die. What *is* structurally
computable is set membership: commits reachable from the shared ref but not from
this lane's own branch, over the range the lane was open. That is the question
the policy actually asks. Saying whose actions a claim covers stays a reporting
obligation on the agent, not something this module pretends to derive.

Three outcomes, never collapsed into each other, because a reader draws opposite
conclusions from the last two:

``observed``       the ref moved under this lane; the commits are listed.
``observed_empty`` the range was read and this lane was the only thing in it.
``unavailable``    the range could not be read, with the reason.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

_FORMAT = "%H%x1f%an%x1f%s"
_RECORD_FIELDS = 3

BASIS_START_REVISION = "start_revision"
BASIS_MERGE_BASE = "merge_base"

OBSERVED = "observed"
OBSERVED_EMPTY = "observed_empty"
UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ForeignCommit:
    """One commit on the shared ref that did not come from this lane."""

    sha: str
    author_name: str
    subject: str

    @property
    def short_sha(self) -> str:
        return self.sha[:9]


@dataclass(frozen=True)
class SharedRefReport:
    """What was learned about movement on ``ref`` while a lane was open."""

    ref: str
    state: str
    basis: str = BASIS_START_REVISION
    commits: tuple[ForeignCommit, ...] = ()
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if self.state not in (OBSERVED, OBSERVED_EMPTY, UNAVAILABLE):
            raise ValueError(f"unknown report state: {self.state}")
        if self.basis not in (BASIS_START_REVISION, BASIS_MERGE_BASE):
            raise ValueError(f"unknown range basis: {self.basis}")
        if self.state == UNAVAILABLE and not self.unavailable_reason:
            raise ValueError("an unavailable report must carry its reason")
        if self.state != UNAVAILABLE and self.unavailable_reason:
            raise ValueError("only an unavailable report carries a reason")
        if self.state == OBSERVED and not self.commits:
            raise ValueError("an observed report must carry at least one commit")
        if self.state == OBSERVED_EMPTY and self.commits:
            raise ValueError("an observed_empty report must carry no commits")


def _git(repo_root: Path, arguments: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _parse_log(output: str) -> list[ForeignCommit]:
    commits: list[ForeignCommit] = []
    for line in output.splitlines():
        if not line:
            continue
        parts = line.split("\x1f")
        if len(parts) != _RECORD_FIELDS:
            continue
        sha, author_name, subject = parts
        commits.append(ForeignCommit(sha=sha, author_name=author_name, subject=subject))
    return commits


def collect_shared_ref_movement(
    repo_root: Path,
    *,
    ref: str,
    since_revision: str | None,
    lane_refs: tuple[str, ...] = (),
    basis: str = BASIS_START_REVISION,
) -> SharedRefReport:
    """Read ``since_revision..ref``, minus anything reachable from ``lane_refs``.

    Excluding the lane's own history is set membership, not attribution: it drops
    exactly this lane's commits and nothing else, so a commit is reported when it
    genuinely arrived from outside the lane, whoever authored it.

    ``lane_refs`` must include the lane's squash-merge commit as well as its
    branch. A squash merge writes a *new* commit that no branch history reaches,
    so a lane that passed only its branch name would report its own merged work
    as somebody else's on every successful close -- the notice would be wrong
    exactly when the lane did everything right. Unresolvable refs are skipped
    rather than failing the report, since a lane's branch is routinely deleted
    before this runs.
    """

    if not since_revision:
        return SharedRefReport(
            ref=ref,
            state=UNAVAILABLE,
            basis=basis,
            unavailable_reason=(
                "the lane recorded no start revision and no merge-base could be computed, "
                "so the range it was open for is unknown"
            ),
        )

    code, _, stderr = _git(repo_root, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
    if code != 0:
        return SharedRefReport(
            ref=ref,
            state=UNAVAILABLE,
            basis=basis,
            unavailable_reason=f"{ref} could not be resolved: {stderr.strip() or 'unknown error'}",
        )

    revisions = [f"{since_revision}..{ref}"]
    for lane_ref in lane_refs:
        if not lane_ref:
            continue
        code, _, _ = _git(repo_root, ["rev-parse", "--verify", "--quiet", f"{lane_ref}^{{commit}}"])
        if code == 0:
            revisions.append(f"^{lane_ref}")

    code, stdout, stderr = _git(repo_root, ["log", f"--format={_FORMAT}", *revisions])
    if code != 0:
        return SharedRefReport(
            ref=ref,
            state=UNAVAILABLE,
            basis=basis,
            unavailable_reason=(
                f"{since_revision}..{ref} could not be read: {stderr.strip() or 'unknown error'}"
            ),
        )

    commits = tuple(_parse_log(stdout))
    if not commits:
        return SharedRefReport(ref=ref, state=OBSERVED_EMPTY, basis=basis)
    return SharedRefReport(ref=ref, state=OBSERVED, basis=basis, commits=commits)


def render_report(report: SharedRefReport) -> str:
    """One short block naming what this session must not describe from memory."""

    caveat = (
        ""
        if report.basis == BASIS_START_REVISION
        else " (measured from this lane's merge-base; a lane that rebased onto newer main "
        "will under-report here)"
    )
    if report.state == UNAVAILABLE:
        return (
            f"{report.ref}: NOT CHECKED -- {report.unavailable_reason}. "
            "Do not report this branch's state as though nothing else landed."
        )
    if report.state == OBSERVED_EMPTY:
        return f"{report.ref}: unchanged from outside this lane while it was open{caveat}."
    lines = [
        f"{report.ref}: {len(report.commits)} commit(s) landed from outside this lane while it "
        f"was open. Read them before describing this branch's state, and say whose actions your "
        f"claim covers.{caveat}",
    ]
    lines.extend(
        f"  {commit.short_sha} {commit.author_name}: {commit.subject}" for commit in report.commits
    )
    return "\n".join(lines)
