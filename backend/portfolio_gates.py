"""Gate F portfolio gates: a11y, visual, performance, locale, safe security.

Missing evidence is unknown — never treated as pass. Security checks are
read-only observations of already-captured response metadata; nothing is probed.
"""
from __future__ import annotations

from .locale_check import check_locale

PORTFOLIOS = ("a11y", "visual", "performance", "locale", "security", "compatibility")

# Safe, passive header observations only (no scanning, no auth bypass).
_SECURITY_HEADERS = ("content-security-policy", "strict-transport-security", "x-content-type-options")


def _unknown(name: str, reason: str) -> dict:
    return {"portfolio": name, "verdict": "unknown", "ok": False, "reason": reason, "findings": []}


def evaluate_a11y(page: dict | None) -> dict:
    """Offline a11y signals from a recorded page inventory. No browser run."""
    if not isinstance(page, dict) or not page:
        return _unknown("a11y", "no page inventory for accessibility checks")
    findings = []
    for img in page.get("images") or []:
        if isinstance(img, dict) and not (img.get("alt") or "").strip():
            findings.append({"kind": "missing_alt", "target": img.get("src") or img.get("selector") or "img"})
    for field in page.get("inputs") or page.get("fields") or []:
        if not isinstance(field, dict):
            continue
        label = (field.get("label") or field.get("accname") or field.get("aria_label") or "").strip()
        if not label:
            findings.append({"kind": "unlabeled_input", "target": field.get("name") or field.get("selector") or "input"})
    return {
        "portfolio": "a11y",
        "verdict": "fail" if findings else "pass",
        "ok": not findings,
        "reason": f"{len(findings)} accessibility finding(s)" if findings else "",
        "findings": findings[:50],
    }


def evaluate_visual(report: dict | None) -> dict:
    """Visual portfolio uses an existing visual.json summary; empty is unknown."""
    if not isinstance(report, dict) or not report:
        return _unknown("visual", "no visual.json evidence")
    pages = report.get("pages") if isinstance(report.get("pages"), list) else []
    if not pages and "changed" not in report and "same" not in report:
        return _unknown("visual", "visual report has no page results")
    changed = report.get("changed")
    if changed is None and pages:
        changed = [p for p in pages if p.get("status") in {"changed", "diff", "fail"}]
    changed_n = len(changed) if isinstance(changed, list) else int(changed or 0)
    return {
        "portfolio": "visual",
        "verdict": "fail" if changed_n else "pass",
        "ok": not changed_n,
        "reason": f"{changed_n} visual change(s)" if changed_n else "",
        "findings": (changed[:20] if isinstance(changed, list) else []),
    }


def evaluate_performance(timings: dict | None, budgets: dict | None = None) -> dict:
    """Compare observed timings (ms) with budgets. Missing timings stay unknown."""
    if not isinstance(timings, dict) or not timings:
        return _unknown("performance", "no performance timings recorded")
    budgets = budgets or {"dom_content_loaded_ms": 3000, "load_ms": 5000, "largest_contentful_paint_ms": 4000}
    findings = []
    for key, limit in budgets.items():
        if key not in timings:
            continue
        try:
            value = float(timings[key])
            cap = float(limit)
        except (TypeError, ValueError):
            continue
        if value > cap:
            findings.append({"kind": "budget_exceeded", "metric": key, "observed": value, "budget": cap})
    checked = [k for k in budgets if k in timings]
    if not checked:
        return _unknown("performance", "timings do not include any budgeted metrics")
    return {
        "portfolio": "performance",
        "verdict": "fail" if findings else "pass",
        "ok": not findings,
        "reason": f"{len(findings)} budget breach(es)" if findings else "",
        "findings": findings,
        "checked": checked,
    }


def evaluate_locale(observed: dict | None, expected: dict | None) -> dict:
    """Locale portfolio wraps locale_check; missing expected values stay unknown."""
    if not isinstance(observed, dict) or not observed:
        return _unknown("locale", "no locale observations")
    if not isinstance(expected, dict) or not expected:
        return _unknown("locale", "no approved locale expectation")
    result = check_locale(observed, expected)
    bad = [c for c in result["checks"] if not c["ok"]]
    return {
        "portfolio": "locale",
        "verdict": "fail" if bad else "pass",
        "ok": result["ok"],
        "reason": f"{len(bad)} locale field mismatch(es)" if bad else "",
        "findings": bad,
    }


def evaluate_security(headers: dict | None, *, https: bool | None = None) -> dict:
    """Passive security observations only. Never probes or exploits a target."""
    if headers is None and https is None:
        return _unknown("security", "no response metadata for safe security checks")
    findings = []
    normalized = {(k or "").strip().lower(): v for k, v in (headers or {}).items()}
    if https is False:
        findings.append({"kind": "not_https", "target": "transport"})
    for name in _SECURITY_HEADERS:
        if name not in normalized or normalized[name] in (None, ""):
            findings.append({"kind": "missing_header", "target": name})
    return {
        "portfolio": "security",
        "verdict": "fail" if findings else "pass",
        "ok": not findings,
        "reason": f"{len(findings)} safe-security finding(s)" if findings else "",
        "findings": findings,
        "probe": False,
    }


def evaluate_compatibility(matrix: dict | None) -> dict:
    """Compatibility portfolio: desktop + mobile viewport evidence (offline).

    Missing matrix stays unknown. Live multi-browser CI still open — never marks
    Gate F complete on its own.
    """
    if not isinstance(matrix, dict) or not matrix:
        return _unknown("compatibility", "no compatibility / viewport matrix evidence")
    desktop = int(matrix.get("desktop") or matrix.get("desktop_or_default") or 0)
    mobile = int(matrix.get("mobile") or matrix.get("mobile_checked") or 0)
    browsers = matrix.get("browsers") if isinstance(matrix.get("browsers"), list) else []
    findings = []
    if desktop <= 0:
        findings.append({"kind": "missing_desktop_viewport", "target": "desktop"})
    if mobile <= 0:
        findings.append({"kind": "missing_mobile_viewport", "target": "mobile"})
    # Optional browser list: if present and empty → fail; absent is fine (unknown only on empty matrix).
    if "browsers" in matrix and not browsers:
        findings.append({"kind": "empty_browser_list", "target": "browsers"})
    return {
        "portfolio": "compatibility",
        "verdict": "fail" if findings else "pass",
        "ok": not findings,
        "reason": f"{len(findings)} compatibility gap(s)" if findings else "",
        "findings": findings,
        "evidence": {"desktop": desktop, "mobile": mobile, "browsers": browsers[:20]},
        "gate_f_complete": False,
    }


def evaluate_portfolios(*, a11y_page=None, visual_report=None, timings=None, budgets=None,
                        locale_observed=None, locale_expected=None, security_headers=None,
                        https=None, compatibility_matrix=None) -> dict:
    """Run all Gate F portfolios. Overall complete only when none are unknown."""
    results = [
        evaluate_a11y(a11y_page),
        evaluate_visual(visual_report),
        evaluate_performance(timings, budgets),
        evaluate_locale(locale_observed, locale_expected),
        evaluate_security(security_headers, https=https),
        evaluate_compatibility(compatibility_matrix),
    ]
    by_name = {row["portfolio"]: row for row in results}
    unknown = [n for n, row in by_name.items() if row["verdict"] == "unknown"]
    failed = [n for n, row in by_name.items() if row["verdict"] == "fail"]
    return {
        "complete": not unknown,
        "ok": not unknown and not failed,
        "unknown": unknown,
        "failed": failed,
        "passed": [n for n, row in by_name.items() if row["verdict"] == "pass"],
        "portfolios": by_name,
    }
