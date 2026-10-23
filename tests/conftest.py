"""Shared test setup."""

import os

# `make check` runs pytest inside make, so MAKELEVEL/MAKEFLAGS leak into the
# environment and every `make` a test spawns prints "make[1]: Entering directory"
# around its output, which breaks tests that parse that output as JSON.
for _name in ("MAKELEVEL", "MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES"):
    os.environ.pop(_name, None)
