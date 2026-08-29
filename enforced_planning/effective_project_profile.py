"""Resolve one portable, explainable governed-project profile."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


ControlMode = Literal["off", "observe", "enforce"]


class EffectiveControlV1(BaseModel):
    """One configured value and the value effective after master policy."""

    model_config = ConfigDict(extra="forbid")
    configured: bool | ControlMode
    effective: bool | ControlMode
    reason: Literal["configured", "default", "master_disabled"]


class EffectiveProjectProfileV1(BaseModel):
    """Machine-readable effective state for the portable framework."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0.0"] = "1.0.0"
    master_enabled: bool
    master_source: Literal["default", "configured"]
    controls: dict[str, EffectiveControlV1]
    wiki_authority: Literal["derived_navigation"] = "derived_navigation"


DEFAULTS: dict[str, bool | ControlMode] = {
    "plans.enabled": True,
    "plans.integrity.mode": "enforce",
    "claims.enabled": True,
    "claims.prewrite_mode": "off",
    "artifact_creation.mode": "off",
    "worktrees.enabled": False,
    "quality.doc_coupling.enabled": False,
    "knowledge_navigation.enabled": True,
    "knowledge_navigation.freshness_mode": "observe",
}


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return value


def _read_path(root: dict[str, Any], dotted: str) -> tuple[Any, bool]:
    current: Any = root
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None, False
        current = current[part]
    return current, True


def resolve_effective_project_profile(payload: dict[str, Any] | None) -> EffectiveProjectProfileV1:
    """Resolve defaults and master override without mutating source configuration."""

    root = _mapping(payload, field="configuration")
    meta = _mapping(root.get("meta_process", root), field="meta_process")
    governance = _mapping(meta.get("governance"), field="meta_process.governance")
    raw_master = governance.get("enabled", True)
    if not isinstance(raw_master, bool):
        raise ValueError("meta_process.governance.enabled must be a boolean")
    controls: dict[str, EffectiveControlV1] = {}
    for dotted, default in DEFAULTS.items():
        configured, present = _read_path(meta, dotted)
        value = configured if present else default
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError(f"meta_process.{dotted} must be a boolean")
            disabled: bool | ControlMode = False
        else:
            if value not in {"off", "observe", "enforce"}:
                raise ValueError(f"meta_process.{dotted} must be one of: off, observe, enforce")
            disabled = "off"
        controls[dotted] = EffectiveControlV1(
            configured=value,
            effective=value if raw_master else disabled,
            reason="master_disabled" if not raw_master else ("configured" if present else "default"),
        )
    return EffectiveProjectProfileV1(
        master_enabled=raw_master,
        master_source="configured" if "enabled" in governance else "default",
        controls=controls,
    )


def load_effective_project_profile(repo_root: Path) -> EffectiveProjectProfileV1:
    """Load ``meta-process.yaml`` when present; absence uses default-on policy."""

    path = repo_root / "meta-process.yaml"
    if not path.exists():
        return resolve_effective_project_profile(None)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError("meta-process.yaml must be a mapping")
    return resolve_effective_project_profile(loaded)
