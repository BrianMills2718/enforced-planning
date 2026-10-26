"""Shared test setup."""

import os
import sys
from pathlib import Path

# `make check` runs pytest inside make, so MAKELEVEL/MAKEFLAGS leak into the
# environment and every `make` a test spawns prints "make[1]: Entering directory"
# around its output, which breaks tests that parse that output as JSON.
for _name in ("MAKELEVEL", "MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES"):
    os.environ.pop(_name, None)

# PyYAML and pydantic are runtime dependencies, so a fresh clone installs them
# into .venv and nowhere else. `make check` runs pytest as .venv/bin/python but
# that does not put .venv/bin on PATH, so any `python3` a test subprocess
# resolves -- including the one enforced_planning.hook_wiring probes for a
# target repo with no .venv of its own -- was the bare system interpreter, with
# none of this project's dependencies. On the nightly worker image that failed
# 140 tests. Tests that spawn our scripts directly pass sys.executable; this
# covers the ones where production code picks the interpreter off PATH.
_bin = Path(sys.executable).parent
if (_bin / "python3").exists():
    _path = os.environ.get("PATH", "")
    if str(_bin) not in _path.split(os.pathsep):
        os.environ["PATH"] = os.pathsep.join([str(_bin), _path]) if _path else str(_bin)
