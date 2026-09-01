#!/usr/bin/env python3
"""Dependency-light native hook adapter for canonical pre-write claims."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning.prewrite_claim_fast import (
    DEFAULT_CLAIMS_DIR,
    DEFAULT_PROJECTION_PATH,
    DEFAULT_RECEIPT_PATH,
    FastPreWriteError,
    classify_bash_command,
    evaluate_prewrite_fast,
)


class NonGitWorkingDirectory(FastPreWriteError):
    """The native hook cwd is outside a Git checkout."""


_DENIAL_SUMMARIES = {
    "ambiguous_exact_claim": "More than one claim matches this repository lane.",
    "ambiguous_exact_session_target": "More than one healthy claim could select the session target.",
    "bash_path_outside_worktree": "The command names a mutation path outside the claimed worktree.",
    "bash_runtime_workdir_unattested": "The shell command does not prove it will run in the claimed worktree.",
    "bash_target_unprovable": "The command uses a target that cannot be resolved safely from the hook payload.",
    "claim_git_identity_mismatch": "The claimed worktree no longer matches its recorded Git identity.",
    "claim_not_healthy": "The matching claim is stale, incomplete, or otherwise unhealthy.",
    "client_identity_mismatch": "The event identity belongs to a different native client.",
    "no_exact_claim": "This session has no exact live claim for the target worktree.",
    "no_exact_session_target": "This workspace-root session has no healthy claim selecting a target worktree.",
    "target_worktree_not_claimed": "This session has no healthy claim for the explicitly targeted worktree.",
    "path_outside_claim": "The mutation target is outside the claim's declared write paths.",
    "projection_unavailable_or_stale": "The claim authority projection is unavailable or stale.",
    "repository_identity_unavailable": "The target repository could not be resolved from this event.",
    "session_identity_unavailable": "The event does not identify the native session that would own the mutation.",
    "unsupported_client": "The event names a client that this hook cannot authenticate.",
}


def _compact_detail(value: object, *, limit: int = 240) -> str:
    compact = " ".join(str(value).split())
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _native_denial_message(decision: dict[str, Any]) -> str:
    """Render one compact actionable denial; full diagnostics stay in receipts/JSON."""

    reason = str(decision.get("reason_code") or "unknown")
    summary = _DENIAL_SUMMARIES.get(reason, "The requested mutation lacks verified authority.")
    lines = [f"BLOCKED [prewrite/{reason}]", f"Why: {summary}"]
    details = decision.get("details")
    if isinstance(details, list) and details and reason not in {
        "projection_unavailable_or_stale",
        "repository_identity_unavailable",
    }:
        rendered = "; ".join(_compact_detail(item) for item in details[:2])
        if len(details) > 2:
            rendered += f"; +{len(details) - 2} more"
        lines.append(f"Details: {rendered}")
    recovery = decision.get("recovery")
    if recovery:
        lines.append(f"Next: {_compact_detail(recovery, limit=600)}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True, choices=("codex", "claude-code"))
    parser.add_argument("--mode", choices=("off", "observe", "enforce"))
    parser.add_argument("--claims-dir", type=Path, default=DEFAULT_CLAIMS_DIR)
    parser.add_argument("--projection-path", type=Path)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Compatibility alias: use <dir>/authority-projection-v1.json.",
    )
    parser.add_argument("--receipt-path", type=Path, default=DEFAULT_RECEIPT_PATH)
    outcome_source = parser.add_mutually_exclusive_group()
    outcome_source.add_argument(
        "--outcome-scenario",
        type=Path,
        help="Explicit immutable scenario to correlate after the ordinary decision.",
    )
    outcome_source.add_argument(
        "--outcome-selected",
        action="store_true",
        help="Resolve the create-once scenario from the exact claim-linked session tracker.",
    )
    outcome_source.add_argument(
        "--outcome-enforce-selected",
        action="store_true",
        help="Require exact selected outcome admission after ordinary claim admission.",
    )
    parser.add_argument(
        "--outcome-receipt-path",
        type=Path,
        help="Append-only receipt path for an explicit outcome observation or admission.",
    )
    parser.add_argument("--json", action="store_true", help="Print the decision instead of native hook output.")
    return parser


def _git_root(cwd: str) -> Path:
    completed = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "unable to resolve Git worktree"
        if "not a git repository" in detail.lower():
            raise NonGitWorkingDirectory(detail)
        raise FastPreWriteError(detail)
    return Path(completed.stdout.strip()).resolve()


def _load_mode(repo_root: Path) -> str:
    import yaml  # type: ignore[import-untyped]

    config_path = repo_root / "meta-process.yaml"
    if not config_path.is_file():
        return "off"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if payload is None:
        return "off"
    if not isinstance(payload, dict):
        raise FastPreWriteError(f"{config_path} must contain a YAML mapping")
    meta_process = payload.get("meta_process", payload)
    if not isinstance(meta_process, dict):
        raise FastPreWriteError("meta-process.yaml meta_process must be a mapping")
    claims = meta_process.get("claims", {})
    if claims is None:
        return "off"
    if not isinstance(claims, dict):
        raise FastPreWriteError("meta-process.yaml claims must be a mapping")
    mode = claims.get("prewrite_mode", "off")
    # PyYAML follows YAML 1.1 scalar rules, where an unquoted ``off`` is
    # loaded as Boolean false.  The public configuration vocabulary explicitly
    # names ``off`` as a valid mode, so preserve that spelling's intended
    # meaning while continuing to reject every other non-string value.
    if mode is False:
        mode = "off"
    if mode not in {"off", "observe", "enforce"}:
        raise FastPreWriteError("claims.prewrite_mode must be one of: off, observe, enforce")
    return str(mode)


def _mode(payload: dict[str, Any], explicit: str | None) -> str:
    """Resolve the effective mode for the already target-rebound payload.

    ``main`` rebinds ``payload["cwd"]`` to the repository that actually owns
    the mutation target before calling this, so the question here is whether
    *that* location is a governed checkout -- never merely where the native
    session happened to launch.

    An explicit host ``--mode enforce`` still enforces inside a Git checkout.
    Outside one there is no repository whose claims could authorise the write
    and no repo-local mode to load, so enforcing there denies every write
    including the ``Edit`` that would reconfigure this hook.  That bootstrap
    trap caused two total session outages, so an explicit enforce downgrades
    to ``observe`` outside a checkout instead of denying.
    """

    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        cwd = str(Path.cwd())
    if explicit is not None and explicit != "enforce":
        return explicit
    try:
        repo_root = _git_root(cwd)
    except NonGitWorkingDirectory:
        if explicit != "enforce":
            return "off"
        if isinstance(payload.get("_session_target_error_code"), str):
            # Target resolution did not merely find no governed repository --
            # it failed.  The session has claim authority that does not cover
            # this event (unclaimed, ambiguous, unhealthy, or an explicitly
            # named worktree outside the claim).  Downgrading here would let
            # any claimed session escape its own claim from a workspace root,
            # so unresolved authority still fails closed.
            return "enforce"
        return "observe"
    if explicit is not None:
        return explicit
    return _load_mode(repo_root)


def _configured_outcome_mode(payload: dict[str, Any]) -> str:
    """Load the strict repo-local outcome mode from the actual checkout."""

    from enforced_planning.outcome_admission import load_outcome_admission_mode

    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        cwd = str(Path.cwd())
    try:
        return load_outcome_admission_mode(_git_root(cwd))
    except NonGitWorkingDirectory:
        # Outside git repos: no repo-local outcome mode to load.
        return "off"


def _resolved_outcome_mode(payload: dict[str, Any], *, explicit_mode: str | None) -> str:
    """Use repo outcome policy when present, or explicit host mode outside Git."""

    try:
        return _configured_outcome_mode(payload)
    except NonGitWorkingDirectory:
        if explicit_mode is not None:
            return "off"
        raise


def _session_bound_payload(
    payload: dict[str, Any],
    *,
    client: str,
    claims_dir: Path,
    projection_path: Path,
) -> dict[str, Any]:
    """Resolve non-Git Bash events through one exact native-session claim.

    Native hook ``cwd`` is the immutable session launch directory.  A client
    can execute an individual shell call in another directory without that
    target appearing in the hook payload.  When the launch directory is not a
    Git checkout, one healthy exact-session claim is therefore the only
    structured target authority available to the hook.

    Zero or multiple matching claims deliberately preserve the original
    payload so ordinary admission fails closed with no guessed target.
    """

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return payload
    needs_rebind = tool_name == "Bash"
    target_worktree: Path | None = None
    explicit_paths: tuple[str, ...] = ()
    if tool_name == "Bash":
        from enforced_planning.prewrite_claim_fast import _bash_explicit_worktree

        command = tool_input.get("command")
        if isinstance(command, str):
            target_worktree = _bash_explicit_worktree(command)
    elif tool_name == "apply_patch":
        from enforced_planning.prewrite_claim_fast import _patch_paths

        command = tool_input.get("command")
        paths = _patch_paths(command) if isinstance(command, str) else ()
        explicit_paths = paths
        needs_rebind = bool(paths) and any(not Path(path).expanduser().is_absolute() for path in paths)
    elif tool_name in {"Edit", "Write", "NotebookEdit"}:
        field = "notebook_path" if tool_name == "NotebookEdit" else "file_path"
        value = tool_input.get(field)
        explicit_paths = (value,) if isinstance(value, str) else ()
        needs_rebind = isinstance(value, str) and not Path(value).expanduser().is_absolute()
    if not needs_rebind:
        absolute = [Path(path).expanduser() for path in explicit_paths if Path(path).expanduser().is_absolute()]
        if absolute and len(absolute) == len(explicit_paths):
            roots: list[Path] = []
            try:
                for path in absolute:
                    probe = path
                    while not probe.exists() and probe != probe.parent:
                        probe = probe.parent
                    if probe.is_file():
                        probe = probe.parent
                    roots.append(_git_root(str(probe)))
            except NonGitWorkingDirectory:
                return payload
            if roots and all(root == roots[0] for root in roots):
                targeted = dict(payload)
                targeted["cwd"] = str(roots[0])
                targeted["_explicit_target_worktree"] = str(roots[0])
                return targeted
        return payload
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        return payload
    try:
        launch_root = _git_root(cwd)
    except NonGitWorkingDirectory:
        launch_root = None

    from enforced_planning.session_target import (
        SessionTargetError,
        resolve_exact_session_target,
    )

    try:
        resolution = resolve_exact_session_target(
            payload,
            client=client,
            claims_dir=claims_dir,
            projection_path=projection_path,
            target_worktree=target_worktree,
        )
    except SessionTargetError as exc:
        # A Git launch directory remains a valid local fallback only when this
        # native session has no claimed target at all.  Ambiguous, unhealthy,
        # or stale claim authority must not be hidden merely because the
        # immutable launch cwd happens to be another repository.
        if exc.reason_code == "no_exact_session_target" and launch_root is not None:
            return payload
        unresolved = dict(payload)
        unresolved["_session_target_error_code"] = exc.reason_code
        unresolved["_session_target_error"] = str(exc)
        return unresolved
    if launch_root == resolution.worktree_path:
        # The launch directory is already inside the exact claimed worktree;
        # no synthetic rebound (and therefore no extra runtime -C attestation)
        # is necessary.
        return payload
    rebound = dict(payload)
    rebound["cwd"] = str(resolution.worktree_path)
    rebound["_session_target_worktree"] = str(resolution.worktree_path)
    return rebound


def _native_notice(message: str) -> str:
    return json.dumps({"systemMessage": message}, sort_keys=True)


def _parse_native_mailbox_command(
    command: str,
    *,
    client: str,
    native_session: str | None = None,
) -> None:
    """Validate one exact host mailbox command before claimless admission.

    The mailbox CLI already binds mutating operations to the ambient native
    session. This outer parser prevents shell composition and path/registry
    overrides before allowing that narrower authority check to run.
    """

    from enforced_planning import coordination_messages

    if "\n" in command or "\r" in command:
        raise ValueError("mailbox command must be exactly one line")
    script = (REPO_ROOT / "scripts" / "coordination_messages.py").resolve()
    prefix = f"/usr/bin/python3 {script} "
    if not command.startswith(prefix):
        raise ValueError("mailbox command does not use the canonical host script")
    remainder = command[len(prefix) :]
    operation, separator, request_token = remainder.partition(" --request-json '")
    if separator == "" or operation not in {"send", "poll", "status", "acknowledge"}:
        raise ValueError("mailbox command has no supported exact operation")
    if not request_token.endswith("'"):
        raise ValueError("mailbox request JSON must be one shell single-quoted token")
    raw_json = request_token[:-1]
    if "'" in raw_json:
        raise ValueError("mailbox JSON apostrophes must be encoded as \\u0027")

    model_by_operation = {
        "send": coordination_messages.SendMessageRequest,
        "poll": coordination_messages.PollMessagesRequest,
        "status": coordination_messages.MessageStatusRequest,
        "acknowledge": coordination_messages.AcknowledgeMessageRequest,
    }
    request = model_by_operation[operation].model_validate_json(raw_json)
    if operation == "status":
        return
    session_field = {
        "send": "caller_session_id",
        "poll": "current_session_id",
        "acknowledge": "current_session_id",
    }[operation]
    caller = getattr(request, session_field)
    if native_session is None or caller != native_session:
        raise ValueError("mailbox caller does not match the ambient native session")
    if operation == "send" and request.sender_session_id != native_session:
        raise ValueError("mailbox sender does not match the ambient native session")


def _parse_plan_execution_cursor_command(
    command: str,
    *,
    client: str,
    claims_dir: Path,
    native_session: str | None = None,
) -> None:
    """Validate the version-bound plan cursor manager as one control mutation."""

    from enforced_planning import coordination_claims

    if "\n" in command or "\r" in command:
        raise ValueError("plan execution cursor command must be exactly one line")
    tokens = shlex.split(command)
    if any(token in {";", "&", "&&", "|", "||", ">", ">>", "<"} for token in tokens):
        raise ValueError("plan execution cursor command cannot compose shell operations")
    if len(tokens) < 7 or tokens[0] != "/usr/bin/python3":
        raise ValueError("plan execution cursor command requires the canonical interpreter")

    script = Path(tokens[1]).expanduser()
    cache_root = (
        Path.home() / ".codex" / "plugins" / "cache" / "inside-success" / "company-planning"
    ).resolve()
    if not script.is_absolute() or script.resolve() != script or not script.is_file():
        raise ValueError("plan execution cursor manager must be one canonical installed file")
    try:
        relative_script = script.relative_to(cache_root)
    except ValueError as exc:
        raise ValueError("plan execution cursor manager is outside the trusted plugin cache") from exc
    if len(relative_script.parts) != 3 or relative_script.parts[1:] != (
        "scripts",
        "manage_plan_execution.py",
    ):
        raise ValueError("plan execution cursor manager has an invalid installed layout")
    version = relative_script.parts[0]
    manifest_path = cache_root / version / ".codex-plugin" / "plugin.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("plan execution cursor manager has no valid installed manifest") from exc
    if manifest.get("name") != "company-planning" or manifest.get("version") != version:
        raise ValueError("plan execution cursor manager version does not match its manifest")

    if tokens[2] != "--cwd" or tokens[4] != "--session-id":
        raise ValueError("plan execution cursor command does not match the canonical CLI order")
    worktree = Path(tokens[3]).expanduser()
    if not worktree.is_absolute() or worktree.resolve() != worktree:
        raise ValueError("plan execution cursor cwd must be canonical and absolute")
    if native_session is None or tokens[5] != native_session:
        raise ValueError("plan execution cursor session does not match the ambient native session")

    operation = tokens[6]
    candidate: Path | None = None
    if operation == "start" and len(tokens) == 8:
        candidate = Path(tokens[7]).expanduser()
    elif operation == "replace" and len(tokens) == 10 and tokens[8] == "--expected-revision":
        candidate = Path(tokens[7]).expanduser()
        try:
            if int(tokens[9]) < 1:
                raise ValueError
        except ValueError as exc:
            raise ValueError("plan execution cursor expected revision must be positive") from exc
    elif operation == "archive" and len(tokens) == 7:
        pass
    else:
        raise ValueError("plan execution cursor command does not match a supported exact operation")
    if candidate is not None and (
        not candidate.is_absolute()
        or candidate.resolve() != candidate
        or candidate.suffix != ".json"
        or not candidate.is_file()
    ):
        raise ValueError("plan execution cursor candidate must be one canonical readable JSON file")

    active_claims = coordination_claims.check_claims(claims_dir=claims_dir)
    claims = [
        claim
        for claim in active_claims
        if claim.agent == client
        and claim.session_id == native_session
        and claim.is_live()
        and (claim.target_worktree_path or claim.worktree_path)
        and Path(claim.target_worktree_path or claim.worktree_path).expanduser().resolve() == worktree
    ]
    if len(claims) != 1:
        raise ValueError("plan execution cursor target is not the ambient runtime's exact live claim")
    claim = claims[0]
    if coordination_claims.claim_runtime_status(claim, active_claims=active_claims) != "healthy":
        raise ValueError("plan execution cursor target claim is not healthy")
    required_paths = [".company-planning/active-execution.json"]
    if operation == "archive":
        required_paths.append(".company-planning/history")
    normalized_claim_paths = [
        coordination_claims._normalize_repo_path(path) for path in claim.write_paths
    ]
    if any(
        not any(coordination_claims._paths_overlap(required, owned) for owned in normalized_claim_paths)
        for required in required_paths
    ):
        raise ValueError("plan execution cursor output is outside the exact claim")


def _parse_native_closeout_command(
    command: str,
    *,
    client: str,
    claims_dir: Path,
    native_session: str | None = None,
) -> None:
    """Validate one exact closeout command for the ambient claim owner.

    Closeout is a control-plane mutation, not ordinary repository work.  It is
    admitted only through the canonical host script and only when every target
    identity resolves to one live claim owned by the native runtime.
    """

    from enforced_planning import coordination_claims
    from scripts import session_close, session_finish

    if "\n" in command or "\r" in command:
        raise ValueError("closeout command must be exactly one line")
    tokens = shlex.split(command)
    close_script = (REPO_ROOT / "scripts" / "session_close.py").resolve()
    finish_script = (REPO_ROOT / "scripts" / "session_finish.py").resolve()
    if len(tokens) < 8 or tokens[0] != "/usr/bin/python3" or tokens[1] not in {
        str(close_script),
        str(finish_script),
    }:
        raise ValueError("closeout command does not use the canonical host script")
    if any(token in {";", "&", "&&", "|", "||", ">", ">>", "<"} for token in tokens):
        raise ValueError("closeout command cannot compose shell operations")
    parser = session_finish.parse_args if tokens[1] == str(finish_script) else session_close.parse_args
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            args = parser(tokens[2:])
    except SystemExit as exc:
        raise ValueError("closeout command does not match the canonical CLI grammar") from exc
    if native_session is None or args.agent != client:
        raise ValueError("closeout agent does not match the ambient native client")
    if tokens[1] == str(finish_script):
        if not args.allow_dirty_handoff or args.release_claim:
            raise ValueError("session-finish bypass is restricted to dirty handoff recovery")
        if args.session_id not in {None, native_session}:
            raise ValueError("session-finish asserted session does not match the ambient native session")
    matches = [
        claim
        for claim in coordination_claims.check_claims(project=args.project, claims_dir=claims_dir)
        if claim.agent == args.agent
        and claim.scope == args.scope
        and claim.session_id == native_session
        and claim.is_live()
    ]
    if len(matches) != 1:
        raise ValueError("closeout target is not the ambient runtime's exact live claim")
    claim = matches[0]
    effective_worktree = claim.target_worktree_path or claim.worktree_path
    if args.worktree_path and Path(args.worktree_path).expanduser().resolve() != Path(
        effective_worktree or ""
    ).expanduser().resolve():
        raise ValueError("closeout worktree does not match the exact live claim")
    if getattr(args, "branch", None) and args.branch != claim.branch:
        raise ValueError("closeout branch does not match the exact live claim")


def _same_file_digest(left: Path, right: Path) -> bool:
    """Compare bounded control files without trusting path names alone."""

    try:
        return hashlib.sha256(left.read_bytes()).digest() == hashlib.sha256(right.read_bytes()).digest()
    except OSError:
        return False


def _rendered_consumer_worktree_block_matches(target_makefile: Path) -> bool:
    """Match only the installed governed block, not consumer-owned Make content."""

    start = "# >>> META-PROCESS WORKTREE TARGETS >>>"
    end = "# <<< META-PROCESS WORKTREE TARGETS <<<"
    try:
        target_text = target_makefile.read_text(encoding="utf-8")
        template_text = (REPO_ROOT / "templates" / "Makefile.worktree.block.template").read_text(
            encoding="utf-8"
        )
    except OSError:
        return False
    expected = template_text.replace(
        "__WORKTREE_SCRIPT_ROOT__", "scripts/meta/worktree-coordination"
    ).strip()
    start_at = target_text.find(start)
    end_at = target_text.find(end, start_at + len(start))
    if start_at < 0 or end_at < 0:
        return False
    actual = target_text[start_at : end_at + len(end)].strip()
    return hashlib.sha256(actual.encode()).digest() == hashlib.sha256(expected.encode()).digest()


def _parse_hook_feedback_report_command(command: str) -> None:
    """Validate the exact content-free report entrypoint as claimless observation."""

    from scripts import hook_feedback_report

    if "\n" in command or "\r" in command or any(char in command for char in ";&|<>`$"):
        raise ValueError("hook feedback command cannot compose shell operations")
    tokens = shlex.split(command)
    canonical_script = (REPO_ROOT / "scripts" / "hook_feedback_report.py").resolve()
    report_args: list[str]
    if len(tokens) >= 2 and tokens[:2] == ["/usr/bin/python3", str(canonical_script)]:
        report_args = tokens[2:]
    elif len(tokens) in {4, 5} and tokens[0] in {"make", "/usr/bin/make"} and tokens[1] == "-C":
        target = Path(tokens[2]).expanduser()
        if not target.is_absolute() or tokens[3] != "hook-feedback-report":
            raise ValueError("hook feedback Make target must use one absolute -C directory")
        target = target.resolve()
        target_script = target / "scripts" / "hook_feedback_report.py"
        target_makefile = target / "Makefile"
        if target != REPO_ROOT.resolve() and not (
            _same_file_digest(target_script, canonical_script)
            and _same_file_digest(target_makefile, REPO_ROOT / "Makefile")
        ):
            raise ValueError("hook feedback Make target does not match the installed control revision")
        if len(tokens) == 5:
            key, separator, raw_args = tokens[4].partition("=")
            if key != "ARGS" or not separator:
                raise ValueError("hook feedback Make target accepts only one ARGS assignment")
            report_args = shlex.split(raw_args)
        else:
            report_args = []
    else:
        raise ValueError("hook feedback command does not use a canonical entrypoint")
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            hook_feedback_report._parser().parse_args(report_args)
    except SystemExit as exc:
        raise ValueError("hook feedback arguments do not match the read-only report grammar") from exc


def _parse_maintenance_worktree_make_command(command: str, *, client: str) -> None:
    """Validate the exact self-claiming maintenance Make entrypoint.

    This admission is deliberately narrower than Make's general variable
    surface. The target remains responsible for executing the typed atomic
    bootstrap; this parser only lets that target get far enough to create the
    claim that ordinary pre-write admission requires.
    """

    if "\n" in command or "\r" in command or any(char in command for char in ";&|<>`$"):
        raise ValueError("maintenance-worktree command cannot compose shell operations")
    tokens = shlex.split(command)
    if len(tokens) < 5 or tokens[0] not in {"make", "/usr/bin/make"} or tokens[1] != "-C":
        raise ValueError("maintenance-worktree command must use make -C")
    target = Path(tokens[2]).expanduser()
    if not target.is_absolute() or target.resolve() != target or tokens[3] != "maintenance-worktree":
        raise ValueError("maintenance-worktree requires one canonical absolute Make directory")
    target = target.resolve()
    canonical_bootstrap = REPO_ROOT / "scripts" / "claim_bootstrap.py"
    canonical_module = REPO_ROOT / "enforced_planning" / "claim_bootstrap.py"
    if target != REPO_ROOT.resolve() and not (
        _rendered_consumer_worktree_block_matches(target / "Makefile")
        and _same_file_digest(target / "scripts" / "meta" / "claim_bootstrap.py", canonical_bootstrap)
        and _same_file_digest(
            target / "enforced_planning" / "claim_bootstrap.py", canonical_module
        )
    ):
        raise ValueError("maintenance-worktree target does not match the installed control revision")

    assignments: dict[str, str] = {}
    for token in tokens[4:]:
        key, separator, value = token.partition("=")
        if not separator or key not in {"BRANCH", "SESSION_WRITE_PATHS", "WORKTREE_AGENT"}:
            raise ValueError("maintenance-worktree accepts only bounded bootstrap assignments")
        if key in assignments:
            raise ValueError("maintenance-worktree assignments must be unique")
        assignments[key] = value
    branch = assignments.get("BRANCH", "")
    if (
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch) is None
        or branch.startswith(("-", "/"))
        or branch.endswith(("/", "."))
        or ".." in branch
        or "//" in branch
        or branch in {"main", "master"}
    ):
        raise ValueError("maintenance-worktree branch is not a safe literal")
    asserted_agent = assignments.get("WORKTREE_AGENT")
    if asserted_agent is not None and asserted_agent != client:
        raise ValueError("maintenance-worktree agent does not match the native client")
    raw_paths = assignments.get("SESSION_WRITE_PATHS")
    if raw_paths is not None:
        paths = raw_paths.split()
        if not paths or len(paths) != len(set(paths)):
            raise ValueError("maintenance-worktree write paths must be unique non-empty literals")
        for value in paths:
            path = Path(value)
            if (
                path.is_absolute()
                or ".." in path.parts
                or path.as_posix() != value
                or any(char in value for char in "\\:*?[]")
            ):
                raise ValueError("maintenance-worktree write path is not a safe repository literal")
        if "." in paths and paths != ["."]:
            raise ValueError("whole-repository maintenance scope cannot be mixed with narrow paths")


def _parse_native_narrow_command(
    command: str,
    *,
    client: str,
    claims_dir: Path,
    native_session: str | None = None,
) -> None:
    """Admit one exact owner-bound recovery command for claim narrowing.

    Governed repositories expose the Make target. Project-Graph-registered
    repositories outside the governed fleet may not; they use the canonical
    installed script directly. Both forms resolve the same live claim and
    retain the same strict-subset and native-session checks.
    """

    from enforced_planning import coordination_claims
    from scripts import session_narrow

    if "\n" in command or "\r" in command or any(char in command for char in ";&|<>`$"):
        raise ValueError("session-narrow command cannot compose shell operations")
    tokens = shlex.split(command)
    target: Path | None = None
    if (
        len(tokens) == 8
        and tokens[0:2] == ["/usr/bin/make", "-C"]
        and tokens[3] == "session-narrow"
    ):
        target = Path(tokens[2]).expanduser()
        if not target.is_absolute():
            raise ValueError("session-narrow target must be one absolute worktree")
        assignments: dict[str, str] = {}
        for token in tokens[4:]:
            key, separator, value = token.partition("=")
            if not separator or key in assignments:
                raise ValueError("session-narrow variables must be unique literal assignments")
            assignments[key] = value
        required = {"WORKTREE_AGENT", "WORKTREE_PROJECT", "BRANCH", "SESSION_WRITE_PATHS"}
        if set(assignments) != required:
            raise ValueError("session-narrow command has missing or extra variables")
        agent = assignments["WORKTREE_AGENT"]
        project = assignments["WORKTREE_PROJECT"]
        scope = assignments["BRANCH"]
        raw_replacements = assignments["SESSION_WRITE_PATHS"].split()
    else:
        script = (REPO_ROOT / "scripts" / "session_narrow.py").resolve()
        if len(tokens) < 10 or tokens[:2] != ["/usr/bin/python3", str(script)]:
            raise ValueError("session-narrow command does not match a canonical recovery grammar")
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                args = session_narrow.parse_args(tokens[2:])
        except SystemExit as exc:
            raise ValueError("session-narrow command does not match the canonical CLI grammar") from exc
        if args.session_id not in {None, native_session}:
            raise ValueError("session-narrow asserted session does not match the ambient native session")
        agent = args.agent
        project = args.project
        scope = args.scope
        raw_replacements = args.write_path
    if agent != client:
        raise ValueError("session-narrow client does not match the ambient native client")
    if native_session is None:
        raise ValueError("session-narrow requires an ambient native session")
    matches = [
        claim
        for claim in coordination_claims.check_claims(
            project=project, claims_dir=claims_dir
        )
        if claim.agent == client
        and claim.scope == scope
        and claim.session_id == native_session
    ]
    if len(matches) != 1:
        raise ValueError("session-narrow target is not the ambient runtime's exact live claim")
    claim = matches[0]
    effective_target = claim.target_worktree_path or claim.worktree_path
    if target is not None and (
        not effective_target or Path(effective_target).expanduser().resolve() != target.resolve()
    ):
        raise ValueError("session-narrow Make directory does not match the exact claim target")
    replacements = [
        coordination_claims._normalize_repo_path(path)
        for path in raw_replacements
    ]
    if not replacements or len(replacements) != len(set(replacements)):
        raise ValueError("session-narrow requires unique non-empty replacement paths")
    if any(
        Path(path).is_absolute()
        or path == ".."
        or path.startswith("../")
        or any(char in path for char in "*?[]\\")
        for path in replacements
    ):
        raise ValueError("session-narrow replacement paths are not safe repository literals")
    old_paths = [coordination_claims._normalize_repo_path(path) for path in claim.write_paths]
    if set(replacements) == set(old_paths) or any(
        not any(
            coordination_claims._replacement_is_within_existing_authority(path, old)
            for old in old_paths
        )
        for path in replacements
    ):
        raise ValueError("session-narrow replacements are not a strict subset of existing authority")


def _special_unclaimed_command(
    command: str,
    *,
    client: str,
    claims_dir: Path,
    projection_path: Path,
    subagent_event: bool,
    native_session: str | None = None,
) -> bool | str:
    """Classify one exact typed bootstrap, read-target, or recovery operation."""

    try:
        from enforced_planning.claim_bootstrap import parse_projection_recovery_command

        parse_projection_recovery_command(
            command,
            script_path=(REPO_ROOT / "scripts" / "refresh_prewrite_claim_projection.py").resolve(),
            claims_dir=claims_dir,
            projection_path=projection_path,
        )
        return "projection_recovery"
    except Exception:  # noqa: BLE001 -- try the typed bootstrap grammar
        pass

    if subagent_event:
        return False
    try:
        _parse_maintenance_worktree_make_command(command, client=client)
        return "claim_bootstrap"
    except Exception as exc:  # noqa: BLE001 -- try the remaining strict control grammars
        _ = exc
    try:
        _parse_hook_feedback_report_command(command)
        return "hook_feedback_report"
    except Exception as exc:  # noqa: BLE001 -- try the remaining strict control grammars
        _ = exc
    try:
        _parse_native_mailbox_command(
            command,
            client=client,
            native_session=native_session,
        )
        return "native_mailbox"
    except Exception:  # noqa: BLE001 -- try the remaining strict control grammars
        pass
    try:
        _parse_plan_execution_cursor_command(
            command,
            client=client,
            claims_dir=claims_dir,
            native_session=native_session,
        )
        # Compatibility classification: this strict control-plane mutation
        # owns its own fixed output contract just like typed claim bootstrap.
        return "claim_bootstrap"
    except Exception:  # noqa: BLE001 -- try the remaining strict control grammars
        pass
    try:
        _parse_native_closeout_command(
            command,
            client=client,
            claims_dir=claims_dir,
            native_session=native_session,
        )
        return "native_closeout"
    except Exception:  # noqa: BLE001 -- try the remaining strict control grammars
        pass
    try:
        _parse_native_narrow_command(
            command,
            client=client,
            claims_dir=claims_dir,
            native_session=native_session,
        )
        return "native_session_narrow"
    except Exception:  # noqa: BLE001 -- try the remaining strict control grammars
        pass
    try:
        from enforced_planning.read_target import parse_raw_bash_command as parse_read_target_command

        request = parse_read_target_command(
            command,
            script_path=(REPO_ROOT / "scripts" / "session_read_target.py").resolve(),
        )
        if request.get("client") != client:
            return False
        return "read_target_selection"
    except Exception:  # noqa: BLE001 -- try the typed claim bootstrap grammar
        pass
    try:
        from enforced_planning.claim_bootstrap import parse_raw_bash_command

        parse_raw_bash_command(
            command,
            script_path=(REPO_ROOT / "scripts" / "claim_bootstrap.py").resolve(),
        )
        return "claim_bootstrap"
    except Exception:  # noqa: BLE001 -- any ambiguity must require a live claim
        return False


def _is_subagent_event(payload: dict[str, Any], *, client: str) -> bool:
    """Distinguish a child identity from Codex root payload duplication."""

    raw_agent = payload.get("agent_id")
    if not isinstance(raw_agent, str) or not raw_agent.strip():
        return False
    from enforced_planning.session_target import SessionTargetError, effective_session_id

    try:
        effective_agent = effective_session_id(payload, client)
        parent_payload = dict(payload)
        parent_payload.pop("agent_id", None)
        effective_parent = effective_session_id(parent_payload, client)
    except SessionTargetError:
        return True
    return effective_agent != effective_parent


def _is_claim_bootstrap_command(command: str) -> bool:
    """Compatibility helper for callers testing the legacy typed bootstrap."""

    try:
        from enforced_planning.claim_bootstrap import parse_raw_bash_command

        parse_raw_bash_command(
            command,
            script_path=(REPO_ROOT / "scripts" / "claim_bootstrap.py").resolve(),
        )
    except Exception:  # noqa: BLE001 -- ambiguity requires ordinary admission
        return False
    return True


def _observe_outcome(
    decision: dict[str, Any],
    *,
    scenario_path: Path,
    receipt_path: Path | None,
) -> dict[str, Any]:
    """Lazy-load the typed observer after ordinary admission is recorded."""

    try:
        from enforced_planning.outcome_prewrite_observation import (
            DEFAULT_OUTCOME_PREWRITE_RECEIPT_PATH,
            observe_prewrite_outcome,
        )

        record = observe_prewrite_outcome(
            decision,
            scenario_path=scenario_path,
            receipt_path=receipt_path or DEFAULT_OUTCOME_PREWRITE_RECEIPT_PATH,
        )
        return record.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 -- observation cannot override ordinary admission
        # Observation is deliberately non-authoritative.  Fail visibly without
        # changing the already-recorded ordinary decision or its exit behavior.
        return {
            "schema_version": "1.0.0",
            "record_type": "outcome_prewrite_observation_unrecorded_failure",
            "ordinary_receipt_id": decision.get("receipt_id"),
            "scenario_path": str(scenario_path),
            "disposition": "observation_error",
            "error_code": getattr(exc, "code", type(exc).__name__),
            "error_message": str(exc),
            "ordinary_authority_preserved": True,
            "enforcement_applied": False,
        }


def _observe_selected_outcome(
    decision: dict[str, Any],
    *,
    receipt_path: Path | None,
) -> dict[str, Any]:
    """Lazy-load exact-session selected observation after ordinary admission."""

    try:
        from enforced_planning.outcome_prewrite_observation import (
            DEFAULT_OUTCOME_PREWRITE_RECEIPT_PATH,
            observe_selected_prewrite_outcome,
        )

        record = observe_selected_prewrite_outcome(
            decision,
            receipt_path=receipt_path or DEFAULT_OUTCOME_PREWRITE_RECEIPT_PATH,
        )
        return record.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 -- observation cannot override ordinary admission
        return {
            "schema_version": "1.0.0",
            "record_type": "outcome_prewrite_observation_unrecorded_failure",
            "ordinary_receipt_id": decision.get("receipt_id"),
            "scenario_path": "<selected-outcome>",
            "disposition": "observation_error",
            "error_code": getattr(exc, "code", type(exc).__name__),
            "error_message": str(exc),
            "ordinary_authority_preserved": True,
            "enforcement_applied": False,
        }


def _outcome_notice(observation: dict[str, Any]) -> str:
    disposition = observation.get("disposition", "observation_error")
    receipt_id = observation.get("ordinary_receipt_id")
    ordinary = observation.get("ordinary")
    if isinstance(ordinary, dict):
        receipt_id = ordinary.get("receipt_id", receipt_id)
    if disposition in {"would_allow", "would_deny"}:
        detail = observation.get("outcome_reason_code", "unknown")
    else:
        detail = observation.get("error_code", "unknown_observation_error")
    return (
        f"OUTCOME OBSERVE ONLY: {disposition} ({detail}) correlated to ordinary "
        f"receipt {receipt_id}; ordinary claim admission remains authoritative."
    )


def _exact_outcome_claim(decision: dict[str, Any]) -> Any:
    """Load the exact canonical claim named by an ordinary allow decision."""

    import yaml  # type: ignore[import-untyped]

    from enforced_planning import coordination_claims

    source_value = decision.get("claim_source_file")
    if not isinstance(source_value, str) or not source_value.strip():
        raise FastPreWriteError("ordinary allow decision lacks exact claim_source_file for outcome admission")
    source = Path(source_value).expanduser().resolve()
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FastPreWriteError(f"unable to read exact outcome claim source: {exc}") from exc
    if not isinstance(payload, dict):
        raise FastPreWriteError("exact outcome claim source must contain a YAML mapping")
    claim = coordination_claims.normalize_claim(payload, source_file=str(source))
    if claim is None:
        raise FastPreWriteError("exact outcome claim source cannot be normalized")
    return claim


def _sanctioned_maintenance_exemption(decision: dict[str, Any]) -> dict[str, Any] | None:
    """Return bounded exemption evidence only after ordinary exact-claim allow."""

    if decision.get("decision") != "allow" or decision.get("reason_code") != "exact_live_claim":
        return None
    from enforced_planning.outcome_admission import is_sanctioned_maintenance_claim

    claim = _exact_outcome_claim(decision)
    if not is_sanctioned_maintenance_claim(claim):
        return None
    return {
        "reason_code": "sanctioned_unplanned_maintenance",
        "claim_project": claim.primary_project(),
        "claim_scope": claim.scope,
        "claim_source_file": claim.source_file,
        "tracker_path": claim.tracker_path,
    }


def _enforce_selected_outcome(
    decision: dict[str, Any],
    *,
    receipt_path: Path | None,
    allow_bootstrap: bool = False,
) -> dict[str, Any]:
    """Derive, record, and return hard selected admission for one ordinary receipt."""

    from enforced_planning.outcome_admission import (
        DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH,
        OutcomeAdmissionRequestV1,
        OutcomeAdmissionResultV1,
        decide_outcome_admission,
        evaluate_claim_bootstrap_admission,
        evaluate_selected_claim_admission,
        record_outcome_admission,
    )

    ordinary_allowed = decision.get("decision") == "allow"
    if not ordinary_allowed:
        request = OutcomeAdmissionRequestV1(
            boundary="prewrite",
            enforcement_scope="new_or_renewed",
            ordinary_allowed=False,
            portfolio_state="missing",
            continuation_state="missing",
        )
        result = OutcomeAdmissionResultV1(
            source="selected",
            request=request,
            decision=decide_outcome_admission(request),
        )
    else:
        targets = decision.get("normalized_target_paths")
        if not isinstance(targets, list) or any(
            not isinstance(target, str) or not target.strip() for target in targets
        ):
            raise FastPreWriteError("ordinary allow decision has invalid normalized_target_paths")
        claim = _exact_outcome_claim(decision)
        # Bash authority is intentionally worktree-scoped, so its ordinary
        # decision has no normalized file target. Selected admission supports
        # that shape with ``target_path=None``. File tools may carry multiple
        # targets; every target must remain inside the selected outcome scope.
        target_paths: list[str | None] = targets or [None]
        result = None
        for target in target_paths:
            bootstrap_result = (
                evaluate_claim_bootstrap_admission(
                    claim,
                    target_path=target,
                    ordinary_allowed=True,
                )
                if allow_bootstrap and target is not None
                else None
            )
            candidate = bootstrap_result or evaluate_selected_claim_admission(
                claim,
                boundary="prewrite",
                ordinary_allowed=True,
                renewal=False,
                target_path=target,
            )
            result = candidate
            if candidate.decision.disposition != "allow":
                break
        assert result is not None
    receipt = record_outcome_admission(
        result,
        receipt_path=receipt_path or DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH,
    )
    return receipt.model_dump(mode="json")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload: object = {}
    outcome_mode = "off"
    outcome_config_invalid = False
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise FastPreWriteError("PreToolUse payload must be a JSON object")
        projection_path = args.projection_path
        if projection_path is None and args.cache_dir is not None:
            projection_path = args.cache_dir / "authority-projection-v1.json"
        if projection_path is None:
            projection_path = DEFAULT_PROJECTION_PATH
        payload = _session_bound_payload(
            payload,
            client=args.client,
            claims_dir=args.claims_dir,
            projection_path=projection_path,
        )
        mode = _mode(payload, args.mode)
        from enforced_planning.claim_bootstrap import projection_recovery_command

        recovery_command = projection_recovery_command(
            script_path=(REPO_ROOT / "scripts" / "refresh_prewrite_claim_projection.py").resolve(),
            claims_dir=args.claims_dir,
            projection_path=projection_path,
        )
        from enforced_planning.session_target import SessionTargetError, effective_session_id

        try:
            native_session = effective_session_id(payload, args.client)
        except SessionTargetError:
            native_session = None
        special_classifier = lambda command: _special_unclaimed_command(
            command,
            client=args.client,
            claims_dir=args.claims_dir,
            projection_path=projection_path,
            subagent_event=_is_subagent_event(payload, client=args.client),
            native_session=native_session,
        )
        early_bash_classification = None
        tool_input = payload.get("tool_input")
        if payload.get("tool_name") == "Bash" and isinstance(tool_input, dict):
            command = tool_input.get("command")
            if isinstance(command, str):
                early_bash_classification = classify_bash_command(
                    command,
                    claim_bootstrap_classifier=special_classifier,
                )
        if early_bash_classification in {
            "read_only",
            "claim_bootstrap",
            "native_mailbox",
            "native_closeout",
            "native_session_narrow",
            "hook_feedback_report",
            "read_target_selection",
            "projection_recovery",
        }:
            outcome_mode = "off"
        else:
            try:
                outcome_mode = _resolved_outcome_mode(
                    payload,
                    explicit_mode=args.mode,
                )
            except (FastPreWriteError, OSError, TypeError, ValueError):
                outcome_config_invalid = True
                raise
        decision = evaluate_prewrite_fast(
            payload,
            client=args.client,
            mode=mode,
            claims_dir=args.claims_dir,
            projection_path=projection_path,
            receipt_path=args.receipt_path,
            claim_bootstrap_classifier=special_classifier,
            projection_recovery_command=recovery_command,
        )
    except (json.JSONDecodeError, FastPreWriteError, OSError, TypeError, ValueError) as exc:
        try:
            mode = _mode(payload if isinstance(payload, dict) else {}, args.mode)
        except Exception:  # noqa: BLE001 -- retain the original fail-safe mode resolution
            mode = args.mode or "enforce"
        message = f"Pre-write claim gate could not validate this write: {exc}"
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "mode": mode,
                        "reason_code": "invalid_hook_payload",
                        "error": str(exc),
                    },
                    sort_keys=True,
                )
            )
        elif mode == "observe":
            print(_native_notice(f"OBSERVE ONLY: {message}"))
        elif mode == "enforce":
            print(message, file=sys.stderr)
        return 2 if mode == "enforce" or outcome_config_invalid else 0

    outcome_observation = None
    if args.outcome_scenario is not None:
        outcome_observation = _observe_outcome(
            decision,
            scenario_path=args.outcome_scenario,
            receipt_path=args.outcome_receipt_path,
        )
    elif args.outcome_selected:
        outcome_observation = _observe_selected_outcome(
            decision,
            receipt_path=args.outcome_receipt_path,
        )

    outcome_admission_receipt = None
    outcome_admission_exemption = None
    enforce_selected_outcome = args.outcome_enforce_selected or outcome_mode == "enforce_selected"
    # Outcome admission governs mutations. Provably read-only shell calls have
    # already been admitted without repository identity, and the strict claim
    # bootstrap commands enforce their own narrow contracts. Projection repair
    # only rebuilds a replaceable digest-bound cache. Applying selected
    # admission to any of these recreates the bootstrap trap this adapter
    # exists to prevent.
    outcome_exempt = decision.get("reason_code") in {
        "bash_read_only",
        "claim_bootstrap_command",
        "native_mailbox_command",
        "native_closeout_command",
        "hook_feedback_report_command",
        "read_target_selection_command",
        "projection_recovery_command",
    }
    enforce_selected_outcome = enforce_selected_outcome and not outcome_exempt
    if enforce_selected_outcome and decision.get("decision") == "allow":
        try:
            outcome_admission_exemption = _sanctioned_maintenance_exemption(decision)
        except FastPreWriteError:
            # The ordinary selected-admission path below owns the fail-closed
            # error report for malformed or missing exact claim state.
            outcome_admission_exemption = None
        enforce_selected_outcome = outcome_admission_exemption is None
    if enforce_selected_outcome:
        if mode != "enforce":
            message = "hard selected outcome admission requires ordinary --mode enforce"
            if args.json:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "mode": mode,
                            "reason_code": "outcome_admission_mode_invalid",
                            "error": message,
                        },
                        sort_keys=True,
                    )
                )
            else:
                print(message, file=sys.stderr)
            return 2
        try:
            outcome_admission_receipt = _enforce_selected_outcome(
                decision,
                receipt_path=args.outcome_receipt_path,
                allow_bootstrap=outcome_mode == "enforce_selected",
            )
        except Exception as exc:  # noqa: BLE001 -- hard admission fails closed
            message = f"selected outcome admission could not be recorded: {exc}"
            if args.json:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "mode": mode,
                            "reason_code": "outcome_admission_state_invalid",
                            "error": message,
                        },
                        sort_keys=True,
                    )
                )
            else:
                print(message, file=sys.stderr)
            return 2

    if args.json:
        output = decision
        if outcome_observation is not None:
            output = {**decision, "outcome_observation": outcome_observation}
        if outcome_admission_receipt is not None:
            output = {**output, "outcome_admission": outcome_admission_receipt}
        if outcome_admission_exemption is not None:
            output = {**output, "outcome_admission_exemption": outcome_admission_exemption}
        print(json.dumps(output, indent=2, sort_keys=True))
        if outcome_admission_receipt is not None:
            admission = outcome_admission_receipt["result"]["decision"]
            return 0 if admission["disposition"] == "allow" else 2
        return 2 if decision["decision"] == "deny" else 0
    outcome_notice = _outcome_notice(outcome_observation) if outcome_observation is not None else None
    if decision["decision"] == "deny":
        if outcome_notice is not None:
            print(_native_notice(outcome_notice))
        print(_native_denial_message(decision), file=sys.stderr)
        return 2
    if decision["decision"] == "observe_violation":
        message = f"OBSERVE ONLY: pre-write claim violation ({decision['reason_code']})."
        if outcome_notice is not None:
            message += f" {outcome_notice}"
        print(_native_notice(message))
    elif outcome_notice is not None:
        print(_native_notice(outcome_notice))
    if outcome_admission_receipt is not None:
        admission = outcome_admission_receipt["result"]["decision"]
        if admission["disposition"] != "allow":
            message = f"Outcome admission denied ({admission['reason_code']})"
            print(message, file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
