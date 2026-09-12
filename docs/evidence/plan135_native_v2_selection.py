#!/usr/bin/env python3
"""Reproduce Plan 135's blind native-v2 source selection without reading prose."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enforced_planning.correction_learning import extract_transcript_exchanges

START = datetime.fromisoformat("2026-09-07T00:00:00Z")
END = datetime.fromisoformat("2026-09-12T01:42:13Z")
SEED = "plan135-native-v2"
EXCLUDED_SESSIONS = {
    "01a09111-50bc-7b21-944b-1e597e6247ce",
    "01a09110-c715-7ed0-a135-25a865bf23c8",
    "01a09155-5a13-7f33-a090-d61f15137995",
    "195b3b11-f476-4b26-9568-d35045d13e98",
    "651515e8-1107-47c1-9215-3bbb570f97a6",
    "4a9d56fb-8247-46be-9401-dafe7a795dab",
    "8ac28193-5093-41e7-adde-c897290fa563",
    "b20e2ff1-e776-4b25-ac1b-d6c45dc9b286",
}


def _session_id(path: Path, agent: str) -> str:
    if agent == "claude-code":
        return path.stem
    return "-".join(path.stem.split("-")[-5:])


def _paths(home: Path) -> dict[str, list[Path]]:
    codex: list[Path] = []
    for day in ("07", "08", "09", "10", "11"):
        codex.extend((home / ".codex/sessions/2026/09" / day).glob("*.jsonl"))
    claude: list[Path] = []
    for path in (home / ".claude/projects").glob("*/*.jsonl"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size <= 20_000_000 and stat.st_mtime >= START.timestamp():
            claude.append(path)
    return {"codex": codex, "claude-code": claude}


def _ranked(home: Path, agent: str, paths: list[Path]):
    eligible = []
    for path in sorted(paths)[:5000]:
        session_id = _session_id(path, agent)
        if session_id in EXCLUDED_SESSIONS:
            continue
        try:
            exchanges = [
                exchange
                for exchange in extract_transcript_exchanges(path, agent=agent)
                if START <= exchange.occurred_at <= END
            ]
        except Exception:  # noqa: BLE001, S112 - deterministic ineligibility
            continue
        if len(exchanges) < 4:
            continue
        relative = path.relative_to(home)
        score = hashlib.sha256(f"{SEED}|{agent}|{relative}".encode()).hexdigest()
        eligible.append((score, path, session_id, exchanges))
    return sorted(eligible)


def _wave(home: Path, start_rank: int, end_rank: int) -> dict[str, object]:
    selected = []
    for agent, paths in _paths(home).items():
        for score, path, session_id, exchanges in _ranked(home, agent, paths)[
            start_rank:end_rank
        ]:
            offset = int(score[-8:], 16) % (len(exchanges) - 3)
            window = exchanges[offset : offset + 4]
            selected.append(
                {
                    "agent": agent,
                    "session_id": session_id,
                    "source_path": str(path.relative_to(home)),
                    "window_start": window[0].occurred_at.isoformat().replace("+00:00", "Z"),
                    "window_end": window[-1].occurred_at.isoformat().replace("+00:00", "Z"),
                    "events": [
                        {
                            "event_id": exchange.event_id,
                            "event_hash": exchange.event_hash,
                            "occurred_at": exchange.occurred_at.isoformat().replace(
                                "+00:00", "Z"
                            ),
                        }
                        for exchange in window
                    ],
                }
            )
    payload: dict[str, object] = {
        "schema_version": "candidate/1.0",
        "seed": SEED,
        "development_revision": "f5680f700c4a",
        "population_start": START.isoformat().replace("+00:00", "Z"),
        "population_end": END.isoformat().replace("+00:00", "Z"),
        "sources": selected,
    }
    if start_rank:
        payload["rank_window"] = f"{start_rank}:{end_rank}"
    return payload


def _serialized(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def main() -> int:
    home = Path.home()
    checks = [
        (0, 8, ROOT / "docs/evidence/plan135_native_v2_candidates.json"),
        (8, 16, ROOT / "docs/evidence/plan135_native_v2_extension1_candidates.json"),
    ]
    for start_rank, end_rank, expected in checks:
        actual = _serialized(_wave(home, start_rank, end_rank))
        expected_bytes = expected.read_bytes()
        if actual != expected_bytes:
            raise SystemExit(f"selection mismatch: {expected.name}")
        print(f"PASS {expected.name} {hashlib.sha256(actual).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
