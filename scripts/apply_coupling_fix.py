#!/usr/bin/env python3
"""Apply verified coupling actions: auto-fix docs, log verifications, write escalations.

Reads a VerificationJudgment produced by verify_coupling.py and takes the
appropriate action:
  - CURRENT: log as verified, no file changes
  - STALE + proposed_fix: apply the fix to the coupled doc and append to log
  - STALE + no fix: append to escalations.yaml
  - UNCERTAIN: append to escalations.yaml with evidence

Usage:
    python apply_coupling_fix.py --judgment judgment.json \\
        --coupling-id "src/foo.py → docs/adr/001.md" \\
        --doc-path docs/adr/001.md \\
        --commit abc123
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from pydantic import BaseModel, Field
except ImportError:
    print("Error: pydantic required. pip install pydantic", file=sys.stderr)
    sys.exit(1)

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

DEFAULT_VERIFICATION_LOG = Path("docs/ops/verification_log.yaml")
DEFAULT_ESCALATIONS = Path("docs/ops/escalations.yaml")


class FixResult(BaseModel):
    """Result of apply_fix."""

    applied: bool = Field(description="True if a doc edit was written to disk")
    committed: bool = Field(default=False, description="True if the edit was git-committed (not done by this script)")
    escalated: bool = Field(description="True if an escalation entry was written")
    logged: bool = Field(description="True if a verification log entry was written")
    message: str = Field(description="Human-readable summary of what happened")


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _load_yaml_list(path: Path) -> list:
    if not path.exists():
        return []
    if yaml is None:
        # Fall back to JSON-style: read line by line (not ideal but avoids hard dep for callers)
        return []
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    data = yaml.safe_load(content)
    return data if isinstance(data, list) else []


def _write_yaml_list(path: Path, entries: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if yaml is None:
        # Minimal fallback: write as JSON (valid YAML)
        path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
        return
    path.write_text(yaml.dump(entries, default_flow_style=False, sort_keys=False), encoding="utf-8")


def log_verification(
    coupling_id: str,
    commit: str,
    verdict: str,
    confidence: str,
    evidence: str,
    agent: str = "claude-sonnet-4-6",
    log_path: Path = DEFAULT_VERIFICATION_LOG,
) -> None:
    """Append a CURRENT verdict to the verification log."""
    entries = _load_yaml_list(log_path)
    entries.append({
        "coupling_id": coupling_id,
        "commit": commit,
        "verdict": verdict,
        "confidence": confidence,
        "evidence": evidence,
        "verified_at": _now_iso(),
        "agent": agent,
    })
    _write_yaml_list(log_path, entries)


def write_escalation(
    coupling_id: str,
    commit: str,
    verdict: str,
    evidence: str,
    proposed_fix: str | None,
    escalations_path: Path = DEFAULT_ESCALATIONS,
) -> None:
    """Append an escalation entry (STALE without fix, or UNCERTAIN)."""
    entries = _load_yaml_list(escalations_path)
    entries.append({
        "coupling_id": coupling_id,
        "commit": commit,
        "verdict": verdict,
        "evidence": evidence,
        "proposed_fix": proposed_fix,
        "created_at": _now_iso(),
        "resolved_at": None,
    })
    _write_yaml_list(escalations_path, entries)


def apply_fix(
    judgment_data: dict,
    coupling_id: str,
    doc_path: Path,
    commit: str = "unknown",
    log_path: Path = DEFAULT_VERIFICATION_LOG,
    escalations_path: Path = DEFAULT_ESCALATIONS,
    agent: str = "claude-sonnet-4-6",
) -> FixResult:
    """Take action based on a VerificationJudgment dict.

    Does NOT commit any git changes — calling code is responsible for that.
    Returns a FixResult describing what happened.
    """
    verdict = judgment_data.get("verdict")
    confidence = judgment_data.get("confidence", "low")
    evidence = judgment_data.get("evidence", "")
    proposed_fix = judgment_data.get("proposed_fix")
    if verdict == "CURRENT":
        log_verification(coupling_id, commit, verdict, confidence, evidence, agent, log_path)
        return FixResult(
            applied=False,
            escalated=False,
            logged=True,
            message=f"Coupling verified CURRENT (confidence={confidence}). Logged to {log_path}.",
        )

    if verdict == "STALE" and proposed_fix:
        # Apply the proposed fix to the doc
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(proposed_fix, encoding="utf-8")
        log_verification(coupling_id, commit, verdict, confidence, evidence, agent, log_path)
        return FixResult(
            applied=True,
            escalated=False,
            logged=True,
            message=f"Applied auto-fix to {doc_path}. Commit with '[Governance] auto-fix: {coupling_id}'.",
        )

    # STALE without fix, or UNCERTAIN, or explicit escalate
    write_escalation(coupling_id, commit, verdict or "UNKNOWN", evidence, proposed_fix, escalations_path)
    return FixResult(
        applied=False,
        escalated=True,
        logged=False,
        message=f"Escalation written to {escalations_path}. Human review required.",
    )


def main() -> int:
    """Entry point for CLI usage."""
    parser = argparse.ArgumentParser(description="Apply a VerificationJudgment action")
    parser.add_argument("--judgment", type=Path, required=True, help="JSON file with VerificationJudgment")
    parser.add_argument("--coupling-id", required=True, help="Human-readable coupling ID")
    parser.add_argument("--doc-path", type=Path, required=True, help="Path to coupled doc")
    parser.add_argument("--commit", default="unknown", help="Commit hash this judgment was made for")
    parser.add_argument("--log-path", type=Path, default=DEFAULT_VERIFICATION_LOG)
    parser.add_argument("--escalations-path", type=Path, default=DEFAULT_ESCALATIONS)
    args = parser.parse_args()

    if not args.judgment.exists():
        print(f"Error: judgment file not found: {args.judgment}", file=sys.stderr)
        return 1

    judgment_data = json.loads(args.judgment.read_text())
    result = apply_fix(
        judgment_data=judgment_data,
        coupling_id=args.coupling_id,
        doc_path=args.doc_path,
        commit=args.commit,
        log_path=args.log_path,
        escalations_path=args.escalations_path,
    )

    print(result.message)
    return 1 if result.escalated else 0


if __name__ == "__main__":
    raise SystemExit(main())
