from __future__ import annotations

import json
from pathlib import Path

import pytest

from enforced_planning.data_contract_snapshot import (
    BOUNDARY_NAME,
    DEFAULT_SNAPSHOT_PATH,
    SnapshotDriftError,
    build_contract_snapshot,
    check_contract_snapshot,
    main,
    render_contract_snapshot,
    write_contract_snapshot,
)
from enforced_planning.planning_handoff import RoadmapGoalHandoff


def test_committed_snapshot_matches_model() -> None:
    check_contract_snapshot()

    payload = json.loads(DEFAULT_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    contract = payload["contracts"][0]
    assert payload["schema_version"] == "contract-snapshot-v1"
    assert contract["name"] == BOUNDARY_NAME
    assert contract["producer"] == "enforced-planning"
    assert contract["consumers"] == ["company-planning"]
    assert contract["output_schema"] == RoadmapGoalHandoff.model_json_schema()


def test_snapshot_render_is_deterministic_and_portable() -> None:
    first = render_contract_snapshot()
    second = render_contract_snapshot()

    assert first == second
    rendered = first.decode("utf-8")
    assert str(Path.home()) not in rendered
    for runtime_field in ("first_registered", "call_count", "error_count", "updated_at"):
        assert runtime_field not in rendered


def test_build_snapshot_returns_fresh_data() -> None:
    first = build_contract_snapshot()
    first["contracts"][0]["consumers"].append("mutation")

    second = build_contract_snapshot()

    assert second["contracts"][0]["consumers"] == ["company-planning"]


def test_check_fails_for_stale_snapshot(tmp_path: Path) -> None:
    stale = tmp_path / "snapshot.json"
    stale.write_text("{}\n", encoding="utf-8")

    with pytest.raises(SnapshotDriftError, match=f"stale: {stale}"):
        check_contract_snapshot(stale)


def test_write_refreshes_stale_snapshot(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"

    write_contract_snapshot(snapshot)

    assert snapshot.read_bytes() == render_contract_snapshot()
    check_contract_snapshot(snapshot)


def test_cli_returns_nonzero_for_stale_snapshot(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stale = tmp_path / "snapshot.json"
    stale.write_text("{}\n", encoding="utf-8")

    assert main(["--check", "--path", str(stale)]) == 1
    assert str(stale) in capsys.readouterr().out
