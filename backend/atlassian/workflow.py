"""The guided Jira testing workflow (connect -> import -> explore -> analyse -> review -> test cases -> execute -> live
-> report) and target resolution. Stores only: no HTTP here (the reachability check is backend/target_check.py).

  drafts    one workflow DRAFT per person and tenant: what they chose so far (connection, project, requirement ids,
            test case ids, strategy, target url, execution id, step). Never a password, token or key. A draft is not
            an execution: New Test starts a fresh draft (a new id) and never deletes executions, reports,
            requirements or test cases. A draft remembers its execution id only once that run was started from it.
  state     facts from the stores (is a Jira connection authenticated, how many requirements are imported /
            analysed / have accepted ideas / runnable test cases, which execution belongs to this draft) - the
            stepper's "completed" marks come from these, never from "the page was visited".
  targets   the application under test for a Jira project + environment, saved only with the person's
            authorization; its test account (optional) is kept in the owner-only credentials file
            (credentials.set_account: DPAPI on Windows, chmod 600 elsewhere), never in this database, never returned. resolve() lists candidates with their SOURCE:
              saved target of the project          (authorized)
              target of an earlier execution of the project's test cases   (authorized when that run was started)
              a website address written in the requirement text     (a candidate only: needs confirmation)
            Atlassian / Confluence / GitHub / documentation / image links are never candidates. Exactly one
            authorized address -> found; several -> the person chooses; none -> the person enters one.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

from . import credentials

SCHEMA = """
CREATE TABLE IF NOT EXISTS req_workflow_drafts (
    tenant_id TEXT NOT NULL, actor TEXT NOT NULL, id TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (tenant_id, actor));
CREATE TABLE IF NOT EXISTS req_targets (
    tenant_id TEXT NOT NULL, project_key TEXT NOT NULL, environment TEXT NOT NULL, updated_at TEXT NOT NULL,
    data TEXT NOT NULL, PRIMARY KEY (tenant_id, project_key, environment));
"""
STEPS = ("connect", "import", "explorer", "analysis", "reviews", "builder", "execution", "agents", "reports")
DRAFT_KEYS = {"connection_id": str, "project_key": str, "requirement_ids": list, "test_case_ids": list,
              "strategy": str, "target_url": str, "target_source": str, "environment": str, "execution_id": str,
              "step": str, "app_type": str, "ai_provider": str, "ai_model": str}  # (the AI's NAME only)
NOT_TARGETS = re.compile(r"(^|\.)(atlassian\.(net|com)|jira\.com|github\.com|githubusercontent\.com|gitlab\.com|"
                         r"bitbucket\.org|readthedocs\.io|wikipedia\.org|docs\.google\.com|drive\.google\.com|"
                         r"confluence\.[a-z.]+|youtube\.com|youtu\.be|figma\.com|loom\.com)$"
                         r"|^(docs?|developers?|help|support|wiki|cdn|static|images?|img|assets)\.", re.I)
NOT_TARGET_PATH = re.compile(r"\.(png|jpe?g|gif|svg|webp|ico|pdf|docx?|xlsx?|pptx?|zip|mp4|mov)$|/wiki/|/browse/[A-Z]|"
                             r"^/docs?(/|$)", re.I)
URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def ensure(db) -> None:
    db.executescript(SCHEMA)


# ---------------------------------------------------------------- drafts
def _clean(data: dict) -> dict:
    out = {}
    for k, kind in DRAFT_KEYS.items():
        if k not in data:
            continue
        v = data[k]
        if kind is list:
            out[k] = [str(x)[:80] for x in (v or []) if str(x).strip()][:200] if isinstance(v, list) else []
        else:
            out[k] = str(v or "")[:500]
    if "step" in out and out["step"] not in STEPS:
        out["step"] = ""
    if out.get("strategy") and out["strategy"] not in ("requirements", "hybrid", "autonomous"):
        out["strategy"] = ""
    if out.get("app_type") and out["app_type"] not in ("web", "android"):
        out["app_type"] = "web"
    return out


def new_draft(db, tenant: str, actor: str, **start) -> dict:
    ensure(db)
    d = {"id": "WF-" + uuid.uuid4().hex[:10], "created_at": _now(), "strategy": "requirements", "app_type": "web",
         "environment": "test", **_clean(start)}
    with db:
        db.execute("INSERT OR REPLACE INTO req_workflow_drafts (tenant_id, actor, id, updated_at, data) "
                   "VALUES (?, ?, ?, ?, ?)", (tenant, actor, d["id"], _now(), json.dumps(d)))
    return d


def get_draft(db, tenant: str, actor: str) -> dict:
    ensure(db)
    r = db.execute("SELECT data FROM req_workflow_drafts WHERE tenant_id = ? AND actor = ?",
                   (tenant, actor)).fetchone()
    return json.loads(r["data"]) if r else new_draft(db, tenant, actor)


def update_draft(db, tenant: str, actor: str, changes: dict, draft_id: str = "") -> dict:
    """Merge changes into the person's CURRENT draft. A change for an older draft (another tab, a late answer) is
    refused, so an old workflow never overwrites a new one."""
    d = get_draft(db, tenant, actor)
    if draft_id and draft_id != d["id"]:
        raise ValueError("this workflow was replaced by a newer one (New Test); reload to continue it")
    d.update(_clean(changes))
    with db:
        db.execute("UPDATE req_workflow_drafts SET updated_at = ?, data = ? WHERE tenant_id = ? AND actor = ?",
                   (_now(), json.dumps(d), tenant, actor))
    return d


def state(db, tenant: str, draft: dict, *, connection_ready: bool) -> dict:
    """Facts for the stepper (completed = what the stores say, not what was visited)."""
    from . import analysis as an, bridge, store
    reqs = list(draft.get("requirement_ids") or [])
    imported = list(store.list_sources(db, tenant))
    keys = {r["source"].source_id if r["source"].kind.value == "jira_issue" else f"conf-{r['source'].source_id}"
            for r in imported}
    analyses = {a.requirement.id: a for a in store.list_analyses(db, tenant)}
    chosen = [r for r in reqs if r in keys] or []
    analysed = [r for r in chosen if r in analyses and not an.stale(db, tenant, analyses[r])]
    accepted = [r for r in analysed if any(s.review.value == "accepted" for s in analyses[r].suggestions)]
    pending = sum(1 for r in analysed for s in analyses[r].suggestions if s.review.value == "needs_review")
    cases = [c for c in bridge.list_cases(db, tenant) if c["requirement_id"] in chosen]
    runnable = [c["id"] for c in cases if c["status"] in ("approved", "ready")]
    ex = bridge.get_execution(db, tenant, draft.get("execution_id") or "") if draft.get("execution_id") else None
    done = {"connect": connection_ready, "import": bool(keys), "explorer": bool(chosen),
            "analysis": bool(chosen) and len(analysed) == len(chosen), "reviews": bool(accepted) and not pending,
            "builder": bool(set(draft.get("test_case_ids") or []) & set(runnable)),
            "execution": bool(ex), "agents": bool(ex) and ex["status"] not in ("running", "queued"),
            "reports": bool(ex) and ex["status"] not in ("running", "queued")}
    return {"done": done, "imported": len(keys), "selected": chosen, "analysed": analysed,
            "has_analysis": [r for r in chosen if r in analyses], "with_accepted": accepted,
            "pending_reviews": pending, "test_cases": [c["id"] for c in cases], "runnable": runnable,
            "execution": {"id": ex["id"], "status": ex["status"]} if ex else None}


# ---------------------------------------------------------------- targets
def _target_ok(url: str) -> bool:
    p = urlparse(url)
    return p.scheme in ("http", "https") and bool(p.hostname) and not p.username and not p.password


def save_target(db, tenant: str, project_key: str, url: str, *, environment: str = "test", actor: str,
                app_type: str = "web", username: str = "", password: str = "") -> dict:
    ensure(db)
    project_key = (project_key or "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,19}", project_key):
        raise ValueError("not a Jira project key")
    url = (url or "").strip()
    if not _target_ok(url):
        raise ValueError("give a full http(s) website address, without a user name or password in it")
    old = get_target(db, tenant, project_key, environment, with_secret=True) or {}
    data = {"project_key": project_key, "environment": environment, "url": url, "app_type": app_type,
            "authorized_by": actor, "authorized_at": _now()}
    slot = f"{project_key}:{environment}"
    if username and password:  # (the account itself goes to the owner-only credentials file, never to this db)
        credentials.set_account(tenant, slot, username, password)
        data["account"] = {"stored": "credentials file", "saved_at": _now()}
    elif old.get("account") and old.get("url") == url:
        data["account"] = old["account"]  # (same website: its saved test account stays)
    elif old.get("account"):
        credentials.delete_account(tenant, slot)  # (another website never inherits this account)
    with db:
        db.execute("INSERT OR REPLACE INTO req_targets (tenant_id, project_key, environment, updated_at, data) "
                   "VALUES (?, ?, ?, ?, ?)", (tenant, project_key, environment, _now(), json.dumps(data)))
    return public_target(data)


def get_target(db, tenant: str, project_key: str, environment: str = "test", with_secret: bool = False):
    ensure(db)
    r = db.execute("SELECT data FROM req_targets WHERE tenant_id = ? AND project_key = ? AND environment = ?",
                   (tenant, project_key, environment)).fetchone()
    if not r:
        return None
    d = json.loads(r["data"])
    return d if with_secret else public_target(d)


def public_target(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "account"} | {"has_test_account": bool(d.get("account"))}


def forget_account(db, tenant: str, project_key: str, environment: str = "test") -> None:
    d = get_target(db, tenant, project_key, environment, with_secret=True)
    if d and d.pop("account", None):
        credentials.delete_account(tenant, f"{project_key}:{environment}")
        with db:
            db.execute("UPDATE req_targets SET data = ? WHERE tenant_id = ? AND project_key = ? AND environment = ?",
                       (json.dumps(d), tenant, project_key, environment))


def test_account(db, tenant: str, project_key: str, environment: str, url: str) -> tuple[str, str]:
    """The saved test account of this project's target - only for that same website address."""
    d = get_target(db, tenant, project_key, environment, with_secret=True)
    if not d or not d.get("account") or d.get("url") != url:
        return "", ""
    return credentials.get_account(tenant, f"{project_key}:{environment}")


def urls_in_text(text: str, exclude_hosts: set[str]) -> list[str]:
    out = []
    for raw in URL.findall(text or ""):
        url = raw.rstrip(".,;:!?\\")
        p = urlparse(url)
        host = (p.hostname or "").lower()
        if not host or host in exclude_hosts or NOT_TARGETS.search(host) or NOT_TARGET_PATH.search(p.path or ""):
            continue
        base = f"{p.scheme}://{p.netloc}/"
        if base not in out:
            out.append(base)
    return out[:10]


# --- what kind of application a value names (the engine that tests it)
API_PATH = re.compile(r"/(api|rest|graphql|v\d+)(/|$)|openapi|swagger|\.(json|ya?ml)$", re.I)
REPO_HOST = re.compile(r"(^|\.)(github\.com|gitlab\.com|bitbucket\.org)$", re.I)
PACKAGE = re.compile(r"\b((?:com|org|net|io|app|dev|co|in|uk|de|fr|br|me|ai)\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)\b")
PACKAGE_WORDS = re.compile(r"\b(package|app ?id|application ?id|android|apk|play store)\b", re.I)
BUNDLE_WORDS = re.compile(r"\b(bundle(?: ?id)?|ios|iphone|ipad|app store|xcode)\b", re.I)
ENGINE = {"web": "Playwright (browser)", "api": "REST API tests", "openapi": "REST API tests (OpenAPI)",
          "android_apk": "Appium (Android, install the APK)", "android_package": "Appium (Android, installed app)",
          "ios_bundle": "Appium XCUITest (iOS)", "repository": "Qpilot project run (build and test the repository)"}


def targets_in_text(text: str, exclude_hosts: set[str], explicit: bool = False) -> list[dict]:
    """Application candidates in a text: [{value, kind}]. explicit=True: the text is an application field (an
    'Environment' / 'App package' custom field), so repositories and bare package ids count too."""
    out: list[dict] = []

    def add(value: str, kind: str):
        if value and all(c["value"] != value for c in out):
            out.append({"value": value, "kind": kind})
    for raw in URL.findall(text or ""):
        url = raw.rstrip(".,;:!?\\")
        p = urlparse(url)
        host = (p.hostname or "").lower()
        if not host or host in exclude_hosts or p.username or p.password:
            continue
        if REPO_HOST.search(host):
            if explicit and len([x for x in (p.path or "").split("/") if x]) >= 2:
                add(f"https://{host}/" + "/".join([x for x in p.path.split("/") if x][:2]), "repository")
            continue
        if (p.path or "").lower().endswith(".apk"):
            add(url, "android_apk")
            continue
        if NOT_TARGETS.search(host) or NOT_TARGET_PATH.search(p.path or ""):
            continue
        if re.search(r"openapi|swagger", url, re.I) or (p.path or "").lower().endswith((".json", ".yaml", ".yml")):
            add(url, "openapi")
        elif API_PATH.search(p.path or ""):
            add(url, "api")
        else:
            add(f"{p.scheme}://{p.netloc}/", "web")
    plain = URL.sub(" ", text or "")
    for line in plain.splitlines():
        for m in PACKAGE.finditer(line):
            before = line[max(0, m.start() - 40):m.start()]  # (the words right before the id say what it is)
            if BUNDLE_WORDS.search(before):
                add(m.group(1), "ios_bundle")
            elif PACKAGE_WORDS.search(before) or explicit:
                add(m.group(1), "android_package")
    return out[:15]


def resolve(db, tenant: str, requirement_ids: list[str], environment: str = "test") -> dict:
    """Candidates for the application under test of these requirements, each with where it came from."""
    from . import bridge, store
    projects = sorted({r.split("-")[0] for r in requirement_ids if re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", r)})
    found: dict[str, dict] = {}

    def add(url: str, source: str, authorized: bool, project: str = "", kind: str = "web"):
        c = found.setdefault(url, {"url": url, "sources": [], "authorized": False, "has_test_account": False,
                                   "project_key": project, "kind": kind, "engine": ENGINE.get(kind, kind)})
        c["sources"].append(source)
        c["authorized"] = c["authorized"] or authorized
        if project and not c["project_key"]:
            c["project_key"] = project
    for p in projects:
        t = get_target(db, tenant, p, environment)
        if t:
            add(t["url"], f"saved target of Jira project {p} ({environment})", True, p)
            found[t["url"]]["has_test_account"] = t["has_test_account"]
    wanted = set(requirement_ids)
    for ex in bridge.list_executions(db, tenant, limit=100):
        reqs = {c.split("-", 1)[1].rsplit("-", 1)[0] for c in ex.get("case_ids", []) if c.startswith("TC-")}
        url = (ex.get("target") or {}).get("url", "")
        if url and reqs & wanted and _target_ok(url) and url not in found:
            add(url, f"used by execution {ex['id']} ({', '.join(sorted(reqs & wanted))})", True,
                sorted(reqs & wanted)[0].split("-")[0])
    sites = {h for h in (urlparse(c.site_url).hostname for c in store.list_connections(db, tenant)) if h}
    for r in store.list_sources(db, tenant):
        src = r["source"]
        content = r["content"] if isinstance(r["content"], dict) else {}
        if src.kind.value == "jira_issue":
            if src.source_id not in wanted:
                continue
            for name, value in (content.get("app_fields") or {}).items():  # (an application field: explicit)
                for t in targets_in_text(str(value), sites, explicit=True):
                    add(t["value"], f"Jira field '{name}' of {src.source_id} (not yet confirmed)", False,
                        src.source_id.split("-")[0], t["kind"])
            text = "\n".join(str(content.get(k) or "") for k in ("summary", "description", "acceptance_criteria"))
            where = f"written in {src.source_id}"
        else:  # a Confluence page that names one of these requirements (a linked specification)
            text = json.dumps(content, default=str)
            names = [w for w in wanted if re.search(rf"\b{re.escape(w)}\b", text)]
            if f"conf-{src.source_id}" in wanted:
                names.append(f"conf-{src.source_id}")
            if not names:
                continue
            where = f"Confluence page '{src.title[:60]}' ({', '.join(sorted(names)[:3])})"
        for t in targets_in_text(text, sites):
            if t["value"] not in found:
                add(t["value"], f"{where} (not yet confirmed)", False, "", t["kind"])
    candidates = sorted(found.values(), key=lambda c: (not c["authorized"], c["kind"] != "web"))
    authorized = [c for c in candidates if c["authorized"]]
    status = ("found" if len(authorized) == 1 else "multiple" if len(authorized) > 1 or candidates
              else "not_found")
    return {"status": status, "candidates": candidates, "projects": projects,
            "message": {"found": "Target website found.",
                        "multiple": "Several possible websites were found: choose the one to test.",
                        "not_found": "Target website not found. Please enter the website URL you want to test."}[status]}
