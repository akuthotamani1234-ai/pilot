"""Gate E: controlled failure-classification matrix evidence.

Runs rule classify() over a fixed fixture of failure shapes and records the
category histogram. Not a live failure matrix — gate_e_complete stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "failure_matrix_drill.json"

# Deterministic shapes covering Gate E taxonomy buckets (strings must match classify() rules).
FIXTURES: list[dict] = [
    {"id": "assert-product", "outcome": "failed", "error_type": "AssertionError",
     "error": "AssertionError: price was 10 expected 12", "flaky": False},
    {"id": "opener-unique", "outcome": "failed", "error_type": "AssertionError",
     "error": "AssertionError: The recorded opener must resolve uniquely", "flaky": False},
    {"id": "script-bug", "outcome": "failed", "error_type": "NameError",
     "error": "E   NameError: name 'el' is not defined", "flaky": False},
    {"id": "timeout", "outcome": "failed", "error_type": "TestTimeout",
     "error": "TestTimeout: exceeded 30000ms", "flaky": False},
    {"id": "flaky-pass", "outcome": "failed", "error_type": "AssertionError",
     "error": "AssertionError: not visible", "flaky": True},
    {"id": "session", "outcome": "failed", "error_type": "AssertionError",
     "error": "logged out - the website ended the test account's session during the run",
     "flaky": False},
    {"id": "infra-block", "outcome": "failed", "error_type": "AssertionError",
     "error": "This page has been blocked by security software (Network Attack Defense)",
     "flaky": False},
    {"id": "infra-econn", "outcome": "failed", "error_type": "Error",
     "error": "Error: connect ECONNREFUSED 127.0.0.1:9", "flaky": False},
    {"id": "auth-login", "outcome": "failed", "error_type": "AssertionError",
     "error": "AssertionError: sent me back to the login page after submit", "flaky": False},
    {"id": "test-account", "outcome": "failed", "error_type": "AssertionError",
     "error": "AssertionError: no test account configured; set TEST_USERNAME", "flaky": False},
    {"id": "locator-gone", "outcome": "failed", "error_type": "TimeoutError",
     "error": "Timeout 30000ms exceeded.\nwaiting for locator('button#buy')\nError: element(s) not found",
     "flaky": False},
    {"id": "rule-tag", "outcome": "failed", "error_type": "AssertionError",
     "error": "AssertionError: [rule] irreversible action blocked", "flaky": False},
    {"id": "inconclusive", "outcome": "inconclusive", "error_type": "",
     "error": "Inconclusive: nothing was asserted", "flaky": False},
]


def build_failure_matrix(fixtures: list[dict] | None = None) -> dict:
    from .agents.failure_analysis import classify

    rows = []
    counts: dict[str, int] = {}
    for raw in fixtures or FIXTURES:
        cat, why, conf = classify(raw)
        counts[cat] = counts.get(cat, 0) + 1
        rows.append({
            "id": raw.get("id"),
            "category": cat,
            "confidence": conf,
            "why": (why or "")[:160],
            "flaky": bool(raw.get("flaky")),
            "outcome": raw.get("outcome"),
        })
    return {
        "gate_e_complete": False,
        "drill": "controlled_failure_classification_matrix",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cases": len(rows),
        "counts": counts,
        "rows": rows,
        "reason": (
            "Controlled offline failure taxonomy matrix recorded (incl. auth/infra/test_data/"
            "locator/rule); live failure matrix / production healing still open"
        ),
    }


def run_failure_matrix_drill(*, ops_dir: Path | None = None) -> dict:
    evidence = build_failure_matrix()
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "failure_matrix_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "failure_matrix_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
