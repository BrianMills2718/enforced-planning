#!/usr/bin/env python3
"""Validate drift between tracker/docs and runtime coordination truth surfaces.

This validator intentionally separates static framework logic from repo-specific
policy by using a small YAML config file. The current slices enforce generic
checks for:

1. Consumed reservations pointing to real plan files.
2. Active work entries not referencing plans already marked complete.
3. Tracker text not advertising a next action already represented by an active
   registry claim, when configured explicitly.
4. Claimed text state matching measured audit output, when configured explicitly.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Issue:
    """A single truth-surface drift finding."""

    code: str
    severity: str
    message: str
    evidence: dict[str, Any]


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML from path, returning an empty mapping when the file is blank."""
    data = yaml.safe_load(path.read_text())
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def _load_structured(path: Path) -> Any:
    """Load YAML or JSON structured data from disk."""
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text())
    return yaml.safe_load(path.read_text())


def _extract_path(data: Any, path: str) -> Any:
    """Extract a dotted path from nested dict/list data.

    Supports keys separated by dots and numeric list indexes as path segments.
    Example: `repo_results.agentic_scaffolding.coordination_adoption_state`
    or `issues.0.code`.
    """
    current = data
    for raw_segment in path.split("."):
        segment = raw_segment.strip()
        if not segment:
            raise KeyError(f"Invalid empty path segment in '{path}'")
        if isinstance(current, list):
            if not segment.isdigit():
                raise KeyError(f"Expected numeric list index in '{path}', got '{segment}'")
            current = current[int(segment)]
            continue
        if isinstance(current, dict):
            if segment not in current:
                raise KeyError(f"Missing key '{segment}' in '{path}'")
            current = current[segment]
            continue
        raise KeyError(f"Cannot descend into '{segment}' within '{path}'")
    return current


def _parse_plan_index(path: Path) -> dict[str, str]:
    """Extract plan number -> status text from the plan index markdown table."""
    statuses: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.startswith("|"):
            continue
        parts = [part.strip() for part in line.split("|")[1:-1]]
        if len(parts) < 4:
            continue
        plan = parts[0]
        if not plan.isdigit():
            continue
        statuses[plan] = parts[3]
    return statuses


def _severity_rank(value: str) -> int:
    """Return the ordinal rank for severity sorting."""
    ranks = {"info": 0, "warn": 1, "fail": 2}
    return ranks.get(value, 2)


def _normalize_severity(value: Any, default: str = "fail") -> str:
    """Normalize a configured severity to info/warn/fail."""
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"info", "warn", "fail"}:
            return lowered
    return default


def _check_consumed_reservations_exist(
    registry: dict[str, Any], severity: str
) -> list[Issue]:
    """Validate that consumed reservations still point to a real plan file."""
    issues: list[Issue] = []
    for reservation in registry.get("plan_reservations", []):
        if not isinstance(reservation, dict):
            continue
        if reservation.get("status") != "consumed":
            continue
        plan_file = reservation.get("plan_file")
        if not isinstance(plan_file, str) or not plan_file:
            issues.append(
                Issue(
                    code="consumed_reservation_missing_plan_file_field",
                    severity=severity,
                    message="Consumed reservation is missing its plan_file field.",
                    evidence={"reservation": reservation},
                )
            )
            continue
        if not Path(plan_file).exists():
            issues.append(
                Issue(
                    code="consumed_reservation_missing_plan_file",
                    severity=severity,
                    message=f"Consumed reservation points to missing plan file: {plan_file}",
                    evidence={"reservation": reservation},
                )
            )
    return issues


def _is_complete_status(status: str) -> bool:
    """Return True when the status cell marks a plan as complete."""
    lowered = status.lower()
    return "complete" in lowered or "✅" in status


def _check_no_active_work_for_complete_plans(
    registry: dict[str, Any], plan_statuses: dict[str, str], severity: str
) -> list[Issue]:
    """Validate that active work does not still point at completed plans."""
    issues: list[Issue] = []
    for active in registry.get("active_work", []):
        if not isinstance(active, dict):
            continue
        if active.get("status") != "active":
            continue
        plan = active.get("plan")
        if plan is None:
            continue
        plan_key = str(plan)
        status = plan_statuses.get(plan_key)
        if status and _is_complete_status(status):
            issues.append(
                Issue(
                    code="active_work_references_complete_plan",
                    severity=severity,
                    message=(
                        f"Active work entry for project {active.get('project')} still references "
                        f"completed Plan #{plan_key}."
                    ),
                    evidence={"active_work": active, "plan_status": status},
                )
            )
    return issues


def _check_tracker_rules(
    tracker_text: str, registry: dict[str, Any], rules: list[dict[str, Any]]
) -> list[Issue]:
    """Validate explicit tracker-pattern rules against active registry entries."""
    issues: list[Issue] = []
    active_work = [
        item
        for item in registry.get("active_work", [])
        if isinstance(item, dict) and item.get("status") == "active"
    ]
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        pattern = rule.get("tracker_pattern")
        project = rule.get("project")
        scope = rule.get("scope")
        severity = _normalize_severity(rule.get("severity"), default="warn")
        if not isinstance(pattern, str) or not pattern:
            continue
        if not re.search(pattern, tracker_text, flags=re.MULTILINE):
            continue
        for active in active_work:
            if project and active.get("project") != project:
                continue
            if scope and active.get("scope") != scope:
                continue
            issues.append(
                Issue(
                    code="tracker_next_action_already_active",
                    severity=severity,
                    message=(
                        f"Tracker still matches pattern '{pattern}' even though active work already exists "
                        f"for project={active.get('project')} scope={active.get('scope')}."
                    ),
                    evidence={"rule": rule, "active_work": active},
                )
            )
    return issues


def _check_audit_claim_rules(
    tracker_text: str, rules: list[dict[str, Any]]
) -> list[Issue]:
    """Compare claimed text state against measured audit output via config rules."""
    issues: list[Issue] = []
    audit_cache: dict[str, Any] = {}
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        source_pattern = rule.get("source_pattern")
        audit_file = rule.get("audit_file")
        audit_json_path = rule.get("audit_json_path")
        severity = _normalize_severity(rule.get("severity"), default="fail")
        group_name = rule.get("group_name", "claim")
        if not isinstance(source_pattern, str) or not source_pattern:
            continue
        if not isinstance(audit_file, str) or not audit_file:
            continue
        if not isinstance(audit_json_path, str) or not audit_json_path:
            continue
        match = re.search(source_pattern, tracker_text, flags=re.MULTILINE)
        if not match:
            continue
        claim_value = match.groupdict().get(group_name)
        if claim_value is None:
            raise ValueError(
                f"source_pattern must define named group '{group_name}' for audit claim rules"
            )
        if audit_file not in audit_cache:
            audit_cache[audit_file] = _load_structured(Path(audit_file).expanduser())
        measured_value = _extract_path(audit_cache[audit_file], audit_json_path)
        if str(claim_value) != str(measured_value):
            issues.append(
                Issue(
                    code="audit_claim_mismatch",
                    severity=severity,
                    message=(
                        f"Claimed value '{claim_value}' from source pattern '{source_pattern}' does not match "
                        f"measured audit value '{measured_value}' at '{audit_json_path}'."
                    ),
                    evidence={
                        "rule": rule,
                        "claim_value": claim_value,
                        "measured_value": measured_value,
                    },
                )
            )
    return issues


def run_checks(config_path: Path) -> list[Issue]:
    """Run all enabled checks from a truth-surface drift config."""
    config = _load_yaml(config_path)
    surfaces = config.get("surfaces", {})
    if not isinstance(surfaces, dict):
        raise ValueError("surfaces must be a mapping")

    registry_file = Path(surfaces["registry_file"]).expanduser()
    plan_index_file = Path(surfaces["plan_index_file"]).expanduser()
    tracker_file = surfaces.get("tracker_file")

    registry = _load_yaml(registry_file)
    plan_statuses = _parse_plan_index(plan_index_file)
    tracker_text = ""
    if tracker_file:
        tracker_text = Path(str(tracker_file)).expanduser().read_text()

    checks = config.get("checks", {})
    if not isinstance(checks, dict):
        raise ValueError("checks must be a mapping")

    issues: list[Issue] = []

    consumed_cfg = checks.get("consumed_reservations_exist", {})
    if consumed_cfg is not False:
        severity = _normalize_severity(
            consumed_cfg.get("severity") if isinstance(consumed_cfg, dict) else None,
            default="fail",
        )
        issues.extend(_check_consumed_reservations_exist(registry, severity))

    active_cfg = checks.get("no_active_work_for_complete_plans", {})
    if active_cfg is not False:
        severity = _normalize_severity(
            active_cfg.get("severity") if isinstance(active_cfg, dict) else None,
            default="fail",
        )
        issues.extend(_check_no_active_work_for_complete_plans(registry, plan_statuses, severity))

    tracker_cfg = checks.get("tracker_next_action_claim_conflicts", {})
    if tracker_cfg and tracker_text:
        rules = tracker_cfg.get("rules", []) if isinstance(tracker_cfg, dict) else []
        issues.extend(_check_tracker_rules(tracker_text, registry, rules))

    audit_cfg = checks.get("audit_claim_rules", {})
    if audit_cfg and tracker_text:
        rules = audit_cfg.get("rules", []) if isinstance(audit_cfg, dict) else []
        issues.extend(_check_audit_claim_rules(tracker_text, rules))

    return sorted(issues, key=lambda issue: (_severity_rank(issue.severity), issue.code), reverse=True)


def _print_text(issues: list[Issue]) -> None:
    """Render issues as compact human-readable output."""
    if not issues:
        print("No truth-surface drift detected.")
        return
    for issue in issues:
        print(f"[{issue.severity.upper()}] {issue.code}: {issue.message}")


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to truth-surface drift YAML config")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args()

    issues = run_checks(Path(args.config).expanduser())

    if args.json:
        print(
            json.dumps(
                {
                    "issues": [
                        {
                            "code": issue.code,
                            "severity": issue.severity,
                            "message": issue.message,
                            "evidence": issue.evidence,
                        }
                        for issue in issues
                    ]
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _print_text(issues)

    if any(issue.severity == "fail" for issue in issues):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
