"""Studio API for Requirements Intelligence (Jira Cloud + Confluence Cloud), under /api/requirements.

Every route: who is asking and in which tenant comes from dashboard_auth.authorize (never from the request), the
role must allow the action (rbac), and every read and write of the store is filtered by that tenant.

  run.read       look: connections, projects, types, spaces, preview, items, versions, analyses, coverage, history
  run.write      do: test a connection, validate JQL, import, analyse
  tenant.manage  change connections and their tokens (admin)
  review.write   accept / reject a suggestion (a named, signed-in reviewer; recorded as such)
  audit.read     the requirements audit trail

Studio login off (localhost, one person): everything runs in the 'local' tenant as 'local-user'.

Tokens: PUT .../token stores one (write-only); no answer, log, error or audit entry ever contains it. Atlassian is
only READ (backend/atlassian/client.py refuses anything else). Importing never runs tests: test generation and runs
come with later phases, and /capabilities says which actions exist today.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import execution_preflight
from .atlassian import analysis as an, bridge, confluence, credentials, jira, store, sync, workflow
from .atlassian.client import AtlassianError, Client
from .atlassian.models import (
    DEFAULT_TOKEN_REF,
    ISSUE_KEY,
    PAGE_ID,
    Classification,
    Connection,
    ImportFilter,
    Product,
    SourceKind,
    safe_error,
)
from .safety import redact

ACTION_PREFIX = "requirements."
PREFLIGHT_PROBE = None  # (tests replace the real browser probe; None = open the page in the run's Chromium)
CLIENT_BASE_URL = ""  # tests only: a local mock site on 127.0.0.1 (client.Client refuses anything else)
MAX_JOBS = 200

# Which workspace actions exist in this build. Later phases switch theirs on; the Studio shows the rest as coming.
CAPABILITIES = {
    "import_requirements": True, "analyze_requirements": True, "review_suggestions": True,
    "generate_test_cases": True, "run_selected_tests": True, "run_impacted_tests": True,
    "run_all_approved_tests": True, "traceability": True, "defects": True, "writeback_proposals": True,
    "jira_write_back": False,  # (True only when the server owner sets QPILOT_JIRA_WRITEBACK=1; see capabilities())
}
COMING = {"jira_write_back": "off: the server owner must allow it (QPILOT_JIRA_WRITEBACK=1), a workspace admin "
                             "switches it on with a separate write token, and a named person approves every write"}


# ---------------------------------------------------------------- who is asking

def _context(authorization: str | None, x_qa_token: str | None, action: str) -> dict:
    from .dashboard_auth import auth_mode, authorize, reviewer_identity
    mode = auth_mode()
    if mode == "none":
        return {"tenant": credentials.LOCAL_TENANT, "actor": "local-user", "reviewer": "local-user", "mode": mode}
    verdict = authorize(authorization, x_qa_token=x_qa_token, action=action)
    if not verdict.get("ok"):
        raise HTTPException(403 if verdict.get("role") else 401, verdict.get("reason") or "unauthorized")
    if mode in ("principal", "oidc"):
        tenant = str(verdict.get("tenant_id") or "").strip()
        if not tenant:
            raise HTTPException(403, "principal has no tenant")
        who = str(verdict.get("principal_id") or "")
        return {"tenant": tenant, "actor": who, "reviewer": reviewer_identity(verdict), "mode": mode}
    # (a shared bearer / webhook token: the owner's single-tenant automation, not a person)
    return {"tenant": credentials.LOCAL_TENANT, "actor": f"{mode}-token", "reviewer": None, "mode": mode}


def _can_review(authorization: str | None, x_qa_token: str | None, ctx: dict) -> bool:
    """A named person whose role may decide reviews (what the review route itself will require)."""
    if not ctx["reviewer"]:
        return False
    if ctx["mode"] == "none":
        return True
    from .dashboard_auth import authorize
    return bool(authorize(authorization, x_qa_token=x_qa_token, action="review.write").get("ok"))


def _audit(ctx: dict, action: str, allowed: bool, **detail) -> None:
    try:
        import json

        from . import audit_store
        audit_store.record_audit(actor=ctx["actor"], action=ACTION_PREFIX + action, allowed=allowed,
                                 tenant_id=ctx["tenant"], detail=redact(json.dumps(detail, default=str))[:1000])
    except Exception:
        pass


def _db():
    return store.connect()


def _connection(db, ctx: dict, connection_id: str, product: Product | None = None) -> Connection:
    try:
        conn = store.get_connection(db, ctx["tenant"], connection_id)
    except ValueError as error:
        raise HTTPException(409, safe_error(error)) from None
    if conn is None:
        raise HTTPException(404, "No such connection in your workspace.")
    if product is not None and conn.product != product:
        raise HTTPException(400, f"This is a {conn.product.value} connection.")
    return conn


def _client(ctx: dict, conn: Connection) -> Client:
    return Client(conn, secret=credentials.resolver(ctx["tenant"], site=conn.site_url), base_url=CLIENT_BASE_URL,
                  max_retries=3,
                  max_wait=30.0)


def _atlassian_error(error: Exception) -> HTTPException:
    """A meaningful, secret-free answer for an Atlassian failure."""
    if isinstance(error, AtlassianError):
        status = {"auth_missing": 412, "auth_expired": 401, "forbidden": 403, "not_found": 404, "bad_request": 400,
                  "rate_limited": 429}.get(error.kind, 502)
        hint = {"auth_missing": "Add the API token for this connection.",
                "auth_expired": "The token was refused: replace it (Atlassian tokens expire or can be revoked).",
                "forbidden": "The account has no permission for this.",
                "rate_limited": "Atlassian is limiting requests: try again in a minute.",
                "network": "Atlassian could not be reached: check the network and try again."}.get(error.kind, "")
        return HTTPException(status if status != 401 else 424, {"kind": error.kind, "message": safe_error(error),
                                                                "hint": hint})
    return HTTPException(400, {"kind": "invalid", "message": safe_error(error), "hint": ""})


def _public(conn: Connection, tenant: str) -> dict:
    data = conn.model_dump(mode="json")
    data["credential"] = credentials.status(tenant, conn.token_ref, site=conn.site_url)
    return data


# ---------------------------------------------------------------- import jobs (background, cancellable)

class Jobs:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, ctx: dict, connection_id: str, mode: str, work) -> dict:
        with self._lock:
            busy = [j for j in self._jobs.values() if j["tenant"] == ctx["tenant"] and j["status"] == "running"
                    and j["connection_id"] == connection_id]
            if busy:
                raise HTTPException(409, f"An import of this connection is already running ({busy[0]['id']}).")
            if len(self._jobs) >= MAX_JOBS:
                for old in sorted((j for j in self._jobs.values() if j["status"] != "running"),
                                  key=lambda j: j["created"])[: len(self._jobs) - MAX_JOBS + 1]:
                    self._jobs.pop(old["id"], None)
            job = {"id": uuid.uuid4().hex, "tenant": ctx["tenant"], "actor": ctx["actor"],
                   "connection_id": connection_id, "mode": mode, "status": "running", "progress": {},
                   "result": None, "error": "", "created": time.time(), "cancel": threading.Event()}
            self._jobs[job["id"]] = job

        def run():
            db = _db()
            try:
                job["result"] = work(db, job)
                job["status"] = job["result"].get("status") or "complete"
            except HTTPException as error:
                job.update(status="failed", error=str(error.detail))
            except (AtlassianError, ValueError, LookupError, PermissionError) as error:
                job.update(status="failed", error=safe_error(error))
            except Exception as error:  # (never a stack trace, never a secret)
                job.update(status="failed", error=f"unexpected {type(error).__name__}")
            finally:
                db.close()
        threading.Thread(target=run, daemon=True, name=f"requirements-import-{job['id'][:8]}").start()
        return self.view(job)

    def get(self, ctx: dict, job_id: str) -> dict:
        job = self._jobs.get(job_id)
        if job is None or job["tenant"] != ctx["tenant"]:
            raise HTTPException(404, "No such import.")
        return job

    @staticmethod
    def view(job: dict) -> dict:
        return {k: v for k, v in job.items() if k not in ("cancel", "tenant")}

    def wait(self, job_id: str, seconds: float = 30.0) -> None:  # (tests)
        end = time.time() + seconds
        while time.time() < end and self._jobs.get(job_id, {}).get("status") == "running":
            time.sleep(0.02)


JOBS = Jobs()


# ---------------------------------------------------------------- request bodies

class ConnectionBody(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    product: Product
    site_url: str = Field(max_length=200)
    email: str = Field(max_length=254)
    token_ref: str = ""
    work_item_types: list[str] = Field(default_factory=lambda: ["Story"])
    classification: Classification = Classification.internal


class DismissBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ProposalBody(BaseModel):
    execution_id: str = Field(default="", max_length=40)
    defect_id: str = Field(default="", max_length=40)


class WritebackSettingsBody(BaseModel):
    enabled: bool = False
    project_key: str = Field(default="", max_length=20)
    issue_type: str = Field(default="Bug", max_length=40)


class TokenBody(BaseModel):
    token: str = Field(min_length=1, max_length=4000)


class JqlBody(BaseModel):
    project: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,19}$")
    jql: str = Field(max_length=2000)


class PreviewBody(BaseModel):
    filters: ImportFilter | None = None
    keys: str = Field(default="", max_length=20000)  # keys and / or work-item links, comma or space separated
    limit: int = Field(default=50, ge=1, le=100)
    next_page_token: str = Field(default="", max_length=4000)


class ImportBody(BaseModel):
    mode: str = Field(pattern=r"^(incremental|full|items|space)$")
    filters: ImportFilter | None = None
    keys: str = Field(default="", max_length=20000)
    include: list[str] = Field(default_factory=list, max_length=3)
    space_key: str = Field(default="", max_length=255)
    confluence_connection: str = Field(default="", max_length=64)  # items: also read the pages the stories link to


class AnalyzeBody(BaseModel):
    ai: str = Field(default="off", pattern=r"^(off|auto)$")


class SuggestionEdit(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    steps: list[str] = Field(default_factory=list, max_length=20)
    expected_outcome: str = Field(default="", max_length=1000)


class ReviewBody(BaseModel):
    answer: str = Field(pattern=r"^(?i:yes|no|accept|accepted|approve|approved|reject|rejected)$")
    edit: SuggestionEdit | None = None  # accept with the reviewer's corrections (kept with the original)


class CaseEdit(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    preconditions: list[str] | None = Field(default=None, max_length=20)
    steps: list[str] | None = Field(default=None, max_length=30)
    expected: str | None = Field(default=None, max_length=1500)
    assertions: list[str] | None = Field(default=None, max_length=20)


class ExecutionScope(BaseModel):
    test_case_ids: list[str] = Field(default_factory=list, max_length=200)
    requirements: list[str] = Field(default_factory=list, max_length=200)  # Jira keys / conf-<page id>
    all_approved: bool = False
    impacted: bool = False   # test cases changed since they last ran (requirement source versions)
    failed: bool = False     # test cases whose latest result failed or was blocked
    regression: bool = False  # every test case that ran before
    epic: str = Field(default="", max_length=40)  # stories whose parent is this epic
    confluence_page: str = Field(default="", max_length=20)  # requirements specified by this page


class ExecutionTarget(BaseModel):
    type: str = Field(default="web", pattern=r"^(web)$")  # (Android requirement runs: a later milestone)
    url: str = Field(min_length=4, max_length=2000)
    authorized: bool = False   # "I own this application or have permission to test it"
    environment: str = Field(default="test", pattern=r"^(test|staging)$")
    # "This is a demo / test shop - no real payment": its checkout may be completed by the checkout test cases of a
    # requirement-based run (the engine's existing staging + test-payment permission, for THIS run only)
    demo_checkout: bool = False
    test_username: str = Field(default="", max_length=200)
    test_password: str = Field(default="", max_length=200)  # this run only; never stored, never returned
    llm_provider: str = Field(default="", max_length=30)
    llm_model: str = Field(default="", max_length=100)
    api_key: str = Field(default="", max_length=400)  # this run only (as the Studio's run form); never stored
    max_pages: int = Field(default=0, ge=0, le=5000)
    page_timeout_s: int = Field(default=0, ge=0, le=300)
    show_browser: bool = False
    record_video: bool = False
    thorough: bool = False
    use_saved_account: bool = True  # the project's saved test account for this same website (never returned)
    save_target: bool = False  # remember this website (and the account typed, if any) for the project
    project_key: str = Field(default="", max_length=20)

    def public(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if k not in ("test_password", "api_key")} | {
            "test_password": "[set]" if self.test_password else "", "api_key": "[set]" if self.api_key else ""}


class DraftBody(BaseModel):
    draft_id: str = Field(default="", max_length=20)
    changes: dict = Field(default_factory=dict)


class TargetBody(BaseModel):
    project_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,19}$")
    url: str = Field(min_length=4, max_length=2000)
    environment: str = Field(default="test", pattern=r"^(test|staging)$")
    app_type: str = Field(default="web", pattern=r"^(web|android)$")
    authorized: bool = False
    test_username: str = Field(default="", max_length=200)
    test_password: str = Field(default="", max_length=200)


class UrlBody(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class DependencyPlanBody(BaseModel):
    use_ai: bool = False  # also ask the AI (small batches; only real case ids are kept)


class DependencyBody(BaseModel):
    case_id: str = Field(min_length=3, max_length=80)
    requires_id: str = Field(min_length=3, max_length=80)
    present: bool = True  # False: remove (also hides an inferred edge from later plans)
    reason: str = Field(default="", max_length=300)


class ExecutionBody(BaseModel):
    strategy: str = Field(pattern=r"^(requirements|autonomous|hybrid)$")
    scope: ExecutionScope = Field(default_factory=ExecutionScope)
    target: ExecutionTarget


def _scope_cases(db, tenant: str, scope: ExecutionScope) -> list[str]:
    """The test cases a scope names - only approved / ready ones are returned (stale and blocked ones are reported
    by bridge.plan when they are named explicitly)."""
    bridge.refresh(db, tenant)
    cases = bridge.list_cases(db, tenant)
    runnable = [c for c in cases if c["status"] in ("approved", "ready")]
    chosen: list[str] = list(scope.test_case_ids)
    if scope.requirements:
        chosen += [c["id"] for c in runnable if c["requirement_id"] in scope.requirements]
    if scope.all_approved:
        chosen += [c["id"] for c in runnable]
    if scope.failed:
        chosen += [c["id"] for c in runnable if (c.get("latest_result") or {}).get("status") in ("Failed", "Blocked")]
    if scope.regression:
        chosen += [c["id"] for c in runnable if c.get("latest_result")]
    if scope.impacted:  # (changed since they last ran: a newer test-case version than the one executed)
        for c in runnable:
            runs = bridge.case_results(db, tenant, c["id"])
            if runs and all(r.get("case_version", 0) < c["version"] for r in runs):
                chosen.append(c["id"])
    if scope.epic:
        reqs = {r["source"].source_id for r in store.list_sources(db, tenant)
                if r["content"].get("parent") == scope.epic}
        chosen += [c["id"] for c in runnable if c["requirement_id"] in reqs]
    if scope.confluence_page:
        reqs = {a.requirement.id for a in store.list_analyses(db, tenant)
                if any(k.endswith(f":confluence_page:{scope.confluence_page}") for k in a.source_versions)}
        chosen += [c["id"] for c in runnable if c["requirement_id"] in reqs]
    return list(dict.fromkeys(chosen))


def _settle_execution(db, tenant: str, ex: dict) -> dict:
    """A running execution whose Qpilot run has ended: collect its real results now (idempotent)."""
    if ex.get("status") not in ("running", "queued") or not str(ex.get("run_id", "")).isdigit():
        return ex
    from . import server
    job = server.jobs.get(int(ex["run_id"]))
    if job is None or job.get("status") == "running":
        return ex
    run_dir = server._plain_run_dir(str(job.get("run"))) if job.get("run") else None
    if run_dir is None:
        return bridge.collect(db, tenant, ex["id"], Path("/nonexistent"), job.get("status", "failed"))
    return bridge.collect(db, tenant, ex["id"], run_dir, job.get("status", "done"))


def _with_outcome(ex: dict) -> dict:
    return {**ex, **bridge.outcome_of(ex)}


def _watch(tenant: str, execution_id: str, job_id: int) -> None:
    """Collect the results when the run ends, even if nobody has the page open."""
    def wait():
        from . import server
        while True:
            job = server.jobs.get(job_id)
            if job is None or job.get("status") != "running":
                break
            time.sleep(2)
        db = bridge.connect()
        try:
            ex = bridge.get_execution(db, tenant, execution_id)
            if ex:
                _settle_execution(db, tenant, ex)
        except Exception:
            pass
        finally:
            db.close()
    threading.Thread(target=wait, daemon=True, name=f"requirements-execution-{execution_id}").start()


# ---------------------------------------------------------------- helpers for items

def _root_key(connection_id: str, source_id: str) -> str:
    if ISSUE_KEY.match(source_id):
        return f"{connection_id}:{SourceKind.jira_issue.value}:{source_id}"
    if PAGE_ID.match(source_id):
        return f"{connection_id}:{SourceKind.confluence_page.value}:{source_id}"
    raise HTTPException(400, "Not a work-item key or a page id.")


def _requirement_id(source) -> str:
    return source.source_id if source.kind == SourceKind.jira_issue else f"conf-{source.source_id}"


def _analysis_state(db, tenant: str, req_id: str) -> tuple[str, object]:
    analysis = store.get_analysis(db, tenant, req_id)
    if analysis is None:
        return "not_analyzed", None
    return ("stale" if an.stale(db, tenant, analysis) else "current"), analysis


def _item_row(db, tenant: str, row: dict, runs: dict) -> dict:
    src, content = row["source"], row["content"]
    req_id = _requirement_id(src)
    state, analysis = _analysis_state(db, tenant, req_id)
    if analysis is not None:
        criteria = len(analysis.requirement.criteria)
        pending = sum(1 for s in analysis.suggestions if s.review.value == "needs_review")
    else:
        try:
            criteria = len(an.build_requirement(db, tenant, src.key).criteria)
        except (LookupError, ValueError):
            criteria = 0
        pending = 0
    covered = sum(1 for status in analysis.coverage.values() if status.value == "covered") if analysis else None
    review_status = ("pending" if pending else "reviewed") if analysis and analysis.suggestions else ""
    pages = sum(1 for link in store.links_from(db, tenant, src.key) if link["relation"] == "specified_by") \
        if src.kind == SourceKind.jira_issue else 0
    return {"key": src.source_id, "connection_id": src.connection_id, "kind": src.kind.value, "requirement_id": req_id,
            "summary": content.get("summary") or content.get("title") or src.title,
            "type": content.get("type", "page" if src.kind != SourceKind.jira_issue else ""),
            "priority": content.get("priority", ""), "status": content.get("status", ""),
            "labels": content.get("labels", []), "criteria": criteria, "linked_pages": pages,
            "analysis": state, "pending_reviews": pending, "review_status": review_status, "covered": covered,
            "version": src.version, "present": row["present"],
            "updated": src.updated.isoformat(), "last_synced": src.retrieved_at.isoformat(), "url": src.url,
            "space": content.get("space", ""), "parent_id": content.get("parent_id", ""),
            "last_sync": runs.get(src.connection_id, "")}


# ---------------------------------------------------------------- routes

def register_requirements_api(app) -> None:
    auth = {"authorization": Header(default=None), "x_qa_token": Header(default=None, alias="X-QA-Token")}
    A, Q = auth["authorization"], auth["x_qa_token"]

    @app.get("/api/requirements/capabilities")
    def capabilities(authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        from .atlassian import writeback
        allowed = writeback.server_allows()
        return {"capabilities": {**CAPABILITIES, "jira_write_back": allowed},
                "coming": {} if allowed else COMING, "tenant": ctx["tenant"], "actor": ctx["actor"],
                "can_review": _can_review(authorization, x_qa_token, ctx), "read_only_atlassian": not allowed}

    # -- connections
    @app.get("/api/requirements/connections")
    def list_conns(authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = _db()
        try:
            try:
                conns = store.list_connections(db, ctx["tenant"])
            except ValueError as error:
                raise HTTPException(409, safe_error(error)) from None
            out = []
            for c in conns:
                item = _public(c, ctx["tenant"])
                item["last_success"] = store.last_success(db, ctx["tenant"], c.id)
                out.append(item)
            from .atlassian.cli import legacy_write_status
            legacy = legacy_write_status()
            return {"connections": out, "defect_creation_writes_to_jira": legacy["active"],
                    "defect_creation_project": legacy["project"]}
        finally:
            db.close()

    @app.post("/api/requirements/connections")
    def save_conn(body: ConnectionBody, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "tenant.manage")
        db = _db()
        try:
            old = store.get_connection(db, ctx["tenant"], body.id)
            others = [c for c in store.list_connections(db, ctx["tenant"]) if c.id != body.id]
            moved = bool(old) and (credentials.site_of(old.site_url) != credentials.site_of(body.site_url)
                                   or old.email.strip().lower() != body.email.strip().lower())
            default = DEFAULT_TOKEN_REF[body.product.value]
            # one token slot per site: a second site, or a connection moved to another site / account, gets its own
            # (the shared default, and a token from .env under that name, stay with the site they were set up for)
            own = f"{body.product.value.upper()}_{re.sub(r'[^A-Z0-9]', '_', body.id.upper())}_SITE_TOKEN"
            if body.token_ref:
                ref = body.token_ref
            elif old and not moved:
                ref = old.token_ref
            elif moved or any(c.product == body.product and c.token_ref == default for c in others):
                ref = own
            else:
                ref = default
            try:
                conn = Connection(id=body.id, tenant_id=ctx["tenant"], product=body.product, site_url=body.site_url,
                                  email=body.email, token_ref=ref, work_item_types=body.work_item_types or ["Story"],
                                  classification=body.classification)
            except ValueError as error:
                _audit(ctx, "connection.save", False, connection=body.id, why=safe_error(error)[:200])
                raise HTTPException(400, safe_error(error)) from None
            store.save_connection(db, conn)
        finally:
            db.close()
        cleared = False
        if moved and not any(c.token_ref == old.token_ref for c in others):
            cleared = credentials.delete_token(ctx["tenant"], old.token_ref)  # (its token was for the old site)
        _audit(ctx, "connection.save", True, connection=conn.id, site=conn.site_url, product=conn.product.value,
               site_changed=moved, token_cleared=cleared, secret_name=conn.token_ref)
        out = _public(conn, ctx["tenant"])
        if moved:
            out["notice"] = ("The site or account changed, so the token saved for the old one is no longer used. "
                             "Paste the API token for this site.")
        return out

    @app.delete("/api/requirements/connections/{connection_id}")
    def delete_conn(connection_id: str, forget_token: bool = True, authorization: str | None = A,
                    x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "tenant.manage")
        db = _db()
        try:
            conn = _connection(db, ctx, connection_id)
            store.delete_connection(db, ctx["tenant"], connection_id)
        finally:
            db.close()
        if forget_token:
            credentials.delete_token(ctx["tenant"], conn.token_ref)
        _audit(ctx, "connection.delete", True, connection=connection_id, token_forgotten=forget_token)
        return {"deleted": connection_id, "imported_requirements_kept": True}

    @app.put("/api/requirements/connections/{connection_id}/token")
    def put_token(connection_id: str, body: TokenBody, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "tenant.manage")
        db = _db()
        try:
            conn = _connection(db, ctx, connection_id)
        finally:
            db.close()
        try:
            state = credentials.set_token(ctx["tenant"], conn.token_ref, body.token, site=conn.site_url)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        _audit(ctx, "token.set", True, connection=connection_id, secret_name=conn.token_ref)
        return {"connection_id": connection_id, "credential": state}

    @app.delete("/api/requirements/connections/{connection_id}/token")
    def delete_token(connection_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "tenant.manage")
        db = _db()
        try:
            conn = _connection(db, ctx, connection_id)
        finally:
            db.close()
        removed = credentials.delete_token(ctx["tenant"], conn.token_ref)
        _audit(ctx, "token.delete", True, connection=connection_id)
        return {"connection_id": connection_id, "removed": removed,
                "credential": credentials.status(ctx["tenant"], conn.token_ref, site=conn.site_url)}

    @app.post("/api/requirements/connections/{connection_id}/test")
    def test_conn(connection_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.write")
        db = _db()
        try:
            conn = _connection(db, ctx, connection_id)
        finally:
            db.close()
        client = _client(ctx, conn)
        try:
            if conn.product == Product.jira:
                who = jira.myself(client)
                detail = {"account": who["display_name"] or who["account_id"], "active": who["active"],
                          "projects": len(jira.projects(client))}
            else:
                detail = {"spaces": len(confluence.spaces(client))}
        except (AtlassianError, ValueError) as error:
            _audit(ctx, "connection.test", False, connection=connection_id, kind=getattr(error, "kind", "invalid"))
            raise _atlassian_error(error) from None
        _audit(ctx, "connection.test", True, connection=connection_id)
        return {"ok": True, "read_only": True, **detail}

    @app.get("/api/requirements/connections/{connection_id}/projects")
    def projects(connection_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = _db()
        try:
            conn = _connection(db, ctx, connection_id, Product.jira)
        finally:
            db.close()
        try:
            return {"projects": jira.projects(_client(ctx, conn))}
        except (AtlassianError, ValueError) as error:
            raise _atlassian_error(error) from None

    @app.get("/api/requirements/connections/{connection_id}/projects/{project}/types")
    def types(connection_id: str, project: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = _db()
        try:
            conn = _connection(db, ctx, connection_id, Product.jira)
        finally:
            db.close()
        client = _client(ctx, conn)
        try:
            found = jira.work_item_types(client, project)
            counts = {c["name"]: c["count"] for c in jira.type_counts(client, project, found)}
        except (AtlassianError, ValueError) as error:
            raise _atlassian_error(error) from None
        chosen = {x.lower() for x in conn.work_item_types}
        return {"project": project, "types": [{**t, "count": counts.get(t["name"]),
                                                "selected": t["name"].lower() in chosen} for t in found]}

    @app.get("/api/requirements/connections/{connection_id}/spaces")
    def spaces(connection_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = _db()
        try:
            conn = _connection(db, ctx, connection_id, Product.confluence)
        finally:
            db.close()
        try:
            return {"spaces": confluence.spaces(_client(ctx, conn))}
        except (AtlassianError, ValueError) as error:
            raise _atlassian_error(error) from None

    @app.post("/api/requirements/connections/{connection_id}/jql/validate")
    def validate(connection_id: str, body: JqlBody, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.write")
        db = _db()
        try:
            conn = _connection(db, ctx, connection_id, Product.jira)
        finally:
            db.close()
        try:
            f = ImportFilter(project=body.project, jql=body.jql)
            query = jira.build_jql(f.project, conn.work_item_types, jira.filter_jql(f), order=False)
            errors = jira.validate_jql(_client(ctx, conn), query)
        except (AtlassianError, ValueError) as error:
            if isinstance(error, AtlassianError):
                raise _atlassian_error(error) from None
            return {"valid": False, "errors": [safe_error(error)], "jql": ""}
        return {"valid": not errors, "errors": errors, "jql": query}

    @app.post("/api/requirements/connections/{connection_id}/preview")
    def preview(connection_id: str, body: PreviewBody, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = _db()
        try:
            conn = _connection(db, ctx, connection_id, Product.jira)
            client = _client(ctx, conn)
            try:
                keys = jira.parse_issue_refs(body.keys, conn.host) if body.keys.strip() else None
                if body.filters and body.filters.jql:
                    _require_valid(client, conn, body.filters)
                return sync.preview(db, conn, client, tenant_id=ctx["tenant"], filters=body.filters, keys=keys,
                                    limit=body.limit, next_page_token=body.next_page_token, actor=ctx["actor"])
            except (AtlassianError, ValueError) as error:
                raise _atlassian_error(error) from None
        finally:
            db.close()

    # -- imports
    @app.post("/api/requirements/connections/{connection_id}/imports")
    def start_import(connection_id: str, body: ImportBody, authorization: str | None = A,
                     x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.write")
        db = _db()
        try:
            conn = _connection(db, ctx, connection_id)
            conf = _connection(db, ctx, body.confluence_connection, Product.confluence) \
                if body.confluence_connection else None
        finally:
            db.close()
        try:
            if body.mode == "space":
                if conn.product != Product.confluence or not body.space_key:
                    raise ValueError("a space import needs a Confluence connection and a space key")
            elif conn.product != Product.jira:
                raise ValueError("work items are imported from a Jira connection")
            keys = jira.parse_issue_refs(body.keys, conn.host) if body.mode == "items" else None
            if body.mode == "items" and not keys:
                raise ValueError("give one or more work-item keys or links")
            if body.mode in ("incremental", "full") and body.filters is None:
                raise ValueError("choose a project")
            if body.filters and body.filters.jql:
                _require_valid(_client(ctx, conn), conn, body.filters)
            include = tuple(body.include)
        except (AtlassianError, ValueError) as error:
            raise _atlassian_error(error) from None

        def work(db, job):
            client = _client(ctx, conn)
            result = sync.run_import(db, conn, client, tenant_id=ctx["tenant"], mode=body.mode, filters=body.filters,
                                     keys=keys, include=include, space_key=body.space_key, actor=ctx["actor"],
                                     should_stop=job["cancel"].is_set,
                                     progress=lambda r: job.__setitem__("progress", _progress(r)))
            if conf is not None and body.mode == "items":
                conf_client = _client(ctx, conf)
                result["confluence"] = []
                for key in keys:
                    try:
                        result["confluence"].append(sync.link_story(
                            db, conn, client, conf, conf_client, tenant_id=ctx["tenant"], issue_key=key,
                            actor=ctx["actor"]))
                    except (AtlassianError, LookupError, ValueError) as error:
                        result["warnings"].append(f"{key}: linked pages not read ({safe_error(error)[:120]})")
            return result
        job = JOBS.start(ctx, connection_id, body.mode, work)
        _audit(ctx, "import.start", True, connection=connection_id, mode=body.mode, job=job["id"])
        return job

    @app.get("/api/requirements/imports")
    def import_history(connection_id: str = "", limit: int = 50, authorization: str | None = A,
                       x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = _db()
        try:
            runs = store.sync_runs(db, ctx["tenant"], connection_id, limit)
        finally:
            db.close()
        running = [Jobs.view(j) for j in JOBS._jobs.values() if j["tenant"] == ctx["tenant"]
                   and j["status"] == "running" and (not connection_id or j["connection_id"] == connection_id)]
        return {"runs": runs, "running": running}

    @app.get("/api/requirements/imports/{job_id}")
    def import_status(job_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        return Jobs.view(JOBS.get(ctx, job_id))

    @app.post("/api/requirements/imports/{job_id}/cancel")
    def cancel_import(job_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.write")
        job = JOBS.get(ctx, job_id)
        job["cancel"].set()
        _audit(ctx, "import.cancel", True, job=job_id)
        return {"id": job_id, "cancelling": job["status"] == "running"}

    # -- requirements
    @app.get("/api/requirements/items")
    def items(q: str = "", kind: str = "", type: str = "", status: str = "", priority: str = "",
              analysis: str = "", connection_id: str = "", space: str = "", missing: bool = False,
              sort: str = "key", page: int = 1, size: int = 25, authorization: str | None = A,
              x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        size, page = max(1, min(100, size)), max(1, page)
        db = _db()
        try:
            runs = {c.id: store.last_success(db, ctx["tenant"], c.id) for c in _safe_list(db, ctx)}
            rows = store.list_sources(db, ctx["tenant"], connection_id, include_missing=True)
            if kind:
                rows = [r for r in rows if r["source"].kind.value == kind]
            rows = [r for r in rows if missing or r["present"]]
            words = q.strip().lower()
            if words:
                rows = [r for r in rows if words in r["source"].source_id.lower() or words in r["source"].title.lower()
                        or words in str(r["content"].get("description", "")).lower()]
            for field, wanted in (("type", type), ("status", status), ("priority", priority),
                                  ("space", space)):
                if wanted:
                    rows = [r for r in rows if str(r["content"].get(field, "")).lower() == wanted.lower()]
            out = [_item_row(db, ctx["tenant"], r, runs) for r in rows]
        finally:
            db.close()
        if analysis:
            out = [o for o in out if o["analysis"] == analysis]
        keyf = {"key": lambda o: (o["kind"], _natural(o["key"])), "updated": lambda o: o["updated"],
                "criteria": lambda o: o["criteria"], "summary": lambda o: o["summary"].lower(),
                "status": lambda o: o["status"].lower(), "priority": lambda o: o["priority"].lower()}
        reverse = sort.startswith("-")
        out.sort(key=keyf.get(sort.lstrip("-"), keyf["key"]), reverse=reverse)
        start = (page - 1) * size
        return {"items": out[start:start + size], "total": len(out), "page": page, "size": size}

    @app.get("/api/requirements/items/{connection_id}/{source_id}")
    def item(connection_id: str, source_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        key = _root_key(connection_id, source_id)
        db = _db()
        try:
            row = store.get_source(db, ctx["tenant"], key)
            if not row:
                raise HTTPException(404, "Not imported in your workspace.")
            src = row["source"]
            try:
                req = an.build_requirement(db, ctx["tenant"], key)
            except (LookupError, ValueError) as error:
                raise HTTPException(409, safe_error(error)) from None
            state, analysis = _analysis_state(db, ctx["tenant"], req.id)
            stale = an.stale(db, ctx["tenant"], analysis) if analysis else []
            linked = []
            for link in store.links_from(db, ctx["tenant"], key) + [
                    {"to_key": x["from_key"], "relation": x["relation"], "found_via": x["found_via"]}
                    for x in store.links_to(db, ctx["tenant"], key)]:
                other = store.get_source(db, ctx["tenant"], link["to_key"])
                linked.append({"key": link["to_key"].split(":")[-1], "kind": link["to_key"].split(":")[1],
                               "connection_id": link["to_key"].split(":")[0], "relation": link["relation"],
                               "found_via": link["found_via"], "title": other["source"].title if other else "",
                               "imported": bool(other), "present": bool(other and other["present"])})
            return {"key": src.source_id, "kind": src.kind.value, "connection_id": connection_id, "url": src.url,
                    "title": src.title, "version": src.version, "present": row["present"],
                    "updated": src.updated.isoformat(), "retrieved_at": src.retrieved_at.isoformat(),
                    "fields": row["content"], "requirement_id": req.id, "requirement_kind": req.kind,
                    "criteria": [_criterion(c) for c in req.criteria],
                    "sources": [{"key": s.key, "kind": s.kind.value, "id": s.source_id, "version": s.version,
                                 "url": s.url, "title": s.title} for s in req.sources],
                    "links": linked, "analysis": state, "stale_reasons": stale,
                    "analysis_summary": an.summary(analysis) if analysis else None}
        finally:
            db.close()

    @app.get("/api/requirements/items/{connection_id}/{source_id}/versions")
    def versions(connection_id: str, source_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        key = _root_key(connection_id, source_id)
        db = _db()
        try:
            hist = store.history(db, ctx["tenant"], key)
        finally:
            db.close()
        if not hist:
            raise HTTPException(404, "Not imported in your workspace.")
        return {"key": source_id, "versions": [
            {"version": v["source"].version, "updated": v["source"].updated.isoformat(),
             "retrieved_at": v["source"].retrieved_at.isoformat(), "content_hash": v["source"].content_hash,
             "title": v["source"].title, "fields": v["content"]} for v in hist]}

    @app.post("/api/requirements/items/{connection_id}/{source_id}/analyze")
    def analyze(connection_id: str, source_id: str, body: AnalyzeBody, authorization: str | None = A,
                x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.write")
        key = _root_key(connection_id, source_id)
        db = _db()
        try:
            if not store.get_source(db, ctx["tenant"], key):
                raise HTTPException(404, "Not imported in your workspace.")
            try:
                result = an.analyze(db, ctx["tenant"], key, ai=body.ai, actor=ctx["actor"])
            except (LookupError, ValueError) as error:
                raise HTTPException(400, safe_error(error)) from None
            return _analysis_view(db, ctx["tenant"], result)
        finally:
            db.close()

    @app.get("/api/requirements/items/{connection_id}/{source_id}/analysis")
    def get_analysis(connection_id: str, source_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        key = _root_key(connection_id, source_id)
        db = _db()
        try:
            row = store.get_source(db, ctx["tenant"], key)
            if not row:
                raise HTTPException(404, "Not imported in your workspace.")
            analysis = store.get_analysis(db, ctx["tenant"], _requirement_id(row["source"]))
            if analysis is None:
                raise HTTPException(404, "Not analysed yet.")
            return _analysis_view(db, ctx["tenant"], analysis)
        finally:
            db.close()

    @app.post("/api/requirements/items/{connection_id}/{source_id}/suggestions/{suggestion_id}/review")
    def review(connection_id: str, source_id: str, suggestion_id: str, body: ReviewBody,
               authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "review.write")
        if not ctx["reviewer"]:
            raise HTTPException(403, "Suggestions are reviewed by a named, signed-in person; a shared token cannot "
                                     "sign a review.")
        key = _root_key(connection_id, source_id)
        db = _db()
        try:
            row = store.get_source(db, ctx["tenant"], key)
            if not row:
                raise HTTPException(404, "Not imported in your workspace.")
            req_id = _requirement_id(row["source"])
            try:
                updated = an.review(db, ctx["tenant"], req_id, suggestion_id, body.answer, ctx["reviewer"],
                                    edit=body.edit.model_dump() if body.edit else None)
            except LookupError as error:
                raise HTTPException(404, safe_error(error)) from None
            except PermissionError as error:
                raise HTTPException(403, safe_error(error)) from None
            except ValueError as error:
                raise HTTPException(400, safe_error(error)) from None
            return {"suggestion": updated.model_dump(mode="json"),
                    "analysis": _analysis_view(db, ctx["tenant"], store.get_analysis(db, ctx["tenant"], req_id))}
        finally:
            db.close()

    @app.get("/api/requirements/reviews")
    def reviews(status: str = "needs_review", q: str = "", authorization: str | None = A,
                x_qa_token: str | None = Q):
        """Every suggestion of the tenant's analysed requirements, with the criteria and source words behind it."""
        ctx = _context(authorization, x_qa_token, "run.read")
        if status not in ("needs_review", "accepted", "rejected", "stale", "all"):
            raise HTTPException(400, "status is needs_review, accepted, rejected, stale or all")
        from . import approvals
        db = _db()
        try:
            out = []
            for a in store.list_analyses(db, ctx["tenant"]):
                source = a.requirement.sources[0]
                criteria = {c.id: c for c in a.requirement.criteria}
                stale = bool(an.stale(db, ctx["tenant"], a))
                for s in a.suggestions:
                    if status == "stale" and not stale:
                        continue
                    if status not in ("all", "stale") and s.review.value != status:
                        continue
                    if q and q.lower() not in (s.title + " " + a.requirement.id + " " + a.requirement.title).lower():
                        continue
                    try:
                        row = approvals.get_approval(s.approval_id, tenant_id=ctx["tenant"]) if s.approval_id else {}
                    except (KeyError, PermissionError):
                        row = {}
                    out.append({
                        "suggestion": s.model_dump(mode="json"), "requirement_id": a.requirement.id,
                        "requirement_title": a.requirement.title, "connection_id": source.connection_id,
                        "key": source.source_id, "stale": stale,
                        "criteria": [_criterion(criteria[c]) for c in s.criterion_ids if c in criteria],
                        "decided_by": row.get("decided_by", ""), "decided_at": row.get("decided_at"),
                        "approval_status": row.get("status", "")})
        finally:
            db.close()
        can = _can_review(authorization, x_qa_token, ctx)
        return {"reviews": out, "total": len(out), "can_review": can, "reviewer": ctx["reviewer"] if can else None}

    # -- Phase 4: test cases (approved scenarios -> executable tests)
    @app.post("/api/requirements/items/{connection_id}/{source_id}/test-cases")
    def generate_tests(connection_id: str, source_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.write")
        key = _root_key(connection_id, source_id)
        db = bridge.connect()
        try:
            row = store.get_source(db, ctx["tenant"], key)
            if not row:
                raise HTTPException(404, "Not imported in your workspace.")
            try:
                out = bridge.generate(db, ctx["tenant"], _requirement_id(row["source"]), actor=ctx["actor"])
            except LookupError as error:
                raise HTTPException(409, safe_error(error) + " - analyse it and accept test ideas first") from None
            except ValueError as error:
                raise HTTPException(409, safe_error(error)) from None
            out["test_cases"] = bridge.list_cases(db, ctx["tenant"], out["requirement"])
            return out
        finally:
            db.close()

    @app.get("/api/requirements/test-cases")
    def test_cases(requirement: str = "", status: str = "", q: str = "", authorization: str | None = A,
                   x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = bridge.connect()
        try:
            bridge.refresh(db, ctx["tenant"])
            rows = bridge.list_cases(db, ctx["tenant"], requirement, status)
        finally:
            db.close()
        if q:
            rows = [c for c in rows if q.lower() in (c["id"] + " " + c["title"] + " " + c["requirement_id"]).lower()]
        return {"test_cases": rows, "total": len(rows), "statuses": bridge.STATUSES}

    @app.get("/api/requirements/test-cases/{case_id}")
    def test_case(case_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = bridge.connect()
        try:
            c = bridge.get_case(db, ctx["tenant"], case_id)
            if not c:
                raise HTTPException(404, "No such test case in your workspace.")
            return {"test_case": c, "history": bridge.case_history(db, ctx["tenant"], case_id),
                    "results": bridge.case_results(db, ctx["tenant"], case_id)}
        finally:
            db.close()

    @app.put("/api/requirements/test-cases/{case_id}")
    def edit_test_case(case_id: str, body: CaseEdit, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.write")
        db = bridge.connect()
        try:
            try:
                c = bridge.edit_case(db, ctx["tenant"], case_id, body.model_dump(), ctx["actor"])
            except LookupError:
                raise HTTPException(404, "No such test case in your workspace.") from None
            except ValueError as error:
                raise HTTPException(409, safe_error(error)) from None
        finally:
            db.close()
        _audit(ctx, "test_case.edit", True, test_case=case_id)
        return {"test_case": c}

    @app.post("/api/requirements/test-cases/{case_id}/approve")
    def approve_test_case(case_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "review.write")
        if not ctx["reviewer"]:
            raise HTTPException(403, "Test cases are approved by a named, signed-in person.")
        db = bridge.connect()
        try:
            try:
                c = bridge.approve_case(db, ctx["tenant"], case_id, ctx["reviewer"])
            except LookupError:
                raise HTTPException(404, "No such test case in your workspace.") from None
            except ValueError as error:
                raise HTTPException(409, safe_error(error)) from None
        finally:
            db.close()
        _audit(ctx, "test_case.approve", True, test_case=case_id)
        return {"test_case": c}

    # -- Phase 4: executions (the EXISTING Qpilot run executes; results come from its files)
    def _saved_account(db, tenant: str, t, ids: list[str]) -> tuple[str, str]:
        projects = sorted({c.split("-", 1)[1].rsplit("-", 1)[0].split("-")[0] for c in ids if c.startswith("TC-")}
                          | ({t.project_key.upper()} if t.project_key else set()))
        for p in projects:  # (the project's saved account for THIS website only)
            user, pw = workflow.test_account(db, tenant, p, t.environment, t.url)
            if user and pw:
                return user, pw
        return "", ""

    def _preflight(db, ctx: dict, body: ExecutionBody, ids: list[str]) -> dict:
        t = body.target
        has_account = bool(t.test_username and t.test_password) or (
            t.use_saved_account and all(_saved_account(db, ctx["tenant"], t, ids)))
        return execution_preflight.check(
            strategy=body.strategy, case_count=len(ids), url=t.url, authorized=t.authorized, app_type=t.type,
            llm_provider=t.llm_provider, llm_model=t.llm_model, api_key=t.api_key, has_account=has_account,
            probe=PREFLIGHT_PROBE, demo_checkout=t.demo_checkout)

    @app.post("/api/requirements/executions/preflight")
    def preflight_execution(body: ExecutionBody, authorization: str | None = A, x_qa_token: str | None = Q):
        """Can this execution test anything? Every prerequisite with a recovery action; nothing is created."""
        ctx = _context(authorization, x_qa_token, "run.write")
        db = bridge.connect()
        try:
            return _preflight(db, ctx, body, _scope_cases(db, ctx["tenant"], body.scope))
        finally:
            db.close()

    @app.post("/api/requirements/executions")
    def start_execution(body: ExecutionBody, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.write")
        if not body.target.authorized:
            raise HTTPException(400, "Confirm that you own the application or have permission to test it.")
        db = bridge.connect()
        try:
            ids = _scope_cases(db, ctx["tenant"], body.scope)
            if body.strategy != "autonomous" and not ids:
                raise HTTPException(400, "No approved test case matches this selection. Generate test cases from "
                                         "accepted ideas first.")
            # a run that cannot automate anything is never started (it used to end 'complete', all 'Not automated')
            pre = _preflight(db, ctx, body, ids)
            if not pre["ok"]:
                first = next(p for p in pre["problems"] if p["blocking"])
                _audit(ctx, "execution.preflight", False, problems=[p["code"] for p in pre["problems"]])
                raise HTTPException(409, first["message"])
            if pre["needs_ai"] or body.target.llm_provider:  # (the AI checked is the AI the run gets)
                body = body.model_copy(update={"target": body.target.model_copy(update={
                    "llm_provider": pre["ai"]["provider"], "llm_model": pre["ai"]["model"] or body.target.llm_model})})
            bridge.plan_dependencies(db, ctx["tenant"])  # (the current links / preconditions; AI and manual kept)
            try:
                planned = bridge.plan(db, ctx["tenant"], ids, body.strategy, body.target.public(), actor=ctx["actor"])
            except (LookupError, ValueError) as error:
                raise HTTPException(400, safe_error(error)) from None
            ex = planned["execution"]
            from . import server
            t = body.target
            projects = sorted({c.split("-", 1)[1].rsplit("-", 1)[0].split("-")[0] for c in ex.get("case_ids", [])
                               if c.startswith("TC-")} | ({t.project_key.upper()} if t.project_key else set()))
            if t.save_target:
                for p in projects:
                    workflow.save_target(db, ctx["tenant"], p, t.url, environment=t.environment, actor=ctx["actor"],
                                         username=t.test_username, password=t.test_password)
            if t.use_saved_account and not (t.test_username and t.test_password):
                user, pw = _saved_account(db, ctx["tenant"], t, ex.get("case_ids", []))
                if user and pw:
                    t = t.model_copy(update={"test_username": user, "test_password": pw})
            demo = t.demo_checkout and body.strategy == "requirements"
            req = server.RunRequest(
                source=t.url, authorized=True, environment="staging" if demo else t.environment,
                writes_confirmed=demo, allow_actions="pay" if demo else None, test_payment=demo,
                max_pages=t.max_pages,
                show_browser=t.show_browser, record_video=t.record_video, thorough=t.thorough,
                llm_provider=t.llm_provider or None, llm_model=t.llm_model or None, api_key=t.api_key or None,
                test_username=t.test_username or None, test_password=t.test_password or None,
                auth_mode="existing" if t.test_username and t.test_password else "auto",
                page_timeout_s=t.page_timeout_s, requirement_tests=planned["requirement_tests"],
                requirements_only=body.strategy == "requirements",
                objective_focus=body.strategy == "requirements", fresh=False)
            caller = ctx["actor"] if ctx["mode"] in ("principal", "oidc") else None
            try:
                job = server._launch_run(req, caller)
            except HTTPException as error:
                with db:
                    db.execute("UPDATE req_executions SET status = 'failed' WHERE tenant_id = ? AND id = ?",
                               (ctx["tenant"], ex["id"]))
                raise HTTPException(error.status_code, f"The test run could not start: {error.detail}") from None
            if isinstance(job, JSONResponse):
                raise HTTPException(job.status_code, "The test run could not start.")
            bridge.attach_run(db, ctx["tenant"], ex["id"], str(job.get("id")))
        finally:
            db.close()
        _watch(ctx["tenant"], ex["id"], int(job.get("id")))
        _audit(ctx, "execution.start", True, execution=ex["id"], strategy=body.strategy, cases=len(ex["case_ids"]),
               target=body.target.url[:200])
        return {"execution": {**ex, "status": "running", "run_id": str(job.get("id"))}, "job": job.get("id")}

    @app.get("/api/requirements/executions")
    def executions(limit: int = 50, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = bridge.connect()
        try:
            out = []
            for ex in bridge.list_executions(db, ctx["tenant"], limit):
                out.append(_with_outcome(_settle_execution(db, ctx["tenant"], ex)))
            return {"executions": out}
        finally:
            db.close()

    @app.get("/api/requirements/executions/{execution_id}")
    def execution(execution_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = bridge.connect()
        try:
            ex = bridge.get_execution(db, ctx["tenant"], execution_id)
            if not ex:
                raise HTTPException(404, "No such execution in your workspace.")
            ex = _with_outcome(_settle_execution(db, ctx["tenant"], ex))
            from . import server
            job = server.jobs.get(int(ex["run_id"])) if str(ex.get("run_id", "")).isdigit() else None
            try:
                live = server._public(job) if job else None
            except (KeyError, TypeError, ValueError):  # (the live view is extra: results come from the run's files)
                live = None
            return {"execution": ex, "results": bridge.results(db, ctx["tenant"], execution_id),
                    "live": {k: live.get(k) for k in ("status", "current", "stages", "run", "lines", "elapsed",
                                                      "pages", "cases", "scripts", "report_ready", "live_pages")
                             if k in live} if live else None}
        finally:
            db.close()

    @app.post("/api/requirements/executions/{execution_id}/cancel")
    def cancel_execution(execution_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.write")
        db = bridge.connect()
        try:
            ex = bridge.get_execution(db, ctx["tenant"], execution_id)
        finally:
            db.close()
        if not ex:
            raise HTTPException(404, "No such execution in your workspace.")
        from . import server
        job = server.jobs.get(int(ex["run_id"])) if str(ex.get("run_id", "")).isdigit() else None
        if not job or job.get("status") != "running":
            return {"execution": execution_id, "cancelling": False}
        server.stop_run(int(ex["run_id"]), authorization, x_qa_token)
        _audit(ctx, "execution.cancel", True, execution=execution_id)
        return {"execution": execution_id, "cancelling": True}

    # -- prerequisites between test cases (atlassian/prerequisites.py): the persistent graph a run follows
    @app.get("/api/requirements/dependencies")
    def dependencies(authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = bridge.connect()
        try:
            return bridge.dependency_graph(db, ctx["tenant"])
        finally:
            db.close()

    @app.post("/api/requirements/dependencies/plan")
    def plan_dependencies(body: DependencyPlanBody, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "review.write")
        db = bridge.connect()
        try:
            graph = bridge.plan_dependencies(db, ctx["tenant"], use_ai=body.use_ai)
        finally:
            db.close()
        _audit(ctx, "dependencies.plan", True, edges=len(graph["edges"]), cycles=len(graph["cycles"]),
               ai=body.use_ai)
        return graph

    @app.put("/api/requirements/dependencies")
    def set_dependency(body: DependencyBody, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "review.write")
        db = bridge.connect()
        try:
            for cid in (body.case_id, body.requires_id):
                if not bridge.get_case(db, ctx["tenant"], cid):
                    raise HTTPException(404, f"{cid} is not a test case of this workspace.")
            try:
                from .atlassian import prerequisites
                prerequisites.set_manual(db, ctx["tenant"], body.case_id, body.requires_id, body.present,
                                         body.reason)
            except ValueError as error:
                raise HTTPException(400, safe_error(error)) from None
            graph = bridge.dependency_graph(db, ctx["tenant"])
        finally:
            db.close()
        _audit(ctx, "dependencies.set", True, case=body.case_id, requires=body.requires_id, present=body.present)
        return graph

    @app.get("/api/requirements/traceability")
    def traceability(q: str = "", coverage: str = "", authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = bridge.connect()
        try:
            rows = bridge.matrix(db, ctx["tenant"])
        finally:
            db.close()
        if q:
            rows = [r for r in rows if q.lower() in json.dumps(r).lower()]
        if coverage:
            rows = [r for r in rows if r["coverage"] == coverage]
        return {"rows": rows, "total": len(rows)}

    @app.get("/api/requirements/coverage/execution")
    def execution_coverage(authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = bridge.connect()
        try:
            return {"coverage": bridge.coverage(db, ctx["tenant"]), "impacted": bridge.impacted(db, ctx["tenant"])}
        finally:
            db.close()

    # -- the guided workflow and the application under test
    def _connection_ready(db, ctx: dict) -> bool:
        conns = [c for c in store.list_connections(db, ctx["tenant"]) if c.product == Product.jira]
        return any(credentials.status(ctx["tenant"], c.token_ref, site=c.site_url)["configured"] for c in conns)

    def _workflow_answer(db, ctx: dict, draft: dict) -> dict:
        return {"draft": draft, "state": workflow.state(db, ctx["tenant"], draft,
                                                        connection_ready=_connection_ready(db, ctx)),
                "steps": list(workflow.STEPS)}

    @app.get("/api/requirements/workflow")
    def get_workflow(authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = bridge.connect()
        try:
            return _workflow_answer(db, ctx, workflow.get_draft(db, ctx["tenant"], ctx["actor"]))
        finally:
            db.close()

    @app.put("/api/requirements/workflow/draft")
    def put_draft(body: DraftBody, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = bridge.connect()
        try:
            try:
                d = workflow.update_draft(db, ctx["tenant"], ctx["actor"], body.changes, body.draft_id)
            except ValueError as error:
                raise HTTPException(409, str(error)) from None
            return _workflow_answer(db, ctx, d)
        finally:
            db.close()

    @app.post("/api/requirements/workflow/new")
    def new_workflow(body: DraftBody, authorization: str | None = A, x_qa_token: str | None = Q):
        """New Test: a fresh draft. Executions, reports, requirements and test cases are all kept."""
        ctx = _context(authorization, x_qa_token, "run.read")
        db = bridge.connect()
        try:
            d = workflow.new_draft(db, ctx["tenant"], ctx["actor"], **body.changes)
            _audit(ctx, "workflow.new", True, draft=d["id"])
            return _workflow_answer(db, ctx, d)
        finally:
            db.close()

    @app.get("/api/requirements/targets/resolve")
    def resolve_target(requirements: str = "", environment: str = "test", authorization: str | None = A,
                       x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        reqs = [r.strip() for r in requirements.split(",") if r.strip()][:100]
        db = bridge.connect()
        try:
            return workflow.resolve(db, ctx["tenant"], reqs, environment if environment in ("test", "staging")
                                    else "test")
        finally:
            db.close()

    @app.put("/api/requirements/targets")
    def put_target(body: TargetBody, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.write")
        if not body.authorized:
            raise HTTPException(400, "Confirm that you own the application or have permission to test it.")
        from .safety import UrlError, check_target
        try:
            check_target(body.url, resolve=False)
        except UrlError as error:
            raise HTTPException(400, str(error)) from None
        db = bridge.connect()
        try:
            try:
                t = workflow.save_target(db, ctx["tenant"], body.project_key, body.url, environment=body.environment,
                                         actor=ctx["actor"], app_type=body.app_type, username=body.test_username,
                                         password=body.test_password)
            except ValueError as error:
                raise HTTPException(400, str(error)) from None
        finally:
            db.close()
        _audit(ctx, "target.save", True, project=body.project_key, environment=body.environment)
        return {"target": t}

    @app.delete("/api/requirements/targets/{project_key}/account")
    def forget_target_account(project_key: str, environment: str = "test", authorization: str | None = A,
                              x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.write")
        db = bridge.connect()
        try:
            workflow.forget_account(db, ctx["tenant"], project_key.upper(), environment)
        finally:
            db.close()
        _audit(ctx, "target.account.delete", True, project=project_key)
        return {"removed": True}

    @app.post("/api/requirements/targets/check")
    def check_target_url(body: UrlBody, authorization: str | None = A, x_qa_token: str | None = Q):
        _context(authorization, x_qa_token, "run.write")
        from . import target_check
        return target_check.check(body.url)

    # -- defects and controlled Jira write-back (Phase 5)
    from .atlassian import defects as dfx, writeback as wb

    def _wb_db():
        db = bridge.connect()
        dfx.ensure(db)
        wb.ensure(db)
        return db

    @app.get("/api/requirements/defects")
    def list_defects(status: str = "", requirement: str = "", authorization: str | None = A,
                     x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = _wb_db()
        try:
            rows = dfx.list_defects(db, ctx["tenant"], status, requirement)
        finally:
            db.close()
        counts: dict[str, int] = {}
        for d in rows:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        return {"defects": rows, "total": len(rows), "counts": counts}

    @app.get("/api/requirements/defects/{defect_id}")
    def get_defect(defect_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = _wb_db()
        try:
            dfx.refresh(db, ctx["tenant"])
            d = dfx.get_defect(db, ctx["tenant"], defect_id)
        finally:
            db.close()
        if not d:
            raise HTTPException(404, "No such defect in your workspace.")
        return {"defect": d}

    @app.post("/api/requirements/defects/{defect_id}/dismiss")
    def dismiss_defect(defect_id: str, body: DismissBody, authorization: str | None = A,
                       x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "review.write")
        if not ctx["reviewer"]:
            raise HTTPException(403, "A defect is dismissed only by a named, signed-in person.")
        db = _wb_db()
        try:
            d = dfx.dismiss(db, ctx["tenant"], defect_id, ctx["reviewer"], body.reason)
        except LookupError:
            raise HTTPException(404, "No such defect in your workspace.") from None
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        finally:
            db.close()
        _audit(ctx, "defect.dismiss", True, defect=defect_id)
        return {"defect": d}

    def _wb_state(db, ctx: dict) -> list[dict]:
        token = credentials.status(ctx["tenant"], wb.WRITE_TOKEN)["configured"]
        conns = [c for c in store.list_connections(db, ctx["tenant"]) if c.product == Product.jira]
        return [{**wb.readiness(db, ctx["tenant"], c.id, token), "site_url": c.site_url} for c in conns]

    @app.get("/api/requirements/writeback")
    def writeback_state(status: str = "", authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = _wb_db()
        try:
            return {"connections": _wb_state(db, ctx), "writes": wb.list_writes(db, ctx["tenant"], status),
                    "server_allows": wb.server_allows(), "server_setting": wb.SERVER_ENV,
                    "write_token": credentials.status(ctx["tenant"], wb.WRITE_TOKEN),
                    "can_review": _can_review(authorization, x_qa_token, ctx)}
        finally:
            db.close()

    @app.put("/api/requirements/writeback/settings/{connection_id}")
    def writeback_settings(connection_id: str, body: WritebackSettingsBody, authorization: str | None = A,
                           x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "tenant.manage")
        db = _wb_db()
        try:
            _connection(db, ctx, connection_id, Product.jira)
            s = wb.set_settings(db, ctx["tenant"], connection_id, enabled=body.enabled, project_key=body.project_key,
                                issue_type=body.issue_type, actor=ctx["actor"])
        except PermissionError as error:
            raise HTTPException(403, str(error)) from None
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        finally:
            db.close()
        return {"settings": s}

    @app.put("/api/requirements/writeback/token")
    def put_write_token(body: TokenBody, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "tenant.manage")
        try:
            state = credentials.set_token(ctx["tenant"], wb.WRITE_TOKEN, body.token)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        _audit(ctx, "token.set", True, secret_name=wb.WRITE_TOKEN)
        return {"credential": state}

    @app.delete("/api/requirements/writeback/token")
    def delete_write_token(authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "tenant.manage")
        removed = credentials.delete_token(ctx["tenant"], wb.WRITE_TOKEN)
        _audit(ctx, "token.delete", True, secret_name=wb.WRITE_TOKEN)
        return {"removed": removed, "credential": credentials.status(ctx["tenant"], wb.WRITE_TOKEN)}

    @app.post("/api/requirements/writeback/proposals")
    def propose_write(body: ProposalBody, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.write")
        if bool(body.execution_id) == bool(body.defect_id):
            raise HTTPException(400, "Propose either an execution's results or one defect.")
        db = _wb_db()
        try:
            if body.execution_id:
                writes = wb.propose_results_comment(db, ctx["tenant"], body.execution_id, ctx["actor"])
            else:
                dfx.refresh(db, ctx["tenant"])
                writes = [wb.propose_defect(db, ctx["tenant"], body.defect_id, ctx["actor"])]
        except LookupError:
            raise HTTPException(404, "Not found in your workspace.") from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        finally:
            db.close()
        return {"writes": writes}

    @app.get("/api/requirements/writeback/{write_id}")
    def get_write(write_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = _wb_db()
        try:
            w = wb.get_write(db, ctx["tenant"], write_id)
        finally:
            db.close()
        if not w:
            raise HTTPException(404, "No such write in your workspace.")
        return {"write": w}

    def _decide_write(write_id: str, answer: str, authorization, x_qa_token) -> dict:
        ctx = _context(authorization, x_qa_token, "review.write")
        if not ctx["reviewer"]:
            raise HTTPException(403, "A Jira write is approved only by a named, signed-in reviewer.")
        db = _wb_db()
        try:
            fn = wb.approve if answer == "yes" else wb.reject
            return {"write": fn(db, ctx["tenant"], write_id, ctx["reviewer"])}
        except LookupError:
            raise HTTPException(404, "No such write in your workspace.") from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        except PermissionError as error:
            raise HTTPException(403, str(error)) from None
        finally:
            db.close()

    @app.post("/api/requirements/writeback/{write_id}/approve")
    def approve_write(write_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        return _decide_write(write_id, "yes", authorization, x_qa_token)

    @app.post("/api/requirements/writeback/{write_id}/reject")
    def reject_write(write_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        return _decide_write(write_id, "no", authorization, x_qa_token)

    @app.post("/api/requirements/writeback/{write_id}/send")
    def send_write(write_id: str, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "tenant.manage")
        db = _wb_db()
        try:
            w = wb.get_write(db, ctx["tenant"], write_id)
            if not w:
                raise HTTPException(404, "No such write in your workspace.")
            conn = _connection(db, ctx, w["connection_id"], Product.jira)
            w = wb.send(db, ctx["tenant"], write_id, ctx["actor"], connection=conn,
                        secret=credentials.resolver(ctx["tenant"]), base_url=CLIENT_BASE_URL)
        except PermissionError as error:
            raise HTTPException(403, str(error)) from None
        finally:
            db.close()
        return {"write": w}

    # -- overview, coverage, audit
    @app.get("/api/requirements/overview")
    def overview(authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = _db()
        try:
            conns = _safe_list(db, ctx)
            rows = store.list_sources(db, ctx["tenant"], include_missing=True)
            analyses = store.list_analyses(db, ctx["tenant"])
            stale = sum(1 for a in analyses if an.stale(db, ctx["tenant"], a))
            runs = store.sync_runs(db, ctx["tenant"], limit=1)
        finally:
            db.close()
        jira_rows = [r for r in rows if r["source"].kind == SourceKind.jira_issue]
        return {
            "connections": [{"id": c.id, "product": c.product.value, "site_url": c.site_url,
                             "credential": credentials.status(ctx["tenant"], c.token_ref,
                                                              site=c.site_url)["configured"]}
                            for c in conns],
            "requirements": sum(1 for r in jira_rows if r["present"]),
            "pages": sum(1 for r in rows if r["source"].kind == SourceKind.confluence_page and r["present"]),
            "missing": sum(1 for r in rows if not r["present"]),
            "analysed": len(analyses), "stale_analyses": stale,
            "criteria": sum(len(a.requirement.criteria) for a in analyses),
            "conflicts_open": sum(1 for a in analyses for x in a.conflicts if x.status == "open"),
            "quality_issues": sum(len(a.issues) for a in analyses),
            "pending_reviews": sum(1 for a in analyses for s in a.suggestions if s.review.value == "needs_review"),
            "last_import": runs[0] if runs else None,
            "running_imports": sum(1 for j in JOBS._jobs.values() if j["tenant"] == ctx["tenant"]
                                   and j["status"] == "running"),
            "capabilities": CAPABILITIES,
        }

    @app.get("/api/requirements/coverage")
    def coverage(authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "run.read")
        db = _db()
        try:
            analyses = store.list_analyses(db, ctx["tenant"])
            rows = []
            totals: dict[str, int] = {}
            for a in analyses:
                counts: dict[str, int] = {}
                for status in a.coverage.values():
                    counts[status.value] = counts.get(status.value, 0) + 1
                    totals[status.value] = totals.get(status.value, 0) + 1
                rows.append({"requirement": a.requirement.id, "title": a.requirement.title,
                             "criteria": len(a.requirement.criteria), "coverage": counts,
                             "stale": bool(an.stale(db, ctx["tenant"], a))})
        finally:
            db.close()
        return {"basis": "approved test ideas (executed coverage comes with Phase 5 traceability)",
                "totals": totals, "requirements": rows}

    @app.get("/api/requirements/audit")
    def audit(limit: int = 100, authorization: str | None = A, x_qa_token: str | None = Q):
        ctx = _context(authorization, x_qa_token, "audit.read" if _logged_in() else "run.read")
        from . import audit_store
        events = audit_store.list_audits(limit=500, tenant_id=ctx["tenant"])
        mine = [e for e in events if str(e.get("action", "")).startswith(ACTION_PREFIX)]
        return {"events": mine[: max(1, min(500, limit))]}


# ---------------------------------------------------------------- small helpers

def _logged_in() -> bool:
    from .dashboard_auth import auth_mode
    return auth_mode() in ("principal", "oidc")


def _safe_list(db, ctx) -> list[Connection]:
    try:
        return store.list_connections(db, ctx["tenant"])
    except ValueError:
        return []


def _natural(key: str):
    import re
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", key)]


def _progress(result: dict) -> dict:
    return {k: (len(v) if isinstance(v, list) else v) for k, v in result.items()
            if k in ("new", "changed", "unchanged", "reappeared", "pages", "failed_items", "new_keys",
                     "changed_keys")}


def _require_valid(client: Client, conn: Connection, filters: ImportFilter) -> None:
    query = jira.build_jql(filters.project, filters.types or conn.work_item_types, jira.filter_jql(filters),
                           order=False)
    errors = jira.validate_jql(client, query)
    if errors:
        raise ValueError("Jira refused the JQL filter: " + "; ".join(errors)[:400])


def _criterion(c) -> dict:
    cit = c.citations[0]
    return {"id": c.id, "text": c.text, "given": c.given, "when": c.when, "then": c.then,
            "extraction": c.extraction.value, "review": c.review.value, "automatable": c.automatable,
            "not_automatable_reason": c.not_automatable_reason,
            "citation": {"source": cit.source.source_id, "kind": cit.source.kind.value, "version": cit.source.version,
                         "locator": cit.locator, "quote": cit.quote, "url": cit.source.url}}


def _analysis_view(db, tenant: str, analysis) -> dict:
    data = analysis.model_dump(mode="json")
    return {"analysis": data, "summary": an.summary(analysis), "stale_reasons": an.stale(db, tenant, analysis),
            "history": store.analysis_history(db, tenant, analysis.requirement.id),
            "analyzed_at": analysis.analyzed_at.isoformat(), "generated_at": datetime.now(UTC).isoformat()}
