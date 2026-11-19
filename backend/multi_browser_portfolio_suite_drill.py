"""Gate F: live multi-browser DemoStore portfolio suite.

Re-runs compatibility (Chromium/Firefox/WebKit) plus a11y/locale/security/
perf/visual drills against a controlled DemoStore. Broad hosted CI still open —
``gate_f_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "multi_browser_portfolio_suite_drill.json"


def _linked_suite() -> dict:
    return {
        "gate_f_complete": False,
        "ok": False,
        "drill": "multi_browser_portfolio_suite",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_multi_browser_portfolio_suite_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    out_dir = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "multi_browser_portfolio_suite_drill.json"
    if folder_is_linked(out_dir) or folder_is_linked(out_dir / out_name):
        return _linked_suite()

    from .a11y_portfolio_drill import run_a11y_portfolio_drill
    from .compatibility_portfolio_drill import run_compatibility_portfolio_drill
    from .locale_portfolio_drill import run_locale_portfolio_drill
    from .perf_portfolio_drill import run_perf_portfolio_drill
    from .security_portfolio_drill import run_security_portfolio_drill
    from .visual_portfolio_drill import run_visual_portfolio_drill

    dest = Path(ops_dir) if ops_dir else None
    compat = run_compatibility_portfolio_drill(ops_dir=dest)
    suites = {
        "compatibility": compat,
        "a11y": run_a11y_portfolio_drill(ops_dir=dest),
        "locale": run_locale_portfolio_drill(ops_dir=dest),
        "security": run_security_portfolio_drill(ops_dir=dest),
        "perf": run_perf_portfolio_drill(ops_dir=dest),
        "visual": run_visual_portfolio_drill(ops_dir=dest),
    }
    browsers = list(((compat.get("matrix") or {}).get("browsers")) or [])
    passed = {name: bool(ev.get("ok")) for name, ev in suites.items()}
    evidence = {
        "gate_f_complete": False,
        "drill": "multi_browser_portfolio_suite",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "browsers": browsers,
        "suites_ok": passed,
        "suites_passed": sum(1 for ok in passed.values() if ok),
        "suites_total": len(passed),
        "ok": all(passed.values()) and len(browsers) >= 3,
        "reason": (
            f"Live DemoStore portfolio suite on {', '.join(browsers) or 'no browsers'}: "
            f"{sum(1 for ok in passed.values() if ok)}/{len(passed)} drills ok; "
            "broad hosted multi-browser CI artifacts still open"
        ),
    }

    text = json.dumps(evidence, indent=2)
    if folder_is_linked(out_dir) or folder_is_linked(out_dir / out_name):
        return _linked_suite()
    out_dir.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(out_dir, out_name, text):
        return _linked_suite()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
