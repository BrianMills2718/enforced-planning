"""Validate implementation plans against the documentation relationship graph."""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import hashlib
import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from io import StringIO
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import urlparse

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from enforced_planning.file_context import collect_context, load_relationships
from enforced_planning.notebook_registry_validation import (
    load_notebook_registry,
    print_human_readable,
    validate_notebook_registry,
)
from enforced_planning.worktree_paths import detect_workspace_root


def _detect_repo_root(script_path: Path) -> Path:
    """Resolve repo root for canonical, installed, and package layouts."""
    if script_path.parent.name == "meta" and script_path.parent.parent.name == "scripts":
        return script_path.parents[2]
    if script_path.parent.name in {"scripts", "enforced_planning"}:
        return script_path.parents[1]
    return script_path.parents[1]


def detect_repository_id(repo_root: Path) -> str:
    """Prefer the stable common-checkout directory over a linked-worktree name."""

    completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        common_dir = Path(completed.stdout.strip()).resolve()
        if common_dir.name == ".git":
            return common_dir.parent.name
    return repo_root.resolve().name


ROOT = _detect_repo_root(Path(__file__).resolve())
PLANS_DIR = ROOT / "docs" / "plans"
PATH_CLEAN_RE = re.compile(r"[,;:.()]$")
REFERENCES_REVIEWED_HEADINGS = (
    "References Reviewed",
    "Research",
    "References",
    "Prior Art",
)
LEGACY_REFERENCES_REVIEWED_HEADINGS = REFERENCES_REVIEWED_HEADINGS[1:]
RESEARCH_CITATION_RE = re.compile(r"^agent_memory:[A-Za-z0-9._-]+$")
LANDSCAPE_DISPOSITIONS = frozenset({"linked", "inline", "exempt-trivial"})
CRITICAL_PATH_CLASSES = frozenset({"vertical", "direct_blocker", "enabler", "hardening"})
CAPABILITY_ADOPTION_DISPOSITIONS = frozenset(
    {"none", "reuse", "extend", "supersede", "explicit_exception", "explicit-exception"}
)
LANDSCAPE_URL_RE = re.compile(r"https?://[^\s)`>]+")
RESEARCH_PROVENANCE_HINTS = (
    re.compile(r"memory context\s*:\s*`?agent-memory recall", re.IGNORECASE),
    re.compile(r"agent-memory recall.+\bfindings\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"direct db query", re.IGNORECASE),
    re.compile(r"prior session", re.IGNORECASE),
    re.compile(r"agent_memory:", re.IGNORECASE),
)

PLANNING_INTEGRITY_CONTRACT_VERSION = "1.0.0"
PLANNING_INTEGRITY_COVERAGE_NONCLAIM = (
    "PASS proves the declared planning-integrity structure, not that every material area "
    "was named or that the plan is optimal."
)
PLANNING_FRONTIER_STATES = frozenset(
    {
        "fully_specifiable_now",
        "conditional",
        "exploration_required",
        "enabling_work_blocked",
        "human_decision_required",
        "deliberately_deferred",
    }
)
PLACEHOLDER_RE = re.compile(
    r"(?:\b(?:todo|tbd|tbc|fixme)\b|\[[^\]]+\])",
    re.IGNORECASE,
)
TEMPLATE_ACCEPTANCE_CRITERIA = frozenset(
    {
        "any declared boundary gate passed immediately before its protected action",
        "increment gate passed for the affected surface",
        "terminal gate passed before closeout or a works/done claim",
        "evidence reuse, if any, matches the declared reuse key",
        "docs updated",
    }
)
PLANNING_INTEGRITY_GOVERNED_HEADINGS = (
    "User Outcome",
    "Canonical Behavioral Example",
    "Capability Adoption",
    "Acceptance Criteria",
    "Epistemic Planning Frontier",
    "Reassessment Contract",
)


class PlanningIntegrityError(ValueError):
    """Fail-loud planning-integrity configuration or source error."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """YAML loader that rejects duplicate mapping keys instead of last-write-wins."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise PlanningIntegrityError(f"duplicate YAML key in meta-process.yaml: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class StrictIntegrityModel(BaseModel):
    """Strict base for the portable planning-integrity contract."""

    model_config = ConfigDict(extra="forbid", strict=True)


class PlanningIntegrityConfigV1(StrictIntegrityModel):
    """Repository adoption configuration for Planning Integrity 1.0.0."""

    mode: Literal["off", "observe", "enforce"] = "off"
    contract_version: str = PLANNING_INTEGRITY_CONTRACT_VERSION
    minimum_plan_number: int = Field(default=1, ge=1)


class PlanningFrontierEntryV1(StrictIntegrityModel):
    """One declared epistemic planning area and its executable resolution rule."""

    area: str = Field(min_length=2)
    state: Literal[
        "fully_specifiable_now",
        "conditional",
        "exploration_required",
        "enabling_work_blocked",
        "human_decision_required",
        "deliberately_deferred",
    ]
    current_contract: str = Field(min_length=3)
    trigger_or_stopping_rule: str = Field(min_length=3)
    downstream_update: str = Field(min_length=3)


class ReassessmentSummaryV1(StrictIntegrityModel):
    """Explicit triggers and authority boundaries for adaptive execution."""

    triggers: str = Field(min_length=3)
    autonomous_action: str = Field(min_length=3)
    plan_revision_required: str = Field(min_length=3)
    human_decision_required: str = Field(min_length=3)
    stopping_rule: str = Field(min_length=3)


class PlanIntegrityFindingV1(StrictIntegrityModel):
    """One stable structural finding from the exact plan bytes."""

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=3)


class PlanIntegrityResultV1(StrictIntegrityModel):
    """Versioned result consumed by admission and AES documentation projection."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract_version: str
    disposition: Literal["pass", "fail", "not_applicable"]
    repository_id: str = Field(min_length=1)
    plan_number: int | None
    plan_path: str | None
    plan_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    config_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_revision: str | None
    validator_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: Literal["off", "observe", "enforce"]
    minimum_plan_number: int = Field(ge=1)
    findings: list[PlanIntegrityFindingV1]
    warnings: list[PlanIntegrityFindingV1]
    frontier: list[PlanningFrontierEntryV1]
    user_outcome: str | None
    canonical_example: str | None
    critical_path_classifications: list[str]
    capability_disposition: str | None
    acceptance_criteria: list[str]
    reassessment: ReassessmentSummaryV1 | None
    coverage_nonclaim: Literal[
        "PASS proves the declared planning-integrity structure, not that every material area was named or that the plan is optimal."
    ] = PLANNING_INTEGRITY_COVERAGE_NONCLAIM


def normalize(path: str) -> str:
    """Normalize a repo-relative path for comparisons."""
    return str(path).replace("\\", "/").strip()


def get_current_plan_number(repo_root: Path = ROOT) -> int | None:
    """Infer the active plan number from the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    branch = result.stdout.strip()
    match = re.match(r".*plan-(\d+).*", branch)
    if not match:
        return None
    return int(match.group(1))


def find_plan_file(plan_number: int, plans_dir: Path) -> Path | None:
    """Find one plan file by numeric prefix inside the plans directory."""
    patterns = [
        f"{plan_number:02d}_*.md",
        f"{plan_number}_*.md",
    ]
    for pattern in patterns:
        matches = sorted(plans_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def _git_output(repo_root: Path, args: list[str], *, text: bool) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=text,
        check=False,
    )


def _git_object_bytes(repo_root: Path, revision: str, path: str) -> bytes | None:
    completed = _git_output(repo_root, ["show", f"{revision}:{path}"], text=False)
    return completed.stdout if completed.returncode == 0 else None


def _numbered_plan_paths_at_revision(
    repo_root: Path,
    *,
    revision: str,
    plans_dir: str,
    plan_number: int,
) -> list[str]:
    completed = _git_output(
        repo_root,
        ["ls-tree", "-r", "--name-only", revision, "--", plans_dir],
        text=True,
    )
    if completed.returncode != 0:
        raise PlanningIntegrityError(f"unable to inspect plans at {revision}: {completed.stderr.strip()}")
    matches: list[str] = []
    for raw_path in completed.stdout.splitlines():
        name = Path(raw_path).name
        match = re.fullmatch(r"(\d+)_.*\.md", name, re.IGNORECASE)
        if match and int(match.group(1)) == plan_number:
            matches.append(normalize(raw_path))
    return sorted(matches)


def validate_plan_integrity_at_revision(
    *,
    repo_root: Path | str,
    repository_id: str,
    plan_number: int,
    start_point: str = "HEAD",
) -> PlanIntegrityResultV1:
    """Validate plan/config bytes from the exact Git commit used to open a lane."""

    root = Path(repo_root).expanduser().resolve()
    resolved = _git_output(root, ["rev-parse", "--verify", f"{start_point}^{{commit}}"], text=True)
    if resolved.returncode != 0:
        raise PlanningIntegrityError(f"unable to resolve Git start point {start_point!r}: {resolved.stderr.strip()}")
    source_revision = resolved.stdout.strip()
    config_bytes = _git_object_bytes(root, source_revision, "meta-process.yaml")
    config, plans_dir, config_sha256 = parse_planning_integrity_config_bytes(config_bytes)
    if config.mode == "off" or plan_number < config.minimum_plan_number:
        return evaluate_plan_integrity_bytes(
            plan_bytes=None,
            plan_path=None,
            plan_number=plan_number,
            repository_id=repository_id,
            config=config,
            config_sha256=config_sha256,
            source_revision=source_revision,
        )
    matches = _numbered_plan_paths_at_revision(
        root,
        revision=source_revision,
        plans_dir=plans_dir,
        plan_number=plan_number,
    )
    if len(matches) != 1:
        result = evaluate_plan_integrity_bytes(
            plan_bytes=None,
            plan_path=None,
            plan_number=plan_number,
            repository_id=repository_id,
            config=config,
            config_sha256=config_sha256,
            source_revision=source_revision,
        )
        code = "missing_plan" if not matches else "ambiguous_plan_identity"
        message = (
            f"No plan #{plan_number} exists at {source_revision}."
            if not matches
            else f"Plan #{plan_number} is ambiguous at {source_revision}: {', '.join(matches)}."
        )
        findings = [item for item in result.findings if item.code != "missing_plan"]
        findings.insert(0, PlanIntegrityFindingV1(code=code, message=message))
        return result.model_copy(update={"findings": findings, "disposition": "fail"})
    plan_path = matches[0]
    plan_bytes = _git_object_bytes(root, source_revision, plan_path)
    return evaluate_plan_integrity_bytes(
        plan_bytes=plan_bytes,
        plan_path=plan_path,
        plan_number=plan_number,
        repository_id=repository_id,
        config=config,
        config_sha256=config_sha256,
        source_revision=source_revision,
    )


def validate_plan_integrity_from_path(
    *,
    repo_root: Path,
    repository_id: str,
    plan_path: Path,
    plan_number: int | None,
) -> PlanIntegrityResultV1:
    """Validate exact working-tree bytes for explicit inspection/CLI output."""

    config_path = repo_root / "meta-process.yaml"
    config_bytes = config_path.read_bytes() if config_path.is_file() else None
    config, _plans_dir, config_sha256 = parse_planning_integrity_config_bytes(config_bytes)
    try:
        relative_path = normalize(str(plan_path.resolve().relative_to(repo_root.resolve())))
    except ValueError as exc:
        raise PlanningIntegrityError("plan path must remain inside the repository") from exc
    plan_bytes = plan_path.read_bytes()
    return evaluate_plan_integrity_bytes(
        plan_bytes=plan_bytes,
        plan_path=relative_path,
        plan_number=plan_number,
        repository_id=repository_id,
        config=config,
        config_sha256=config_sha256,
    )


def read_text(path: Path) -> str:
    """Read one UTF-8 text file from disk."""
    return path.read_text(encoding="utf-8")


def _validator_source_sha256() -> str:
    """Bind results to the exact executing validator bytes in every layout."""

    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_unique_yaml_bytes(content: bytes, *, source: str) -> dict[str, Any]:
    """Decode one strict YAML mapping and reject duplicate keys."""

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlanningIntegrityError(f"{source} is not valid UTF-8: {exc}") from exc
    try:
        payload = yaml.load(text, Loader=_UniqueKeyLoader)
    except PlanningIntegrityError:
        raise
    except yaml.YAMLError as exc:
        raise PlanningIntegrityError(f"{source} is invalid YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise PlanningIntegrityError(f"{source} must be a YAML mapping")
    return payload


def parse_planning_integrity_config_bytes(
    content: bytes | None,
) -> tuple[PlanningIntegrityConfigV1, str, str | None]:
    """Return strict live settings, plans directory, and exact config digest."""

    if content is None:
        return PlanningIntegrityConfigV1(), "docs/plans", None
    payload = _load_unique_yaml_bytes(content, source="meta-process.yaml")
    meta_process = payload.get("meta_process", payload)
    if not isinstance(meta_process, dict):
        raise PlanningIntegrityError("meta-process.yaml meta_process must be a mapping")
    plans = meta_process.get("plans", {})
    if not isinstance(plans, dict):
        raise PlanningIntegrityError("meta-process.yaml plans must be a mapping")
    plans_dir = plans.get("plans_dir", "docs/plans")
    if not isinstance(plans_dir, str) or not plans_dir.strip():
        raise PlanningIntegrityError("meta-process.yaml plans.plans_dir must be a non-empty string")
    portable_dir = normalize(plans_dir).strip()
    drive_absolute = re.match(r"^[A-Za-z]:/", portable_dir) is not None
    parts = PurePosixPath(portable_dir).parts
    if portable_dir.startswith("/") or drive_absolute or portable_dir in {"", ".", ".."} or ".." in parts:
        raise PlanningIntegrityError("meta-process.yaml plans.plans_dir must be repository-relative")
    normalized_dir = PurePosixPath(portable_dir).as_posix().rstrip("/")
    raw_integrity = plans.get("integrity")
    if raw_integrity is None:
        config = PlanningIntegrityConfigV1()
    else:
        if not isinstance(raw_integrity, dict):
            raise PlanningIntegrityError("meta-process.yaml plans.integrity must be a mapping")
        try:
            config = PlanningIntegrityConfigV1.model_validate(raw_integrity)
        except ValidationError as exc:
            raise PlanningIntegrityError(f"invalid plans.integrity configuration: {exc}") from exc
    return config, normalized_dir, _sha256(content)


def _meaningful(value: str) -> bool:
    stripped = value.strip().strip("`*_ ")
    return len(stripped) >= 3 and not PLACEHOLDER_RE.search(stripped)


def _authored_section(section: str) -> str | None:
    """Remove instructions and accept only non-placeholder authored section bytes."""

    lines = [
        line.strip()
        for line in section.splitlines()
        if line.strip() and not line.lstrip().startswith(">") and not line.lstrip().startswith("<!--")
    ]
    value = "\n".join(lines).strip()
    return value if len(value) >= 10 and not PLACEHOLDER_RE.search(value) else None


def _bold_fields(section: str) -> dict[str, str]:
    """Parse bold Markdown field declarations with multiline values."""

    pattern = re.compile(r"^\s*(?:[-*]\s+)?\*\*([^*:\n]+):\*\*\s*(.*)$", re.MULTILINE)
    matches = list(pattern.finditer(section))
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        key = re.sub(r"[^a-z0-9]+", "_", match.group(1).strip().lower()).strip("_")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        continuation = section[match.end() : end].strip()
        value = "\n".join(part for part in (match.group(2).strip(), continuation) if part).strip()
        fields[key] = value
    return fields


def _duplicate_bold_field_keys(section: str) -> list[str]:
    """Return normalized bold-field keys declared more than once."""

    patterns = (
        re.compile(r"^\s*(?:[-*]\s+)?\*\*([^*:\n]+):\*\*", re.MULTILINE),
        re.compile(r"^\s*(?:[-*]\s+)?\*\*([^*:\n]+):\s+[^*\n]+\*\*", re.MULTILINE),
    )
    declarations: list[tuple[int, str]] = []
    for pattern in patterns:
        for match in pattern.finditer(section):
            key = re.sub(r"[^a-z0-9]+", "_", match.group(1).strip().lower()).strip("_")
            declarations.append((match.start(), key))
    seen: set[str] = set()
    duplicates: set[str] = set()
    for _position, key in sorted(declarations):
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return sorted(duplicates)


def _second_level_heading_pattern(heading: str) -> str:
    """Return one CommonMark-compatible ATX level-two heading pattern."""

    return rf"^[ \t]{{0,3}}##(?!#)[ \t]+{re.escape(heading)}(?:[ \t]+#+)?[ \t]*(?=\r?$)"


def _ambiguous_governed_structure_findings(content: str) -> list[PlanIntegrityFindingV1]:
    """Reject duplicate governed headings or field declarations."""

    findings: list[PlanIntegrityFindingV1] = []
    for heading in PLANNING_INTEGRITY_GOVERNED_HEADINGS:
        matches = re.findall(
            _second_level_heading_pattern(heading),
            content,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if len(matches) > 1:
            findings.append(
                PlanIntegrityFindingV1(
                    code="duplicate_governed_heading",
                    message=f"Governed heading {heading!r} is declared {len(matches)} times.",
                )
            )
            continue
        section = extract_section(content, heading)
        duplicate_fields = _duplicate_bold_field_keys(section)
        if duplicate_fields:
            findings.append(
                PlanIntegrityFindingV1(
                    code="duplicate_governed_field",
                    message=(f"Governed section {heading!r} repeats field(s): " + ", ".join(duplicate_fields) + "."),
                )
            )
    return findings


def _canonical_example(section: str) -> str | None:
    fields = _bold_fields(section)
    aliases = {
        "starting": ("starting_state", "starting_input_state", "starting_input"),
        "action": ("action",),
        "expected": ("expected_result", "expected_observable_result"),
        "failure": ("failure_signal",),
    }
    selected: dict[str, str] = {}
    for name, candidates in aliases.items():
        value = next((fields[key] for key in candidates if key in fields), "")
        if not _meaningful(value):
            return None
        selected[name] = value
    return "\n".join(f"{name}: {value}" for name, value in selected.items())


def _explicit_critical_path_classes(content: str) -> list[str]:
    match = re.search(
        r"^\*\*Critical[- ]path classification:(?:\*\*\s*)?\s*`?([a-z_]+)`?",
        content,
        re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        return []
    value = match.group(1).lower()
    return [value] if value in CRITICAL_PATH_CLASSES else []


def _explicit_capability_disposition(content: str) -> str | None:
    section = extract_section(content, "Capability Adoption")
    canonical_value = _bold_fields(section).get("disposition", "")
    match = re.match(r"`?([a-z_-]+)", canonical_value, re.IGNORECASE)
    if not match:
        match = re.search(
            r"^\s*(?:[-*]\s+)?\*\*Disposition:\s*`?([a-z_-]+)",
            section,
            re.IGNORECASE | re.MULTILINE,
        )
    if not match:
        return None
    value = match.group(1).lower().replace("-", "_")
    return value if value in {item.replace("-", "_") for item in CAPABILITY_ADOPTION_DISPOSITIONS} else None


def _parse_acceptance_criteria(content: str) -> list[str]:
    """Return authored observable criteria from the canonical plan section."""

    section = extract_section(content, "Acceptance Criteria")
    criteria: list[str] = []
    current: list[str] = []

    def retain_current() -> None:
        value = " ".join(current).strip()
        if _meaningful(value) and value.casefold() not in TEMPLATE_ACCEPTANCE_CRITERIA:
            criteria.append(value)

    for raw_line in section.splitlines():
        line = raw_line.strip()
        marker = re.match(r"^(?:\d+[.)]|[-*](?:\s+\[[ xX]\])?)\s+(.+)$", line)
        if marker:
            retain_current()
            current = [marker.group(1).strip()]
        elif line.startswith(">") or line == "---" or line.startswith("#"):
            retain_current()
            current = []
        elif current and line:
            current.append(line)
    retain_current()
    return criteria


def _markdown_table(section: str) -> tuple[list[str], list[list[str]]]:
    lines = [line.strip() for line in section.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return [], []
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    if not all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in rows[1]):
        return [], []
    return rows[0], rows[2:]


def _parse_frontier(content: str) -> tuple[list[PlanningFrontierEntryV1], list[PlanIntegrityFindingV1]]:
    section = extract_section(content, "Epistemic Planning Frontier")
    findings: list[PlanIntegrityFindingV1] = []
    if not section:
        return [], [
            PlanIntegrityFindingV1(
                code="missing_epistemic_frontier", message="Epistemic Planning Frontier is required."
            )
        ]
    headers, rows = _markdown_table(section)
    normalized = [re.sub(r"[^a-z0-9]+", "_", item.lower()).strip("_") for item in headers]
    expected = ["area", "state", "current_contract", "trigger_or_stopping_rule", "downstream_update"]
    if normalized != expected:
        return [], [
            PlanIntegrityFindingV1(
                code="invalid_frontier_headers",
                message="Frontier headers must be Area, State, Current contract, Trigger or stopping rule, Downstream update.",
            )
        ]
    if not rows:
        return [], [
            PlanIntegrityFindingV1(code="missing_frontier_rows", message="Frontier requires at least one authored row.")
        ]
    entries: list[PlanningFrontierEntryV1] = []
    seen: set[str] = set()
    for index, cells in enumerate(rows, start=1):
        if len(cells) != 5 or any(not _meaningful(cell) for cell in cells):
            findings.append(
                PlanIntegrityFindingV1(
                    code="invalid_frontier_row",
                    message=f"Frontier row {index} is incomplete or contains a placeholder.",
                )
            )
            continue
        area, state, current_contract, trigger, downstream = cells
        normalized_state = state.strip("` ")
        area_key = area.strip().casefold()
        if area_key in seen:
            findings.append(
                PlanIntegrityFindingV1(code="duplicate_frontier_area", message=f"Frontier area {area!r} is duplicated.")
            )
            continue
        seen.add(area_key)
        if normalized_state not in PLANNING_FRONTIER_STATES:
            findings.append(
                PlanIntegrityFindingV1(
                    code="invalid_frontier_state",
                    message=f"Frontier row {index} has unsupported state {normalized_state!r}.",
                )
            )
            continue
        entries.append(
            PlanningFrontierEntryV1(
                area=area,
                state=normalized_state,
                current_contract=current_contract,
                trigger_or_stopping_rule=trigger,
                downstream_update=downstream,
            )
        )
    return entries, findings


def _parse_reassessment(content: str) -> tuple[ReassessmentSummaryV1 | None, list[PlanIntegrityFindingV1]]:
    section = extract_section(content, "Reassessment Contract")
    if not section:
        return None, [
            PlanIntegrityFindingV1(code="missing_reassessment_contract", message="Reassessment Contract is required.")
        ]
    fields = _bold_fields(section)
    required = {
        "triggers": "triggers",
        "autonomous_action": "autonomous_action",
        "plan_revision_required": "plan_revision_required",
        "human_decision_required": "human_decision_required",
        "stopping_rule": "stopping_rule",
    }
    missing = [label for label, key in required.items() if not _meaningful(fields.get(key, ""))]
    if missing:
        return None, [
            PlanIntegrityFindingV1(
                code="invalid_reassessment_contract",
                message="Reassessment Contract is missing authored fields: " + ", ".join(missing),
            )
        ]
    return ReassessmentSummaryV1(**{label: fields[key] for label, key in required.items()}), []


def evaluate_plan_integrity_bytes(
    *,
    plan_bytes: bytes | None,
    plan_path: str | None,
    plan_number: int | None,
    repository_id: str,
    config: PlanningIntegrityConfigV1,
    config_sha256: str | None,
    source_revision: str | None = None,
) -> PlanIntegrityResultV1:
    """Evaluate exact plan bytes without trusting a caller-supplied verdict."""

    base = {
        "contract_version": config.contract_version,
        "repository_id": repository_id,
        "plan_number": plan_number,
        "plan_path": plan_path,
        "plan_sha256": _sha256(plan_bytes) if plan_bytes is not None else None,
        "config_sha256": config_sha256,
        "source_revision": source_revision,
        "validator_source_sha256": _validator_source_sha256(),
        "mode": config.mode,
        "minimum_plan_number": config.minimum_plan_number,
        "warnings": [],
        "coverage_nonclaim": PLANNING_INTEGRITY_COVERAGE_NONCLAIM,
    }
    if config.mode == "off" or (plan_number is not None and plan_number < config.minimum_plan_number):
        return PlanIntegrityResultV1(
            **base,
            disposition="not_applicable",
            findings=[],
            frontier=[],
            user_outcome=None,
            canonical_example=None,
            critical_path_classifications=[],
            capability_disposition=None,
            acceptance_criteria=[],
            reassessment=None,
        )
    findings: list[PlanIntegrityFindingV1] = []
    if config.contract_version != PLANNING_INTEGRITY_CONTRACT_VERSION:
        findings.append(
            PlanIntegrityFindingV1(
                code="unsupported_contract_version",
                message=f"Unsupported Planning Integrity contract {config.contract_version!r}.",
            )
        )
    if plan_number is None:
        findings.append(
            PlanIntegrityFindingV1(
                code="missing_plan_number", message="Planning Integrity requires a numbered plan identity."
            )
        )
    if plan_bytes is None or plan_path is None:
        findings.append(
            PlanIntegrityFindingV1(
                code="missing_plan", message="The exact numbered plan is unavailable at the selected revision."
            )
        )
        content = ""
    else:
        try:
            content = plan_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            findings.append(
                PlanIntegrityFindingV1(code="invalid_plan_encoding", message=f"Plan is not valid UTF-8: {exc}.")
            )
            content = ""

    findings.extend(_ambiguous_governed_structure_findings(content))
    user_outcome = _authored_section(extract_section(content, "User Outcome"))
    if user_outcome is None:
        findings.append(
            PlanIntegrityFindingV1(code="missing_user_outcome", message="An authored User Outcome is required.")
        )
    canonical_example = _canonical_example(extract_section(content, "Canonical Behavioral Example"))
    if canonical_example is None:
        findings.append(
            PlanIntegrityFindingV1(
                code="invalid_canonical_behavioral_example",
                message="Canonical Behavioral Example requires authored starting state, action, expected result, and failure signal.",
            )
        )
    critical_classes = _explicit_critical_path_classes(content)
    if not critical_classes:
        findings.append(
            PlanIntegrityFindingV1(
                code="missing_critical_path_classification",
                message="Declare one explicit Critical-path classification.",
            )
        )
    capability_disposition = _explicit_capability_disposition(content)
    if capability_disposition is None:
        findings.append(
            PlanIntegrityFindingV1(
                code="missing_capability_adoption_disposition",
                message="Capability Adoption requires an explicit supported Disposition.",
            )
        )
    acceptance_criteria = _parse_acceptance_criteria(content)
    if not acceptance_criteria:
        findings.append(
            PlanIntegrityFindingV1(
                code="missing_acceptance_criteria",
                message="At least one authored Acceptance Criteria item is required.",
            )
        )
    frontier, frontier_findings = _parse_frontier(content)
    findings.extend(frontier_findings)
    reassessment, reassessment_findings = _parse_reassessment(content)
    findings.extend(reassessment_findings)
    disposition: Literal["pass", "fail"] = "fail" if findings else "pass"
    return PlanIntegrityResultV1(
        **base,
        disposition=disposition,
        findings=findings,
        frontier=frontier,
        user_outcome=user_outcome,
        canonical_example=canonical_example,
        critical_path_classifications=critical_classes,
        capability_disposition=capability_disposition,
        acceptance_criteria=acceptance_criteria,
        reassessment=reassessment,
    )


def extract_section(content: str, heading: str) -> str:
    """Extract one second-level markdown section body by heading name."""
    pattern = re.compile(
        rf"{_second_level_heading_pattern(heading)}\r?\n"
        rf"(.*?)(?=^[ \t]{{0,3}}##(?!#)[ \t]+|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        return ""
    return match.group(1).strip()


def split_lines(section: str) -> list[str]:
    """Return non-empty stripped lines from one markdown section body."""
    lines: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lines.append(stripped)
    return lines


def looks_like_file_path(value: str) -> bool:
    """Heuristic filter for inline repo-relative file path references."""
    if not value:
        return False
    value = value.strip().strip("`\"'()[],")
    if value in {"None", "none", "N/A", "n/a", "-"}:
        return False
    if value.startswith("#") or value.startswith("http://") or value.startswith("https://"):
        return False
    return bool("/" in value or "\\" in value or re.search(r"\.[A-Za-z0-9]{1,8}$", value))


def extract_inline_paths(line: str) -> list[str]:
    """Extract path-like tokens from one line of markdown text."""
    paths: list[str] = []
    for match in re.finditer(r"\b([A-Za-z0-9_./-]+\.[A-Za-z0-9][A-Za-z0-9._-]*)\b", line):
        value = match.group(1)
        if looks_like_file_path(value):
            paths.append(normalize(value))

    for match in re.finditer(r"`([^`]+)`", line):
        value = match.group(1).strip()
        candidate = value.split(":", 1)[0] if ":" in value else value
        candidate = PATH_CLEAN_RE.sub("", candidate).strip()
        if looks_like_file_path(candidate):
            paths.append(normalize(candidate))

    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", line):
        value = match.group(1).strip()
        if looks_like_file_path(value):
            paths.append(normalize(value))

    return paths


def extract_paths(section: str) -> list[str]:
    """Extract and de-duplicate path references from one markdown section."""
    result: list[str] = []
    for line in split_lines(section):
        if line.startswith("|") and line.endswith("|") and re.match(r"^\|[-\s|:]+\|$", line):
            continue
        result.extend(extract_inline_paths(line))
    dedupe: list[str] = []
    seen: set[str] = set()
    for path in result:
        if path and path not in seen:
            seen.add(path)
            dedupe.append(path)
    return dedupe


def parse_files_affected(content: str) -> list[str]:
    """Parse the Files Affected section of a plan."""
    return extract_paths(extract_section(content, "Files Affected"))


def parse_references_reviewed(content: str) -> list[str]:
    """Parse the canonical reviewed-reference section or a legacy alias."""
    for heading in REFERENCES_REVIEWED_HEADINGS:
        section = extract_section(content, heading)
        if section.strip():
            return extract_paths(section)
    return []


def parse_uncertainty_register(content: str) -> list[str]:
    """Parse bullet items under the Uncertainty Register section."""
    section = extract_section(content, "Uncertainty Register")
    if not section:
        return []
    items: list[str] = []
    for line in split_lines(section):
        if line.startswith("- ") or line.startswith("* "):
            value = line[2:].strip()
            if value and value != "-":
                items.append(value)
    return items


def parse_contracts_used(content: str) -> list[str]:
    """Parse the Contracts Used section from a plan."""
    section = extract_section(content, "Contracts Used")
    if not section:
        return []
    contracts = []
    for line in section.split("\n"):
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            name = line[2:].split("—")[0].split("-")[0].strip().strip("`")
            if name and name != "-":
                contracts.append(name)
    return contracts


def parse_tools_used(content: str) -> list[str]:
    """Parse the Tools Used section from a plan."""
    section = extract_section(content, "Tools Used")
    if not section:
        return []
    tools = []
    for line in section.split("\n"):
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            name = line[2:].split("—")[0].split("-")[0].strip().strip("`")
            if name and name != "-":
                tools.append(name)
    return tools


def parse_data_flow(content: str) -> list[dict[str, str]]:
    """Parse the Data Flow section from a plan."""
    section = extract_section(content, "Data Flow")
    if not section:
        return []

    flows: list[dict[str, str]] = []
    for line in section.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if re.match(r"^\|[-\s|:]+\|$", line):
            continue
        if re.match(r"^\|\s*(Step|#)", line, re.IGNORECASE):
            continue

        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 6:
            flows.append(
                {
                    "producer": parts[2].strip("`"),
                    "producer_schema": parts[3].strip("`"),
                    "consumer": parts[4].strip("`"),
                    "consumer_schema": parts[5].strip("`"),
                }
            )
    return flows


def parse_plan_status(content: str) -> tuple[str, str]:
    """Extract the markdown title and bolded Status line."""
    status = "Unknown"
    status_patterns = (
        r"^\*\*Status:\*\*[ \t]*(.+?)[ \t]*$",
        r"^\*\*Status\*\*:[ \t]*(.+?)[ \t]*$",
        r"^\*Status:\*[ \t]*(.+?)[ \t]*$",
        r"^Status:[ \t]*(.+?)[ \t]*$",
    )
    for pattern in status_patterns:
        if match := re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
            status = match.group(1)
            break
    title = "Plan"
    if first := re.search(r"^#\s*([^\n]+)", content, re.MULTILINE):
        title = first.group(1).strip()
    return title, status


def parse_mentioned_adrs(content: str) -> set[int]:
    """Return ADR numbers mentioned anywhere in the plan text."""
    result: set[int] = set()
    for match in re.finditer(r"\bADR[-_](\d{1,4})\b", content, re.IGNORECASE):
        try:
            result.add(int(match.group(1)))
        except ValueError:
            continue
    return result


def _extract_metadata_value(content: str, field_name: str) -> str | None:
    """Extract one bolded metadata field value from the plan header."""
    match = re.search(
        rf"^\*\*{re.escape(field_name)}:\*\*[ \t]*(.*?)[ \t]*$",
        content,
        re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        return None
    value = re.sub(r"<!--.*?-->", "", match.group(1)).strip()
    return value or None


def _parse_research_citations(content: str) -> tuple[list[str], list[dict[str, str]]]:
    """Parse and validate the optional research_citations metadata field."""
    raw_value = _extract_metadata_value(content, "research_citations")
    if raw_value is None:
        return [], []

    try:
        loaded = yaml.safe_load(raw_value)
    except yaml.YAMLError:
        return [], [
            {
                "code": "invalid_research_citations",
                "message": "`research_citations` must parse as a YAML/JSON list of strings.",
            }
        ]

    if loaded in (None, ""):
        return [], []
    if not isinstance(loaded, list):
        return [], [
            {
                "code": "invalid_research_citations",
                "message": "`research_citations` must be a list of `agent_memory:<entry_id>` strings.",
            }
        ]

    warnings: list[dict[str, str]] = []
    citations: list[str] = []
    seen: set[str] = set()
    duplicates: set[str] = set()

    for item in loaded:
        value = str(item).strip()
        if not value:
            warnings.append(
                {
                    "code": "invalid_research_citations",
                    "message": "`research_citations` contains an empty value.",
                }
            )
            continue
        citations.append(value)
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)
        if not RESEARCH_CITATION_RE.match(value):
            warnings.append(
                {
                    "code": "invalid_research_citation_entry",
                    "message": (f"`research_citations` entry `{value}` must match `agent_memory:<entry_id>`."),
                }
            )

    for duplicate in sorted(duplicates):
        warnings.append(
            {
                "code": "duplicate_research_citation",
                "message": f"`research_citations` contains duplicate entry `{duplicate}`.",
            }
        )

    return citations, warnings


def _parse_landscape_contract(
    content: str,
) -> tuple[str | None, list[str], list[dict[str, str]]]:
    """Parse the report-only landscape disposition and its structural evidence."""
    raw_disposition = _extract_metadata_value(content, "Landscape disposition")
    disposition = raw_disposition.lower() if raw_disposition else None
    section = extract_section(content, "Landscape And Prior Art")
    references = extract_paths(section)
    urls = [url.rstrip(".,;:") for url in LANDSCAPE_URL_RE.findall(section)]
    url_hosts = {urlparse(url).netloc for url in urls}
    references = [reference for reference in references if reference not in url_hosts]
    for clean_url in urls:
        if clean_url not in references:
            references.append(clean_url)

    warnings: list[dict[str, str]] = []
    if disposition is None:
        warnings.append(
            {
                "code": "missing_landscape_disposition",
                "message": (
                    "Declare `Landscape disposition` as `linked`, `inline`, or "
                    "`exempt-trivial`; this is report-only during rollout."
                ),
            }
        )
        return None, references, warnings

    if disposition not in LANDSCAPE_DISPOSITIONS:
        warnings.append(
            {
                "code": "invalid_landscape_disposition",
                "message": (
                    f"Unknown landscape disposition `{raw_disposition}`; expected "
                    "`linked`, `inline`, or `exempt-trivial`."
                ),
            }
        )
        return disposition, references, warnings

    if not section:
        warnings.append(
            {
                "code": "missing_landscape_section",
                "message": "The declared landscape disposition requires a `Landscape And Prior Art` section.",
            }
        )
        return disposition, references, warnings

    lowered_section = section.lower()
    if disposition == "linked" and not references:
        warnings.append(
            {
                "code": "missing_landscape_reference",
                "message": "A `linked` landscape must retain at least one repo-relative path or HTTP(S) source.",
            }
        )
    elif disposition == "inline":
        missing_labels = [label for label in ("alternatives", "project implications") if label not in lowered_section]
        if missing_labels:
            warnings.append(
                {
                    "code": "incomplete_inline_landscape",
                    "message": (
                        "An `inline` landscape must include explicit `Alternatives` and "
                        f"`Project implications`; missing: {', '.join(missing_labels)}."
                    ),
                }
            )
    elif disposition == "exempt-trivial" and "reason" not in lowered_section:
        warnings.append(
            {
                "code": "weak_landscape_exemption",
                "message": "An `exempt-trivial` landscape must include an explicit `Reason`.",
            }
        )

    return disposition, references, warnings


def _research_provenance_hint_present(content: str) -> bool:
    """Heuristically detect plan text that cites prior-session provenance."""
    sections = [
        *(extract_section(content, heading) for heading in REFERENCES_REVIEWED_HEADINGS),
        extract_section(content, "Research Basis For This Slice"),
    ]
    searchable = "\n".join(section for section in sections if section)
    if not searchable:
        return False
    return any(pattern.search(searchable) for pattern in RESEARCH_PROVENANCE_HINTS)


def get_plan_file(
    plan_number: int | None,
    plans_dir: Path,
    plan_file: str | None,
    *,
    repo_root: Path = ROOT,
) -> Path:
    """Resolve the effective plan file from CLI inputs."""
    if plan_file:
        candidate = Path(plan_file)
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        if not candidate.exists():
            print(f"Plan file not found: {candidate}")
            raise SystemExit(1)
        return candidate

    if plan_number is None:
        print("No plan specified and branch name does not contain plan-<N>.")
        print("Use --plan <N> or --plan-file <path>.")
        raise SystemExit(1)

    plan_path = find_plan_file(plan_number, plans_dir)
    if not plan_path:
        print(f"Plan file not found for plan #{plan_number}")
        raise SystemExit(1)
    return plan_path


def collect_plan_requirements(
    file_paths: list[str],
    relationships: dict[str, Any],
    *,
    repo_root: Path = ROOT,
    authority_config_path: Path | None = None,
) -> tuple[set[str], set[str], set[int], list[tuple[str, int, str]]]:
    """Collect required docs and ADRs implied by affected files."""
    required_docs_strict: set[str] = set()
    required_docs_soft: set[str] = set()
    required_adrs: dict[int, str] = {}
    governance: list[tuple[str, int, str]] = []

    for file_path in file_paths:
        ctx = collect_context(
            file_path,
            relationships,
            repo_root=repo_root,
            authority_config_path=authority_config_path,
        )
        if not ctx.governance and not ctx.current_arch_docs and not ctx.coupled_docs and not ctx.doc_spine_reads:
            continue

        for adr in ctx.governance:
            required_adrs[adr["adr"]] = adr.get("title", f"ADR-{adr['adr']:04d}")
            governance.append((adr["path"], adr["adr"], adr["title"]))

        required_docs_strict.update(ctx.current_arch_docs)
        required_docs_strict.update(ctx.target_arch_docs)
        required_docs_strict.update(ctx.gap_docs)
        required_docs_strict.update(ctx.plan_refs)
        required_docs_strict.update(ctx.doc_spine_reads)

        for coupling in ctx.coupled_docs:
            target = normalize(coupling["path"])
            if coupling.get("soft"):
                required_docs_soft.add(target)
            else:
                required_docs_strict.add(target)

    return required_docs_strict, required_docs_soft, set(required_adrs), governance


REQUIRED_PLAN_SECTIONS: dict[str, tuple[list[str], str]] = {
    "Gap": (
        ["Gap", "Goal", "Problem"],
        "Must describe what exists now and what we want (requirements).",
    ),
    "References Reviewed": (
        list(REFERENCES_REVIEWED_HEADINGS),
        "Must cite code/docs/prior art reviewed before planning (no guessing).",
    ),
    "Acceptance Criteria": (
        ["Acceptance Criteria", "Verification", "Success Criteria"],
        "Must define verifiable criteria for completion.",
    ),
}


@dataclass
class ValidationResult:
    """Structured output for one plan validation run."""

    plan_number: int | None
    plan_file: Path
    title: str
    status: str
    affected_files: list[str]
    references_reviewed: list[str]
    research_citations: list[str]
    landscape_disposition: str | None
    landscape_references: list[str]
    uncertainties: list[str]
    required_docs_strict: set[str]
    required_docs_soft: set[str]
    missing_strict: set[str]
    missing_soft: set[str]
    missing_adrs: list[tuple[int, str]]
    governance: list[tuple[str, int, str]]
    missing_sections: list[tuple[str, str]]
    data_flow: list[dict[str, str]]
    contracts_used: list[str]
    tools_used: list[str]
    warnings: list[dict[str, str]]
    plan_integrity: PlanIntegrityResultV1 | None = None

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serializable summary payload."""
        return {
            "plan_number": self.plan_number,
            "plan_file": str(self.plan_file),
            "title": self.title,
            "status": self.status,
            "affected_files": self.affected_files,
            "references_reviewed": self.references_reviewed,
            "research_citations": self.research_citations,
            "landscape": {
                "disposition": self.landscape_disposition,
                "references": self.landscape_references,
            },
            "uncertainties_count": len(self.uncertainties),
            "required_docs": {
                "strict": sorted(self.required_docs_strict),
                "soft": sorted(self.required_docs_soft),
                "missing_strict": sorted(self.missing_strict),
                "missing_soft": sorted(self.missing_soft),
            },
            "governance": [{"source": source, "adr": adr, "title": title} for source, adr, title in self.governance],
            "missing_adrs": [{"adr": adr, "title": title} for adr, title in self.missing_adrs],
            "data_flow": self.data_flow,
            "contracts_used": self.contracts_used,
            "tools_used": self.tools_used,
            "missing_sections": [{"section": name, "reason": reason} for name, reason in self.missing_sections],
            "warnings": self.warnings,
            "plan_integrity": (
                self.plan_integrity.model_dump(mode="json") if self.plan_integrity is not None else None
            ),
        }


def validate_plan(
    plan_file: Path,
    plan_number: int | None,
    relationships: dict[str, Any],
    *,
    repo_root: Path = ROOT,
    authority_config_path: Path | None = None,
    plan_integrity: PlanIntegrityResultV1 | None = None,
) -> ValidationResult:
    """Validate one plan file against required docs, ADRs, and section rules."""
    content = read_text(plan_file)
    title, status = parse_plan_status(content)
    affected = parse_files_affected(content)
    if not affected:
        affected = extract_paths(extract_section(content, "Task Pack"))

    references = parse_references_reviewed(content)
    research_citations, warnings = _parse_research_citations(content)
    canonical_references_section = extract_section(content, "References Reviewed")
    legacy_references_heading = next(
        (
            heading
            for heading in LEGACY_REFERENCES_REVIEWED_HEADINGS
            if extract_section(content, heading).strip()
        ),
        None,
    )
    if not canonical_references_section.strip() and legacy_references_heading:
        warnings.append(
            {
                "code": "deprecated_references_heading",
                "message": (
                    f"`## {legacy_references_heading}` is a deprecated alias for "
                    "`## References Reviewed`. It remains readable during the documented "
                    "compatibility window, but new plans must use the canonical heading."
                ),
            }
        )
    landscape_disposition, landscape_references, landscape_warnings = _parse_landscape_contract(content)
    warnings.extend(landscape_warnings)
    plan_type = (_extract_metadata_value(content, "Type") or "implementation").lower()
    if plan_type.startswith("implementation") and landscape_disposition != "exempt-trivial":
        user_outcome = extract_section(content, "User Outcome")
        if len(user_outcome.strip()) < 10:
            warnings.append(
                {
                    "code": "missing_user_outcome",
                    "message": (
                        "Non-trivial implementation plans should preserve a plain-language "
                        "`User Outcome`; supporting infrastructure is not the outcome."
                    ),
                }
            )

        canonical_example = extract_section(content, "Canonical Behavioral Example")
        if len(canonical_example.strip()) < 10:
            warnings.append(
                {
                    "code": "missing_canonical_behavioral_example",
                    "message": (
                        "Non-trivial implementation plans should preserve the smallest "
                        "representative input, action, and observable result."
                    ),
                }
            )

        plan_section = extract_section(content, "Plan").lower()
        if not any(re.search(rf"\b{re.escape(name)}\b", plan_section) for name in CRITICAL_PATH_CLASSES):
            warnings.append(
                {
                    "code": "missing_critical_path_classification",
                    "message": (
                        "Classify planned increments as `vertical`, `direct_blocker`, "
                        "`enabler`, or `hardening` so substrate work cannot silently "
                        "advance product status."
                    ),
                }
            )

        capability_adoption = extract_section(content, "Capability Adoption")
        if len(capability_adoption.strip()) < 10:
            warnings.append(
                {
                    "code": "missing_capability_adoption",
                    "message": (
                        "Declare whether the change reuses, extends, supersedes, or explicitly "
                        "excepts an existing capability, or state that no existing capability "
                        "owns the concern. Implemented substrate is not proof of consumer adoption."
                    ),
                }
            )
        else:
            normalized_adoption = capability_adoption.lower().replace("`", "")
            if not any(
                re.search(rf"\b{re.escape(disposition)}\b", normalized_adoption)
                for disposition in CAPABILITY_ADOPTION_DISPOSITIONS
            ):
                warnings.append(
                    {
                        "code": "missing_capability_adoption_disposition",
                        "message": (
                            "Capability Adoption must declare one disposition: none, reuse, "
                            "extend, supersede, or explicit_exception."
                        ),
                    }
                )
    uncertainties = parse_uncertainty_register(content)
    covered = {normalize(p) for p in set(affected) | set(references)}
    try:
        covered.add(normalize(str(plan_file.relative_to(repo_root))))
    except ValueError:
        pass

    required_strict, required_soft, adr_nums, governance = collect_plan_requirements(
        affected,
        relationships,
        repo_root=repo_root,
        authority_config_path=authority_config_path,
    )
    required_strict_norm = {normalize(p) for p in required_strict}
    required_soft_norm = {normalize(p) for p in required_soft}

    mentioned_adrs = parse_mentioned_adrs(content)
    adrs_meta: dict[int, dict[str, Any]] = {int(k): v for k, v in relationships.get("adrs", {}).items()}

    missing_adrs: list[tuple[int, str]] = []
    for adr_num in sorted(adr_nums):
        adr_ref = f"ADR-{adr_num:04d}"
        if adr_num in mentioned_adrs:
            continue
        adr_meta = adrs_meta.get(adr_num)
        adr_file = normalize(adr_meta.get("file", "")) if adr_meta else ""
        if adr_file and adr_file not in covered:
            adr_title = str(adr_meta.get("title", adr_ref)) if adr_meta else adr_ref
            missing_adrs.append((adr_num, adr_title))

    missing_strict = {path for path in required_strict_norm if path not in covered}
    missing_soft = {path for path in required_soft_norm if path not in covered}

    data_flow = parse_data_flow(content)
    contracts_used = parse_contracts_used(content)
    tools_used = parse_tools_used(content)

    missing_sections: list[tuple[str, str]] = []
    for section_name, (aliases, reason) in REQUIRED_PLAN_SECTIONS.items():
        found = False
        for alias in aliases:
            section_content = extract_section(content, alias)
            if section_content and len(section_content.strip()) >= 10:
                found = True
                break
        if not found:
            missing_sections.append((section_name, reason))

    if not research_citations and _research_provenance_hint_present(content):
        warnings.append(
            {
                "code": "missing_research_citations",
                "message": (
                    "Plan text suggests prior agent-session findings informed this slice, "
                    "but `research_citations` is empty."
                ),
            }
        )

    return ValidationResult(
        plan_number=plan_number,
        plan_file=plan_file,
        title=title,
        status=status,
        affected_files=sorted(affected),
        references_reviewed=sorted(references),
        research_citations=research_citations,
        landscape_disposition=landscape_disposition,
        landscape_references=landscape_references,
        uncertainties=uncertainties,
        required_docs_strict=required_strict_norm,
        required_docs_soft=required_soft_norm,
        missing_strict=missing_strict,
        missing_soft=missing_soft,
        missing_adrs=missing_adrs,
        governance=governance,
        missing_sections=missing_sections,
        data_flow=data_flow,
        contracts_used=contracts_used,
        tools_used=tools_used,
        warnings=warnings,
        plan_integrity=plan_integrity,
    )


def print_summary(result: ValidationResult) -> None:
    """Print a concise human-readable validation summary."""
    print(f"Plan validation: {result.title}")
    if result.plan_number is not None:
        print(f"  Number: #{result.plan_number}")
    print(f"  File: {result.plan_file}")
    print(f"  Status: {result.status}")
    print(f"  Affected files: {len(result.affected_files)}")
    if not result.affected_files:
        print("  (no affected files discovered)")
    for path in result.affected_files:
        print(f"    - {path}")

    print(f"\nResearch citations: {len(result.research_citations)}")
    for citation in result.research_citations:
        print(f"  - {citation}")

    print(f"\nLandscape disposition: {result.landscape_disposition or '(missing)'}")
    for reference in result.landscape_references:
        print(f"  - {reference}")

    print("\nGOVERNANCE:")
    if result.governance:
        seen = set()
        for source, adr, title in result.governance:
            key = (source, adr, title)
            if key in seen:
                continue
            seen.add(key)
            print(f"  - ADR-{adr:04d}: {title} ({source})")
    else:
        print("  (none)")

    print("\nREQUIRED DOCUMENTATION (strict):")
    if result.required_docs_strict:
        for path in sorted(result.required_docs_strict):
            print(f"  - {path}")
    else:
        print("  (none)")

    if result.required_docs_soft:
        print("\nREQUIRED DOCUMENTATION (soft):")
        for path in sorted(result.required_docs_soft):
            print(f"  - {path}")

    if result.missing_strict or result.missing_adrs or result.missing_soft:
        print("\nGAPS FOUND:")
        if result.missing_strict:
            print("  Strict documentation gaps:")
            for path in sorted(result.missing_strict):
                print(f"    - {path}")
        if result.missing_adrs:
            print("  Missing governance ADR coverage in plan text:")
            for adr_num, title in result.missing_adrs:
                print(f"    - ADR-{adr_num:04d}: {title}")
        if result.missing_soft:
            print("  Soft documentation gaps:")
            for path in sorted(result.missing_soft):
                print(f"    - {path}")
    else:
        print("\nNo documentation gaps found.")

    if result.contracts_used:
        print(f"\nCONTRACTS USED ({len(result.contracts_used)}):")
        for contract in result.contracts_used:
            print(f"  - {contract}")

    if result.tools_used:
        print(f"\nTOOLS USED ({len(result.tools_used)}):")
        for tool in result.tools_used:
            print(f"  - {tool}")

    if result.data_flow:
        print(f"\nDATA FLOW DECLARATIONS ({len(result.data_flow)} boundary crossings):")
        for flow in result.data_flow:
            print(f"  {flow['producer']} ({flow['producer_schema']}) → {flow['consumer']} ({flow['consumer_schema']})")

    if result.missing_sections:
        print("\nMISSING PLAN SECTIONS (design sequence enforcement):")
        for section_name, reason in result.missing_sections:
            print(f"  - {section_name}: {reason}")

    if result.warnings:
        print("\nWARNINGS (non-blocking):")
        for warning in result.warnings:
            print(f"  - {warning['code']}: {warning['message']}")

    if result.plan_integrity is not None:
        integrity = result.plan_integrity
        print("\nPLANNING INTEGRITY:")
        print(f"  disposition: {integrity.disposition}")
        print(f"  mode: {integrity.mode}")
        print(f"  plan_sha256: {integrity.plan_sha256 or '(not applicable)'}")
        print(f"  validator_source_sha256: {integrity.validator_source_sha256}")
        print(f"  coverage non-claim: {integrity.coverage_nonclaim}")
        for finding in integrity.findings:
            print(f"  - {finding.code}: {finding.message}")

    if result.uncertainties:
        print(f"\nUncertainty register entries: {len(result.uncertainties)} (not a blocker)")


def load_ack_file(ack_path: Path) -> dict[str, str]:
    """Load acknowledged plan-validation gaps from a YAML file."""
    if not ack_path.exists():
        return {}
    try:
        data = yaml.safe_load(ack_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, list):
        return {}
    acknowledgments: dict[str, str] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path", "")
        reason = str(entry.get("reason", "")).strip()
        if path and reason:
            acknowledgments[str(Path(path))] = reason
    return acknowledgments


def _apply_acknowledgments(
    result: ValidationResult,
    *,
    ack_file: str | None,
) -> set[str]:
    """Downgrade acknowledged strict gaps to non-blocking notes."""
    acknowledged: set[str] = set()
    if not ack_file:
        return acknowledged

    ack_path = Path(ack_file)
    if not ack_path.exists():
        return acknowledged

    acknowledgments = load_ack_file(ack_path)
    for missing_path in list(result.missing_strict):
        if missing_path in acknowledgments:
            acknowledged.add(missing_path)
            result.missing_strict.discard(missing_path)
            continue
        if any(
            fnmatch.fnmatch(ack_path_glob, missing_path) or fnmatch.fnmatch(missing_path, ack_path_glob)
            for ack_path_glob in acknowledgments
        ):
            acknowledged.add(missing_path)
            result.missing_strict.discard(missing_path)
    return acknowledged


def _run_soft_notebook_check(repo_root: Path) -> None:
    """Run the non-blocking notebook registry validation for one repo."""
    registry_path = repo_root / "notebooks" / "notebook_registry.yaml"
    if not registry_path.exists():
        return

    workspace_root = detect_workspace_root(repo_root)
    try:
        registry = load_notebook_registry(registry_path)
        notebook_result = validate_notebook_registry(
            registry,
            registry_path=registry_path,
            workspace_root=workspace_root,
        )
    except (ValueError, yaml.YAMLError) as exc:
        print("\nNOTEBOOK REGISTRY (soft check — non-blocking):")
        print(f"  notebook registry check error: {exc}")
        return

    buffer = StringIO()
    with contextlib.redirect_stdout(buffer):
        print_human_readable(notebook_result)
    rendered = buffer.getvalue().strip()
    if rendered:
        print("\nNOTEBOOK REGISTRY (soft check — non-blocking):")
        for line in rendered.splitlines():
            print(f"  {line}")


def main(
    argv: Sequence[str] | None = None,
    *,
    repo_root: Path | None = None,
    plans_dir: Path | None = None,
) -> int:
    """Run plan validation from the command line."""
    base_repo_root = repo_root or ROOT
    base_plans_dir = plans_dir or (base_repo_root / "docs" / "plans")

    parser = argparse.ArgumentParser(description="Validate a plan against the documentation relationship graph")
    parser.add_argument(
        "--repo-root",
        default=str(base_repo_root),
        help="Repository root owning the plan and meta-process.yaml.",
    )
    parser.add_argument("--plan", type=int, help="Plan number (e.g. 28)")
    parser.add_argument("--plan-file", help="Plan file path (overrides --plan)")
    parser.add_argument(
        "--plans-dir",
        default=str(base_plans_dir),
        help="Directory containing plan files",
    )
    parser.add_argument(
        "--config",
        default="scripts/relationships.yaml",
        help="Path to relationship configuration",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Do not fail when gaps are found",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable result",
    )
    parser.add_argument(
        "--ack-file",
        default=None,
        help="Path to YAML file with acknowledged doc gaps (path + reason per entry)",
    )
    parser.add_argument(
        "--repository-id",
        default=None,
        help="Stable logical repository ID; defaults to the Git common-checkout directory name.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    effective_repo_root = Path(args.repo_root).expanduser().resolve()

    resolved_plans_dir = Path(args.plans_dir)
    if not resolved_plans_dir.is_absolute():
        resolved_plans_dir = effective_repo_root / resolved_plans_dir

    plan_number = args.plan
    if plan_number is None and not args.plan_file:
        plan_number = get_current_plan_number(repo_root=effective_repo_root)

    plan_path = get_plan_file(
        plan_number,
        resolved_plans_dir,
        args.plan_file,
        repo_root=effective_repo_root,
    )
    if not args.plan and plan_number is None:
        match = re.match(r"(\d+)_", plan_path.name)
        if match:
            plan_number = int(match.group(1))

    try:
        integrity = validate_plan_integrity_from_path(
            repo_root=effective_repo_root,
            repository_id=args.repository_id or detect_repository_id(effective_repo_root),
            plan_path=plan_path,
            plan_number=plan_number,
        )
        relationships = load_relationships(
            repo_root=effective_repo_root,
            config_path=args.config,
        )
        result = validate_plan(
            plan_path,
            plan_number,
            relationships,
            repo_root=effective_repo_root,
            plan_integrity=integrity,
        )
    except (OSError, PlanningIntegrityError) as exc:
        if args.json:
            print(json.dumps({"error": {"code": "planning_integrity_error", "message": str(exc)}}, indent=2))
        else:
            print(f"Planning integrity error: {exc}")
        return 2
    acknowledged = _apply_acknowledgments(result, ack_file=args.ack_file)

    if args.json:
        print(json.dumps(result.to_payload(), indent=2))
    else:
        print_summary(result)
        if acknowledged:
            print("\nACKNOWLEDGED GAPS (non-blocking):")
            ack_data = load_ack_file(Path(args.ack_file)) if args.ack_file else {}
            for path in sorted(acknowledged):
                reason = next(
                    (
                        ack_data[ack_path]
                        for ack_path in ack_data
                        if fnmatch.fnmatch(ack_path, path) or fnmatch.fnmatch(path, ack_path)
                    ),
                    "acknowledged",
                )
                print(f"  - {path} — {reason}")

    integrity_blocks = (
        result.plan_integrity is not None
        and result.plan_integrity.mode == "enforce"
        and result.plan_integrity.disposition == "fail"
    )
    if integrity_blocks:
        return 1

    if args.warn_only:
        return 0

    if result.missing_strict or result.missing_adrs or result.missing_sections:
        return 1

    if not args.json:
        _run_soft_notebook_check(effective_repo_root)

    return 0
