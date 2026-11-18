"""Gate G: tenant-scoped audit export contract drill.

Exercises record_audit + export_audits isolation offline. Studio SSO /
independent review still open — gate_g_complete stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .audit_store import export_audits, record_audit

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "audit_export_drill.json"


def run_audit_export_drill(*, ops_dir: Path | None = None) -> dict:
    work = Path(ops_dir) / "audit_export_work" if ops_dir else (
        ROOT / "artifacts" / "ops" / "audit_export_work"
    )
    work.mkdir(parents=True, exist_ok=True)
    db = work / "audit.sqlite"

    record_audit(actor="alice", action="run.read", allowed=True, tenant_id="t-a",
                 detail="scoped-allow", db_path=db)
    record_audit(actor="alice", action="run.write", allowed=False, tenant_id="t-a",
                 detail="scoped-deny", db_path=db)
    record_audit(actor="bob", action="run.read", allowed=True, tenant_id="t-b",
                 detail="other-tenant", db_path=db)

    scoped = export_audits(tenant_id="t-a", db_path=db)
    other = export_audits(tenant_id="t-b", db_path=db)
    unknown = export_audits(tenant_id="t-missing", db_path=db)
    unscoped = export_audits(db_path=db)

    scoped_actors = sorted({e.get("actor") for e in (scoped.get("events") or [])})
    scoped_tenants = sorted({e.get("tenant_id") for e in (scoped.get("events") or [])})
    other_tenants = sorted({e.get("tenant_id") for e in (other.get("events") or [])})

    ok = (
        scoped.get("gate_g_complete") is False
        and scoped.get("export") == "audit_events"
        and int(scoped.get("count") or 0) == 2
        and scoped_tenants == ["t-a"]
        and "alice" in scoped_actors
        and int(other.get("count") or 0) == 1
        and other_tenants == ["t-b"]
        and int(unknown.get("count") or 0) == 0
        and int(unscoped.get("count") or 0) >= 3
    )

    evidence = {
        "gate_g_complete": False,
        "drill": "tenant_scoped_audit_export",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scoped_count": int(scoped.get("count") or 0),
        "other_count": int(other.get("count") or 0),
        "unknown_count": int(unknown.get("count") or 0),
        "unscoped_count": int(unscoped.get("count") or 0),
        "scoped_tenants": scoped_tenants,
        "scoped_actors": scoped_actors,
        "package_keys": sorted(scoped.keys()),
        "ok": ok,
        "reason": (
            "Tenant-scoped SQLite audit export verified offline; "
            "Studio SSO / independent review still open"
        ),
    }

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "audit_export_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "audit_export_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
