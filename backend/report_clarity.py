"""Honest report labels: keep PASS / FAIL / BLOCKED / SKIPPED / NOT TESTED / INCONCLUSIVE separate,
and surface coverage limits without inventing site-wide accuracy percentages.
"""
from __future__ import annotations

CLARITY_STATUSES = ("PASS", "FAIL", "BLOCKED", "SKIPPED", "NOT TESTED", "INCONCLUSIVE")

# Designed test-case execution_status -> clarity bucket (Flaky counts under FAIL: it failed at least once).
CASE_TO_CLARITY = {
    "Passed": "PASS",
    "Failed": "FAIL",
    "Flaky": "FAIL",
    "Blocked": "BLOCKED",
    "Skipped": "SKIPPED",
    "Not run": "NOT TESTED",
    "Pending": "NOT TESTED",
    "Inconclusive": "INCONCLUSIVE",
}

# Feature registry status -> clarity bucket.
FEATURE_TO_CLARITY = {
    "verified": "PASS",
    "failed": "FAIL",
    "blocked": "BLOCKED",
    "skipped": "SKIPPED",
    "inconclusive": "INCONCLUSIVE",
    "smoke": "PASS",  # passed, but only a weak check - still not FAIL / NOT TESTED
    "suspect": "INCONCLUSIVE",
    "rule_violation": "INCONCLUSIVE",
    "needs_login": "NOT TESTED",
    "clicked_only": "NOT TESTED",
    "test_generated": "NOT TESTED",
    "unresolved": "NOT TESTED",
}


def _empty_counts() -> dict[str, int]:
    return dict.fromkeys(CLARITY_STATUSES, 0)


def case_status_counts(test_cases: dict | None = None, cases: list[dict] | None = None) -> dict:
    """Clarity counts for designed test cases. Prefer the metrics test_cases dict when available."""
    out = _empty_counts()
    flaky = 0
    if test_cases is not None:
        out["PASS"] = int(test_cases.get("passed") or 0)
        flaky = int(test_cases.get("flaky") or 0)
        out["FAIL"] = int(test_cases.get("failed") or 0) + flaky
        out["BLOCKED"] = int(test_cases.get("blocked") or 0)
        out["SKIPPED"] = int(test_cases.get("skipped") or 0)
        out["NOT TESTED"] = int(test_cases.get("not_run") or 0) + int(test_cases.get("pending") or 0)
        out["INCONCLUSIVE"] = int(test_cases.get("inconclusive") or 0)
        planned = int(test_cases.get("planned") or sum(out.values()))
    else:
        for c in cases or []:
            label = CASE_TO_CLARITY.get(c.get("execution_status") or "Not run", "NOT TESTED")
            out[label] = out.get(label, 0) + 1
            if c.get("execution_status") == "Flaky":
                flaky += 1
        planned = len(cases or [])
    return {
        **out,
        "planned": planned,
        "flaky_included_in_FAIL": flaky,
        "labels": list(CLARITY_STATUSES),
        "note": "PASS/FAIL/BLOCKED/SKIPPED/NOT TESTED/INCONCLUSIVE are counted separately; Flaky is included in FAIL.",
    }


def _feature_counts_dict(feature_counts: dict | None) -> dict:
    """Accept registry counts ({pages, features}), a features-counts dict, or a features map."""
    feature_counts = feature_counts or {}
    if isinstance(feature_counts.get("features"), dict) and (
            "discovered" in feature_counts["features"] or "verified" in feature_counts["features"]):
        return feature_counts["features"]
    return feature_counts


def feature_status_counts(features: dict | None) -> dict:
    """Clarity counts for registered features (registry counts or a features map)."""
    out = _empty_counts()
    features = _feature_counts_dict(features)
    if features and ("discovered" in features
                     or any(k in features for k in ("verified", "failed", "blocked", "unresolved"))):
        mapping = (
            ("verified", "PASS"), ("smoke", "PASS"), ("failed", "FAIL"), ("blocked", "BLOCKED"),
            ("skipped", "SKIPPED"), ("inconclusive", "INCONCLUSIVE"), ("suspect", "INCONCLUSIVE"),
            ("rule_violation", "INCONCLUSIVE"), ("needs_login", "NOT TESTED"), ("clicked_only", "NOT TESTED"),
            ("test_generated", "NOT TESTED"), ("unresolved", "NOT TESTED"),
        )
        for key, label in mapping:
            out[label] += int(features.get(key) or 0)
        discovered = int(features.get("discovered") or sum(out.values()))
    else:
        for feat in features.values() if isinstance(features, dict) else []:
            if not isinstance(feat, dict):
                continue
            label = FEATURE_TO_CLARITY.get(feat.get("status") or "unresolved", "NOT TESTED")
            out[label] = out.get(label, 0) + 1
        discovered = sum(out.values())
    return {
        **out,
        "discovered": discovered,
        "labels": list(CLARITY_STATUSES),
        "note": "Feature outcomes stay separate: blocked / skipped / not tested / inconclusive are never counted as PASS.",
    }


def pages_coverage(crawl: dict | None, app_map: list | None = None) -> dict:
    """Pages discovered / visited / not visited - never one mixed 'site coverage %'."""
    crawl = crawl or {}
    visited = len(app_map) if app_map is not None else int(crawl.get("visited") or 0)
    not_visited = int(crawl.get("not_visited_count") or 0)
    discovered = visited + not_visited
    return {
        "discovered": discovered,
        "visited": visited,
        "not_visited": not_visited,
        "limit_reached": bool(crawl.get("limit_reached")),
        "time_limit_reached": bool(crawl.get("time_limit_reached")),
        "sampled": int(crawl.get("sampled") or 0),
        "note": "Visited pages are not proof that every feature or workflow on those pages was tested.",
    }


def coverage_limitations(*, crawl: dict | None = None, limits: list[dict] | None = None,
                         incomplete: bool = False, discovery_only: bool = False,
                         feature_counts: dict | None = None) -> dict:
    """When crawl/time limits leave work undone, say so plainly. Never invent a complete-site claim."""
    crawl = crawl or {}
    limits = limits or []
    exploration = crawl.get("exploration") or {}
    pages = pages_coverage(crawl)
    feats = feature_status_counts(feature_counts)
    not_tested_features = (feats.get("NOT TESTED", 0) + feats.get("BLOCKED", 0) + feats.get("SKIPPED", 0)
                           + feats.get("INCONCLUSIVE", 0))
    partial = bool(
        discovery_only or incomplete or limits or pages["not_visited"] > 0
        or exploration.get("status") == "partial"
        or not exploration.get("within_selected_scope", pages["not_visited"] == 0)
    )
    if discovery_only:
        statement = ("Discovery only: pages and components were observed, but functionality was not tested. "
                     "A separate test run is required for PASS/FAIL evidence.")
    elif incomplete:
        statement = ("This run did not finish. What was not reached is not tested and is not counted as passed.")
    elif pages["not_visited"] > 0 or limits:
        bits = []
        if pages["not_visited"] > 0:
            bits.append(f"{pages['not_visited']} discovered page(s) were not visited")
        if limits:
            bits.append(f"{len(limits)} limit(s) shortened the run")
        statement = ("Coverage is incomplete: " + "; ".join(bits)
                     + ". This report does not claim the entire site or app was tested.")
    elif exploration.get("status") == "partial":
        statement = (exploration.get("statement")
                     or "Exploration is partial; inspect unvisited routes and recorded limits.")
    else:
        statement = (exploration.get("statement")
                     or "All discovered routes were processed within the selected scope and exploration budgets.")
    limitation = (exploration.get("limitation")
                  or "Route discovery is not proof that every component state or business workflow was tested.")
    return {
        "partial": partial,
        "claims_complete_product_coverage": False,
        "discovery_only": bool(discovery_only),
        "incomplete": bool(incomplete),
        "pages": pages,
        "features_not_pass": not_tested_features,
        "limits_hit": [{"id": x.get("id"), "limit": x.get("limit")} for x in limits],
        "exploration_status": exploration.get("status"),
        "statement": statement,
        "limitation": limitation,
    }


def build(*, crawl: dict | None = None, app_map: list | None = None, limits: list[dict] | None = None,
          incomplete: bool = False, discovery_only: bool = False, test_cases: dict | None = None,
          cases: list[dict] | None = None, feature_counts: dict | None = None) -> dict:
    """One additive clarity block for summary.json / discovery summary / HTML."""
    return {
        "result_status_counts": case_status_counts(test_cases, cases),
        "feature_status_counts": feature_status_counts(feature_counts),
        "pages_coverage": pages_coverage(crawl, app_map),
        "coverage_limitations": coverage_limitations(
            crawl=crawl, limits=limits, incomplete=incomplete, discovery_only=discovery_only,
            feature_counts=feature_counts),
    }
