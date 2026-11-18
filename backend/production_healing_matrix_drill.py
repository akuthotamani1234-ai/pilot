"""Gate E: production-like multi-failure healing matrix (controlled fixtures).

Provokes missing-locator, assertion, role-timeout, and navigation-timeout
failures on DemoStore, ClassicShop, AdminPortal, and TravelSite; classifies
each; and checks locator-only healing vs assertion weaken denial. Production /
third-party healing still open — ``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .agents.failure_analysis import classify
from .healing_policy import review_repair

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_matrix_drill.json"

APPS = (
    ("demo_store", "tests.demo_store", "DemoStore"),
    ("classic_shop", "tests.classic_shop", "ClassicShop"),
    ("admin_portal", "tests.admin_portal", "AdminPortal"),
    ("travel_site", "tests.travel_site", "TravelSite"),
)


def _provoke(page, app_id: str) -> list[dict]:
    cases: list[dict] = []
    try:
        page.locator(f"#qpilot-prod-missing-{app_id}").click(timeout=600)
        cases.append({"id": "missing-locator", "outcome": "passed"})
    except Exception as exc:
        cases.append({
            "id": "missing-locator",
            "outcome": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:240],
            "flaky": False,
        })
    try:
        text = page.locator("body").inner_text(timeout=1500)[:200]
        assert "___QPILOT_PROD_IMPOSSIBLE___" in text
        cases.append({"id": "assert-text", "outcome": "passed"})
    except Exception as exc:
        cases.append({
            "id": "assert-text",
            "outcome": "failed",
            "error_type": type(exc).__name__,
            "error": f"AssertionError: marker missing ({exc})"[:240],
            "flaky": False,
        })
    try:
        page.get_by_role("button", name="___NoSuchProdRole___").click(timeout=600)
        cases.append({"id": "role-timeout", "outcome": "passed"})
    except Exception as exc:
        cases.append({
            "id": "role-timeout",
            "outcome": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:240],
            "flaky": False,
        })
    try:
        page.goto(
            "http://127.0.0.1:9/qpilot-prod-unreachable",
            wait_until="domcontentloaded",
            timeout=700,
        )
        cases.append({"id": "nav-timeout", "outcome": "passed"})
    except Exception as exc:
        cases.append({
            "id": "nav-timeout",
            "outcome": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:240],
            "flaky": False,
        })
    return cases


def _heal_checks(app_id: str) -> dict:
    old = (
        f"def test_{app_id}(page):\n"
        f"    page.locator(\"#qpilot-prod-missing-{app_id}\").click()\n"
        "    assert page.locator(\"body\").is_visible()\n"
    )
    healed = (
        f"def test_{app_id}(page):\n"
        "    page.locator(\"a, button\").first.click()\n"
        "    assert page.locator(\"body\").is_visible()\n"
    )
    weakened = (
        f"def test_{app_id}(page):\n"
        f"    page.locator(\"#qpilot-prod-missing-{app_id}\").click()\n"
        "    assert True\n"
    )
    allow = review_repair(old, healed)
    deny = review_repair(old, weakened)
    return {
        "locator_repair_allowed": bool(allow.get("allowed")),
        "weaken_denied": not bool(deny.get("allowed")),
    }


def run_production_healing_matrix_drill(*, ops_dir: Path | None = None) -> dict:
    from importlib import import_module

    from playwright.sync_api import sync_playwright

    apps: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for app_id, mod_name, cls_name in APPS:
            mod = import_module(mod_name)
            fixture = getattr(mod, cls_name)().start()
            try:
                page = browser.new_page()
                page.goto(fixture.url, wait_until="domcontentloaded")
                raw = _provoke(page, app_id)
                classified = []
                for case in raw:
                    if case.get("outcome") == "failed":
                        cat, why, conf = classify(case)
                        classified.append({
                            **case,
                            "category": cat,
                            "confidence": conf,
                            "why": (why or "")[:120],
                        })
                    else:
                        classified.append(case)
                healing = _heal_checks(app_id)
                failed = [c for c in classified if c.get("outcome") == "failed"]
                ok = (
                    len(failed) >= 4
                    and healing["locator_repair_allowed"]
                    and healing["weaken_denied"]
                )
                apps.append({
                    "app": app_id,
                    "ok": ok,
                    "failed": len(failed),
                    "cases": classified,
                    "healing": healing,
                })
                page.close()
            except Exception as exc:
                apps.append({"app": app_id, "ok": False, "error": str(exc)[:240]})
            finally:
                try:
                    fixture.stop()
                except Exception:
                    pass
        browser.close()

    passed = sum(1 for a in apps if a.get("ok"))
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_matrix",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "apps": apps,
        "passed": passed,
        "total": len(APPS),
        "ok": passed == len(APPS),
        "reason": (
            f"Production-like healing matrix {passed}/{len(APPS)} apps "
            "(missing/assert/role/nav + locator-only heal); production suite still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "production_healing_matrix_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "production_healing_matrix_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
