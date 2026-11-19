"""Gate G: independent review handoff pack (request + sign-off + attestation).

Bundles reviewer handoff artifacts into one unsigned pack. Does **not** collect
a human signature — ``signed_off`` / ``gate_g_complete`` stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "independent_review_handoff_pack_drill.json"


def run_independent_review_handoff_pack_drill(*, ops_dir: Path | None = None) -> dict:
    from .independent_review_blocker_freeze_drill import (
        run_independent_review_blocker_freeze_drill,
    )
    from .independent_review_request_drill import run_independent_review_request_drill
    from .independent_review_scope_matrix_drill import (
        run_independent_review_scope_matrix_drill,
    )
    from .independent_review_signoff_pack_drill import (
        run_independent_review_signoff_pack_drill,
    )
    from .independent_review_summary_drill import run_independent_review_summary_drill

    started = time.perf_counter()
    parts = {}
    for key, fn in (
        ("request", run_independent_review_request_drill),
        ("signoff_pack", run_independent_review_signoff_pack_drill),
        ("summary", run_independent_review_summary_drill),
        ("scope_matrix", run_independent_review_scope_matrix_drill),
        ("blocker_freeze", run_independent_review_blocker_freeze_drill),
    ):
        try:
            parts[key] = fn(ops_dir=ops_dir)
        except Exception as exc:
            parts[key] = {"ok": False, "reason": str(exc)[:160]}
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    signed_off = any(bool((parts.get(k) or {}).get("signed_off")) for k in parts)
    ok = all(bool((parts.get(k) or {}).get("ok")) for k in parts) and not signed_off
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_handoff_pack",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "unsigned_ops_pack",
        "parts": {k: bool((v or {}).get("ok")) for k, v in parts.items()},
        "signed_off": signed_off,
        "elapsed_ms": elapsed_ms,
        "ok": ok,
        "reason": (
            f"Independent review handoff pack ok in {elapsed_ms}ms (unsigned); "
            "external sign-off still open"
            if ok else
            "Independent review handoff pack incomplete; sign-off still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "independent_review_handoff_pack_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "independent_review_handoff_pack_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
