#!/usr/bin/env python3
"""Print the effective governed-project profile as JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for candidate in Path(__file__).resolve().parents:
    if (candidate / "enforced_planning").is_dir():
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
        break
else:
    raise RuntimeError("unable to locate repository root containing enforced_planning")

from enforced_planning.effective_project_profile import load_effective_project_profile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    profile = load_effective_project_profile(args.repo_root.expanduser().resolve())
    print(json.dumps(profile.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
