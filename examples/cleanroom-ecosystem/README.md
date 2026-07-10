# Clean-Room Ecosystem Example

This directory is the canonical source location for the generated clean-room
alpha fixture. Slice 1 currently implements the fixture in
`enforced_planning.cleanroom_alpha`; this directory anchors the future template
surface so the generated external instance does not become source authority.

Use the CLI from the repository root:

```bash
python scripts/cleanroom_alpha.py --root /tmp/loop-engineering-cleanroom plan
python scripts/cleanroom_alpha.py --root /tmp/loop-engineering-cleanroom apply
python scripts/cleanroom_alpha.py --root /tmp/loop-engineering-cleanroom verify
python scripts/cleanroom_alpha.py --root /tmp/loop-engineering-cleanroom reset
```
