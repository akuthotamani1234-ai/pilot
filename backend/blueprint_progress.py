"""Studio sidebar blueprint progress: phases + gates with honest Partial status.

Never marks A–J complete. Used by /api/enterprise/readiness so the left sidebar
shows what landed, what is in progress, and what comes next.
"""
from __future__ import annotations

# Status vocabulary for the UI: done | strong | partial | active | open
# "done" = phase doc + offline evidence for that phase's scope (not gate-complete).
# "strong" = high DemoStore evidence; still not globally COMPLETE.
# "active" = currently being advanced on this branch.
# "partial" / "open" = foundations or not established.


def progress() -> dict:
    """Snapshot for the Studio sidebar. Always incomplete until gates A–J close."""
    phases = [
        {"id": "P0", "label": "Phase 0 — Baseline inventory", "status": "done",
         "note": "Offline inventory + baseline docs"},
        {"id": "P1", "label": "Phase 1 — DemoStore Gate J", "status": "strong",
         "note": "Run6: 19/19 pages, 24/24 clean, 6/6 bugs, 0 FA"},
        {"id": "P2", "label": "Phase 2 — Discovery verifier", "status": "done",
         "note": "Truth-page coverage checks"},
        {"id": "P3", "label": "Phase 3 — Durable swarm queue", "status": "done",
         "note": "SQLite leases; Redis still open"},
        {"id": "P4", "label": "Phase 4 — Oracles + cleanup", "status": "done",
         "note": "Provenance + remote-confirm APIs"},
        {"id": "P5", "label": "Phase 5 — Device / portfolios", "status": "done",
         "note": "Matrix + evaluators offline"},
        {"id": "P6", "label": "Phase 6 — Enterprise foundations", "status": "done",
         "note": "RBAC / API v1 / local object store"},
        {"id": "P7", "label": "Phase 7 — Gates A/H/I increments", "status": "partial",
         "note": "Graph, ops probe, Studio panel — not complete"},
    ]
    gates = [
        {"id": "A", "label": "Gate A — Discovery surfaces", "status": "partial",
         "note": "Graph + surface_coverage; full live matrix open"},
        {"id": "B", "label": "Gate B — Durable swarm", "status": "partial",
         "note": "Local SQLite queue; Redis/Postgres open"},
        {"id": "C", "label": "Gate C — Oracles + cleanup", "status": "active",
         "note": "Durable lifecycle + created.jsonl confirm; oracle bind softens AI defects"},
        {"id": "D", "label": "Gate D — Cross-surface matrix", "status": "partial",
         "note": "Declared; live Android emulator evidence open"},
        {"id": "E", "label": "Gate E — Replay + healing", "status": "partial",
         "note": "Bounded run_saved + healing_policy; live failure matrix open"},
        {"id": "F", "label": "Gate F — Portfolios (a11y/perf/…)", "status": "partial",
         "note": "a11y/perf/security/visual capture on apply_run; broad live CI open"},
        {"id": "G", "label": "Gate G — Tenancy / audit / store", "status": "partial",
         "note": "SQLite audit_events; live Postgres/Redis/MinIO open"},
        {"id": "H", "label": "Gate H — Ops / DR / load", "status": "partial",
         "note": "Checklist + ops_readiness; drills/load/observability still open"},
        {"id": "I", "label": "Gate I — React/TS dashboard", "status": "partial",
         "note": "frontend/dashboard React+TS scaffold; auth/approvals/hosting open"},
        {"id": "J", "label": "Gate J — Seeded-defect benchmark", "status": "strong",
         "note": "DemoStore strong; broader sites/Android open"},
    ]
    active = next((g for g in gates if g["status"] == "active"), None)
    upcoming = [
        {"id": "F-capture", "label": "Portfolio capture from discovery app_map", "status": "done"},
        {"id": "G-audit", "label": "Persist studio/RBAC audit events to SQLite", "status": "done"},
        {"id": "sidebar", "label": "Studio sidebar blueprint todo progress", "status": "done"},
        {"id": "H-checklist", "label": "Ops drill checklist documented", "status": "done"},
        {"id": "C-wire", "label": "Oracle + lifecycle artifacts on apply_run", "status": "done"},
        {"id": "E-policy", "label": "Healing policy artifact on apply_run", "status": "done"},
        {"id": "I-react", "label": "React/TS enterprise dashboard scaffold", "status": "done"},
        {"id": "C-durable", "label": "Durable lifecycle + created.jsonl remote confirm", "status": "active"},
        {"id": "C-oracle-bind", "label": "Design-time oracle bind + failure soften", "status": "active"},
        {"id": "E-execute", "label": "Bounded replay re-execution evidence", "status": "done"},
        {"id": "H-drills", "label": "Ops backup/restore + load evidence", "status": "open"},
        {"id": "D-android", "label": "Live Android device-matrix proof", "status": "open"},
        {"id": "G-live", "label": "Live Postgres / Redis / MinIO isolation", "status": "open"},
        {"id": "I-auth", "label": "Dashboard auth, approvals, hosted contracts", "status": "open"},
    ]
    return {
        "complete": False,
        "rule": "Gates A–J stay Partial/open until controlled live evidence + independent review",
        "active": active,
        "phases": phases,
        "gates": gates,
        "upcoming": upcoming,
        "counts": {
            "phases_done": sum(1 for p in phases if p["status"] in {"done", "strong"}),
            "phases_total": len(phases),
            "gates_strong_or_done": sum(1 for g in gates if g["status"] in {"done", "strong"}),
            "gates_partial": sum(1 for g in gates if g["status"] == "partial"),
            "gates_open": sum(1 for g in gates if g["status"] in {"open", "active"}),
            "gates_total": len(gates),
        },
    }
