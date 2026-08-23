#!/usr/bin/env python3
"""Run a lane command with the canonical checkout mounted read-only.

This wrapper exists because every write-governing hook in this ecosystem is
wired to the ``Edit``/``Write`` tool names only. An agent that edits files with
``sed -i``, a heredoc, or a Python script -- which is exactly what bypass
permissions mode instructs agents to do -- never reaches those gates, so two
sessions can still silently overwrite each other in one shared checkout.

The boundary enforced here is route-independent: it is a kernel mount
namespace, not a tool-name check. ``systemd-run --user`` starts the command in
a transient unit whose mount namespace has the canonical checkout bound
read-only and the lane worktree (plus the minimum Git state a lane genuinely
needs) bound read-write. A ``>`` redirection, ``sed -i``, ``python open()``,
``cp``, ``tee``, or a compiled binary all fail identically against the
canonical tree.

The writable carve-outs below were derived by running real lane operations
under confinement and observing what broke, not by inspection:

``<worktree>``
    The lane checkout itself. Without it nothing can be edited.
``<repo>/.git/worktrees``
    ``git commit`` in a linked worktree writes ``index.lock``, ``index``, and
    ``COMMIT_EDITMSG`` under ``.git/worktrees/<name>/``. Observed failure
    without it: ``fatal: Unable to create '.../index.lock': Read-only file
    system``.
``<repo>/.git/objects``
    Commit object and pack writes, and ``git fetch``.
``<repo>/.git/refs``
    Branch ref updates for the lane branch and remote-tracking refs.
``<repo>/.git/logs``
    Reflog updates that accompany every ref update.
``<repo>/.git/config``
    Only needed by ``git push -u`` / ``git branch --set-upstream-to``.
    Observed failure without it: the push succeeds but prints ``error: could
    not lock config file ...: Read-only file system`` and leaves no upstream.

Deliberately *not* carved out: ``<repo>/.git/index``, ``<repo>/.git/HEAD``, and
the canonical working tree. A lane therefore cannot switch or dirty the
canonical checkout, which is the collision this wrapper prevents.

Everything outside the repository stays writable, which was also verified
rather than assumed: the coordination claim registry under
``~/.claude/coordination/``, ``$HOME`` caches, and ``/tmp`` are all writable
inside confinement, so claim creation, heartbeats, and ``pytest`` behave
normally.

When ``systemd-run --user`` is unavailable this wrapper REFUSES to launch. A
boundary that silently degrades to no boundary is the exact defect this
addresses -- four existing hooks already fail open silently on a shell payload.
Pass ``--allow-unconfined`` to run anyway; it is loud, explicit, and recorded in
the JSON result.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


EXIT_USAGE = 2
EXIT_NO_CONFINEMENT = 3
EXIT_SELF_TEST_FAILED = 4

# Carve-outs relative to the repository root. See module docstring for the
# observed failure each one prevents.
GIT_WRITABLE_SUBPATHS = (
    ".git/worktrees",
    ".git/objects",
    ".git/refs",
    ".git/logs",
    ".git/config",
)


@dataclass
class Confinement:
    """The computed mount boundary for one lane."""

    repo_root: str
    worktree_path: str
    branch: str | None
    read_only_paths: list[str] = field(default_factory=list)
    read_write_paths: list[str] = field(default_factory=list)

    def systemd_properties(self) -> list[str]:
        props: list[str] = []
        for path in self.read_only_paths:
            props.extend(["--property", f"ReadOnlyPaths={path}"])
        for path in self.read_write_paths:
            # The '-' prefix tells systemd to ignore a path that does not
            # exist. Without it a missing path (e.g. a repo with no reflogs)
            # makes the transient unit fail to start with no useful output.
            props.extend(["--property", f"ReadWritePaths=-{path}"])
        return props


@dataclass
class LaunchResult:
    ok: bool
    confined: bool
    reason: str
    confinement: dict[str, Any]
    command: list[str]
    exit_code: int | None


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def systemd_run_available() -> tuple[bool, str]:
    """Probe by execution, not by ``which``.

    A ``systemd-run`` binary on ``PATH`` proves nothing: the per-user manager
    may be absent (containers, some CI images), in which case the binary exists
    and every launch fails. So actually start a trivial confined unit.
    """

    if shutil.which("systemd-run") is None:
        return False, "systemd-run is not on PATH"
    probe = _run(
        [
            "systemd-run",
            "--user",
            "--pipe",
            "--quiet",
            "--collect",
            "--property=ReadOnlyPaths=/etc",
            "/bin/true",
        ]
    )
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "").strip().splitlines()
        return False, f"systemd-run --user probe failed: {detail[-1] if detail else probe.returncode}"
    return True, "systemd-run --user probe succeeded"


def resolve_worktree(repo_root: Path, branch: str | None, worktree_path: Path | None) -> Path:
    """Resolve the lane checkout from an explicit path or a branch name."""

    if worktree_path is not None:
        return worktree_path.resolve()
    if branch is None:
        raise SystemExit("one of --branch or --worktree-path is required")
    listing = _run(["git", "-C", str(repo_root), "worktree", "list", "--porcelain"])
    if listing.returncode != 0:
        raise SystemExit(f"git worktree list failed: {listing.stderr.strip()}")
    current: str | None = None
    for line in listing.stdout.splitlines():
        if line.startswith("worktree "):
            current = line[len("worktree ") :]
        elif line.startswith("branch ") and current is not None:
            if line[len("branch ") :] == f"refs/heads/{branch}":
                return Path(current).resolve()
    raise SystemExit(f"no linked worktree found for branch {branch!r} in {repo_root}")


def compute_confinement(
    repo_root: Path,
    worktree: Path,
    branch: str | None,
    extra_writable: list[Path],
) -> Confinement:
    repo_root = repo_root.resolve()
    worktree = worktree.resolve()
    if worktree == repo_root:
        raise SystemExit(
            "refusing to confine the canonical checkout as its own lane: "
            "implementation belongs in <repo>/worktrees/<branch>/"
        )
    read_write = [str(worktree)]
    read_write.extend(str(repo_root / sub) for sub in GIT_WRITABLE_SUBPATHS)
    read_write.extend(str(p.resolve()) for p in extra_writable)
    return Confinement(
        repo_root=str(repo_root),
        worktree_path=str(worktree),
        branch=branch,
        read_only_paths=[str(repo_root)],
        read_write_paths=read_write,
    )


# ``systemd-run --user`` starts the unit from the *manager's* environment, not
# the caller's. Observed consequence: the coordination claim helper could not
# resolve CLAUDE_CODE_SESSION_ID inside confinement and refused to write, which
# looks exactly like a confinement failure but is not one. So forward the
# caller's environment explicitly. These keys are dropped because forwarding
# them confuses the transient unit or leaks the caller's unit identity.
ENV_PASSTHROUGH_DENYLIST = frozenset(
    {"INVOCATION_ID", "JOURNAL_STREAM", "MANAGERPID", "LISTEN_PID", "LISTEN_FDS", "NOTIFY_SOCKET"}
)


def _setenv_args(env: dict[str, str]) -> list[str]:
    args: list[str] = []
    for key in sorted(env):
        if key in ENV_PASSTHROUGH_DENYLIST or "\n" in env[key]:
            continue
        args.extend(["--setenv", f"{key}={env[key]}"])
    return args


def build_command(
    confinement: Confinement,
    payload: list[str],
    pty: bool,
    confined: bool,
    env: dict[str, str] | None = None,
) -> list[str]:
    if not confined:
        return payload
    stream = "--pty" if pty else "--pipe"
    return [
        "systemd-run",
        "--user",
        stream,
        "--quiet",
        "--collect",
        f"--working-directory={confinement.worktree_path}",
        *_setenv_args(env if env is not None else dict(os.environ)),
        *confinement.systemd_properties(),
        *payload,
    ]


# --------------------------------------------------------------------------
# Self-test: the controls that make this wrapper trustworthy.
# --------------------------------------------------------------------------

PROBE_SCRIPT = r"""
set -u
CANON_FILE="$CANON/tracked.txt"
LANE="$LANE"
report() { printf '%s\t%s\n' "$1" "$2"; }

# --- negative controls: three unrelated write routes against the canonical tree
if (echo mutated > "$CANON_FILE") 2>/dev/null; then report neg_redirect ALLOWED; else report neg_redirect BLOCKED; fi
if sed -i 's/original/mutated/' "$CANON_FILE" 2>/dev/null; then report neg_sed ALLOWED; else report neg_sed BLOCKED; fi
if python3 -c "open('$CANON_FILE','a').write('mutated')" 2>/dev/null; then report neg_python ALLOWED; else report neg_python BLOCKED; fi

# --- positive controls: the same three routes against the lane worktree
if (echo original > "$LANE/probe_redirect.txt") 2>/dev/null; then report pos_redirect ALLOWED; else report pos_redirect BLOCKED; fi
if sed -i 's/original/edited/' "$LANE/probe_redirect.txt" 2>/dev/null; then report pos_sed ALLOWED; else report pos_sed BLOCKED; fi
if python3 -c "open('$LANE/probe_python.txt','w').write('ok')" 2>/dev/null; then report pos_python ALLOWED; else report pos_python BLOCKED; fi

# --- non-breakage: a real commit in the lane
cd "$LANE" || exit 90
if git add -A >/dev/null 2>&1 && git commit -q -m "confinement probe commit" >/dev/null 2>&1; then
  report lane_commit ALLOWED
else
  report lane_commit BLOCKED
fi

# --- non-breakage: the coordination claim registry stays writable
if (echo probe > "$COORD/.confinement_probe") 2>/dev/null; then
  report claim_registry ALLOWED
  rm -f "$COORD/.confinement_probe"
else
  report claim_registry BLOCKED
fi
"""

EXPECTED_CONFINED = {
    "neg_redirect": "BLOCKED",
    "neg_sed": "BLOCKED",
    "neg_python": "BLOCKED",
    "pos_redirect": "ALLOWED",
    "pos_sed": "ALLOWED",
    "pos_python": "ALLOWED",
    "lane_commit": "ALLOWED",
    "claim_registry": "ALLOWED",
}


def _build_probe_repo(root: Path) -> tuple[Path, Path]:
    canon = root / "canon"
    canon.mkdir(parents=True)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(root / "gitconfig"), "GIT_CONFIG_SYSTEM": "/dev/null"}
    (root / "gitconfig").write_text(
        "[user]\n\tname = Confinement Probe\n\temail = probe@example.invalid\n"
        "[commit]\n\tgpgsign = false\n[core]\n\thooksPath = /dev/null\n"
    )
    for cmd in (
        ["git", "init", "-q", "-b", "main", str(canon)],
        ["git", "-C", str(canon), "add", "-A"],
    ):
        _run(cmd, env=env)
    (canon / "tracked.txt").write_text("original\n")
    _run(["git", "-C", str(canon), "add", "-A"], env=env)
    _run(["git", "-C", str(canon), "commit", "-q", "-m", "seed"], env=env)
    lane = canon / "worktrees" / "lane"
    add = _run(
        ["git", "-C", str(canon), "worktree", "add", "-q", "-b", "lane", str(lane)],
        env=env,
    )
    if add.returncode != 0:
        raise SystemExit(f"probe worktree setup failed: {add.stderr.strip()}")
    return canon, lane


def run_self_test(confined: bool, coordination_dir: Path) -> dict[str, Any]:
    """Execute the four controls against a throwaway repository.

    ``confined=False`` is the discriminator: the identical probe runs with no
    read-only boundary, and the negative controls are then expected to be
    ALLOWED. A check that cannot fail proves nothing, so the self-test asserts
    the *expected* outcome for the mode it was asked to run.
    """

    coordination_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="confined-lane-selftest-") as tmp:
        root = Path(tmp)
        canon, lane = _build_probe_repo(root)
        confinement = compute_confinement(canon, lane, "lane", [])
        payload = ["/bin/bash", "-c", PROBE_SCRIPT]
        env = {
            **os.environ,
            "CANON": str(canon),
            "LANE": str(lane),
            "COORD": str(coordination_dir),
            "GIT_CONFIG_GLOBAL": str(root / "gitconfig"),
            "GIT_CONFIG_SYSTEM": "/dev/null",
        }
        cmd = build_command(confinement, payload, pty=False, confined=confined, env=env)
        proc = _run(cmd, env=env)
        observed: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            if "\t" in line:
                name, verdict = line.split("\t", 1)
                observed[name.strip()] = verdict.strip()
        canonical_content = (canon / "tracked.txt").read_text()

    if confined:
        expected = dict(EXPECTED_CONFINED)
    else:
        expected = dict(EXPECTED_CONFINED)
        expected.update({"neg_redirect": "ALLOWED", "neg_sed": "ALLOWED", "neg_python": "ALLOWED"})

    controls = []
    for name, want in expected.items():
        got = observed.get(name, "MISSING")
        controls.append({"control": name, "expected": want, "observed": got, "ok": got == want})
    canonical_intact = canonical_content == "original\n"
    ok = all(c["ok"] for c in controls) and (canonical_intact if confined else True)
    return {
        "mode": "confined" if confined else "unconfined-discriminator",
        "ok": ok,
        "controls": controls,
        "canonical_file_after": canonical_content,
        "canonical_file_intact": canonical_intact,
        "stderr": proc.stderr.strip()[-2000:],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a command for one lane with the canonical checkout mounted "
            "read-only and the lane worktree writable."
        )
    )
    parser.add_argument("--repo-root", type=Path, help="Canonical repository checkout to protect.")
    parser.add_argument("--branch", help="Lane branch; its linked worktree is resolved from git.")
    parser.add_argument("--worktree-path", type=Path, help="Lane worktree path (alternative to --branch).")
    parser.add_argument(
        "--extra-writable",
        type=Path,
        action="append",
        default=[],
        metavar="PATH",
        help="Additional path inside the repo to keep writable. Repeatable.",
    )
    parser.add_argument("--pty", action="store_true", help="Allocate a TTY (for an interactive shell).")
    parser.add_argument("--dry-run", action="store_true", help="Print the computed boundary; launch nothing.")
    parser.add_argument(
        "--allow-unconfined",
        action="store_true",
        help="Run without a boundary when systemd-run is unavailable. Loud and recorded.",
    )
    parser.add_argument("--self-test", action="store_true", help="Run the built-in controls in a throwaway repo.")
    parser.add_argument(
        "--self-test-unconfined",
        action="store_true",
        help="Discriminator: run the same controls with no boundary; negative controls must be ALLOWED.",
    )
    parser.add_argument(
        "--coordination-dir",
        type=Path,
        default=Path.home() / ".claude" / "coordination",
        help="Claim registry directory probed by the non-breakage control.",
    )
    parser.add_argument("--json", action="store_true", help="Emit a JSON result.")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run in the lane. Defaults to $SHELL. Prefix with -- to pass flags.",
    )
    args = parser.parse_args(argv)

    if args.self_test or args.self_test_unconfined:
        available, detail = systemd_run_available()
        if args.self_test and not available:
            payload = {"ok": False, "reason": detail, "systemd_run_available": False}
            print(json.dumps(payload, indent=2) if args.json else f"REFUSED: {detail}", file=sys.stderr)
            return EXIT_NO_CONFINEMENT
        results = []
        if args.self_test:
            results.append(run_self_test(True, args.coordination_dir))
        if args.self_test_unconfined:
            results.append(run_self_test(False, args.coordination_dir))
        ok = all(r["ok"] for r in results)
        payload = {"ok": ok, "systemd_run_available": available, "results": results}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            for result in results:
                print(f"[{result['mode']}] {'PASS' if result['ok'] else 'FAIL'}")
                for control in result["controls"]:
                    mark = "ok " if control["ok"] else "FAIL"
                    print(f"  {mark} {control['control']}: expected {control['expected']}, observed {control['observed']}")
                print(f"  canonical file after probe: {result['canonical_file_after']!r}")
        return 0 if ok else EXIT_SELF_TEST_FAILED

    if args.repo_root is None:
        parser.error("--repo-root is required unless --self-test/--self-test-unconfined is used")

    payload = [c for c in args.command if c != "--"] or [os.environ.get("SHELL", "/bin/bash")]
    worktree = resolve_worktree(args.repo_root.resolve(), args.branch, args.worktree_path)
    confinement = compute_confinement(args.repo_root, worktree, args.branch, args.extra_writable)

    available, detail = systemd_run_available()
    confined = available
    if not available and not args.allow_unconfined:
        result = LaunchResult(
            ok=False,
            confined=False,
            reason=(
                f"{detail}. Refusing to launch: an unenforced boundary is the "
                "failure this wrapper exists to prevent. Pass --allow-unconfined "
                "to override explicitly."
            ),
            confinement=asdict(confinement),
            command=payload,
            exit_code=None,
        )
        print(json.dumps(asdict(result), indent=2) if args.json else f"REFUSED: {result.reason}", file=sys.stderr)
        return EXIT_NO_CONFINEMENT

    cmd = build_command(confinement, payload, args.pty, confined, env=dict(os.environ))

    if args.dry_run:
        result = LaunchResult(
            ok=True,
            confined=confined,
            reason=detail,
            confinement=asdict(confinement),
            command=cmd,
            exit_code=None,
        )
        print(json.dumps(asdict(result), indent=2) if args.json else _human(result))
        return 0

    if not confined:
        print(f"WARNING: running UNCONFINED. {detail}", file=sys.stderr)

    proc = subprocess.run(cmd, cwd=confinement.worktree_path)
    result = LaunchResult(
        ok=proc.returncode == 0,
        confined=confined,
        reason=detail,
        confinement=asdict(confinement),
        command=cmd,
        exit_code=proc.returncode,
    )
    if args.json:
        print(json.dumps(asdict(result), indent=2))
    return proc.returncode


def _human(result: LaunchResult) -> str:
    conf = result.confinement
    lines = [
        f"confined: {result.confined} ({result.reason})",
        f"repo-root (read-only): {conf['repo_root']}",
        f"lane worktree (writable): {conf['worktree_path']}",
        "writable carve-outs:",
    ]
    lines.extend(f"  + {p}" for p in conf["read_write_paths"])
    lines.append("denied: everything else under the repo root, including "
                 ".git/index and .git/HEAD of the canonical checkout")
    lines.append(f"command: {' '.join(result.command)}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
