"""Controlled Jira write-back (Requirements Intelligence, Phase 5). OFF by default; every write approved by a person.

  proposals   propose_results_comment(): one comment per Jira story with the REAL results of an execution;
              propose_defect(): one Bug for a likely defect, linked to its story. A proposal is only stored: nothing
              is sent. Its exact preview (the text and the Jira JSON) is shown before anyone approves it.
  approval    approve() / reject(): a NAMED, signed-in reviewer (approvals.py kind 'jira_write'); recorded in the audit
  sending     send() only when ALL of these hold - otherwise it refuses and sends nothing:
                1. the server owner allows write-back: QPILOT_JIRA_WRITEBACK=1 in the Studio's environment
                2. the workspace switched it on for this connection (settings: enabled, project, issue type)
                3. a separate WRITE token is stored (JIRA_WRITE_API_TOKEN) - the read token never writes
                4. the proposal is approved by a named person
  idempotency the idempotency key is the hash of (tenant, operation, target, content): the same proposal twice is
              one proposal; a sent one is never sent again. Each write carries a marker (comment text / issue label
              'qpilot-<key>'); before sending - and before any retry - Jira is read for that marker, so a write that
              arrived but whose answer was lost is recorded, not repeated.
  audit       every proposal, decision, refusal, send and failure (no token, no password in any record)
"""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime

from .. import approvals, audit_store
from ..safety import redact
from .models import (
    ISSUE_KEY,
    LOOKS_LIKE_SECRET,
    Connection,
    OutboundWrite,
    WriteOperation,
    WriteStatus,
    idempotency_key,
)

SERVER_ENV = "QPILOT_JIRA_WRITEBACK"
WRITE_TOKEN = "JIRA_WRITE_API_TOKEN"  # noqa: S105 (the NAME of the secret, not a secret)
ACTION = "requirements.writeback"
APPROVAL_KIND = "jira_write"
SCHEMA = """
CREATE TABLE IF NOT EXISTS req_writes (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, idempotency_key TEXT NOT NULL, status TEXT NOT NULL,
    created_at TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (tenant_id, id), UNIQUE (tenant_id, idempotency_key));
CREATE TABLE IF NOT EXISTS req_writeback_settings (
    tenant_id TEXT NOT NULL, connection_id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (tenant_id, connection_id));
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def ensure(db) -> None:
    db.executescript(SCHEMA)


def _audit(actor: str, tenant: str, allowed: bool, detail: dict, audit_db=None) -> None:
    try:
        audit_store.record_audit(actor=actor or "system", action=ACTION, allowed=allowed, tenant_id=tenant,
                                 detail=json.dumps(detail, default=str)[:1500],
                                 **({"db_path": audit_db} if audit_db else {}))
    except Exception:
        pass


def server_allows() -> bool:
    return os.environ.get(SERVER_ENV, "").strip() == "1"


def marker(key: str) -> str:
    return f"qpilot-{key[:16]}"


# ---------------------------------------------------------------- settings
def settings(db, tenant: str, connection_id: str) -> dict:
    ensure(db)
    r = db.execute("SELECT data FROM req_writeback_settings WHERE tenant_id = ? AND connection_id = ?",
                   (tenant, connection_id)).fetchone()
    base = {"connection_id": connection_id, "enabled": False, "project_key": "", "issue_type": "Bug",
            "write_token_ref": WRITE_TOKEN, "updated_by": "", "updated_at": ""}
    return {**base, **(json.loads(r["data"]) if r else {})}


def set_settings(db, tenant: str, connection_id: str, *, enabled: bool, project_key: str = "",
                 issue_type: str = "Bug", actor: str, audit_db=None) -> dict:
    if enabled and not server_allows():
        _audit(actor, tenant, False, {"event": "enable refused", "connection": connection_id}, audit_db)
        raise PermissionError(f"write-back is not allowed on this server ({SERVER_ENV}=1 is not set by its owner)")
    project_key = (project_key or "").strip().upper()
    if project_key and not re.fullmatch(r"[A-Z][A-Z0-9_]{0,19}", project_key):
        raise ValueError("not a Jira project key")
    issue_type = " ".join((issue_type or "Bug").split())[:40] or "Bug"
    data = {**settings(db, tenant, connection_id), "enabled": bool(enabled), "project_key": project_key,
            "issue_type": issue_type, "updated_by": actor, "updated_at": _now()}
    with db:
        db.execute("INSERT OR REPLACE INTO req_writeback_settings (tenant_id, connection_id, data) VALUES (?, ?, ?)",
                   (tenant, connection_id, json.dumps(data)))
    _audit(actor, tenant, True, {"event": "settings", "connection": connection_id, "enabled": data["enabled"],
                                 "project": project_key, "issue_type": issue_type}, audit_db)
    return data


def readiness(db, tenant: str, connection_id: str, write_token_set: bool) -> dict:
    s = settings(db, tenant, connection_id)
    why = [m for ok, m in ((server_allows(), f"the server owner has not allowed write-back ({SERVER_ENV}=1)"),
                           (s["enabled"], "write-back is switched off for this connection"),
                           (write_token_set, f"no write token ({WRITE_TOKEN}) is stored")) if not ok]
    return {**s, "server_allows": server_allows(), "write_token_set": write_token_set, "can_send": not why,
            "blocked_because": why}


# ---------------------------------------------------------------- proposals
def _save(db, tenant: str, w: dict) -> None:
    OutboundWrite(**{k: w[k] for k in OutboundWrite.model_fields if k in w})  # (the contract: approval, key, no secret)
    with db:
        db.execute("INSERT OR REPLACE INTO req_writes (tenant_id, id, idempotency_key, status, created_at, data) "
                   "VALUES (?, ?, ?, ?, ?, ?)", (tenant, w["id"], w["idempotency_key"], w["status"],
                                                 w["created_at"], json.dumps(w, default=str)))


def _by_key(db, tenant: str, key: str) -> dict | None:
    r = db.execute("SELECT data FROM req_writes WHERE tenant_id = ? AND idempotency_key = ?", (tenant, key)).fetchone()
    return json.loads(r["data"]) if r else None


def get_write(db, tenant: str, write_id: str) -> dict | None:
    ensure(db)
    r = db.execute("SELECT data FROM req_writes WHERE tenant_id = ? AND id = ?", (tenant, write_id)).fetchone()
    return json.loads(r["data"]) if r else None


def list_writes(db, tenant: str, status: str = "") -> list[dict]:
    ensure(db)
    sql, args = "SELECT data FROM req_writes WHERE tenant_id = ?", [tenant]
    if status:
        sql += " AND status = ?"
        args.append(status)
    return [json.loads(r["data"]) for r in db.execute(sql + " ORDER BY created_at DESC", args)]


def _clean(text: str) -> str:
    """Text that leaves for Jira: known secret values (the run's password, keys, tokens) and anything that looks like
    a credential are removed. (Long file names are shortened, so they are not mistaken for one.)"""
    text = redact(str(text or ""), include_username=False) or ""
    return LOOKS_LIKE_SECRET.sub("[removed]", text)


def _short(name: str) -> str:
    name = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    return name if len(name) <= 36 else name[:20] + "…" + name[-12:]


def _adf(text: str) -> dict:
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": line}]} if line else {"type": "paragraph"}
        for line in text.split("\n")]}


def request_body(w: dict) -> dict:
    """The exact JSON that send() posts (shown in the preview)."""
    p, mark = w["payload"], marker(w["idempotency_key"])
    if w["operation"] == WriteOperation.add_comment.value:
        return {"body": _adf(f"{p['text']}\n\n[{mark}]")}
    fields = {"project": {"key": w["target"]}, "issuetype": {"name": p["issue_type"]}, "summary": p["summary"],
              "description": _adf(f"{p['description']}\n\n[{mark}]"), "labels": ["qpilot", mark]}
    body = {"fields": fields}
    if p.get("links_to"):
        body["update"] = {"issuelinks": [{"add": {"type": {"name": "Relates"},
                                                  "outwardIssue": {"key": p["links_to"]}}}]}
    return body


def _propose(db, tenant: str, *, connection_id: str, operation: WriteOperation, target: str, payload: dict,
             actor: str, about: dict, audit_db=None) -> tuple[dict, bool]:
    ensure(db)
    payload = {k: _clean(v) if isinstance(v, str) else v for k, v in payload.items()}
    key = idempotency_key(tenant, operation, target, payload)
    old = _by_key(db, tenant, key)
    if old:
        return old, False
    w = {"tenant_id": tenant, "connection_id": connection_id, "operation": operation.value, "target": target,
         "payload": payload, "idempotency_key": key, "status": WriteStatus.proposed.value, "id": "WR-" + key[:10],
         "created_at": _now(), "created_by": actor, "about": about, "history": [{"at": _now(), "event":
                                                                               f"proposed by {actor}"}]}
    w["preview"] = request_body(w)
    _save(db, tenant, w)
    _audit(actor, tenant, True, {"event": "proposed", "write": w["id"], "operation": operation.value,
                                 "target": target}, audit_db)
    return w, True


def propose_results_comment(db, tenant: str, execution_id: str, actor: str, audit_db=None) -> list[dict]:
    """One comment per Jira story of the execution, with each test case's REAL result."""
    from . import bridge
    ex = bridge.get_execution(db, tenant, execution_id)
    if not ex:
        raise LookupError(execution_id)
    if ex["status"] in ("running", "queued"):
        raise ValueError("the execution is still running: propose its results when it has finished")
    res = bridge.results(db, tenant, execution_id)
    if not res:
        raise ValueError("this execution has no results")
    by_req: dict[str, list[tuple[dict, dict]]] = {}
    for r in res:
        case = bridge.get_case(db, tenant, r["test_case_id"]) or {}
        by_req.setdefault(case.get("requirement_id", ""), []).append((case, r))
    out = []
    for req, items in sorted(by_req.items()):
        if not ISSUE_KEY.match(req):
            continue  # (a Confluence-only requirement has no Jira issue to comment on)
        lines = [f"Qpilot test results for {req} (execution {execution_id}, {ex.get('finished_at', '')[:10]}):"]
        for case, r in items:
            detail = r.get("reason") if r["status"] != "Passed" else (
                f"{r.get('checks')} checks passed" if r.get("checks") else "")
            crit = ", ".join(c.split("#")[-1] for c in case.get("criterion_ids", []))
            lines.append(f"- {case.get('id')} [{crit}] {case.get('title', '')}: {r['status']}"
                         + (f" - {str(detail)[:200]}" if detail else ""))
        passed = sum(1 for _, r in items if r["status"] == "Passed")
        lines.append(f"{passed} of {len(items)} test cases passed. Target: {ex.get('target', {}).get('url', '')}.")
        lines.append("Results come from a real Qpilot run; evidence is in its report.")
        w, _ = _propose(db, tenant, connection_id=items[0][0].get("connection_id", ""),
                        operation=WriteOperation.add_comment, target=req, payload={"text": "\n".join(lines)},
                        actor=actor, about={"kind": "results", "execution_id": execution_id}, audit_db=audit_db)
        out.append(w)
    if not out:
        raise ValueError("no Jira story in this execution to comment on")
    return out


def propose_defect(db, tenant: str, defect_id: str, actor: str, audit_db=None) -> dict:
    from . import defects
    d = defects.get_defect(db, tenant, defect_id)
    if not d:
        raise LookupError(defect_id)
    if d["status"] not in ("open", "reopened"):
        raise ValueError(f"this defect is {d['status']}: only an open defect is proposed to Jira")
    if d.get("triage") == "reported_bug_reproduced":
        raise ValueError("this is the reported Jira bug itself, reproduced - it is not a new defect; comment on the "
                         "existing issue instead")
    if d.get("triage") in ("test_problem", "environment"):
        raise ValueError(f"triaged as {d['triage'].replace('_', ' ')}: fix the test or the environment; it is not "
                         "proposed as an application bug")
    if d.get("jira_issue"):
        raise ValueError(f"already reported as {d['jira_issue']}")
    s = settings(db, tenant, d.get("connection_id", ""))
    project = s["project_key"] or d["requirement_id"].split("-")[0]
    if not ISSUE_KEY.match(d["requirement_id"]):
        raise ValueError("this requirement is not a Jira issue; set a project in the write-back settings")
    desc = "\n".join([
        f"Found by Qpilot while testing {d['requirement_id']} ({d.get('requirement_title', '')}), acceptance "
        f"criteria {', '.join(c.split('#')[-1] for c in d.get('criterion_ids', []))}.",
        f"Test case: {d['test_case_id']} (version {d.get('case_version')}), requirement version "
        f"{d.get('source_version')}.", "Steps:", *[f"{i}. {s_}" for i, s_ in enumerate(d.get("steps", []), 1)],
        f"Expected: {d.get('expected', '')}", f"Actual: {d.get('actual', '')}",
        f"Seen {d.get('occurrences')} time(s), last in execution {d.get('last_execution')}; severity "
        f"{d.get('severity')}; classification: {d.get('failure_category') or 'not classified'}.",
        f"Evidence (Qpilot run {d.get('run_folder')}): "
        f"{', '.join(_short(e) for e in d.get('evidence', [])[:5]) or 'none'}"])
    payload = {"summary": d["title"][:240], "description": desc[:30000], "issue_type": s["issue_type"],
               "links_to": d["requirement_id"], "severity": d.get("severity", "")}
    w, _ = _propose(db, tenant, connection_id=d.get("connection_id", ""), operation=WriteOperation.create_issue,
                    target=project, payload=payload, actor=actor, about={"kind": "defect", "defect_id": defect_id},
                    audit_db=audit_db)
    return w


# ---------------------------------------------------------------- decisions
def _decide(db, tenant: str, write_id: str, reviewer: str, answer: str, audit_db=None) -> dict:
    w = get_write(db, tenant, write_id)
    if not w:
        raise LookupError(write_id)
    if not (reviewer or "").strip():
        raise PermissionError("a write is approved only by a named, signed-in reviewer")
    if w["status"] != WriteStatus.proposed.value:
        raise ValueError(f"this write is already {w['status']}")
    row = approvals.create(APPROVAL_KIND, f"{w['operation']} {w['target']}", detail=json.dumps(
        {"write": write_id, "key": w["idempotency_key"]}), tenant_id=tenant)
    done = approvals.decide_approval(row["id"], answer, tenant_id=tenant, decided_by=reviewer)
    accepted = done["status"] == "accepted"
    w.update(status=WriteStatus.approved.value if accepted else WriteStatus.rejected.value, approval_id=row["id"],
             approved_by=reviewer if accepted else "", decided_by=reviewer, decided_at=_now())
    w["history"].append({"at": _now(), "event": f"{'approved' if accepted else 'rejected'} by {reviewer}"})
    _save(db, tenant, w)
    _audit(reviewer, tenant, True, {"event": w["status"], "write": write_id}, audit_db)
    return w


def approve(db, tenant: str, write_id: str, reviewer: str, audit_db=None) -> dict:
    return _decide(db, tenant, write_id, reviewer, "yes", audit_db)


def reject(db, tenant: str, write_id: str, reviewer: str, audit_db=None) -> dict:
    return _decide(db, tenant, write_id, reviewer, "no", audit_db)


# ---------------------------------------------------------------- sending
def _already_in_jira(client, w: dict) -> str:
    """The remote id when this write's marker is already in Jira (it arrived before), else ''."""
    mark = marker(w["idempotency_key"])
    if w["operation"] == WriteOperation.add_comment.value:
        data = client.get(f"/rest/api/3/issue/{w['target']}/comment", {"maxResults": 100, "orderBy": "-created"})
        for c in data.get("comments") or []:
            if mark in json.dumps(c.get("body"), default=str):
                return str(c.get("id") or "")
        return ""
    data = client.post_read("/rest/api/3/search/jql", {"jql": f'labels = "{mark}"', "fields": ["summary"],
                                                       "maxResults": 1})
    issues = data.get("issues") or []
    return str(issues[0].get("key") or "") if issues else ""


def send(db, tenant: str, write_id: str, actor: str, *, connection: Connection, secret, base_url: str = "",
         audit_db=None, client_factory=None) -> dict:
    """Send ONE approved write. Refuses (sends nothing) unless every condition in the module notes holds."""
    from .client import AtlassianError, WriteClient
    w = get_write(db, tenant, write_id)
    if not w:
        raise LookupError(write_id)
    if w["status"] == WriteStatus.sent.value:
        return w  # (never twice)
    if w["status"] not in (WriteStatus.approved.value, WriteStatus.failed.value) or not w.get("approval_id"):
        raise PermissionError("only an approved write is sent")
    ready = readiness(db, tenant, w["connection_id"], bool(secret(WRITE_TOKEN)))
    if not ready["can_send"]:
        _audit(actor, tenant, False, {"event": "send refused", "write": write_id, "why": ready["blocked_because"]},
               audit_db)
        raise PermissionError("not sent: " + "; ".join(ready["blocked_because"]))
    twin = _by_key(db, tenant, w["idempotency_key"])
    if twin and twin["id"] != w["id"] and twin["status"] == WriteStatus.sent.value:
        return twin
    conn = connection.model_copy(update={"token_ref": WRITE_TOKEN})
    client = (client_factory or WriteClient)(conn, secret=secret, base_url=base_url, max_retries=2, max_wait=30.0)
    w["attempts"] = int(w.get("attempts", 0)) + 1
    try:
        remote = _already_in_jira(client, w)
        note = "already in Jira (an earlier attempt arrived): not sent again" if remote else ""
        if not remote:
            if w["operation"] == WriteOperation.add_comment.value:
                answer = client.post_write(f"/rest/api/3/issue/{w['target']}/comment", request_body(w))
                remote = str(answer.get("id") or "")
            else:
                answer = client.post_write("/rest/api/3/issue", request_body(w))
                remote = str(answer.get("key") or answer.get("id") or "")
            if not remote:
                raise AtlassianError("invalid_response", "Jira did not say what it created")
            note = f"sent; Jira answered {remote}"
    except AtlassianError as error:
        w.update(status=WriteStatus.failed.value, last_error=f"{error.kind}: {error}"[:500])
        w["history"].append({"at": _now(), "event": f"send failed ({error.kind}) by {actor}"})
        _save(db, tenant, w)
        _audit(actor, tenant, False, {"event": "send failed", "write": write_id, "kind": error.kind}, audit_db)
        return w
    w.update(status=WriteStatus.sent.value, remote_id=remote, sent_at=_now(), sent_by=actor, last_error="")
    w["history"].append({"at": _now(), "event": f"{note} (by {actor})"})
    _save(db, tenant, w)
    if w.get("about", {}).get("kind") == "defect" and w["operation"] == WriteOperation.create_issue.value:
        from . import defects
        defects.link_issue(db, tenant, w["about"]["defect_id"], remote, write_id)
    _audit(actor, tenant, True, {"event": "sent", "write": write_id, "remote": remote}, audit_db)
    return w
