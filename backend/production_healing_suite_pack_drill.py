"""Gate E: production healing suite pack (local fixtures, not third-party).

Bundles readiness score, flaky policy, replay pack, multi-app suite, and
taxonomy. Does **not** run a production / third-party suite —
``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_suite_pack_drill.json"


def run_production_healing_suite_pack_drill(*, ops_dir: Path | None = None) -> dict:
    from .multi_app_healing_suite_drill import run_multi_app_healing_suite_drill
    from .production_healing_flaky_policy_drill import (
        run_production_healing_flaky_policy_drill,
    )
    from .production_healing_readiness_drill import (
        run_production_healing_readiness_drill,
    )
    from .production_healing_replay_pack_drill import (
        run_production_healing_replay_pack_drill,
    )
    from .production_healing_taxonomy_drill import (
        run_production_healing_taxonomy_drill,
    )

    started = time.perf_counter()
    parts = {}
    for key, fn in (
        ("readiness", run_production_healing_readiness_drill),
        ("flaky_policy", run_production_healing_flaky_policy_drill),
        ("replay_pack", run_production_healing_replay_pack_drill),
        ("taxonomy", run_production_healing_taxonomy_drill),
        ("multi_app", run_multi_app_healing_suite_drill),
    ):
        try:
            parts[key] = fn(ops_dir=ops_dir)
        except Exception as exc:
            parts[key] = {"ok": False, "reason": str(exc)[:160]}
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    ok = all(bool((parts.get(k) or {}).get("ok")) for k in parts)
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_suite_pack",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "local_ops_pack",
        "parts": {k: bool((v or {}).get("ok")) for k, v in parts.items()},
        "production_suite_executed": False,
        "elapsed_ms": elapsed_ms,
        "ok": ok,
        "reason": (
            f"Production healing suite pack ok in {elapsed_ms}ms; "
            "production / third-party healing suite still open"
            if ok else
            "Production healing suite pack incomplete; production suite still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "production_healing_suite_pack_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "production_healing_suite_pack_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
