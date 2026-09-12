#!/usr/bin/env python3
"""Select or reproduce Plan 135's unseen native-v4 source windows."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enforced_planning.correction_learning import extract_transcript_exchanges

START = datetime.fromisoformat("2026-08-31T00:00:00Z")
END = datetime.fromisoformat("2026-09-07T00:00:00Z")
SEED = "plan135-native-v4"
PER_AGENT = 16
OUTPUT = ROOT / "docs/evidence/plan135_native_v4_candidates.json"


def _session_id(path: Path, agent: str) -> str:
    if agent == "claude-code":
        return path.stem
    return "-".join(path.stem.split("-")[-5:])


def _paths(home: Path) -> dict[str, list[Path]]:
    codex: list[Path] = []
    for month, days in (("08", ("31",)), ("09", ("01", "02", "03", "04", "05", "06"))):
        for day in days:
            codex.extend((home / ".codex/sessions/2026" / month / day).glob("*.jsonl"))
    claude = [
        path
        for path in (home / ".claude/projects").glob("*/*.jsonl")
        if path.stat().st_size <= 20_000_000
    ]
    return {"codex": codex, "claude-code": claude}


def _selected(home: Path, agent: str, paths: list[Path]):
    eligible = []
    for path in sorted(paths)[:5000]:
        try:
            exchanges = [
                exchange
                for exchange in extract_transcript_exchanges(path, agent=agent)
                if START <= exchange.occurred_at < END
            ]
        except Exception:  # noqa: BLE001, S112 - deterministic ineligibility
            continue
        if len(exchanges) < 4:
            continue
        relative = path.relative_to(home)
        score = hashlib.sha256(f"{SEED}|{agent}|{relative}".encode()).hexdigest()
        eligible.append((score, path, _session_id(path, agent), exchanges))
    if len(eligible) < PER_AGENT:
        raise RuntimeError(f"only {len(eligible)} eligible {agent} sessions")
    return sorted(eligible)[:PER_AGENT]


def build(home: Path, development_revision: str) -> dict[str, object]:
    sources = []
    for agent, paths in _paths(home).items():
        for score, path, session_id, exchanges in _selected(home, agent, paths):
            offset = int(score[-8:], 16) % (len(exchanges) - 3)
            window = exchanges[offset : offset + 4]
            sources.append(
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
                            "occurred_at": exchange.occurred_at.isoformat().replace("+00:00", "Z"),
                        }
                        for exchange in window
                    ],
                }
            )
    return {
        "schema_version": "candidate/1.0",
        "seed": SEED,
        "development_revision": development_revision,
        "population_start": START.isoformat().replace("+00:00", "Z"),
        "population_end": END.isoformat().replace("+00:00", "Z"),
        "sources": sources,
    }


def _serialized(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-revision", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    actual = _serialized(build(Path.home(), args.development_revision))
    if args.write:
        OUTPUT.write_bytes(actual)
    elif actual != OUTPUT.read_bytes():
        raise SystemExit("selection mismatch: plan135_native_v4_candidates.json")
    print(f"PASS {OUTPUT.name} {hashlib.sha256(actual).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
