"""Gate E: controlled live DemoStore locator failure + healing policy drill.

Against a running DemoStore page: provoke a missing-locator failure, propose a
locator-only repair, and verify ``healing_policy.review_repair`` allows it while
rejecting an assertion-weaken. Production healing suite still open —
``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .agents.failure_analysis import classify
from .healing_policy import review_repair

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "demo_store_healing_live_drill.json"


def run_demo_store_healing_live_drill(*, ops_dir: Path | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    from tests.demo_store import DemoStore

    store = DemoStore().start()
    live: dict = {"url": store.url, "missing_locator": False, "good_locator": False}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(store.url, wait_until="domcontentloaded")
            # Provoked missing locator (expected fail).
            try:
                page.locator("#qpilot-missing-buy-button").click(timeout=800)
            except Exception as exc:
                live["missing_locator"] = True
                live["missing_error"] = str(exc)[:240]
            # Known-good interaction still works.
            try:
                page.locator("a, button").first.click(timeout=2000)
                live["good_locator"] = True
            except Exception as exc:
                live["good_error"] = str(exc)[:160]
            browser.close()
    finally:
        try:
            store.stop()
        except Exception:
            pass

    failure = {
        "id": "live-missing-locator",
        "outcome": "failed",
        "error_type": "TimeoutError",
        "error": live.get("missing_error")
        or "Timeout exceeded waiting for locator('#qpilot-missing-buy-button')",
        "flaky": False,
    }
    category, why, conf = classify(failure)

    old = (
        "def test_buy(page):\n"
        "    page.locator(\"#qpilot-missing-buy-button\").click()\n"
        "    assert page.locator(\".cart\").is_visible()\n"
    )
    healed = (
        "def test_buy(page):\n"
        "    page.locator(\"a, button\").first.click()\n"
        "    assert page.locator(\".cart\").is_visible()\n"
    )
    weakened = (
        "def test_buy(page):\n"
        "    page.locator(\"#qpilot-missing-buy-button\").click()\n"
        "    assert True\n"
    )
    allow = review_repair(old, healed)
    deny = review_repair(old, weakened)

    evidence = {
        "gate_e_complete": False,
        "drill": "demo_store_healing_live",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "live": live,
        "classification": {
            "category": category,
            "confidence": conf,
            "why": (why or "")[:160],
        },
        "healing": {
            "locator_repair_allowed": bool(allow.get("allowed")),
            "weaken_denied": not bool(deny.get("allowed")),
            "allow_reason": (allow.get("reason") or "")[:160],
            "deny_reason": (deny.get("reason") or "")[:160],
        },
        "ok": bool(live.get("missing_locator"))
        and bool(allow.get("allowed"))
        and not bool(deny.get("allowed")),
        "reason": (
            "Live DemoStore missing-locator failure classified + locator-only healing "
            "policy checked; production failure matrix / healing suite still open"
        ),
    }

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "demo_store_healing_live_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "demo_store_healing_live_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
