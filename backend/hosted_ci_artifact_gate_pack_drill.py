"""Gates D/F: hosted CI artifact gate pack (readiness + dispatch + upload).

Bundles runner readiness, dispatch payload rehearsal, and upload rehearsal.
Does **not** execute hosted runners — ``gate_d_complete`` / ``gate_f_complete``
stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_ci_artifact_gate_pack_drill.json"


def _linked_gate() -> dict:
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "ok": False,
        "drill": "hosted_ci_artifact_gate_pack",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_hosted_ci_artifact_gate_pack_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "hosted_ci_artifact_gate_pack_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_gate()

    from .ci_artifact_upload_rehearsal_drill import (
        run_ci_artifact_upload_rehearsal_drill,
    )
    from .hosted_dispatch_payload_rehearsal_drill import (
        run_hosted_dispatch_payload_rehearsal_drill,
    )
    from .hosted_runner_readiness_drill import run_hosted_runner_readiness_drill

    started = time.perf_counter()
    parts = {}
    for key, fn in (
        ("runner_readiness", run_hosted_runner_readiness_drill),
        ("dispatch_payload", run_hosted_dispatch_payload_rehearsal_drill),
        ("upload_rehearsal", run_ci_artifact_upload_rehearsal_drill),
    ):
        try:
            parts[key] = fn(ops_dir=ops_dir)
        except Exception as exc:
            parts[key] = {"ok": False, "reason": str(exc)[:160]}
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    ok = all(bool((parts.get(k) or {}).get("ok")) for k in parts)
    evidence = {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "hosted_ci_artifact_gate_pack",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "local_ops_pack",
        "parts": {k: bool((v or {}).get("ok")) for k, v in parts.items()},
        "live_hosted_runners": False,
        "elapsed_ms": elapsed_ms,
        "ok": ok,
        "reason": (
            f"Hosted CI artifact gate pack ok in {elapsed_ms}ms; "
            "broad hosted multi-device/browser runners still open"
            if ok else
            "Hosted CI artifact gate pack incomplete; hosted runners still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_gate()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_gate()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
