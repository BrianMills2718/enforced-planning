#!/usr/bin/env python3
"""Migrate relationships.yaml from V1 to V2 format.

V1: couplings with optional soft: true, verify_sync as separate concept
V2: coupling_types (locked/generated/validated), overrides section

Usage:
    python migrate_relationships.py /path/to/relationships.yaml
    python migrate_relationships.py /path/to/relationships.yaml --output v2.yaml
    python migrate_relationships.py /path/to/relationships.yaml --dry-run
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: pyyaml required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


def migrate_v1_to_v2(v1_data: dict) -> dict:
    """Convert a V1 relationships.yaml to V2 format.

    V1 format:
        couplings:
          - sources: [...]
            docs: [...]
            soft: true/false
            verify_sync: "command"

    V2 format:
        version: 2
        coupling_types:
          locked: {action: block, actor: programmatic}
          generated: {action: regenerate, actor: programmatic}
          validated: {action: agent_verify, actor: agent}
        couplings:
          - sources: [...]
            docs: [...]
            type: locked|generated|validated
            regenerate_cmd: "..." (for generated type)
        overrides: {}
    """
    v2: dict = {
        "version": 2,
        "coupling_types": {
            "locked": {
                "action": "block",
                "description": "Commit blocked until coupled doc also updated",
                "actor": "programmatic",
            },
            "generated": {
                "action": "regenerate",
                "description": "Regeneration command runs automatically when source changes",
                "actor": "programmatic",
            },
            "validated": {
                "action": "agent_verify",
                "description": "Agent checks if doc is actually stale; fixes or escalates",
                "actor": "agent",
            },
        },
    }

    # Migrate required_reading (pass through)
    if "required_reading" in v1_data:
        v2["required_reading"] = v1_data["required_reading"]

    # Migrate ADRs (pass through)
    if "adrs" in v1_data:
        v2["adrs"] = v1_data["adrs"]

    # Migrate governance edges (pass through, add type)
    if "governance" in v1_data:
        v2["governance"] = []
        for edge in v1_data["governance"]:
            new_edge = dict(edge)
            if "type" not in new_edge:
                new_edge["type"] = "locked"
            v2["governance"].append(new_edge)

    # Migrate couplings — the main transformation
    if "couplings" in v1_data:
        v2["couplings"] = []
        for coupling in v1_data["couplings"]:
            new_coupling = {
                "sources": coupling.get("sources", []),
                "docs": coupling.get("docs", []),
            }

            # Determine type from V1 fields
            if coupling.get("verify_sync"):
                new_coupling["type"] = "generated"
                new_coupling["regenerate_cmd"] = coupling["verify_sync"]
            elif coupling.get("soft"):
                new_coupling["type"] = "validated"
            else:
                new_coupling["type"] = "locked"

            # Preserve description
            if "description" in coupling:
                new_coupling["description"] = coupling["description"]

            v2["couplings"].append(new_coupling)

    # Migrate architecture edges (pass through, add type)
    if "architecture" in v1_data:
        v2["architecture"] = []
        for edge in v1_data["architecture"]:
            new_edge = dict(edge)
            if "type" not in new_edge:
                new_edge["type"] = "locked"
            v2["architecture"].append(new_edge)

    # Migrate capability_surfaces (pass through)
    if "capability_surfaces" in v1_data:
        v2["capability_surfaces"] = v1_data["capability_surfaces"]

    # Migrate notebook_links (pass through)
    if "notebook_links" in v1_data:
        v2["notebook_links"] = v1_data["notebook_links"]

    # Migrate verify_sync as generated couplings
    if "verify_sync" in v1_data:
        if "couplings" not in v2:
            v2["couplings"] = []
        for entry in v1_data["verify_sync"]:
            v2["couplings"].append({
                "sources": entry.get("sources", entry.get("docs", [])),
                "docs": entry.get("docs", []),
                "type": "generated",
                "regenerate_cmd": entry.get("command", ""),
                "description": entry.get("description", "Auto-verified sync"),
            })

    # Migrate file_scope (pass through)
    if "file_scope" in v1_data:
        v2["file_scope"] = v1_data["file_scope"]

    # Add empty overrides section
    v2["overrides"] = {}

    return v2


def format_v2_yaml(v2_data: dict) -> str:
    """Format V2 data as readable YAML."""
    return yaml.dump(v2_data, default_flow_style=False, sort_keys=False, width=120)


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(description="Migrate relationships.yaml V1 → V2")
    parser.add_argument("input", type=Path, help="Input relationships.yaml (V1)")
    parser.add_argument("--output", "-o", type=Path, help="Output file (default: stdout)")
    parser.add_argument("--dry-run", action="store_true", help="Show diff without writing")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: {args.input} not found", file=sys.stderr)
        sys.exit(1)

    with open(args.input) as f:
        v1_data = yaml.safe_load(f)

    if not isinstance(v1_data, dict):
        print(f"Error: {args.input} is not a valid YAML mapping", file=sys.stderr)
        sys.exit(1)

    # Check if already V2
    if v1_data.get("version") == 2:
        print(f"{args.input} is already V2 format")
        return

    v2_data = migrate_v1_to_v2(v1_data)
    v2_yaml = format_v2_yaml(v2_data)

    if args.dry_run:
        print("=== V2 Output (dry run) ===")
        print(v2_yaml)
        v1_couplings = len(v1_data.get("couplings", []))
        v2_couplings = len(v2_data.get("couplings", []))
        locked = sum(1 for c in v2_data.get("couplings", []) if c.get("type") == "locked")
        generated = sum(1 for c in v2_data.get("couplings", []) if c.get("type") == "generated")
        validated = sum(1 for c in v2_data.get("couplings", []) if c.get("type") == "validated")
        print(f"\nMigration summary: {v1_couplings} V1 couplings → {v2_couplings} V2 couplings")
        print(f"  locked: {locked}, generated: {generated}, validated: {validated}")
    elif args.output:
        with open(args.output, "w") as f:
            f.write(v2_yaml)
        print(f"Wrote V2 to {args.output}")
    else:
        print(v2_yaml)


if __name__ == "__main__":
    main()
