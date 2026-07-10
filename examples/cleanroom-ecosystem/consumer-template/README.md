# Neutral consumer template

Copy `consumer.json` outside the source repository, edit the instance identity,
component source, policy-pack name, and project inventory, then pass it to the
clean-room CLI with `--consumer-config`.

The file intentionally contains no home-directory paths, credentials, or
maintainer project names. Project paths are relative to the generated root.

For non-demo project ids the alpha materializes deterministic placeholder
projects with a `Makefile` verification interface. Replacing those placeholders
with real source/build adapters remains consumer-owned integration work.
