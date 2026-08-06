"""Validate immutable roadmap-to-design handoff records without storing them.

The contract keeps project direction authoritative in its roadmap while giving
the bounded design procedure an exact, machine-checkable input and a compact
delta-only return. It intentionally provides no registry or persistence layer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Annotated, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"
SLUG_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"


class StrictRecord(BaseModel):
    """Reject undeclared fields so transport records cannot absorb authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthorityRef(StrictRecord):
    """Reference one concern-specific authority at an immutable revision."""

    path: str = Field(min_length=1, description="Repository-relative or governed external authority path.")
    revision: str = Field(min_length=1, description="Immutable commit, digest, or version observed by the handoff.")
    concern: str = Field(min_length=1, description="Exact fact class or concern owned by the referenced surface.")


class TypedDependency(StrictRecord):
    """Describe why the selected goal depends on another governed artifact."""

    dependency_type: Literal[
        "requires_implementation",
        "requires_proof",
        "recommended_before",
        "blocked_by",
        "informs",
    ] = Field(description="Meaning of the dependency rather than an untyped edge.")
    target_ref: AuthorityRef = Field(description="Authority that owns the dependency target.")
    condition: str = Field(min_length=1, description="Observable condition under which the dependency is discharged.")


class EvidenceTarget(StrictRecord):
    """Name the exact future claim and the evidence class needed to support it."""

    claim: str = Field(min_length=1, description="Bounded claim that the design and implementation should license.")
    evidence_class: Literal["doc", "fixture", "schema_validated", "test", "observed"] = Field(
        description="Minimum evidence class required for this claim."
    )


class CapabilityAdoptionBinding(StrictRecord):
    """Bind an existing capability to the consumer path that must actually use it."""

    capability_ref: AuthorityRef = Field(description="Existing capability authority being adopted or displaced.")
    disposition: Literal["reuse", "extend", "supersede", "explicit_exception"] = Field(
        description="Explicit treatment of the existing capability; silent parallel implementations are forbidden."
    )
    canonical_seam: str = Field(
        min_length=1,
        description="Repository symbol, interface, command, or other concrete entrypoint owned by the capability.",
    )
    intended_consumer: str = Field(
        min_length=1,
        description="Product path, scenario, service, or other consumer that must bind to the capability.",
    )
    adoption_proof: EvidenceTarget = Field(
        description="Evidence that will show the intended consumer actually executed the selected capability path."
    )
    replacement_ref: AuthorityRef | None = Field(
        default=None,
        description="Accepted replacement authority required only when the prior capability is superseded.",
    )
    exception_reason: str | None = Field(
        default=None,
        min_length=1,
        description="Visible bounded reason required only for an explicit reduced-capability exception.",
    )

    @model_validator(mode="after")
    def validate_disposition_fields(self) -> "CapabilityAdoptionBinding":
        """Keep replacement and exception authority explicit and mutually exclusive."""

        if self.disposition == "supersede":
            if self.replacement_ref is None or self.exception_reason is not None:
                raise ValueError("supersede requires replacement_ref and forbids exception_reason")
        elif self.disposition == "explicit_exception":
            if self.exception_reason is None or self.replacement_ref is not None:
                raise ValueError("explicit_exception requires exception_reason and forbids replacement_ref")
        elif self.replacement_ref is not None or self.exception_reason is not None:
            raise ValueError(f"{self.disposition} forbids replacement_ref and exception_reason")
        return self


class MaterialUnknown(StrictRecord):
    """Keep an unknown explicit and assign its permitted treatment."""

    unknown_id: str = Field(pattern=SLUG_PATTERN, description="Stable packet-local identifier for the unknown.")
    question: str = Field(min_length=1, description="Decision-relevant fact that is not yet known.")
    treatment: Literal["investigate", "instrument", "human_decision", "block"] = Field(
        description="How the unknown must be resolved rather than guessed."
    )


class OwnerSelection(StrictRecord):
    """Name either the responsible role or the authority that must choose it."""

    kind: Literal["owner", "owner_decision_required"] = Field(description="Whether ownership is known or needs a decision.")
    owner_role: str | None = Field(default=None, min_length=1, description="Responsible role when ownership is known.")
    decision_ref: AuthorityRef | None = Field(
        default=None,
        description="Authority that must assign ownership when no owner is yet known.",
    )

    @model_validator(mode="after")
    def validate_selection(self) -> "OwnerSelection":
        """Require exactly the fields appropriate to the selected ownership mode."""

        if self.kind == "owner" and (self.owner_role is None or self.decision_ref is not None):
            raise ValueError("kind=owner requires owner_role and forbids decision_ref")
        if self.kind == "owner_decision_required" and (self.decision_ref is None or self.owner_role is not None):
            raise ValueError("kind=owner_decision_required requires decision_ref and forbids owner_role")
        return self


class RoadmapGoalHandoff(StrictRecord):
    """Immutable selection snapshot produced by project roadmapping."""

    schema_version: Literal["1.0"] = Field(description="Planning handoff contract version.")
    record_type: Literal["roadmap_goal_handoff"] = Field(description="Discriminator for the selection record.")
    handoff_id: str = Field(min_length=1, description="Deterministic project, goal, and roadmap-revision identity.")
    project_id: str = Field(pattern=SLUG_PATTERN, description="Stable project or initiative identifier.")
    goal_id: str = Field(pattern=SLUG_PATTERN, description="Stable roadmap-owned goal identifier.")
    project_roadmap_ref: AuthorityRef = Field(description="Roadmap authority that selected this goal.")
    objective: str = Field(min_length=1, description="One bounded observable outcome passed to design.")
    objective_sha256: str = Field(pattern=SHA256_PATTERN, description="UTF-8 SHA-256 of the exact objective text.")
    audience_or_actor: str = Field(min_length=1, description="Actor who receives value from the outcome.")
    current_state_ref: AuthorityRef = Field(description="Current-state authority consumed at selection time.")
    desired_outcome: str = Field(min_length=1, description="Observable target state without implementation detail.")
    non_goals: tuple[str, ...] = Field(default=(), description="Explicitly excluded outcomes.")
    non_claims: tuple[str, ...] = Field(default=(), description="Claims this handoff does not license.")
    required_capability_refs: tuple[AuthorityRef, ...] = Field(
        default=(), description="Existing authorities for capabilities required by the goal."
    )
    capability_adoptions: tuple[CapabilityAdoptionBinding, ...] = Field(
        default=(),
        description="Exact reuse, extension, supersession, or visible-exception binding for each required capability.",
    )
    typed_dependencies: tuple[TypedDependency, ...] = Field(default=(), description="Typed project-level dependencies.")
    applicable_decision_refs: tuple[AuthorityRef, ...] = Field(default=(), description="Adopted decisions governing design.")
    applicable_policy_refs: tuple[AuthorityRef, ...] = Field(default=(), description="Policy authorities governing design.")
    success_or_readout: str = Field(min_length=1, description="Frozen pass/fail criterion or exploratory decision readout.")
    evidence_target: EvidenceTarget = Field(description="Claim-specific evidence required for closure.")
    material_unknowns: tuple[MaterialUnknown, ...] = Field(default=(), description="Unknowns design must not silently guess.")
    owner_or_owner_decision: OwnerSelection = Field(description="Owner or explicit ownership-decision authority.")
    recommended_design_profile: Literal["small", "standard"] = Field(description="Required design depth.")
    recommended_overlays: tuple[
        Literal[
            "runtime_state",
            "exploratory",
            "public_api",
            "migration",
            "llm",
            "ui",
            "regulated_data",
            "operational_service",
            "repository_governance",
        ],
        ...,
    ] = Field(default=(), description="Conditionally activated design overlays.")
    selected_at: AwareDatetime = Field(description="Timezone-aware time when the roadmap selected this goal.")

    @model_validator(mode="after")
    def validate_identity(self) -> "RoadmapGoalHandoff":
        """Bind the transport identity to the roadmap-owned goal and revision."""

        expected_id = f"roadmap-goal:{self.project_id}:{self.goal_id}:{self.project_roadmap_ref.revision}"
        if self.handoff_id != expected_id:
            raise ValueError(f"handoff_id must equal {expected_id!r}")
        expected_objective_hash = hashlib.sha256(self.objective.encode("utf-8")).hexdigest()
        if self.objective_sha256 != expected_objective_hash:
            raise ValueError("objective_sha256 does not match objective")
        required = {
            (item.path, item.revision, item.concern)
            for item in self.required_capability_refs
        }
        adopted = {
            (
                item.capability_ref.path,
                item.capability_ref.revision,
                item.capability_ref.concern,
            )
            for item in self.capability_adoptions
        }
        if len(adopted) != len(self.capability_adoptions):
            raise ValueError("capability_adoptions must bind each capability exactly once")
        if adopted != required:
            raise ValueError("capability_adoptions must exactly match required_capability_refs")
        return self


class CapabilityGraphDelta(StrictRecord):
    """Propose one bounded capability-graph change without replacing the graph."""

    operation: Literal["add", "update", "remove"] = Field(description="Proposed graph operation.")
    capability_ref: AuthorityRef = Field(description="Capability authority affected by the proposal.")
    rationale: str = Field(min_length=1, description="Reason the roadmap owner should consider the proposal.")


class RelationshipUpdate(StrictRecord):
    """Propose one reviewed intent or maintenance-edge update."""

    operation: Literal["add", "update", "remove"] = Field(description="Proposed relationship operation.")
    subject_ref: AuthorityRef = Field(description="Authority for the relationship subject.")
    predicate: str = Field(pattern=SLUG_PATTERN, description="Typed relationship predicate.")
    object_ref: AuthorityRef = Field(description="Authority for the relationship object.")
    rationale: str = Field(min_length=1, description="Why the reviewed edge should change.")


class MaterialConcern(StrictRecord):
    """Require every material design concern to close or leave with an owner."""

    concern_id: str = Field(pattern=SLUG_PATTERN, description="Stable packet-local concern identifier.")
    concern_class: Literal["strategy", "architecture", "policy", "implementation", "verification", "execution"] = Field(
        description="Native concern class whose authority must own unresolved state."
    )
    summary: str = Field(min_length=1, description="Decision-relevant concern.")
    disposition: Literal["closed", "promoted", "assigned"] = Field(description="Required handoff disposition.")
    resolution: str | None = Field(default=None, min_length=1, description="Closure reason when disposition is closed.")
    authority_ref: AuthorityRef | None = Field(default=None, description="Canonical owner when promoted.")
    owner_role: str | None = Field(default=None, min_length=1, description="Responsible role when assigned.")
    resume_condition: str | None = Field(default=None, min_length=1, description="Exact event that resumes an assigned concern.")

    @model_validator(mode="after")
    def validate_disposition(self) -> "MaterialConcern":
        """Reject unresolved concerns that lack their native authority or owner."""

        if self.disposition == "closed":
            valid = self.resolution is not None and self.authority_ref is None and self.owner_role is None and self.resume_condition is None
        elif self.disposition == "promoted":
            valid = self.authority_ref is not None and self.resolution is None and self.owner_role is None and self.resume_condition is None
        else:
            valid = self.owner_role is not None and self.resume_condition is not None and self.resolution is None and self.authority_ref is None
        if not valid:
            raise ValueError(f"material concern fields do not match disposition={self.disposition}")
        return self


class RoadmapImplication(StrictRecord):
    """Return a proposal for roadmap review without claiming it is adopted."""

    implication_type: Literal["goal_revision", "dependency_change", "priority_review", "new_goal_candidate"] = Field(
        description="Kind of roadmap-owned decision proposed by design."
    )
    proposal: str = Field(min_length=1, description="Proposed roadmap delta, never current roadmap state.")
    rationale: str = Field(min_length=1, description="Design evidence or constraint motivating the proposal.")


class DesignPacketResult(StrictRecord):
    """Compact delta-only handback produced by one bounded design packet."""

    schema_version: Literal["1.0"] = Field(description="Planning handoff contract version.")
    record_type: Literal["design_packet_result"] = Field(description="Discriminator for the handback record.")
    handoff_id: str = Field(min_length=1, description="Exact handoff identity consumed by the design packet.")
    source_handoff_sha256: str = Field(pattern=SHA256_PATTERN, description="Canonical SHA-256 of the consumed handoff record.")
    source_roadmap_revision: str = Field(min_length=1, description="Roadmap revision consumed by the design packet.")
    goal_id: str = Field(pattern=SLUG_PATTERN, description="Roadmap-owned goal identifier echoed by design.")
    objective_sha256: str = Field(pattern=SHA256_PATTERN, description="Exact objective identity echoed from the handoff.")
    design_packet_ref: AuthorityRef = Field(description="Authority for detailed bounded design decisions.")
    objective_disposition: Literal["preserved", "proposed_revision", "blocked"] = Field(
        description="Whether design preserved, proposed changing, or could not design the objective."
    )
    proposed_objective: str | None = Field(default=None, min_length=1, description="Proposed replacement only when revision is requested.")
    requirement_refs: tuple[AuthorityRef, ...] = Field(default=(), description="Detailed requirements owned by the design packet or native authority.")
    boundary_refs: tuple[AuthorityRef, ...] = Field(default=(), description="Affected interface and responsibility boundaries.")
    domain_model_ref: AuthorityRef | None = Field(default=None, description="Domain-model authority when one is required.")
    contract_refs: tuple[AuthorityRef, ...] = Field(default=(), description="Typed contracts derived by the design.")
    schema_disposition: Literal["reuse", "extend", "create", "none"] = Field(description="Disposition for machine-readable schema work.")
    capability_graph_delta: tuple[CapabilityGraphDelta, ...] = Field(default=(), description="Scoped capability proposals for roadmap review.")
    relationship_or_intent_updates: tuple[RelationshipUpdate, ...] = Field(default=(), description="Reviewed relationship proposals.")
    evidence_plan_ref: AuthorityRef = Field(description="Authority for acceptance and disproof evidence.")
    next_slice_refs: tuple[AuthorityRef, ...] = Field(default=(), description="Authorized or proposed risk-ordered next slices.")
    material_concerns: tuple[MaterialConcern, ...] = Field(default=(), description="Concerns closed, promoted, or assigned at handoff.")
    roadmap_implications: tuple[RoadmapImplication, ...] = Field(default=(), description="Delta proposals requiring roadmap-owner adoption.")
    completed_at: AwareDatetime = Field(description="Timezone-aware completion time for the design handback.")

    @model_validator(mode="after")
    def validate_objective_disposition(self) -> "DesignPacketResult":
        """Permit proposed objective text only for an explicit revision proposal."""

        if (self.objective_disposition == "proposed_revision") != (self.proposed_objective is not None):
            raise ValueError("proposed_objective is required only for objective_disposition=proposed_revision")
        return self


class PlanningHandoffExchange(StrictRecord):
    """Validate one roadmap selection and its corresponding design handback."""

    handoff: RoadmapGoalHandoff = Field(description="Immutable roadmap selection snapshot.")
    result: DesignPacketResult = Field(description="Delta-only bounded design handback.")

    @model_validator(mode="after")
    def validate_exchange(self) -> "PlanningHandoffExchange":
        """Fail loud when design returns against a different goal, objective, or revision."""

        expected_handoff_hash = canonical_record_sha256(self.handoff)
        mismatches: list[str] = []
        if self.result.handoff_id != self.handoff.handoff_id:
            mismatches.append("handoff_id")
        if self.result.goal_id != self.handoff.goal_id:
            mismatches.append("goal_id")
        if self.result.objective_sha256 != self.handoff.objective_sha256:
            mismatches.append("objective_sha256")
        if self.result.source_roadmap_revision != self.handoff.project_roadmap_ref.revision:
            mismatches.append("source_roadmap_revision")
        if self.result.source_handoff_sha256 != expected_handoff_hash:
            mismatches.append("source_handoff_sha256")
        if mismatches:
            raise ValueError(f"design result does not match handoff: {', '.join(mismatches)}")
        return self


PlanningSchema = Annotated[
    RoadmapGoalHandoff | DesignPacketResult,
    Field(discriminator="record_type"),
]


def canonical_record_sha256(record: BaseModel) -> str:
    """Hash one validated record using deterministic JSON serialization."""

    payload = json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_exchange(path: Path) -> PlanningHandoffExchange:
    """Load and validate one YAML or JSON exchange fixture."""

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("planning handoff exchange must be a mapping")
    return PlanningHandoffExchange.model_validate(raw)


def build_parser() -> argparse.ArgumentParser:
    """Build the agent-drivable validator and schema-export CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    validate = subparsers.add_parser("validate", help="Validate one handoff exchange YAML or JSON file.")
    validate.add_argument("path", type=Path)
    schema = subparsers.add_parser("schema", help="Print one generated JSON Schema.")
    schema.add_argument("record", choices=("handoff", "result", "exchange"))
    return parser


def main(argv: list[str] | None = None) -> int:
    """Validate a transport fixture or emit its generated structural schema."""

    args = build_parser().parse_args(argv)
    if args.operation == "schema":
        models: dict[str, type[BaseModel]] = {
            "handoff": RoadmapGoalHandoff,
            "result": DesignPacketResult,
            "exchange": PlanningHandoffExchange,
        }
        model = models[args.record]
        print(json.dumps(model.model_json_schema(), indent=2, sort_keys=True))
        return 0
    try:
        exchange = load_exchange(args.path)
    except (OSError, ValueError, ValidationError) as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "handoff_id": exchange.handoff.handoff_id,
                "goal_id": exchange.handoff.goal_id,
                "result_ref": exchange.result.design_packet_ref.path,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
