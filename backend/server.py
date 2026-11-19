"""Backend web server: the bridge between the frontend (web page) and the testing engine.

Start:  double-click ui.bat     (or:  python -m backend.server)
Open:   http://127.0.0.1:8000   (opens automatically)

It serves the page from  frontend/,  starts `main.py` in the background when you press Test,
streams its progress to the page, and serves the report, fixes and Excel test cases (JSON API).
"""
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urljoin, urlparse

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.config import _load_dotenv  # noqa: E402  (.env keys -> os.environ, so the UI knows which keys exist)
from backend.safety import UrlError, check_target, is_private_host, redact  # noqa: E402

_load_dotenv(ROOT / ".env")
RUNS = ROOT / "runs"
STATIC = ROOT / "frontend"   # the web page files (served at /static/...)
AUDIT = ROOT / "logs" / "audit.jsonl"  # who started / stopped / deleted what, and when (never secrets)
RUNS.mkdir(exist_ok=True)
STAGE_RE = re.compile(r"^::stage::(\w+)::(start|done)$")
NOTE_RE = re.compile(r"^::note::(.+)$")
PAGE_RE = re.compile(r"^::page::(\{.*\})$")  # one inspected page (live page cards in the chat)
HUMAN_RE = re.compile(r"^::human::(\{.*\})$")  # the login needs a person (one-time code / CAPTCHA) - and the outcome
RUN_NAME = re.compile(r"^[\w.\-]+$")
# Run reads that carry another tenant's findings. Job ids are checked on the job, not as a folder name.
_SCOPED_RUN = re.compile(
    r"^/api/(?:report|coverage|pages|components)/([^/]+)"
    r"|^/api/(?:cases|excel)/([^/]+)"
    r"|^/api/android/runs/([^/]+)/"
    r"|^/api/runs/([^/]+)/(?:repo-fix|recheck)"
    r"|^/api/visual/([^/]+)/"
    r"|^/runs/([^/]+)/"
)
IS_WINDOWS = os.name == "nt"
# the UI only answers to these host names: a web page on another site can't reach it through DNS tricks
UI_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


# Sensitive run artifacts: never served as public static files even if copied outside .private/
_PRIVATE_RUN_FILES = frozenset({
    "auth.json",
    "contract_inputs.json",
    "android_config.json",
    "app.apk",
    "active_appium_session.json",
})


class RunFiles(StaticFiles):
    """runs/ as files for the report pages - except private inputs, APKs, auth and hidden files."""

    async def get_response(self, path: str, scope):
        parts = Path(path).parts
        if any(p.startswith(".") for p in parts) or (parts and parts[-1].lower() in _PRIVATE_RUN_FILES):
            raise HTTPException(404, "not found")
        return await super().get_response(path, scope)


app = FastAPI(title="Qpilot")
app.mount("/runs", RunFiles(directory=RUNS), name="runs")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
DASHBOARD_DIST = STATIC / "dashboard" / "dist"


@app.get("/dashboard")
@app.get("/dashboard/")
def dashboard_home():
    """Gate I React/TS dashboard. Serves the Vite build when present."""
    index = DASHBOARD_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse(
        "<!doctype html><title>Qpilot Enterprise</title>"
        "<body style='font-family:system-ui;padding:2rem'>"
        "<h1>Qpilot Enterprise</h1>"
        "<p>React/TypeScript dashboard source is at <code>frontend/dashboard</code>.</p>"
        "<p>Build it with <code>npm install && npm run build</code>, then restart the UI.</p>"
        "<p>Gate I remains incomplete until auth, approvals, and hosting are proven.</p>"
        "<p><a href='/'>Back to Studio</a></p>",
        status_code=200,
    )


if (DASHBOARD_DIST / "assets").is_dir():
    app.mount("/dashboard/assets", StaticFiles(directory=DASHBOARD_DIST / "assets"), name="dashboard-assets")

jobs: dict[int, dict] = {}
lock = threading.Lock()
from backend.privacy import (  # noqa: E402 - workspace and application state are initialized above
    PrivacyError,
    apply_worker_policy,
    load_policy,
    local_ai_request,
    public_policy,
    select_provider,
)
from backend.privacy_api import MCPPresence, register_privacy_api  # noqa: E402

mcp_presence = MCPPresence()


def key_provider(key: str) -> str | None:
    """The cloud provider an API key belongs to, from its well-known prefix (None when it cannot be told)."""
    if key.startswith("sk-ant-"):
        return "anthropic"
    if key.startswith("AIza"):
        return "gemini"
    if key.startswith("sk-"):
        return "openai"
    return None


def _privacy_provider(requested, expected_mode=None):
    try:
        return select_provider(requested, os.environ.get("LLM_PROVIDER", "ollama"),
                               os.environ.get("OLLAMA_URL", "http://localhost:11434"), expected_mode)
    except PrivacyError as error:
        raise HTTPException(403, str(error)) from error


def _worker_privacy(env, provider=None, expected_mode=None):
    try:
        return apply_worker_policy(env, provider, expected_mode)
    except PrivacyError as error:
        raise HTTPException(403, str(error)) from error


@app.middleware("http")
async def local_only(request: Request, call_next):
    """Only answer on 127.0.0.1 / localhost, and every change (POST / DELETE) needs the X-Agentic-QA header -
    browsers can't send that header from another website, so other sites can't start, stop or delete tests."""
    from backend.api_versioning import resolve_path
    # Canonical clients use /api/v1/...; rewrite to legacy /api/... so handlers stay single-sourced.
    resolved = resolve_path(request.url.path)
    if resolved.get("ok") and not resolved.get("legacy") and resolved.get("version") == 1:
        request.scope["path"] = "/api" + (resolved.get("resource") or "/")
    elif resolved.get("version") is not None and not resolved.get("ok"):
        return JSONResponse({"detail": resolved.get("reason") or "unsupported API version"}, status_code=404)
    path = request.url.path
    mcp_request = request.headers.get("x-qpilot-client", request.headers.get("x-blowai-client")) == "mcp"
    if mcp_request:
        control = path in {"/api/mcp/info", "/api/mcp/heartbeat"}
        if path.startswith("/api/settings/"):
            return JSONResponse({"detail": "Change privacy settings in the Qpilot UI."}, status_code=403)
        if not control and not load_policy().allow_mcp:
            return JSONResponse({"detail": "MCP data access is disabled. Approve your assistant in Privacy settings."},
                                status_code=403)
    host = request.headers.get("host", "")
    host = host[:host.index("]") + 1] if host.startswith("[") and "]" in host else host.split(":")[0]
    if host.lower() not in UI_HOSTS:
        return JSONResponse({"detail": "The Qpilot UI only answers on 127.0.0.1 / localhost."}, status_code=400)
    blocked = _principal_run_block(
        path, request.headers.get("authorization"), request.headers.get("x-qa-token"), request.method)
    if blocked is not None:
        return blocked
    # (a webhook proves itself with its own token instead - /api/hooks/run)
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.headers.get("x-agentic-qa") != "1" \
            and path != "/api/hooks/run":
        return JSONResponse({"detail": "forbidden (missing X-Agentic-QA header)"}, status_code=403)
    if path == "/api/mobile/runs" and request.method == "POST":
        length = request.headers.get("content-length")
        if length is None:
            return JSONResponse({"detail": "Provide Content-Length for a bounded APK upload."}, status_code=411)
        try:
            size = int(length)
        except ValueError:
            return JSONResponse({"detail": "Invalid upload Content-Length."}, status_code=400)
        if size < 0 or size > 501 * 1024 * 1024:
            return JSONResponse({"detail": "APK request exceeds the 500 MB upload limit."}, status_code=413)
    response = await call_next(request)
    # Studio JS/CSS must never stick on an old build after git pull (Windows browsers are aggressive).
    if request.url.path.startswith("/static/") and request.url.path.rsplit(".", 1)[-1].lower() in {
        "js", "css", "html",
    }:
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


def _audit(action: str, **details) -> None:
    """Consequential actions -> logs/audit.jsonl + Gate G SQLite audit_events (no secrets)."""
    try:
        AUDIT.parent.mkdir(exist_ok=True)
        with AUDIT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action, **details}) + "\n")
    except OSError:
        pass
    try:
        from backend.audit_store import record_audit
        safe = {k: v for k, v in details.items()
                if k not in {"password", "api_key", "token", "secret", "test_password", "test_totp_secret"}}
        detail = ", ".join(f"{k}={v}" for k, v in list(safe.items())[:12])[:500]
        record_audit(
            actor=str(details.get("actor") or "studio"),
            action=action,
            allowed=True,
            tenant_id=str(details.get("tenant_id") or ""),
            detail=detail,
        )
    except Exception:
        pass


class RunRequest(BaseModel):
    workflow: Literal["standard", "mcp"] = "standard"
    privacy_mode: Literal["local", "cloud"] | None = None
    discovery_only: bool = False
    website_only: bool = False       # MCP accepts URLs, never cloned repositories or local projects
    source: str                      # website URL, GitHub link or local folder
    max_pages: int = 0               # 0 = full same-site crawl, bounded by HARD_PAGE_CAP
    show_browser: bool = False
    execution_mode: Literal["watch", "fast"] | None = None
    action_delay_ms: int = Field(default=1000, ge=0, le=3000)
    fresh: bool = False
    llm_provider: str | None = None  # ollama | gemini | openai | anthropic | none   (None = use .env)
    llm_model: str | None = None
    api_key: str | None = None       # only passed to this run's process, never written to disk
    auth_mode: Literal["auto", "public", "existing", "signup", "configured"] = "auto"
    allow_rules_fallback: bool = True  # legacy callers retain fallback; guided setup asks explicitly
    max_interactions_per_page: int | None = None
    explore_repeated_controls: bool = False
    thorough: bool = False  # raise this-run crawl/test budgets (Studio Thorough / MCP parity)
    test_username: str | None = None  # test account for websites with a login (this run only, never saved)
    test_password: str | None = None
    test_totp_secret: str | None = None  # the test account's authenticator key (2-step login; this run only, never saved)
    authorized: bool = False         # "I own this website or have permission to test it" - required
    allow_signup: bool = False       # may the tester create a test account on the website's sign-up page?
    environment: str = "test"        # test | staging | production
    production_confirmed: bool = False  # production: an extra confirmation
    # staging: forms are sent, records created -> edited -> deleted (tagged, cleaned up). On a host that does not look
    # like a test copy, only with this second confirmation (it is written to the audit log)
    writes_confirmed: bool = False
    allow_actions: str | None = None  # staging only: also delete, logout, password, pay (comma-separated)
    test_payment: bool = False       # staging + allow pay: the payment provider is in its test mode
    reuse_tests: bool = False        # run the tests of the last run again (regression) instead of writing new ones
    reuse_from_run: str | None = None  # prefer that run's generated_tests + test_cases.json
    record_video: bool = False       # save a video of the test browsers (runs/<run>/videos)
    # optional - only when the tester can't work it out by itself
    max_depth: int = 0
    crawl_scope: str = "auto"
    page_timeout_s: int = 0
    login_url: str | None = None
    login_user_selector: str | None = None
    login_password_selector: str | None = None
    login_submit_selector: str | None = None
    login_success_text: str | None = None
    allowed_hosts: str | None = None  # comma-separated
    exclude_paths: str | None = None  # comma-separated
    requirements: str | None = None   # business workflows / expected results / roles, in plain words
    my_tests: str | None = None       # your own tests in plain English, one per line (None = keep the saved ones)
    qa_contract: dict | None = None  # explicit expected behavior; secret references only
    contract_only: bool = False      # run only the approved contract flows; no built-in site suite
    review: bool = False              # review the test cases before the scripts are written (untick, add tests)


PROVIDERS = [  # shown in the UI, in this order; Ollama first = the secure default
    {"id": "ollama", "name": "Ollama (local)", "badge": "Secure · Free",
     "info": "Runs on your machine. No page data leaves your computer. Best when security matters.",
     "key_env": None, "models": ["llama3.1", "qwen2.5-coder", "llama3.2", "mistral"]},
    {"id": "gemini", "name": "Google Gemini", "badge": "Free tier",
     "info": "Cloud AI with a free tier (get a key at aistudio.google.com). Page data is sent to Google.",
     "key_env": "GEMINI_API_KEY", "models": ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]},
    {"id": "openai", "name": "OpenAI GPT", "badge": "Paid",
     "info": "Cloud AI, billed per token. Page data is sent to OpenAI.",
     "key_env": "OPENAI_API_KEY", "models": ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o", "gpt-5-mini"]},
    {"id": "anthropic", "name": "Anthropic Claude", "badge": "Paid",
     "info": "Cloud AI, billed per token. Page data is sent to Anthropic.",
     "key_env": "ANTHROPIC_API_KEY", "models": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"]},
    {"id": "none", "name": "No AI (rules)", "badge": "Free · Offline",
     "info": "Built-in rule-based test design and script templates. No AI at all.",
     "key_env": None, "models": []},
]
KEY_ENV = {p["id"]: p["key_env"] for p in PROVIDERS}


# ------------------------------------------------------------------ helpers

def _signed_in_reader(authorization: str | None, x_qa_token: str | None, action: str = "run.read"):
    """None when the studio is open. Otherwise the principal id, or a JSON refusal."""
    from backend.dashboard_auth import auth_mode, authorize
    if auth_mode() not in ("principal", "oidc"):
        return None
    verdict = authorize(authorization, x_qa_token=x_qa_token, action=action)
    if not verdict.get("ok"):
        reason = verdict.get("reason") or "unauthorized"
        return JSONResponse({"detail": reason}, status_code=403 if verdict.get("role") else 401)
    principal = str(verdict.get("principal_id") or "").strip()
    if not principal:
        return JSONResponse({"detail": "principal required"}, status_code=401)
    return principal


def _principal_run_block(path: str, authorization: str | None, x_qa_token: str | None, method: str = "GET"):
    """When a principal is signed in, a run read or delete stays inside that principal's tenant."""
    match = _SCOPED_RUN.search(path or "")
    run = next((part for part in match.groups() if part), "") if match else ""
    if not run and method == "DELETE":
        deleted = re.fullmatch(r"/api/runs/([^/]+)", path or "")
        run = deleted.group(1) if deleted else ""
    if not run:
        return None
    reader = _signed_in_reader(
        authorization, x_qa_token, "run.read" if method in ("GET", "HEAD") else "run.write")
    if reader is None or not isinstance(reader, str):
        return reader
    from backend.tenancy_store import assert_run_access
    access = assert_run_access(principal_id=reader, run_id=run)
    if not access.get("allowed"):
        return JSONResponse({"detail": access.get("reason") or "forbidden"}, status_code=403)
    return None


def _run_dir(run: str) -> Path:
    """runs/<run>, refusing anything that is not a plain folder name."""
    if not RUN_NAME.fullmatch(run or "") or run.startswith("."):
        raise HTTPException(400, "bad run name")
    d = RUNS / run
    if d.resolve().parent != RUNS.resolve():
        raise HTTPException(400, "Run directory must stay inside runs.")
    if not d.is_dir():
        raise HTTPException(404, "run not found")
    return d


def _job_or_404(job_id: int) -> dict:
    """In-memory job by id, or a consistent 404 for missing / unknown job ids."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


def _refuse_job(job: dict, reader, action: str = "run.read"):
    """None when this caller may use the live test. Open mode always may."""
    if reader is None:
        return None
    if not isinstance(reader, str):
        return reader
    if str(job.get("principal_id") or "") == reader:
        return None
    run = str(job.get("run") or "")
    if run:
        from backend.tenancy_store import assert_run_access
        access = assert_run_access(principal_id=reader, run_id=run, audit=action != "run.read")
        if access.get("allowed"):
            return None
    return JSONResponse({"detail": "tenant isolation"}, status_code=403)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _excel_file(d: Path) -> Path | None:
    files = [f for f in (d / "test_cases.xlsx", d / "test_cases_results.xlsx") if f.exists()]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def _reader(job: dict) -> None:
    """Read main.py's output line by line: stage events update the pipeline, the rest is the live log."""
    proc = job["proc"]
    for raw in proc.stdout:
        line = redact(raw.rstrip("\r\n"), job.get("secrets") or [])  # (passwords / keys never reach the page)
        m = NOTE_RE.match(line.strip())
        if m:
            job["note"] = m.group(1).strip()
            job["lines"].append(job["note"])
            continue
        m = STAGE_RE.match(line.strip())
        if m:
            name, ev = m.groups()
            stack = job.setdefault("_stage_stack", [])
            if ev == "start":
                if name in stack:
                    stack.remove(name)
                stack.append(name)
                job["stages"][name] = "running"
            else:
                job["stages"][name] = "done"
                if name in stack:
                    stack.remove(name)
            job["current"] = stack[-1] if stack else None
            continue
        m = PAGE_RE.match(line.strip())
        if m:
            try:
                job["pages"].append(json.loads(m.group(1)))
            except ValueError:
                pass
            continue
        m = HUMAN_RE.match(line.strip())
        if m:  # the chat asks the person to complete the code / CAPTCHA in the Chrome window (and then thanks them)
            try:
                job["human"] = json.loads(m.group(1))
            except ValueError:
                pass
            continue
        if line.startswith("Output:") and not job.get("run"):
            job["run"] = Path(line.split(":", 1)[1].strip()).name
        job["lines"].append(line)
    proc.wait()
    job["exit_code"] = proc.returncode
    job["status"] = "stopped" if job.get("stopping") else ("done" if proc.returncode == 0 else "failed")
    job["current"] = None
    job["ended"] = time.time()
    if job.get("run") and (RUNS / job["run"]).is_dir():  # keep the console output with the run
        (RUNS / job["run"] / "console.log").write_text("\n".join(job["lines"]), encoding="utf-8")


def _live_cost(d: Path | None) -> dict:
    """Cost so far, from the LLM calls logged while the run is going."""
    calls = []
    if d and (d / "llm_usage.jsonl").exists():
        for line in (d / "llm_usage.jsonl").read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                calls.append(json.loads(line))
            except ValueError:
                pass
    return {"calls": len(calls), "tokens": sum(c["tokens_in"] + c["tokens_out"] for c in calls),
            "cost_usd": round(sum(c["cost_usd"] for c in calls), 6)}


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass  # line still being written
    return out


def _live_results(d: Path) -> list[Path]:
    """The result files a running test writes: results.jsonl, one per parallel worker (results.gw0.jsonl ...),
    and the small checks that run hidden while you watch the big tests in Chrome (results_bg*.jsonl)."""
    return [d / "results.jsonl", d / "android_results.jsonl"] + sorted(d.glob("results.gw*.jsonl")) + sorted(d.glob("results_bg*.jsonl"))


def _case_progress(d: Path, executing: bool) -> dict:
    """Live status of every Excel test case: Pending -> Automated -> Running -> Passed / Failed / ...

    Results come from results.jsonl, which pytest's conftest appends to after EACH test, so the
    UI can follow the execution test by test. Tests run in a fixed order (large end-to-end cases first,
    link checks last - excel.RUN_ORDER), so the first case that has not run all its checks yet is the
    one running right now.
    """
    from backend.excel import _case_files, _short_error, automation_status, case_hits, case_result, file_rank

    cases = _read_json(d / "test_cases.json", [])
    if cases and all(str(c.get("id", "")).startswith("android_") for c in cases):
        from backend.android_design import normalize_case
        cases = [normalize_case(c) for c in cases]
    final = (d / "results.json").exists() and not executing
    if final:
        results = _read_json(d / "results.json", [])
    else:  # live: the main file + one file per parallel worker (results.gw0.jsonl, ...) + the hidden small checks
        results = [r for f in _live_results(d) for r in _read_jsonl(f)]
    test_dir = d / "generated_tests"
    scripts_ready = test_dir.is_dir() and any(test_dir.glob("test_*.py"))

    rows, unfinished = [], []
    for n, c in enumerate(cases, start=1):
        auto, how = automation_status(c, test_dir) if scripts_ready else ("Pending", "")
        status, detail = case_result(c, results) if results or c.get("blocked") else ("Pending", "")
        if status in ("Not run", "Pending"):
            status, detail = ("Not automated", c.get("automation_note") or "No automated script for this case.") \
                if auto == "Not automated" \
                else ("Not run" if final else "Pending", "")
        done_checks = len(case_hits(c, results)) if results else 0
        if executing and auto == "Automated" and done_checks < (c.get("check_count") or 1):
            unfinished.append((min((file_rank(f) for f in _case_files(c)), default=2), n - 1, done_checks))
        rows.append({"n": n, "page": c.get("page", ""), "url": c.get("url", ""), "id": c.get("id", ""),
                     "tc_id": c.get("tc_id", ""), "risk": c.get("risk", ""), "feature": c.get("feature", ""),
                     "title": c.get("title", ""), "type": c.get("type", ""), "priority": c.get("priority", ""),
                     "size": c.get("size", ""), "steps": len(c.get("steps") or []),
                     "test_data": c.get("test_data") or "",
                     "automation": auto, "automated_by": how, "status": status, "detail": detail})
    links = [r for r in results if r.get("file") == "test_all_links.py"]
    links_total = 0
    if (test_dir / "test_all_links.py").exists():
        links_total = len(re.findall(r"'id': ", (test_dir / "test_all_links.py").read_text(encoding="utf-8", errors="replace")))
    for n, c in enumerate(cases):  # the steps each finished test did, in order (the failing one marked)
        hit = [r for r in case_hits(c, results) if r.get("live_steps")] if results else []
        if hit:
            last = next((r for r in hit if r.get("outcome") in ("failed", "error")), hit[-1])
            rows[n]["steps_done"] = last["live_steps"][-30:]
            rows[n]["steps_test"] = last.get("test", "")
    marked = False  # the tests the browsers run right now (the conftest writes them) - with how long they have run
    for now in (_read_json(f, {}) for f in sorted(d.glob("running.*.json"))) if executing else []:
        i = next((i for i, c in enumerate(cases) if now.get("test") and case_hits(c, [now])), None)
        if i is not None:
            secs, limit = int(time.time() - now.get("since", time.time())), int(now.get("limit_s") or 0)
            rows[i]["status"], marked = "Running", True
            rows[i]["detail"] = f"running for {secs // 60}:{secs % 60:02d}" + (
                f" - stops at {limit // 60}:{limit % 60:02d} at the latest" if limit else "")
            rows[i]["steps_live"] = (now.get("steps") or [])[-12:]  # (the steps so far: the chat ticks them)
            rows[i]["steps_test"] = now.get("test", "")
    if unfinished and not marked:  # (older runs) the first case in run order with checks to do is running now
        _, i, k = min(unfinished)
        rows[i]["status"] = "Running"
        checks = cases[i].get("check_count") or 1
        rows[i]["detail"] = f"{k} of {checks} checks done" if checks > 1 else ""
    done = sum(r["status"] in ("Passed", "Failed", "Flaky", "Skipped", "Inconclusive", "Blocked") for r in rows)
    return {
        "cases": rows,
        "done": done, "total": len(rows),
        "passed": sum(r["status"] == "Passed" for r in rows),
        "failed": sum(r["status"] in ("Failed", "Flaky") for r in rows),
        "inconclusive": sum(r["status"] == "Inconclusive" for r in rows),
        "links": {"total": links_total, "done": len(links),
                  "broken": sum(r["outcome"] in ("failed", "error") for r in links),
                  "last_error": _short_error(next((r.get("error") for r in reversed(links)
                                                   if r["outcome"] in ("failed", "error")), None))},
        "tests_run": len(results),
    }


def _count(path: Path) -> int | None:
    data = _read_json(path, None) if path.exists() else None
    return len(data) if isinstance(data, list) else None


def _public(job: dict, since: int = 0, psince: int = 0) -> dict:
    run = job.get("run")
    d = RUNS / run if run else None
    excel = _excel_file(d) if d and d.is_dir() else None
    return {
        "target_type": job.get("target_type", "web"),
        "workflow": job.get("workflow", "standard"), "privacy_mode": job.get("privacy_mode", "local"),
        "discovery_only": bool(job.get("discovery_only")),
        "thorough": bool(job.get("thorough")),
        "llm": job.get("llm"),
        "cost": _live_cost(d),
        "pages": _count(d / "app_map.json") if d else None,
        "cases": _count(d / "test_cases.json") if d else None,
        "scripts": len(list((d / "generated_tests").glob("test_*.py"))) if d and (d / "generated_tests").is_dir() else None,
        "id": job["id"], "source": job["source"], "status": job["status"], "run": run,
        # exit_code is set when the worker process ends (None while still running)
        "exit_code": job.get("exit_code"),
        "stages": job["stages"], "current": job["current"], "human": job.get("human"),
        "note": job.get("note") or "",
        "lines": job["lines"][since:], "next": len(job["lines"]),
        "live_pages": job.get("pages", [])[psince:], "pnext": len(job.get("pages", [])),
        "excel": f"/runs/{run}/{excel.name}" if excel else None,
        "report_ready": bool(d and (d / "summary.json").exists()),
        # the run asks you something (backend/review.py) and waits for the answers
        "review": bool(d and (d / "review_request.json").exists() and not (d / "review_answers.json").exists()
                       and job["status"] == "running"),
        "elapsed": int((job.get("ended") or time.time()) - job["started"]),
    }


# ------------------------------------------------------------------ API

def _ui_asset_digests() -> dict[str, str]:
    names = ("chat.js", "workflow.js", "contract-builder.js", "chat.css", "studio.css", "qpilot.css",
             "execution.js", "repository.js", "workspace.js", "android-workspace.js", "android-scenarios.js", "mcp-settings.js")
    return {name: hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:12] for name in names}


@app.get("/api/ui-build")
def ui_build():
    """Fingerprint of Studio frontend files — use to confirm git pull + ui.bat restart picked up changes."""
    digests = _ui_asset_digests()
    return {"ok": True, "build": digests.get("chat.js", ""), "assets": digests}


@app.get("/")
def home():
    """Chat page: type a URL, pick the AI, follow the to-do list as each step gets its tick."""
    html = (STATIC / "chat.html").read_text(encoding="utf-8")
    digests = _ui_asset_digests()
    for name, digest in digests.items():
        html = html.replace("/static/" + name, "/static/" + name + "?v=" + digest)
    # Visible stamp so operators can confirm they are not on a stale Windows copy.
    stamp = digests.get("chat.js", "")[:8]
    html = html.replace(
        "<!--UI_BUILD-->",
        f'<br><span class="ui-build" title="Frontend fingerprint — must change after git pull + ui.bat restart">'
        f'build {stamp}</span>',
        1,
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"})


@app.get("/api/enterprise/readiness")
def enterprise_readiness():
    """Gate G/I readiness probe. Never claims complete when backends are only configured."""
    from backend.enterprise import readiness
    from backend.ops_readiness import readiness as ops_readiness
    snap = readiness()
    snap["ops"] = ops_readiness()
    return snap


@app.post("/api/sso/validate-bearer")
def sso_validate_bearer(authorization: str | None = Header(default=None)):
    """Gate I: structural OIDC JWT claim check. Never completes Gate I."""
    from backend.dashboard_sso import validate_authorization_header
    verdict = validate_authorization_header(authorization)
    _audit("sso_validate_bearer", ok=bool(verdict.get("ok")),
           verified=bool(verdict.get("signature_verified")))
    return verdict


@app.post("/api/sso/login")
def sso_login():
    """Gate I: start one Studio login. Hosted IdP SSO stays open."""
    from backend.studio_oidc_callback import issue_sso_login

    started = issue_sso_login()
    _audit("sso_login", ok=bool(started.get("ok")))
    return started


@app.get("/api/sso/callback")
def sso_callback(
    code: str = "",
    state: str = "",
    redirect_uri: str = "",
):
    """Gate I: Studio OIDC auth-code callback helper (hosted IdP still open).

    A caller-supplied ``redirect_uri`` is forwarded only when it is on
    ``QPILOT_OIDC_REDIRECT_ALLOWLIST``. When that list is unset, the query
    value is ignored and the configured callback URI is used.
    The PKCE verifier is the one stored when this login started. A verifier
    in the query string is not read.
    """
    from backend.studio_oidc_callback import (
        consume_sso_login,
        exchange_code,
        validate_redirect_uri,
    )

    forwarded = None
    if (redirect_uri or "").strip():
        check = validate_redirect_uri(redirect_uri)
        if not check.get("redirect_enforced"):
            redirect_uri = ""
        elif not check.get("ok"):
            _audit(
                "sso_callback",
                ok=False,
                redirect_ok=False,
                reason="redirect_uri not allowlisted",
            )
            return check
        else:
            forwarded = redirect_uri.strip()
    login = consume_sso_login(state)
    if not login.get("ok"):
        _audit(
            "sso_callback",
            ok=False,
            state_ok=False,
            reason=str(login.get("reason") or "")[:80],
        )
        return login
    verdict = exchange_code(
        code=code,
        state=state,
        nonce=str(login.get("nonce") or ""),
        code_verifier=str(login.get("code_verifier") or ""),
        **({"redirect_uri": forwarded} if forwarded else {}),
    )
    _audit(
        "sso_callback",
        ok=bool(verdict.get("ok")),
        verified=bool(verdict.get("signature_verified")),
        state=(state or "")[:40],
        state_ok=verdict.get("state_ok"),
        redirect_ok=verdict.get("redirect_ok"),
    )
    return verdict


@app.get("/api/blueprint/progress")
def blueprint_progress_api():
    """Studio sidebar todos: phases, gates A–J, and what is next. Never claims complete."""
    from backend.blueprint_progress import progress
    return progress()


@app.get("/api/device-matrix/status")
def device_matrix_status(include_android_dry_run: bool = False):
    """Gate D matrix scoreboard. Optional Android protocol dry-run never verifies profiles."""
    from backend.device_matrix import evaluate_matrix, protocol_dry_run_evidence
    evidence = []
    if include_android_dry_run:
        evidence.extend(protocol_dry_run_evidence())
    scored = evaluate_matrix(evidence)
    scored["gate_d_complete"] = False
    scored["android_dry_run_included"] = bool(include_android_dry_run)
    scored["reason"] = (
        "Android protocol dry-run rows ignored for verification; live emulator/API24+ still required"
        if include_android_dry_run else
        "No live evidence supplied; matrix incomplete"
    )
    return scored


@app.post("/api/ops/drills/android-adb-probe")
def ops_android_adb_probe():
    """Gate D: probe local ADB (does not verify emulator matrix)."""
    from backend.android_adb_probe import run_adb_probe
    evidence = run_adb_probe()
    _audit("ops_android_adb_probe", ok=bool(evidence.get("ok")),
           online=int(evidence.get("devices_online") or 0))
    return {"gate_d_complete": False, "adb_probe": evidence}


@app.post("/api/ops/drills/failure-matrix")
def ops_failure_matrix():
    """Gate E: controlled failure-classification matrix (still incomplete)."""
    from backend.failure_matrix import run_failure_matrix_drill
    evidence = run_failure_matrix_drill()
    _audit("ops_failure_matrix", cases=int(evidence.get("cases") or 0))
    return {"gate_e_complete": False, "failure_matrix": evidence}


@app.post("/api/ops/drills/healing-regression")
def ops_healing_regression():
    """Gate E: offline locator-only healing regression suite (still incomplete)."""
    from backend.healing_regression import run_healing_regression_drill
    evidence = run_healing_regression_drill()
    _audit("ops_healing_regression", cases=int(evidence.get("cases") or 0),
           mismatches=int(evidence.get("mismatches") or 0))
    return {"gate_e_complete": False, "healing_regression": evidence}


@app.post("/api/ops/drills/demo-store-healing-live")
def ops_demo_store_healing_live():
    """Gate E: live DemoStore missing-locator + healing policy drill (still incomplete)."""
    from backend.demo_store_healing_live_drill import run_demo_store_healing_live_drill
    evidence = run_demo_store_healing_live_drill()
    _audit(
        "ops_demo_store_healing_live",
        ok=bool(evidence.get("ok")),
        category=str((evidence.get("classification") or {}).get("category") or "")[:40],
    )
    return {"gate_e_complete": False, "demo_store_healing_live": evidence}


@app.post("/api/ops/drills/live-failure-matrix")
def ops_live_failure_matrix():
    """Gate E: live DemoStore provoked failure matrix + healing policy (still incomplete)."""
    from backend.live_failure_matrix_drill import run_live_failure_matrix_drill
    evidence = run_live_failure_matrix_drill()
    _audit(
        "ops_live_failure_matrix",
        ok=bool(evidence.get("ok")),
        failed=int(evidence.get("failed") or 0),
    )
    return {"gate_e_complete": False, "live_failure_matrix": evidence}


@app.post("/api/ops/drills/multi-app-healing-suite")
def ops_multi_app_healing_suite():
    """Gate E: multi-fixture live healing suite (production healing still open)."""
    from backend.multi_app_healing_suite_drill import run_multi_app_healing_suite_drill
    evidence = run_multi_app_healing_suite_drill()
    _audit(
        "ops_multi_app_healing_suite",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("passed") or 0),
        total=int(evidence.get("total") or 0),
    )
    return {"gate_e_complete": False, "multi_app_healing_suite": evidence}


@app.post("/api/ops/drills/production-healing-matrix")
def ops_production_healing_matrix():
    """Gate E: production-like multi-failure healing matrix (suite still open)."""
    from backend.production_healing_matrix_drill import run_production_healing_matrix_drill
    evidence = run_production_healing_matrix_drill()
    _audit(
        "ops_production_healing_matrix",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("passed") or 0),
        total=int(evidence.get("total") or 0),
    )
    return {"gate_e_complete": False, "production_healing_matrix": evidence}


@app.post("/api/ops/drills/api-version-contract")
def ops_api_version_contract():
    """Gate I: API versioning contract snapshot (SSO still open)."""
    from backend.api_version_drill import run_api_version_drill
    evidence = run_api_version_drill()
    _audit("ops_api_version_contract", ok=bool(evidence.get("ok")))
    return {"gate_i_complete": False, "api_version_contract": evidence}


@app.post("/api/ops/drills/lifecycle-cleanup")
def ops_lifecycle_cleanup():
    """Gate C: offline lifecycle + created.jsonl cleanup confirmation (still incomplete)."""
    from backend.lifecycle_cleanup_drill import run_lifecycle_cleanup_drill
    evidence = run_lifecycle_cleanup_drill()
    _audit("ops_lifecycle_cleanup", ok=bool(evidence.get("ok")),
           confirmed=int(evidence.get("confirmed") or 0))
    return {"gate_c_complete": False, "lifecycle_cleanup": evidence}


@app.post("/api/ops/drills/admin-portal-lifecycle")
def ops_admin_portal_lifecycle():
    """Gate C: AdminPortal create→remote_delete cleanup confirmation (still incomplete)."""
    from backend.admin_portal_lifecycle_drill import run_admin_portal_lifecycle_drill
    evidence = run_admin_portal_lifecycle_drill()
    _audit("ops_admin_portal_lifecycle", ok=bool(evidence.get("ok")),
           confirmed=int(evidence.get("confirmed") or 0),
           user_id=str(evidence.get("user_id") or ""))
    return {"gate_c_complete": False, "admin_portal_lifecycle": evidence}


@app.post("/api/ops/drills/oracle-spec")
def ops_oracle_spec():
    """Gate C: approved-spec oracle bind + AI needs_review (still incomplete)."""
    from backend.oracle_spec_drill import run_oracle_spec_drill
    evidence = run_oracle_spec_drill()
    _audit("ops_oracle_spec", ok=bool(evidence.get("ok")),
           features=int(evidence.get("features_bound") or 0))
    return {"gate_c_complete": False, "oracle_spec": evidence}


@app.post("/api/ops/drills/demo-store-cart-lifecycle")
def ops_demo_store_cart_lifecycle():
    """Gate C: DemoStore cart add→remove cleanup confirmation (still incomplete)."""
    from backend.demo_store_cart_lifecycle_drill import run_demo_store_cart_lifecycle_drill
    evidence = run_demo_store_cart_lifecycle_drill()
    _audit("ops_demo_store_cart_lifecycle", ok=bool(evidence.get("ok")),
           confirmed=int(evidence.get("confirmed") or 0))
    return {"gate_c_complete": False, "demo_store_cart_lifecycle": evidence}


@app.post("/api/ops/drills/swarm-control")
def ops_swarm_control():
    """Gate B: claim/checkpoint/cancel control drill (still incomplete)."""
    from backend.swarm_control_drill import run_swarm_control_drill
    evidence = run_swarm_control_drill()
    _audit("ops_swarm_control", ok=bool(evidence.get("ok")),
           backend=str(evidence.get("backend") or ""))
    return {"gate_b_complete": False, "swarm_control": evidence}


@app.post("/api/ops/drills/swarm-retry")
def ops_swarm_retry():
    """Gate B: lease-expiry → retry_wait control drill (still incomplete)."""
    from backend.swarm_retry_drill import run_swarm_retry_drill
    evidence = run_swarm_retry_drill()
    _audit("ops_swarm_retry", ok=bool(evidence.get("ok")),
           backend=str(evidence.get("backend") or ""),
           status=str(evidence.get("status_after_recover") or ""))
    return {"gate_b_complete": False, "swarm_retry": evidence}


@app.post("/api/ops/drills/device-matrix")
def ops_device_matrix():
    """Gate D: combined web + Android dry-run + ADB probe snapshot (still incomplete)."""
    from backend.device_matrix_drill import run_device_matrix_drill
    evidence = run_device_matrix_drill()
    _audit("ops_device_matrix", android_dry=int(evidence.get("android_dry_run_rows") or 0),
           android_live=int(evidence.get("android_live_rows") or 0),
           online=int((evidence.get("adb_probe") or {}).get("devices_online") or 0))
    return {"gate_d_complete": False, "device_matrix": evidence}


@app.post("/api/ops/drills/android-emulator-smoke")
def ops_android_emulator_smoke():
    """Gate D: live emulator adb smoke when a device is online (still incomplete)."""
    from backend.android_emulator_smoke_drill import run_android_emulator_smoke_drill
    evidence = run_android_emulator_smoke_drill()
    _audit("ops_android_emulator_smoke", ok=bool(evidence.get("ok")),
           api=int(evidence.get("api_level") or 0),
           device=str(evidence.get("device_id") or "")[:40])
    return {"gate_d_complete": False, "android_emulator_smoke": evidence}


@app.post("/api/ops/drills/android-appium-product-matrix")
def ops_android_appium_product_matrix():
    """Gate D: live Appium UiAutomator2 product matrix (still incomplete)."""
    from backend.android_appium_product_matrix_drill import (
        run_android_appium_product_matrix_drill,
    )
    evidence = run_android_appium_product_matrix_drill()
    _audit(
        "ops_android_appium_product_matrix",
        ok=bool(evidence.get("ok")),
        api=int(evidence.get("api_level") or 0),
        passed=int(evidence.get("apps_passed") or 0),
        device=str(evidence.get("device_id") or "")[:40],
    )
    return {"gate_d_complete": False, "android_appium_product_matrix": evidence}


@app.post("/api/ops/drills/multi-api-android-matrix")
def ops_multi_api_android_matrix():
    """Gate D: combine API24 smoke + API30+ Appium matrix rows (still incomplete)."""
    from backend.multi_api_android_matrix_drill import run_multi_api_android_matrix_drill
    evidence = run_multi_api_android_matrix_drill()
    _audit(
        "ops_multi_api_android_matrix",
        ok=bool(evidence.get("ok")),
        apis=",".join(str(a) for a in (evidence.get("api_levels") or [])),
    )
    return {"gate_d_complete": False, "multi_api_android_matrix": evidence}


@app.post("/api/ops/drills/mutation-score")
def ops_mutation_score():
    """Gate J / QX-A09: DemoStore planted-defect mutation score (still incomplete)."""
    from backend.mutation_score_drill import run_mutation_score_drill
    evidence = run_mutation_score_drill()
    caught = len((evidence.get("score") or {}).get("caught") or [])
    _audit("ops_mutation_score", ok=bool(evidence.get("ok")), caught=caught)
    return {"gate_j_complete": False, "mutation_score": evidence}


@app.post("/api/ops/drills/cross-platform-journey")
def ops_cross_platform_journey():
    """QX-A10: cross-platform DemoStore (+ optional Android) journey (still incomplete)."""
    from backend.cross_platform_journey_drill import run_cross_platform_journey_drill
    evidence = run_cross_platform_journey_drill()
    _audit(
        "ops_cross_platform_journey",
        ok=bool(evidence.get("ok")),
        surfaces=len(evidence.get("surfaces") or []),
    )
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "cross_platform_journey": evidence,
    }


@app.post("/api/ops/drills/qx-capabilities")
def ops_qx_capabilities():
    """QX-A02/A07/A12–A18 offline capability bundle (gates stay Partial)."""
    from backend.qx_capabilities_drill import run_qx_capabilities_drill
    evidence = run_qx_capabilities_drill()
    _audit(
        "ops_qx_capabilities",
        ok=bool(evidence.get("ok")),
        passed=sum(1 for v in (evidence.get("checks") or {}).values() if v),
    )
    return {"gate_complete": False, "qx_capabilities": evidence}


@app.post("/api/ops/drills/qx-core-capabilities")
def ops_qx_core_capabilities():
    """QX-A01/A03–A06/A08/A11 offline core capability bundle (gates stay Partial)."""
    from backend.qx_core_capabilities_drill import run_qx_core_capabilities_drill
    evidence = run_qx_core_capabilities_drill()
    _audit(
        "ops_qx_core_capabilities",
        ok=bool(evidence.get("ok")),
        passed=sum(1 for v in (evidence.get("checks") or {}).values() if v),
    )
    return {"gate_complete": False, "qx_core_capabilities": evidence}


@app.post("/api/ops/drills/locale-portfolio")
def ops_locale_portfolio():
    """Gate F: DemoStore locale portfolio evidence (still incomplete)."""
    from backend.locale_portfolio_drill import run_locale_portfolio_drill
    evidence = run_locale_portfolio_drill()
    _audit("ops_locale_portfolio", ok=bool(evidence.get("ok")))
    return {"gate_f_complete": False, "locale_portfolio": evidence}


@app.post("/api/ops/drills/security-portfolio")
def ops_security_portfolio():
    """Gate F: passive DemoStore security portfolio (no probing; still incomplete)."""
    from backend.security_portfolio_drill import run_security_portfolio_drill
    evidence = run_security_portfolio_drill()
    _audit("ops_security_portfolio", ok=bool(evidence.get("ok")),
           verdict=str((evidence.get("portfolio") or {}).get("verdict") or ""))
    return {"gate_f_complete": False, "security_portfolio": evidence}


@app.post("/api/ops/drills/a11y-portfolio")
def ops_a11y_portfolio():
    """Gate F: DemoStore a11y portfolio evidence (still incomplete)."""
    from backend.a11y_portfolio_drill import run_a11y_portfolio_drill
    evidence = run_a11y_portfolio_drill()
    _audit("ops_a11y_portfolio", ok=bool(evidence.get("ok")),
           verdict=str((evidence.get("portfolio") or {}).get("verdict") or ""))
    return {"gate_f_complete": False, "a11y_portfolio": evidence}


@app.post("/api/ops/drills/perf-portfolio")
def ops_perf_portfolio():
    """Gate F: DemoStore performance portfolio evidence (still incomplete)."""
    from backend.perf_portfolio_drill import run_perf_portfolio_drill
    evidence = run_perf_portfolio_drill()
    _audit("ops_perf_portfolio", ok=bool(evidence.get("ok")),
           verdict=str((evidence.get("portfolio") or {}).get("verdict") or ""))
    return {"gate_f_complete": False, "perf_portfolio": evidence}


@app.post("/api/ops/drills/visual-portfolio")
def ops_visual_portfolio():
    """Gate F: DemoStore first-run visual portfolio evidence (still incomplete)."""
    from backend.visual_portfolio_drill import run_visual_portfolio_drill
    evidence = run_visual_portfolio_drill()
    _audit("ops_visual_portfolio", ok=bool(evidence.get("ok")),
           verdict=str((evidence.get("portfolio") or {}).get("verdict") or ""),
           pages=int(evidence.get("pages_recorded") or 0))
    return {"gate_f_complete": False, "visual_portfolio": evidence}


@app.post("/api/ops/drills/compatibility-portfolio")
def ops_compatibility_portfolio():
    """Gate F: DemoStore desktop+mobile compatibility portfolio (still incomplete)."""
    from backend.compatibility_portfolio_drill import run_compatibility_portfolio_drill
    evidence = run_compatibility_portfolio_drill()
    _audit("ops_compatibility_portfolio", ok=bool(evidence.get("ok")),
           verdict=str((evidence.get("portfolio") or {}).get("verdict") or ""),
           desktop=int((evidence.get("matrix") or {}).get("desktop") or 0),
           mobile=int((evidence.get("matrix") or {}).get("mobile") or 0))
    return {"gate_f_complete": False, "compatibility_portfolio": evidence}


@app.post("/api/ops/drills/multi-browser-portfolio-suite")
def ops_multi_browser_portfolio_suite():
    """Gate F: live Chromium/Firefox/WebKit DemoStore portfolio suite (still incomplete)."""
    from backend.multi_browser_portfolio_suite_drill import (
        run_multi_browser_portfolio_suite_drill,
    )
    evidence = run_multi_browser_portfolio_suite_drill()
    _audit(
        "ops_multi_browser_portfolio_suite",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("suites_passed") or 0),
        browsers=",".join(evidence.get("browsers") or [])[:80],
    )
    return {"gate_f_complete": False, "multi_browser_portfolio_suite": evidence}


def _audit_scope(authorization: str | None, x_qa_token: str | None, tenant_id: str | None) -> str | None:
    """Local studio may list every tenant. A signed-in principal sees only their own."""
    from backend.dashboard_auth import auth_mode, authorize
    if auth_mode() not in ("principal", "oidc"):
        return (tenant_id or "").strip() or None
    verdict = authorize(authorization, x_qa_token=x_qa_token, action="audit.read")
    if not verdict.get("ok"):
        reason = verdict.get("reason") or "unauthorized"
        raise HTTPException(403 if verdict.get("role") else 401, reason)
    own = str(verdict.get("tenant_id") or "").strip()
    if not own:
        raise HTTPException(403, "principal has no tenant")
    asked = (tenant_id or "").strip()
    if asked and asked != own:
        raise HTTPException(403, "tenant isolation")
    return own


@app.get("/api/audit/events")
def audit_events(
    limit: int = 50,
    tenant_id: str | None = None,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    """Gate G: newest persisted RBAC/studio audit events (SQLite)."""
    from backend.audit_store import list_audits
    scope = _audit_scope(authorization, x_qa_token, tenant_id)
    return {
        "events": list_audits(
            limit=min(200, max(1, int(limit or 50))),
            tenant_id=scope,
        ),
        "tenant_id": scope,
        "gate_g_complete": False,
    }


@app.get("/api/audit/export")
def audit_export(
    limit: int = 200,
    tenant_id: str | None = None,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    """Gate G: export audit events package (SSO still open)."""
    from backend.audit_store import export_audits
    scope = _audit_scope(authorization, x_qa_token, tenant_id)
    body = export_audits(limit=min(500, max(1, int(limit or 200))), tenant_id=scope)
    _audit("audit_export", count=int(body.get("count") or 0),
           tenant=(scope or "")[:80] or None)
    return body


@app.post("/api/ops/drills/audit-export")
def ops_audit_export():
    """Gate G: tenant-scoped audit export contract drill (still incomplete)."""
    from backend.audit_export_drill import run_audit_export_drill
    evidence = run_audit_export_drill()
    _audit("ops_audit_export", ok=bool(evidence.get("ok")),
           scoped=int(evidence.get("scoped_count") or 0))
    return {"gate_g_complete": False, "audit_export": evidence}


@app.post("/api/ops/drills/dashboard-auth-matrix")
def ops_dashboard_auth_matrix():
    """Gate I: dashboard auth mode matrix (still incomplete — live SSO open)."""
    from backend.dashboard_auth_matrix_drill import run_dashboard_auth_matrix_drill
    evidence = run_dashboard_auth_matrix_drill()
    _audit("ops_dashboard_auth_matrix", ok=bool(evidence.get("ok")),
           passed=int(evidence.get("passed") or 0),
           failed=int(evidence.get("failed") or 0))
    return {"gate_i_complete": False, "dashboard_auth_matrix": evidence}


@app.post("/api/ops/drills/approvals")
def ops_approvals_drill():
    """Gate I: approvals enqueue→decide contract (still incomplete)."""
    from backend.approvals_drill import run_approvals_drill
    evidence = run_approvals_drill()
    _audit("ops_approvals_drill", ok=bool(evidence.get("ok")),
           pending_after=int(evidence.get("pending_after") or 0))
    return {"gate_i_complete": False, "approvals": evidence}


@app.post("/api/ops/drills/sso-contract")
def ops_sso_contract():
    """Gate I: OIDC/hosting env contract snapshot (still incomplete — live SSO open)."""
    from backend.sso_contract_drill import run_sso_contract_drill
    evidence = run_sso_contract_drill()
    _audit("ops_sso_contract", ok=bool(evidence.get("ok")),
           configured=bool(evidence.get("configured")))
    return {"gate_i_complete": False, "sso_contract": evidence}


@app.post("/api/ops/drills/loopback-sso")
def ops_loopback_sso():
    """Gate I: loopback OIDC JWKS + RS256 JWT verification (hosted IdP still open)."""
    from backend.loopback_sso_drill import run_loopback_sso_drill
    evidence = run_loopback_sso_drill()
    _audit(
        "ops_loopback_sso",
        ok=bool(evidence.get("ok")),
        signature=bool(evidence.get("signature_verified")),
    )
    return {"gate_i_complete": False, "loopback_sso": evidence}


@app.post("/api/ops/drills/sso-tenant-acl")
def ops_sso_tenant_acl():
    """Gate I/G: loopback OIDC JWT + SQLite tenant ACL (hosted IdP still open)."""
    from backend.sso_tenant_acl_drill import run_sso_tenant_acl_drill
    evidence = run_sso_tenant_acl_drill()
    _audit(
        "ops_sso_tenant_acl",
        ok=bool(evidence.get("ok")),
        allow=bool((evidence.get("acl") or {}).get("same_tenant_allowed")),
        deny=bool((evidence.get("acl") or {}).get("cross_tenant_denied")),
    )
    return {
        "gate_i_complete": False,
        "gate_g_complete": False,
        "sso_tenant_acl": evidence,
    }


@app.post("/api/ops/drills/incident-tabletop")
def ops_incident_tabletop():
    """Gate H: offline incident tabletop cross-check (still incomplete — hosted on-call open)."""
    from backend.incident_tabletop_drill import run_incident_tabletop_drill
    evidence = run_incident_tabletop_drill()
    _audit("ops_incident_tabletop", ok=bool(evidence.get("ok")),
           roles=len(evidence.get("roles_exercised") or []))
    return {"gate_h_complete": False, "incident_tabletop": evidence}


@app.post("/api/ops/drills/independent-review-pack")
def ops_independent_review_pack():
    """Gate G: hash ops-evidence pack for reviewers (sign-off still pending)."""
    from backend.independent_review_pack_drill import run_independent_review_pack_drill
    evidence = run_independent_review_pack_drill()
    _audit(
        "ops_independent_review_pack",
        ok=bool(evidence.get("ok")),
        artifacts=int(evidence.get("artifact_count") or 0),
        signed_off=bool(evidence.get("signed_off")),
    )
    return {"gate_g_complete": False, "independent_review_pack": evidence}


@app.post("/api/ops/drills/loopback-auth-code-sso")
def ops_loopback_auth_code_sso():
    """Gate I: loopback OIDC auth-code → JWT → dashboard (hosted IdP still open)."""
    from backend.loopback_auth_code_sso_drill import run_loopback_auth_code_sso_drill
    evidence = run_loopback_auth_code_sso_drill()
    _audit("ops_loopback_auth_code_sso", ok=bool(evidence.get("ok")))
    return {"gate_i_complete": False, "loopback_auth_code_sso": evidence}


@app.post("/api/ops/drills/studio-oidc-callback")
def ops_studio_oidc_callback():
    """Gate I: Studio OIDC callback helper against loopback IdP (hosted IdP still open)."""
    from backend.studio_oidc_callback_drill import run_studio_oidc_callback_drill
    evidence = run_studio_oidc_callback_drill()
    _audit("ops_studio_oidc_callback", ok=bool(evidence.get("ok")))
    return {"gate_i_complete": False, "studio_oidc_callback": evidence}


@app.post("/api/ops/drills/loopback-pkce-sso")
def ops_loopback_pkce_sso():
    """Gate I: loopback OIDC PKCE S256 auth-code (hosted IdP still open)."""
    from backend.loopback_pkce_sso_drill import run_loopback_pkce_sso_drill
    evidence = run_loopback_pkce_sso_drill()
    _audit("ops_loopback_pkce_sso", ok=bool(evidence.get("ok")))
    return {"gate_i_complete": False, "loopback_pkce_sso": evidence}


@app.post("/api/ops/drills/swarm-review-checklist")
def ops_swarm_review_checklist():
    """Gate B: product-wide swarm review checklist (sign-off still pending)."""
    from backend.swarm_review_checklist_drill import run_swarm_review_checklist_drill
    evidence = run_swarm_review_checklist_drill()
    _audit("ops_swarm_review_checklist", ok=bool(evidence.get("ok")),
           signed_off=bool(evidence.get("signed_off")))
    return {"gate_b_complete": False, "swarm_review_checklist": evidence}


@app.post("/api/ops/drills/hosted-runner-contracts")
def ops_hosted_runner_contracts():
    """Gates D/F: offline multi-device + multi-browser CI runner contracts."""
    from backend.hosted_runner_contract_drill import run_hosted_runner_contract_drill
    evidence = run_hosted_runner_contract_drill()
    _audit("ops_hosted_runner_contracts", ok=bool(evidence.get("ok")))
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "hosted_runner_contracts": evidence,
    }


@app.post("/api/ops/drills/discovery-score")
def ops_discovery_score():
    """Gate A: multi-fixture discovery completeness score (full matrix still open)."""
    from backend.discovery_score_drill import run_discovery_score_drill
    evidence = run_discovery_score_drill()
    _audit(
        "ops_discovery_score",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("passed") or 0),
        total=int(evidence.get("total") or 0),
    )
    return {"gate_a_complete": False, "discovery_score": evidence}


@app.post("/api/ops/drills/multi-portal-oracle")
def ops_multi_portal_oracle():
    """Gate C: multi-portal approved-spec oracle bind (live portal paths still open)."""
    from backend.multi_portal_oracle_drill import run_multi_portal_oracle_drill
    evidence = run_multi_portal_oracle_drill()
    _audit(
        "ops_multi_portal_oracle",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("passed") or 0),
        total=int(evidence.get("total") or 0),
    )
    return {"gate_c_complete": False, "multi_portal_oracle": evidence}


@app.post("/api/ops/drills/remaining-blockers")
def ops_remaining_blockers():
    """Inventory hard-open hosted/independent blockers (gates stay Partial)."""
    from backend.remaining_blockers_drill import run_remaining_blockers_drill
    evidence = run_remaining_blockers_drill()
    _audit("ops_remaining_blockers", ok=bool(evidence.get("ok")),
           open_count=int(evidence.get("open_count") or 0))
    return {"complete": False, "remaining_blockers": evidence}


@app.post("/api/ops/drills/classic-mutation-score")
def ops_classic_mutation_score():
    """Gate J: ClassicShop planted-defect mutation score (still incomplete)."""
    from backend.classic_mutation_score_drill import run_classic_mutation_score_drill
    evidence = run_classic_mutation_score_drill()
    caught = len((evidence.get("score") or {}).get("caught") or [])
    _audit("ops_classic_mutation_score", ok=bool(evidence.get("ok")), caught=caught)
    return {"gate_j_complete": False, "classic_mutation_score": evidence}


@app.post("/api/ops/drills/fixture-mutation-suite")
def ops_fixture_mutation_suite():
    """Gate J: AdminPortal + TravelSite mutation scores (still incomplete)."""
    from backend.fixture_mutation_suite_drill import run_fixture_mutation_suite_drill
    evidence = run_fixture_mutation_suite_drill()
    _audit(
        "ops_fixture_mutation_suite",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("passed") or 0),
        total=int(evidence.get("total") or 0),
    )
    return {"gate_j_complete": False, "fixture_mutation_suite": evidence}


@app.get("/api/ops/readiness")
def ops_readiness_api():
    """Gate H ops probe. Docs alone never mark the gate complete."""
    from backend.ops_readiness import readiness
    return readiness()


@app.post("/api/ops/drills/backup-restore")
def ops_backup_restore_drill():
    """Run the local SQLite backup/restore drill and record evidence (Gate H still incomplete)."""
    from backend.ops_drill import run_backup_restore_drill, write_local_metrics_snapshot
    evidence = run_backup_restore_drill()
    metrics = write_local_metrics_snapshot()
    _audit("ops_backup_restore_drill", ok=bool(evidence.get("ok")))
    return {"gate_h_complete": False, "backup_restore": evidence, "metrics": metrics}


@app.post("/api/ops/drills/load-probe")
def ops_load_probe(requests: int = 40):
    """Local TestClient load probe. Does not complete Gate H."""
    from backend.ops_drill import run_local_load_probe
    evidence = run_local_load_probe(requests=requests)
    _audit("ops_load_probe", ok=int(evidence.get("ok") or 0), requests=int(evidence.get("requests") or 0))
    return {"gate_h_complete": False, "load_probe": evidence}


@app.post("/api/ops/drills/controlled-soak")
def ops_controlled_soak(duration_s: float = 20.0):
    """Controlled AdminPortal HTTP soak. Does not complete Gate H."""
    from backend.ops_soak_drill import run_controlled_soak
    evidence = run_controlled_soak(duration_s=duration_s)
    _audit(
        "ops_controlled_soak",
        ok=int(evidence.get("ok") or 0),
        fail=int(evidence.get("fail") or 0),
        requests=int(evidence.get("requests") or 0),
    )
    return {"gate_h_complete": False, "controlled_soak": evidence}


@app.post("/api/ops/drills/postgres-isolation")
def ops_postgres_isolation():
    """Live Postgres tenant isolation drill (Gate G still incomplete)."""
    from backend.postgres_drill import isolation_drill
    evidence = isolation_drill()
    _audit("ops_postgres_isolation", ok=bool(evidence.get("ok")))
    return {"gate_g_complete": False, "postgres_isolation": evidence}


@app.post("/api/ops/drills/redis-lease")
def ops_redis_lease():
    """Live Redis SETNX lease drill."""
    from backend.redis_drill import lease_drill
    evidence = lease_drill()
    _audit("ops_redis_lease", ok=bool(evidence.get("ok")))
    return {"gate_g_complete": False, "gate_b_complete": False, "redis_lease": evidence}


@app.post("/api/ops/drills/redis-queue")
def ops_redis_queue():
    """Live Redis DurableQueue plan/drain drill (Gate B/G still incomplete)."""
    from backend.redis_queue_drill import durable_queue_drill
    evidence = durable_queue_drill()
    _audit("ops_redis_queue", ok=bool(evidence.get("ok")))
    return {"gate_g_complete": False, "gate_b_complete": False, "redis_queue": evidence}


@app.post("/api/ops/drills/minio")
def ops_minio_drill():
    """Live MinIO object-store drill (Gate G still incomplete)."""
    from backend.minio_drill import object_store_drill
    evidence = object_store_drill()
    _audit("ops_minio_drill", ok=bool(evidence.get("ok")))
    return {"gate_g_complete": False, "minio": evidence}


@app.post("/api/ops/drills/minio-backup-restore")
def ops_minio_backup_restore():
    """Live MinIO object backup/restore drill (Gate H still incomplete)."""
    from backend.minio_dr_drill import object_store_backup_restore_drill
    evidence = object_store_backup_restore_drill()
    _audit("ops_minio_backup_restore", ok=bool(evidence.get("ok")))
    return {"gate_h_complete": False, "gate_g_complete": False, "minio_backup_restore": evidence}


@app.post("/api/ops/drills/postgres-dr")
def ops_postgres_dr():
    """Gate H: Postgres dump→restore into isolated DB (hosted DR still open)."""
    from backend.postgres_dr_drill import run_postgres_dr_drill
    evidence = run_postgres_dr_drill()
    _audit("ops_postgres_dr", ok=bool(evidence.get("ok")),
           dump_bytes=int(evidence.get("dump_bytes") or 0))
    return {"gate_h_complete": False, "postgres_dr": evidence}


@app.post("/api/ops/drills/multi-region-dr")
def ops_multi_region_dr():
    """Gate H: local dual-region Postgres failover (hosted multi-region still open)."""
    from backend.multi_region_dr_drill import run_multi_region_dr_drill
    evidence = run_multi_region_dr_drill()
    _audit("ops_multi_region_dr", ok=bool(evidence.get("ok")),
           dump_bytes=int(evidence.get("dump_bytes") or 0))
    return {"gate_h_complete": False, "multi_region_dr": evidence}


@app.post("/api/ops/drills/minio-multi-region")
def ops_minio_multi_region():
    """Gate H: MinIO dual-bucket failover (hosted multi-region object DR still open)."""
    from backend.minio_multi_region_drill import run_minio_multi_region_drill
    evidence = run_minio_multi_region_drill()
    _audit("ops_minio_multi_region", ok=bool(evidence.get("ok")),
           bytes=int(evidence.get("bytes") or 0))
    return {"gate_h_complete": False, "minio_multi_region": evidence}


@app.post("/api/ops/drills/redis-multi-region")
def ops_redis_multi_region():
    """Gate H/B: Redis dual-DB failover (hosted Redis multi-region still open)."""
    from backend.redis_multi_region_drill import run_redis_multi_region_drill
    evidence = run_redis_multi_region_drill()
    _audit("ops_redis_multi_region", ok=bool(evidence.get("ok")))
    return {
        "gate_h_complete": False,
        "gate_b_complete": False,
        "redis_multi_region": evidence,
    }


@app.post("/api/ops/drills/multi-store-dr")
def ops_multi_store_dr():
    """Gate H: combined Postgres+MinIO+Redis failover (hosted multi-region still open)."""
    from backend.multi_store_dr_drill import run_multi_store_dr_drill
    evidence = run_multi_store_dr_drill()
    _audit(
        "ops_multi_store_dr",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("passed") or 0),
        total=int(evidence.get("total") or 0),
    )
    return {"gate_h_complete": False, "multi_store_dr": evidence}


@app.post("/api/ops/drills/failover-rto")
def ops_failover_rto():
    """Gate H: timed multi-store failover RTO pack (hosted multi-region still open)."""
    from backend.failover_rto_drill import run_failover_rto_drill
    evidence = run_failover_rto_drill()
    _audit(
        "ops_failover_rto",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("passed") or 0),
        total_ms=int(evidence.get("total_elapsed_ms") or 0),
    )
    return {"gate_h_complete": False, "failover_rto": evidence}


@app.post("/api/ops/drills/portfolio-artifact-manifest")
def ops_portfolio_artifact_manifest():
    """Gate F: CI-upload-shaped portfolio manifest (hosted multi-browser still open)."""
    from backend.portfolio_artifact_manifest_drill import (
        run_portfolio_artifact_manifest_drill,
    )
    evidence = run_portfolio_artifact_manifest_drill()
    _audit(
        "ops_portfolio_artifact_manifest",
        ok=bool(evidence.get("ok")),
        artifacts=int(len(evidence.get("artifacts") or [])),
    )
    return {"gate_f_complete": False, "portfolio_artifact_manifest": evidence}


@app.post("/api/ops/drills/device-artifact-manifest")
def ops_device_artifact_manifest():
    """Gate D: CI-upload-shaped Appium/device manifest (broad CI runners still open)."""
    from backend.device_artifact_manifest_drill import run_device_artifact_manifest_drill
    evidence = run_device_artifact_manifest_drill()
    _audit(
        "ops_device_artifact_manifest",
        ok=bool(evidence.get("ok")),
        artifacts=int(len(evidence.get("artifacts") or [])),
    )
    return {"gate_d_complete": False, "device_artifact_manifest": evidence}


@app.post("/api/ops/drills/independent-review-readiness")
def ops_independent_review_readiness():
    """Gate G: review readiness score (unsigned; human sign-off still open)."""
    from backend.independent_review_readiness_drill import (
        run_independent_review_readiness_drill,
    )
    evidence = run_independent_review_readiness_drill()
    _audit(
        "ops_independent_review_readiness",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
        score=int(evidence.get("score") or 0),
    )
    return {"gate_g_complete": False, "independent_review_readiness": evidence}


@app.post("/api/ops/drills/hosted-idp-contract")
def ops_hosted_idp_contract():
    """Gate I: hosted IdP SSO contract snapshot (live IdP login still open)."""
    from backend.hosted_idp_contract_drill import run_hosted_idp_contract_drill
    evidence = run_hosted_idp_contract_drill()
    _audit("ops_hosted_idp_contract", ok=bool(evidence.get("ok")))
    return {"gate_i_complete": False, "hosted_idp_contract": evidence}


@app.post("/api/ops/drills/hosted-oncall-contract")
def ops_hosted_oncall_contract():
    """Gate H: hosted DR/on-call contract snapshot (live paging still open)."""
    from backend.hosted_oncall_contract_drill import run_hosted_oncall_contract_drill
    evidence = run_hosted_oncall_contract_drill()
    _audit("ops_hosted_oncall_contract", ok=bool(evidence.get("ok")))
    return {"gate_h_complete": False, "hosted_oncall_contract": evidence}


@app.post("/api/ops/drills/production-healing-taxonomy")
def ops_production_healing_taxonomy():
    """Gate E: production failure taxonomy + heal policy (suite still open)."""
    from backend.production_healing_taxonomy_drill import (
        run_production_healing_taxonomy_drill,
    )
    evidence = run_production_healing_taxonomy_drill()
    _audit(
        "ops_production_healing_taxonomy",
        ok=bool(evidence.get("ok")),
        matched=int(evidence.get("matched") or 0),
        total=int(evidence.get("total") or 0),
    )
    return {"gate_e_complete": False, "production_healing_taxonomy": evidence}


@app.post("/api/ops/drills/dual-tenant-oidc-acl")
def ops_dual_tenant_oidc_acl():
    """Gate I/G: dual-tenant loopback OIDC ACL (hosted IdP still open)."""
    from backend.dual_tenant_oidc_acl_drill import run_dual_tenant_oidc_acl_drill
    evidence = run_dual_tenant_oidc_acl_drill()
    _audit(
        "ops_dual_tenant_oidc_acl",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("passed") or 0),
        total=int(evidence.get("total") or 0),
    )
    return {
        "gate_i_complete": False,
        "gate_g_complete": False,
        "dual_tenant_oidc_acl": evidence,
    }


@app.post("/api/ops/drills/workflow-dispatch-contracts")
def ops_workflow_dispatch_contracts():
    """Gates D/F: validate workflow_dispatch YAML contracts (hosted runners open)."""
    from backend.workflow_dispatch_contract_drill import (
        run_workflow_dispatch_contract_drill,
    )
    evidence = run_workflow_dispatch_contract_drill()
    _audit("ops_workflow_dispatch_contracts", ok=bool(evidence.get("ok")))
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "workflow_dispatch_contracts": evidence,
    }


@app.post("/api/ops/drills/classic-shop-cart-lifecycle")
def ops_classic_shop_cart_lifecycle():
    """Gate C: ClassicShop cart add→remove (broader portal paths still open)."""
    from backend.classic_shop_cart_lifecycle_drill import (
        run_classic_shop_cart_lifecycle_drill,
    )
    evidence = run_classic_shop_cart_lifecycle_drill()
    _audit("ops_classic_shop_cart_lifecycle", ok=bool(evidence.get("ok")))
    return {"gate_c_complete": False, "classic_shop_cart_lifecycle": evidence}


@app.post("/api/ops/drills/redis-swarm-contention")
def ops_redis_swarm_contention():
    """Gate B: Redis multi-worker lease contention (product review still open)."""
    from backend.redis_swarm_contention_drill import run_redis_swarm_contention_drill
    evidence = run_redis_swarm_contention_drill()
    _audit(
        "ops_redis_swarm_contention",
        ok=bool(evidence.get("ok")),
        backend=str(evidence.get("backend") or ""),
        claimed=int(evidence.get("total_claimed") or 0),
    )
    return {"gate_b_complete": False, "redis_swarm_contention": evidence}


@app.post("/api/ops/drills/apidemos-interaction")
def ops_apidemos_interaction():
    """Gate D: deeper ApiDemos Appium interaction (broad CI runners still open)."""
    from backend.apidemos_interaction_drill import run_apidemos_interaction_drill
    evidence = run_apidemos_interaction_drill()
    _audit("ops_apidemos_interaction", ok=bool(evidence.get("ok")))
    return {"gate_d_complete": False, "apidemos_interaction": evidence}


@app.post("/api/ops/drills/discovery-surface-matrix")
def ops_discovery_surface_matrix():
    """Gate A: multi-fixture surface-signal matrix (full live completeness open)."""
    from backend.discovery_surface_matrix_drill import run_discovery_surface_matrix_drill
    evidence = run_discovery_surface_matrix_drill()
    _audit(
        "ops_discovery_surface_matrix",
        ok=bool(evidence.get("ok")),
        union_hit=int(evidence.get("union_hit") or 0),
        passed=int(evidence.get("passed") or 0),
    )
    return {"gate_a_complete": False, "discovery_surface_matrix": evidence}


@app.post("/api/ops/drills/production-healing-contract")
def ops_production_healing_contract():
    """Gate E: production healing suite contract (third-party suite still open)."""
    from backend.production_healing_contract_drill import (
        run_production_healing_contract_drill,
    )
    evidence = run_production_healing_contract_drill()
    _audit("ops_production_healing_contract", ok=bool(evidence.get("ok")))
    return {"gate_e_complete": False, "production_healing_contract": evidence}


@app.post("/api/ops/drills/independent-review-summary")
def ops_independent_review_summary():
    """Gate G: human-readable review summary (unsigned; sign-off still open)."""
    from backend.independent_review_summary_drill import (
        run_independent_review_summary_drill,
    )
    evidence = run_independent_review_summary_drill()
    _audit(
        "ops_independent_review_summary",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
        blockers=int(evidence.get("open_blockers") or 0),
    )
    return {"gate_g_complete": False, "independent_review_summary": evidence}


@app.post("/api/ops/drills/independent-review-request")
def ops_independent_review_request():
    """Gate G: reviewer handoff receipt (unsigned; sign-off still open)."""
    from backend.independent_review_request_drill import (
        run_independent_review_request_drill,
    )
    evidence = run_independent_review_request_drill()
    _audit(
        "ops_independent_review_request",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
        blockers=len((evidence.get("request") or {}).get("open_blockers") or []),
    )
    return {"gate_g_complete": False, "independent_review_request": evidence}


@app.post("/api/ops/drills/production-healing-replay-pack")
def ops_production_healing_replay_pack():
    """Gate E: fixture before/after healing replay pack (production still open)."""
    from backend.production_healing_replay_pack_drill import (
        run_production_healing_replay_pack_drill,
    )
    evidence = run_production_healing_replay_pack_drill()
    _audit(
        "ops_production_healing_replay_pack",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("passed") or 0),
    )
    return {"gate_e_complete": False, "production_healing_replay_pack": evidence}


@app.post("/api/ops/drills/hosted-ci-runner-matrix")
def ops_hosted_ci_runner_matrix():
    """Gates D/F: hosted runner matrix honesty snapshot (execution still open)."""
    from backend.hosted_ci_runner_matrix_drill import (
        run_hosted_ci_runner_matrix_drill,
    )
    evidence = run_hosted_ci_runner_matrix_drill()
    _audit(
        "ops_hosted_ci_runner_matrix",
        ok=bool(evidence.get("ok")),
        gate_d_complete=False,
        gate_f_complete=False,
    )
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "hosted_ci_runner_matrix": evidence,
    }


@app.post("/api/ops/drills/hosted-idp-readiness")
def ops_hosted_idp_readiness():
    """Gate I: hosted IdP readiness score (live SSO still open)."""
    from backend.hosted_idp_readiness_drill import run_hosted_idp_readiness_drill
    evidence = run_hosted_idp_readiness_drill()
    _audit(
        "ops_hosted_idp_readiness",
        ok=bool(evidence.get("ok")),
        score=int(evidence.get("score") or 0),
        score_of=int(evidence.get("score_of") or 0),
    )
    return {"gate_i_complete": False, "hosted_idp_readiness": evidence}


@app.post("/api/ops/drills/hosted-oncall-readiness")
def ops_hosted_oncall_readiness():
    """Gate H: hosted DR/on-call readiness score (live paging still open)."""
    from backend.hosted_oncall_readiness_drill import (
        run_hosted_oncall_readiness_drill,
    )
    evidence = run_hosted_oncall_readiness_drill()
    _audit(
        "ops_hosted_oncall_readiness",
        ok=bool(evidence.get("ok")),
        score=int(evidence.get("score") or 0),
        score_of=int(evidence.get("score_of") or 0),
    )
    return {"gate_h_complete": False, "hosted_oncall_readiness": evidence}


@app.post("/api/ops/drills/oidc-groups-role-acl")
def ops_oidc_groups_role_acl():
    """Gate I: OIDC groups→role ACL mapping (hosted IdP still open)."""
    from backend.oidc_groups_role_acl_drill import run_oidc_groups_role_acl_drill
    evidence = run_oidc_groups_role_acl_drill()
    _audit(
        "ops_oidc_groups_role_acl",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("passed") or 0),
    )
    return {"gate_i_complete": False, "oidc_groups_role_acl": evidence}


@app.post("/api/ops/drills/paging-ack")
def ops_paging_ack():
    """Gate H: loopback paging ack→resolve lifecycle (hosted on-call still open)."""
    from backend.paging_ack_drill import run_paging_ack_drill
    evidence = run_paging_ack_drill()
    _audit(
        "ops_paging_ack",
        ok=bool(evidence.get("ok")),
        incident_id=str(evidence.get("incident_id") or ""),
    )
    return {"gate_h_complete": False, "paging_ack": evidence}


@app.post("/api/ops/drills/paging-escalation-ack-pack")
def ops_paging_escalation_ack_pack():
    """Gate H: escalation + ack pack (hosted on-call still open)."""
    from backend.paging_escalation_ack_pack_drill import (
        run_paging_escalation_ack_pack_drill,
    )
    evidence = run_paging_escalation_ack_pack_drill()
    _audit(
        "ops_paging_escalation_ack_pack",
        ok=bool(evidence.get("ok")),
        escalation_ok=bool(evidence.get("escalation_ok")),
        ack_ok=bool(evidence.get("ack_ok")),
    )
    return {"gate_h_complete": False, "paging_escalation_ack_pack": evidence}


@app.post("/api/ops/drills/studio-sso-principal-bootstrap")
def ops_studio_sso_principal_bootstrap():
    """Gate I: first-login principal bootstrap from OIDC claims (hosted IdP still open)."""
    from backend.studio_sso_principal_bootstrap_drill import (
        run_studio_sso_principal_bootstrap_drill,
    )
    evidence = run_studio_sso_principal_bootstrap_drill()
    _audit(
        "ops_studio_sso_principal_bootstrap",
        ok=bool(evidence.get("ok")),
        bootstrapped=bool((evidence.get("bootstrapped") or {}).get("present_after")),
    )
    return {"gate_i_complete": False, "studio_sso_principal_bootstrap": evidence}


@app.post("/api/ops/drills/ci-artifact-upload-rehearsal")
def ops_ci_artifact_upload_rehearsal():
    """Gates D/F: local CI artifact staging rehearsal (hosted runners still open)."""
    from backend.ci_artifact_upload_rehearsal_drill import (
        run_ci_artifact_upload_rehearsal_drill,
    )
    evidence = run_ci_artifact_upload_rehearsal_drill()
    _audit(
        "ops_ci_artifact_upload_rehearsal",
        ok=bool(evidence.get("ok")),
        android=len((evidence.get("android") or {}).get("artifacts") or []),
        browsers=len((evidence.get("browsers") or {}).get("artifacts") or []),
    )
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "ci_artifact_upload_rehearsal": evidence,
    }


@app.post("/api/ops/drills/production-healing-flaky-policy")
def ops_production_healing_flaky_policy():
    """Gate E: flaky/auth/infra no-auto-apply policy (production suite still open)."""
    from backend.production_healing_flaky_policy_drill import (
        run_production_healing_flaky_policy_drill,
    )
    evidence = run_production_healing_flaky_policy_drill()
    _audit(
        "ops_production_healing_flaky_policy",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("passed") or 0),
    )
    return {"gate_e_complete": False, "production_healing_flaky_policy": evidence}


@app.post("/api/ops/drills/production-healing-readiness")
def ops_production_healing_readiness():
    """Gate E: production healing readiness score (third-party suite still open)."""
    from backend.production_healing_readiness_drill import (
        run_production_healing_readiness_drill,
    )
    evidence = run_production_healing_readiness_drill()
    _audit(
        "ops_production_healing_readiness",
        ok=bool(evidence.get("ok")),
        score=int(evidence.get("score") or 0),
        score_of=int(evidence.get("score_of") or 0),
    )
    return {"gate_e_complete": False, "production_healing_readiness": evidence}


@app.post("/api/ops/drills/production-healing-suite-pack")
def ops_production_healing_suite_pack():
    """Gate E: readiness+flaky+replay+taxonomy+multi-app pack (prod suite still open)."""
    from backend.production_healing_suite_pack_drill import (
        run_production_healing_suite_pack_drill,
    )
    evidence = run_production_healing_suite_pack_drill()
    _audit(
        "ops_production_healing_suite_pack",
        ok=bool(evidence.get("ok")),
        production=bool(evidence.get("production_suite_executed")),
    )
    return {"gate_e_complete": False, "production_healing_suite_pack": evidence}


@app.post("/api/ops/drills/production-healing-third-party-sla")
def ops_production_healing_third_party_sla():
    """Gate E: third-party healing SLA contract (production suite still open)."""
    from backend.production_healing_third_party_sla_drill import (
        run_production_healing_third_party_sla_drill,
    )
    evidence = run_production_healing_third_party_sla_drill()
    _audit(
        "ops_production_healing_third_party_sla",
        ok=bool(evidence.get("ok")),
        production=bool(evidence.get("production_suite_executed")),
    )
    return {"gate_e_complete": False, "production_healing_third_party_sla": evidence}


@app.post("/api/ops/drills/production-healing-acceptance-gate")
def ops_production_healing_acceptance_gate():
    """Gate E: acceptance criteria gate (production suite still open / not accepted)."""
    from backend.production_healing_acceptance_gate_drill import (
        run_production_healing_acceptance_gate_drill,
    )
    evidence = run_production_healing_acceptance_gate_drill()
    _audit(
        "ops_production_healing_acceptance_gate",
        ok=bool(evidence.get("ok")),
        accepted=bool(evidence.get("accepted")),
        production=bool(evidence.get("production_suite_executed")),
    )
    return {"gate_e_complete": False, "production_healing_acceptance_gate": evidence}


@app.post("/api/ops/drills/production-healing-seed-catalog")
def ops_production_healing_seed_catalog():
    """Gate E: seed catalog for third-party healing (suite still open)."""
    from backend.production_healing_seed_catalog_drill import (
        run_production_healing_seed_catalog_drill,
    )
    evidence = run_production_healing_seed_catalog_drill()
    _audit(
        "ops_production_healing_seed_catalog",
        ok=bool(evidence.get("ok")),
        score=int(evidence.get("score") or 0),
        production=bool(evidence.get("production_suite_executed")),
    )
    return {"gate_e_complete": False, "production_healing_seed_catalog": evidence}


@app.post("/api/ops/drills/hosted-dispatch-payload-rehearsal")
def ops_hosted_dispatch_payload_rehearsal():
    """Gates D/F: dry-run workflow_dispatch payloads (hosted runners still open)."""
    from backend.hosted_dispatch_payload_rehearsal_drill import (
        run_hosted_dispatch_payload_rehearsal_drill,
    )
    evidence = run_hosted_dispatch_payload_rehearsal_drill()
    _audit(
        "ops_hosted_dispatch_payload_rehearsal",
        ok=bool(evidence.get("ok")),
        android=bool((evidence.get("android") or {}).get("ok")),
        browsers=bool((evidence.get("browsers") or {}).get("ok")),
    )
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "hosted_dispatch_payload_rehearsal": evidence,
    }


@app.post("/api/ops/drills/independent-review-integrity")
def ops_independent_review_integrity():
    """Gate G: unsigned integrity checksum over review artifacts."""
    from backend.independent_review_integrity_drill import (
        run_independent_review_integrity_drill,
    )
    evidence = run_independent_review_integrity_drill()
    _audit(
        "ops_independent_review_integrity",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
        artifacts=len(evidence.get("artifacts") or []),
    )
    return {"gate_g_complete": False, "independent_review_integrity": evidence}


@app.post("/api/ops/drills/independent-review-evidence-catalog")
def ops_independent_review_evidence_catalog():
    """Gate G: catalog ops-evidence for reviewers (unsigned)."""
    from backend.independent_review_evidence_catalog_drill import (
        run_independent_review_evidence_catalog_drill,
    )
    evidence = run_independent_review_evidence_catalog_drill()
    _audit(
        "ops_independent_review_evidence_catalog",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
        entries=int(evidence.get("entry_count") or 0),
    )
    return {"gate_g_complete": False, "independent_review_evidence_catalog": evidence}


@app.post("/api/ops/drills/independent-review-attestation")
def ops_independent_review_attestation():
    """Gate G: unsigned attestation stub for external reviewers."""
    from backend.independent_review_attestation_drill import (
        run_independent_review_attestation_drill,
    )
    evidence = run_independent_review_attestation_drill()
    _audit(
        "ops_independent_review_attestation",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
    )
    return {"gate_g_complete": False, "independent_review_attestation": evidence}


@app.post("/api/ops/drills/hosted-idp-sso-readiness-pack")
def ops_hosted_idp_sso_readiness_pack():
    """Gate I: IdP contract+readiness+ACL pack (hosted SSO still open)."""
    from backend.hosted_idp_sso_readiness_pack_drill import (
        run_hosted_idp_sso_readiness_pack_drill,
    )
    evidence = run_hosted_idp_sso_readiness_pack_drill()
    _audit(
        "ops_hosted_idp_sso_readiness_pack",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "hosted_idp_sso_readiness_pack": evidence}


@app.post("/api/ops/drills/oidc-org-tenant-acl")
def ops_oidc_org_tenant_acl():
    """Gate I: OIDC org/hd claim → tenant ACL (hosted IdP still open)."""
    from backend.oidc_org_tenant_acl_drill import run_oidc_org_tenant_acl_drill
    evidence = run_oidc_org_tenant_acl_drill()
    _audit(
        "ops_oidc_org_tenant_acl",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("passed") or 0),
    )
    return {"gate_i_complete": False, "oidc_org_tenant_acl": evidence}


@app.post("/api/ops/drills/oidc-acl-matrix-pack")
def ops_oidc_acl_matrix_pack():
    """Gate I: tid+email+org/hd+groups ACL matrix (hosted IdP still open)."""
    from backend.oidc_acl_matrix_pack_drill import run_oidc_acl_matrix_pack_drill
    evidence = run_oidc_acl_matrix_pack_drill()
    _audit(
        "ops_oidc_acl_matrix_pack",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "oidc_acl_matrix_pack": evidence}


@app.post("/api/ops/drills/android-device-ci-readiness-pack")
def ops_android_device_ci_readiness_pack():
    """Gate D: Android device CI readiness pack (hosted runners still open)."""
    from backend.android_device_ci_readiness_pack_drill import (
        run_android_device_ci_readiness_pack_drill,
    )
    evidence = run_android_device_ci_readiness_pack_drill()
    _audit(
        "ops_android_device_ci_readiness_pack",
        ok=bool(evidence.get("ok")),
        score=int(evidence.get("score") or 0),
        live=bool(evidence.get("live_hosted_runners")),
    )
    return {"gate_d_complete": False, "android_device_ci_readiness_pack": evidence}


@app.post("/api/ops/drills/browser-portfolio-ci-readiness-pack")
def ops_browser_portfolio_ci_readiness_pack():
    """Gate F: browser portfolio CI readiness pack (hosted runners still open)."""
    from backend.browser_portfolio_ci_readiness_pack_drill import (
        run_browser_portfolio_ci_readiness_pack_drill,
    )
    evidence = run_browser_portfolio_ci_readiness_pack_drill()
    _audit(
        "ops_browser_portfolio_ci_readiness_pack",
        ok=bool(evidence.get("ok")),
        score=int(evidence.get("score") or 0),
        live=bool(evidence.get("live_hosted_runners")),
    )
    return {"gate_f_complete": False, "browser_portfolio_ci_readiness_pack": evidence}


@app.post("/api/ops/drills/independent-review-signoff-pack")
def ops_independent_review_signoff_pack():
    """Gate G: catalog+integrity+attestation pack (unsigned)."""
    from backend.independent_review_signoff_pack_drill import (
        run_independent_review_signoff_pack_drill,
    )
    evidence = run_independent_review_signoff_pack_drill()
    _audit(
        "ops_independent_review_signoff_pack",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
    )
    return {"gate_g_complete": False, "independent_review_signoff_pack": evidence}


@app.post("/api/ops/drills/independent-review-handoff-pack")
def ops_independent_review_handoff_pack():
    """Gate G: request+signoff+summary handoff pack (unsigned)."""
    from backend.independent_review_handoff_pack_drill import (
        run_independent_review_handoff_pack_drill,
    )
    evidence = run_independent_review_handoff_pack_drill()
    _audit(
        "ops_independent_review_handoff_pack",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
    )
    return {"gate_g_complete": False, "independent_review_handoff_pack": evidence}


@app.post("/api/ops/drills/independent-review-findings-template")
def ops_independent_review_findings_template():
    """Gate G: reviewer findings Markdown template (unsigned)."""
    from backend.independent_review_findings_template_drill import (
        run_independent_review_findings_template_drill,
    )
    evidence = run_independent_review_findings_template_drill()
    _audit(
        "ops_independent_review_findings_template",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
    )
    return {"gate_g_complete": False, "independent_review_findings_template": evidence}


@app.post("/api/ops/drills/hosted-idp-claim-map-completeness")
def ops_hosted_idp_claim_map_completeness():
    """Gate I: OIDC claim-map completeness score (hosted IdP still open)."""
    from backend.hosted_idp_claim_map_completeness_drill import (
        run_hosted_idp_claim_map_completeness_drill,
    )
    evidence = run_hosted_idp_claim_map_completeness_drill()
    _audit(
        "ops_hosted_idp_claim_map_completeness",
        ok=bool(evidence.get("ok")),
        score=int(evidence.get("score") or 0),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "hosted_idp_claim_map_completeness": evidence}


@app.post("/api/ops/drills/studio-sso-login-path")
def ops_studio_sso_login_path():
    """Gate I: Studio SSO login-path contract (hosted IdP still open)."""
    from backend.studio_sso_login_path_drill import run_studio_sso_login_path_drill
    evidence = run_studio_sso_login_path_drill()
    _audit(
        "ops_studio_sso_login_path",
        ok=bool(evidence.get("ok")),
        score=int(evidence.get("score") or 0),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "studio_sso_login_path": evidence}


@app.post("/api/ops/drills/studio-sso-session-rebind")
def ops_studio_sso_session_rebind():
    """Gate I: SSO session rebind same sub (hosted IdP still open)."""
    from backend.studio_sso_session_rebind_drill import (
        run_studio_sso_session_rebind_drill,
    )
    evidence = run_studio_sso_session_rebind_drill()
    _audit(
        "ops_studio_sso_session_rebind",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "studio_sso_session_rebind": evidence}


@app.post("/api/ops/drills/independent-review-scope-matrix")
def ops_independent_review_scope_matrix():
    """Gate G: gate→evidence scope matrix (unsigned)."""
    from backend.independent_review_scope_matrix_drill import (
        run_independent_review_scope_matrix_drill,
    )
    evidence = run_independent_review_scope_matrix_drill()
    _audit(
        "ops_independent_review_scope_matrix",
        ok=bool(evidence.get("ok")),
        score=int(evidence.get("score") or 0),
        signed_off=bool(evidence.get("signed_off")),
    )
    return {"gate_g_complete": False, "independent_review_scope_matrix": evidence}


@app.post("/api/ops/drills/independent-review-blocker-freeze")
def ops_independent_review_blocker_freeze():
    """Gate G: freeze hard-open blockers inventory hash (unsigned)."""
    from backend.independent_review_blocker_freeze_drill import (
        run_independent_review_blocker_freeze_drill,
    )
    evidence = run_independent_review_blocker_freeze_drill()
    _audit(
        "ops_independent_review_blocker_freeze",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
    )
    return {"gate_g_complete": False, "independent_review_blocker_freeze": evidence}


@app.post("/api/ops/drills/oidc-tid-tenant-acl")
def ops_oidc_tid_tenant_acl():
    """Gate I: OIDC tid claim → tenant ACL (hosted IdP still open)."""
    from backend.oidc_tid_tenant_acl_drill import run_oidc_tid_tenant_acl_drill
    evidence = run_oidc_tid_tenant_acl_drill()
    _audit(
        "ops_oidc_tid_tenant_acl",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("passed") or 0),
    )
    return {"gate_i_complete": False, "oidc_tid_tenant_acl": evidence}


@app.post("/api/ops/drills/oidc-email-domain-tenant-acl")
def ops_oidc_email_domain_tenant_acl():
    """Gate I: OIDC email domain → tenant ACL (hosted IdP still open)."""
    from backend.oidc_email_domain_tenant_acl_drill import (
        run_oidc_email_domain_tenant_acl_drill,
    )
    evidence = run_oidc_email_domain_tenant_acl_drill()
    _audit(
        "ops_oidc_email_domain_tenant_acl",
        ok=bool(evidence.get("ok")),
        passed=int(evidence.get("passed") or 0),
    )
    return {"gate_i_complete": False, "oidc_email_domain_tenant_acl": evidence}


@app.post("/api/ops/drills/hosted-oncall-readiness-pack")
def ops_hosted_oncall_readiness_pack():
    """Gate H: on-call contract+readiness+paging pack (hosted paging still open)."""
    from backend.hosted_oncall_readiness_pack_drill import (
        run_hosted_oncall_readiness_pack_drill,
    )
    evidence = run_hosted_oncall_readiness_pack_drill()
    _audit(
        "ops_hosted_oncall_readiness_pack",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_paging")),
    )
    return {"gate_h_complete": False, "hosted_oncall_readiness_pack": evidence}


@app.post("/api/ops/drills/multi-region-dr-readiness-pack")
def ops_multi_region_dr_readiness_pack():
    """Gate H: multi-store DR + cutover + on-call pack (hosted DR still open)."""
    from backend.multi_region_dr_readiness_pack_drill import (
        run_multi_region_dr_readiness_pack_drill,
    )
    evidence = run_multi_region_dr_readiness_pack_drill()
    _audit(
        "ops_multi_region_dr_readiness_pack",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_dr")),
    )
    return {"gate_h_complete": False, "multi_region_dr_readiness_pack": evidence}


@app.post("/api/ops/drills/dual-region-store-health-probe")
def ops_dual_region_store_health_probe():
    """Gate H: local dual-region store TCP health probe (hosted DR still open)."""
    from backend.dual_region_store_health_probe_drill import (
        run_dual_region_store_health_probe_drill,
    )
    evidence = run_dual_region_store_health_probe_drill()
    _audit(
        "ops_dual_region_store_health_probe",
        ok=bool(evidence.get("ok")),
        primary_up=int(evidence.get("primary_up") or 0),
        live=bool(evidence.get("live_hosted_dr")),
    )
    return {"gate_h_complete": False, "dual_region_store_health_probe": evidence}


@app.post("/api/ops/drills/hosted-dr-cutover-checklist")
def ops_hosted_dr_cutover_checklist():
    """Gate H: hosted DR cutover checklist (hosted DR still open)."""
    from backend.hosted_dr_cutover_checklist_drill import (
        run_hosted_dr_cutover_checklist_drill,
    )
    evidence = run_hosted_dr_cutover_checklist_drill()
    _audit(
        "ops_hosted_dr_cutover_checklist",
        ok=bool(evidence.get("ok")),
        score=int(evidence.get("score") or 0),
        live=bool(evidence.get("live_hosted_dr")),
    )
    return {"gate_h_complete": False, "hosted_dr_cutover_checklist": evidence}


@app.post("/api/ops/drills/hosted-oncall-rota-contract")
def ops_hosted_oncall_rota_contract():
    """Gate H: hosted on-call rota contract (hosted paging still open)."""
    from backend.hosted_oncall_rota_contract_drill import (
        run_hosted_oncall_rota_contract_drill,
    )
    evidence = run_hosted_oncall_rota_contract_drill()
    _audit(
        "ops_hosted_oncall_rota_contract",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_paging")),
    )
    return {"gate_h_complete": False, "hosted_oncall_rota_contract": evidence}


@app.post("/api/ops/drills/hosted-ci-artifact-gate-pack")
def ops_hosted_ci_artifact_gate_pack():
    """Gates D/F: readiness+dispatch+upload pack (hosted runners still open)."""
    from backend.hosted_ci_artifact_gate_pack_drill import (
        run_hosted_ci_artifact_gate_pack_drill,
    )
    evidence = run_hosted_ci_artifact_gate_pack_drill()
    _audit(
        "ops_hosted_ci_artifact_gate_pack",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_runners")),
    )
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "hosted_ci_artifact_gate_pack": evidence,
    }


@app.post("/api/ops/drills/hosted-workflow-runner-audit")
def ops_hosted_workflow_runner_audit():
    """Gates D/F: audit workflow YAML for dispatch/runner/artifacts (not run)."""
    from backend.hosted_workflow_runner_audit_drill import (
        run_hosted_workflow_runner_audit_drill,
    )
    evidence = run_hosted_workflow_runner_audit_drill()
    _audit(
        "ops_hosted_workflow_runner_audit",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_runners")),
    )
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "hosted_workflow_runner_audit": evidence,
    }


@app.post("/api/ops/drills/hosted-ci-artifact-retention-contract")
def ops_hosted_ci_artifact_retention_contract():
    """Gates D/F: artifact retention contract (hosted runners still open)."""
    from backend.hosted_ci_artifact_retention_contract_drill import (
        run_hosted_ci_artifact_retention_contract_drill,
    )
    evidence = run_hosted_ci_artifact_retention_contract_drill()
    _audit(
        "ops_hosted_ci_artifact_retention_contract",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_runners")),
    )
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "hosted_ci_artifact_retention_contract": evidence,
    }


@app.post("/api/ops/drills/studio-sso-audience-binding")
def ops_studio_sso_audience_binding():
    """Gate I: wrong-aud rejection (hosted IdP SSO still open)."""
    from backend.studio_sso_audience_binding_drill import (
        run_studio_sso_audience_binding_drill,
    )
    evidence = run_studio_sso_audience_binding_drill()
    _audit(
        "ops_studio_sso_audience_binding",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "studio_sso_audience_binding": evidence}


@app.post("/api/ops/drills/hosted-dr-rpo-contract")
def ops_hosted_dr_rpo_contract():
    """Gate H: RPO/backup retention contract (hosted DR still open)."""
    from backend.hosted_dr_rpo_contract_drill import run_hosted_dr_rpo_contract_drill
    evidence = run_hosted_dr_rpo_contract_drill()
    _audit(
        "ops_hosted_dr_rpo_contract",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_dr")),
    )
    return {"gate_h_complete": False, "hosted_dr_rpo_contract": evidence}


@app.post("/api/ops/drills/independent-review-response-sla")
def ops_independent_review_response_sla():
    """Gate G: reviewer response SLA contract (unsigned)."""
    from backend.independent_review_response_sla_drill import (
        run_independent_review_response_sla_drill,
    )
    evidence = run_independent_review_response_sla_drill()
    _audit(
        "ops_independent_review_response_sla",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
    )
    return {"gate_g_complete": False, "independent_review_response_sla": evidence}


@app.post("/api/ops/drills/production-healing-fixture-coverage")
def ops_production_healing_fixture_coverage():
    """Gate E: fixture coverage map (production suite still open)."""
    from backend.production_healing_fixture_coverage_drill import (
        run_production_healing_fixture_coverage_drill,
    )
    evidence = run_production_healing_fixture_coverage_drill()
    _audit(
        "ops_production_healing_fixture_coverage",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("production_suite_executed")),
    )
    return {"gate_e_complete": False, "production_healing_fixture_coverage": evidence}


@app.post("/api/ops/drills/studio-sso-token-expiry")
def ops_studio_sso_token_expiry():
    """Gate I: expired token rejection (hosted IdP SSO still open)."""
    from backend.studio_sso_token_expiry_drill import run_studio_sso_token_expiry_drill
    evidence = run_studio_sso_token_expiry_drill()
    _audit(
        "ops_studio_sso_token_expiry",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "studio_sso_token_expiry": evidence}


@app.post("/api/ops/drills/hosted-ci-permissions-contract")
def ops_hosted_ci_permissions_contract():
    """Gates D/F: workflow permissions contract (hosted runners still open)."""
    from backend.hosted_ci_permissions_contract_drill import (
        run_hosted_ci_permissions_contract_drill,
    )
    evidence = run_hosted_ci_permissions_contract_drill()
    _audit(
        "ops_hosted_ci_permissions_contract",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_runners")),
    )
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "hosted_ci_permissions_contract": evidence,
    }


@app.post("/api/ops/drills/production-healing-rollback-policy")
def ops_production_healing_rollback_policy():
    """Gate E: healing rollback policy (production suite still open)."""
    from backend.production_healing_rollback_policy_drill import (
        run_production_healing_rollback_policy_drill,
    )
    evidence = run_production_healing_rollback_policy_drill()
    _audit(
        "ops_production_healing_rollback_policy",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("production_suite_executed")),
    )
    return {"gate_e_complete": False, "production_healing_rollback_policy": evidence}


@app.post("/api/ops/drills/independent-reviewer-roster-contract")
def ops_independent_reviewer_roster_contract():
    """Gate G: reviewer roster contract (unsigned)."""
    from backend.independent_reviewer_roster_contract_drill import (
        run_independent_reviewer_roster_contract_drill,
    )
    evidence = run_independent_reviewer_roster_contract_drill()
    _audit(
        "ops_independent_reviewer_roster_contract",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
    )
    return {"gate_g_complete": False, "independent_reviewer_roster_contract": evidence}


@app.post("/api/ops/drills/hosted-dr-comms-contract")
def ops_hosted_dr_comms_contract():
    """Gate H: DR communications contract (hosted DR still open)."""
    from backend.hosted_dr_comms_contract_drill import run_hosted_dr_comms_contract_drill
    evidence = run_hosted_dr_comms_contract_drill()
    _audit(
        "ops_hosted_dr_comms_contract",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_dr")),
    )
    return {"gate_h_complete": False, "hosted_dr_comms_contract": evidence}


@app.post("/api/ops/drills/studio-sso-state-binding")
def ops_studio_sso_state_binding():
    """Gate I: OIDC state binding (hosted IdP SSO still open)."""
    from backend.studio_sso_state_binding_drill import run_studio_sso_state_binding_drill
    evidence = run_studio_sso_state_binding_drill()
    _audit(
        "ops_studio_sso_state_binding",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "studio_sso_state_binding": evidence}


@app.post("/api/ops/drills/hosted-ci-timeout-budget")
def ops_hosted_ci_timeout_budget():
    """Gates D/F: workflow timeout budget contract (hosted runners still open)."""
    from backend.hosted_ci_timeout_budget_drill import run_hosted_ci_timeout_budget_drill
    evidence = run_hosted_ci_timeout_budget_drill()
    _audit(
        "ops_hosted_ci_timeout_budget",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_runners")),
    )
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "hosted_ci_timeout_budget": evidence,
    }


@app.post("/api/ops/drills/production-healing-human-loop-contract")
def ops_production_healing_human_loop_contract():
    """Gate E: human-in-the-loop healing contract (production suite still open)."""
    from backend.production_healing_human_loop_contract_drill import (
        run_production_healing_human_loop_contract_drill,
    )
    evidence = run_production_healing_human_loop_contract_drill()
    _audit(
        "ops_production_healing_human_loop_contract",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("production_suite_executed")),
    )
    return {"gate_e_complete": False, "production_healing_human_loop_contract": evidence}


@app.post("/api/ops/drills/independent-review-findings-freeze")
def ops_independent_review_findings_freeze():
    """Gate G: findings + blocker freeze hash (unsigned)."""
    from backend.independent_review_findings_freeze_drill import (
        run_independent_review_findings_freeze_drill,
    )
    evidence = run_independent_review_findings_freeze_drill()
    _audit(
        "ops_independent_review_findings_freeze",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
    )
    return {"gate_g_complete": False, "independent_review_findings_freeze": evidence}


@app.post("/api/ops/drills/hosted-idp-metadata-contract")
def ops_hosted_idp_metadata_contract():
    """Gate I: IdP discovery metadata contract (hosted SSO still open)."""
    from backend.hosted_idp_metadata_contract_drill import (
        run_hosted_idp_metadata_contract_drill,
    )
    evidence = run_hosted_idp_metadata_contract_drill()
    _audit(
        "ops_hosted_idp_metadata_contract",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "hosted_idp_metadata_contract": evidence}


@app.post("/api/ops/drills/paging-severity-routing-contract")
def ops_paging_severity_routing_contract():
    """Gate H: severity→rota routing contract (hosted paging still open)."""
    from backend.paging_severity_routing_contract_drill import (
        run_paging_severity_routing_contract_drill,
    )
    evidence = run_paging_severity_routing_contract_drill()
    _audit(
        "ops_paging_severity_routing_contract",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_paging")),
    )
    return {"gate_h_complete": False, "paging_severity_routing_contract": evidence}


@app.post("/api/ops/drills/hosted-ci-concurrency-contract")
def ops_hosted_ci_concurrency_contract():
    """Gates D/F: concurrency contract for manual dispatch workflows."""
    from backend.hosted_ci_concurrency_contract_drill import (
        run_hosted_ci_concurrency_contract_drill,
    )
    evidence = run_hosted_ci_concurrency_contract_drill()
    _audit(
        "ops_hosted_ci_concurrency_contract",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_runners")),
    )
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "hosted_ci_concurrency_contract": evidence,
    }


@app.post("/api/ops/drills/independent-review-window-contract")
def ops_independent_review_window_contract():
    """Gate G: review window / embargo contract (unsigned)."""
    from backend.independent_review_window_contract_drill import (
        run_independent_review_window_contract_drill,
    )
    evidence = run_independent_review_window_contract_drill()
    _audit(
        "ops_independent_review_window_contract",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
    )
    return {"gate_g_complete": False, "independent_review_window_contract": evidence}


@app.post("/api/ops/drills/production-healing-budget-contract")
def ops_production_healing_budget_contract():
    """Gate E: healing suite budget contract (production suite still open)."""
    from backend.production_healing_budget_contract_drill import (
        run_production_healing_budget_contract_drill,
    )
    evidence = run_production_healing_budget_contract_drill()
    _audit(
        "ops_production_healing_budget_contract",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("production_suite_executed")),
    )
    return {"gate_e_complete": False, "production_healing_budget_contract": evidence}


@app.post("/api/ops/drills/hosted-runner-os-matrix-contract")
def ops_hosted_runner_os_matrix_contract():
    """Gates D/F: runner OS matrix contract (hosted runners still open)."""
    from backend.hosted_runner_os_matrix_contract_drill import (
        run_hosted_runner_os_matrix_contract_drill,
    )
    evidence = run_hosted_runner_os_matrix_contract_drill()
    _audit(
        "ops_hosted_runner_os_matrix_contract",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_runners")),
    )
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "hosted_runner_os_matrix_contract": evidence,
    }


@app.post("/api/ops/drills/healing-approval-queue")
def ops_healing_approval_queue():
    """Gate E: approvals queue applies a heal only when policy allows it."""
    from backend.healing_approval_queue_drill import run_healing_approval_queue_drill
    evidence = run_healing_approval_queue_drill()
    _audit(
        "ops_healing_approval_queue",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("production_suite_executed")),
    )
    return {"gate_e_complete": False, "healing_approval_queue": evidence}


@app.post("/api/ops/drills/production-healing-approval-gate")
def ops_production_healing_approval_gate():
    """Gate E: level-3 repairs require a single-use approval token."""
    from backend.production_healing_approval_gate_drill import (
        run_production_healing_approval_gate_drill,
    )
    evidence = run_production_healing_approval_gate_drill()
    _audit(
        "ops_production_healing_approval_gate",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("production_suite_executed")),
    )
    return {
        "gate_e_complete": False,
        "production_healing_approval_gate": evidence,
    }


@app.post("/api/ops/drills/production-healing-escalation-enforcement")
def ops_production_healing_escalation_enforcement():
    """Gate E: escalation ladder enforced on the repair path."""
    from backend.production_healing_escalation_enforcement_drill import (
        run_production_healing_escalation_enforcement_drill,
    )
    evidence = run_production_healing_escalation_enforcement_drill()
    _audit(
        "ops_production_healing_escalation_enforcement",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("production_suite_executed")),
    )
    return {
        "gate_e_complete": False,
        "production_healing_escalation_enforcement": evidence,
    }


@app.post("/api/ops/drills/production-healing-escalation-ladder")
def ops_production_healing_escalation_ladder():
    """Gate E: healing escalation ladder (production suite still open)."""
    from backend.production_healing_escalation_ladder_drill import (
        run_production_healing_escalation_ladder_drill,
    )
    evidence = run_production_healing_escalation_ladder_drill()
    _audit(
        "ops_production_healing_escalation_ladder",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("production_suite_executed")),
    )
    return {"gate_e_complete": False, "production_healing_escalation_ladder": evidence}


@app.post("/api/ops/drills/hosted-ci-cache-key-contract")
def ops_hosted_ci_cache_key_contract():
    """Gates D/F: CI cache-key contract (hosted runners still open)."""
    from backend.hosted_ci_cache_key_contract_drill import (
        run_hosted_ci_cache_key_contract_drill,
    )
    evidence = run_hosted_ci_cache_key_contract_drill()
    _audit(
        "ops_hosted_ci_cache_key_contract",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_runners")),
    )
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "hosted_ci_cache_key_contract": evidence,
    }


@app.post("/api/ops/drills/independent-review-evidence-retention")
def ops_independent_review_evidence_retention():
    """Gate G: evidence retention contract (unsigned)."""
    from backend.independent_review_evidence_retention_contract_drill import (
        run_independent_review_evidence_retention_contract_drill,
    )
    evidence = run_independent_review_evidence_retention_contract_drill()
    _audit(
        "ops_independent_review_evidence_retention",
        ok=bool(evidence.get("ok")),
        signed_off=bool(evidence.get("signed_off")),
    )
    return {
        "gate_g_complete": False,
        "independent_review_evidence_retention": evidence,
    }


@app.post("/api/ops/drills/studio-sso-pkce-verifier")
def ops_studio_sso_pkce_verifier():
    """Gate I: PKCE verifier required on the Studio token POST when configured."""
    from backend.studio_sso_pkce_verifier_drill import (
        run_studio_sso_pkce_verifier_drill,
    )
    evidence = run_studio_sso_pkce_verifier_drill()
    _audit(
        "ops_studio_sso_pkce_verifier",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "studio_sso_pkce_verifier": evidence}


@app.post("/api/ops/drills/studio-sso-code-reuse")
def ops_studio_sso_code_reuse():
    """Gate I: authorization-code single use (hosted IdP still open)."""
    from backend.studio_sso_code_reuse_drill import run_studio_sso_code_reuse_drill
    evidence = run_studio_sso_code_reuse_drill()
    _audit(
        "ops_studio_sso_code_reuse",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "studio_sso_code_reuse": evidence}


@app.post("/api/ops/drills/studio-sso-redirect-allowlist-enforcement")
def ops_studio_sso_redirect_allowlist_enforcement():
    """Gate I: redirect URI allowlist enforcement (hosted IdP still open)."""
    from backend.studio_sso_redirect_allowlist_enforcement_drill import (
        run_studio_sso_redirect_allowlist_enforcement_drill,
    )
    evidence = run_studio_sso_redirect_allowlist_enforcement_drill()
    _audit(
        "ops_studio_sso_redirect_allowlist_enforcement",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "studio_sso_redirect_allowlist_enforcement": evidence}


@app.post("/api/ops/drills/studio-sso-nbf")
def ops_studio_sso_nbf():
    """Gate I: Studio SSO nbf rejection (hosted IdP still open)."""
    from backend.studio_sso_nbf_drill import run_studio_sso_nbf_drill
    evidence = run_studio_sso_nbf_drill()
    _audit(
        "ops_studio_sso_nbf",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "studio_sso_nbf": evidence}


@app.post("/api/ops/drills/studio-sso-jti-replay")
def ops_studio_sso_jti_replay():
    """Gate I: Studio SSO jti replay rejection (hosted IdP still open)."""
    from backend.studio_sso_jti_replay_drill import run_studio_sso_jti_replay_drill
    evidence = run_studio_sso_jti_replay_drill()
    _audit(
        "ops_studio_sso_jti_replay",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "studio_sso_jti_replay": evidence}


@app.post("/api/ops/drills/studio-sso-nonce-binding")
def ops_studio_sso_nonce_binding():
    """Gate I: Studio SSO nonce binding (hosted IdP still open)."""
    from backend.studio_sso_nonce_binding_drill import run_studio_sso_nonce_binding_drill
    evidence = run_studio_sso_nonce_binding_drill()
    _audit(
        "ops_studio_sso_nonce_binding",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "studio_sso_nonce_binding": evidence}


@app.post("/api/ops/drills/hosted-idp-redirect-uri-allowlist")
def ops_hosted_idp_redirect_uri_allowlist():
    """Gate I: redirect URI allowlist contract (hosted SSO still open)."""
    from backend.hosted_idp_redirect_uri_allowlist_drill import (
        run_hosted_idp_redirect_uri_allowlist_drill,
    )
    evidence = run_hosted_idp_redirect_uri_allowlist_drill()
    _audit(
        "ops_hosted_idp_redirect_uri_allowlist",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_sso")),
    )
    return {"gate_i_complete": False, "hosted_idp_redirect_uri_allowlist": evidence}


@app.post("/api/ops/drills/dual-region-cutover-lag-gate")
def ops_dual_region_cutover_lag_gate():
    """Gate H: block cutover when measured lag exceeds the contract."""
    from backend.dual_region_cutover_lag_gate_drill import (
        run_dual_region_cutover_lag_gate_drill,
    )
    evidence = run_dual_region_cutover_lag_gate_drill()
    _audit(
        "ops_dual_region_cutover_lag_gate",
        ok=bool(evidence.get("ok")),
        blocked=bool(evidence.get("cutover_blocked")),
        live=bool(evidence.get("live_hosted_dr")),
    )
    return {"gate_h_complete": False, "dual_region_cutover_lag_gate": evidence}


@app.post("/api/ops/drills/dual-region-replication-lag-contract")
def ops_dual_region_replication_lag_contract():
    """Gate H: replication lag contract (hosted DR still open)."""
    from backend.dual_region_replication_lag_contract_drill import (
        run_dual_region_replication_lag_contract_drill,
    )
    evidence = run_dual_region_replication_lag_contract_drill()
    _audit(
        "ops_dual_region_replication_lag_contract",
        ok=bool(evidence.get("ok")),
        live=bool(evidence.get("live_hosted_dr")),
    )
    return {"gate_h_complete": False, "dual_region_replication_lag_contract": evidence}


@app.post("/api/ops/drills/multi-region-cutover-rehearsal")
def ops_multi_region_cutover_rehearsal():
    """Gate H: local multi-region cutover pack (hosted DR/on-call still open)."""
    from backend.multi_region_cutover_rehearsal_drill import (
        run_multi_region_cutover_rehearsal_drill,
    )
    evidence = run_multi_region_cutover_rehearsal_drill()
    _audit(
        "ops_multi_region_cutover_rehearsal",
        ok=bool(evidence.get("ok")),
        steps_passed=int(evidence.get("steps_passed") or 0),
        elapsed_ms=int(evidence.get("elapsed_ms") or 0),
    )
    return {"gate_h_complete": False, "multi_region_cutover_rehearsal": evidence}


@app.post("/api/ops/drills/hosted-runner-readiness")
def ops_hosted_runner_readiness():
    """Gates D/F: hosted runner readiness scores (execution still open)."""
    from backend.hosted_runner_readiness_drill import (
        run_hosted_runner_readiness_drill,
    )
    evidence = run_hosted_runner_readiness_drill()
    _audit(
        "ops_hosted_runner_readiness",
        ok=bool(evidence.get("ok")),
        device_score=int((evidence.get("multi_device") or {}).get("score") or 0),
        browser_score=int((evidence.get("multi_browser") or {}).get("score") or 0),
    )
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "hosted_runner_readiness": evidence,
    }


@app.post("/api/ops/drills/observability-probe")
def ops_observability_probe():
    """Gate H: local observability probe (central metrics stack still open)."""
    from backend.observability_probe_drill import run_observability_probe_drill
    evidence = run_observability_probe_drill()
    _audit(
        "ops_observability_probe",
        ok=bool(evidence.get("ok")),
        checks_ready=int(evidence.get("checks_ready") or 0),
        checks_total=int(evidence.get("checks_total") or 0),
    )
    return {"gate_h_complete": False, "observability_probe": evidence}


@app.post("/api/ops/drills/admin-portal-surfaces")
def ops_admin_portal_surfaces():
    """Gate A surface inventory against AdminPortal (still incomplete)."""
    from backend.surface_evidence_drill import run_admin_portal_surface_drill
    evidence = run_admin_portal_surface_drill()
    _audit("ops_admin_portal_surfaces", pages=len(evidence.get("pages_walked") or []), complete=False)
    return {"gate_a_surfaces_complete": False, "surfaces": evidence}


@app.post("/api/ops/drills/demo-store-surfaces")
def ops_demo_store_surfaces():
    """Gate A: DemoStore surface_coverage inventory incl. /lab (still incomplete)."""
    from backend.surface_evidence_drill import run_demo_store_surface_drill
    evidence = run_demo_store_surface_drill()
    _audit("ops_demo_store_surfaces", pages=len(evidence.get("pages_walked") or []), complete=False)
    return {"gate_a_surfaces_complete": False, "surfaces": evidence}


@app.post("/api/ops/drills/classic-shop-surfaces")
def ops_classic_shop_surfaces():
    """Gate A: ClassicShop surface_coverage inventory (still incomplete)."""
    from backend.surface_evidence_drill import run_classic_shop_surface_drill
    evidence = run_classic_shop_surface_drill()
    _audit("ops_classic_shop_surfaces", pages=len(evidence.get("pages_walked") or []), complete=False)
    return {"gate_a_surfaces_complete": False, "surfaces": evidence}


@app.post("/api/ops/drills/travel-site-surfaces")
def ops_travel_site_surfaces():
    """Gate A: TravelSite surface_coverage inventory (still incomplete)."""
    from backend.surface_evidence_drill import run_travel_site_surface_drill
    evidence = run_travel_site_surface_drill()
    _audit("ops_travel_site_surfaces", pages=len(evidence.get("pages_walked") or []), complete=False)
    return {"gate_a_surfaces_complete": False, "surfaces": evidence}


@app.post("/api/ops/drills/ci-rollback")
def ops_ci_rollback():
    """Offline CI/deploy rollback rehearsal (Gate H still incomplete)."""
    from backend.ops_rollback_drill import run_ci_rollback_rehearsal
    evidence = run_ci_rollback_rehearsal()
    _audit("ops_ci_rollback", ok=bool(evidence.get("ok")))
    return {"gate_h_complete": False, "ci_rollback": evidence}


@app.post("/api/ops/drills/paging")
def ops_paging_rehearsal():
    """Loopback paging rehearsal (Gate H still incomplete — no live on-call)."""
    from backend.ops_paging_drill import run_paging_rehearsal
    evidence = run_paging_rehearsal()
    _audit("ops_paging_rehearsal", ok=bool(evidence.get("ok")))
    return {"gate_h_complete": False, "paging": evidence}


@app.post("/api/ops/drills/paging-escalation")
def ops_paging_escalation():
    """Gate H: primary→secondary paging escalation (hosted on-call still open)."""
    from backend.paging_escalation_drill import run_paging_escalation_drill
    evidence = run_paging_escalation_drill()
    _audit("ops_paging_escalation", ok=bool(evidence.get("ok")),
           escalated=bool(evidence.get("escalated")))
    return {"gate_h_complete": False, "paging_escalation": evidence}


def _require_dashboard_auth(
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
) -> None:
    """Optional dashboard auth (bearer / webhook token / principal+RBAC)."""
    from backend.dashboard_auth import authorize
    verdict = authorize(authorization, x_qa_token=x_qa_token)
    if not verdict["ok"]:
        raise HTTPException(401, verdict["reason"])


@app.get("/api/approvals")
def list_approval_queue(
    status: str = "pending",
    limit: int = 50,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    """Gate I: list human-review approvals (pending by default)."""
    _require_dashboard_auth(authorization, x_qa_token)
    from backend.approvals import list_approvals
    return {"approvals": list_approvals(status=status, limit=limit), "gate_i_complete": False}


class CreateApproval(BaseModel):
    kind: str
    subject: str
    detail: str = ""


@app.post("/api/approvals")
def create_approval(
    req: CreateApproval,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    """Enqueue an uncertain_assertion / heal / sensitive item for a person."""
    _require_dashboard_auth(authorization, x_qa_token)
    from backend.approvals import create
    try:
        row = create(req.kind, req.subject, detail=req.detail or "")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    _audit("approval_create", approval=row["id"], kind=row["kind"])
    return row


class DecideApproval(BaseModel):
    answer: str  # yes/accept/approved or no/reject (empty keeps safe reject)


@app.post("/api/approvals/{approval_id}/decide")
def decide_approval_api(
    approval_id: str,
    req: DecideApproval,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    """Record a person's answer via human_review.decide."""
    _require_dashboard_auth(authorization, x_qa_token)
    from backend.approvals import decide_approval
    try:
        row = decide_approval(approval_id, req.answer)
    except KeyError as e:
        raise HTTPException(404, "Approval not found.") from e
    _audit("approval_decide", approval=approval_id, status=row.get("status"))
    return row


@app.get("/api/tenancy/runs")
def tenancy_runs_for_principal(
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    """Gate G: list runs visible to the authenticated principal (tenant isolation).

    Requires QPILOT_DASHBOARD_AUTH=principal. Live Studio SSO remains open.
    """
    from backend.dashboard_auth import authorize
    verdict = authorize(authorization, x_qa_token=x_qa_token, action="run.read")
    if not verdict.get("ok"):
        raise HTTPException(401, verdict.get("reason") or "unauthorized")
    if verdict.get("mode") != "principal" or not verdict.get("principal_id"):
        raise HTTPException(
            400,
            "Set QPILOT_DASHBOARD_AUTH=principal and pass Authorization: Bearer <principal_id>",
        )
    from backend.tenancy_store import runs_visible_to_principal
    body = runs_visible_to_principal(verdict["principal_id"])
    _audit("tenancy_runs", principal=verdict["principal_id"], ok=bool(body.get("ok")),
           count=len(body.get("runs") or []))
    return body


@app.get("/api/tenancy/runs/{run_id}/access")
def tenancy_run_access(
    run_id: str,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    """Gate G: check (and audit) whether the principal may read ``run_id``."""
    from backend.dashboard_auth import authorize
    verdict = authorize(authorization, x_qa_token=x_qa_token, action="run.read")
    if not verdict.get("ok"):
        raise HTTPException(401, verdict.get("reason") or "unauthorized")
    if verdict.get("mode") != "principal" or not verdict.get("principal_id"):
        raise HTTPException(
            400,
            "Set QPILOT_DASHBOARD_AUTH=principal and pass Authorization: Bearer <principal_id>",
        )
    from backend.tenancy_store import assert_run_access
    access = assert_run_access(principal_id=verdict["principal_id"], run_id=run_id)
    _audit("tenancy_run_access", principal=verdict["principal_id"], run=run_id,
           allowed=bool(access.get("allowed")))
    if not access.get("allowed"):
        raise HTTPException(403, access.get("reason") or "forbidden")
    return {**access, "gate_g_complete": False}


@app.get("/api/check")
def check_source(source: str):
    """Step 2: open the website once (or recognise a GitHub repo / project folder) before testing starts."""
    import html as _html

    import requests

    from backend.agents.discovery import unwrap_link
    from backend.agents.setup_agent import is_github, is_local_project, project_name
    pasted = source.strip().strip('"')
    s = unwrap_link(pasted)  # a link copied from Bing / Google results -> the real website address
    if not s:
        raise HTTPException(400, "Enter a website URL, GitHub link or project folder.")
    if is_github(s):
        return {"kind": "github", "ok": True, "title": project_name(s), "url": s}
    if is_local_project(s):
        return {"kind": "folder", "ok": True, "title": project_name(s), "url": s}
    url = s if "://" in s else ("http://" + s if s.startswith(("localhost", "127.")) else "https://" + s)
    try:
        check_target(url)
    except UrlError as e:
        return {"kind": "website", "ok": False, "url": url, "error": str(e)}
    t0 = time.time()
    try:  # follow redirects one by one: a public website may not send us into a private network / metadata address
        public = not is_private_host(urlparse(url).hostname, resolve=True)
        r, hop = None, url
        for _ in range(6):
            r = requests.get(hop, timeout=12, allow_redirects=False, stream=True,
                             headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Qpilot/1.0"})
            if not r.is_redirect:
                break
            hop = urljoin(hop, r.headers.get("location", ""))
            check_target(hop)
            if public and is_private_host(urlparse(hop).hostname, resolve=True):
                raise UrlError(f"the website redirects to a private network address ({urlparse(hop).hostname})")
            r.close()
        r._content = r.raw.read(300_000, decode_content=True)  # (only the start of the page is needed)
    except UrlError as e:
        return {"kind": "website", "ok": False, "url": url, "error": str(e)}
    except requests.RequestException as e:
        return {"kind": "website", "ok": False, "url": url, "error": str(e).split("(Caused by")[0][:200]}
    m = re.search(r"<title[^>]*>(.*?)</title>", r.text[:300_000], re.I | re.S)
    from backend.agents.discovery import _auth_link
    # (a single-page app's #/auth/register is only in the address: the server never sees the part after #)
    login = bool(_auth_link(url) or _auth_link(r.url) or re.search(r"type=[\"']?password", r.text[:300_000], re.I))
    from backend import my_tests  # (your own tests saved for this website: the chat shows them to edit)
    return {"kind": "website", "ok": r.status_code < 400, "url": url, "final_url": r.url,
            "my_tests": [t["text"] for t in my_tests.load(my_tests.site_key_of(url))],
            "unwrapped": pasted if s != pasted else "",
            "status": r.status_code, "ms": int((time.time() - t0) * 1000), "login": login,
            "has_test_account": bool(os.environ.get("TEST_USERNAME") and os.environ.get("TEST_PASSWORD")),
            "title": _html.unescape(" ".join(m.group(1).split()))[:120] if m else ""}


@app.get("/api/providers")
def providers():
    """AI choices for the UI: which have a key in .env (never the key itself) and whether Ollama is running."""
    from backend.config import settings
    ollama_models, ollama_up = [], False
    try:
        probe = settings.ollama_url.replace("//localhost", "//127.0.0.1")  # skips a slow IPv6 attempt on Windows
        # Model discovery must not contact an unapproved network AI endpoint either.
        tags = local_ai_request("GET", f"{probe}/api/tags", timeout=1).json().get("models", [])
        ollama_models, ollama_up = [m["name"].removesuffix(":latest") for m in tags if m.get("name")], True
    except Exception:
        pass
    out = []
    for p in PROVIDERS:
        q = dict(p)
        q["allowed"] = p["id"] in public_policy()["allowed_providers"]
        q["has_key"] = bool(p["key_env"] and os.environ.get(p["key_env"]))
        if p["id"] == "ollama":
            q["running"] = ollama_up
            q["installed"] = ollama_models
            q["models"] = ollama_models + [m for m in p["models"] if m not in ollama_models]
        q["ready"] = bool(q["allowed"] and (
            (ollama_up and ollama_models) if p["id"] == "ollama" else q["has_key"] if p["key_env"] else True))
        q["readiness_reason"] = ("Blocked by local-only privacy" if not q["allowed"] else
            "Ollama is not running" if p["id"] == "ollama" and not ollama_up else
            "No local model is installed" if p["id"] == "ollama" and not ollama_models else
            "API key required" if p["key_env"] and not q["has_key"] else
            "Rules only; no AI interpretation" if p["id"] == "none" else
            "Ready" if p["id"] == "ollama" else "Configured; validated when the provider is called")
        out.append(q)
    return {"exploration": {"hard_page_cap": settings.hard_page_cap,
                            "time_limit_min": settings.crawl_time_limit_min,
                            "default_actions": settings.max_interactions_per_page},
            "default": "ollama", "env_provider": settings.llm_provider, "providers": out,
            "privacy": public_policy()}


def _require_registered_target(req: RunRequest, url: str) -> None:
    """A run starts only with an authorized target, a scope, and a budget."""
    from backend.config import settings as cfg
    from backend.release_row import open_target
    registered = open_target(
        url=url,
        scope=req.crawl_scope or "site",
        page_budget=req.max_pages,
        hard_cap=cfg.hard_page_cap,
        time_budget_min=cfg.crawl_time_limit_min or cfg.run_time_limit_min,
        authorized=req.authorized,
    )
    if not registered["ok"]:
        raise HTTPException(400, registered["problems"][0])


def _validate(req: RunRequest, source: str) -> None:
    """Setup checks with a plain-English message for each problem (HTTP 400)."""
    from backend.agents.setup_agent import is_github, is_local_project
    if req.execution_mode:
        req.show_browser = req.execution_mode == "watch"
    if not req.authorized:
        raise HTTPException(400, "Please confirm that you own this website or have written permission to test it.")
    if req.environment not in ("test", "staging", "production"):
        raise HTTPException(400, "Environment must be test, staging or production.")
    if req.environment == "production" and not req.production_confirmed:
        raise HTTPException(400, "Testing a PRODUCTION website needs the extra confirmation (real users and real data "
                                 "are affected). Prefer a test or staging copy.")
    if req.auth_mode == "existing" and not ((req.test_username or "").strip() and req.test_password):
        raise HTTPException(400, "Existing account: enter both the test username and password.")
    if req.auth_mode == "configured" and not (os.environ.get("TEST_USERNAME") and os.environ.get("TEST_PASSWORD")):
        raise HTTPException(400, "No configured test account is available. Enter an existing account instead.")
    if req.auth_mode == "public" and (req.test_username or req.test_password or req.allow_signup):
        raise HTTPException(400, "Public-only access cannot also use an account or create one.")
    if req.auth_mode == "signup" and not req.allow_signup:
        raise HTTPException(400, "Confirm permission to create a test account, or select another account method.")
    if req.max_interactions_per_page is not None and not 1 <= req.max_interactions_per_page <= 100:
        raise HTTPException(400, "Exploration actions must be between 1 and 100 per page.")
    user, password = (req.test_username or "").strip(), req.test_password or ""
    if bool(user) != bool(password):
        raise HTTPException(400, "Give both the test account's user name AND its password (or neither).")
    if bool((req.login_user_selector or "").strip()) != bool((req.login_password_selector or "").strip()):
        raise HTTPException(400, "Login selectors: give both the user name box and the password box (or neither).")
    if req.crawl_scope not in ("auto", "site", "section", "page"):
        raise HTTPException(400, "Crawl scope must be auto, site, section or page.")
    if req.max_pages < 0 or req.max_depth < 0 or not 0 <= req.page_timeout_s <= 300:
        raise HTTPException(400, "Pages and depth must be 0 or more; the page timeout 0-300 seconds.")
    if len(req.requirements or "") > 4000:
        raise HTTPException(400, "Workflows / expected results: please keep them under 4000 characters.")
    if is_github(source) or is_local_project(source):
        if req.website_only or req.discovery_only:
            raise HTTPException(400, "This operation accepts website URLs only, not repositories or project folders.")
        _require_registered_target(req, source)
        return
    url = source if "://" in source else ("http://" + source if source.startswith(("localhost", "127."))
                                          else "https://" + source)
    bad = [a for a in (req.allow_actions or "").replace(" ", "").lower().split(",") if a
           and a not in ("delete", "logout", "password", "pay")]
    if bad:
        raise HTTPException(400, f"'Also allow' only knows delete, logout, password and pay (not {', '.join(bad)}).")
    if (req.allow_actions or req.test_payment) and req.environment != "staging":
        raise HTTPException(400, "'Also allow' and test payments only apply to a staging run (the owner's test copy).")
    from backend.safety import looks_like_test_host
    if req.environment == "staging" and not req.writes_confirmed and not looks_like_test_host(urlparse(url).hostname):
        raise HTTPException(400, f"{urlparse(url).hostname} does not look like a test copy (no staging / test / qa / "
                                 "dev / uat / preview / sandbox in its address). A staging run SENDS forms and creates, "
                                 "edits and deletes records: tick the second confirmation if this really is a test "
                                 "copy, or choose 'test' / 'production'.")
    try:
        check_target(url)
        if (req.login_url or "").strip():
            login = check_target(req.login_url.strip())
            hosts = {urlparse(url).hostname} | {h.strip() for h in (req.allowed_hosts or "").split(",") if h.strip()}
            if urlparse(login).hostname not in hosts:
                raise UrlError("The login page must be on the same website (or add its host to 'Allowed hosts').")
    except UrlError as e:
        raise HTTPException(400, str(e)) from e
    _require_registered_target(req, url)


@app.post("/api/runs")
def start_run(
    req: RunRequest,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    caller = _signed_in_reader(authorization, x_qa_token, "run.write")
    if isinstance(caller, JSONResponse):
        return caller
    if caller and req.reuse_from_run:
        from backend.tenancy_store import assert_run_access
        reused = Path(req.reuse_from_run).name
        access = assert_run_access(principal_id=caller, run_id=reused, audit=True)
        if not access.get("allowed"):
            return JSONResponse({"detail": access.get("reason") or "forbidden"}, status_code=403)
    from backend.agents.discovery import unwrap_link
    from backend.safety import API_KEY_ENV, safe_url_for_display
    req.llm_provider = _privacy_provider(req.llm_provider, req.privacy_mode)
    source = unwrap_link(req.source.strip().strip('"'))  # Bing / Google result link -> the real website
    if not source:
        raise HTTPException(400, "Enter a website URL, GitHub link or project folder.")
    _validate(req, source)
    if req.llm_provider == "ollama" and not req.allow_rules_fallback:
        from backend.config import settings as cfg
        try:
            models = local_ai_request("GET", cfg.ollama_url.rstrip("/") + "/api/tags", timeout=3).json().get("models", [])
            installed = {m.get("name", "") for m in models}
        except Exception as error:
            raise HTTPException(409, "Selected local AI is unavailable. Start Ollama, select another provider, "
                                     "or explicitly allow rules fallback.") from error
        selected = req.llm_model or cfg.llm_model
        if selected not in installed and selected + ":latest" not in installed:
            raise HTTPException(409, "The selected AI model is not installed. Refresh AI choices or select an installed model.")
    contract_json = ""
    contract = None
    if req.qa_contract is not None:
        from backend.qa_contracts import parse_contract
        try:
            contract = parse_contract(req.qa_contract)
            contract_json = contract.model_dump_json()
        except ValueError as error:
            raise HTTPException(400, "Invalid QA contract: " + str(error)[:500]) from error
    if req.contract_only:
        if contract is None or not contract.test_environment or not contract.flows or contract.rules or contract.checks:
            raise HTTPException(400, "Contract-only runs need an approved test environment with flow cases only.")
        if any(not flow.approved for flow in contract.flows):
            raise HTTPException(400, "Every contract-only flow must be explicitly approved.")
        req.llm_provider = "none"
    with lock:
        if any(j["status"] == "running" for j in jobs.values()):
            raise HTTPException(409, "A test is already running. Wait for it to finish or stop it first.")
        # pages / depth are always sent: 0 really means "no limit" (up to HARD_PAGE_CAP), whatever .env says
        cmd = [sys.executable, "-u", "main.py", source, "--no-open",
               "--max-pages", str(req.max_pages), "--max-depth", str(req.max_depth)]
        if req.crawl_scope != "auto":
            cmd.extend(["--scope", req.crawl_scope])
        if req.discovery_only:
            if req.fresh or req.reuse_tests or req.my_tests or req.qa_contract or req.review or req.allow_signup:
                raise HTTPException(400, "Discovery only cannot edit baselines, run contracts, review tests or create accounts.")
            cmd.append("--discovery-only")
        if req.show_browser:
            cmd.append("--show-browser")
        if req.fresh:
            cmd.append("--fresh")
        if req.reuse_tests:
            cmd.append("--reuse-tests")
        env = os.environ.copy()
        if req.reuse_tests and req.reuse_from_run:
            env["REUSE_FROM_RUN"] = Path(req.reuse_from_run).name
        elif "REUSE_FROM_RUN" in env:
            env.pop("REUSE_FROM_RUN", None)
        env["QA_CONTRACT_JSON"] = contract_json
        env["QA_CONTRACT_ONLY"] = "1" if req.contract_only else "0"
        if req.contract_only:
            env["VISION"] = "off"
        env["QA_LOGIN_ENABLED"] = "0" if req.auth_mode == "public" else "1"
        env["USE_SAVED_ACCOUNT"] = "0" if req.auth_mode in ("public", "existing", "configured") else "1"
        env["QA_ALLOW_RULES_FALLBACK"] = "1" if req.allow_rules_fallback else "0"
        env["EXPLORE_REPEATED_CONTROLS"] = "true" if req.explore_repeated_controls else "false"
        if req.max_interactions_per_page is not None:
            env["MAX_INTERACTIONS_PER_PAGE"] = str(req.max_interactions_per_page)
        # Thorough budgets only when the client sets thorough=true explicitly (Studio Thorough / MCP).
        # explore_repeated_controls stays independent and must not imply Thorough by itself.
        apply_thorough = bool(req.thorough)
        if apply_thorough:
            env["EXPLORE_REPEATED_CONTROLS"] = "true"
            actions = max(80, req.max_interactions_per_page or 0)
            env["MAX_INTERACTIONS_PER_PAGE"] = str(min(100, actions))
            try:
                crawl_min = float(env.get("CRAWL_TIME_LIMIT_MIN") or "0")
            except ValueError:
                crawl_min = 0.0
            env["CRAWL_TIME_LIMIT_MIN"] = str(max(60.0, crawl_min))
            try:
                cases_cap = int(float(env.get("MAX_TEST_CASES") or "0"))
            except ValueError:
                cases_cap = 0
            env["MAX_TEST_CASES"] = str(max(500, cases_cap))
            env["PATTERN_SAMPLES"] = "0"
            env["SWARM_SAMPLE"] = "0"
            env["QA_THOROUGH"] = "1"
        else:
            env.setdefault("SWARM_SAMPLE", "3")
        if req.auth_mode in ("public", "signup", "existing"):
            env.update({"TEST_USERNAME": "", "TEST_PASSWORD": "", "TEST_TOTP_SECRET": "", "TEST_ACCOUNTS": ""})
        env.update({"QA_EVENTS": "1", "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        # this run's setup (anything left empty: the tester decides by itself, or .env is used)
        env["AUTO_REGISTER"] = "true" if req.allow_signup else "false"  # only with your explicit permission
        env["TEST_ENVIRONMENT"] = req.environment
        env["CONFIRM_WRITES"] = "1" if req.environment == "staging" and req.writes_confirmed else "0"
        env["ALLOW_ACTIONS"] = (req.allow_actions or "").replace(" ", "").lower() if req.environment == "staging" else ""
        env["TEST_PAYMENT"] = "1" if req.environment == "staging" and req.test_payment else "0"
        env["RECORD_VIDEO"] = "true" if req.record_video else "false"  # (the tick in the chat decides)
        if req.my_tests is not None:  # (the chat's box: what is in it becomes this website's own tests - main.py)
            env["QA_MY_TESTS_SET"], env["QA_MY_TESTS"] = "1", req.my_tests[:12000]
        if req.review:
            env["REVIEW"] = "on"
        if req.page_timeout_s:
            env["PAGE_TIMEOUT_MS"] = str(req.page_timeout_s * 1000)
        for key, val in {"LOGIN_URL": req.login_url, "LOGIN_USER_SELECTOR": req.login_user_selector,
                         "LOGIN_PASSWORD_SELECTOR": req.login_password_selector,
                         "LOGIN_SUBMIT_SELECTOR": req.login_submit_selector,
                         "LOGIN_SUCCESS_TEXT": req.login_success_text, "ALLOWED_HOSTS": req.allowed_hosts,
                         "EXCLUDE_PATHS": req.exclude_paths, "QA_REQUIREMENTS": req.requirements}.items():
            if (val or "").strip():
                env[key] = val.strip()
        if req.execution_mode:
            req.show_browser = req.execution_mode == "watch"
            env["SLOW_MO_MS"] = str(req.action_delay_ms if req.show_browser else 0)
        env["HEADLESS"] = "false" if req.show_browser else "true"
        if req.show_browser and not req.execution_mode and (not env.get("SLOW_MO_MS") or env["SLOW_MO_MS"] == "0"):
            env["SLOW_MO_MS"] = "1000"
        llm = None
        if req.llm_provider:
            prov = req.llm_provider.lower()
            if prov not in KEY_ENV:
                raise HTTPException(400, f"Unknown AI provider '{req.llm_provider}'.")
            env["LLM_PROVIDER"] = prov
            env["LLM_MODEL"] = (req.llm_model or "").strip()
            key_env = KEY_ENV[prov]
            if key_env and (req.api_key or "").strip():
                env[key_env] = req.api_key.strip()
            if key_env and not env.get(key_env):
                raise HTTPException(400, f"{prov} needs an API key: paste one, or set {key_env} in .env.")
            llm = f"{prov} {env['LLM_MODEL']}".strip()
        if (req.test_username or "").strip() and req.test_password:
            env["TEST_USERNAME"], env["TEST_PASSWORD"] = req.test_username.strip(), req.test_password
        if (req.test_totp_secret or "").strip():
            env["TEST_TOTP_SECRET"] = req.test_totp_secret.strip()
        privacy = _worker_privacy(env, req.llm_provider, req.privacy_mode)
        kwargs = (
            {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
            if IS_WINDOWS
            else {"start_new_session": True}
        )
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", **kwargs)
        job_id = len(jobs) + 1
        secrets = [v for v in [req.test_password, (req.api_key or "").strip()] + [env.get(k) for k in API_KEY_ENV]
                   if v and len(v) >= 4]
        start_lines = (["Thorough budgets active for this run "
                        "(repeated controls, ≥80 actions/page, ≥60 min crawl, ≥500 test cases, every URL pattern)."]
                       if apply_thorough else [])
        jobs[job_id] = {"id": job_id, "source": source, "status": "running", "proc": proc, "lines": start_lines,
                        "pages": [], "stages": {}, "current": None, "run": None, "started": time.time(), "llm": llm,
                        "secrets": secrets, "discovery_only": req.discovery_only,
                        "thorough": apply_thorough, "principal_id": caller or "",
                        "workflow": req.workflow, "privacy_mode": privacy["mode"]}  # (kept in memory only, to hide them in the live log)
    _audit("start_test", job=job_id, source=safe_url_for_display(source), environment=req.environment,
           authorized=True, allow_signup=req.allow_signup, test_account=bool(req.test_username),
           llm=llm or "from .env", reuse_tests=req.reuse_tests, record_video=req.record_video,
           writes_confirmed=bool(req.environment == "staging" and req.writes_confirmed),
           allow_actions=env.get("ALLOW_ACTIONS", ""), test_payment=env.get("TEST_PAYMENT") == "1")
    threading.Thread(target=_reader, args=(jobs[job_id],), daemon=True).start()
    return _public(jobs[job_id])


@app.get("/api/android/environment")
def android_environment_status(appium_url: str | None = None):
    """Report Android prerequisites and local devices without starting Appium or installing tools."""
    from backend.android import ANDROID_EXECUTION_REVISION, AndroidEnvironmentError, android_environment
    from backend.android_emulator import startup_choices
    try:
        return {**startup_choices(android_environment(appium_url) if appium_url else android_environment()),
                'execution_revision': ANDROID_EXECUTION_REVISION}
    except AndroidEnvironmentError as e:
        raise HTTPException(400, str(e)) from e


class AndroidPrepareRequest(BaseModel):
    device_id: str
    avd_name: str = ""
    appium_url: str = "http://127.0.0.1:4723"
    authorized: bool = False
    stage: Literal["all", "appium", "device"] = "all"


@app.post("/api/android/prepare")
async def prepare_android_device(request: AndroidPrepareRequest):
    """Start local Appium and boot the selected emulator before uploading/running a test."""
    from starlette.concurrency import run_in_threadpool

    from backend.android import AndroidEnvironmentError, android_environment
    from backend.android_emulator import ensure_device_ready, startup_choices
    from backend.android_service import ensure_appium_ready

    if not request.authorized:
        raise HTTPException(400, "Confirm that you have permission to test this application.")
    with lock:
        if any(job["status"] == "running" for job in jobs.values()):
            raise HTTPException(409, "A test is already running. Wait for it to finish first.")
    try:
        environment = await run_in_threadpool(android_environment, request.appium_url)
        choices = await run_in_threadpool(startup_choices, environment)
        if not environment["ok"] and not choices["can_prepare"]:
            raise AndroidEnvironmentError("Android tools are not ready: " + "; ".join(environment["errors"]))
        appium = ({"url": request.appium_url, "started": False} if environment.get("appium", {}).get("available")
                  else await run_in_threadpool(ensure_appium_ready, request.appium_url))
        if request.stage == "appium":
            return {"appium": appium}
        return await run_in_threadpool(ensure_device_ready, request.device_id, request.avd_name)
    except AndroidEnvironmentError as error:
        raise HTTPException(409, str(error)) from error


@app.post("/api/mobile/runs")
async def start_mobile_run(
    app_mode: str = Form(...),
    workflow: Literal["standard", "mcp"] = Form("standard"),
    privacy_mode: Literal["local", "cloud"] | None = Form(None),
    device_id: str = Form(...),
    package_name: str = Form(""),
    start_url: str = Form(""),
    app_activity: str = Form(""),
    max_screens: int = Form(0),  # 0 = until exhausted
    max_actions: int = Form(0),
    max_scroll_actions: int = Form(0),
    max_scrolls_per_screen: int = Form(0),
    requested_scope: str = Form('', max_length=2000),
    authorized: bool = Form(False),
    appium_url: str = Form("http://127.0.0.1:4723"),
    max_depth: int = Form(0),
    discovery_timeout_s: int = Form(0),
    expected_destinations: str = Form(""),
    expected_values: str = Form(""),
    requirements: str = Form(""),
    qa_contract: str = Form(""),
    contract_only: bool = Form(False),
    interaction_testing: bool = Form(False),
    test_all_discovered: bool = Form(False),
    thorough: bool = Form(False),  # raise soft budgets when set; 0 still means until exhausted
    max_interactions: int = Form(0),
    interaction_timeout_s: int = Form(0),
    bot_check_wait_s: int = Form(30),
    human_wait_s: int = Form(180),
    dynamic_wait_s: int = Form(12),
    dynamic_retries: int = Form(1),
    overlay_attempts: int = Form(1),
    repeated_failures: int = Form(1),
    scroll_stalls: int = Form(2),
    max_test_cases: int = Form(300),
    allow_rules_fallback: bool = Form(True),
    api_key: str = Form("", max_length=4096),
    test_username: str = Form('', max_length=1024),
    test_password: str = Form('', max_length=4096),
    account_mode: str = Form('legacy', max_length=32),
    llm_provider: str | None = Form(None),
    llm_model: str | None = Form(None),
    apk: Annotated[UploadFile | None, File()] = None,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    """Start an isolated native Appium run from a private APK upload or installed package."""
    caller = _signed_in_reader(authorization, x_qa_token, "run.write")
    if isinstance(caller, JSONResponse):
        return caller
    from backend.android import (
        MAX_APK_BYTES,
        AndroidEnvironmentError,
        android_environment,
        require_device,
        validate_apk,
        validate_mobile_config,
    )

    if not authorized:
        raise HTTPException(400, "Confirm that you own this app or have permission to test it.")
    if llm_provider is None and api_key.strip():
        # A key typed with "Use configured provider": its well-known prefix names the provider (an Anthropic key was
        # sent to OpenAI in run android_20261110_110821_90cd6d)
        llm_provider = key_provider(api_key.strip())
    llm_provider = _privacy_provider(llm_provider, privacy_mode)
    if app_mode == "apk" and apk is None:
        raise HTTPException(400, "Choose an APK file to test.")
    if app_mode != "apk" and apk is not None:
        raise HTTPException(400, "Choose either an APK upload or an installed app, not both.")
    if llm_provider is not None and llm_provider not in KEY_ENV:
        raise HTTPException(400, "Select a supported AI provider.")
    if api_key.strip() and not KEY_ENV.get(llm_provider):
        raise HTTPException(400, "Select a cloud AI provider before entering its API key.")
    try:
        config = validate_mobile_config({
            "app_mode": app_mode, "device_id": device_id, "package_name": package_name, "start_url": start_url,
            "app_activity": app_activity, "max_screens": max_screens, "max_actions": max_actions,
            "max_scroll_actions": max_scroll_actions,
            "max_scrolls_per_screen": max_scrolls_per_screen,
            "appium_url": appium_url, "max_depth": max_depth, "discovery_timeout_s": discovery_timeout_s,
            "expected_destinations": expected_destinations, "expected_values": expected_values, "requirements": requirements, "qa_contract": qa_contract, "contract_only": contract_only,
            "max_test_cases": max_test_cases, "allow_rules_fallback": allow_rules_fallback,
            "interaction_testing": interaction_testing, "thorough": thorough,
            "account_mode": account_mode,
            "max_interactions": max_interactions,
            "test_all_discovered": test_all_discovered,
            "interaction_timeout_s": interaction_timeout_s, "bot_check_wait_s": bot_check_wait_s,
            "human_wait_s": human_wait_s, "dynamic_wait_s": dynamic_wait_s,
            "dynamic_retries": dynamic_retries, "overlay_attempts": overlay_attempts,
            "repeated_failures": repeated_failures, "scroll_stalls": scroll_stalls,
        })
    except AndroidEnvironmentError as e:
        raise HTTPException(400, str(e)) from e
    from .android_accounts import validate_credentials
    try:
        validate_credentials(account_mode, test_username, test_password)
    except AndroidEnvironmentError as e:
        raise HTTPException(400, str(e)) from e
    scope_keys = ('max_depth', 'max_screens', 'max_actions', 'max_scroll_actions',
                  'max_scrolls_per_screen', 'discovery_timeout_s', 'max_test_cases')
    accepted_scope = {key: config[key] for key in scope_keys}
    if requested_scope and not thorough:
        # Thorough raises budgets server-side; client requested_scope may still hold the pre-raise numbers.
        try:
            requested = json.loads(requested_scope)
            if not isinstance(requested, dict) or requested != accepted_scope:
                raise ValueError('Scope differs')
        except (ValueError, TypeError) as error:
            raise HTTPException(409, 'Android exploration settings changed before submission. Refresh the page and review the limits; no test was started.') from error
    elif requested_scope and thorough:
        try:
            requested = json.loads(requested_scope)
            if not isinstance(requested, dict):
                raise ValueError('Scope differs')
        except (ValueError, TypeError) as error:
            raise HTTPException(409, 'Android exploration settings changed before submission. Refresh the page and review the limits; no test was started.') from error
    from starlette.concurrency import run_in_threadpool
    environment = await run_in_threadpool(android_environment, config["appium_url"])
    if not environment["ok"]:
        raise HTTPException(409, "Android environment is not ready: " + "; ".join(environment["errors"]))
    try:
        require_device(config["device_id"], environment["devices"])
    except AndroidEnvironmentError as e:
        raise HTTPException(400, str(e)) from e

    with lock:
        if any(job["status"] == "running" for job in jobs.values()):
            raise HTTPException(409, "A test is already running. Wait for it to finish or stop it first.")
    run_id = f"android_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    run_dir = RUNS / run_id
    private = run_dir / ".private"
    private.mkdir(parents=True)
    if apk is not None:
        filename = (apk.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        if Path(filename).suffix.lower() != ".apk":
            shutil.rmtree(run_dir)
            await apk.close()
            raise HTTPException(400, "Upload an Android .apk file.")
        apk_path = private / "app.apk"
        size = 0
        try:
            with apk_path.open("wb") as target:
                while chunk := await apk.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_APK_BYTES:
                        raise HTTPException(413, f"APK must be no larger than {MAX_APK_BYTES // (1024 * 1024)} MB.")
                    target.write(chunk)
        except Exception:
            shutil.rmtree(run_dir, ignore_errors=True)
            await apk.close()
            raise
        finally:
            await apk.close()
        try:
            config["apk_path"] = str(validate_apk(apk_path))
        except AndroidEnvironmentError as e:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise HTTPException(400, str(e)) from e
    config_path = private / "android_config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    source = (f"Android Chrome {config['start_url']}" if app_mode == "web" else
              f"Android app {config['package_name']}" if config["package_name"] else "Uploaded Android APK")
    command = [sys.executable, "-u", "-m", "backend.android_runner", "--config", str(config_path)]
    env = os.environ.copy()
    if llm_provider is not None:
        previous_provider = env.get("LLM_PROVIDER", "ollama")
        env["LLM_PROVIDER"] = llm_provider
        if llm_model is None and (llm_provider != previous_provider or not env.get("LLM_MODEL")):
            models = next(provider["models"] for provider in PROVIDERS if provider["id"] == llm_provider)
            env["LLM_MODEL"] = models[0] if models else ""
    if llm_model is not None:
        env["LLM_MODEL"] = llm_model[:200]
    if api_key.strip():
        env[KEY_ENV[llm_provider]] = api_key.strip()
    if test_username:
        env['BLOWAI_SECRET_TEST_USERNAME'] = test_username
        env['QPILOT_SECRET_TEST_USERNAME'] = test_username
    if test_password:
        env['BLOWAI_SECRET_TEST_PASSWORD'] = test_password
        env['QPILOT_SECRET_TEST_PASSWORD'] = test_password
    from .qa_contracts import parse_contract
    from .qa_oracles import resolve_private_inputs
    try:
        private_inputs = resolve_private_inputs(parse_contract(config['qa_contract']), env)
    except ValueError as error:
        if run_dir.resolve().is_relative_to(RUNS.resolve()):
            shutil.rmtree(run_dir)
        raise HTTPException(400, str(error)) from error
    env.update({"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    kwargs = (
        {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
        if IS_WINDOWS
        else {"start_new_session": True}
    )
    with lock:
        if any(job["status"] == "running" for job in jobs.values()):
            shutil.rmtree(run_dir, ignore_errors=True)
            raise HTTPException(409, "A test is already running. Wait for it to finish or stop it first.")
        try:
            privacy = _worker_privacy(env, llm_provider, privacy_mode)
            proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", **kwargs)
        except HTTPException:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise
        except OSError as e:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise HTTPException(500, "Could not start the Android test process.") from e
        job_id = max(jobs, default=0) + 1
        jobs[job_id] = {"id": job_id, "source": source, "status": "running", "proc": proc, "lines": [],
                        "pages": [], "stages": {}, "current": None, "run": run_id, "started": time.time(),
                        "llm": {"provider": env.get("LLM_PROVIDER", "ollama"), "model": env.get("LLM_MODEL", "")},
                        "secrets": [env[k] for k in KEY_ENV.values() if k and env.get(k)]
                        + [value for value in (test_username, test_password) if value]
                        + list(private_inputs['secrets'].values()), "target_type": "android",
                         "workflow": workflow, "privacy_mode": privacy["mode"],
                         "principal_id": caller or ""}
    _audit("start_android_test", job=job_id, run=run_id, app_mode=app_mode, device=device_id,
           package=package_name if app_mode == "installed" else "", authorized=True)
    threading.Thread(target=_reader, args=(jobs[job_id],), daemon=True).start()
    return {**_public(jobs[job_id]), 'exploration_scope': accepted_scope}


@app.get("/api/runs/latest")
def latest_run(
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    caller = _signed_in_reader(authorization, x_qa_token)
    if isinstance(caller, JSONResponse):
        return caller
    visible = [job for job in jobs.values() if _refuse_job(job, caller) is None]
    return _public(max(visible, key=lambda job: job["id"])) if visible else None


@app.get("/api/android/runs/{run}/coverage")
def android_coverage_dashboard(run: str):
    from .android_coverage import dashboard
    d = _run_dir(run)
    if not (d / ".private/android_config.json").is_file():
        raise HTTPException(400, "This is not an Android run.")
    return dashboard(d)


@app.post("/api/android/runs/{run}/resume")
async def resume_android_run(
    run: str,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    caller = _signed_in_reader(authorization, x_qa_token, "run.write")
    if isinstance(caller, JSONResponse):
        return caller
    from .android_resume import snapshot
    d = _run_dir(run)
    config_path = d / ".private/android_config.json"
    if not config_path.is_file():
        raise HTTPException(400, "The saved Android configuration is unavailable.")
    if not snapshot(d)["can_resume"]:
        raise HTTPException(409, "No safely resumable unexecuted cases remain.")
    config = _read_json(config_path, {})
    # Reuse the original selected device and authorization, never substitute a phone.
    await prepare_android_device(AndroidPrepareRequest(device_id=config["device_id"],
                                 appium_url=config["appium_url"], authorized=True))
    from .qa_contracts import parse_contract
    from .qa_oracles import resolve_private_inputs
    try:
        inputs = resolve_private_inputs(parse_contract(config.get("qa_contract")))
    except ValueError as error:
        raise HTTPException(409, "Restore the original private input references before resuming.") from error
    env = os.environ.copy()
    # Resuming executes saved, validated cases; no new AI exploration is requested.
    env.update(LLM_PROVIDER="none", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    privacy = _worker_privacy(env, "none")
    command = [sys.executable, "-u", "-m", "backend.android_runner", "--config", str(config_path), "--resume"]
    kwargs = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if IS_WINDOWS else {"start_new_session": True}
    with lock:
        if any(job["status"] == "running" for job in jobs.values()):
            raise HTTPException(409, "A test is already running.")
        (d / "STOP").unlink(missing_ok=True)
        try:
            proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", **kwargs)
        except OSError as error:
            raise HTTPException(500, "Could not start the Android resume worker.") from error
        job_id = max(jobs, default=0) + 1
        jobs[job_id] = {"id": job_id, "source": "Resume Android " + run, "status": "running", "proc": proc,
                        "lines": [], "pages": [], "stages": {}, "current": None, "run": run, "started": time.time(),
                        "llm": {"provider": "none", "model": ""}, "secrets": list(inputs["secrets"].values()),
                        "target_type": "android", "workflow": "standard", "privacy_mode": privacy["mode"],
                        "principal_id": caller or ""}
    _audit("resume_android_test", job=job_id, run=run)
    threading.Thread(target=_reader, args=(jobs[job_id],), daemon=True).start()
    return _public(jobs[job_id])


@app.get("/api/runs/{job_id}")
def run_status(
    job_id: int, since: int = 0, psince: int = 0,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    caller = _signed_in_reader(authorization, x_qa_token)
    if isinstance(caller, JSONResponse):
        return caller
    job = _job_or_404(job_id)
    refused = _refuse_job(job, caller)
    if refused is not None:
        return refused
    return _public(job, since, psince)


@app.get("/api/pages/{run}")
def pages_status(run: str):
    """Every page found: verified (opened), inspected (type, elements, features) and its tests' results -
    the page-by-page view of the run (live while it runs, final afterwards)."""
    from backend.excel import case_hits, case_result
    d = _run_dir(run)
    pages = _read_json(d / "app_map.json", [])
    cases = _read_json(d / "test_cases.json", [])
    results = _read_json(d / "results.json", []) if (d / "results.json").exists() else \
        [r for f in _live_results(d) for r in _read_jsonl(f)]
    out = []
    for n, p in enumerate(pages, start=1):
        mine = [c for c in cases if p.get("slug") in (c.get("pages") or [c.get("page")])]
        st = [case_result(c, results)[0] if results or c.get("blocked") else "Pending" for c in mine]
        checks = sum(len(case_hits(c, results)) for c in mine) if results else 0
        out.append({"n": n, "url": p.get("url"), "title": p.get("title"), "auth": bool(p.get("auth")),
                    "type": p.get("page_type"), "features": p.get("features") or [],
                    "buttons": len(p.get("buttons", [])), "inputs": len(p.get("inputs", [])),
                    "forms": len(p.get("forms", [])), "status": p.get("status"),
                    "needs_permission": bool(p.get("needs_permission")), "failed": bool(p.get("error")),
                    "screenshot": f"/runs/{run}/{p['screenshot']}" if p.get("screenshot") else None,
                    "cases": len(mine), "checks": checks,
                    **{k.lower().replace(" ", "_"): st.count(k) for k in
                       ("Passed", "Failed", "Flaky", "Skipped", "Blocked", "Inconclusive", "Pending", "Not run")}})
    return {"pages": out, "total": len(out)}


class ReviewAnswers(BaseModel):
    answers: dict = {}  # tc_id -> {"answer": "correct" | "should be" | "skip" | "allowed" | "not allowed", "text": ".."}
    leave_out: list[str] = []   # test cases you unticked (this run only)
    add_tests: list[str] = []   # your own tests in plain English (kept for the website)


@app.get("/api/runs/{job_id}/events")
def run_events(
    job_id: int, after: str = "", limit: int = Query(default=150, ge=1, le=500),
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    from backend.execution_events import read_events
    caller = _signed_in_reader(authorization, x_qa_token)
    if isinstance(caller, JSONResponse):
        return caller
    job = _job_or_404(job_id)
    refused = _refuse_job(job, caller)
    if refused is not None:
        return refused
    if not job.get("run"):
        return {"events": [], "cursor": after}
    try:
        return read_events(_run_dir(job["run"]), after, limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/runs/{job_id}/review")
def get_review(
    job_id: int,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    """The questions a running test asks you (what it can't know: is what it saw correct, is a rule allowed)."""
    caller = _signed_in_reader(authorization, x_qa_token)
    if isinstance(caller, JSONResponse):
        return caller
    job = jobs.get(job_id)
    if job and (refused := _refuse_job(job, caller)) is not None:
        return refused
    if not job or not job.get("run"):
        raise HTTPException(404, "no such test")
    req = _read_json(RUNS / job["run"] / "review_request.json", None)
    if not req:
        return {"questions": [], "answered": False}
    return dict(req, answered=(RUNS / job["run"] / "review_answers.json").exists())


@app.post("/api/runs/{job_id}/review")
def post_review(
    job_id: int, body: ReviewAnswers,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    caller = _signed_in_reader(authorization, x_qa_token, "run.write")
    if isinstance(caller, JSONResponse):
        return caller
    job = jobs.get(job_id)
    if job and (refused := _refuse_job(job, caller, "run.write")) is not None:
        return refused
    if not job:
        raise HTTPException(404, "no such test")
    if not job.get("run") or job["status"] != "running":
        raise HTTPException(400, "this test is not waiting for a review")
    allowed = {"correct", "should be", "skip", "allowed", "not allowed"}
    clean = {str(k)[:20]: {"answer": v.get("answer"), "text": str(v.get("text") or "")[:300]}
             for k, v in body.answers.items() if isinstance(v, dict) and v.get("answer") in allowed}
    leave_out = [str(x)[:20] for x in body.leave_out[:500]]
    add_tests = [str(x)[:300] for x in body.add_tests[:30] if str(x).strip()]
    (RUNS / job["run"] / "review_answers.json").write_text(json.dumps(
        {"answers": clean, "leave_out": leave_out, "add_tests": add_tests}, indent=2), encoding="utf-8")
    _audit("review_answers", job=job_id, run=job["run"], answers=len(clean), left_out=len(leave_out),
           added=len(add_tests))
    return {"ok": True, "answers": len(clean), "left_out": len(leave_out), "added": len(add_tests)}


@app.post("/api/runs/{job_id}/stop")
def stop_run(
    job_id: int,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    caller = _signed_in_reader(authorization, x_qa_token, "run.write")
    if isinstance(caller, JSONResponse):
        return caller
    job = _job_or_404(job_id)
    refused = _refuse_job(job, caller, "run.write")
    if refused is not None:
        return refused
    if job["status"] != "running":
        raise HTTPException(400, "not running")
    job["stopping"] = True
    job["current"] = "stopping"
    _audit("stop_test", job=job_id, run=job.get("run"))
    run = job.get("run")
    if run and (RUNS / run).is_dir():
        # Preserve the stop marker for diagnostics, then stop main.py and its browser/pytest/Appium children now.
        try:
            (RUNS / run / "STOP").write_text("stopped from the web UI", encoding="utf-8")
        except OSError:
            pass  # termination must not wait on a run folder that is being removed or is read-only
    _kill(job)
    return {"ok": True, "stopped_immediately": True}


def _kill(job: dict) -> None:
    """Kill main.py AND the browser / pytest / app server it started."""
    if job["proc"].poll() is not None:
        return
    if IS_WINDOWS:
        result = subprocess.run(["taskkill", "/F", "/T", "/PID", str(job["proc"].pid)], check=False,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode and job["proc"].poll() is None:
            job["proc"].kill()
    else:
        try:
            os.killpg(os.getpgid(job["proc"].pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            job["proc"].kill()


@app.get("/api/history")
def history(
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    reader = _signed_in_reader(authorization, x_qa_token)
    if isinstance(reader, JSONResponse):
        return reader
    folders = sorted((p for p in RUNS.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    if reader:
        from backend.tenancy_store import assert_run_access
        folders = [d for d in folders
                   if assert_run_access(principal_id=reader, run_id=d.name, audit=False).get("allowed")]
    out = []
    for d in folders[:30]:
        s = _read_json(d / "summary.json", None)
        date = time.strftime("%d %b %H:%M", time.localtime(d.stat().st_mtime))
        if s:
            out.append({"run": d.name, "url": s.get("source") or s.get("url"), "verdict": s.get("verdict"),
                        "date": date, "incomplete": False})
        else:
            # Incomplete / aborted runs still appear so they can be opened or deleted from Studio.
            label = d.name
            cfg = _read_json(d / ".private" / "android_config.json", None) or {}
            if cfg.get("start_url"):
                label = f"Android Chrome {cfg['start_url']}"
            elif cfg.get("package_name"):
                label = f"Android app {cfg['package_name']}"
            elif cfg.get("apk_path") or cfg.get("app_mode") == "apk":
                label = "Uploaded Android APK"
            out.append({"run": d.name, "url": label, "verdict": "incomplete",
                        "date": date, "incomplete": True})
    return out


@app.get("/api/report/{run}")
def report(run: str):
    d = _run_dir(run)
    pages = [{"url": p.get("url"), "title": p.get("title"), "status": p.get("status"), "error": p.get("error"),
              "load_time_ms": p.get("load_time_ms"), "screenshot": p.get("screenshot"),
              "console_errors": len(p.get("console_errors", []))}
             for p in _read_json(d / "app_map.json", [])]
    excel = _excel_file(d)
    console = d / "console.log"
    return {
        "run": run,
        "summary": _read_json(d / "summary.json", None),
        "cases_available": (d / "test_cases.json").is_file(),
        "components_count": (_read_json(d / "components.json", {}) or {}).get("total_components"),
        "fixes": _read_json(d / "fixes.json", []),
        "failures": _read_json(d / "failures.json", []),
        "changes": _read_json(d / "changes.json", {}),
        "cost": _read_json(d / "cost.json", None),
        "healing": _read_json(d / "healing_log.json", []),
        "coverage": _read_json(d / "coverage.json", None),
        "components_report": f"/runs/{run}/components.html" if (d / "components.html").exists() else None,
        "comparison": _read_json(d / "comparison.json", None),
        "crawl": _read_json(d / "crawl.json", None),
        "login": _read_json(d / "login.json", None),
        "execution": _read_json(d / "execution.json", None),
        "visual": _read_json(d / "visual.json", None),
        "integrations": _read_json(d / "integrations.json", None),
        "recheck": _read_json(d / "recheck.json", {}),
        "pages": pages,
        "excel": f"/runs/{run}/{excel.name}" if excel else None,
        "report_html": f"/runs/{run}/report.html" if (d / "report.html").exists() else None,
        "videos": [f"/runs/{run}/videos/{v.name}" for v in sorted((d / "videos").glob("*.webm"))],
        "console": console.read_text(encoding="utf-8", errors="replace").splitlines()[-400:] if console.exists() else [],
    }


@app.get("/api/coverage/{run}")
def coverage(run: str):
    """Every control found on the pages: tested, or not tested and why."""
    return _read_json(_run_dir(run) / "coverage.json", None)


@app.get("/api/cases/{run}/download")
def cases_download(run: str):
    """The structured test cases (with their results) as JSON - to keep, review or reuse."""
    d = _run_dir(run)
    if not (d / "test_cases.json").exists():
        raise HTTPException(404, "no test cases yet")
    return FileResponse(d / "test_cases.json", filename=f"test_cases_{run}.json", media_type="application/json")


@app.get("/api/cases/{run}")
def case_progress(run: str):
    """Every Excel test case with its live execution status (used while the run is going, and after)."""
    d = _run_dir(run)
    executing = any(j.get("run") == run and j["status"] == "running" and j["stages"].get("execution") == "running"
                    for j in jobs.values())
    progress = _case_progress(d, executing)
    summary = _read_json(d / "summary.json", {}) or {}
    progress.update({
        "available": (d / "test_cases.json").is_file(),
        "excel_available": _excel_file(d) is not None,
        "discovery_only": bool(summary.get("discovery_only") or summary.get("mode") == "discovery"),
        "complete": (d / "summary.json").is_file(),
        "empty_reason": summary.get("setup_error") or summary.get("incomplete_reason") or "",
    })
    return progress


@app.get("/api/excel/{run}/download")
def excel_download(run: str):
    """The Excel file as a normal download (saved to the Downloads folder, opens in Excel)."""
    d = _run_dir(run)
    f = _excel_file(d)
    if not f:
        raise HTTPException(404, "no Excel file yet")
    site = re.sub(r"_\d{8}_\d{6}$", "", run)
    return FileResponse(f, filename=f"test_cases_{site}.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/excel/{run}")
def excel(run: str):
    """The Excel workbook as JSON, so the page can show it as a table."""
    f = _excel_file(_run_dir(run))
    if not f:
        raise HTTPException(404, "no Excel file yet")
    from openpyxl import load_workbook
    wb = load_workbook(f, read_only=True)
    sheets = []
    for ws in wb.worksheets:
        rows = [["" if v is None else v for v in r] for r in ws.iter_rows(values_only=True)]
        if rows:
            sheets.append({"name": ws.title, "headers": rows[0], "rows": rows[1:]})
    wb.close()
    return {"file": f"/runs/{run}/{f.name}", "name": f.name, "sheets": sheets}


@app.delete("/api/runs/{run}")
def delete_run(run: str, x_agentic_qa: str | None = Header(default=None)):
    """Delete one test completely: its folder (report, Excel, screenshots, scripts, logs) and, if the site's
    saved baseline came from this test, that baseline too (so the next test of the site starts fresh)."""
    import shutil
    if x_agentic_qa != "1":
        raise HTTPException(403, "forbidden")
    d = _run_dir(run)
    if any(j.get("run") == run and j["status"] == "running" for j in jobs.values()):
        raise HTTPException(409, "This test is still running. Stop it first.")
    baseline_removed = False
    for meta in (ROOT / "baseline").glob("*/meta.json"):  # the baseline saved by this test, if any
        if (_read_json(meta, {}) or {}).get("run_id") == run:
            shutil.rmtree(meta.parent, ignore_errors=True)
            baseline_removed = True

    def _rmtree_force(path: Path) -> None:
        """Delete a run folder; clear read-only bits and retry (common on Windows when Excel held a file)."""
        import stat
        import time as _time

        def _clear(func, p, _exc=None):
            try:
                os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
                func(p)
            except OSError:
                pass

        last: Exception | None = None
        for attempt in range(5):
            try:
                if not path.exists():
                    return
                # Python 3.12+: onexc; older: onerror
                try:
                    shutil.rmtree(path, onexc=_clear)
                except TypeError:
                    shutil.rmtree(path, onerror=lambda f, p, e: _clear(f, p, e))
                if not path.exists():
                    return
            except Exception as e:
                last = e
            _time.sleep(0.35 * (attempt + 1))
        if last:
            raise last
        raise OSError(f"Could not remove {path}")

    try:
        _rmtree_force(d)
    except PermissionError as e:
        raise HTTPException(409, "A file of this test is open in another program (e.g. the Excel file in Excel). "
                                 "Close it and try again.") from e
    except OSError as e:
        raise HTTPException(409 if getattr(e, "winerror", None) in {5, 32} else 500,
                            "Could not delete the test folder. Close Excel/report viewers for this run, "
                            f"then try again. ({str(e)[:160]})") from e
    if d.exists():
        raise HTTPException(409, "The test folder is still on disk after delete. Close any open files from this run and retry.")
    _audit("delete_test", run=run, baseline_removed=baseline_removed)
    return {"ok": True, "baseline_removed": baseline_removed, "removed": run}


class RepoFixRequest(BaseModel):
    repo_url: str | None = None   # GitHub repo of the website (default: the repo that was tested)
    token: str | None = None      # GitHub token for this action only (default: GITHUB_TOKEN in .env), never saved
    selected_findings: list[str] = Field(default_factory=list, max_length=5)
    proposal_id: str = ""


def _repo_token(req: RepoFixRequest) -> str:
    return (req.token or "").strip() or os.environ.get("GITHUB_TOKEN", "")


@app.get("/api/runs/{run}/repo-fix")
def repo_fix_info(run: str):
    """What the 'Apply fixes to my code' card needs: is there a token in .env, which repo was tested."""
    from backend.agents.setup_agent import is_github
    from backend.config import settings
    d = _run_dir(run)
    summary = _read_json(d / "summary.json", {}) or {}
    fixes = _read_json(d / "fixes.json", [])
    src = summary.get("source") or ""
    from backend.repo_jobs import status
    from backend.repo_proposals import candidates
    return {"has_token": bool(os.environ.get("GITHUB_TOKEN")), "repo_url": src if is_github(src) else "",
            "fixes_with_code": sum(1 for x in fixes if (x.get("code") or {}).get("after")),
            "plan": _read_json(d / "repo_fix_plan.json", None) and True,
            "candidates": [{k: v for k, v in item.items() if k != "finding"} for item in candidates(d)],
            "preparation": status(d), "provider": settings.llm_provider}


@app.post("/api/runs/{run}/repo-fix/prepare")
def repo_fix_prepare(run: str, req: RepoFixRequest, x_agentic_qa: str | None = Header(default=None)):
    """Step 1: download the repo and preview the changes (nothing is sent to GitHub)."""
    from backend.repo_fix import RepoFixError
    from backend.repo_jobs import start
    if x_agentic_qa != "1":
        raise HTTPException(403, "forbidden")
    d = _run_dir(run)
    repo = (req.repo_url or "").strip() or repo_fix_info(run)["repo_url"]
    if not repo:
        raise HTTPException(400, "Enter the GitHub repository of this website.")
    try:
        return start(d, repo, _repo_token(req), req.selected_findings)
    except (RepoFixError, ValueError) as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/runs/{run}/repo-fix/create")
def repo_fix_create(run: str, req: RepoFixRequest, x_agentic_qa: str | None = Header(default=None)):
    """Step 2 (only when the user presses the button): new branch + Pull Request on GitHub."""
    from backend.repo_fix import RepoFixError, create_pr
    if x_agentic_qa != "1":
        raise HTTPException(403, "forbidden")
    d = _run_dir(run)
    try:
        if not req.proposal_id or not (d / ".private" / "repo_fix_plan.json").exists():
            raise RepoFixError("Prepare and review a proposal before creating a pull request.")
        result = create_pr(d, _repo_token(req), run, _read_json(d / "summary.json", None), req.proposal_id)
        _audit("create_pull_request", run=run, pr=result.get("pr_url"))
        return result
    except RepoFixError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # network etc.
        raise HTTPException(502, f"Could not reach GitHub: {str(e)[:200]}") from e


class RecheckRequest(BaseModel):
    failure_ids: list[int]   # the findings (failures.json ids) whose tests run again


rechecks: dict[str, dict] = {}  # run -> {"running", "tests", "error"} (the re-check runs in its own main.py process)


def _recheck_worker(run: str, tests: list[str]) -> None:
    env = os.environ.copy()
    env.update({"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    try:
        _worker_privacy(env)
        p = subprocess.run([sys.executable, "-u", "main.py", "--recheck", run, *tests], cwd=ROOT, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=300 + 240 * len(tests), check=False)
        error = "" if p.returncode == 0 else redact((p.stdout or "")[-400:])
    except subprocess.TimeoutExpired:
        error = "The re-check took too long and was stopped."
    except HTTPException as error_response:
        error = str(error_response.detail)
    rechecks[run] = {"running": False, "tests": tests, "error": error, "finished": time.time()}


@app.post("/api/runs/{run}/recheck")
def start_recheck(run: str, req: RecheckRequest):
    """Re-check after a fix: only the tests of these findings run again, against the website as it is now
    (backend/recheck.py) - fixed / still failing."""
    from backend.recheck import tests_of
    d = _run_dir(run)
    tests = tests_of(d, req.failure_ids)
    if not tests:
        raise HTTPException(400, "Nothing to re-check: only bugs and open questions found by a test can be re-checked.")
    with lock:
        if any(j["status"] == "running" for j in jobs.values()) or any(r.get("running") for r in rechecks.values()):
            raise HTTPException(409, "A test or a re-check is running - try again when it has finished.")
        rechecks[run] = {"running": True, "tests": tests, "started": time.time()}
    threading.Thread(target=_recheck_worker, args=(run, tests), daemon=True).start()
    _audit("recheck", run=run, tests=len(tests))
    return {"started": True, "tests": tests}


@app.get("/api/runs/{run}/recheck")
def get_recheck(run: str):
    d = _run_dir(run)
    return {"status": rechecks.get(run, {"running": False}), "history": _read_json(d / "recheck.json", {})}


# ------------------------------------------------------------------ scheduled runs (TestOptim: daily / hourly runs)
# A test of a website repeated every hour / day / week while this UI is open (schedules.json - local data, never a
# secret: the AI key and a test account come from .env). A time missed because the UI was closed or the PC slept is
# shown as missed - never started later by surprise, in the middle of your own test.
SCHEDULES = ROOT / "schedules.json"
EVERY = ("hourly", "daily", "weekly")
MISSED_AFTER = 30 * 60  # s: started up to 30 min late (a test was running), later = missed


class ScheduleRequest(BaseModel):
    run: str                  # repeat this run's test: its website and its settings (AI, environment, page limit)
    every: str = "daily"      # hourly | daily | weekly
    at: str = "07:00"         # HH:MM (hourly: only the minutes count)
    day: int = 0              # weekly: 0 = Monday ... 6 = Sunday


def _next_time(s: dict, after):
    from datetime import timedelta
    hh, mm = (int(x) for x in s["at"].split(":"))
    t = after.replace(hour=hh if s["every"] != "hourly" else after.hour, minute=mm, second=0, microsecond=0)
    step = timedelta(hours=1) if s["every"] == "hourly" else timedelta(days=1)
    while t <= after or (s["every"] == "weekly" and t.weekday() != s.get("day", 0)):
        t += step
    return t


def _schedules() -> list[dict]:
    return _read_json(SCHEDULES, [])


def _save_schedules(items: list[dict]) -> None:
    SCHEDULES.write_text(json.dumps(items, indent=1), encoding="utf-8")


def _require_run_change(authorization: str | None, x_qa_token: str | None, run: str, action: str = "run.write"):
    """None when the change may proceed. A signed-in principal must own the run."""
    reader = _signed_in_reader(authorization, x_qa_token, action)
    if reader is None or not isinstance(reader, str):
        return reader
    from backend.tenancy_store import assert_run_access
    access = assert_run_access(principal_id=reader, run_id=run, audit=action == "run.write")
    if not access.get("allowed"):
        return JSONResponse({"detail": access.get("reason") or "forbidden"}, status_code=403)
    return None


@app.get("/api/schedules")
def list_schedules(
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    reader = _signed_in_reader(authorization, x_qa_token)
    if isinstance(reader, JSONResponse):
        return reader
    items = _schedules()
    if not reader:
        return items
    from backend.tenancy_store import assert_run_access
    return [item for item in items
            if assert_run_access(
                principal_id=reader, run_id=str(item.get("from_run") or ""), audit=False).get("allowed")]


@app.post("/api/schedules")
def add_schedule(
    req: ScheduleRequest,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    refused = _require_run_change(authorization, x_qa_token, req.run)
    if refused is not None:
        return refused
    from datetime import datetime
    d = _run_dir(req.run)
    if req.every not in EVERY or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", req.at) or not 0 <= req.day <= 6:
        raise HTTPException(400, "Choose hourly, daily or weekly, and a time like 07:00.")
    args = _read_json(d / "run_args.json", {})
    st = args.get("settings") or {}
    if not args.get("source"):
        raise HTTPException(400, "This run can't be repeated (its settings are missing).")
    prov = st.get("llm_provider") or ""
    if KEY_ENV.get(prov) and not os.environ.get(KEY_ENV[prov]):
        raise HTTPException(400, f"A scheduled test runs without you: put the {prov} key in .env as {KEY_ENV[prov]} "
                                 "first (a key typed in the chat is never saved).")
    env_ = st.get("environment") if st.get("environment") in ("test", "staging", "production") else "test"
    s = {"id": f"S{int(time.time())}", "source": args["source"], "every": req.every, "at": req.at, "day": req.day,
         "settings": {"llm_provider": prov or None, "llm_model": st.get("llm_model") or None, "environment": env_,
                      "production_confirmed": env_ == "production", "max_pages": int(st.get("max_pages") or 0),
                      "writes_confirmed": bool(st.get("confirm_writes"))},
         "from_run": req.run, "created": datetime.now().isoformat(timespec="minutes")}
    s["next"] = _next_time(s, datetime.now()).isoformat(timespec="minutes")
    items = [x for x in _schedules() if not (x["source"] == s["source"] and x["every"] == s["every"])] + [s]
    _save_schedules(items)
    _audit("add_schedule", schedule=s["id"], every=s["every"], at=s["at"])
    return s


@app.delete("/api/schedules/{sid}")
def delete_schedule(
    sid: str,
    authorization: str | None = Header(default=None),
    x_qa_token: str | None = Header(default=None, alias="X-QA-Token"),
):
    items = _schedules()
    target = next((item for item in items if item.get("id") == sid), None)
    if target is not None:
        refused = _require_run_change(authorization, x_qa_token, str(target.get("from_run") or ""))
        if refused is not None:
            return refused
    _save_schedules([x for x in items if x["id"] != sid])
    _audit("delete_schedule", schedule=sid)
    return {"ok": True, "deleted": len(items) - len(_schedules())}


def run_due_schedules(now=None) -> list[str]:
    """Start the scheduled tests that are due (one at a time: a running test is never disturbed). Returns the ids."""
    from datetime import datetime
    now, started, changed = now or datetime.now(), [], False
    items = _schedules()
    for s in items:
        due = datetime.fromisoformat(s["next"])
        if due > now:
            continue
        if (now - due).total_seconds() > MISSED_AFTER and not s.get("waiting"):  # (the UI was closed / the PC slept)
            s["missed"], s["next"], changed = s.get("missed", 0) + 1, _next_time(s, now).isoformat(timespec="minutes"), True
            continue
        if started or any(j["status"] == "running" for j in jobs.values()) or any(r.get("running") for r in rechecks.values()):
            if not s.get("waiting"):  # (it was due while the UI was open: it waits for the running test)
                s["waiting"], changed = True, True
            continue
        try:
            job = start_run(RunRequest(source=s["source"], authorized=True, **s.get("settings", {})))
            s.update(last=now.isoformat(timespec="minutes"), last_job=job["id"], last_error="", waiting=False)
            started.append(s["id"])
            _audit("scheduled_run", schedule=s["id"], job=job["id"])
        except HTTPException as e:
            s["last_error"] = str(e.detail)[:200]
        s["next"], changed = _next_time(s, now).isoformat(timespec="minutes"), True
    if changed:
        _save_schedules(items)
    return started


def _scheduler() -> None:
    while True:
        time.sleep(30)
        try:
            run_due_schedules()
        except Exception as e:  # (a broken schedules.json must never stop the UI)
            print(f"  [schedule] {str(e)[:150]}")


class ApproveVisual(BaseModel):
    pages: list[str] | None = None   # the pages' keys (visual.json); none = every page whose look changed


@app.post("/api/visual/{run}/approve")
def approve_visual(run: str, req: ApproveVisual):
    """A person approved the new look of these pages: the next runs compare with it (backend/visual.py)."""
    from backend.visual import approve
    d = _run_dir(run)
    if not (d / "visual.json").exists():
        raise HTTPException(404, "This run has no visual check.")
    n = approve(d, req.pages)
    _audit("approve_visual", run=run, pages=n)
    return {"approved": n, "visual": _read_json(d / "visual.json", None)}


@app.post("/api/hooks/run")
async def hook_run(request: Request):
    """Continuous testing: a deploy script (or a GitHub webhook through a tunnel) starts a run in this UI.
    Needs WEBHOOK_TOKEN in .env, sent as the X-QA-Token header - or GitHub's X-Hub-Signature-256 made with it.
    Body: {"url": "https://..."}; a GitHub 'deployment_status' event tests the deployed address; without an address
    WEBHOOK_TEST_URL is tested. Whoever holds the token may start tests of the websites it names."""
    import hashlib
    import hmac

    from backend.config import settings
    token = settings.webhook_token
    if not token:
        raise HTTPException(404, "Webhooks are off: set WEBHOOK_TOKEN in .env.")
    body = await request.body()
    given = request.headers.get("x-qa-token", "")
    signed = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(token.encode(), body, hashlib.sha256).hexdigest()
    if not ((given and hmac.compare_digest(given, token)) or (signed and hmac.compare_digest(signed, expected))):
        raise HTTPException(401, "Wrong or missing token.")
    try:
        data = json.loads(body or b"{}")
    except ValueError as e:
        raise HTTPException(400, "The body must be JSON.") from e
    event = request.headers.get("x-github-event", "")
    if event == "ping":
        return {"ok": True}
    if event == "deployment_status":
        status = data.get("deployment_status") or {}
        if status.get("state") != "success":
            return {"ok": True, "started": False, "why": f"the deployment is '{status.get('state')}', not 'success'"}
        url = status.get("environment_url") or status.get("target_url")
    else:
        url = data.get("url") if isinstance(data, dict) else None
    url = url or settings.webhook_test_url
    if not url:
        raise HTTPException(400, 'No website address: send {"url": "https://..."} or set WEBHOOK_TEST_URL in .env.')
    job = start_run(RunRequest(source=str(url), authorized=True))
    _audit("webhook_run", job=job["id"], event=event or "hook")
    return {"ok": True, "started": True, "job": job["id"]}


@app.post("/api/shutdown")
def shutdown(x_agentic_qa: str | None = Header(default=None)):
    """Lets a newly started ui.bat replace this (older) server, so double-clicking always loads the latest code.
    Needs the X-Agentic-QA header: browsers can't send that cross-site, so other websites can't call this."""
    if x_agentic_qa != "1":
        raise HTTPException(403, "forbidden")
    if any(j["status"] == "running" for j in jobs.values()) or any(r.get("running") for r in rechecks.values()):
        raise HTTPException(409, "a test is running")
    threading.Timer(0.5, lambda: os._exit(EXIT_REPLACED)).start()
    return {"ok": True}


# ------------------------------------------------------------------ start

EXIT_REPLACED = 3   # ui.bat closes the old window quietly when it gets this exit code


def _port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _take_over(port: int) -> str:
    """An app is already on this port. Returns 'free' (old UI stopped), 'busy' (old UI is running a test) or 'other'."""
    import requests
    try:
        r = requests.post(f"http://127.0.0.1:{port}/api/shutdown", headers={"X-Agentic-QA": "1"}, timeout=3)
    except requests.RequestException:
        return "other"
    if r.status_code == 409:
        return "busy"
    if r.status_code != 200:
        return "other"   # not our server, or an old version without /api/shutdown
    for _ in range(40):  # wait until the old server has let go of the port
        if not _port_in_use(port):
            return "free"
        time.sleep(0.25)
    return "other"



@app.get("/qa-lab")
def qa_lab():
    return FileResponse(STATIC / "qa-lab.html")


@app.get("/api/contracts/schema")
def qa_contract_schema():
    from backend.qa_contracts import Contract
    return Contract.model_json_schema()


@app.post("/api/android/runs/{run}/scenario-draft")
def android_scenario_draft(run: str, payload: dict):
    from .android_scenarios import draft
    from .config import settings
    from .llm import LLMError
    root = _run_dir(run)
    if not (root / ".private/android_config.json").is_file():
        raise HTTPException(400, "Select an Android discovery run.")
    if any(job["status"] == "running" for job in jobs.values()):
        raise HTTPException(409, "Wait for the current run before drafting another scenario.")
    _privacy_provider(settings.llm_provider)
    if settings.llm_provider == "none":
        raise HTTPException(409, "Configure an AI provider first, or use Build a test flow.")
    instructions = payload.get("instructions")
    if not isinstance(instructions, str):
        raise HTTPException(400, "Describe the scenario and its expected result.")
    try:
        return draft(root, instructions)
    except (ValueError, LLMError) as error:
        raise HTTPException(400, "Could not produce a validated scenario draft. Check requirements and observed controls.") from error


CONTRACT_EXAMPLES = {
    'wdio-basic': ('WebdriverIO v2.2 — 10 functional checks', 'webdriverio-expanded-checks.json'),
    'wdio-complete': ('WebdriverIO v2.2 — 33 configured flows', 'webdriverio-complete-checks.json'),
    'controlled-simulations': ('Qpilot fixture — protected flows and safe previews', 'controlled-sandbox-checks.json'),
    'sauce-cart': ('Sauce Labs demo — add product and verify cart', 'sauce-cart-checks.json'),
    'chrome-dropdown': ('Android Chrome — dropdown selection checks', 'chrome-dropdown-checks.json'),
    'ecommerce-web': ('E-commerce web — search and cart (Automation Exercise template)', 'ecommerce-web-contract.json'),
}
WEB_CONTRACT_EXAMPLE_IDS = {'chrome-dropdown', 'ecommerce-web'}


@app.get('/api/contracts/examples')
def contract_examples():
    return {'examples': [{'id': key, 'name': name,
                          'app_mode': 'web' if key in WEB_CONTRACT_EXAMPLE_IDS else 'native'}
                         for key, (name, filename) in CONTRACT_EXAMPLES.items()
                         if (ROOT / 'demo-apps' / filename).is_file()]}


@app.get('/api/contracts/examples/{example_id}')
def contract_example(example_id: str):
    from .qa_contracts import parse_contract
    if example_id not in CONTRACT_EXAMPLES:
        raise HTTPException(404, 'Unknown test-flow example')
    name, filename = CONTRACT_EXAMPLES[example_id]
    path = ROOT / 'demo-apps' / filename
    if not path.is_file():
        raise HTTPException(404, 'This test-flow example is unavailable')
    contract = parse_contract(path.read_text(encoding='utf-8'))
    return {'name': name, 'contract': contract.model_dump(mode='json', exclude_defaults=True, exclude_none=True),
            'note': 'Review these app-specific expectations. Permission flows require separate emulator approval.'}


@app.post("/api/contracts/validate")
def validate_qa_contract(payload: dict):
    """Validate expected behavior without starting a test or resolving private inputs."""
    from backend.qa_contracts import parse_contract
    try:
        contract = parse_contract(payload.get("contract"))
    except ValueError as e:
        # Validation errors must not echo entered credentials or inline secret values.
        raise HTTPException(400, "Invalid test flow. Check actions, unique IDs, expected results and secret references.") from e
    refs = sorted({s.secret_ref for f in contract.flows for s in f.steps if s.secret_ref})
    return {"contract": contract.model_dump(mode="json"),
            "compact_contract": contract.model_dump(mode="json", exclude_defaults=True, exclude_none=True),
            "flows": len(contract.flows), "rules": len(contract.rules), "checks": len(contract.checks),
            "unapproved_flows": [f.id for f in contract.flows if not f.approved],
            "test_environment_approved": contract.test_environment, "required_secret_refs": refs,
            "note": "Expected results are configured requirements. Coverage is established only after execution."}


@app.post("/api/qa/benchmark")
def qa_benchmark(manifest: dict):
    from backend.qa_benchmark import save_showcase
    run_id = "qa_showcase_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    directory = RUNS / run_id
    try:
        result = save_showcase(RUNS, manifest, directory)
    except (ValueError, OSError, KeyError) as error:
        # Keep a failed benchmark request from leaving an empty presentation.
        if directory.is_dir():
            shutil.rmtree(directory)
        raise HTTPException(400, "Cannot benchmark these runs: " + str(error)[:400]) from error
    return {"run": run_id, "report": f"/runs/{run_id}/report.html", "measurement": result}



@app.get("/api/components/{run}")
def component_inventory(run: str, page: str | None = None, offset: int = 0, limit: int = 100, paginate: bool = False):
    if offset < 0 or not 1 <= limit <= 500:
        raise HTTPException(400, "Use a nonnegative offset and a limit between 1 and 500.")
    data = _read_json(_run_dir(run) / "components.json", {})
    if not data:
        return {"pages": [], "total_components": 0, "status": "Inventory not available yet"}
    if page is None:
        catalog = data["pages"][offset:offset + limit] if paginate else data["pages"]
        return {**{k: v for k, v in data.items() if k != "pages"}, "total_pages": len(data["pages"]),
                "offset": offset if paginate else 0, "limit": limit if paginate else len(data["pages"]), "pages": [
            {"url": p["url"], "title": p["title"], "slug": p["slug"], "auth": p["auth"],
             "component_count": len(p["components"]), "states": p["states"], "limits": p["limits"],
             "errors": p["errors"], "uninspected_frames": p["uninspected_frames"]} for p in catalog]}
    selected = next((p for p in data["pages"] if p.get("slug") == page), None)
    if selected is None:
        raise HTTPException(404, "Page inventory not found")
    return {**selected, "components": selected["components"][offset:offset + limit],
            "total": len(selected["components"]), "offset": offset, "limit": limit}


# These read-only views have no optional MCP SDK dependency.
from backend.mcp_api import register_mcp_api  # noqa: E402 - register views after their shared handlers exist

register_mcp_api(app, jobs, lock, _run_dir, _read_json, mcp_presence)
register_privacy_api(app, jobs, lock, mcp_presence,
                     lambda: any(r.get("running") for r in rechecks.values()))

from backend.mcp_prepared import register_prepared_api  # noqa: E402 - uses existing start handlers

register_prepared_api(app, RunRequest, start_run, start_mobile_run, prepare_android_device,
                      AndroidPrepareRequest, _privacy_provider, key_provider, KEY_ENV)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("UI_PORT", "8000"))
    if _port_in_use(port):
        state = _take_over(port)
        if state == "busy":  # don't interrupt a running test: just show it
            print(f"A test is running in the UI that is already open - opening http://127.0.0.1:{port}\n"
                  "NOTE: that UI still runs the code from when it was started. To use the latest version, wait for the\n"
                  "test to finish (or stop it), close the old black window, then double-click ui.bat again.")
            webbrowser.open(f"http://127.0.0.1:{port}")
            sys.exit(0)
        if state == "free":
            print("Replaced the UI that was already open (now running the latest version).")
        else:
            old = port
            port = next((p for p in range(port + 1, port + 20) if not _port_in_use(p)), port + 20)
            print(f"Port {old} is used by another program (or an old UI window - you can close it). Using port {port}.")
    url = f"http://127.0.0.1:{port}"
    print(f"\n  Qpilot UI running at {url}   (close this window to stop it)\n")
    if _schedules():
        print(f"  {len(_schedules())} scheduled test(s): they run while this window is open\n")
    threading.Thread(target=_scheduler, daemon=True).start()  # (scheduled tests: checked every 30 s)
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
