"""Gate C: approved-spec oracle bind + decide_observation drill.

Uses DemoStore truth fixture features as approved expectations and proves
AI proposals stay needs_review. Broader live portal oracles still open —
gate_c_complete stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .finalization import folder_is_linked, write_text_unless_linked
from .oracle import bind_assertion, decide_observation
from .oracle_bind import attach_assertion, soften_defect_category

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "oracle_spec_drill.json"
TRUTH = ROOT / "tests" / "demo_store_truth.json"


def _linked_drill() -> dict:
    return {
        "gate_c_complete": False,
        "ok": False,
        "drill": "demo_store_oracle_spec",
        "reason": "A link was in the way, so the drill was not saved.",
    }


def run_oracle_spec_drill(*, ops_dir: Path | None = None) -> dict:
    out_name = "oracle_spec_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_drill()
    if folder_is_linked(TRUTH):
        return _linked_drill()
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    features = list(truth.get("features") or [])[:5]
    if not features:
        raise RuntimeError("demo_store_truth.json has no features")

    approved_cases = []
    pass_verdicts = []
    for feat in features:
        case = attach_assertion({
            "tc_id": f"TRUTH-{feat.get('id')}",
            "title": str(feat.get("id") or ""),
            "expected": f"Feature {feat.get('id')} behaves per fixture: {feat.get('test') or ''}",
            "oracle": "fixture",
            "url": str(feat.get("page") or "/"),
            "page": str(feat.get("page") or "/"),
        })
        approved_cases.append({
            "id": feat.get("id"),
            "accepted": bool(case["assertion"].get("accepted")),
            "oracle_source": case["assertion"].get("oracle_source"),
            "status": case["assertion"].get("status"),
        })
        decision = decide_observation(
            case["assertion"],
            observed=str(feat.get("test") or "ok"),
            matched=True,
        )
        pass_verdicts.append(decision.get("verdict"))

    # Negative: AI proposal must never pass/fail as a product defect alone.
    ai_case = attach_assertion({
        "tc_id": "AI-GUESS-001",
        "title": "Unreviewed AI guess",
        "expected": "Maybe wrong total",
        "oracle": "ai",
        "url": "/cart",
    })
    ai_decision = decide_observation(
        ai_case["assertion"], observed="57", matched=False,
    )
    softened_cat, soften_why, soften_dec = soften_defect_category(
        "product_defect", ai_case, {"outcome": "failed"},
    )

    # Explicit business_rule bind (cart total from approved source).
    rule = bind_assertion(
        source="business_rule",
        statement="Cart total must include quantity × unit price",
        scope="/cart",
        requirement_id="cart.totals",
    )
    rule_pass = decide_observation(rule, observed="114", matched=True)
    rule_fail = decide_observation(rule, observed="57", matched=False)

    all_approved = all(row.get("accepted") for row in approved_cases)
    all_pass = all(v == "pass" for v in pass_verdicts)
    evidence = {
        "gate_c_complete": False,
        "drill": "demo_store_oracle_spec",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture": "DemoStore truth",
        "truth_path": "tests/demo_store_truth.json",
        "features_bound": len(approved_cases),
        "approved_cases": approved_cases,
        "approved_pass_verdicts": pass_verdicts,
        "ai_proposal": {
            "accepted": bool(ai_case["assertion"].get("accepted")),
            "status": ai_case["assertion"].get("status"),
            "decide_verdict": ai_decision.get("verdict"),
            "softened_category": softened_cat,
            "soften_reason": soften_why[:200],
            "soften_verdict": (soften_dec or {}).get("verdict"),
        },
        "business_rule": {
            "accepted": bool(rule.get("accepted")),
            "pass_verdict": rule_pass.get("verdict"),
            "fail_verdict": rule_fail.get("verdict"),
        },
        "ok": (
            all_approved
            and all_pass
            and ai_decision.get("verdict") == "needs_review"
            and softened_cat == "inconclusive"
            and rule_pass.get("verdict") == "pass"
            and rule_fail.get("verdict") == "fail"
        ),
        "reason": (
            "DemoStore fixture/business_rule oracles bind and decide; AI stays needs_review; "
            "broader live portal oracle paths still open"
        ),
    }

    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_drill()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, json.dumps(evidence, indent=2)):
        return _linked_drill()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "oracle_spec_drill.json"
        if not folder_is_linked(art) and not folder_is_linked(art.parent):
            art.parent.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art.parent, art.name, json.dumps(evidence, indent=2))
    return evidence
