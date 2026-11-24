"""Requirements -> executable tests -> real runs -> results (Requirements Intelligence, Phases 4-5).

  test cases   generate(): every ACCEPTED scenario of a requirement's CURRENT analysis becomes one stored test case
               (id TC-<KEY>-<n>) with the Jira key / Confluence page, criterion ids, source version, the quoted source
               words, the reviewer and approval time, preconditions, steps, expected result, test data needs and
               assertions. Rejected / unreviewed ideas never become test cases. The same idea again -> the same test
               case (no duplicates); changed wording -> a new version (history kept).
  staleness    refresh(): a test case whose requirement has a newer source version, whose analysis is out of date,
               or whose scenario is no longer accepted becomes STALE - it is not run silently; it waits for
               re-analysis / re-review and a new generation.
  executions   plan(): the chosen test cases + a target + a strategy -> the plain-English instructions handed to the
               EXISTING Qpilot run (server.start_run; backend/requirement_tests.py): the same discovery, AI test
               design, Playwright execution, evidence and reports as every Qpilot run. Nothing here executes a test.
  results      collect(): after the run, each test case gets the run's REAL result for its case (Passed / Failed /
               Blocked / Not run / Not automated), with the actual result and evidence files. A test case is never
               'passed' without an executed case that passed.
  trace        matrix(): requirement -> criterion -> test case -> latest execution -> evidence (+ defect proposals).

Strategies: requirements (only the selected requirement tests), autonomous (the usual Qpilot run, no requirement tests),
hybrid (requirement tests first, then the usual exploration; results labelled by origin).
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .. import audit_store
from . import analysis as an, store
from .models import ReviewStatus, normalize_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS req_test_cases (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, requirement_id TEXT NOT NULL, status TEXT NOT NULL,
    fingerprint TEXT NOT NULL, version INTEGER NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id));
CREATE INDEX IF NOT EXISTS req_test_cases_by_req ON req_test_cases (tenant_id, requirement_id);
CREATE TABLE IF NOT EXISTS req_test_case_history (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL, at TEXT NOT NULL, event TEXT NOT NULL,
    data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS req_executions (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, status TEXT NOT NULL, run_id TEXT NOT NULL, created_at TEXT NOT NULL,
    data TEXT NOT NULL, PRIMARY KEY (tenant_id, id));
CREATE TABLE IF NOT EXISTS req_results (
    tenant_id TEXT NOT NULL, execution_id TEXT NOT NULL, test_case_id TEXT NOT NULL, status TEXT NOT NULL,
    at TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (tenant_id, execution_id, test_case_id));
CREATE INDEX IF NOT EXISTS req_results_by_case ON req_results (tenant_id, test_case_id, at);
"""

ACTION = "requirements.tests"
STRATEGIES = ("requirements", "autonomous", "hybrid")
# test-case lifecycle (the run itself has queued / running / finished; each RESULT is Passed, Failed, ...)
STATUSES = ("draft", "awaiting_approval", "approved", "ready", "stale", "requires_review", "blocked")
RESULTS = ("Passed", "Failed", "Blocked", "Skipped", "Not run", "Not automated", "Flaky", "Cancelled")
# test data a scenario needs that the requirement does not give (asked for in the execution setup, never invented)
NEEDS = (("a test account (username and password)", re.compile(r"\b(log ?in|sign ?in|password|username|user name|"
                                                                r"credentials?|account)\b", re.I)),
         ("checkout details (name, address or postal code)", re.compile(r"\b(checkout|shipping|address|postal|zip|"
                                                                        r"first name|last name)\b", re.I)),
         ("payment details", re.compile(r"\b(card number|credit card|payment details|cvv)\b", re.I)))


def connect(path=None):
    db = store.connect(path)
    db.executescript(SCHEMA)
    return db


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _audit(actor: str, tenant: str, allowed: bool, detail: dict, audit_db=None) -> None:
    try:
        audit_store.record_audit(actor=actor or "system", action=ACTION, allowed=allowed, tenant_id=tenant,
                                 detail=json.dumps(detail, default=str)[:1500],
                                 **({"db_path": audit_db} if audit_db else {}))
    except Exception:
        pass


# ---------------------------------------------------------------- test cases

def _row(r) -> dict:
    data = json.loads(r["data"])
    data.update(status=r["status"], version=r["version"])
    return data


def get_case(db, tenant: str, case_id: str) -> dict | None:
    r = db.execute("SELECT * FROM req_test_cases WHERE tenant_id = ? AND id = ?", (tenant, case_id)).fetchone()
    return _row(r) if r else None


def list_cases(db, tenant: str, requirement_id: str = "", status: str = "") -> list[dict]:
    q, args = "SELECT * FROM req_test_cases WHERE tenant_id = ?", [tenant]
    if requirement_id:
        q += " AND requirement_id = ?"
        args.append(requirement_id)
    if status:
        q += " AND status = ?"
        args.append(status)
    rows = [_row(r) for r in db.execute(q, args)]
    rows.sort(key=lambda c: (c["requirement_id"], int(re.sub(r"\D", "", c["id"].rsplit("-", 1)[-1]) or 0)))
    for c in rows:
        c["latest_result"] = latest_result(db, tenant, c["id"])
    return rows


def case_history(db, tenant: str, case_id: str) -> list[dict]:
    rows = db.execute("SELECT version, at, event FROM req_test_case_history WHERE tenant_id = ? AND id = ? "
                      "ORDER BY rowid", (tenant, case_id))
    return [dict(r) for r in rows]


def _save(db, tenant: str, case: dict, event: str) -> None:
    data = {k: v for k, v in case.items() if k not in ("status", "version", "latest_result")}
    body = json.dumps(data, sort_keys=True, default=str)
    with db:
        db.execute("INSERT INTO req_test_cases (tenant_id, id, requirement_id, status, fingerprint, version, "
                   "updated_at, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (tenant_id, id) DO UPDATE SET "
                   "status = excluded.status, fingerprint = excluded.fingerprint, version = excluded.version, "
                   "updated_at = excluded.updated_at, data = excluded.data",
                   (tenant, case["id"], case["requirement_id"], case["status"], case["fingerprint"],
                    case["version"], _now(), body))
        db.execute("INSERT INTO req_test_case_history (tenant_id, id, version, at, event, data) VALUES "
                   "(?, ?, ?, ?, ?, ?)", (tenant, case["id"], case["version"], _now(), event[:200], body))


def _content_fp(case: dict) -> str:
    raw = json.dumps([case["title"], case["steps"], case["expected"], case["preconditions"], case["criterion_ids"],
                      case.get("test_data_needs", [])], sort_keys=True)
    return hashlib.sha256(normalize_text(raw).encode()).hexdigest()


def instruction(case: dict) -> str:
    """The plain-English test the Qpilot run designs and executes (data only: it is never code)."""
    parts = [case["title"].rstrip(".") + "."]
    if case["preconditions"]:
        parts.append("Preconditions: " + "; ".join(case["preconditions"]) + ".")
    if case["steps"]:
        parts.append("Steps: " + "; ".join(s.rstrip(".") for s in case["steps"]) + ".")
    if case["expected"]:
        parts.append("Expected: " + case["expected"].rstrip(".") + ".")
    if case.get("assertions"):
        parts.append("Check: " + "; ".join(case["assertions"]) + ".")
    return " ".join(parts)[:1800]


def generate(db, tenant: str, requirement_id: str, *, actor: str = "system", audit_db=None) -> dict:
    """Accepted scenarios of a requirement's current analysis -> stored executable test cases."""
    analysis = store.get_analysis(db, tenant, requirement_id)
    if analysis is None:
        raise LookupError(f"{requirement_id} has not been analysed")
    reasons = an.stale(db, tenant, analysis)
    if reasons:
        raise ValueError("the requirement changed since it was analysed - analyse and review it again first: "
                         + "; ".join(reasons)[:300])
    from ..objective import destructive
    root = analysis.requirement.sources[0]
    criteria = {c.id: c for c in analysis.requirement.criteria}
    existing = {c["suggestion_fingerprint"]: c for c in list_cases(db, tenant, requirement_id)}
    used_numbers = [int(c["id"].rsplit("-", 1)[-1]) for c in existing.values()]
    accepted = [s for s in analysis.suggestions if s.review == ReviewStatus.accepted]
    out = {"requirement": requirement_id, "created": [], "updated": [], "unchanged": [], "stale": [], "skipped": []}
    seen = set()
    for s in accepted:
        cited = [criteria[c] for c in s.criterion_ids if c in criteria]
        if not cited:
            out["skipped"].append(f"{s.id}: its criteria are gone")
            continue
        quotes = [{"criterion": c.id, "text": c.text, "quote": c.citations[0].quote,
                   "source": c.citations[0].source.source_id, "kind": c.citations[0].source.kind.value,
                   "version": c.citations[0].source.version, "locator": c.citations[0].locator,
                   "url": c.citations[0].source.url} for c in cited]
        words = " ".join([s.title, *s.steps, s.expected_outcome, *(c.text for c in cited)])
        needs = [label for label, rx in NEEDS if rx.search(words)]
        blocked = []
        if not all(c.automatable for c in cited):
            blocked.append("; ".join(c.not_automatable_reason for c in cited if not c.automatable))
        if destructive(words) or s.destructive:
            blocked.append(f"changes or destroys data ('{destructive(words) or s.destructive}') - only on a staging "
                           "copy with explicit permission")
        steps = list(s.steps) or [f"Use the application as described: {cited[0].text}"]
        expected = s.expected_outcome or "; ".join(c.then or c.text for c in cited)
        case = {
            "tenant_id": tenant, "requirement_id": requirement_id, "connection_id": root.connection_id,
            "source_key": root.key, "source_kind": root.kind.value, "source_id": root.source_id,
            "source_version": analysis.source_versions.get(root.key, root.version),
            "source_versions": analysis.source_versions, "requirement_title": analysis.requirement.title,
            "criterion_ids": list(s.criterion_ids), "suggestion_id": s.id, "suggestion_fingerprint": s.fingerprint,
            "approval_id": s.approval_id, "reviewer": s.reviewer or s.edited_by, "edited_by": s.edited_by,
            "kind": s.kind.value, "basis": s.basis.value, "origin": s.origin, "title": s.title,
            "preconditions": [*(["Signed in with the test account"] if needs and needs[0].startswith("a test") else [])],
            "steps": steps, "expected": expected, "expected_basis": s.basis.value,
            "assertions": [f"{c.id.split('#')[-1]}: {c.then or c.text}" for c in cited],
            "test_data_needs": needs, "evidence": quotes, "platform": "web",
            "automation": "manual" if blocked else "automated", "blocked_reason": " | ".join(blocked),
            "priority": "high" if s.kind.value in ("positive", "security") else "medium",
        }
        fp = _content_fp(case)
        old = existing.get(s.fingerprint)
        seen.add(s.fingerprint)
        if old and old["fingerprint"] == fp and old["status"] != "stale":
            out["unchanged"].append(old["id"])
            continue
        n = int(old["id"].rsplit("-", 1)[-1]) if old else (max(used_numbers, default=0) + 1)
        used_numbers.append(n)
        case.update(id=f"TC-{requirement_id}-{n}", fingerprint=fp, version=(old["version"] + 1) if old else 1,
                    created_at=old.get("created_at", _now()) if old else _now(), approved_at=_now(),
                    status="blocked" if blocked else "approved")
        _save(db, tenant, case, "regenerated (requirement or scenario changed)" if old else "generated from "
              f"approved scenario {s.id} (reviewed by {case['reviewer'] or 'unknown'})")
        out["updated" if old else "created"].append(case["id"])
    for fp, old in existing.items():  # (scenarios no longer accepted, or gone with a changed requirement)
        if fp not in seen and old["status"] != "stale":
            old.update(status="stale", stale_reason="its scenario is no longer accepted in the current analysis")
            _save(db, tenant, old, "stale: scenario no longer accepted")
            out["stale"].append(old["id"])
    _audit(actor, tenant, True, {"generate": requirement_id, **{k: len(v) for k, v in out.items() if k != "requirement"}},
           audit_db)
    return out


def refresh(db, tenant: str) -> list[str]:
    """Mark test cases STALE whose requirement source moved on or whose analysis is out of date (not run silently)."""
    changed = []
    for c in [_row(r) for r in db.execute("SELECT * FROM req_test_cases WHERE tenant_id = ? AND status != 'stale'",
                                          (tenant,))]:
        why = ""
        for key, version in (c.get("source_versions") or {c["source_key"]: c["source_version"]}).items():
            now = store.get_source(db, tenant, key)
            if not now:
                why = f"{key.split(':')[-1]} is no longer imported"
            elif not now["present"]:
                why = f"{key.split(':')[-1]} is no longer visible in Atlassian"
            elif now["source"].version != version:
                why = f"{key.split(':')[-1]} changed: version {version} -> {now['source'].version}"
            if why:
                break
        if why:
            c.update(status="stale", stale_reason=why)
            _save(db, tenant, c, f"stale: {why}")
            changed.append(c["id"])
    return changed


def edit_case(db, tenant: str, case_id: str, changes: dict, editor: str) -> dict:
    """A person corrects a test case: a new version that waits for approval again (its source links stay)."""
    case = get_case(db, tenant, case_id)
    if not case:
        raise LookupError(case_id)
    if case["status"] == "stale":
        raise ValueError("a stale test case is regenerated from the re-analysed requirement, not edited")
    for k in ("title", "preconditions", "steps", "expected", "assertions"):
        if k in changes and changes[k] is not None:
            case[k] = changes[k]
    case.update(edited_by=editor, version=case["version"] + 1, status="awaiting_approval",
                fingerprint=_content_fp(case))
    _save(db, tenant, case, f"edited by {editor}")
    return case


def approve_case(db, tenant: str, case_id: str, reviewer: str) -> dict:
    case = get_case(db, tenant, case_id)
    if not case:
        raise LookupError(case_id)
    if case["status"] not in ("awaiting_approval", "requires_review"):
        raise ValueError(f"{case_id} is {case['status']}, not waiting for approval")
    case.update(status="blocked" if case.get("blocked_reason") else "approved", reviewer=reviewer,
                approved_at=_now())
    _save(db, tenant, case, f"approved by {reviewer}")
    return case


# ---------------------------------------------------------------- executions

def _ready(case: dict) -> str:
    """'' when the case may run, else why not."""
    if case["status"] == "stale":
        return "stale: " + case.get("stale_reason", "the requirement changed")
    if case["status"] in ("awaiting_approval", "requires_review", "draft"):
        return "waiting for approval"
    if case["status"] == "blocked":
        return "blocked: " + (case.get("blocked_reason") or "not automatable")
    return ""


def plan(db, tenant: str, case_ids: list[str], strategy: str, target: dict, *, actor: str = "system") -> dict:
    """Record an execution and return the instructions for the existing Qpilot run. Stale / unapproved / blocked
    cases are listed as not run (with the reason) and never handed to the run."""
    if strategy not in STRATEGIES:
        raise ValueError("strategy is requirements, autonomous or hybrid")
    refresh(db, tenant)
    cases, excluded = [], []
    for cid in dict.fromkeys(case_ids):
        c = get_case(db, tenant, cid)
        if not c:
            raise LookupError(f"{cid} is not a test case of this workspace")
        why = _ready(c)
        (excluded.append({"id": cid, "reason": why}) if why else cases.append(c))
    if strategy != "autonomous" and not cases:
        raise ValueError("no selected test case can run: " + "; ".join(f"{x['id']} {x['reason']}" for x in excluded)[:400])
    execution = {"id": "EX-" + uuid.uuid4().hex[:10], "tenant_id": tenant, "strategy": strategy,
                 "case_ids": [c["id"] for c in cases], "excluded": excluded, "actor": actor, "created_at": _now(),
                 "case_versions": {c["id"]: c["version"] for c in cases},
                 "source_versions": {c["id"]: c["source_version"] for c in cases},
                 "target": {k: v for k, v in target.items() if k not in ("test_password", "api_key")},
                 "requirements": sorted({c["requirement_id"] for c in cases}), "status": "queued", "run_id": ""}
    tests = [] if strategy == "autonomous" else [
        {"id": "rq_" + re.sub(r"[^a-z0-9_]", "_", c["id"].lower()), "text": instruction(c), "tc": c["id"],
         "requirement": c["requirement_id"], "criteria": c["criterion_ids"], "title": c["title"]} for c in cases]
    with db:
        db.execute("INSERT INTO req_executions (tenant_id, id, status, run_id, created_at, data) VALUES "
                   "(?, ?, ?, ?, ?, ?)", (tenant, execution["id"], "queued", "", execution["created_at"],
                                          json.dumps(execution)))
    return {"execution": execution, "requirement_tests": tests}


def attach_run(db, tenant: str, execution_id: str, run_id: str, status: str = "running") -> None:
    ex = get_execution(db, tenant, execution_id)
    if not ex:
        raise LookupError(execution_id)
    ex.update(run_id=run_id, status=status, started_at=_now())
    with db:
        db.execute("UPDATE req_executions SET status = ?, run_id = ?, data = ? WHERE tenant_id = ? AND id = ?",
                   (status, run_id, json.dumps(ex), tenant, execution_id))


def get_execution(db, tenant: str, execution_id: str) -> dict | None:
    r = db.execute("SELECT data, status FROM req_executions WHERE tenant_id = ? AND id = ?",
                   (tenant, execution_id)).fetchone()
    if not r:
        return None
    data = json.loads(r["data"])
    data["status"] = r["status"]
    return data


def list_executions(db, tenant: str, limit: int = 50) -> list[dict]:
    rows = db.execute("SELECT data, status FROM req_executions WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                      (tenant, max(1, min(500, limit))))
    out = []
    for r in rows:
        d = json.loads(r["data"])
        d["status"] = r["status"]
        out.append(d)
    return out


def _result_status(case: dict) -> str:
    """The run's own result for a case. A case that never executed (skipped as not automated, blocked, not run) is
    reported as such - never as executed."""
    status = str(case.get("execution_status") or "").strip()
    reason = str(case.get("skip_reason", ""))
    if status in ("Not run", "Skipped", ""):
        if reason.startswith(("Not automated", "Needs clarif")):
            return "Not automated"
        if reason.startswith("Blocked"):
            return "Blocked"
    return status if status in RESULTS else "Not run"


def collect(db, tenant: str, execution_id: str, run_dir: Path, run_status: str = "done") -> dict:
    """Read the REAL results of the finished run and record one result per requirement test case."""
    ex = get_execution(db, tenant, execution_id)
    if not ex:
        raise LookupError(execution_id)
    run_cases = []
    f = Path(run_dir) / "test_cases.json"
    if f.is_file() and not f.is_symlink():
        try:
            run_cases = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            run_cases = []
    by_tc = {}
    for c in run_cases if isinstance(run_cases, list) else []:
        if isinstance(c, dict) and c.get("requirement_test"):
            by_tc[c["requirement_test"]] = c
    counts: dict[str, int] = {}
    for cid in ex["case_ids"]:
        c = by_tc.get(cid)
        if c is None:
            status = "Cancelled" if run_status in ("stopped", "cancelled") else "Not run"
            result = {"status": status, "reason": "the run ended before this test case was designed or executed"
                      if run_status in ("stopped", "cancelled") else "the run did not produce this test case",
                      "evidence": [], "actual": "", "run_case": ""}
        else:
            status = _result_status(c)
            result = {"status": status, "actual": str(c.get("actual_result") or "")[:2000],
                      "reason": str(c.get("skip_reason") or "")[:500], "expected": str(c.get("expected") or "")[:1000],
                      "steps": c.get("steps") or [], "evidence": [str(e) for e in c.get("evidence") or []][:20],
                      "run_case": str(c.get("tc_id") or c.get("id") or ""), "checks": c.get("check_count"),
                      "verification": c.get("verification"), "type": c.get("type"),
                      "failure_category": str(c.get("failure_category") or "")[:120],
                      "confidence": str(c.get("confidence") or "")[:20]}
        counts[status] = counts.get(status, 0) + 1
        result.update(execution_id=execution_id, test_case_id=cid, run_id=ex.get("run_id", ""), at=_now(),
                      case_version=(ex.get("case_versions") or {}).get(cid),
                      source_version=(ex.get("source_versions") or {}).get(cid), run_folder=Path(run_dir).name)
        with db:
            db.execute("INSERT OR REPLACE INTO req_results (tenant_id, execution_id, test_case_id, status, at, data) "
                       "VALUES (?, ?, ?, ?, ?, ?)", (tenant, execution_id, cid, status, result["at"],
                                                     json.dumps(result, default=str)))
    exploratory = [c for c in run_cases if isinstance(c, dict) and not c.get("requirement_test")] \
        if isinstance(run_cases, list) else []
    ex.update(status="finished" if run_status == "done" else run_status, finished_at=_now(), counts=counts,
              exploratory={"cases": len(exploratory),
                           "failed": sum(1 for c in exploratory if c.get("execution_status") == "Failed"),
                           "passed": sum(1 for c in exploratory if c.get("execution_status") == "Passed")})
    with db:
        db.execute("UPDATE req_executions SET status = ?, data = ? WHERE tenant_id = ? AND id = ?",
                   (ex["status"], json.dumps(ex), tenant, execution_id))
    return ex


def results(db, tenant: str, execution_id: str) -> list[dict]:
    rows = db.execute("SELECT data FROM req_results WHERE tenant_id = ? AND execution_id = ? ORDER BY test_case_id",
                      (tenant, execution_id))
    return [json.loads(r["data"]) for r in rows]


def latest_result(db, tenant: str, case_id: str) -> dict | None:
    r = db.execute("SELECT data FROM req_results WHERE tenant_id = ? AND test_case_id = ? ORDER BY at DESC LIMIT 1",
                   (tenant, case_id)).fetchone()
    return json.loads(r["data"]) if r else None


def case_results(db, tenant: str, case_id: str) -> list[dict]:
    rows = db.execute("SELECT data FROM req_results WHERE tenant_id = ? AND test_case_id = ? ORDER BY at DESC",
                      (tenant, case_id))
    return [json.loads(r["data"]) for r in rows]


# ---------------------------------------------------------------- traceability and coverage

def matrix(db, tenant: str) -> list[dict]:
    """One row per (requirement, criterion, test case) with the latest real result; criteria without tests too."""
    from . import defects as dfx
    refresh(db, tenant)
    dfx.refresh(db, tenant)
    found = dfx.by_case(db, tenant)
    rows = []
    cases = list_cases(db, tenant)
    by_req: dict[str, list[dict]] = {}
    for c in cases:
        by_req.setdefault(c["requirement_id"], []).append(c)
    for a in store.list_analyses(db, tenant):
        root = a.requirement.sources[0]
        stale = bool(an.stale(db, tenant, a))
        for crit in a.requirement.criteria:
            tcs = [c for c in by_req.get(a.requirement.id, []) if crit.id in c["criterion_ids"]]
            base = {"requirement": a.requirement.id, "summary": a.requirement.title, "connection_id": root.connection_id,
                    "source": root.source_id, "source_kind": root.kind.value,
                    "source_version": a.source_versions.get(root.key), "criterion": crit.id, "criterion_text": crit.text,
                    "locator": crit.citations[0].locator, "analysis_stale": stale,
                    "approval": a.coverage.get(crit.id).value if a.coverage.get(crit.id) else ""}
            if not tcs:
                rows.append({**base, "test_case": "", "test_status": "", "result": "", "last_run": "", "evidence": [],
                             "defects": [],
                             "coverage": "not automatable" if not crit.automatable else "no approved test"})
                continue
            for c in tcs:
                r = c.get("latest_result") or {}
                status = r.get("status", "")
                coverage = ("stale" if c["status"] == "stale" else "passed" if status == "Passed" else
                            "failed" if status in ("Failed", "Flaky") else "blocked" if c["status"] == "blocked"
                            or status == "Blocked" else "not automated" if status == "Not automated" else "planned")
                rows.append({**base, "test_case": c["id"], "test_title": c["title"], "test_status": c["status"],
                             "result": r.get("status", ""), "last_run": r.get("at", ""), "run_id": r.get("run_id", ""),
                             "execution_id": r.get("execution_id", ""), "evidence": r.get("evidence", []),
                             "run_folder": r.get("run_folder", ""),
                             "defects": [{"id": d["id"], "status": d["status"], "jira_issue": d.get("jira_issue", "")}
                                         for d in found.get(c["id"], [])],
                             "coverage": coverage})
    return rows


def coverage(db, tenant: str) -> dict:
    """Separate counts: planned (approved tests), executed, passed - approved ideas are never 'executed'."""
    reqs = {}
    imported = [r for r in store.list_sources(db, tenant) if r["source"].kind.value == "jira_issue"]
    for r in imported:
        reqs[r["source"].source_id] = {"analysed": False, "criteria": 0, "approved_scenarios": 0, "test_cases": 0,
                                       "executed": 0, "passed": 0, "failed": 0, "blocked": 0, "stale": False}
    for a in store.list_analyses(db, tenant):
        d = reqs.setdefault(a.requirement.id, {"analysed": False, "criteria": 0, "approved_scenarios": 0,
                                               "test_cases": 0, "executed": 0, "passed": 0, "failed": 0, "blocked": 0,
                                               "stale": False})
        d.update(analysed=True, criteria=len(a.requirement.criteria),
                 approved_scenarios=sum(1 for s in a.suggestions if s.review == ReviewStatus.accepted),
                 stale=bool(an.stale(db, tenant, a)))
    refresh(db, tenant)
    for c in list_cases(db, tenant):
        d = reqs.get(c["requirement_id"])
        if d is None:
            continue
        d["test_cases"] += 1
        d["stale"] = d["stale"] or c["status"] == "stale"
        r = c.get("latest_result") or {}
        if r.get("status") in ("Passed", "Failed", "Flaky"):
            d["executed"] += 1
        d["passed"] += r.get("status") == "Passed"
        d["failed"] += r.get("status") == "Failed"
        d["blocked"] += c["status"] == "blocked" or r.get("status") == "Blocked"
    n = len(reqs)

    def count(pred):
        return sum(1 for d in reqs.values() if pred(d))
    return {"requirements": n, "analysed": count(lambda d: d["analysed"]),
            "with_criteria": count(lambda d: d["criteria"] > 0),
            "with_approved_scenarios": count(lambda d: d["approved_scenarios"] > 0),
            "with_test_cases": count(lambda d: d["test_cases"] > 0),
            "executed": count(lambda d: d["executed"] > 0),
            "passed": count(lambda d: d["test_cases"] and d["passed"] == d["test_cases"]),
            "failed": count(lambda d: d["failed"] > 0), "blocked": count(lambda d: d["blocked"] > 0),
            "not_tested": count(lambda d: d["executed"] == 0),
            "needs_revalidation": count(lambda d: d["stale"]), "by_requirement": reqs,
            "basis": "planned = approved test cases; executed = a real run executed them; passed = every test case of "
                     "the requirement passed in its latest run"}


def impacted(db, tenant: str) -> list[dict]:
    """Test cases whose requirement changed (real source-version changes), with the reason - for re-review and
    regression. Code-change impact is NOT claimed (there is no code-to-test mapping)."""
    refresh(db, tenant)
    return [{"id": c["id"], "requirement": c["requirement_id"], "reason": c.get("stale_reason", "")}
            for c in list_cases(db, tenant, status="stale")]
