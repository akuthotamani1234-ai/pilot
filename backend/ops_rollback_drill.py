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
OPS_DIR = ROOT / "artifacts" / "ops"


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
    from .finalization import folder_is_linked
    rows = {}
    wf = ROOT / ".github" / "workflows"
    if folder_is_linked(wf) or not wf.is_dir():
        return rows
    for path in sorted(wf.glob("*.yml")) + sorted(wf.glob("*.yaml")):
        if folder_is_linked(path) or not path.is_file():
            continue
        data = path.read_bytes()
        rows[path.name] = hashlib.sha256(data).hexdigest()[:16]
    return rows


def _ops_folder(ops_dir: Path | None) -> Path | None:
    """This rehearsal's folder. A link is not this install's evidence folder."""
    from .finalization import folder_is_linked
    base = Path(ops_dir) if ops_dir is not None else OPS_DIR
    if folder_is_linked(base):
        return None
    return base


def _linked_rehearsal() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "ci_rollback_rehearsal",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def _write_json(folder: Path, name: str, payload: dict) -> bool:
    from .finalization import write_text_unless_linked
    return write_text_unless_linked(folder, name, json.dumps(payload, indent=2))


def run_ci_rollback_rehearsal(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked
    base = _ops_folder(ops_dir)
    if base is None:
        return _linked_rehearsal()
    base.mkdir(parents=True, exist_ok=True)
    good_dir = base / "rollback_good"
    bad_dir = base / "rollback_bad"
    restore_dir = base / "rollback_restored"
    evidence_path = base / "ci_rollback_rehearsal.json"
    if any(folder_is_linked(path) for path in (good_dir, bad_dir, restore_dir, evidence_path)):
        return _linked_rehearsal()
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
    if not _write_json(good_dir, "artifact.json", good):
        return _linked_rehearsal()

    bad = {
        "kind": "deploy_artifact",
        "revision": "bad-deploy-marker",
        "workflows": workflows,
        "status": "broken",
        "note": "simulated bad deploy for Gate H rehearsal",
    }
    if not _write_json(bad_dir, "artifact.json", bad):
        return _linked_rehearsal()

    # Rollback: restore known-good into isolated folder (do not overwrite live paths).
    restored_path = restore_dir / "artifact.json"
    if folder_is_linked(restored_path):
        return _linked_rehearsal()
    shutil.copy2(good_dir / "artifact.json", restored_path)
    if folder_is_linked(restored_path):
        return _linked_rehearsal()
    restored = json.loads(restored_path.read_text(encoding="utf-8"))
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
    if not _write_json(base, "ci_rollback_rehearsal.json", evidence):
        return _linked_rehearsal()
    if ops_dir is None and not folder_is_linked(EVIDENCE) and not folder_is_linked(EVIDENCE.parent):
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        _write_json(EVIDENCE.parent, EVIDENCE.name, evidence)
    return evidence
