"""Gate E: live DemoStore failure matrix + locator healing policy.

Provokes several real Playwright failures against DemoStore, classifies each
via ``failure_analysis.classify``, and checks locator-only healing allows a
repair while denying assertion weakening. Production healing suite still open —
``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .agents.failure_analysis import classify
from .healing_policy import review_repair

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "live_failure_matrix_drill.json"


def _provoke(page) -> list[dict]:
    cases: list[dict] = []
    # 1) missing locator
    try:
        page.locator("#qpilot-no-such-element").click(timeout=700)
        cases.append({"id": "missing-locator", "outcome": "passed", "error": "", "error_type": ""})
    except Exception as exc:
        cases.append({
            "id": "missing-locator",
            "outcome": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
            "flaky": False,
        })
    # 2) assertion on wrong text
    try:
        text = page.locator("body").inner_text(timeout=2000)[:200]
        assert "___QPILOT_IMPOSSIBLE_MARKER___" in text
        cases.append({"id": "assert-text", "outcome": "passed", "error": "", "error_type": ""})
    except Exception as exc:
        cases.append({
            "id": "assert-text",
            "outcome": "failed",
            "error_type": type(exc).__name__,
            "error": f"AssertionError: expected marker not found ({exc})"[:300],
            "flaky": False,
        })
    # 3) timeout waiting for hidden role
    try:
        page.get_by_role("button", name="___NoSuchRole___").click(timeout=700)
        cases.append({"id": "role-timeout", "outcome": "passed", "error": "", "error_type": ""})
    except Exception as exc:
        cases.append({
            "id": "role-timeout",
            "outcome": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
            "flaky": False,
        })
    return cases


def _linked_matrix() -> dict:
    return {
        "gate_e_complete": False,
        "ok": False,
        "drill": "live_demo_store_failure_matrix",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_live_failure_matrix_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "live_failure_matrix_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_matrix()

    from playwright.sync_api import sync_playwright

    from tests.demo_store import DemoStore

    store = DemoStore().start()
    raw_cases: list[dict] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(store.url, wait_until="domcontentloaded")
            raw_cases = _provoke(page)
            browser.close()
    finally:
        try:
            store.stop()
        except Exception:
            pass

    rows = []
    counts: dict[str, int] = {}
    for raw in raw_cases:
        cat, why, conf = classify(raw)
        counts[cat] = counts.get(cat, 0) + 1
        rows.append({
            "id": raw.get("id"),
            "category": cat,
            "confidence": conf,
            "why": (why or "")[:160],
            "outcome": raw.get("outcome"),
            "error_type": raw.get("error_type"),
        })

    old = (
        "def test_buy(page):\n"
        "    page.locator(\"#qpilot-no-such-element\").click()\n"
        "    assert page.locator(\"body\").is_visible()\n"
    )
    healed = (
        "def test_buy(page):\n"
        "    page.locator(\"a, button\").first.click()\n"
        "    assert page.locator(\"body\").is_visible()\n"
    )
    weakened = (
        "def test_buy(page):\n"
        "    page.locator(\"#qpilot-no-such-element\").click()\n"
        "    assert True\n"
    )
    allow = review_repair(old, healed)
    deny = review_repair(old, weakened)

    failed = [r for r in rows if r.get("outcome") == "failed"]
    evidence = {
        "gate_e_complete": False,
        "drill": "live_demo_store_failure_matrix",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cases": len(rows),
        "failed": len(failed),
        "counts": counts,
        "rows": rows,
        "healing": {
            "locator_repair_allowed": bool(allow.get("allowed")),
            "weaken_denied": not bool(deny.get("allowed")),
        },
        "ok": len(failed) >= 2
        and bool(allow.get("allowed"))
        and not bool(deny.get("allowed")),
        "reason": (
            f"Live DemoStore failure matrix classified {len(failed)} provoked failures; "
            "production failure matrix / healing suite still open"
        ),
    }

    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_matrix()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_matrix()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
