"""Task-local verification of the existing host gate; no host claim mutation."""
import hashlib
import importlib.util
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
pytest = importlib.import_module("pytest")
claim_mutation_receipts = importlib.import_module("enforced_planning.claim_mutation_receipts")
write_projection = importlib.import_module("enforced_planning.prewrite_claim_projection").write_projection

spec = importlib.util.spec_from_file_location("ep629_fixture", root / "tests/test_session_cli.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
scratch = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix="ep629-host-probe-", dir=scratch) as temporary:
    tmp = Path(temporary)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(claim_mutation_receipts, "DEFAULT_EVENTS_PATH", tmp / "events.jsonl")
        monkeypatch.setattr(claim_mutation_receipts, "DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH", tmp / "archive.jsonl")
        repo, claim, tracker, environment, owner = fixture._active_canonical_environment_lane(tmp, monkeypatch)
        write_projection(claims_dir=claim.parent, projection_path=tmp / "projection.json")
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (claim, tracker, environment)}
        argv = ["/usr/bin/python3", str(root / "scripts/session_close.py"),
                "--agent", "codex", "--project", "environment-consumer", "--scope", "verify-existing-env",
                "--repo-root", str(repo), "--retain-canonical-environment",
                "--claim-sha256", before[str(claim)], "--tracker-sha256", before[str(tracker)], "--json"]
        for native, expected in [(owner, "allow"), ("codex:foreign-environment-owner", "deny")]:
            payload = {"hook_event_name": "PreToolUse", "cwd": str(repo), "session_id": native, "tool_name": "Bash",
                       "tool_input": {"command": shlex.join(argv)}}
            result = subprocess.run([
                "/usr/bin/python3", str(root / "scripts/prewrite_claim_gate.py"), "--client", "codex",
                "--mode", "enforce", "--claims-dir", str(claim.parent),
                "--projection-path", str(tmp / "projection.json"), "--receipt-path", str(tmp / "receipts.jsonl"),
                "--outcome-receipt-path", str(tmp / "outcome-receipts.jsonl"), "--json"],
                input=json.dumps(payload), text=True, capture_output=True, cwd=root, check=False)
            print(json.dumps({"root": str(root), "native": native, "command": argv,
                              "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}), flush=True)
            decision = json.loads(result.stdout)
            assert decision["decision"] == expected, decision
            assert result.returncode == (0 if expected == "allow" else 2), result
            if expected == "allow":
                assert decision["reason_code"] == "native_closeout_command", decision
            assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in before.items())
print("RESULT host-admission probes: 2 passed, 0 failed, 0 skipped; exit=0", flush=True)
