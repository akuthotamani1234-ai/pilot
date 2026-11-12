"""Inventory reports deliberately make no claim about functional correctness."""
import html
import json
from datetime import datetime
from pathlib import Path

from .page_status import exploration_status
from .report_clarity import build as clarity_build
from .state import QAState


def discovery_report(state: QAState) -> dict:
    run_dir = Path(state["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    pages = state.get("app_map", [])
    crawl = dict(state.get("crawl") or {})
    if "exploration" not in crawl:
        crawl["exploration"] = exploration_status(crawl)
    opened = sum(not p.get("error") and (p.get("status") or 0) < 400 for p in pages)
    complete = not state.get("incomplete") and not state.get("setup_error") and bool(opened)
    note = ("Discovery only. Components were observed, but their functionality was not tested. "
            "A separate test run is required for a release verdict.")
    clarity = clarity_build(
        crawl=crawl, app_map=pages, limits=[], incomplete=bool(state.get("incomplete")),
        discovery_only=True, test_cases={"planned": 0, "passed": 0, "failed": 0, "flaky": 0, "skipped": 0,
                                         "blocked": 0, "inconclusive": 0, "not_run": 0, "pending": 0},
        feature_counts=state.get("feature_counts"))
    pages_cov = clarity["pages_coverage"]
    summary = {
        "run_id": state["run_id"], "source": state.get("source"), "url": state.get("url"),
        "mode": "discovery", "discovery_only": True, "inventory_available": bool(pages),
        "discovery_finished": complete, "verdict": "Insufficient Evidence",
        "headline": {"title": "Component discovery", "text": note}, "reasons": [note],
        "pages": len(pages), "pages_opened": opened,
        "pages_discovered": pages_cov["discovered"], "pages_visited": pages_cov["visited"],
        "pages_not_visited": pages_cov["not_visited"],
        "tests": 0, "passed": 0, "failed": 0, "skipped": 0, "inconclusive": 0, "blocked": 0,
        "not_tested": 0, "test_cases": 0, "scripts": 0, "findings": 0, "bugs": 0,
        "incomplete": bool(state.get("incomplete")), "incomplete_reason": state.get("incomplete_reason", ""),
        "setup_error": state.get("setup_error", ""), "stopped_at": state.get("stopped_at", ""),
        "crawl": crawl, "exploration": crawl.get("exploration"),
        "result_status_counts": clarity["result_status_counts"],
        "feature_status_counts": clarity["feature_status_counts"],
        "pages_coverage": pages_cov,
        "coverage_limitations": clarity["coverage_limitations"],
        "cost_usd": 0, "cost_per_case_usd": 0, "tokens": 0, "llm": "none",
        "finished": datetime.now().isoformat(timespec="seconds"),
        "gates": [{"id": "functional_tests", "name": "Functional tests ran", "status": "missing",
                   "mandatory": True, "detail": note}],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    def esc(value):
        return html.escape(str(value or ""), quote=True)
    rows = "".join("<tr><td>" + esc(p.get("title")) + "</td><td>" + esc(p.get("url"))
                   + "</td><td>" + esc(p.get("error") or p.get("status")) + "</td></tr>" for p in pages)
    reason = state.get("incomplete_reason") or state.get("setup_error") or ""
    lim = clarity["coverage_limitations"]
    feat = clarity["feature_status_counts"]
    statuses = clarity["result_status_counts"]
    status_line = " · ".join(f"{statuses[k]} {k}" for k in statuses["labels"])
    feat_line = (" · ".join(f"{feat[k]} {k}" for k in feat["labels"]) if feat.get("discovered")
                 else "0 features tested (discovery does not run functional checks)")
    doc = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
           'content="width=device-width,initial-scale=1"><title>Blow AI component discovery</title>'
           '<style>body{font:16px system-ui;color:#172033;background:#f5f7fb;margin:40px auto;max-width:1100px;'
           'padding:24px}main{background:white;border-radius:20px;padding:32px}a{color:#4f46e5}'
           'table{border-collapse:collapse;width:100%}td,th{padding:12px;text-align:left;'
           'border-bottom:1px solid #ddd;overflow-wrap:anywhere}aside{padding:20px;background:#eef2ff;'
           'margin:16px 0}.nums{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}.nums div{background:#f8fafc;'
           'border:1px solid #e2e8f0;border-radius:12px;padding:12px 14px;min-width:120px}.nums b{display:block;'
           'font-size:22px}</style>'
           '<main><h1>Component discovery</h1><aside>' + esc(note) + '</aside>'
           '<p><b>Coverage limitations:</b> ' + esc(lim["statement"]) + ' ' + esc(lim["limitation"]) + '</p>'
           '<div class="nums"><div><b>' + str(pages_cov["discovered"]) + '</b><span>pages discovered</span></div>'
           '<div><b>' + str(pages_cov["visited"]) + '</b><span>pages visited</span></div>'
           '<div><b>' + str(pages_cov["not_visited"]) + '</b><span>pages not visited</span></div>'
           '<div><b>0</b><span>functional tests (PASS/FAIL)</span></div></div>'
           '<p>Result statuses: ' + esc(status_line) + '</p>'
           '<p>Features: ' + esc(feat_line) + '</p>'
           '<p>' + str(len(pages)) + ' page(s) observed. No functional tests run. This is not a release verdict.</p><p>'
           + esc(reason) + '</p>'
           '<p><a href="components.html">Browse component inventory</a> ? '
           '<a href="components.json">Inventory JSON</a> ? <a href="crawl.json">Crawl limits and gaps</a></p>'
           '<table><tr><th>Page</th><th>URL</th><th>Load result</th></tr>' + rows + '</table></main></html>')
    report = run_dir / "report.html"
    report.write_text(doc, encoding="utf-8")
    return {"verdict": "Insufficient Evidence", "report_path": str(report),
            "log": state.get("log", []) + [note]}
