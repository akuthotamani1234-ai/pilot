"""Requirement-based tests of ONE run (Requirements Intelligence, Phase 4): approved Jira / Confluence scenarios.

The Studio's requirements bridge (backend/atlassian/bridge.py) hands a run its approved, executable test cases in
QA_REQUIREMENT_TESTS (JSON). They are designed exactly like your own plain-English tests (test_design.my_test_cases:
the AI turns each into steps from what exploring really found; without an AI, or when the website has no such page,
the case stays 'Not automated' with the reason) - but they belong to this run only: they are never saved to the
website's own test list, so a later autonomous run does not inherit them.

  QA_REQUIREMENTS_ONLY=1   requirement-based testing: only these cases are designed (no built-in site suite)
  otherwise                hybrid testing: these cases first, then the usual exploratory suite

Every case keeps where it came from (requirement_test = the test case id, requirement = the Jira key / page and the
acceptance criteria), so its real result is reported against the requirement. Imported text is data: it is never
run as code, and a test that would delete, pay or change data is refused exactly like a person's instruction.
"""
from __future__ import annotations

import json
import os
import re

ENV = "QA_REQUIREMENT_TESTS"
ONLY_ENV = "QA_REQUIREMENTS_ONLY"
MAX_TESTS = 60
ID = re.compile(r"^rq_[a-z0-9_]{1,80}$")


def load() -> list[dict]:
    """[{'id': 'rq_…', 'text': plain-English test, 'tc': test case id, 'requirement': 'QPL-2', 'criteria': [...]}]"""
    raw = os.environ.get(ENV, "")
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        print("  [run] the requirement tests could not be read (not JSON) - none are used", flush=True)
        return []
    out = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        tid, text = str(item.get("id", "")), " ".join(str(item.get("text", "")).split())
        if not ID.match(tid) or not text or tid in {t["id"] for t in out}:
            continue
        out.append({"id": tid, "text": text[:2000], "tc": str(item.get("tc", ""))[:80],
                    "requirement": str(item.get("requirement", ""))[:80],
                    "criteria": [str(c)[:80] for c in (item.get("criteria") or [])][:10],
                    "title": str(item.get("title", ""))[:200]})
        if len(out) >= MAX_TESTS:
            break
    return out


def only() -> bool:
    return os.environ.get(ONLY_ENV) == "1" and bool(load())


def label(cases: list[dict], tests: list[dict]) -> list[dict]:
    """Mark the designed cases with the requirement they test (the report and the bridge read these fields)."""
    by_id = {t["id"]: t for t in tests}
    for case in cases:
        t = by_id.get(str(case.get("my_test", "")))
        if not t:
            continue
        case["requirement_test"] = t["tc"]
        case["origin"] = "requirement"
        case["requirement"] = t["requirement"] + (f" ({', '.join(c.split('#')[-1] for c in t['criteria'])})"
                                                  if t["criteria"] else "")
        case["feature"] = f"Requirement {t['requirement']}"
        case["element"] = "approved requirement scenario"
        if t["title"]:
            case["title"] = t["title"]
    return cases
