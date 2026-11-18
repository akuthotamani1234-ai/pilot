"""Gate E: multi-app live failure + locator-only healing suite.

Runs a controlled missing-locator provoke + healing policy check against
DemoStore, ClassicShop, AdminPortal, and TravelSite fixtures. Advances the
production-like healing suite evidence — production / third-party healing
still open; ``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .agents.failure_analysis import classify
from .healing_policy import review_repair

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "multi_app_healing_suite_drill.json"

APPS = (
    ("demo_store", "tests.demo_store", "DemoStore"),
    ("classic_shop", "tests.classic_shop", "ClassicShop"),
    ("admin_portal", "tests.admin_portal", "AdminPortal"),
    ("travel_site", "tests.travel_site", "TravelSite"),
)


def _provoke_and_heal(page, app_id: str) -> dict:
    live = {"app": app_id, "missing_locator": False, "good_locator": False}
    try:
        page.locator(f"#qpilot-missing-{app_id}").click(timeout=700)
    except Exception as exc:
        live["missing_locator"] = True
        live["missing_error"] = str(exc)[:240]
    try:
        page.locator("a, button, input, select").first.click(timeout=2000)
        live["good_locator"] = True
    except Exception as exc:
        live["good_error"] = str(exc)[:160]

    failure = {
        "id": f"{app_id}-missing-locator",
        "outcome": "failed",
        "error_type": "TimeoutError",
        "error": live.get("missing_error")
        or f"Timeout waiting for locator('#qpilot-missing-{app_id}')",
        "flaky": False,
    }
    category, why, conf = classify(failure)
    old = (
        f"def test_{app_id}(page):\n"
        f"    page.locator(\"#qpilot-missing-{app_id}\").click()\n"
        "    assert page.locator(\"body\").is_visible()\n"
    )
    healed = (
        f"def test_{app_id}(page):\n"
        "    page.locator(\"a, button\").first.click()\n"
        "    assert page.locator(\"body\").is_visible()\n"
    )
    weakened = (
        f"def test_{app_id}(page):\n"
        f"    page.locator(\"#qpilot-missing-{app_id}\").click()\n"
        "    assert True\n"
    )
    allow = review_repair(old, healed)
    deny = review_repair(old, weakened)
    ok = (
        bool(live.get("missing_locator"))
        and bool(allow.get("allowed"))
        and not bool(deny.get("allowed"))
    )
    return {
        "app": app_id,
        "ok": ok,
        "live": live,
        "classification": {
            "category": category,
            "confidence": conf,
            "why": (why or "")[:160],
        },
        "healing": {
            "locator_repair_allowed": bool(allow.get("allowed")),
            "weaken_denied": not bool(deny.get("allowed")),
        },
    }


def run_multi_app_healing_suite_drill(*, ops_dir: Path | None = None) -> dict:
    from importlib import import_module

    from playwright.sync_api import sync_playwright

    results: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for app_id, mod_name, cls_name in APPS:
            mod = import_module(mod_name)
            fixture = getattr(mod, cls_name)().start()
            try:
                page = browser.new_page()
                page.goto(fixture.url, wait_until="domcontentloaded")
                results.append(_provoke_and_heal(page, app_id))
                page.close()
            except Exception as exc:
                results.append({
                    "app": app_id,
                    "ok": False,
                    "error": str(exc)[:240],
                })
            finally:
                try:
                    fixture.stop()
                except Exception:
                    pass
        browser.close()

    passed = sum(1 for r in results if r.get("ok"))
    evidence = {
        "gate_e_complete": False,
        "drill": "multi_app_healing_suite",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "apps": results,
        "passed": passed,
        "total": len(results),
        "ok": passed == len(APPS) and len(results) == len(APPS),
        "reason": (
            f"Multi-app healing suite {passed}/{len(APPS)} fixtures ok; "
            "production / third-party healing suite still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "multi_app_healing_suite_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "multi_app_healing_suite_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
