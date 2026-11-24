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

import threading
import time
import uuid
from datetime import UTC, datetime

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from .atlassian import analysis as an, confluence, credentials, jira, store, sync
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
CLIENT_BASE_URL = ""  # tests only: a local mock site on 127.0.0.1 (client.Client refuses anything else)
MAX_JOBS = 200

# Which workspace actions exist in this build. Later phases switch theirs on; the Studio shows the rest as coming.
CAPABILITIES = {
    "import_requirements": True, "analyze_requirements": True, "review_suggestions": True,
    "generate_test_cases": False, "run_selected_tests": False, "run_impacted_tests": False,
    "run_all_approved_tests": False, "traceability": False, "jira_write_back": False,
}
COMING = {"generate_test_cases": "Phase 4 (requirements to test cases)", "run_selected_tests": "Phase 4",
          "run_impacted_tests": "Phase 4", "run_all_approved_tests": "Phase 4",
          "traceability": "Phase 5", "jira_write_back": "Phase 5 (off by default, every write approved)"}


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
    return Client(conn, secret=credentials.resolver(ctx["tenant"]), base_url=CLIENT_BASE_URL, max_retries=3,
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
    data["credential"] = credentials.status(tenant, conn.token_ref)
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
        return {"capabilities": CAPABILITIES, "coming": COMING, "tenant": ctx["tenant"], "actor": ctx["actor"],
                "can_review": _can_review(authorization, x_qa_token, ctx), "read_only_atlassian": True}

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
        try:
            conn = Connection(id=body.id, tenant_id=ctx["tenant"], product=body.product, site_url=body.site_url,
                              email=body.email, token_ref=body.token_ref or DEFAULT_TOKEN_REF[body.product.value],
                              work_item_types=body.work_item_types or ["Story"], classification=body.classification)
        except ValueError as error:
            _audit(ctx, "connection.save", False, connection=body.id, why=safe_error(error)[:200])
            raise HTTPException(400, safe_error(error)) from None
        db = _db()
        try:
            store.save_connection(db, conn)
        finally:
            db.close()
        _audit(ctx, "connection.save", True, connection=conn.id, site=conn.site_url, product=conn.product.value)
        return _public(conn, ctx["tenant"])

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
            state = credentials.set_token(ctx["tenant"], conn.token_ref, body.token)
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
                "credential": credentials.status(ctx["tenant"], conn.token_ref)}

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
                             "credential": credentials.status(ctx["tenant"], c.token_ref)["configured"]}
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
