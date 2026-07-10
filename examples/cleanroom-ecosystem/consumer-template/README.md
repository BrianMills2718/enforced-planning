# Neutral consumer template

Copy `consumer.json` outside the source repository, edit the instance identity,
component source, policy-pack name, and project inventory, then pass it to the
clean-room CLI with `--consumer-config`.

The file intentionally contains no home-directory paths, credentials, or
maintainer project names. Project paths are relative to the generated root.

This is a configuration example, not a project migration tool: arbitrary build
systems and project materialization remain consumer-owned adapter work.
