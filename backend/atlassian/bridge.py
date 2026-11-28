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
RESULTS = ("Passed", "Failed", "Blocked", "Skipped", "Not run", "Not automated", "Flaky", "Cancelled",
           "Requires review")
# a failure the engine's own analysis puts on the generated TEST (checked on screen: the website did the right thing;
# the generated script is wrong): it ran, but proves nothing about the website - a person looks. (A locator failure
# stays Failed: a removed element can be a real regression.)
TEST_SIDE = ("Test mistake", "Test-script defect")
# test data a scenario needs that the requirement does not give (asked for in the execution setup, never invented)
NEEDS = (("a test account (username and password)", re.compile(r"\b(log ?in|sign ?in|password|username|user name|"
                                                                r"credentials?|account)\b", re.I)),
         ("checkout details (name, address or postal code)", re.compile(r"\b(checkout|shipping|address|postal|zip|"
                                                                        r"first name|last name)\b", re.I)),
         ("payment details", re.compile(r"\b(card number|credit card|payment details|cvv)\b", re.I)))


def connect(path=None):
    db = store.connect(path)
    db.executescript(SCHEMA)
    from . import automations, connection_status, prerequisites
    prerequisites.connect_schema(db)
    automations.connect_schema(db)
    connection_status.connect_schema(db)
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
    if any(str(n).startswith("a test") for n in case.get("test_data_needs") or []):
        parts.append("Test account: take its user name and password from the qa_login fixture (never write them). "
                     "A valid login uses both; a wrong-password check types the test account's user name with "
                     "another password.")
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
    from ..objective import checkout_only, destructive, needs_payment_sandbox
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
        risky = " ".join([s.destructive or "", words])
        demo = checkout_only(risky)  # (a checkout: runs only on a demo shop the owner confirms for the run)
        sandbox = needs_payment_sandbox(risky)  # (it pays: runs only with a payment sandbox declared for the run)
        if destructive(risky) and not demo and not sandbox:
            blocked.append(f"changes or destroys data ('{destructive(risky)}') - only on a staging "
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
            "preconditions": [*(["A test account (username and password) is available"]
                                if needs and needs[0].startswith("a test") else [])],
            "steps": steps, "expected": expected, "expected_basis": s.basis.value,
            "assertions": [f"{c.id.split('#')[-1]}: {c.then or c.text}" for c in cited],
            "test_data_needs": needs, "evidence": quotes, "platform": "web",
            "automation": "manual" if blocked else "automated", "blocked_reason": " | ".join(blocked),
            "priority": "high" if s.kind.value in ("positive", "security") else "medium",
            # a Jira Bug is checked for whether it still happens (reproduction / regression), never reported as a
            # new defect Qpilot found; a story / task / spec is a requirement
            "demo_checkout": demo,
            "payment_sandbox": sandbox,
            "work_item": analysis.requirement.kind,
            "purpose": "reproduce the reported bug (regression check)" if analysis.requirement.kind == "bug"
            else "verify the requirement",
        }
        fp = _content_fp(case)
        old = existing.get(s.fingerprint)
        seen.add(s.fingerprint)
        status = "blocked" if blocked else "approved"
        if old and old["fingerprint"] == fp and old["status"] != "stale" and (
                old["status"] == status or old["status"] not in ("blocked", "approved")) and \
                old.get("demo_checkout", "") == demo and old.get("payment_sandbox", "") == sandbox and \
                old.get("blocked_reason", "") == case["blocked_reason"]:
            out["unchanged"].append(old["id"])
            continue
        n = int(old["id"].rsplit("-", 1)[-1]) if old else (max(used_numbers, default=0) + 1)
        used_numbers.append(n)
        case.update(id=f"TC-{requirement_id}-{n}", fingerprint=fp, version=(old["version"] + 1) if old else 1,
                    created_at=old.get("created_at", _now()) if old else _now(), approved_at=_now(),
                    status=status)
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


def plan_dependencies(db, tenant: str, use_ai: bool = False) -> dict:
    """(Re)build the prerequisite graph of this workspace's test cases (prerequisites.py). Returns the graph."""
    from . import prerequisites as pq
    cases = [c for c in list_cases(db, tenant) if c["status"] != "stale"]
    sources = {}
    for c in cases:
        if c["requirement_id"] not in sources:
            row = store.get_source(db, tenant, c.get("source_key") or "")
            sources[c["requirement_id"]] = {"content": row["content"]} if row else {}
    found = pq.infer(cases, sources)
    note = ""
    if use_ai:
        more, note = pq.ai_edges(cases)
        known = {(e["case_id"], e["requires_id"]) for e in found}
        found += [e for e in more if (e["case_id"], e["requires_id"]) not in known]
    pq.save(db, tenant, found, replace=("link", "declared", "ai") if use_ai else ("link", "declared"))
    return dependency_graph(db, tenant) | {"note": note}


def dependency_graph(db, tenant: str) -> dict:
    from . import prerequisites as pq
    all_edges = pq.edges(db, tenant)
    return {"edges": all_edges, "cycles": pq.cycles(all_edges)}


def _with_prerequisites(text: str, prereqs: list[dict]) -> str:
    """The dependent test does its prerequisites' steps first (its own browser state: tests stay isolated)."""
    if not prereqs:
        return text
    first = " Then ".join(f"{p['title'].rstrip('.')}: " + "; ".join(s.rstrip(".") for s in p["steps"])
                          for p in prereqs)
    return (f"Prerequisite (do first; it sets up the state - it is not what this test checks): {first}. "
            f"Then this test: {text}")[:2600]


def _tests_for(cases: list[dict], by_id: dict, prerequisite_info: dict) -> list[dict]:
    """The plain-English tests handed to the engine (each with its prerequisites' steps first)."""
    chains = prerequisite_info.get("chains") or {}
    return [{"id": "rq_" + re.sub(r"[^a-z0-9_]", "_", c["id"].lower()),
             "text": _with_prerequisites(instruction(c), [by_id[p] for p in chains.get(c["id"], []) if p in by_id]),
             "tc": c["id"], "prerequisite_for": [d for d, ch in chains.items() if c["id"] in ch],
             "requirement": c["requirement_id"], "criteria": c["criterion_ids"], "title": c["title"]} for c in cases]


def tests_for_execution(db, tenant: str, ex: dict) -> list[dict]:
    """The engine's tests of an execution again (a resumed batch: only ids are stored, never a password)."""
    cases = [c for c in (get_case(db, tenant, cid) for cid in ex.get("case_ids") or []) if c]
    return _tests_for(cases, {c["id"]: c for c in cases}, ex.get("prerequisites") or {})


def save_execution(db, tenant: str, ex: dict) -> None:
    data = {k: v for k, v in ex.items() if k not in ("outcome", "outcome_text", "tally", "automation_coverage",
                                                     "pass_rate")}
    with db:
        db.execute("UPDATE req_executions SET status = ?, data = ? WHERE tenant_id = ? AND id = ?",
                   (ex.get("status", "queued"), json.dumps(data), tenant, ex["id"]))


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
        why = _ready(c) or (
            f"Blocked: it pays ('{c['payment_sandbox']}'), so it runs only with a payment sandbox declared for the run "
            "(Execution Center -> Payment sandbox: the provider whose sandbox / test mode the application uses, and "
            "its official test instruments) - real payment details are never used"
            if c.get("payment_sandbox") and not target.get("payment_provider") else
            "Blocked: it places an order, so it runs only on a demo shop you confirm (tick 'Demo shop - allow placing "
            "the order' in the Execution Center) or with a payment sandbox"
            if c.get("demo_checkout") and not (target.get("demo_checkout") or target.get("payment_provider")) else "")
        (excluded.append({"id": cid, "reason": why}) if why else cases.append(c))
    if strategy != "autonomous" and not cases:
        raise ValueError("no selected test case can run: " + "; ".join(f"{x['id']} {x['reason']}" for x in excluded)[:400])
    # prerequisites (prerequisites.py): added even when their requirement was not selected; cycles never followed
    from . import prerequisites as pq
    runnable = {c["id"] for c in list_cases(db, tenant) if not _ready(c) and not (
        c.get("demo_checkout") and not (target.get("demo_checkout") or target.get("payment_provider"))) and not (
        c.get("payment_sandbox") and not target.get("payment_provider"))}
    graph = pq.closure([c["id"] for c in cases], pq.edges(db, tenant), runnable)
    for pid in graph["added"]:
        cases.append(get_case(db, tenant, pid))
    by_id = {c["id"]: c for c in cases}
    prerequisite_info = {"added": graph["added"], "requires": graph["requires"], "skipped": graph["skipped"],
                         "cycles": graph["cycles"],
                         "chains": {cid: pq.all_requirements_of(cid, graph["requires"]) for cid in by_id
                                    if graph["requires"].get(cid)}}
    execution = {"id": "EX-" + uuid.uuid4().hex[:10], "tenant_id": tenant, "strategy": strategy,
                 "case_ids": [c["id"] for c in cases], "excluded": excluded, "actor": actor, "created_at": _now(),
                 "case_versions": {c["id"]: c["version"] for c in cases},
                 "source_versions": {c["id"]: c["source_version"] for c in cases},
                 "target": {k: v for k, v in target.items() if k not in ("test_password", "api_key")},
                 "requirements": sorted({c["requirement_id"] for c in cases}), "status": "queued", "run_id": "",
                 "prerequisites": prerequisite_info}
    tests = [] if strategy == "autonomous" else _tests_for(cases, by_id, prerequisite_info)
    if (target.get("type") or "web") == "web":  # (validated automation of a website case is reused - automations.py)
        from . import automations
        reused = {}
        for t in tests:
            a = automations.compatible(db, tenant, by_id[t["tc"]], target)
            if a:
                t["automation"] = {"code": a["code"], "test": a["test"], "validated_in": a["evidence"]["run"],
                                   "selectors": a.get("selectors") or [],
                                   **({"design": a["design"]} if a.get("design") else {})}
                reused[t["tc"]] = {"validated_in": a["evidence"]["run"], "passes": a.get("passes", 1)}
        execution["automation_reuse"] = reused
    with db:
        db.execute("INSERT INTO req_executions (tenant_id, id, status, run_id, created_at, data) VALUES "
                   "(?, ?, ?, ?, ?, ?)", (tenant, execution["id"], "queued", "", execution["created_at"],
                                          json.dumps(execution)))
    return {"execution": execution, "requirement_tests": tests}


def attach_run(db, tenant: str, execution_id: str, run_id: str, status: str = "running", boot: str = "") -> None:
    ex = get_execution(db, tenant, execution_id)
    if not ex:
        raise LookupError(execution_id)
    ex.update(run_id=run_id, status=status, started_at=_now(), **({"studio_boot": boot} if boot else {}))
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
    if status == "Failed" and _prerequisite_failure(case):
        return "Blocked"
    if status == "Failed" and str(case.get("failure_category") or "").startswith(TEST_SIDE):
        return "Requires review"
    if status == "Inconclusive":  # (it ran, but did not establish its expected result: a person looks - never Passed)
        return "Requires review"
    return status if status in RESULTS else "Not run"


LOGIN_WORDS = re.compile(r"\b(log ?in|sign ?in|username|password|credentials?|authenticat\w*)\b", re.I)
PREREQ_CATEGORIES = ("Authentication / permission failure", "Test data / precondition problem",
                     "Infrastructure failure")


def _prerequisite_failure(case: dict) -> bool:
    """A failed case whose own subject is not the login, failing because the login (or the environment) it needs did
    not work: its prerequisite failed, so it is Blocked, not a product failure of what it tests. A login test failing
    on the login stays Failed."""
    category = str(case.get("failure_category") or "")
    if not category.startswith(PREREQ_CATEGORIES):
        return False
    if category.startswith("Infrastructure failure"):  # (the website itself could not be reached - never a test
        actual = str(case.get("actual_result") or "")  # that went to another address the browser refused)
        return "ERR_BLOCKED_BY_CLIENT" not in actual and "not explored" not in actual
    subject = " ".join(str(case.get(k) or "") for k in ("title", "expected"))
    return not LOGIN_WORDS.search(subject)


TAG = re.compile(r"\[(TC-[A-Za-z0-9_-]+)\]")


def _android_results(run_dir: Path) -> dict[str, dict]:
    """An Android run's outcome per Jira test case (its owner's-test line was tagged '[TC-...]'), from the engine's
    own evidence (android_interaction.json): a kept journey replayed -> Passed; one that failed twice on its
    assertions -> Failed; not automated / could not be tried / session lost -> said so. Nothing is assumed."""
    f = Path(run_dir) / "android_interaction.json"
    if not f.is_file() or f.is_symlink():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict] = {}
    for flow in data.get("flows") or []:
        m = TAG.search(str(flow.get("title") or ""))
        if not m:
            continue
        replay = str((flow.get("meta") or {}).get("discovery_replay") or "")
        status = "Passed" if replay == "passed" else "Failed" if replay.startswith("failed twice") else \
            "Requires review"
        out[m.group(1)] = {"execution_status": status, "actual_result": replay or "the journey was kept",
                           "steps": [str(s.get("action")) for s in flow.get("steps") or []][:40],
                           "failure_category": "Assertion failure" if status == "Failed" else "",
                           "skip_reason": "" if status != "Requires review" else
                           f"Requires review: the journey's replay was '{replay or 'not run'}'"}
    for item in data.get("tried") or []:
        m = TAG.search(str(item.get("check") or ""))
        if not m or m.group(1) in out:
            continue
        outcome, detail = str(item.get("outcome") or ""), str(item.get("detail") or "")
        status = {"not automated": "Not automated", "incomplete": "Blocked"}.get(outcome, "Not automated")
        out[m.group(1)] = {"execution_status": status, "actual_result": detail,
                           "skip_reason": f"{status}: {detail or outcome}"[:500]}
    return out


def collect(db, tenant: str, execution_id: str, run_dir: Path, run_status: str = "done",
            only: list[str] | None = None, final: bool = True) -> dict:
    """Read the REAL results of the finished run and record one result per requirement test case. only / final: one
    batch of a large execution (scheduler.py) - its cases only, and the execution stays running until the last."""
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
    for cid, c in _android_results(run_dir).items():  # (an Android run: its own evidence, per tagged case)
        by_tc.setdefault(cid, dict(c, requirement_test=cid, tc_id=cid))
    counts: dict[str, int] = {}
    stored: list[tuple[str, str, dict]] = []
    access = {}  # the application kept the tester out and nobody helped in time (access_help.py): why it stopped
    pause_file = Path(run_dir) / "pause.json"
    if pause_file.is_file() and not pause_file.is_symlink():
        try:
            access = json.loads(pause_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            access = {}
    summary_file = Path(run_dir) / "summary.json"  # (a run cut short says why: a time limit is 'Timed Out')
    try:
        summ = json.loads(summary_file.read_text(encoding="utf-8")) if summary_file.is_file() and \
            not summary_file.is_symlink() else {}
    except (OSError, ValueError):
        summ = {}
    if not isinstance(summ, dict):
        summ = {}
    provider_failure = ""
    if summ.get("stop_kind") == "ai_unavailable":
        provider_failure = str(summ.get("incomplete_reason") or "The selected AI provider is unavailable.")[:500]
        ex["provider_failure"] = provider_failure
    for cid in (only if only is not None else ex["case_ids"]):
        c = by_tc.get(cid)
        case_provider_failure = (c or {}).get("blocked_by_provider")
        if case_provider_failure or (provider_failure and
                                     (c is None or _result_status(c) in ("Not run", "Not automated", "Skipped"))):
            status = "Blocked"
            reason = provider_failure or str(c.get("skip_reason") or "The selected AI provider is unavailable.")[:500]
            ex.setdefault("provider_failure", reason)
            result = {"status": status, "reason": reason, "evidence": [], "actual": "",
                      "run_case": str((c or {}).get("tc_id") or ""), "blocked_by_provider": True}
        elif c is None and access.get("state") == "timed_out":
            result = {"status": "Blocked", "reason": f"Blocked: {access.get('message')} ({access.get('url')}) - "
                                                     f"{access.get('help')}"[:500],
                      "evidence": [], "actual": "", "run_case": "", "access_blocked": access.get("kind")}
            status = "Blocked"
        elif c is None:
            status = "Cancelled" if run_status in ("stopped", "cancelled") else "Not run"
            result = {"status": status, "reason": "the run ended before this test case was designed or executed"
                      if run_status in ("stopped", "cancelled") else
                      "the Studio stopped (restart / crash) while this execution ran, before this test case ran"
                      if run_status == "interrupted" else "the run did not produce this test case",
                      "evidence": [], "actual": "", "run_case": ""}
        else:
            status = _result_status(c)
            reason = str(c.get("skip_reason") or "")[:500]
            if c.get("execution_status") == "Inconclusive":
                reason = ("Inconclusive: " + str(c.get("actual_result") or "the test did not establish its expected "
                                                                          "result"))[:500]
            if status == "Blocked" and c.get("execution_status") == "Failed":
                reason = f"Blocked: a prerequisite failed ({c.get('failure_category')}), not the feature under test"
            result = {"status": status, "actual": str(c.get("actual_result") or "")[:2000],
                      "reason": reason, "expected": str(c.get("expected") or "")[:1000],
                      "steps": c.get("steps") or [], "evidence": [str(e) for e in c.get("evidence") or []][:20],
                      "run_case": str(c.get("tc_id") or c.get("id") or ""), "checks": c.get("check_count"),
                      "verification": c.get("verification"), "type": c.get("type"),
                      "failure_category": str(c.get("failure_category") or "")[:120],
                      "confidence": str(c.get("confidence") or "")[:20]}
        result.update(execution_id=execution_id, test_case_id=cid, run_id=ex.get("run_id", ""), at=_now(),
                      case_version=(ex.get("case_versions") or {}).get(cid),
                      source_version=(ex.get("source_versions") or {}).get(cid), run_folder=Path(run_dir).name)
        stored.append((cid, status, result))
    # a test that did not pass while a prerequisite it needs really failed: Blocked, naming that prerequisite
    pre = ex.get("prerequisites") or {}
    outcome_of_case = {cid: status for cid, status, _ in stored}
    for i, (cid, status, result) in enumerate(stored):
        if (pre.get("added") or []) and cid in pre["added"]:
            result["role"] = "prerequisite (added: needed by " + ", ".join(
                d for d, ch in (pre.get("chains") or {}).items() if cid in ch) + ")"
        if status == "Passed":
            continue
        failed = [p for p in (pre.get("chains") or {}).get(cid, []) if outcome_of_case.get(p) in ("Failed", "Blocked")]
        if failed:
            result.update(status="Blocked", own_status=status, blocked_by=failed[0],
                          reason=f"Blocked: its prerequisite {failed[0]} did not pass ({outcome_of_case[failed[0]]}) - the state "
                                 f"this test starts from could not be established; not a failure of what it tests")
            stored[i] = (cid, "Blocked", result)
    # a selected case that could not run (it pays without a sandbox, it is stale, not approved ...) gets its outcome
    # too - never silently left out
    for x in (ex.get("excluded") or []) if final else []:
        reason = str(x.get("reason") or "")
        status = "Blocked" if reason.lower().startswith(("blocked", "it places", "it pays")) else "Not run"
        stored.append((x["id"], status, {"status": status, "reason": reason[:500], "evidence": [], "actual": "",
                                         "run_case": "", "excluded": True, "execution_id": execution_id,
                                         "test_case_id": x["id"], "run_id": ex.get("run_id", ""), "at": _now(),
                                         "run_folder": Path(run_dir).name}))
    for cid, _status, result in stored:
        rec = by_tc.get(cid) or {}
        if rec.get("automation_source"):
            result["automation"] = rec["automation_source"]  # (reused validated automation / newly generated)
    if (ex.get("target") or {}).get("type", "web") == "web":
        from . import automations
        try:
            ex["automation_store"] = automations.after_execution(
                db, tenant, ex, by_tc, {cid: r for cid, _s, r in stored},
                {cid: get_case(db, tenant, cid) for cid, _s, _r in stored}, Path(run_dir))
        except Exception as error:  # (keeping automation is extra: results stand without it)
            ex["automation_store"] = {"error": type(error).__name__}
    for cid, status, result in stored:
        with db:
            db.execute("INSERT OR REPLACE INTO req_results (tenant_id, execution_id, test_case_id, status, at, data) "
                       "VALUES (?, ?, ?, ?, ?, ?)", (tenant, execution_id, cid, status, result["at"],
                                                     json.dumps(result, default=str)))
    for row in db.execute("SELECT status FROM req_results WHERE tenant_id = ? AND execution_id = ?",
                          (tenant, execution_id)):  # (every batch so far, and the excluded cases at the end)
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    exploratory = [c for c in run_cases if isinstance(c, dict) and not c.get("requirement_test")] \
        if isinstance(run_cases, list) else []
    if not final:
        ex["counts"] = counts
        with db:
            db.execute("UPDATE req_executions SET data = ? WHERE tenant_id = ? AND id = ?",
                       (json.dumps(ex), tenant, execution_id))
        return ex
    if summ.get("incomplete"):
        reason = str(summ.get("incomplete_reason") or "")
        ex["run_incomplete"] = reason[:300]
        ex["timed_out"] = bool(re.search(r"time limit|RUN_TIME_LIMIT|execution budget ended", reason, re.I))
    ex.update(status="finished" if run_status == "done" else run_status, finished_at=_now(), counts=counts,
              exploratory={"cases": len(exploratory),
                           "failed": sum(1 for c in exploratory if c.get("execution_status") == "Failed"),
                           "passed": sum(1 for c in exploratory if c.get("execution_status") == "Passed"),
                           "not_run": sum(1 for c in exploratory if c.get("execution_status") not in (
                               "Passed", "Failed", "Flaky"))})
    with db:
        db.execute("UPDATE req_executions SET status = ?, data = ? WHERE tenant_id = ? AND id = ?",
                   (ex["status"], json.dumps(ex), tenant, execution_id))
    return ex


OUTCOME_TEXT = {
    "running": "Running",
    "cancelled": "Cancelled",
    "interrupted": "Interrupted - resume it to run the remaining batches",
    "interrupted_run": "Interrupted - the Studio stopped while this execution ran; start it again",
    "automation_failed": "Execution unsuccessful - the test run itself failed",
    "provider_blocked": "Blocked by the selected AI provider",
    "no_tests_automated": "Execution unsuccessful - no tests were automated",
    "completed_with_failures": "Completed with failures",
    "completed_with_review": "Completed - some test results need review (the test, not the website, failed)",
    "completed_with_blocked": "Completed - some tests were blocked",
    "completed_with_unautomated": "Completed - some tests were not automated",
    "completed": "Completed - all tests passed",
}


def execution_state(ex: dict, key: str, tally: dict) -> str:
    """One word for the execution, from its real status and results: Queued, Running, Passed, Failed, Blocked,
    Cancelled, Timed Out or Partially Completed (the outcome text keeps the detail)."""
    status = ex.get("status")
    if status == "queued":
        return "Queued"
    if status == "running":
        return "Running"
    if status in ("stopped", "cancelled"):
        return "Cancelled"
    if ex.get("timed_out"):
        return "Timed Out"
    return {"completed": "Passed", "completed_with_failures": "Failed", "automation_failed": "Failed",
            "no_tests_automated": "Failed", "completed_with_blocked": "Blocked", "provider_blocked": "Blocked"}.get(key, "Partially Completed")


def outcome_of(ex: dict) -> dict:
    """The execution's lifecycle (status) kept apart from what its tests showed. Counters come only from the stored
    results: an unautomated or not-run test is never 'executed', an approved one never 'passed'."""
    counts = ex.get("counts") or {}
    selected = len(ex.get("case_ids") or []) + len(ex.get("excluded") or [])
    executed = sum(counts.get(k, 0) for k in ("Passed", "Failed", "Flaky", "Requires review"))
    tally = {"selected": selected, "executed": executed, "passed": counts.get("Passed", 0) + counts.get("Flaky", 0),
             "failed": counts.get("Failed", 0), "requires_review": counts.get("Requires review", 0),
             "blocked": counts.get("Blocked", 0),
             "not_automated": counts.get("Not automated", 0), "skipped": counts.get("Skipped", 0),
             "not_run": counts.get("Not run", 0) + counts.get("Cancelled", 0),
             "prerequisites_added": len((ex.get("prerequisites") or {}).get("added") or [])}
    status = ex.get("status")
    if status in ("running", "queued"):
        key = "running"
    elif status in ("stopped", "cancelled"):
        key = "cancelled"
    elif ex.get("provider_failure") and not executed:
        key = "provider_blocked"
    elif status == "interrupted" and not ex.get("batches"):
        key = "interrupted_run"
    elif status == "interrupted":
        key = "interrupted"
    elif status == "failed" and not executed:
        key = "automation_failed"
    elif not selected and ex.get("strategy") == "autonomous":  # (no Jira case: what the run's own scenarios showed)
        auto = ex.get("exploratory") or {}
        key = ("no_tests_automated" if not auto.get("cases") or auto.get("cases") == auto.get("not_run") else
               "completed_with_failures" if auto.get("failed") else
               "completed_with_unautomated" if auto.get("not_run") else "completed")
        tally["autonomous"] = {k: auto.get(k, 0) for k in ("cases", "passed", "failed", "not_run")}
    elif selected and not executed:
        key = "no_tests_automated"
    elif tally["failed"]:
        key = "completed_with_failures"
    elif tally["requires_review"]:
        key = "completed_with_review"
    elif tally["blocked"]:
        key = "completed_with_blocked"
    elif tally["not_automated"] or tally["not_run"] or tally["skipped"]:
        key = "completed_with_unautomated"
    else:
        key = "completed"
    return {"outcome": key, "outcome_text": OUTCOME_TEXT[key], "tally": tally, "state": execution_state(ex, key, tally),
            "automation_coverage": round(100 * executed / selected) if selected else 0,
            "pass_rate": round(100 * tally["passed"] / executed) if executed else None}


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
                            "failed" if status in ("Failed", "Flaky") else "requires review" if status == "Requires review"
                            else "blocked" if c["status"] == "blocked"
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
        if r.get("status") in ("Passed", "Failed", "Flaky", "Requires review"):
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


def accountability(db, tenant: str) -> dict:
    """One record per imported requirement - nothing selected disappears: its criteria and their approval, scenarios,
    test cases, prerequisites, the engine of its last execution, each case's latest REAL outcome with evidence and the
    reason when it did not pass, defects, blockers - and the coverage figures kept apart:
      requirement coverage   criteria with at least one passed test / all criteria
      automation coverage    test cases that ran (a real result) / test cases
      execution coverage     test cases with any recorded outcome / test cases
      pass rate              passed / ran"""
    from . import defects as dfx, prerequisites as pq
    refresh(db, tenant)
    found = dfx.by_case(db, tenant)
    edges = pq.edges(db, tenant)
    engines: dict[str, str] = {}
    for ex in reversed(list_executions(db, tenant, limit=200)):
        kind = str((ex.get("target") or {}).get("type") or "web")
        for cid in ex.get("case_ids") or []:
            engines[cid] = {"web": "Playwright (browser)", "android": "Appium (Android)",
                            "api": "REST API tests"}.get(kind, kind)
    cases = list_cases(db, tenant)
    by_req: dict[str, list[dict]] = {}
    for c in cases:
        by_req.setdefault(c["requirement_id"], []).append(c)
    ran_states = ("Passed", "Failed", "Flaky", "Requires review")
    rows, totals = [], {"criteria": 0, "criteria_passed": 0, "cases": 0, "ran": 0, "outcome": 0, "passed": 0}
    for a in store.list_analyses(db, tenant):
        req = a.requirement
        mine = by_req.get(req.id, [])
        crit_rows = []
        for crit in req.criteria:
            tcs = [c for c in mine if crit.id in c["criterion_ids"]]
            passed = any((c.get("latest_result") or {}).get("status") == "Passed" for c in tcs)
            crit_rows.append({"id": crit.id, "text": crit.text, "automatable": crit.automatable,
                              "approval": a.coverage.get(crit.id).value if a.coverage.get(crit.id) else "",
                              "test_cases": [c["id"] for c in tcs], "verified": passed})
        case_rows = []
        for c in mine:
            r = c.get("latest_result") or {}
            case_rows.append({
                "id": c["id"], "title": c["title"], "status": c["status"], "kind": c.get("kind"),
                "engine": engines.get(c["id"], ""),
                "prerequisites": [e["requires_id"] for e in edges if e["case_id"] == c["id"]],
                "outcome": r.get("status") or ("not run yet" if c["status"] in ("approved", "ready") else c["status"]),
                "reason": r.get("reason") or c.get("blocked_reason") or "",
                "checks": r.get("checks"), "evidence": (r.get("evidence") or [])[:5], "last_run": r.get("run_folder", ""),
                "defects": [d.get("id") for d in found.get(c["id"], [])]})
        blockers = sorted({x["reason"][:200] for x in case_rows
                           if x["outcome"] in ("Blocked", "Not automated", "blocked") and x["reason"]})
        ran = [x for x in case_rows if x["outcome"] in ran_states]
        with_outcome = [x for x in case_rows if x["outcome"] not in ("not run yet", "approved", "draft",
                                                                    "awaiting_approval")]
        n_crit, n_crit_ok = len(crit_rows), sum(1 for x in crit_rows if x["verified"])
        rows.append({
            "requirement": req.id, "title": req.title, "kind": req.kind, "source": req.sources[0].source_id,
            "source_version": a.source_versions.get(req.sources[0].key), "analysis_stale": bool(an.stale(db, tenant, a)),
            "criteria": crit_rows,
            "scenarios": {"total": len(a.suggestions),
                          "approved": sum(1 for s in a.suggestions if s.review == ReviewStatus.accepted)},
            "test_cases": case_rows, "blockers": blockers,
            "requirement_coverage": round(100 * n_crit_ok / n_crit) if n_crit else 0,
            "automation_coverage": round(100 * len(ran) / len(case_rows)) if case_rows else 0,
            "execution_coverage": round(100 * len(with_outcome) / len(case_rows)) if case_rows else 0,
            "pass_rate": round(100 * sum(1 for x in ran if x["outcome"] == "Passed") / len(ran)) if ran else None})
        totals["criteria"] += n_crit
        totals["criteria_passed"] += n_crit_ok
        totals["cases"] += len(case_rows)
        totals["ran"] += len(ran)
        totals["outcome"] += len(with_outcome)
        totals["passed"] += sum(1 for x in ran if x["outcome"] == "Passed")
    summary = {
        "requirements": len(rows),
        "requirement_coverage": round(100 * totals["criteria_passed"] / totals["criteria"]) if totals["criteria"] else 0,
        "automation_coverage": round(100 * totals["ran"] / totals["cases"]) if totals["cases"] else 0,
        "execution_coverage": round(100 * totals["outcome"] / totals["cases"]) if totals["cases"] else 0,
        "pass_rate": round(100 * totals["passed"] / totals["ran"]) if totals["ran"] else None,
        "note": "Requirement coverage counts criteria with a PASSED test; a case that was not run, not automated or "
                "blocked never counts as covered."}
    return {"summary": summary, "requirements": rows}
