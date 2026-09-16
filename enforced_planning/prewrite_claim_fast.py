"""Dependency-light pre-write decisions over a canonical claim projection.

This module intentionally uses only the Python standard library.  The YAML
registry is authoritative; this runtime accepts a projection only when its
digest exactly matches the current registry.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_CLAIMS_DIR = Path.home() / ".claude" / "coordination" / "claims"
DEFAULT_PROJECTION_PATH = (
    Path.home() / ".claude" / "coordination" / "prewrite-authority-v1.json"
)
DEFAULT_RECEIPT_PATH = (
    Path.home() / ".claude" / "coordination" / "prewrite-events-v1.jsonl"
)
LIVE_STATUSES = {"active", "blocked", "handoff"}
# Kept identical to enforced_planning/coordination_claims.py's
# APPEND_ONLY_WRITE_PREFIXES by design, not imported: this module is
# intentionally stdlib-only (see module docstring), and coordination_claims.py
# pulls in yaml and heavier machinery unsuited to a per-tool-call hot path.
# An append-only store cannot contend with itself, so a session with zero
# live claim may still write here -- but only here; a mutation touching any
# non-append-only path still requires the ordinary exact-claim gate below.
APPEND_ONLY_WRITE_PREFIXES = (
    "learnings/entries",
    "learnings/invalid_entries",
    "policy/proposals",
)
PROJECTION_FIELDS = {
    "schema_version",
    "generated_at",
    "claims_dir",
    "registry_digest",
    "claims",
}
CLAIM_FIELDS = {
    "agent",
    "projects",
    "scope",
    "claim_type",
    "session_id",
    "repo_root",
    "worktree_path",
    "branch",
    "write_paths",
    "expires_at",
    "heartbeat_at",
    "status",
    "source_file",
    "source_sha256",
    "static_issues",
}

_CUSTOM_PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$")
_CUSTOM_MOVE_PATH = re.compile(r"^\*\*\* Move to: (.+)$")
_UNIFIED_PATCH_PATH = re.compile(r"^(?:---|\+\+\+) (.+)$")
_SHELL_CONTROL = frozenset({";", "&", "&&", "|", "||", ">", ">>", "<", "<<", "<<<", "2>", "2>>"})
_READ_ONLY_SEPARATORS = frozenset({";", "&&", "||", "|"})
_SIMPLE_READ_ONLY_COMMANDS = frozenset(
    {
        ":",
        "cat",
        "cd",
        "date",
        "echo",
        "false",
        "grep",
        "head",
        "jq",
        "ls",
        "printf",
        "pwd",
        "readlink",
        "realpath",
        "rg",
        "sha256sum",
        "stat",
        "tail",
        "test",
        "true",
        "type",
        "wc",
        "which",
    }
)
_READ_ONLY_GIT_SUBCOMMANDS = frozenset(
    {
        "cat-file",
        "diff",
        "log",
        "ls-files",
        "ls-tree",
        "rev-parse",
        "rev-list",
        "show",
        "status",
    }
)
_BASENAME_PATH_COMMANDS = frozenset({"mkdir", "rm", "rmdir", "touch", "truncate", "unlink"})

BashBootstrapClassifier = Callable[[str], bool | str]

_SESSION_STATUS_VALUE_OPTIONS = frozenset(
    {
        "--project",
        "--agent",
        "--scope",
        "--branch",
        "--session-id",
        "--codex-session-index",
    }
)
_SESSION_STATUS_FLAG_OPTIONS = frozenset({"--include-ended", "--json"})


class FastPreWriteError(ValueError):
    """Raised when a hook request cannot be normalized safely."""


def registry_digest(claims_dir: Path) -> str:
    """Hash every YAML authority record deterministically without parsing it."""

    digest = hashlib.sha256()
    if not claims_dir.exists():
        return digest.hexdigest()
    for path in sorted(claims_dir.glob("*.yaml")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def projection_path_for(claims_dir: Path) -> Path:
    """Return the default derived projection path for one registry."""

    resolved = claims_dir.expanduser().resolve()
    if resolved == DEFAULT_CLAIMS_DIR.expanduser().resolve():
        return DEFAULT_PROJECTION_PATH
    return resolved.parent / f"{resolved.name}-prewrite-authority-v1.json"


def _nonempty(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise FastPreWriteError(f"PreToolUse payload requires non-empty {field!r}")
    return value.strip()


def _patch_paths(command: str) -> tuple[str, ...]:
    paths: list[str] = []
    for line in command.splitlines():
        match = _CUSTOM_PATCH_PATH.match(line) or _CUSTOM_MOVE_PATH.match(line)
        if match:
            paths.append(match.group(1).strip())
            continue
        unified = _UNIFIED_PATCH_PATH.match(line)
        if unified:
            candidate = unified.group(1).strip().split("\t", 1)[0]
            if candidate == "/dev/null":
                continue
            if candidate.startswith(("a/", "b/")):
                candidate = candidate[2:]
            paths.append(candidate)
    return tuple(dict.fromkeys(path for path in paths if path))


def _shell_commands(command: str) -> tuple[tuple[str, ...], ...] | None:
    """Return safely separated shell argv groups, or ``None`` when ambiguous.

    Read-only inspection commonly chains commands or pipes output.  Treating
    every control operator as a possible write made ``pwd && ls`` require a
    repository claim, including at a non-repository workspace root.  We accept
    only separators whose every component can be proved read-only; background
    execution, redirection, substitutions, and malformed groups still fail
    closed.
    """

    if not command.strip() or "\r" in command:
        return None
    if "`" in command or "$(" in command or "${" in command:
        return None
    try:
        # Keep physical newlines visible to the parser. Native agents commonly
        # batch independent inspections as one multiline Bash request; treating
        # the newline as ordinary whitespace would merge adjacent commands,
        # while rejecting every newline sends harmless observation through the
        # write-claim path. Newlines embedded in any other token remain
        # ambiguous and fail closed below.
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>\n")
        lexer.whitespace_split = True
        lexer.whitespace = " \t"
        # Shell comments terminate at a physical newline.  Letting shlex
        # consume comments also consumes that boundary and can merge a later
        # mutating command into the argv of an allowed read command.
        lexer.commenters = ""
        tokens = tuple(lexer)
    except ValueError:
        return None
    if not tokens:
        return None
    commands: list[tuple[str, ...]] = []
    current: list[str] = []
    for token in tokens:
        if "\n" in token:
            if set(token) != {"\n"}:
                # shlex groups adjacent punctuation, for example ``\n>``.
                # Such a token contains shell behavior beyond a command
                # boundary and is not provably read-only.
                return None
            if current:
                commands.append(tuple(current))
                current = []
            continue
        if token in _READ_ONLY_SEPARATORS:
            if not current:
                return None
            commands.append(tuple(current))
            current = []
            continue
        if token in _SHELL_CONTROL or set(token) <= set(";&|<>"):
            return None
        current.append(token)
    if current:
        commands.append(tuple(current))
    elif not commands:
        return None
    if any("=" in argv[0] and not argv[0].startswith(("/", "./")) for argv in commands):
        return None
    return tuple(commands)


def _git_command_is_read_only(argv: tuple[str, ...]) -> bool:
    index = 1
    while index < len(argv):
        token = argv[index]
        if token == "-C":
            index += 2
            continue
        if token in {"--no-pager", "--paginate", "-P", "-p"}:
            index += 1
            continue
        break
    if index >= len(argv):
        return False
    subcommand = argv[index]
    tail = argv[index + 1 :]
    if subcommand == "ls-remote":
        return not any(
            token in {"--upload-pack", "--exec"}
            or token.startswith(("--upload-pack=", "--exec="))
            for token in tail
        )
    if subcommand in _READ_ONLY_GIT_SUBCOMMANDS:
        return not any(
            token in {"--output", "--output-indicator-new", "--output-indicator-old"} or token.startswith("--output=")
            for token in tail
        )
    if subcommand == "branch":
        return not tail or all(
            token in {"--show-current", "--list", "--all", "-a", "-r", "--remotes"} for token in tail
        )
    if subcommand == "remote":
        return not tail or tail[0] in {"-v", "show", "get-url"}
    if subcommand == "worktree":
        return bool(tail) and tail[0] == "list"
    if subcommand == "tag":
        return not tail or tail[0] in {"--list", "-l"}
    if subcommand == "config":
        return bool(tail) and tail[0] in {"--get", "--get-all", "--get-regexp", "--list", "-l"}
    return False


def _gh_command_is_read_only(argv: tuple[str, ...]) -> bool:
    """Admit only bounded GitHub CLI queries with no write-capable flags."""

    if len(argv) < 2:
        return False
    group = argv[1]
    tail = argv[2:]
    if group in {"status", "search"}:
        return True
    if group == "auth":
        return bool(tail) and tail[0] == "status"
    allowed = {
        "issue": {"list", "status", "view"},
        "pr": {"checks", "diff", "list", "status", "view"},
        "release": {"list", "view"},
        "repo": {"list", "view"},
        "run": {"list", "view"},
        "workflow": {"list", "view"},
    }
    if group in allowed:
        return bool(tail) and tail[0] in allowed[group]
    if group != "api":
        return False
    unsafe_api_flags = {
        "-X",
        "--method",
        "-f",
        "--raw-field",
        "-F",
        "--field",
        "--input",
    }
    for index, token in enumerate(tail):
        if token.startswith(("-f", "-F")) and token not in {"-f", "-F"}:
            return False
        if token.startswith("-X") and token != "-X":
            if token[2:].upper() == "GET":
                continue
            return False
        option = token.split("=", 1)[0]
        if option in unsafe_api_flags:
            if option in {"-X", "--method"} and "=" not in token:
                method = tail[index + 1] if index + 1 < len(tail) else ""
                if method.upper() == "GET":
                    continue
            elif option in {"-X", "--method"} and token.split("=", 1)[1].upper() == "GET":
                continue
            return False
    return bool(tail)


def _date_command_is_read_only(argv: tuple[str, ...]) -> bool:
    """Reject GNU date's clock-setting forms while allowing observation."""

    for token in argv[1:]:
        option = token.split("=", 1)[0]
        if option.startswith("--") and option != "--" and "--set".startswith(option):
            return False
        if token.startswith("-") and not token.startswith("--") and "s" in token[1:]:
            return False
    return True


def _sort_command_is_read_only(argv: tuple[str, ...]) -> bool:
    """Allow formatting-only sort calls while rejecting file-writing options."""

    unsafe_long_options = (
        "--output",
        "--temporary-directory",
        "--compress-program",
    )
    for token in argv[1:]:
        if token.startswith("--"):
            option = token.split("=", 1)[0]
            # GNU long options accept unambiguous abbreviations, so reject a
            # prefix such as ``--out=...`` as well as the full spelling.
            if any(unsafe.startswith(option) for unsafe in unsafe_long_options):
                return False
        elif token.startswith("-") and token != "-":
            # Short options may be clustered (for example ``-uo result``).
            # Conservatively reject any option token containing output (-o)
            # or temp-directory (-T), even if it also contains safe flags.
            if any(option in token[1:] for option in ("o", "T")):
                return False
    return True


def classify_bash_command(
    command: str,
    *,
    claim_bootstrap_classifier: BashBootstrapClassifier | None = None,
) -> str:
    """Classify Bash without executing it.

    A command bypasses ordinary claim admission only when every shell component
    is provably read-only, or when the separately validated claim bootstrap
    escape hatch accepts it.
    """

    if claim_bootstrap_classifier is not None:
        try:
            special = claim_bootstrap_classifier(command)
            if special is True:
                return "claim_bootstrap"
            if special in {
                "claim_bootstrap",
                "native_mailbox",
                "native_closeout",
                "native_session_narrow",
                "hook_feedback_report",
                "read_target_selection",
                "projection_recovery",
            }:
                return str(special)
        except Exception:  # noqa: BLE001 -- classifier failure must fail closed
            return "claim_required"
    commands = _shell_commands(command)
    if commands is None:
        return "claim_required"

    if all(_if_control_argv_is_read_only(argv) for argv in commands):
        return "read_only"
    return "claim_required"


def _if_control_argv_is_read_only(argv: tuple[str, ...]) -> bool:
    """Admit a flat shell ``if`` only when every contained command is read-only.

    ``_shell_commands`` already rejects substitution, redirection, background
    execution, malformed separators, and assignment-led commands.  A flat
    ``if`` therefore arrives as groups beginning with ``if``, ``then``,
    ``elif``, ``else``, and the terminal ``fi`` marker.  Strip only those
    reserved words and reuse the existing command allowlist; loops, nesting,
    shell interpreters, and any mutating condition or branch still fail closed.
    """

    if argv == ("fi",):
        return True
    if argv and argv[0] in {"if", "then", "elif", "else"}:
        return len(argv) > 1 and _argv_is_read_only(argv[1:])
    return _argv_is_read_only(argv)


def _bash_declared_paths(command: str) -> tuple[str, ...]:
    """Extract explicit path operands that could redirect a shell mutation.

    Hook payloads do not expose the shell tool's per-command workdir.  A claim
    can therefore authorize ordinary pathless commands in its worktree, but an
    explicit absolute or traversal operand must be proved to remain inside the
    selected worktree.  This intentionally recognizes only path-shaped tokens;
    ambiguity never creates authority outside the selected worktree.
    """

    commands = _shell_commands(command)
    if commands is not None and len(commands) == 1:
        effective_argv = _bash_effective_argv(commands[0])
        git_paths = _git_declared_paths(effective_argv)
        if git_paths is not None:
            return git_paths
        lifecycle_paths = _lifecycle_declared_paths(effective_argv)
        if lifecycle_paths is not None:
            return lifecycle_paths
        make_lifecycle_paths = _make_lifecycle_declared_paths(effective_argv)
        if make_lifecycle_paths is not None:
            return make_lifecycle_paths
        github_paths = _github_declared_paths(effective_argv)
        if github_paths is not None:
            return github_paths
        concern_paths = _concern_issue_declared_paths(effective_argv)
        if concern_paths is not None:
            return concern_paths

    pytest_node_paths: dict[str, str] = {}
    if commands is not None:
        for argv in commands:
            command_tokens = list(_bash_effective_argv(argv))
            executable = Path(command_tokens[0]).name if command_tokens else ""
            tail: list[str] = []
            if executable in {"pytest", "py.test"}:
                tail = command_tokens[1:]
            elif (
                executable in {"python", "python3", "python3.12"}
                and len(command_tokens) >= 3
                and command_tokens[1:3] == ["-m", "pytest"]
            ):
                tail = command_tokens[3:]
            for operand in tail:
                if not operand.startswith("-") and "::" in operand:
                    pytest_node_paths[operand] = operand.split("::", 1)[0]

    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        tokens = tuple(lexer)
    except ValueError:
        return ()
    paths: list[str] = []
    command_start = True
    env_command = False
    python_script_pending = False
    skip_env_cwd = False
    for token in tokens:
        if token in _SHELL_CONTROL or set(token) <= set(";&|<>"):
            command_start = token in {";", "&&", "||", "|", "&"}
            continue
        if command_start:
            command_start = False
            env_command = token == "/usr/bin/env"
            if token.startswith(("/usr/bin/", "/bin/")):
                continue
        if env_command:
            if skip_env_cwd:
                skip_env_cwd = False
                continue
            if token in {"-C", "--chdir"}:
                skip_env_cwd = True
                continue
            if token.startswith("--chdir=") or (
                "=" in token and not token.startswith(("/", "~", "."))
            ):
                continue
            env_command = False
            python_script_pending = Path(token).name in {"python", "python3", "python3.12"}
            continue
        if python_script_pending:
            if token.startswith("-"):
                continue
            python_script_pending = False
            continue
        candidate = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
        candidate = pytest_node_paths.get(candidate, candidate)
        if "://" in candidate or candidate in {"-", "."}:
            continue
        if "=" in candidate and not candidate.startswith(("/", "~", ".")):
            candidate = candidate.split("=", 1)[1]
        if candidate.startswith(("/", "~", "./", "../")) or "/" in candidate:
            paths.append(candidate)
    if commands is not None:
        for argv in commands:
            command_argv = _bash_effective_argv(argv)
            if not command_argv:
                continue
            executable = Path(command_argv[0]).name
            if executable not in _BASENAME_PATH_COMMANDS:
                continue
            after_options = False
            for operand in command_argv[1:]:
                if operand == "--":
                    after_options = True
                    continue
                if not after_options and operand.startswith("-"):
                    continue
                if (
                    operand not in {"", ".", "-"}
                    and "://" not in operand
                    and "=" not in operand
                    and not any(marker in operand for marker in ("$", "`", "*", "?", "["))
                ):
                    paths.append(operand)
    return tuple(dict.fromkeys(paths))


def _bash_effective_argv(argv: tuple[str, ...]) -> tuple[str, ...]:
    """Return the command executed by the supported literal env cwd wrapper."""

    if len(argv) >= 4 and argv[:2] == ("/usr/bin/env", "-C"):
        return argv[3:]
    return argv


def _paths_except_identifier_options(
    argv: tuple[str, ...],
    *,
    start: int,
    identifier_options: frozenset[str],
) -> tuple[str, ...]:
    """Return path-shaped operands while skipping typed identifier values."""

    paths: list[str] = []
    index = start
    while index < len(argv):
        token = argv[index]
        option, separator, inline_value = token.partition("=")
        if option in identifier_options:
            index += 1 if separator else 2
            continue
        candidate = inline_value if separator and token.startswith("-") else token
        if _path_shaped(candidate):
            paths.append(candidate)
        index += 1
    return tuple(dict.fromkeys(paths))


def _github_declared_paths(argv: tuple[str, ...]) -> tuple[str, ...] | None:
    """Treat GitHub ``owner/repo`` selectors as identifiers, not paths."""

    if not argv or Path(argv[0]).name != "gh":
        return None
    return _paths_except_identifier_options(
        argv,
        start=1,
        identifier_options=frozenset({"--repo", "-R"}),
    )


def _concern_issue_declared_paths(argv: tuple[str, ...]) -> tuple[str, ...] | None:
    """Classify concern-register arguments by their typed CLI contract."""

    if len(argv) < 3 or Path(argv[0]).name not in {"python", "python3", "python3.12"}:
        return None
    if argv[1] not in {"scripts/concern_issue.py", "scripts/meta/concern_issue.py"}:
        return None
    return _paths_except_identifier_options(
        argv,
        start=2,
        identifier_options=frozenset(
            {
                "--body",
                "--evidence",
                "--key",
                "--occurrence",
                "--repo",
                "--source",
                "--title",
            }
        ),
    )


_LIFECYCLE_IDENTIFIER_OPTIONS = {
    "--agent",
    "--branch",
    "--disposition",
    "--disposition-reason",
    "--merge-commit",
    "--note",
    "--project",
    "--recovery-ref",
    "--scope",
    "--session-id",
}
_LIFECYCLE_PATH_OPTIONS = {"--worktree-path"}
_LIFECYCLE_SCRIPT_PATHS = frozenset(
    {
        "scripts/session_close.py",
        "scripts/session_finish.py",
        "scripts/meta/session_close.py",
        "scripts/meta/session_finish.py",
    }
)
_MAKE_LIFECYCLE_IDENTIFIER_VARIABLES = {
    "BRANCH",
    "SESSION_NOTE",
    "WORKTREE_AGENT",
    "WORKTREE_DISPOSITION",
    "WORKTREE_DISPOSITION_REASON",
    "WORKTREE_MERGE_COMMIT",
    "WORKTREE_PROJECT",
    "WORKTREE_RECOVERY_REF",
}


def _path_shaped(value: str) -> bool:
    return value.startswith(("/", "~", "./", "../")) or "/" in value


def _is_trusted_lifecycle_script(value: str) -> bool:
    """Accept canonical relative paths and this runtime's absolute scripts."""

    if value in _LIFECYCLE_SCRIPT_PATHS:
        return True
    candidate = Path(value)
    if not candidate.is_absolute():
        return False
    runtime_scripts = Path(__file__).resolve().parents[1] / "scripts"
    return candidate.resolve() in {
        runtime_scripts / relative.removeprefix("scripts/")
        for relative in _LIFECYCLE_SCRIPT_PATHS
    }


def _lifecycle_declared_paths(argv: tuple[str, ...]) -> tuple[str, ...] | None:
    """Return only filesystem operands from a direct lifecycle invocation.

    Branches, scopes, and recovery refs are typed identifiers and commonly
    contain slashes.  Treating those values as paths makes the canonical
    closeout command unable to retire exactly the lanes it created.  Unknown
    path-shaped operands still fail through the ordinary path gate.
    """

    if len(argv) < 2 or Path(argv[0]).name not in {"python", "python3", "python3.12"}:
        return None
    if not _is_trusted_lifecycle_script(argv[1]):
        return None
    paths: list[str] = []
    index = 2
    while index < len(argv):
        token = argv[index]
        option, separator, inline_value = token.partition("=")
        if option in _LIFECYCLE_IDENTIFIER_OPTIONS:
            if not separator and index + 1 >= len(argv):
                return None
            index += 1 if separator else 2
            continue
        if option in _LIFECYCLE_PATH_OPTIONS:
            if separator:
                if inline_value:
                    paths.append(inline_value)
                index += 1
            elif index + 1 < len(argv):
                paths.append(argv[index + 1])
                index += 2
            else:
                index += 1
            continue
        candidate = inline_value if separator and token.startswith("-") else token
        if _path_shaped(candidate):
            paths.append(candidate)
        index += 1
    return tuple(dict.fromkeys(paths))


def _make_lifecycle_declared_paths(argv: tuple[str, ...]) -> tuple[str, ...] | None:
    """Return path operands for the sanctioned Make lifecycle targets."""

    if not argv or Path(argv[0]).name not in {"make", "gmake"}:
        return None
    paths: list[str] = []
    targets: list[str] = []
    assignments: list[tuple[str, str]] = []
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in {"-C", "--directory", "-f", "--file", "--makefile"}:
            if index + 1 >= len(argv):
                return None
            paths.append(argv[index + 1])
            index += 2
            continue
        if token.startswith(("--directory=", "--file=", "--makefile=")):
            paths.append(token.split("=", 1)[1])
            index += 1
            continue
        if "=" in token and not token.startswith("-"):
            name, value = token.split("=", 1)
            assignments.append((name, value))
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        targets.append(token)
        index += 1
    if targets not in [["session-close"], ["session-finish"]]:
        return None
    for name, value in assignments:
        if name in _MAKE_LIFECYCLE_IDENTIFIER_VARIABLES:
            continue
        if _path_shaped(value):
            paths.append(value)
    return tuple(dict.fromkeys(paths))


def _git_declared_paths(argv: tuple[str, ...]) -> tuple[str, ...] | None:
    """Return actual path operands for bounded Git command shapes.

    Read-only Git operands and a push's remote/ref operands are identifiers,
    not filesystem paths. Treating ``origin/main`` or ``branch...HEAD`` as a
    path creates a circular denial at inspection and integration boundaries.
    Execution-directory and merge-message-file operands remain paths.
    """

    if not argv or Path(argv[0]).name != "git":
        return None
    paths: list[str] = []
    index = 1
    while index < len(argv):
        token = argv[index]
        if token == "-C":
            if index + 1 >= len(argv):
                return None
            paths.append(argv[index + 1])
            index += 2
            continue
        if token == "-c":
            if index + 1 >= len(argv):
                return None
            index += 2
            continue
        if token in {"--no-pager", "--paginate", "-P", "-p"}:
            index += 1
            continue
        break
    if index >= len(argv):
        return None
    subcommand = argv[index]
    if _git_command_is_read_only(argv):
        return tuple(dict.fromkeys(paths))
    if subcommand == "push":
        tail = argv[index + 1 :]
        positional = [token for token in tail if not token.startswith("-")]
        if not positional or positional[0] == "origin":
            return tuple(dict.fromkeys(paths))
        return None
    if subcommand != "merge":
        return None
    index += 1
    while index < len(argv):
        token = argv[index]
        if token in {"-F", "--file"}:
            if index + 1 >= len(argv):
                return None
            paths.append(argv[index + 1])
            index += 2
            continue
        if token.startswith("--file="):
            paths.append(token.split("=", 1)[1])
        index += 1
    return tuple(dict.fromkeys(paths))


def _bash_target_is_unprovable(command: str) -> bool:
    """Reject expansions that can conceal a target path from the hook."""

    quote: str | None = None
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if quote == "'":
            if char == "'":
                quote = None
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if char == '"':
            quote = None if quote == '"' else '"'
            index += 1
            continue
        if quote == '"':
            if char in {"$", "`"}:
                return True
            index += 1
            continue
        if char == "'":
            quote = "'"
            index += 1
            continue
        if char in {"$", "`", "*", "?", "["} or command.startswith((">(", "<("), index):
            return True
        index += 1
    return False


def _bash_explicit_worktree(command: str) -> Path | None:
    """Return one literal runtime cwd attested by a supported Bash form."""

    if _bash_target_is_unprovable(command):
        return None
    commands = _shell_commands(command)
    if commands is None or len(commands) != 1:
        return None
    argv = commands[0]
    if len(argv) >= 4 and argv[:2] == ("/usr/bin/env", "-C"):
        return Path(argv[2]).expanduser().resolve()
    executable = Path(argv[0]).name if argv else ""
    if executable in {"git", "make"} and len(argv) >= 3 and argv[1] == "-C":
        return Path(argv[2]).expanduser().resolve()
    return None


def _bash_is_explicitly_bound(command: str, worktree: Path) -> bool:
    """Require a literal runtime cwd when the native payload omits workdir."""

    return _bash_explicit_worktree(command) == worktree


def _canonical_sync_command_targets_repo(
    command: str,
    *,
    worktree: Path,
    repo_root: Path,
) -> bool:
    """Recognize the exact installed canonical-checkout sync operation.

    A linked-worktree claim deliberately owns writes while the canonical
    checkout is locked.  ``canonical_lock.py --sync`` is the one sanctioned
    operation that must cross that physical worktree boundary: it temporarily
    unlocks the canonical checkout, performs an exact fast-forward, and always
    restores the lock.  Keep this recognition narrower than general Python or
    arbitrary out-of-worktree commands.
    """

    if _bash_target_is_unprovable(command):
        return False
    commands = _shell_commands(command)
    if commands is None or len(commands) != 1:
        return False
    tokens = list(commands[0])
    if len(tokens) < 7 or tokens[:2] != ["/usr/bin/env", "-C"]:
        return False
    if Path(tokens[2]).expanduser().resolve(strict=False) != worktree.resolve(strict=False):
        return False
    tokens = tokens[3:]
    if len(tokens) not in {4, 5, 6} or tokens[0] != "/usr/bin/python3":
        return False
    script = Path(tokens[1]).expanduser().resolve(strict=False)
    installed_scripts = {
        (
            Path.home()
            / ".codex/runtime/enforced-planning/scripts/worktree-coordination/canonical_lock.py"
        ).resolve(strict=False),
        (
            Path.home()
            / ".claude/runtime/enforced-planning/scripts/worktree-coordination/canonical_lock.py"
        ).resolve(strict=False),
    }
    if script not in installed_scripts or tokens[2] != "--sync":
        return False
    if Path(tokens[3]).expanduser().resolve(strict=False) != repo_root.resolve(strict=False):
        return False
    return len(tokens) == 4 or set(tokens[4:]).issubset({"--json", "--quiet"})


def _session_status_command_is_read_only(argv: tuple[str, ...]) -> bool:
    """Recognize only the canonical Python-backed session-status operation."""

    tokens = list(argv)
    bound_worktree: Path | None = None
    if len(tokens) >= 4 and tokens[:2] == ["/usr/bin/env", "-C"]:
        worktree = Path(tokens[2]).expanduser()
        if not worktree.is_absolute():
            return False
        bound_worktree = worktree.resolve(strict=False)
        tokens = tokens[3:]
    if len(tokens) < 2 or tokens[0] != "/usr/bin/python3":
        return False

    script = Path(tokens[1]).expanduser()
    if not script.is_absolute():
        return False
    resolved_script = script.resolve(strict=False)
    installed_scripts = {
        (Path.home() / ".codex/runtime/enforced-planning/scripts/session_status.py").resolve(strict=False),
        (Path.home() / ".claude/runtime/enforced-planning/scripts/session_status.py").resolve(strict=False),
    }
    if resolved_script not in installed_scripts:
        return False

    seen: set[str] = set()
    index = 2
    while index < len(tokens):
        token = tokens[index]
        if token in _SESSION_STATUS_FLAG_OPTIONS:
            if token in seen:
                return False
            seen.add(token)
            index += 1
            continue
        option, separator, inline_value = token.partition("=")
        if option not in _SESSION_STATUS_VALUE_OPTIONS or option in seen:
            return False
        seen.add(option)
        if separator:
            if not inline_value:
                return False
            index += 1
            continue
        if index + 1 >= len(tokens) or not tokens[index + 1]:
            return False
        index += 2
    return True


def _argv_is_read_only(argv: tuple[str, ...]) -> bool:
    """Return whether one already-tokenized shell component is read-only."""

    if _session_status_command_is_read_only(argv):
        return True
    if _goal_authority_validator_is_read_only(argv):
        return True

    executable_token = argv[0]
    if Path(executable_token).name != executable_token:
        return False
    executable = executable_token
    if executable in _SIMPLE_READ_ONLY_COMMANDS:
        if executable == "date":
            return _date_command_is_read_only(argv)
        return not (
            executable == "rg"
            and any(
                token == "--pre" or token.startswith("--pre=")
                for token in argv[1:]
            )
        )
    if executable == "systemctl":
        return _systemctl_command_is_read_only(argv)
    if executable == "sed":
        tail = argv[1:]
        if any(
            (
                token.startswith("--")
                and len(token.partition("=")[0]) > 2
                and "--in-place".startswith(token.partition("=")[0])
            )
            or (
                token.startswith("-")
                and not token.startswith("--")
                and "i" in token[1:]
            )
            for token in tail
        ):
            return False
        if len(tail) < 2 or tail[0] not in {"-n", "--quiet", "--silent"}:
            return False
        return re.fullmatch(r"\d+(?:,\d+)?p", tail[1]) is not None
    if executable == "find":
        mutating = {
            "-delete",
            "-exec",
            "-execdir",
            "-fls",
            "-fprint",
            "-fprint0",
            "-fprintf",
            "-ok",
            "-okdir",
        }
        return not any(token in mutating for token in argv[1:])
    if executable == "sort":
        return _sort_command_is_read_only(argv)
    # Organization-owned GitHub repositories must use the configured wrapper
    # rather than bare ``gh``.  It preserves the same CLI grammar and only
    # selects a separate credential/configuration, so classify its query forms
    # with the same conservative rules as bare GitHub CLI commands.
    if executable in {"gh", "gh-insidesuccess"}:
        return _gh_command_is_read_only(("gh", *argv[1:]))
    return executable == "git" and _git_command_is_read_only(argv)


def _goal_authority_validator_is_read_only(argv: tuple[str, ...]) -> bool:
    """Admit the exact shared goal validator with one read-only document operand."""

    if len(argv) != 3 or argv[0] != "/usr/bin/python3":
        return False
    validator = Path(argv[1]).expanduser()
    if not validator.is_absolute():
        return False
    expected = (
        Path.home()
        / ".agents"
        / "skills"
        / "authoring-goals"
        / "scripts"
        / "validate_goal_authority.py"
    ).resolve(strict=False)
    return validator.resolve(strict=False) == expected and bool(argv[2])


def _systemctl_command_is_read_only(argv: tuple[str, ...]) -> bool:
    """Admit only bounded systemd queries; lifecycle verbs remain claim-bound."""

    flags = {
        "--user",
        "--system",
        "--no-pager",
        "--plain",
        "--quiet",
        "--no-legend",
        "--full",
        "--all",
        "--value",
    }
    value_prefixes = ("--property=", "--type=", "--state=", "--lines=")
    index = 1
    while index < len(argv) and (
        argv[index] in flags or argv[index].startswith(value_prefixes)
    ):
        index += 1
    if index >= len(argv) or argv[index] not in {"is-active", "show"}:
        return False
    verb = argv[index]
    tail = argv[index + 1 :]
    if verb == "is-active" and not any(not token.startswith("-") for token in tail):
        return False
    return all(
        not token.startswith("-")
        or token in flags
        or token.startswith(value_prefixes)
        for token in tail
    )


def adapt_native_payload(
    payload: dict[str, Any],
    *,
    client: str,
    claim_bootstrap_classifier: BashBootstrapClassifier | None = None,
) -> dict[str, Any]:
    """Normalize one supported native event without retaining write contents."""

    if not isinstance(payload, dict):
        raise FastPreWriteError("PreToolUse payload must be a JSON object")
    if client not in {"codex", "claude-code"}:
        raise FastPreWriteError(f"Unsupported pre-write client: {client!r}")
    event_name = _nonempty(payload, "hook_event_name")
    if event_name != "PreToolUse":
        raise FastPreWriteError(f"Unsupported hook event: {event_name!r}")
    tool_name = _nonempty(payload, "tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        raise FastPreWriteError("PreToolUse payload requires object field 'tool_input'")

    bash_classification: str | None = None
    if tool_name == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str) or not command.strip():
            raise FastPreWriteError("Bash requires non-empty string tool_input.command")
        bash_declared_paths = _bash_declared_paths(command)
        target_paths = bash_declared_paths
        bash_classification = classify_bash_command(
            command,
            claim_bootstrap_classifier=claim_bootstrap_classifier,
        )
    elif client == "codex":
        bash_declared_paths = ()
        if tool_name != "apply_patch":
            raise FastPreWriteError(f"Unsupported Codex pre-write tool: {tool_name!r}")
        command = tool_input.get("command")
        if not isinstance(command, str) or not command:
            raise FastPreWriteError("Codex apply_patch requires string tool_input.command")
        target_paths = _patch_paths(command)
        if not target_paths:
            raise FastPreWriteError("Codex apply_patch payload contains no provable target paths")
    else:
        bash_declared_paths = ()
        if tool_name not in {"Edit", "Write", "NotebookEdit"}:
            raise FastPreWriteError(f"Unsupported Claude pre-write tool: {tool_name!r}")
        path_field = "notebook_path" if tool_name == "NotebookEdit" else "file_path"
        file_path = tool_input.get(path_field)
        if not isinstance(file_path, str) or not file_path.strip():
            raise FastPreWriteError(f"Claude {tool_name} requires string tool_input.{path_field}")
        target_paths = (file_path.strip(),)

    from enforced_planning.session_target import effective_session_id

    session_id = effective_session_id(payload, client)
    return {
        "client": client,
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "session_id": session_id,
        "cwd": _nonempty(payload, "cwd"),
        "target_paths": target_paths,
        "bash_classification": bash_classification,
        "bash_declared_paths": bash_declared_paths,
        "bash_target_unprovable": _bash_target_is_unprovable(command) if tool_name == "Bash" else False,
        "bash_command": command if tool_name == "Bash" else None,
        "session_target_error_code": payload.get("_session_target_error_code"),
        "session_target_error": payload.get("_session_target_error"),
        "session_target_recovery": payload.get("_session_target_recovery"),
        "session_target_rebound": bool(payload.get("_session_target_worktree")),
    }


def _git(path: Path, *args: str, allow_failure: bool = False) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return completed.stdout.strip()
    if allow_failure:
        return None
    detail = completed.stderr.strip() or completed.stdout.strip() or "unknown Git error"
    raise FastPreWriteError(f"git {' '.join(args)} failed: {detail}")


def _existing_probe(path: Path) -> Path:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe if probe.is_dir() else probe.parent


def _git_identity(path: Path) -> tuple[Path, Path, str]:
    identity = _git(
        _existing_probe(path),
        "rev-parse",
        "--show-toplevel",
        "--path-format=absolute",
        "--git-common-dir",
        "--abbrev-ref",
        "HEAD",
    )
    assert identity is not None
    parts = identity.splitlines()
    if len(parts) != 3:
        raise FastPreWriteError("Git identity response did not contain worktree, common dir, and branch")
    worktree = Path(parts[0]).resolve()
    common_git = Path(parts[1]).resolve()
    if common_git.name != ".git":
        raise FastPreWriteError(f"unsupported Git common directory: {common_git}")
    repo_root = common_git.parent
    branch = parts[2].strip()
    if not branch:
        raise FastPreWriteError("Pre-write enforcement requires a named Git branch")

    return worktree, repo_root, branch


def _repository_context(request: dict[str, Any]) -> dict[str, Any]:
    cwd = Path(str(request["cwd"])).expanduser().resolve()
    raw_targets = tuple(request["target_paths"])
    if request.get("tool_name") == "Bash":
        worktree, repo_root, branch = _git_identity(cwd)
        normalized: list[str] = []
        outside: list[str] = []
        for raw_path in request.get("bash_declared_paths", ()):
            candidate = Path(raw_path).expanduser()
            if not candidate.is_absolute():
                candidate = cwd / candidate
            resolved = candidate.resolve(strict=False)
            try:
                relative = resolved.relative_to(worktree)
            except ValueError:
                outside.append(str(resolved))
                continue
            value = relative.as_posix()
            if value not in {"", "."}:
                normalized.append(value)
    else:
        if not raw_targets:
            raise FastPreWriteError("pre-write request contains no target paths")
        normalized = []
        worktree = repo_root = None
        branch = ""
        for raw_path in raw_targets:
            candidate = Path(raw_path).expanduser()
            if not candidate.is_absolute():
                candidate = cwd / candidate
            resolved = candidate.resolve(strict=False)
            target_worktree, target_repo, target_branch = _git_identity(resolved)
            if worktree is None:
                worktree, repo_root, branch = target_worktree, target_repo, target_branch
            elif (target_worktree, target_repo, target_branch) != (worktree, repo_root, branch):
                raise FastPreWriteError("all target paths must resolve to the same Git worktree and branch")
            assert worktree is not None
            try:
                relative = resolved.relative_to(worktree)
            except ValueError as exc:
                raise FastPreWriteError(f"target path escapes active worktree: {raw_path}") from exc
            value = relative.as_posix()
            if value in {"", "."}:
                raise FastPreWriteError("target path must identify a file below the worktree root")
            normalized.append(value)
        assert worktree is not None and repo_root is not None
    return {
        "worktree_path": str(worktree),
        "repo_root": str(repo_root),
        "branch": branch,
        "normalized_target_paths": tuple(dict.fromkeys(normalized)),
        "bash_paths_outside_worktree": tuple(dict.fromkeys(outside)) if request.get("tool_name") == "Bash" else (),
    }


def _load_projection(path: Path, *, claims_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(payload, dict) or set(payload) != PROJECTION_FIELDS:
        return None, "projection fields do not match PreWriteAuthorityProjectionV1"
    if (
        payload.get("schema_version") != "1.0"
        or not isinstance(payload.get("generated_at"), str)
        or not isinstance(payload.get("claims_dir"), str)
        or not isinstance(payload.get("registry_digest"), str)
        or not isinstance(payload.get("claims"), list)
    ):
        return None, "projection schema is invalid"
    resolved_claims = str(claims_dir.expanduser().resolve())
    if payload.get("claims_dir") != resolved_claims:
        return None, "projection claims_dir does not match the requested registry"
    try:
        current_digest = registry_digest(claims_dir)
    except OSError as exc:
        return None, f"claim registry digest failed: {exc}"
    if payload.get("registry_digest") != current_digest:
        return None, "projection registry digest is stale"
    for claim in payload["claims"]:
        if not _valid_projected_claim(claim):
            return None, "projected claim fields are invalid"
    return payload, None


def _valid_projected_claim(claim: object) -> bool:
    """Validate the dependency-light view of PreWriteAuthorityClaimV1."""

    if not isinstance(claim, dict) or set(claim) != CLAIM_FIELDS:
        return False
    string_fields = {
        "agent",
        "scope",
        "claim_type",
        "session_id",
        "repo_root",
        "worktree_path",
        "branch",
        "status",
        "source_file",
        "source_sha256",
    }
    if any(not isinstance(claim.get(field), str) for field in string_fields):
        return False
    for field in ("projects", "write_paths", "static_issues"):
        value = claim.get(field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return False
    for field in ("expires_at", "heartbeat_at"):
        if claim.get(field) is not None and not isinstance(claim.get(field), str):
            return False
    return True


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _heartbeat_window() -> timedelta:
    raw = os.environ.get("COORDINATION_HEARTBEAT_STALE_MINUTES", "").strip()
    try:
        minutes = float(raw) if raw else 120.0
    except ValueError:
        minutes = 120.0
    if minutes <= 0:
        minutes = 120.0
    return timedelta(minutes=minutes)


def _default_ref(repo_root: Path) -> tuple[str, str] | None:
    remote = _git(
        repo_root,
        "symbolic-ref",
        "--quiet",
        "--short",
        "refs/remotes/origin/HEAD",
        allow_failure=True,
    )
    candidates = [remote] if remote else []
    candidates.extend(["main", "master"])
    for candidate in candidates:
        if not candidate:
            continue
        ref = (
            f"refs/remotes/{candidate}"
            if candidate.startswith("origin/")
            else f"refs/heads/{candidate}"
        )
        exists = _git(repo_root, "show-ref", "--verify", ref, allow_failure=True)
        if exists is not None:
            name = candidate.split("/", 1)[1] if candidate.startswith("origin/") else candidate
            return name, ref
    return None


def _dynamic_claim_issues(claim: dict[str, Any]) -> tuple[str, ...]:
    issues: list[str] = []
    now = datetime.now(timezone.utc)
    expires = _parse_time(claim.get("expires_at"))
    if expires is not None and expires < now:
        issues.append("expired_claim")
    heartbeat = _parse_time(claim.get("heartbeat_at"))
    if claim.get("session_id"):
        if heartbeat is None:
            issues.append("invalid_or_missing_heartbeat_at")
        elif now - heartbeat > _heartbeat_window():
            issues.append("stale_session_heartbeat")

    worktree_raw = claim.get("worktree_path")
    repo_raw = claim.get("repo_root")
    branch = claim.get("branch")
    if not isinstance(worktree_raw, str) or not Path(worktree_raw).expanduser().exists():
        issues.append("missing_worktree_on_disk")
        return tuple(dict.fromkeys(issues))
    if not isinstance(repo_raw, str) or not isinstance(branch, str):
        return tuple(dict.fromkeys(issues))
    repo_root = Path(repo_raw).expanduser().resolve()
    branch_ref = f"refs/heads/{branch}"
    if _git(repo_root, "show-ref", "--verify", branch_ref, allow_failure=True) is None:
        issues.append("missing_branch_ref")
        return tuple(dict.fromkeys(issues))
    default = _default_ref(repo_root)
    if default and default[0] != branch:
        revisions = _git(
            repo_root,
            "rev-parse",
            branch_ref,
            default[1],
            allow_failure=True,
        )
        revision_lines = revisions.splitlines() if revisions is not None else []
        if len(revision_lines) != 2 or revision_lines[0] == revision_lines[1]:
            return tuple(dict.fromkeys(issues))
        start_revision = claim.get("start_revision")
        if isinstance(start_revision, str) and revision_lines[0] == start_revision:
            return tuple(dict.fromkeys(issues))
        merged = subprocess.run(
            ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", branch_ref, default[1]],
            capture_output=True,
            check=False,
        )
        if merged.returncode == 0:
            worktree_status = _git(
                Path(worktree_raw).expanduser(),
                "status",
                "--porcelain",
                "--untracked-files=normal",
                allow_failure=True,
            )
            if worktree_status in {None, ""}:
                issues.append("merged_active_claim_requires_disposition")
    return tuple(dict.fromkeys(issues))


def _path_is_claimed(target: str, claimed_path: str) -> bool:
    normalized = claimed_path.strip().replace("\\", "/").strip("/")
    if normalized in {"", "."}:
        return True
    return target == normalized or target.startswith(f"{normalized}/")


def _is_append_only_path(path: str) -> bool:
    """Return whether a normalized target path lands only in an append-only store.

    ``path`` is already a clean, worktree-relative POSIX path by the time this
    is called (see ``_repository_context``'s ``normalized_target_paths``), so
    no further normalization is needed here.
    """

    return any(
        path == prefix or path.startswith(f"{prefix}/") for prefix in APPEND_ONLY_WRITE_PREFIXES
    )


def _claim_covers_targets(claim: dict[str, Any], targets: tuple[str, ...]) -> bool:
    """Return whether one claim alone authorizes every normalized target."""

    return all(
        any(_path_is_claimed(target, claimed) for claimed in claim["write_paths"])
        for target in targets
    )


def _record_receipt(path: Path, decision: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt = {
        key: value
        for key, value in decision.items()
        if key != "recovery"
    }
    receipt["recorded_at"] = datetime.now(timezone.utc).isoformat()
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _decision(
    *,
    started: float,
    request: dict[str, Any],
    mode: str,
    decision: str,
    reason_code: str,
    context: dict[str, Any] | None,
    claim: dict[str, Any] | None = None,
    details: tuple[str, ...] = (),
    recovery: str | None = None,
    cache_hit: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "receipt_id": f"prewrite_{uuid.uuid4().hex}",
        "decision": decision,
        "mode": mode,
        "reason_code": reason_code,
        "client": request["client"],
        "session_id": request["session_id"],
        "repo_root": context["repo_root"] if context else None,
        "worktree_path": context["worktree_path"] if context else None,
        "branch": context["branch"] if context else None,
        "normalized_target_paths": list(context["normalized_target_paths"]) if context else [],
        "claim_project": claim["projects"][0] if claim and claim["projects"] else None,
        "claim_scope": claim["scope"] if claim else None,
        "claim_source_file": claim["source_file"] if claim else None,
        "details": list(details),
        "recovery": recovery,
        "elapsed_ms": (time.perf_counter() - started) * 1000,
        "cache_hit": cache_hit,
    }


def evaluate_request_fast(
    request: dict[str, Any],
    *,
    mode: str,
    claims_dir: Path = DEFAULT_CLAIMS_DIR,
    projection_path: Path | None = None,
    receipt_path: Path = DEFAULT_RECEIPT_PATH,
    cache_hit: bool = True,
    projection_recovery_command: str | None = None,
) -> dict[str, Any]:
    """Evaluate one normalized request and append its durable receipt."""

    if mode not in {"off", "observe", "enforce"}:
        raise FastPreWriteError("mode must be one of: off, observe, enforce")
    started = time.perf_counter()
    bash_classification = request.get("bash_classification")
    if bash_classification in {
        "read_only",
        "claim_bootstrap",
        "native_mailbox",
        "native_closeout",
        "native_session_narrow",
        "hook_feedback_report",
        "read_target_selection",
        "projection_recovery",
    }:
        reason_by_classification = {
            "read_only": "bash_read_only",
            "claim_bootstrap": "claim_bootstrap_command",
            "native_mailbox": "native_mailbox_command",
            "native_closeout": "native_closeout_command",
            "native_session_narrow": "native_session_narrow_command",
            "hook_feedback_report": "hook_feedback_report_command",
            "read_target_selection": "read_target_selection_command",
            "projection_recovery": "projection_recovery_command",
        }
        result = _decision(
            started=started,
            request=request,
            mode=mode,
            decision="allow",
            reason_code=reason_by_classification[bash_classification],
            context=None,
        )
        _record_receipt(receipt_path, result)
        return result
    target_error_code = request.get("session_target_error_code")
    target_error = request.get("session_target_error")
    if isinstance(target_error_code, str) and target_error_code:
        exact_recovery = request.get("session_target_recovery")
        recovery = (
            exact_recovery
            if isinstance(exact_recovery, str) and exact_recovery.strip()
            else (
                "Create one healthy claim for this native session with the exact typed maintenance_worktree "
                "claim-bootstrap transaction, or close duplicate claims before mutating. The raw Bash "
                "bootstrap form must start with /usr/bin/python3 and the installed canonical "
                "scripts/claim_bootstrap.py; bare python3 is intentionally not admitted."
            )
        )
        result = _decision(
            started=started,
            request=request,
            mode=mode,
            decision="allow" if mode == "off" else ("observe_violation" if mode == "observe" else "deny"),
            reason_code=target_error_code,
            context=None,
            details=(str(target_error),) if target_error else (),
            recovery=recovery,
        )
        _record_receipt(receipt_path, result)
        return result
    try:
        context = _repository_context(request)
    except FastPreWriteError as exc:
        result = _decision(
            started=started,
            request=request,
            mode=mode,
            decision="allow" if mode == "off" else ("observe_violation" if mode == "observe" else "deny"),
            reason_code="repository_identity_unavailable",
            context=None,
            details=(str(exc),),
            recovery="Run the write from a named branch in a governed Git worktree.",
        )
        _record_receipt(receipt_path, result)
        return result

    if mode == "off":
        result = _decision(
            started=started,
            request=request,
            mode=mode,
            decision="allow",
            reason_code="mode_off",
            context=context,
        )
        _record_receipt(receipt_path, result)
        return result

    resolved_claims = claims_dir.expanduser().resolve()
    resolved_projection = (projection_path or projection_path_for(resolved_claims)).expanduser().resolve()
    projection, projection_error = _load_projection(
        resolved_projection,
        claims_dir=resolved_claims,
    )
    if projection is None:
        result = _decision(
            started=started,
            request=request,
            mode=mode,
            decision="observe_violation" if mode == "observe" else "deny",
            reason_code="projection_unavailable_or_stale",
            context=context,
            details=(projection_error or "projection unavailable",),
            recovery=(
                projection_recovery_command
                or "Refresh the claim authority projection through the installed exact recovery command."
            ),
        )
        _record_receipt(receipt_path, result)
        return result

    outside_bash_paths = tuple(context.get("bash_paths_outside_worktree", ()))
    if request.get("tool_name") == "Bash" and request.get("session_target_rebound"):
        raw_command = request.get("bash_command")
        if not isinstance(raw_command, str) or not _bash_is_explicitly_bound(
            raw_command,
            Path(context["worktree_path"]),
        ):
            result = _decision(
                started=started,
                request=request,
                mode=mode,
                decision="observe_violation" if mode == "observe" else "deny",
                reason_code="bash_runtime_workdir_unattested",
                context=context,
                recovery=(
                    "The native hook omitted the shell workdir. Re-run one literal command through "
                    f"/usr/bin/env -C {context['worktree_path']} <command>, or use git/make -C with that exact worktree."
                ),
            )
            _record_receipt(receipt_path, result)
            return result
    if request.get("session_target_rebound") and request.get("bash_target_unprovable"):
        result = _decision(
            started=started,
            request=request,
            mode=mode,
            decision="observe_violation" if mode == "observe" else "deny",
            reason_code="bash_target_unprovable",
            context=context,
            recovery=(
                "Use literal paths inside the exact claimed worktree; variable, wildcard, and command "
                "expansions cannot establish mutation authority from a workspace-root hook payload."
            ),
        )
        _record_receipt(receipt_path, result)
        return result
    raw_bash_command = request.get("bash_command")
    sanctioned_canonical_sync = (
        request.get("tool_name") == "Bash"
        and isinstance(raw_bash_command, str)
        and _canonical_sync_command_targets_repo(
            raw_bash_command,
            worktree=Path(context["worktree_path"]),
            repo_root=Path(context["repo_root"]),
        )
    )
    if outside_bash_paths and not sanctioned_canonical_sync:
        recovery = (
            "If this is inspection, split it into simple read-only commands without shell loops, "
            "substitutions, or redirection. Otherwise run the mutation inside the exact claimed "
            "worktree or create a separate claimed lane."
        )
        result = _decision(
            started=started,
            request=request,
            mode=mode,
            decision="observe_violation" if mode == "observe" else "deny",
            reason_code="bash_path_outside_worktree",
            context=context,
            details=outside_bash_paths,
            recovery=recovery,
        )
        _record_receipt(receipt_path, result)
        return result

    candidates = [
        claim
        for claim in projection["claims"]
        if claim["agent"] == request["client"]
        and claim["session_id"] == request["session_id"]
        and Path(claim["worktree_path"]).expanduser().resolve() == Path(context["worktree_path"])
        and Path(claim["repo_root"]).expanduser().resolve() == Path(context["repo_root"])
        and claim["branch"] == context["branch"]
    ]
    claim: dict[str, Any] | None = None
    authorized = False
    reason_code = "exact_live_claim"
    details: tuple[str, ...] = ()
    recovery: str | None = None
    authorizing_candidates = [
        candidate
        for candidate in candidates
        if _claim_covers_targets(candidate, context["normalized_target_paths"])
    ]
    if not candidates and context["normalized_target_paths"] and all(
        _is_append_only_path(path) for path in context["normalized_target_paths"]
    ):
        # An append-only store cannot contend with itself (mirrors
        # coordination_claims.py's APPEND_ONLY_WRITE_PREFIXES conflict
        # exemption). Every target must be append-only -- a mutation mixing
        # one append-only path with any ordinary path still requires a claim.
        authorized = True
        reason_code = "append_only_exempt"
    elif not candidates:
        reason_code = "no_exact_claim"
        recovery = (
            "If this is inspection, split it into simple read-only commands without shell control flow. "
            "Otherwise create or resume an exact claimed worktree lane before editing; from a shared-root "
            f"session use /usr/bin/make -C {context['repo_root']} maintenance-worktree BRANCH=<safe-branch>."
        )
    elif len(authorizing_candidates) > 1:
        reason_code = "ambiguous_exact_claim"
        details = tuple(
            sorted(f"{item['projects'][0]}:{item['scope']}" for item in authorizing_candidates)
        )
        recovery = "Close or reconcile overlapping live claims before editing."
    elif not authorizing_candidates:
        # Preserve the exact claim on the receipt when only one identity
        # candidate exists. With parent/child claims, no single claim may
        # combine disjoint write scopes into authority for one mutation.
        claim = candidates[0] if len(candidates) == 1 else None
        if claim is not None:
            health_issues = tuple(
                dict.fromkeys([*claim["static_issues"], *_dynamic_claim_issues(claim)])
            )
            if health_issues:
                reason_code = "claim_not_healthy"
                details = health_issues
                recovery = "Repair or resume the claim through the sanctioned session workflow."
            else:
                reason_code = "path_outside_claim"
                details = tuple(context["normalized_target_paths"])
                recovery = "Use a separately claimed lane or update the declared write scope before editing."
        else:
            reason_code = "path_outside_claim"
            details = tuple(context["normalized_target_paths"])
            recovery = (
                "Use one claim whose declared write scope covers every target; disjoint claims do not combine authority."
            )
    else:
        claim = authorizing_candidates[0]
        health_issues = tuple(dict.fromkeys([*claim["static_issues"], *_dynamic_claim_issues(claim)]))
        if health_issues:
            reason_code = "claim_not_healthy"
            details = health_issues
            recovery = "Repair or resume the claim through the sanctioned session workflow."
        else:
            authorized = True

    result = _decision(
        started=started,
        request=request,
        mode=mode,
        decision="allow" if authorized else ("observe_violation" if mode == "observe" else "deny"),
        reason_code=reason_code,
        context=context,
        claim=claim,
        details=details,
        recovery=recovery,
        cache_hit=cache_hit,
    )
    _record_receipt(receipt_path, result)
    return result


def evaluate_prewrite_fast(
    payload: dict[str, Any],
    *,
    client: str,
    mode: str,
    claims_dir: Path = DEFAULT_CLAIMS_DIR,
    projection_path: Path | None = None,
    receipt_path: Path = DEFAULT_RECEIPT_PATH,
    claim_bootstrap_classifier: BashBootstrapClassifier | None = None,
    projection_recovery_command: str | None = None,
) -> dict[str, Any]:
    """Normalize and evaluate one native hook payload."""

    request = adapt_native_payload(
        payload,
        client=client,
        claim_bootstrap_classifier=claim_bootstrap_classifier,
    )
    return evaluate_request_fast(
        request,
        mode=mode,
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_path=receipt_path,
        projection_recovery_command=projection_recovery_command,
    )


def native_mutation_worktree(payload: dict[str, Any], *, client: str) -> Path:
    """Resolve the Git worktree named by one native mutation event.

    This is target discovery only: it writes no receipt and grants no mutation
    authority. Consumers must still resolve a healthy exact-session claim and
    run their own output-path admission. Post-event consumers may pass their
    native payload; target syntax is normalized as the corresponding pre-event.
    """

    request = adapt_native_payload(
        dict(payload, hook_event_name="PreToolUse"),
        client=client,
    )
    context = _repository_context(request)
    return Path(context["worktree_path"])


__all__ = [
    "DEFAULT_CLAIMS_DIR",
    "DEFAULT_PROJECTION_PATH",
    "DEFAULT_RECEIPT_PATH",
    "FastPreWriteError",
    "adapt_native_payload",
    "classify_bash_command",
    "evaluate_prewrite_fast",
    "evaluate_request_fast",
    "native_mutation_worktree",
    "projection_path_for",
    "registry_digest",
]
