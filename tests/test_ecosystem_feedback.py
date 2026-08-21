"""Both-sign contract, storage, concurrency, and CLI tests for Plan 111 EF-01."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from typing import Any

import pydantic
import pytest
from pydantic import ValidationError

from enforced_planning import ecosystem_feedback as feedback_impl
from enforced_planning.ecosystem_feedback import (
    FEEDBACK_SCOPE_KINDS,
    EcosystemFeedbackCreateV1,
    EcosystemFeedbackDispositionCreateV1,
    EcosystemFeedbackDispositionV1,
    EcosystemFeedbackError,
    EcosystemFeedbackReportV1,
    EcosystemFeedbackSourceV1,
    EcosystemFeedbackV1,
    EcosystemFeedbackViewV1,
    disposition_ecosystem_feedback,
    list_ecosystem_feedback,
    record_ecosystem_feedback,
    report_ecosystem_feedback,
)

CLI_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ecosystem_feedback.py"
FIXED_FEEDBACK_ID = f"ecosystem_feedback_{'1' * 32}"
DEPENDENCY_SITE_PACKAGES = str(Path(pydantic.__file__).resolve().parents[1])


@pytest.fixture(autouse=True)
def _isolate_process_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep API and subprocess defaults inside the per-test temporary directory."""

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("ECOSYSTEM_FEEDBACK_PATH", str(tmp_path / "ambient-must-not-be-used.jsonl"))


def _source(**overrides: str | None) -> EcosystemFeedbackSourceV1:
    payload: dict[str, str | None] = {"client": "pytest"}
    payload.update(overrides)
    return EcosystemFeedbackSourceV1.model_validate(payload)


def _request(
    *,
    feedback_type: str = "friction",
    scope_kind: str = "skill",
    scope_id: str | None | object = ...,
    observation: str = "The runtime profile did not match the accepted plan profile.",
    expected_behavior: str | None | object = ...,
    recommendation: str = "Publish one mechanical profile mapping.",
    evidence_refs: tuple[str, ...] = ("receipt:test-observation",),
    source: EcosystemFeedbackSourceV1 | None = None,
) -> EcosystemFeedbackCreateV1:
    actual_scope_id = (None if scope_kind == "general" else f"{scope_kind}:example") if scope_id is ... else scope_id
    actual_expected = (
        ("The accepted plan profile should map to the runtime profile." if feedback_type == "friction" else None)
        if expected_behavior is ...
        else expected_behavior
    )
    return EcosystemFeedbackCreateV1.model_validate(
        {
            "feedback_type": feedback_type,
            "scope_kind": scope_kind,
            "scope_id": actual_scope_id,
            "observation": observation,
            "expected_behavior": actual_expected,
            "recommendation": recommendation,
            "evidence_refs": evidence_refs,
            "source": source or _source(),
        }
    )


def _record(
    stream: Path,
    *,
    feedback_type: str = "friction",
    scope_kind: str = "skill",
    scope_id: str | None | object = ...,
    source: EcosystemFeedbackSourceV1 | None = None,
) -> EcosystemFeedbackV1:
    return record_ecosystem_feedback(
        _request(
            feedback_type=feedback_type,
            scope_kind=scope_kind,
            scope_id=scope_id,
            source=source,
        ),
        feedback_path=stream,
    )


def _fixed_feedback(*, feedback_id: str = FIXED_FEEDBACK_ID) -> EcosystemFeedbackV1:
    return EcosystemFeedbackV1(
        schema_version="1.0",
        record_type="feedback",
        feedback_id=feedback_id,
        recorded_at=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
        status="open",
        **_request().model_dump(),
    )


def _fixed_disposition(
    *,
    feedback_id: str = FIXED_FEEDBACK_ID,
    disposition_id: str | None = None,
    disposition: str = "resolved",
) -> EcosystemFeedbackDispositionV1:
    return EcosystemFeedbackDispositionV1(
        schema_version="1.0",
        record_type="feedback_disposition",
        disposition_id=disposition_id or f"ecosystem_feedback_disposition_{'2' * 32}",
        recorded_at=datetime(2026, 8, 21, 8, 1, tzinfo=UTC),
        feedback_id=feedback_id,
        disposition=disposition,
        rationale="The contract now has a mechanical mapping.",
    )


def _jsonl(*records: EcosystemFeedbackV1 | EcosystemFeedbackDispositionV1) -> bytes:
    return b"".join((json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n").encode() for record in records)


@pytest.mark.parametrize("scope_kind", FEEDBACK_SCOPE_KINDS)
def test_all_six_scope_kinds_record_through_one_contract(scope_kind: str, tmp_path: Path) -> None:
    """Every declared route uses one contract; general alone carries no scope ID."""

    stream = tmp_path / "feedback.jsonl"
    record = _record(stream, scope_kind=scope_kind)

    assert record.scope_kind == scope_kind
    assert record.scope_id is None if scope_kind == "general" else record.scope_id == f"{scope_kind}:example"
    persisted = json.loads(stream.read_text(encoding="utf-8"))
    assert persisted["feedback_id"] == record.feedback_id
    assert persisted["scope_kind"] == scope_kind


def test_general_scoped_and_feedback_type_semantics_are_strict() -> None:
    """Routing identity and friction expectations fail closed without burdening recommendations."""

    with pytest.raises(ValidationError, match="requires scope_id"):
        _request(scope_kind="policy", scope_id=None)
    with pytest.raises(ValidationError, match="must not fabricate"):
        _request(scope_kind="general", scope_id="invented")
    with pytest.raises(ValidationError, match="requires expected_behavior"):
        _request(feedback_type="friction", expected_behavior=None)

    recommendation = _request(feedback_type="recommendation", expected_behavior=None)
    assert recommendation.expected_behavior is None


def test_unknown_fields_fail_in_both_top_level_and_source_contracts() -> None:
    """Neither transport nor source identity accepts an unversioned extension."""

    payload = _request().model_dump(mode="json")
    with pytest.raises(ValidationError, match="extra_forbidden"):
        EcosystemFeedbackCreateV1.model_validate({**payload, "automatic_policy_change": True})
    with pytest.raises(ValidationError, match="extra_forbidden"):
        EcosystemFeedbackSourceV1.model_validate({"client": "pytest", "ambient_user": "brian"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observation", " \t"),
        ("recommendation", "\n"),
        ("scope_id", " "),
        ("expected_behavior", ""),
    ],
)
def test_empty_semantic_fields_fail(field: str, value: str) -> None:
    """Whitespace cannot satisfy a required semantic field."""

    payload = _request().model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError, match="non-whitespace|at least 1 character"):
        EcosystemFeedbackCreateV1.model_validate(payload)


@pytest.mark.parametrize(
    "evidence_refs",
    [(), ("",), (" \t",), ("receipt:same", "receipt:same")],
)
def test_empty_whitespace_or_duplicate_evidence_fails(evidence_refs: tuple[str, ...]) -> None:
    """A recommendation cannot be persisted without concrete, unique evidence identity."""

    with pytest.raises(ValidationError, match="at least 1 item|non-whitespace|duplicates"):
        _request(feedback_type="recommendation", evidence_refs=evidence_refs)


def test_source_contains_only_explicit_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Ambient repository and session variables cannot become durable source identity."""

    monkeypatch.setenv("CODEX_THREAD_ID", "codex:ambient-session")
    monkeypatch.setenv("PROJECT", "ambient-project")
    monkeypatch.chdir(tmp_path / "home")
    stream = tmp_path / "feedback.jsonl"

    record = _record(stream, source=_source(client="explicit-client"))

    assert record.source == EcosystemFeedbackSourceV1(client="explicit-client")
    assert record.source.project is None
    assert record.source.session_id is None
    assert record.source.working_directory is None
    assert json.loads(stream.read_text(encoding="utf-8"))["source"] == {
        "client": "explicit-client",
        "project": None,
        "session_id": None,
        "task_id": None,
        "working_directory": None,
    }


def test_nonexistent_evidence_reference_is_stored_but_never_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence references are inert identity, even when they resemble local paths."""

    stream = tmp_path / "feedback.jsonl"
    nonexistent = tmp_path / "evidence-that-must-not-be-opened.txt"
    original_open = Path.open
    opened: list[Path] = []

    def guarded_open(path: Path, *args: Any, **kwargs: Any):
        opened.append(path.resolve())
        if path.resolve() == nonexistent.resolve():
            raise AssertionError("transport attempted to dereference evidence")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    request = _request(evidence_refs=(str(nonexistent),))

    record = record_ecosystem_feedback(request, feedback_path=stream)

    assert record.evidence_refs == (str(nonexistent),)
    assert nonexistent.resolve() not in opened
    assert opened == [stream.resolve()]


def test_record_list_report_disposition_lifecycle_and_filters(tmp_path: Path) -> None:
    """Views and reports preserve insertion order and step down every count to stable IDs."""

    stream = tmp_path / "feedback.jsonl"
    skill_friction = _record(stream, scope_kind="skill", scope_id="bounded-design")
    skill_recommendation = _record(
        stream,
        feedback_type="recommendation",
        scope_kind="skill",
        scope_id="initiative-roadmap",
    )
    policy_recommendation = _record(
        stream,
        feedback_type="recommendation",
        scope_kind="policy",
        scope_id="planning-policy",
    )
    general_recommendation = _record(stream, feedback_type="recommendation", scope_kind="general")

    disposition = disposition_ecosystem_feedback(
        EcosystemFeedbackDispositionCreateV1(
            feedback_id=skill_recommendation.feedback_id,
            disposition="accepted",
            rationale="This improvement belongs in the accepted feedback transport.",
            successor_ref="plan:111/EF-02",
        ),
        feedback_path=stream,
    )

    all_views = list_ecosystem_feedback(feedback_path=stream)
    assert [item.feedback_id for item in all_views] == [
        skill_friction.feedback_id,
        skill_recommendation.feedback_id,
        policy_recommendation.feedback_id,
        general_recommendation.feedback_id,
    ]
    assert all_views[1].status == "accepted"
    assert all_views[1].disposition == disposition
    assert [item.feedback_id for item in list_ecosystem_feedback(feedback_path=stream, feedback_type="friction")] == [
        skill_friction.feedback_id
    ]
    assert [item.feedback_id for item in list_ecosystem_feedback(feedback_path=stream, scope_kind="skill")] == [
        skill_friction.feedback_id,
        skill_recommendation.feedback_id,
    ]
    assert [item.feedback_id for item in list_ecosystem_feedback(feedback_path=stream, scope_id="planning-policy")] == [
        policy_recommendation.feedback_id
    ]
    assert [item.feedback_id for item in list_ecosystem_feedback(feedback_path=stream, status="accepted")] == [
        skill_recommendation.feedback_id
    ]
    assert [item.feedback_id for item in list_ecosystem_feedback(feedback_path=stream, status="open")] == [
        skill_friction.feedback_id,
        policy_recommendation.feedback_id,
        general_recommendation.feedback_id,
    ]

    report = report_ecosystem_feedback(feedback_path=stream)
    assert report.feedback_count == 4
    assert report.open_count == 3
    assert report.dispositioned_count == 1
    assert report.feedback_ids == tuple(item.feedback_id for item in all_views)
    assert report.open_feedback_ids == (
        skill_friction.feedback_id,
        policy_recommendation.feedback_id,
        general_recommendation.feedback_id,
    )
    assert report.dispositioned_feedback_ids == (skill_recommendation.feedback_id,)
    assert report.feedback_type_counts == {"friction": 1, "recommendation": 3}
    assert report.scope_kind_counts["skill"] == 2
    assert report.scope_kind_counts["policy"] == 1
    assert report.scope_kind_counts["general"] == 1
    assert report.status_counts["open"] == 3
    assert report.status_counts["accepted"] == 1

    filtered = report_ecosystem_feedback(
        feedback_path=stream,
        feedback_type="recommendation",
        scope_kind="skill",
        status="accepted",
    )
    assert filtered.feedback_ids == (skill_recommendation.feedback_id,)
    assert filtered.feedback_count == filtered.dispositioned_count == 1


@pytest.mark.parametrize(
    ("filter_name", "filter_value"),
    [
        ("feedback_type", "complaint"),
        ("scope_kind", "ecosystem"),
        ("status", "ignored"),
    ],
)
def test_unknown_list_filters_fail_loud(filter_name: str, filter_value: str, tmp_path: Path) -> None:
    """Callers cannot receive a misleading empty result for an unsupported filter."""

    with pytest.raises(EcosystemFeedbackError, match=f"unsupported {filter_name} filter"):
        list_ecosystem_feedback(feedback_path=tmp_path / "missing.jsonl", **{filter_name: filter_value})  # type: ignore[arg-type]


def test_public_view_and_report_contracts_require_fixed_envelope_fields(tmp_path: Path) -> None:
    """Derived contracts cannot silently reconstruct a missing version or record discriminator."""

    stream = tmp_path / "feedback.jsonl"
    _record(stream)
    view_payload = list_ecosystem_feedback(feedback_path=stream)[0].model_dump(mode="json")
    report_payload = report_ecosystem_feedback(feedback_path=stream).model_dump(mode="json")

    for model, payload, missing_field in (
        (EcosystemFeedbackViewV1, view_payload, "schema_version"),
        (EcosystemFeedbackViewV1, view_payload, "record_type"),
        (EcosystemFeedbackReportV1, report_payload, "schema_version"),
    ):
        incomplete = payload.copy()
        del incomplete[missing_field]
        with pytest.raises(ValidationError, match="Field required"):
            model.model_validate(incomplete)


def test_report_contract_rejects_contradictory_status_counts_and_reordered_step_downs(tmp_path: Path) -> None:
    """Report aggregates must agree with lifecycle totals and preserve source-stream order."""

    stream = tmp_path / "feedback.jsonl"
    first_open = _record(stream, scope_kind="skill", scope_id="first-open")
    first_terminal = _record(stream, scope_kind="policy", scope_id="first-terminal")
    second_open = _record(stream, scope_kind="tool", scope_id="second-open")
    second_terminal = _record(stream, scope_kind="project", scope_id="second-terminal")
    for record in (first_terminal, second_terminal):
        disposition_ecosystem_feedback(
            EcosystemFeedbackDispositionCreateV1(
                feedback_id=record.feedback_id,
                disposition="resolved",
                rationale="Create a valid mixed-lifecycle report fixture.",
            ),
            feedback_path=stream,
        )

    baseline = report_ecosystem_feedback(feedback_path=stream).model_dump(mode="json")
    assert baseline["open_feedback_ids"] == [first_open.feedback_id, second_open.feedback_id]
    assert baseline["dispositioned_feedback_ids"] == [first_terminal.feedback_id, second_terminal.feedback_id]

    contradictory_counts = baseline.copy()
    contradictory_counts["status_counts"] = baseline["status_counts"].copy()
    contradictory_counts["status_counts"]["open"] = 1
    contradictory_counts["status_counts"]["resolved"] = 3
    with pytest.raises(ValidationError, match="open status count must equal open_count"):
        EcosystemFeedbackReportV1.model_validate(contradictory_counts)

    reordered_open = baseline.copy()
    reordered_open["open_feedback_ids"] = list(reversed(baseline["open_feedback_ids"]))
    with pytest.raises(ValidationError, match="open_feedback_ids must preserve feedback_ids order"):
        EcosystemFeedbackReportV1.model_validate(reordered_open)

    reordered_terminal = baseline.copy()
    reordered_terminal["dispositioned_feedback_ids"] = list(reversed(baseline["dispositioned_feedback_ids"]))
    with pytest.raises(ValidationError, match="dispositioned_feedback_ids must preserve feedback_ids order"):
        EcosystemFeedbackReportV1.model_validate(reordered_terminal)


def test_disposition_is_append_only_and_original_line_bytes_never_change(tmp_path: Path) -> None:
    """Querying and terminal disposition preserve the exact original JSONL bytes."""

    stream = tmp_path / "feedback.jsonl"
    record = _record(stream)
    original_line = stream.read_bytes().splitlines(keepends=True)[0]

    list_ecosystem_feedback(feedback_path=stream)
    report_ecosystem_feedback(feedback_path=stream)
    assert stream.read_bytes() == original_line

    disposition_ecosystem_feedback(
        EcosystemFeedbackDispositionCreateV1(
            feedback_id=record.feedback_id,
            disposition="resolved",
            rationale="A focused test now proves the intended behavior.",
        ),
        feedback_path=stream,
    )

    lines = stream.read_bytes().splitlines(keepends=True)
    assert len(lines) == 2
    assert lines[0] == original_line

    before_rejected_second = stream.read_bytes()
    with pytest.raises(EcosystemFeedbackError, match="already has a terminal disposition"):
        disposition_ecosystem_feedback(
            EcosystemFeedbackDispositionCreateV1(
                feedback_id=record.feedback_id,
                disposition="accepted_risk",
                rationale="A contradictory terminal outcome must not append.",
            ),
            feedback_path=stream,
        )
    assert stream.read_bytes() == before_rejected_second


def _corrupt_malformed() -> bytes:
    return b'{"record_type": "feedback"\n'


def _corrupt_blank_row() -> bytes:
    return _jsonl(_fixed_feedback()) + b"\n"


def _corrupt_unterminated_row() -> bytes:
    return _jsonl(_fixed_feedback()).removesuffix(b"\n")


def _corrupt_non_object() -> bytes:
    return b'["feedback"]\n'


def _corrupt_unknown_record_type() -> bytes:
    return b'{"schema_version":"1.0","record_type":"mystery"}\n'


def _corrupt_schema_invalid() -> bytes:
    payload = _fixed_feedback().model_dump(mode="json")
    payload["observation"] = " "
    return (json.dumps(payload, sort_keys=True) + "\n").encode()


def _corrupt_feedback_missing_schema_version() -> bytes:
    payload = _fixed_feedback().model_dump(mode="json")
    del payload["schema_version"]
    return (json.dumps(payload, sort_keys=True) + "\n").encode()


def _corrupt_feedback_missing_record_type() -> bytes:
    payload = _fixed_feedback().model_dump(mode="json")
    del payload["record_type"]
    return (json.dumps(payload, sort_keys=True) + "\n").encode()


def _corrupt_feedback_missing_status() -> bytes:
    payload = _fixed_feedback().model_dump(mode="json")
    del payload["status"]
    return (json.dumps(payload, sort_keys=True) + "\n").encode()


def _corrupt_disposition_missing_schema_version() -> bytes:
    payload = _fixed_disposition().model_dump(mode="json")
    del payload["schema_version"]
    return _jsonl(_fixed_feedback()) + (json.dumps(payload, sort_keys=True) + "\n").encode()


def _corrupt_disposition_missing_record_type() -> bytes:
    payload = _fixed_disposition().model_dump(mode="json")
    del payload["record_type"]
    return _jsonl(_fixed_feedback()) + (json.dumps(payload, sort_keys=True) + "\n").encode()


def _corrupt_duplicate_feedback_id() -> bytes:
    line = _jsonl(_fixed_feedback())
    return line + line


def _corrupt_orphan_disposition() -> bytes:
    return _jsonl(_fixed_disposition())


def _corrupt_duplicate_disposition_id() -> bytes:
    disposition = _fixed_disposition()
    return _jsonl(_fixed_feedback(), disposition, disposition)


def _corrupt_second_terminal_disposition() -> bytes:
    return _jsonl(
        _fixed_feedback(),
        _fixed_disposition(),
        _fixed_disposition(
            disposition_id=f"ecosystem_feedback_disposition_{'3' * 32}",
            disposition="accepted_risk",
        ),
    )


CORRUPT_STREAMS: tuple[tuple[str, Callable[[], bytes], str], ...] = (
    ("malformed", _corrupt_malformed, "malformed JSONL"),
    ("blank_row", _corrupt_blank_row, "blank feedback row"),
    ("unterminated_row", _corrupt_unterminated_row, "unterminated feedback row"),
    ("non_object", _corrupt_non_object, "not an object"),
    ("unknown_record_type", _corrupt_unknown_record_type, "unknown record_type"),
    ("schema_invalid", _corrupt_schema_invalid, "schema-invalid feedback row"),
    (
        "feedback_missing_schema_version",
        _corrupt_feedback_missing_schema_version,
        "schema-invalid feedback row",
    ),
    ("feedback_missing_record_type", _corrupt_feedback_missing_record_type, "unknown record_type"),
    ("feedback_missing_status", _corrupt_feedback_missing_status, "schema-invalid feedback row"),
    (
        "disposition_missing_schema_version",
        _corrupt_disposition_missing_schema_version,
        "schema-invalid feedback row",
    ),
    ("disposition_missing_record_type", _corrupt_disposition_missing_record_type, "unknown record_type"),
    ("duplicate_feedback", _corrupt_duplicate_feedback_id, "duplicate feedback_id"),
    ("orphan_disposition", _corrupt_orphan_disposition, "unknown prior feedback_id"),
    ("duplicate_disposition", _corrupt_duplicate_disposition_id, "duplicate disposition_id"),
    ("second_terminal", _corrupt_second_terminal_disposition, "multiple terminal dispositions"),
)


@pytest.mark.parametrize(
    ("_name", "corrupt_bytes", "message"), CORRUPT_STREAMS, ids=[row[0] for row in CORRUPT_STREAMS]
)
def test_corrupt_streams_fail_loud_on_read(
    _name: str,
    corrupt_bytes: Callable[[], bytes],
    message: str,
    tmp_path: Path,
) -> None:
    """Every material storage or lifecycle corruption blocks both detail and aggregate reads."""

    stream = tmp_path / "feedback.jsonl"
    stream.write_bytes(corrupt_bytes())

    with pytest.raises(EcosystemFeedbackError, match=message):
        list_ecosystem_feedback(feedback_path=stream)
    with pytest.raises(EcosystemFeedbackError, match=message):
        report_ecosystem_feedback(feedback_path=stream)


@pytest.mark.parametrize(
    ("_name", "corrupt_bytes", "message"), CORRUPT_STREAMS, ids=[row[0] for row in CORRUPT_STREAMS]
)
def test_recording_into_corrupt_stream_rejects_without_changing_bytes(
    _name: str,
    corrupt_bytes: Callable[[], bytes],
    message: str,
    tmp_path: Path,
) -> None:
    """Exclusive append validates the complete prior stream before writing a byte."""

    stream = tmp_path / "feedback.jsonl"
    original = corrupt_bytes()
    stream.write_bytes(original)

    with pytest.raises(EcosystemFeedbackError, match=message):
        record_ecosystem_feedback(_request(), feedback_path=stream)
    assert stream.read_bytes() == original


def test_disposition_rejects_unknown_feedback_without_appending(tmp_path: Path) -> None:
    """A terminal record may reference only an already-persisted feedback ID."""

    stream = tmp_path / "feedback.jsonl"
    original = _jsonl(_fixed_feedback())
    stream.write_bytes(original)

    with pytest.raises(EcosystemFeedbackError, match="unknown feedback_id"):
        disposition_ecosystem_feedback(
            EcosystemFeedbackDispositionCreateV1(
                feedback_id=f"ecosystem_feedback_{'9' * 32}",
                disposition="misrouted",
                rationale="This ID never existed.",
            ),
            feedback_path=stream,
        )
    assert stream.read_bytes() == original


def test_generated_disposition_id_collision_rejects_without_appending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A UUID collision with another record cannot create an ambiguous disposition identity."""

    stream = tmp_path / "feedback.jsonl"
    second_feedback_id = f"ecosystem_feedback_{'4' * 32}"
    original = _jsonl(
        _fixed_feedback(),
        _fixed_feedback(feedback_id=second_feedback_id),
        _fixed_disposition(),
    )
    stream.write_bytes(original)
    monkeypatch.setattr(feedback_impl.uuid, "uuid4", lambda: SimpleNamespace(hex="2" * 32))

    with pytest.raises(EcosystemFeedbackError, match="generated duplicate disposition_id"):
        disposition_ecosystem_feedback(
            EcosystemFeedbackDispositionCreateV1(
                feedback_id=second_feedback_id,
                disposition="resolved",
                rationale="The generated ID collides with a different disposition.",
            ),
            feedback_path=stream,
        )

    assert stream.read_bytes() == original


def test_backward_clock_disposition_rejects_without_appending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal decision cannot predate the feedback even when the wall clock moves backward."""

    stream = tmp_path / "feedback.jsonl"
    original = _jsonl(_fixed_feedback())
    stream.write_bytes(original)

    class BackwardClock:
        @staticmethod
        def now(_timezone: object) -> datetime:
            return datetime(2026, 8, 21, 7, 59, tzinfo=UTC)

    monkeypatch.setattr(feedback_impl, "datetime", BackwardClock)

    with pytest.raises(EcosystemFeedbackError, match="predates its feedback record"):
        disposition_ecosystem_feedback(
            EcosystemFeedbackDispositionCreateV1(
                feedback_id=FIXED_FEEDBACK_ID,
                disposition="resolved",
                rationale="The terminal timestamp is earlier than the original record.",
            ),
            feedback_path=stream,
        )

    assert stream.read_bytes() == original


def test_concurrent_records_all_complete_without_loss_or_corruption(tmp_path: Path) -> None:
    """The file lock serializes competing appends without dropping valid records."""

    stream = tmp_path / "feedback.jsonl"
    worker_count = 24
    barrier = Barrier(worker_count)

    def append(index: int) -> str:
        barrier.wait()
        request = _request(
            observation=f"Concurrent observation {index}",
            evidence_refs=(f"receipt:concurrent-{index}",),
        )
        return record_ecosystem_feedback(request, feedback_path=stream).feedback_id

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        feedback_ids = list(executor.map(append, range(worker_count)))

    views = list_ecosystem_feedback(feedback_path=stream)
    assert len(views) == worker_count
    assert len(set(feedback_ids)) == worker_count
    assert {item.feedback_id for item in views} == set(feedback_ids)
    assert len(stream.read_bytes().splitlines()) == worker_count


def test_concurrent_same_id_dispositions_yield_exactly_one_success(tmp_path: Path) -> None:
    """Exactly one contender can append the sole terminal decision for a feedback ID."""

    stream = tmp_path / "feedback.jsonl"
    record = _record(stream)
    worker_count = 12
    barrier = Barrier(worker_count)

    def append(index: int) -> tuple[bool, str]:
        barrier.wait()
        try:
            disposition = disposition_ecosystem_feedback(
                EcosystemFeedbackDispositionCreateV1(
                    feedback_id=record.feedback_id,
                    disposition="resolved",
                    rationale=f"Concurrent terminal attempt {index}",
                ),
                feedback_path=stream,
            )
        except EcosystemFeedbackError as exc:
            return False, str(exc)
        return True, disposition.disposition_id

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        outcomes = list(executor.map(append, range(worker_count)))

    successes = [detail for success, detail in outcomes if success]
    failures = [detail for success, detail in outcomes if not success]
    assert len(successes) == 1
    assert len(failures) == worker_count - 1
    assert all("already has a terminal disposition" in detail for detail in failures)
    assert len(stream.read_bytes().splitlines()) == 2
    view = list_ecosystem_feedback(feedback_path=stream)[0]
    assert view.status == "resolved"
    assert view.disposition is not None
    assert view.disposition.disposition_id == successes[0]


def _cli_environment(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    isolated_home = tmp_path / "cli-home"
    isolated_home.mkdir(exist_ok=True)
    env.update(
        {
            "HOME": str(isolated_home),
            "XDG_CONFIG_HOME": str(isolated_home / ".config"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join(
                part for part in (DEPENDENCY_SITE_PACKAGES, env.get("PYTHONPATH", "")) if part
            ),
        }
    )
    env.pop("CODEX_THREAD_ID", None)
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    return env


def _run_cli(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *arguments],
        cwd=CLI_PATH.parents[1],
        env=_cli_environment(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )


def _record_cli_arguments(
    stream: Path,
    *,
    scope_kind: str = "skill",
    scope_id: str | None | object = ...,
) -> list[str]:
    actual_scope_id = (None if scope_kind == "general" else f"{scope_kind}:example") if scope_id is ... else scope_id
    arguments = [
        "record",
        "--type",
        "friction",
        "--scope-kind",
        scope_kind,
        "--observation",
        "The CLI observed a planning-to-runtime mismatch.",
        "--expected-behavior",
        "The accepted profile should have one runtime mapping.",
        "--recommendation",
        "Publish the mapping at the planning seam.",
        "--evidence-ref",
        "receipt:cli-observation",
        "--feedback-path",
        str(stream),
    ]
    if actual_scope_id is not None:
        arguments[5:5] = ["--scope-id", str(actual_scope_id)]
    return arguments


@pytest.mark.parametrize("scope_kind", FEEDBACK_SCOPE_KINDS)
def test_cli_records_all_six_scope_kinds_as_json(scope_kind: str, tmp_path: Path) -> None:
    """The one public record command reaches every declared routing kind."""

    stream = tmp_path / f"{scope_kind}.jsonl"
    result = _run_cli(tmp_path, *_record_cli_arguments(stream, scope_kind=scope_kind))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    response = json.loads(result.stdout)
    assert response["feedback_path"] == str(stream.resolve())
    assert response["payload"]["scope_kind"] == scope_kind
    assert (
        response["payload"]["scope_id"] is None
        if scope_kind == "general"
        else (response["payload"]["scope_id"] == f"{scope_kind}:example")
    )
    assert response["payload"]["source"] == {
        "client": "cli",
        "project": None,
        "session_id": None,
        "task_id": None,
        "working_directory": None,
    }
    persisted = json.loads(stream.read_text(encoding="utf-8"))
    assert persisted == response["payload"]


def test_cli_record_list_report_and_disposition_emit_machine_readable_lifecycle_json(tmp_path: Path) -> None:
    """Every CLI operation returns one stable JSON envelope backed by the same stream."""

    stream = tmp_path / "feedback.jsonl"
    record_result = _run_cli(
        tmp_path,
        *_record_cli_arguments(stream, scope_kind="skill", scope_id="bounded-design"),
    )
    assert record_result.returncode == 0, record_result.stderr
    recorded = json.loads(record_result.stdout)
    feedback_id = recorded["payload"]["feedback_id"]

    list_result = _run_cli(
        tmp_path,
        "list",
        "--scope-kind",
        "skill",
        "--status",
        "open",
        "--feedback-path",
        str(stream),
    )
    assert list_result.returncode == 0, list_result.stderr
    listed = json.loads(list_result.stdout)
    assert listed["feedback_path"] == str(stream.resolve())
    assert [item["feedback_id"] for item in listed["payload"]] == [feedback_id]
    assert listed["payload"][0]["status"] == "open"
    assert listed["payload"][0]["disposition"] is None

    report_result = _run_cli(
        tmp_path,
        "report",
        "--type",
        "friction",
        "--scope-id",
        "bounded-design",
        "--feedback-path",
        str(stream),
    )
    assert report_result.returncode == 0, report_result.stderr
    reported = json.loads(report_result.stdout)
    assert reported["payload"]["feedback_count"] == 1
    assert reported["payload"]["open_count"] == 1
    assert reported["payload"]["feedback_ids"] == [feedback_id]
    assert reported["payload"]["open_feedback_ids"] == [feedback_id]

    first_line = stream.read_bytes().splitlines(keepends=True)[0]
    disposition_result = _run_cli(
        tmp_path,
        "disposition",
        "--feedback-id",
        feedback_id,
        "--disposition",
        "resolved",
        "--rationale",
        "The command now preserves the accepted profile mapping.",
        "--successor-ref",
        "commit:cli-fix",
        "--feedback-path",
        str(stream),
    )
    assert disposition_result.returncode == 0, disposition_result.stderr
    dispositioned = json.loads(disposition_result.stdout)
    assert dispositioned["payload"]["feedback_id"] == feedback_id
    assert dispositioned["payload"]["disposition"] == "resolved"
    assert dispositioned["payload"]["successor_ref"] == "commit:cli-fix"
    assert stream.read_bytes().splitlines(keepends=True)[0] == first_line

    final_list = _run_cli(
        tmp_path,
        "list",
        "--status",
        "resolved",
        "--feedback-path",
        str(stream),
    )
    assert final_list.returncode == 0, final_list.stderr
    final_payload = json.loads(final_list.stdout)["payload"]
    assert [item["feedback_id"] for item in final_payload] == [feedback_id]
    assert final_payload[0]["status"] == "resolved"
    assert final_payload[0]["disposition"]["disposition"] == "resolved"

    final_report = _run_cli(
        tmp_path,
        "report",
        "--status",
        "resolved",
        "--feedback-path",
        str(stream),
    )
    assert final_report.returncode == 0, final_report.stderr
    final_report_payload = json.loads(final_report.stdout)["payload"]
    assert final_report_payload["feedback_count"] == 1
    assert final_report_payload["open_count"] == 0
    assert final_report_payload["dispositioned_feedback_ids"] == [feedback_id]


@pytest.mark.parametrize(
    "mutations",
    [
        pytest.param(
            [("--scope-kind", "general"), ("--scope-id", "fabricated")],
            id="general_with_scope_id",
        ),
        pytest.param(
            [("--scope-kind", "policy"), ("--scope-id", None)],
            id="scoped_without_scope_id",
        ),
        pytest.param(
            [("--expected-behavior", None)],
            id="friction_without_expected_behavior",
        ),
        pytest.param(
            [("--observation", "  ")],
            id="empty_observation",
        ),
        pytest.param(
            [("--evidence-ref", " ")],
            id="empty_evidence",
        ),
    ],
)
def test_cli_validation_failure_exits_two_without_stdout_or_stream_mutation(
    mutations: list[tuple[str, str | None]],
    tmp_path: Path,
) -> None:
    """Semantic validation failures cannot emit a success envelope or append partial state."""

    stream = tmp_path / "feedback.jsonl"
    seed = _jsonl(_fixed_feedback())
    stream.write_bytes(seed)
    arguments = _record_cli_arguments(stream)

    def replace_option(option: str, value: str | None) -> None:
        insertion_index = len(arguments)
        if option in arguments:
            insertion_index = arguments.index(option)
            del arguments[insertion_index : insertion_index + 2]
        if value is not None:
            arguments[insertion_index:insertion_index] = [option, value]

    for option, value in mutations:
        replace_option(option, value)

    result = _run_cli(tmp_path, *arguments)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Ecosystem feedback failed:" in result.stderr
    assert stream.read_bytes() == seed


@pytest.mark.parametrize(
    ("_name", "corrupt_bytes", "_message"), CORRUPT_STREAMS, ids=[row[0] for row in CORRUPT_STREAMS]
)
def test_cli_corrupt_stream_failure_exits_two_without_stdout_or_byte_changes(
    _name: str,
    corrupt_bytes: Callable[[], bytes],
    _message: str,
    tmp_path: Path,
) -> None:
    """The public append command inherits full-stream fail-closed behavior."""

    stream = tmp_path / "feedback.jsonl"
    original = corrupt_bytes()
    stream.write_bytes(original)

    result = _run_cli(tmp_path, *_record_cli_arguments(stream))

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Ecosystem feedback failed:" in result.stderr
    assert stream.read_bytes() == original


def test_cli_rejected_second_disposition_preserves_stream_bytes(tmp_path: Path) -> None:
    """The CLI cannot append a second terminal outcome or print success for it."""

    stream = tmp_path / "feedback.jsonl"
    record_result = _run_cli(tmp_path, *_record_cli_arguments(stream))
    assert record_result.returncode == 0, record_result.stderr
    feedback_id = json.loads(record_result.stdout)["payload"]["feedback_id"]
    first = _run_cli(
        tmp_path,
        "disposition",
        "--feedback-id",
        feedback_id,
        "--disposition",
        "resolved",
        "--rationale",
        "The issue is fixed.",
        "--feedback-path",
        str(stream),
    )
    assert first.returncode == 0, first.stderr
    before_second = stream.read_bytes()

    second = _run_cli(
        tmp_path,
        "disposition",
        "--feedback-id",
        feedback_id,
        "--disposition",
        "accepted_risk",
        "--rationale",
        "This contradictory outcome must be rejected.",
        "--feedback-path",
        str(stream),
    )

    assert second.returncode == 2
    assert second.stdout == ""
    assert "already has a terminal disposition" in second.stderr
    assert stream.read_bytes() == before_second
