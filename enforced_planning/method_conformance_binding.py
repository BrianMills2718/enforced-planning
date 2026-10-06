"""Bind plan-backed claims to an exact Company Planning method-conformance receipt.

Company Planning owns method profiles, compilation, validation, and the adoption
decision (``PlanningMethodConformanceReceiptV1``, written only by its adoption
gate). Enforced Planning owns claim admission. This module consumes the receipt
without re-deciding method policy: it re-resolves the receipt bytes and the plan
bytes at the exact plan-authority revision, and refuses a missing receipt, a
digest mismatch, a non-passing receipt, a receipt for another plan, or a plan
revision newer than its receipt.

Requirement is per repository, declared structurally in ``meta-process.yaml``::

    meta_process:
      plans:
        method_conformance:
          mode: required   # or: off (default)

With ``mode: off`` a claim may still cite a receipt, and the citation is
verified the same way; it can never be cited by an explicitly unplanned claim.
Consumer contract: company-planning
``plugins/company-planning/contracts/method-conformance/README.md``.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

RECEIPT_SCHEMA_VERSION = "planning-method-conformance-receipt.v1"
RECEIPT_RECORD_TYPE = "planning_method_conformance_receipt"
FRONT_MATTER_KEY = "method_conformance_receipt"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MethodConformanceRefusal(ValueError):
    """A claim-admission refusal with one stable reason code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"method conformance refused ({code}): {message}")
        self.code = code


class MethodConformanceBindingV1(BaseModel):
    """The exact receipt identity a plan-backed claim retains."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    mode: Literal["required", "off"]
    plan_path: str
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    receipt_path: str
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_id: str
    route: str
    profile_revision: str
    checklist_definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _git_show(root: Path, revision: str, path: str) -> bytes | None:
    completed = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), "show", f"{revision}:{path}"],
        capture_output=True,
        check=False,
    )
    return completed.stdout if completed.returncode == 0 else None


def _repo_relative(path: str, label: str) -> str:
    normalized = PurePosixPath(path.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts or not normalized.parts:
        raise MethodConformanceRefusal("method_receipt_invalid", f"{label} {path!r} must be repository-relative")
    return normalized.as_posix()


def method_conformance_mode(plan_root: Path, revision: str) -> Literal["required", "off"]:
    """Read the repository's structural requirement at the exact plan revision."""

    content = _git_show(plan_root, revision, "meta-process.yaml")
    if content is None:
        return "off"
    payload = yaml.safe_load(content) or {}
    meta = payload.get("meta_process", payload) if isinstance(payload, dict) else {}
    plans = meta.get("plans", {}) if isinstance(meta, dict) else {}
    setting = plans.get("method_conformance") if isinstance(plans, dict) else None
    if setting is None:
        return "off"
    mode = setting.get("mode") if isinstance(setting, dict) else None
    if mode not in ("required", "off"):
        raise MethodConformanceRefusal(
            "invalid_method_conformance_config",
            "meta-process.yaml plans.method_conformance.mode must be 'required' or 'off'",
        )
    return mode


def _front_matter(content: str) -> dict[str, Any]:
    if not content.startswith("---\n"):
        return {}
    end = content.find("\n---", 4)
    if end < 0:
        return {}
    loaded = yaml.safe_load(content[4:end])
    return loaded if isinstance(loaded, dict) else {}


def _plan_number_from_path(path: str) -> int | None:
    match = re.fullmatch(r"(\d+)_.*\.md", PurePosixPath(path).name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def resolve_method_conformance_binding(
    *,
    plan_root: Path | str,
    plan_revision: str,
    plan_number: int | None,
    receipt_ref: str | None,
    receipt_sha256: str | None,
) -> MethodConformanceBindingV1 | None:
    """Resolve the exact passing receipt a plan-backed claim names, or refuse.

    Returns ``None`` only when the repository does not require a receipt and the
    claim names none.
    """

    root = Path(plan_root).expanduser().resolve()
    mode = method_conformance_mode(root, plan_revision)
    if receipt_ref is None and receipt_sha256 is None:
        if mode == "required":
            raise MethodConformanceRefusal(
                "missing_method_receipt",
                "this repository requires every plan-backed claim to name its passing Company Planning "
                "method-conformance receipt: pass --method-receipt <path> and --method-receipt-sha256 <digest> "
                "from the plan's adoption decision",
            )
        return None
    if receipt_ref is None or receipt_sha256 is None:
        raise MethodConformanceRefusal(
            "missing_method_receipt", "--method-receipt and --method-receipt-sha256 must be given together"
        )
    if SHA256.fullmatch(receipt_sha256) is None:
        raise MethodConformanceRefusal("method_receipt_digest_mismatch", "receipt digest must be 64 lowercase hex")
    receipt_path = _repo_relative(receipt_ref, "receipt path")
    receipt_bytes = _git_show(root, plan_revision, receipt_path)
    if receipt_bytes is None:
        raise MethodConformanceRefusal(
            "method_receipt_missing", f"receipt {receipt_path} is not committed at plan revision {plan_revision}"
        )
    observed = hashlib.sha256(receipt_bytes).hexdigest()
    if observed != receipt_sha256:
        raise MethodConformanceRefusal(
            "method_receipt_digest_mismatch",
            f"receipt {receipt_path} at {plan_revision} has sha256 {observed}, not the claimed {receipt_sha256}",
        )
    try:
        receipt = json.loads(receipt_bytes)
    except json.JSONDecodeError as exc:
        raise MethodConformanceRefusal("method_receipt_invalid", f"receipt is not JSON: {exc}") from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or receipt.get("record_type") != RECEIPT_RECORD_TYPE
    ):
        raise MethodConformanceRefusal("method_receipt_invalid", "not a PlanningMethodConformanceReceiptV1")
    if receipt.get("result") != "pass":
        raise MethodConformanceRefusal(
            "method_receipt_not_passing",
            f"receipt result is {receipt.get('result')!r}; only a passing receipt admits a plan-backed claim",
        )
    plan = receipt.get("plan") or {}
    plan_path = _repo_relative(str(plan.get("plan_ref") or ""), "receipt plan_ref")
    if plan_number is not None and _plan_number_from_path(plan_path) != plan_number:
        raise MethodConformanceRefusal(
            "method_receipt_plan_mismatch", f"receipt is for {plan_path}, not plan #{plan_number}"
        )
    plan_bytes = _git_show(root, plan_revision, plan_path)
    if plan_bytes is None:
        raise MethodConformanceRefusal("method_receipt_plan_missing", f"plan {plan_path} is absent at {plan_revision}")
    plan_sha256 = hashlib.sha256(plan_bytes).hexdigest()
    if plan_sha256 != plan.get("plan_sha256"):
        raise MethodConformanceRefusal(
            "stale_plan_revision",
            f"plan {plan_path} changed after its receipt (now sha256 {plan_sha256}); re-run Company Planning "
            "adoption for this revision before claiming",
        )
    declared = _front_matter(plan_bytes.decode("utf-8")).get(FRONT_MATTER_KEY)
    if declared != receipt_path:
        raise MethodConformanceRefusal(
            "method_receipt_not_declared_by_plan",
            f"plan front matter declares {FRONT_MATTER_KEY}={declared!r}, not {receipt_path!r}",
        )
    checklist = receipt.get("checklist") or {}
    profile = receipt.get("profile") or {}
    return MethodConformanceBindingV1(
        mode=mode,
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        plan_revision=plan_revision,
        receipt_path=receipt_path,
        receipt_sha256=receipt_sha256,
        receipt_id=str(receipt.get("receipt_id")),
        route=str(receipt.get("route")),
        profile_revision=str(profile.get("revision")),
        checklist_definition_sha256=str(checklist.get("definition_sha256")),
    )
