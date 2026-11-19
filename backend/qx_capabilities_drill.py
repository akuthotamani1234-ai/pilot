"""QX-A02/A07/A12–A18: offline capability drills with honest Partial status.

Exercises explore scoring, env controls, agent eval, incremental discovery,
dependency faults, schema diff, human review, quality trends, and plugins.
Never marks gates complete.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .agent_eval import evaluate, model_change_allowed
from .dependency_fault import inject_fault
from .env_controls import action_still_blocked, enable_control
from .explore_score import rank_candidates
from .human_review import decide, withhold_unanswered
from .incremental_map import plan_pages
from .plugins import review_plugin
from .quality_trends import cluster_runs, keep_verdict
from .schema_diff import diff_specs

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "qx_capabilities_drill.json"


def _incremental_from_surfaces() -> dict:
    from .finalization import folder_is_linked
    path = ROOT / "docs" / "ops-evidence" / "demo_store_surface_coverage.json"
    pages = ["/", "/about", "/lab", "/signin"]
    if not folder_is_linked(path) and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            walked = payload.get("pages_walked") or []
            if walked:
                pages = [p if str(p).startswith("/") else f"/{p}" for p in walked]
        except (OSError, ValueError):
            pass
    saved = [{"url": pages[0], "template": "home"}, {"url": pages[1], "template": "about"}]
    current = [
        {"url": pages[0], "template": "home"},
        {"url": pages[1], "template": "about", "changed": True},
        {"url": pages[2] if len(pages) > 2 else "/lab", "template": "lab"},
    ]
    return plan_pages(saved, current, fresh=False)


def _linked_capabilities() -> dict:
    return {
        "gate_complete": False,
        "ok": False,
        "drill": "qx_capabilities_a02_a07_a12_a18",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_qx_capabilities_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    name = "qx_capabilities_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_capabilities()
    ranked = rank_candidates([
        {"url": "https://shop.example/known", "new_template": False, "journey_distance": 9},
        {"url": "https://shop.example/checkout", "new_template": True},
        {"url": "https://shop.example/new", "new_template": True, "failed": True, "journey_distance": 1},
    ])

    env_ok, env_name = enable_control("staging", "fixed_clock")
    env_prod_blocked, _ = enable_control("production", "fixed_clock")
    pay_blocked, _ = action_still_blocked("pay")

    tasks = [
        {"id": "t1", "expected": "pass", "actual": "pass", "cost": 0.01},
        {"id": "t2", "expected": "fail", "actual": "fail", "cost": 0.02},
        {"id": "t3", "expected": "pass", "actual": "fail", "cost": 0.01, "failed": True},
        {"id": "t4", "unsupported": True, "cost": 0.0},
    ]
    evaluation = evaluate(tasks)
    allowed, allow_reason = model_change_allowed(evaluation)

    incremental = _incremental_from_surfaces()

    fault_ok = inject_fault("staging", "payments-api", permitted=True)
    fault_prod = inject_fault("production", "payments-api", permitted=True)

    schema = diff_specs(
        {"operations": [{"method": "GET", "path": "/cart", "fields": ["id", "total"], "workflow": "cart"}]},
        {"operations": [
            {"method": "GET", "path": "/cart", "fields": ["id"], "workflow": "cart"},
            {"method": "POST", "path": "/cart/items", "fields": ["sku"], "workflow": "cart"},
        ]},
    )

    human = {
        "uncertain_no_answer": decide("uncertain_assertion", None),
        "heal_accepted": decide("heal", "approved"),
        "sensitive_rejected": decide("sensitive", "reject"),
    }
    kept, held = withhold_unanswered(
        [
            {"id": "safe", "approval_required": False},
            {"id": "sens", "approval_required": True, "tc_id": "sens"},
        ],
        answers={},
    )

    trends = cluster_runs([
        {"failures": ["cart", "login"], "flaky": ["search"]},
        {"failures": ["cart"], "flaky": []},
        {"failures": ["checkout"], "flaky": ["search"]},
    ])
    verdict_kept = keep_verdict("Not Ready", trends)

    plugin_ok = review_plugin({"version": "1.0.0", "actions": ["note"], "disable": []})
    plugin_bad = review_plugin({"version": "1.0.0", "disable": ["pay"]})

    checks = {
        "A02_explore_score": [r["url"] for r in ranked] == [
            "https://shop.example/new", "https://shop.example/known",
        ],
        "A07_env_controls": bool(env_ok) and not env_prod_blocked and pay_blocked,
        "A12_agent_eval": bool(evaluation.get("stored")) and allowed and evaluation["accuracy"] > 0,
        "A13_incremental": bool(incremental.get("reopen")) and "/about" in (incremental.get("reopen") or []),
        "A14_dependency_fault": bool(fault_ok.get("injected")) and not fault_prod.get("injected"),
        "A15_schema_diff": bool(schema.get("trust_broken")) and bool(schema.get("broken")),
        "A16_human_review": (
            not human["uncertain_no_answer"]["apply"]
            and human["heal_accepted"]["apply"]
            and not human["sensitive_rejected"]["apply"]
            and held == 1
            and len(kept) == 1
        ),
        "A17_quality_trends": (
            trends.get("next_priority", [None])[0] in {"cart", "search"}
            and verdict_kept == "Not Ready"
        ),
        "A18_plugins": bool(plugin_ok.get("accepted")) and not plugin_bad.get("accepted"),
    }

    evidence = {
        "gate_complete": False,
        "drill": "qx_capabilities_a02_a07_a12_a18",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": checks,
        "details": {
            "explore": [r.get("url") for r in ranked],
            "env": {"ok": env_ok, "control": env_name, "pay_blocked": pay_blocked},
            "evaluation": evaluation,
            "model_change": {"allowed": allowed, "reason": allow_reason},
            "incremental": incremental,
            "fault": {"staging": fault_ok, "production": fault_prod},
            "schema": schema,
            "human": human,
            "withheld": held,
            "trends": trends,
            "verdict_kept": verdict_kept,
            "plugins": {"ok": plugin_ok, "blocked": plugin_bad},
        },
        "ok": all(checks.values()),
        "reason": (
            f"QX capabilities A02/A07/A12–A18 offline drill: "
            f"{sum(1 for v in checks.values() if v)}/{len(checks)} checks passed; "
            "gates stay Partial until live/hosted evidence + independent review"
        ),
    }

    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_capabilities()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_capabilities()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
