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
         "note": "Graph + surface_coverage (iframe/shadow/API/lazy/metadata/viewport); full live matrix open"},
        {"id": "B", "label": "Gate B — Durable swarm", "status": "partial",
         "note": "SQLite + Redis DurableQueue adapters, specialists; product-wide Redis default/review open"},
        {"id": "C", "label": "Gate C — Oracles + cleanup", "status": "partial",
         "note": "Durable lifecycle + created.jsonl + AdminPortal remote_delete; live portal paths still open"},
        {"id": "D", "label": "Gate D — Cross-surface matrix", "status": "partial",
         "note": "Web viewports + Android protocol dry-run contract; live emulator still open"},
        {"id": "E", "label": "Gate E — Replay + healing", "status": "partial",
         "note": "Bounded run_saved + healing_policy; live failure matrix open"},
        {"id": "F", "label": "Gate F — Portfolios (a11y/perf/…)", "status": "partial",
         "note": "a11y/perf/security/visual capture on apply_run; broad live CI open"},
        {"id": "G", "label": "Gate G — Tenancy / audit / store", "status": "active",
         "note": "Live Postgres/Redis/MinIO drills when configured; Studio SSO/multi-tenant ACLs still open"},
        {"id": "H", "label": "Gate H — Ops / DR / load", "status": "active",
         "note": "Local drills + CI rollback + loopback paging; live hosted DR/on-call still open"},
        {"id": "I", "label": "Gate I — React/TS dashboard", "status": "active",
         "note": "Auth modes + OIDC/hosting contract snapshot; live SSO login still open"},
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
        {"id": "C-durable", "label": "Durable lifecycle + created.jsonl remote confirm", "status": "done"},
        {"id": "C-oracle-bind", "label": "Design-time oracle bind + failure soften", "status": "done"},
        {"id": "E-execute", "label": "Bounded replay re-execution evidence", "status": "done"},
        {"id": "B-wire", "label": "Durable swarm plan/drain on discovery/apply", "status": "done"},
        {"id": "D-viewport", "label": "Desktop+phone viewport evidence from discovery", "status": "done"},
        {"id": "B-listing", "label": "SiteSwarm listing dual-write into DurableQueue", "status": "done"},
        {"id": "I-approvals", "label": "Approvals queue + dashboard decide UI", "status": "done"},
        {"id": "H-local-drill", "label": "Local backup/restore + metrics snapshot", "status": "done"},
        {"id": "H-load-probe", "label": "Local API load probe evidence", "status": "done"},
        {"id": "A-discovery-surfaces", "label": "Write surface_coverage during discovery", "status": "done"},
        {"id": "I-token", "label": "Optional dashboard bearer token for approvals", "status": "done"},
        {"id": "A-lazy-meta", "label": "Lazy/metadata/viewport signals in surface_coverage", "status": "done"},
        {"id": "H-incident-stub", "label": "Incident runbook + stub tabletop", "status": "done"},
        {"id": "B-specialists", "label": "Coverage/oracle specialist plan+drain", "status": "done"},
        {"id": "E-persist-replay", "label": "Persist replay packages before run_saved", "status": "done"},
        {"id": "G-tenancy-sqlite", "label": "SQLite tenants/principals/run_index helpers", "status": "done"},
        {"id": "G-live-pg-redis", "label": "Live Postgres isolation + Redis lease drills", "status": "done"},
        {"id": "B-redis-queue", "label": "Redis DurableQueue adapter + plan/drain drill", "status": "done"},
        {"id": "G-minio", "label": "Live MinIO object-store drill", "status": "done"},
        {"id": "C-admin-portal", "label": "AdminPortal remote_delete lifecycle adapter", "status": "done"},
        {"id": "H-ci-rollback", "label": "Offline CI/deploy rollback rehearsal", "status": "done"},
        {"id": "I-auth-modes", "label": "Dashboard auth modes bearer/webhook/principal", "status": "done"},
        {"id": "D-android-dryrun", "label": "Android protocol dry-run evidence contract", "status": "done"},
        {"id": "H-paging-loopback", "label": "Loopback paging rehearsal (not live on-call)", "status": "done"},
        {"id": "I-sso-contract", "label": "OIDC/hosting env contract snapshot", "status": "done"},
        {"id": "H-drills", "label": "Live hosted DR / soak / on-call paging", "status": "open"},
        {"id": "D-android", "label": "Live Android emulator/API24+ matrix proof", "status": "open"},
        {"id": "I-auth", "label": "Live SSO login + hosted multi-tenant ACLs", "status": "open"},
        {"id": "G-review", "label": "Independent security/reliability review", "status": "open"},
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
