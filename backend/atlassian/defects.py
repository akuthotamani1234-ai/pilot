"""Defect intelligence (Requirements Intelligence, Phase 5): requirement test FAILURES -> defect records.

Read only from the stored, REAL results (bridge.req_results): nothing here runs a test or calls Atlassian.

  one defect   per test case and failure signature (the actual result with numbers removed): the same failure in
               a later run is the SAME defect (occurrences, executions, last evidence), never a duplicate
  triage       from the engine's own failure analysis (failure_category):
                 likely_defect   application defect, or the requirement's expected result was not met
                 test_problem    locator / test-script / test-data problem: fix the test, not the application
                 environment     network, timeout, authentication, a third-party resource
                 needs_triage    no classification: a person decides
  lifecycle    open -> resolved (a later run of the same test case passed) -> reopened (failed again: regression)
               dismissed: a person said it is not a defect (with the reason); it stays dismissed
  severity     from the test case (positive / security scenarios: high) - lowered for test problems
Flaky, Blocked, Not automated and Not run results are never defects. Only likely / untriaged defects can be proposed
to Jira (backend/atlassian/writeback.py), and only through a person's approval.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS req_defects (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, test_case_id TEXT NOT NULL, requirement_id TEXT NOT NULL,
    status TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (tenant_id, id));
"""
STATUSES = ("open", "reopened", "resolved", "dismissed")
TRIAGE = (("likely_defect", ("Application defect", "Test assertion failure", "Suspect")),
          ("test_problem", ("Locator", "Test-script", "Test data", "Test mistake")),
          ("environment", ("Infrastructure", "Timeout", "Authentication", "Third-party", "Inconclusive")))
KEEP = ("jira_issue", "write_id", "dismissed_by", "dismissed_at", "dismissed_reason")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def ensure(db) -> None:
    db.executescript(SCHEMA)


def signature(actual: str) -> str:
    text = re.sub(r"\d+", "#", (actual or "").lower())
    return " ".join(text.split())[:160]


def triage(category: str) -> str:
    for name, prefixes in TRIAGE:
        if category.startswith(prefixes):
            return name
    return "needs_triage"


def _severity(case: dict, kind: str) -> str:
    base = "high" if case.get("kind") in ("positive", "security") else "medium"
    return {"test_problem": "low", "environment": "low"}.get(kind, base)


def refresh(db, tenant: str) -> dict:
    """Rebuild the defect records from every stored result (idempotent). Returns counts."""
    from . import bridge
    ensure(db)
    rows = db.execute("SELECT data FROM req_results WHERE tenant_id = ? ORDER BY at, execution_id",
                      (tenant,)).fetchall()
    existing = {d["id"]: d for d in list_defects(db, tenant, refresh_first=False)}
    found: dict[str, dict] = {}
    open_by_case: dict[str, list[str]] = {}
    passed_before: set[str] = set()
    for r in rows:
        res = json.loads(r["data"])
        cid, status = res.get("test_case_id", ""), res.get("status")
        if status == "Passed":
            for did in open_by_case.pop(cid, []):
                d = found[did]
                if d["status"] in ("open", "reopened"):
                    d.update(status="resolved", resolved_at=res["at"], resolved_by_execution=res["execution_id"])
            passed_before.add(cid)
            continue
        if status != "Failed":
            continue
        case = bridge.get_case(db, tenant, cid) or {"id": cid, "requirement_id": "", "title": cid}
        sig = signature(res.get("actual") or res.get("reason") or "")
        did = "DF-" + hashlib.sha1(f"{tenant}|{cid}|{sig}".encode(), usedforsecurity=False).hexdigest()[:10]
        kind = triage(res.get("failure_category") or "")
        if case.get("work_item") == "bug" and kind in ("likely_defect", "needs_triage"):
            kind = "reported_bug_reproduced"  # (it is already in Jira: not a new defect found by Qpilot)
        d = found.get(did)
        if d is None:
            d = {"id": did, "test_case_id": cid, "requirement_id": case.get("requirement_id", ""),
                 "requirement_title": case.get("requirement_title", ""), "connection_id": case.get("connection_id", ""),
                 "criterion_ids": case.get("criterion_ids", []), "signature": sig, "first_seen": res["at"],
                 "executions": [], "occurrences": 0, "status": "open", "regression": cid in passed_before}
            found[did] = d
        elif d["status"] == "resolved":
            d.update(status="reopened", regression=True)
        if res["execution_id"] not in d["executions"]:
            d["executions"].append(res["execution_id"])
            d["occurrences"] += 1
        d.update(last_seen=res["at"], triage=kind, failure_category=res.get("failure_category", ""),
                 confidence=res.get("confidence", ""), severity=_severity(case, kind),
                 title=f"{case.get('requirement_id', '')}: {case.get('title', cid)} - fails"[:240],
                 steps=case.get("steps", []), expected=case.get("expected", ""),
                 actual=res.get("actual") or res.get("reason") or "", evidence=res.get("evidence", []),
                 run_folder=res.get("run_folder", ""), last_execution=res["execution_id"],
                 case_version=res.get("case_version"), source_version=res.get("source_version"))
        if did not in open_by_case.setdefault(cid, []):
            open_by_case[cid].append(did)
    for did, d in found.items():
        old = existing.get(did) or {}
        for k in KEEP:
            if old.get(k):
                d[k] = old[k]
        if old.get("status") == "dismissed":
            d["status"] = "dismissed"
        d.setdefault("created_at", old.get("created_at") or _now())
    with db:
        for d in found.values():
            db.execute("INSERT OR REPLACE INTO req_defects (tenant_id, id, test_case_id, requirement_id, status, "
                       "updated_at, data) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (tenant, d["id"], d["test_case_id"], d["requirement_id"], d["status"], _now(), json.dumps(d)))
    counts: dict[str, int] = {}
    for d in found.values():
        counts[d["status"]] = counts.get(d["status"], 0) + 1
    return counts


def list_defects(db, tenant: str, status: str = "", requirement: str = "", refresh_first: bool = True) -> list[dict]:
    ensure(db)
    if refresh_first:
        refresh(db, tenant)
    sql, args = "SELECT data FROM req_defects WHERE tenant_id = ?", [tenant]
    if status:
        sql += " AND status = ?"
        args.append(status)
    if requirement:
        sql += " AND requirement_id = ?"
        args.append(requirement)
    out = [json.loads(r["data"]) for r in db.execute(sql, args)]
    order = {"reopened": 0, "open": 1, "resolved": 2, "dismissed": 3}
    sev = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda d: (order.get(d["status"], 9), sev.get(d.get("severity"), 9), d["id"]))


def get_defect(db, tenant: str, defect_id: str) -> dict | None:
    ensure(db)
    r = db.execute("SELECT data FROM req_defects WHERE tenant_id = ? AND id = ?", (tenant, defect_id)).fetchone()
    return json.loads(r["data"]) if r else None


def _store(db, tenant: str, d: dict) -> None:
    with db:
        db.execute("UPDATE req_defects SET status = ?, updated_at = ?, data = ? WHERE tenant_id = ? AND id = ?",
                   (d["status"], _now(), json.dumps(d), tenant, d["id"]))


def dismiss(db, tenant: str, defect_id: str, actor: str, reason: str) -> dict:
    d = get_defect(db, tenant, defect_id)
    if not d:
        raise LookupError(defect_id)
    if not (reason or "").strip():
        raise ValueError("say why this is not a defect")
    d.update(status="dismissed", dismissed_by=actor, dismissed_at=_now(), dismissed_reason=reason.strip()[:500])
    _store(db, tenant, d)
    return d


def link_issue(db, tenant: str, defect_id: str, issue_key: str, write_id: str) -> None:
    d = get_defect(db, tenant, defect_id)
    if d:
        d.update(jira_issue=issue_key, write_id=write_id)
        _store(db, tenant, d)


def by_case(db, tenant: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for d in list_defects(db, tenant, refresh_first=False):
        out.setdefault(d["test_case_id"], []).append(d)
    return out
