"""Gate H: CI/deploy rollback rehearsal (offline evidence).

Records current HEAD + workflow fingerprint, writes a marked “bad deploy”
artifact, restores the prior artifact into an isolated folder, and emits
docs/ops-evidence/ci_rollback_rehearsal.json. Never marks Gate H complete.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "ci_rollback_rehearsal.json"


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        return (out.stdout or "").strip() or "unknown"
    except Exception:
        return "unknown"


def _workflow_fingerprint() -> dict:
    rows = {}
    wf = ROOT / ".github" / "workflows"
    if not wf.is_dir():
        return rows
    for path in sorted(wf.glob("*.yml")) + sorted(wf.glob("*.yaml")):
        data = path.read_bytes()
        rows[path.name] = hashlib.sha256(data).hexdigest()[:16]
    return rows


def run_ci_rollback_rehearsal(*, ops_dir: Path | None = None) -> dict:
    base = Path(ops_dir) if ops_dir else ROOT / "artifacts" / "ops"
    base.mkdir(parents=True, exist_ok=True)
    good_dir = base / "rollback_good"
    bad_dir = base / "rollback_bad"
    restore_dir = base / "rollback_restored"
    for d in (good_dir, bad_dir, restore_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    head = _git_head()
    workflows = _workflow_fingerprint()
    good = {
        "kind": "deploy_artifact",
        "revision": head,
        "workflows": workflows,
        "status": "known_good",
    }
    (good_dir / "artifact.json").write_text(json.dumps(good, indent=2), encoding="utf-8")

    bad = {
        "kind": "deploy_artifact",
        "revision": "bad-deploy-marker",
        "workflows": workflows,
        "status": "broken",
        "note": "simulated bad deploy for Gate H rehearsal",
    }
    (bad_dir / "artifact.json").write_text(json.dumps(bad, indent=2), encoding="utf-8")

    # Rollback: restore known-good into isolated folder (do not overwrite live paths).
    shutil.copy2(good_dir / "artifact.json", restore_dir / "artifact.json")
    restored = json.loads((restore_dir / "artifact.json").read_text(encoding="utf-8"))
    ok = restored.get("status") == "known_good" and restored.get("revision") == head

    evidence = {
        "gate_h_complete": False,
        "drill": "ci_rollback_rehearsal",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ok": ok,
        "head": head,
        "workflows": workflows,
        "restored_status": restored.get("status"),
        "reason": (
            "Offline CI/deploy rollback rehearsal restored known-good artifact; "
            "live hosted rollback + paging still open"
            if ok else
            "Rollback rehearsal assertions failed"
        ),
    }
    out = base / "ci_rollback_rehearsal.json"
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
