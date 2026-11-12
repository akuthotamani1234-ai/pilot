"""Optional integrations - each one only when it is set in .env; a normal local run needs none of them.

  Slack  SLACK_WEBHOOK_URL: ONE message when a run found significant problems - an application defect at or above
         SLACK_MIN_SEVERITY, or the verdict 'Not Ready': the verdict, the counts, the top defects, where the report is.
  Jira   JIRA_URL + JIRA_EMAIL + JIRA_API_TOKEN + JIRA_PROJECT: one issue per application defect at or above
         JIRA_MIN_SEVERITY (at most JIRA_MAX_ISSUES per run): page, feature, test case, severity, confidence, the steps
         to reproduce, expected / actual, the failure class, the next action, with its screenshot attached. A problem
         an earlier run already sent is not sent again (baseline/<site>/jira.json: problem -> issue key).
Only APPLICATION DEFECTS are sent - never a test-script / automation problem, an inconclusive result or a visual
change. Whatever happens (no network, a wrong token), the run is not affected: the outcome is in integrations.json.

Continuous testing: .github/workflows/blow-ai.yml runs the tester after a push / a deployment (main.py --exit-code
fails the job when the verdict is 'Not Ready'), and POST /api/hooks/run (WEBHOOK_TOKEN) starts a run in the open UI
from a deploy script (backend/server.py).
"""
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

from .agents.change_detection import baseline_path
from .config import settings
from .safety import redact
from .state import QAState

SEV = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEND_CONFIDENCE = ("high", "medium")  # a low-confidence finding is a lead for a person, not an issue for a developer


def _at_least(severity: str, minimum: str) -> bool:
    return SEV.get(severity, 9) <= SEV.get(minimum, 1)


def _url_ok(url: str) -> bool:
    """https only (plain http just to this PC - a test server)."""
    p = urlparse(url)
    return p.scheme == "https" or (p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost"))


def defects(failures: list[dict], minimum: str) -> list[dict]:
    """The application defects worth sending, most severe first."""
    out = [f for f in failures if f.get("category") == "product_defect" and f.get("confidence") in SEND_CONFIDENCE
           and _at_least(f.get("severity", ""), minimum)]
    return sorted(out, key=lambda f: SEV.get(f.get("severity"), 9))


def fingerprint(f: dict) -> str:
    """The same problem in a later run -> the same fingerprint (numbers and addresses left out of its message)."""
    title = (f.get("bug") or {}).get("title") or f.get("test") or ""
    first = (f.get("error") or "").strip().splitlines()[:1]
    error = re.sub(r"\d+", "#", first[0] if first else "")
    path = urlparse(f.get("page_url") or "").path or "/"
    return hashlib.sha1(f"{f.get('category')}|{path}|{title}|{error[:160]}".encode(),
                        usedforsecurity=False).hexdigest()[:16]


def _ci_link() -> str:
    """In GitHub Actions: the page of this workflow run (its report is attached there)."""
    if os.environ.get("GITHUB_RUN_ID") and os.environ.get("GITHUB_REPOSITORY"):
        return (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ['GITHUB_REPOSITORY']}"
                f"/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    return ""


def _title(f: dict) -> str:
    return (f.get("bug") or {}).get("title") or f.get("explanation") or f.get("test") or "Application defect"


# ------------------------------------------------------------------ Slack

def slack_message(state: QAState, found: list[dict]) -> str:
    run_dir = Path(state["run_dir"])
    lines = [f"*Blow AI* tested {state.get('url')}: *{state.get('verdict')}*",
             f"{len(found)} application defect(s) at or above '{settings.slack_min_severity}'"]
    for f in found[:5]:
        lines.append(f"• [{f.get('severity')}] {_title(f)} - {f.get('page_url') or ''}")
    if len(found) > 5:
        lines.append(f"... and {len(found) - 5} more")
    link = _ci_link()
    lines.append(f"Report: {link}" if link else f"Report: {(run_dir / 'report.html').resolve()} (on the PC that ran it)")
    return redact("\n".join(lines))


def send_slack(state: QAState, failures: list[dict]) -> dict:
    found = defects(failures, settings.slack_min_severity)
    if not found and state.get("verdict") != "Not Ready":
        return {"sent": False, "why": f"no application defect at or above '{settings.slack_min_severity}'"}
    if not _url_ok(settings.slack_webhook_url):
        return {"sent": False, "why": "SLACK_WEBHOOK_URL must start with https://"}
    r = requests.post(settings.slack_webhook_url, json={"text": slack_message(state, found)}, timeout=20)
    if r.status_code >= 300:
        return {"sent": False, "why": f"Slack answered HTTP {r.status_code}: {redact(r.text[:150])}"}
    return {"sent": True, "defects": len(found)}


# ------------------------------------------------------------------ Jira

def issue_text(f: dict, state: QAState) -> tuple[str, str]:
    """(summary, description) of one defect - plain text (Jira's wiki markup)."""
    bug = f.get("bug") or {}
    steps = bug.get("steps") or []
    summary = f"[{f.get('severity')}] {_title(f)}"[:240]
    parts = [
        f"*Found by Blow AI* on {state.get('url')} (run {state.get('run_id')})",
        f"*Issue ID:* {fingerprint(f)}",
        f"*Page:* {f.get('page_url') or '-'}",
        f"*Feature:* {bug.get('feature') or '-'}",
        f"*Test case:* {f.get('tc_id') or '-'} ({f.get('test') or '-'})",
        f"*Severity:* {f.get('severity')} · *Confidence:* {f.get('confidence')} · "
        f"*Classification:* {f.get('category_name') or f.get('category')}",
        "*Steps to reproduce:*" + ("".join(f"\n# {s}" for s in steps) if steps else " see the page and the test case"),
        f"*Expected:* {bug.get('expected') or '-'}",
        f"*Actual:* {{noformat}}{bug.get('actual') or f.get('error') or '-'}{{noformat}}",
        f"*Why it is a defect:* {f.get('explanation') or '-'}",
        f"*Next action:* {f.get('next_action') or '-'}",
        "*Evidence:* " + (", ".join(str(x) for x in f.get("evidence") or []) or "-")
        + " (screenshot attached; the trace / video are in the run folder)",
    ]
    link = _ci_link()
    if link:
        parts.append(f"*Run:* {link}")
    return redact(summary), redact("\n".join(parts))


def create_jira_issues(state: QAState, failures: list[dict]) -> dict:
    if not _url_ok(settings.jira_url):
        return {"created": [], "why": "JIRA_URL must start with https://"}
    found = defects(failures, settings.jira_min_severity)
    known_file = baseline_path(state["site_key"]) / "jira.json"
    try:
        known = json.loads(known_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = {}
    s = requests.Session()
    s.auth = (settings.jira_email, settings.jira_api_token)
    s.headers["Accept"] = "application/json"
    created, already, errors = [], [], []
    run_dir = Path(state["run_dir"])
    for f in found:
        fp = fingerprint(f)
        if fp in known:
            already.append(known[fp])
            continue
        if len(created) >= settings.jira_max_issues:
            break
        summary, text = issue_text(f, state)
        r = s.post(f"{settings.jira_url}/rest/api/2/issue", timeout=30, json={"fields": {
            "project": {"key": settings.jira_project}, "summary": summary, "description": text,
            "issuetype": {"name": settings.jira_issue_type}, "labels": ["blow-ai", f"severity-{f.get('severity')}"]}})
        if r.status_code >= 300:
            errors.append(f"HTTP {r.status_code}: {redact(r.text[:200])}")
            if r.status_code in (401, 403, 404):  # wrong token / project / address: every other one fails the same way
                break
            continue
        key = r.json().get("key", "")
        shot = run_dir / f["screenshot"] if f.get("screenshot") else None
        if key and shot and shot.is_file():
            with shot.open("rb") as fh:
                s.post(f"{settings.jira_url}/rest/api/2/issue/{key}/attachments", timeout=60,
                       headers={"X-Atlassian-Token": "no-check"}, files={"file": (shot.name, fh, "image/png")})
        known[fp] = key
        created.append(key)
    if created:
        known_file.parent.mkdir(parents=True, exist_ok=True)
        known_file.write_text(json.dumps(known, indent=1), encoding="utf-8")
    return {"created": created, "already_reported": already, "errors": errors, "defects": len(found)}


# ------------------------------------------------------------------ the last stage of a run

def configured() -> dict:
    from .privacy import runtime_mode
    if runtime_mode() == "local":
        return {"slack": False, "jira": False}
    return {"slack": bool(settings.slack_webhook_url),
            "jira": all((settings.jira_url, settings.jira_email, settings.jira_api_token, settings.jira_project))}


def integrations_agent(state: QAState) -> QAState:
    on = configured()
    if not any(on.values()):
        return {"log": state.get("log", [])}
    failures = state.get("failures", [])
    out = {}
    for name, send in (("slack", send_slack), ("jira", create_jira_issues)):
        if not on[name]:
            continue
        try:
            out[name] = send(state, failures)
        except Exception as e:  # (no network, a wrong address: the run itself is finished and stays as it is)
            out[name] = {"error": redact(str(e).splitlines()[0][:200]) if str(e) else type(e).__name__}
    Path(state["run_dir"], "integrations.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    notes = []
    if "slack" in out:
        notes.append("Slack: message sent" if out["slack"].get("sent") else
                     f"Slack: not sent ({out['slack'].get('why') or out['slack'].get('error')})")
    if "jira" in out:
        j = out["jira"]
        notes.append(f"Jira: {len(j.get('created', []))} issue(s) created"
                     + (f", {len(j['already_reported'])} already reported" if j.get("already_reported") else "")
                     + (f" - errors: {'; '.join(j['errors'][:2])}" if j.get("errors") else "")
                     + (f" - {j['error']}" if j.get("error") else "") + (f" - {j['why']}" if j.get("why") else ""))
    for n in notes:
        print(f"  [integrations] {n}", flush=True)
    return {"log": state.get("log", []) + notes}
