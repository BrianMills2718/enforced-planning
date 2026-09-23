# UI surface routing

`registry.yaml` is the repository's UI inventory authority. Read it before
planning, creating, replacing, or retiring a human-facing surface.

- `ui_status: none` means the repository has no current UI; register a
  `candidate` surface before implementation.
- Patch the registered canonical surface by default.
- Record framework-native source locations rather than creating a duplicate.
- Put new UI source in `ui/src/`, tests in `tests/ui/`, and generated output in
  `generated/ui/` unless the registry declares a reviewed exception.
- Use the shared `/ui` skill for continuity, implementation, and browser
  verification procedure.
