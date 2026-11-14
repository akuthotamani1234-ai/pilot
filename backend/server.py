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
PAGE_RE = re.compile(r"^::page::(\{.*\})$")  # one inspected page (live page cards in the chat)
HUMAN_RE = re.compile(r"^::human::(\{.*\})$")  # the login needs a person (one-time code / CAPTCHA) - and the outcome
RUN_NAME = re.compile(r"^[\w.\-]+$")
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
    mcp_request = request.headers.get("x-blowai-client") == "mcp"
    if mcp_request:
        control = request.url.path in {"/api/mcp/info", "/api/mcp/heartbeat"}
        if request.url.path.startswith("/api/settings/"):
            return JSONResponse({"detail": "Change privacy settings in the Qpilot UI."}, status_code=403)
        if not control and not load_policy().allow_mcp:
            return JSONResponse({"detail": "MCP data access is disabled. Approve your assistant in Privacy settings."},
                                status_code=403)
    host = request.headers.get("host", "")
    host = host[:host.index("]") + 1] if host.startswith("[") and "]" in host else host.split(":")[0]
    if host.lower() not in UI_HOSTS:
        return JSONResponse({"detail": "The Qpilot UI only answers on 127.0.0.1 / localhost."}, status_code=400)
    # (a webhook proves itself with its own token instead - /api/hooks/run)
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.headers.get("x-agentic-qa") != "1" \
            and request.url.path != "/api/hooks/run":
        return JSONResponse({"detail": "forbidden (missing X-Agentic-QA header)"}, status_code=403)
    if request.url.path == "/api/mobile/runs" and request.method == "POST":
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
    """Consequential actions -> logs/audit.jsonl (no passwords, keys or tokens - only what was done)."""
    try:
        AUDIT.parent.mkdir(exist_ok=True)
        with AUDIT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action, **details}) + "\n")
    except OSError:
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
             "execution.js", "repository.js", "workspace.js", "android-workspace.js", "android-scenarios.js")
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
                             headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BlowAI/1.0"})
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


@app.post("/api/runs")
def start_run(req: RunRequest):
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
            env["QA_THOROUGH"] = "1"
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
                        "thorough": apply_thorough,
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
    max_test_cases: int = Form(300),
    allow_rules_fallback: bool = Form(True),
    api_key: str = Form("", max_length=4096),
    test_username: str = Form('', max_length=1024),
    test_password: str = Form('', max_length=4096),
    llm_provider: str | None = Form(None),
    llm_model: str | None = Form(None),
    apk: Annotated[UploadFile | None, File()] = None,
):
    """Start an isolated native Appium run from a private APK upload or installed package."""
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
            "max_interactions": max_interactions,
            "test_all_discovered": test_all_discovered,
            "interaction_timeout_s": interaction_timeout_s, "bot_check_wait_s": bot_check_wait_s,
            "human_wait_s": human_wait_s,
        })
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
    if test_password:
        env['BLOWAI_SECRET_TEST_PASSWORD'] = test_password
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
                         "workflow": workflow, "privacy_mode": privacy["mode"]}
    _audit("start_android_test", job=job_id, run=run_id, app_mode=app_mode, device=device_id,
           package=package_name if app_mode == "installed" else "", authorized=True)
    threading.Thread(target=_reader, args=(jobs[job_id],), daemon=True).start()
    return {**_public(jobs[job_id]), 'exploration_scope': accepted_scope}


@app.get("/api/runs/latest")
def latest_run():
    return _public(jobs[max(jobs)]) if jobs else None


@app.get("/api/android/runs/{run}/coverage")
def android_coverage_dashboard(run: str):
    from .android_coverage import dashboard
    d = _run_dir(run)
    if not (d / ".private/android_config.json").is_file():
        raise HTTPException(400, "This is not an Android run.")
    return dashboard(d)


@app.post("/api/android/runs/{run}/resume")
async def resume_android_run(run: str):
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
                        "target_type": "android", "workflow": "standard", "privacy_mode": privacy["mode"]}
    _audit("resume_android_test", job=job_id, run=run)
    threading.Thread(target=_reader, args=(jobs[job_id],), daemon=True).start()
    return _public(jobs[job_id])


@app.get("/api/runs/{job_id}")
def run_status(job_id: int, since: int = 0, psince: int = 0):
    return _public(_job_or_404(job_id), since, psince)


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
def run_events(job_id: int, after: str = "", limit: int = Query(default=150, ge=1, le=500)):
    from backend.execution_events import read_events
    job = _job_or_404(job_id)
    if not job.get("run"):
        return {"events": [], "cursor": after}
    try:
        return read_events(_run_dir(job["run"]), after, limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/runs/{job_id}/review")
def get_review(job_id: int):
    """The questions a running test asks you (what it can't know: is what it saw correct, is a rule allowed)."""
    job = jobs.get(job_id)
    if not job or not job.get("run"):
        raise HTTPException(404, "no such test")
    req = _read_json(RUNS / job["run"] / "review_request.json", None)
    if not req:
        return {"questions": [], "answered": False}
    return dict(req, answered=(RUNS / job["run"] / "review_answers.json").exists())


@app.post("/api/runs/{job_id}/review")
def post_review(job_id: int, body: ReviewAnswers):
    job = jobs.get(job_id)
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
def stop_run(job_id: int):
    job = _job_or_404(job_id)
    if job["status"] != "running":
        raise HTTPException(400, "not running")
    job["stopping"] = True
    _audit("stop_test", job=job_id, run=job.get("run"))
    run = job.get("run")
    if run and (RUNS / run).is_dir():
        # main.py sees this file, stops at its next safe point and writes the report with what was done so far;
        # if it has not ended after STOP_GRACE_S, it is killed as before
        (RUNS / run / "STOP").write_text("stopped from the web UI", encoding="utf-8")
        threading.Thread(target=_kill_later, args=(job, STOP_GRACE_S), daemon=True).start()
    else:  # (not started far enough to have a run folder: nothing to report yet)
        _kill(job)
    return {"ok": True}


STOP_GRACE_S = 120  # how long a stopped run may take to write its report


def _kill(job: dict) -> None:
    """Kill main.py AND the browser / pytest / app server it started."""
    if job["proc"].poll() is not None:
        return
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(job["proc"].pid)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        os.killpg(os.getpgid(job["proc"].pid), 15)


def _kill_later(job: dict, seconds: float) -> None:
    try:
        job["proc"].wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        _kill(job)


@app.get("/api/history")
def history():
    out = []
    for d in sorted((p for p in RUNS.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
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


@app.get("/api/schedules")
def list_schedules():
    return _schedules()


@app.post("/api/schedules")
def add_schedule(req: ScheduleRequest):
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
def delete_schedule(sid: str):
    items = _schedules()
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
