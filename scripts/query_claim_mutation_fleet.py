#!/usr/bin/env python3
"""Report writer provenance for the current live coordination-claim fleet."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning import claim_mutation_receipts, coordination_claims  # noqa: E402
from enforced_planning.prewrite_claim_fast import DEFAULT_CLAIMS_DIR  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims-dir", type=Path, default=DEFAULT_CLAIMS_DIR)
    parser.add_argument("--events-path", type=Path, default=claim_mutation_receipts.DEFAULT_EVENTS_PATH)
    parser.add_argument("--output", type=Path, help="Write the JSON report to this path atomically.")
    parser.add_argument("--json", action="store_true", help="Print the complete JSON report.")
    return parser


def _claim_identity(claim: coordination_claims.ClaimRecord) -> dict[str, str | None]:
    return {
        "project": claim.primary_project(),
        "scope": claim.scope,
        "session_id": claim.session_id,
        "claim_path": str(Path(claim.source_file or "").expanduser().resolve()),
    }


def _receipt_sort_key(receipt: claim_mutation_receipts.ClaimMutationReceiptV1) -> datetime:
    return receipt.observed_at


def build_report(*, claims_dir: Path, events_path: Path) -> dict[str, Any]:
    """Classify each live claim from exact claim-path receipt evidence only."""

    resolved_claims_dir = claims_dir.expanduser().resolve()
    receipts = claim_mutation_receipts.load_receipts(events_path=events_path)
    receipts_by_path: dict[str, list[claim_mutation_receipts.ClaimMutationReceiptV1]] = {}
    for receipt in receipts:
        if not receipt.target_claim_path or receipt.result == "not_applied":
            continue
        receipt_path = str(Path(receipt.target_claim_path).expanduser().resolve())
        receipts_by_path.setdefault(receipt_path, []).append(receipt)

    groups: dict[str, dict[str, Any]] = {}
    legacy: list[dict[str, str | None]] = []
    for claim in coordination_claims.check_claims(claims_dir=resolved_claims_dir):
        identity = _claim_identity(claim)
        matching = receipts_by_path.get(identity["claim_path"] or "", [])
        # A receipt predating this claim incarnation cannot prove the live
        # mutation. Claims without a parseable creation time fail closed.
        if claim.claimed_at:
            matching = [
                receipt
                for receipt in matching
                if receipt.observed_at.isoformat() >= claim.claimed_at
            ]
        if not matching:
            legacy.append(identity)
            continue
        latest = max(matching, key=_receipt_sort_key)
        group = groups.setdefault(
            latest.writer_source_sha256,
            {
                "writer_source_sha256": latest.writer_source_sha256,
                "writer_source_path": latest.writer_source_path,
                "writer_repo_root": latest.writer_repo_root,
                "live_claims": [],
            },
        )
        group["live_claims"].append(
            {
                **identity,
                "latest_event_id": latest.event_id,
                "latest_operation": latest.operation,
                "latest_result": latest.result,
                "registry_digest_after": latest.registry_digest_after,
                "projection_digest_after": latest.projection_digest_after,
                "projection_current_after": latest.projection_current_after,
            }
        )

    return {
        "schema_version": "1.0",
        "observed_at": datetime.now().astimezone().isoformat(),
        "claims_dir": str(resolved_claims_dir),
        "events_path": str(events_path.expanduser().resolve()),
        "live_writer_groups": sorted(groups.values(), key=lambda group: group["writer_source_sha256"]),
        "unclassified_legacy": sorted(
            legacy,
            key=lambda item: (item["project"] or "", item["scope"] or "", item["claim_path"] or ""),
        ),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = build_report(claims_dir=args.claims_dir, events_path=args.events_path)
        if args.output:
            _write_json(args.output.expanduser().resolve(), report)
    except (OSError, ValueError) as exc:
        print(f"claim mutation fleet query failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "Claim mutation fleet: "
            f"writer_groups={len(report['live_writer_groups'])} "
            f"unclassified_legacy={len(report['unclassified_legacy'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
