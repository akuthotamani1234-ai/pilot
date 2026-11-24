"""Milestone 4: live READ-ONLY acceptance against a real Jira Cloud site (opt-in, never part of the offline suite).

On your own computer (token in .env as JIRA_READ_API_TOKEN, never on the command line):

    QPILOT_LIVE_JIRA=1 QPILOT_JIRA_EMAIL=you@company.com python -m pytest -m live tests/test_live_jira_acceptance.py -s

In a Claude cloud session the token is a network secret of the environment (Basic: email + API token) that the proxy
adds to requests for the site; JIRA_READ_API_TOKEN may then hold any placeholder.

Settings (environment): QPILOT_JIRA_SITE (default the QPL site below), QPILOT_JIRA_PROJECT (QPL),
QPILOT_JIRA_EXPECTED ("QPL-2=User Login Functionality;QPL-3=..."), QPILOT_JIRA_EMAIL.

What it proves, with evidence written to runs/live_jira/<time>/ (report.json and report.md, no secrets):
  the account and project are reachable; the project's REAL work-item types and counts (nothing assumed to be a
  Story); every expected work item is imported with its key, type, status, summary and description; the acceptance
  criteria found in each, with their source locator and quote; version 1 on import, and a second (incremental) and a
  targeted import create no new version and no duplicate; and every request was a read (GET or a read-only search
  POST) to this one site. Nothing in Jira is created or changed. If the site cannot be reached or the credential is
  refused, the test is reported as BLOCKED (skipped with the reason), never as passed.
"""
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
SITE = os.environ.get("QPILOT_JIRA_SITE", "https://aimaniforall1234-1795449805793.atlassian.net").rstrip("/")
PROJECT = os.environ.get("QPILOT_JIRA_PROJECT", "QPL")
EXPECTED = dict(x.split("=", 1) for x in os.environ.get(
    "QPILOT_JIRA_EXPECTED", "QPL-2=User Login Functionality;QPL-3=Product Browsing and Sorting;"
    "QPL-4=Shopping Cart Management;QPL-5=Checkout Functionality;QPL-6=Order Summary Verification").split(";") if x)

pytestmark = [pytest.mark.live, pytest.mark.slow,
              pytest.mark.skipif(os.environ.get("QPILOT_LIVE_JIRA") != "1", reason="live test: set QPILOT_LIVE_JIRA=1")]


class RecordingSession(requests.Session):
    """Records method, host, path and status of every request (never headers or bodies)."""

    def __init__(self):
        super().__init__()
        self.log: list[dict] = []

    def request(self, method, url, *args, **kwargs):
        r = super().request(method, url, *args, **kwargs)
        u = urlparse(url)
        self.log.append({"method": method, "host": u.hostname, "path": u.path, "status": r.status_code})
        return r


def test_live_read_only_import_of_the_qpl_project(tmp_path):
    from backend import audit_store
    from backend.atlassian import analysis as an, jira, store, sync
    from backend.atlassian.client import READ_POSTS, AtlassianError, Client
    from backend.atlassian.models import Connection, ImportFilter

    email = os.environ.get("QPILOT_JIRA_EMAIL", "")
    if not email:
        pytest.skip("BLOCKED: set QPILOT_JIRA_EMAIL to the account the API token belongs to")
    os.environ.setdefault("JIRA_READ_API_TOKEN", "placeholder-replaced-by-the-proxy")
    audit_store.DEFAULT_DB = tmp_path / "audit.sqlite"
    conn = Connection(id="jira-live", tenant_id="local", product="jira", site_url=SITE, email=email,
                      token_ref="JIRA_READ_API_TOKEN")
    session = RecordingSession()
    # (QPILOT_JIRA_REHEARSAL_URL: a local mock on 127.0.0.1 only, to rehearse this test; the client refuses others)
    client = Client(conn, session=session, max_retries=3, max_wait=30.0,
                    base_url=os.environ.get("QPILOT_JIRA_REHEARSAL_URL", ""))
    db = store.connect(tmp_path / "req.sqlite")
    store.save_connection(db, conn)
    report: dict = {"site": SITE, "project": PROJECT, "started_at": datetime.now(UTC).isoformat(), "checks": []}

    def check(name, ok, detail=""):
        report["checks"].append({"check": name, "ok": bool(ok), "detail": detail})

    try:
        who = jira.myself(client)
    except AtlassianError as error:
        pytest.skip(f"BLOCKED: {error.kind}: the site or the credential is not usable here ({error})")
    report["account"] = who["display_name"]
    check("account reachable", who["active"], who["display_name"])

    projects = {p["key"]: p["name"] for p in jira.projects(client)}
    check(f"project {PROJECT} visible", PROJECT in projects, projects.get(PROJECT, ""))
    assert PROJECT in projects, f"{PROJECT} is not visible to this account: {sorted(projects)}"

    types = jira.work_item_types(client, PROJECT)
    counts = jira.type_counts(client, PROJECT, types)
    report["work_item_types"] = [{**t, "count": next((c["count"] for c in counts if c["name"] == t["name"]), None)}
                                 for t in types]
    used = [c["name"] for c in counts if c["count"]]
    check("work-item types discovered", types, ", ".join(f"{c['name']} ({c['count']})" for c in counts))
    assert used, f"{PROJECT} has no work items this account can see"

    preview = sync.preview(db, conn, client, tenant_id="local", filters=ImportFilter(project=PROJECT, types=used),
                           limit=100)
    report["preview"] = {"estimated_total": preview["estimated_total"], "counts": preview["counts"],
                         "keys": [i["key"] for i in preview["items"]]}
    check("preview stores nothing", not store.list_sources(db, "local"))

    first = sync.run_import(db, conn, client, tenant_id="local", mode="full",
                            filters=ImportFilter(project=PROJECT, types=used))
    report["import"] = {k: first.get(k) for k in ("status", "new", "changed", "unchanged", "warnings", "failed_items",
                                                  "missing", "duration_s", "criteria_extracted", "new_keys")}
    check("full import complete", first["status"] == "complete", first.get("error", ""))
    assert first["status"] == "complete", first

    items = []
    for key, summary in EXPECTED.items():
        row = store.get_source(db, "local", f"jira-live:jira_issue:{key}")
        if not row:
            check(f"{key} imported", False, "not found among the imported work items")
            items.append({"key": key, "imported": False})
            continue
        story, src = row["content"], row["source"]
        req = an.build_requirement(db, "local", src.key)
        items.append({"key": key, "imported": True, "type": story["type"], "status": story["status"],
                      "summary": story["summary"], "expected_summary": summary,
                      "summary_matches": story["summary"].strip().lower() == summary.strip().lower(),
                      "description_chars": len(story["description"]), "version": src.version,
                      "content_hash": src.content_hash[:16], "url": src.url,
                      "acceptance_field": story["acceptance_field"],
                      "criteria": [{"id": c.id, "text": c.text, "locator": c.citations[0].locator,
                                    "quote": c.citations[0].quote, "automatable": c.automatable}
                                   for c in req.criteria]})
        check(f"{key} imported", True, f"{story['type']} · {story['status']} · {story['summary']}")
        check(f"{key} summary is '{summary}'", items[-1]["summary_matches"], story["summary"])
        check(f"{key} has a description", story["description"].strip(), f"{len(story['description'])} chars")
        check(f"{key} version 1", src.version == 1, f"v{src.version}")
        check(f"{key} acceptance criteria found", req.criteria, f"{len(req.criteria)} criteria")
    report["items"] = items

    again = sync.run_import(db, conn, client, tenant_id="local", mode="incremental",
                            filters=ImportFilter(project=PROJECT, types=used))
    check("second import: nothing new or changed", again["new"] == 0 and again["changed"] == 0,
          f"new {again['new']}, changed {again['changed']}, unchanged {again['unchanged']}")
    targeted = sync.run_import(db, conn, client, tenant_id="local", mode="items", keys=list(EXPECTED))
    check("targeted import of the expected keys: no new version", targeted["new"] == 0 and targeted["changed"] == 0,
          f"unchanged {targeted['unchanged']}, inaccessible {targeted['inaccessible']}")
    versions = {k: [v["source"].version for v in store.history(db, "local", f"jira-live:jira_issue:{k}")]
                for k in EXPECTED}
    check("no duplicate versions", all(v in ([1], []) for v in versions.values()), json.dumps(versions))

    reads_only = all(r["method"] == "GET" or (r["method"] == "POST" and r["path"] in READ_POSTS) for r in session.log)
    site_host = urlparse(os.environ.get("QPILOT_JIRA_REHEARSAL_URL") or SITE).hostname
    one_site = {r["host"] for r in session.log} == {site_host}
    report["requests"] = {"total": len(session.log), "methods": sorted({r["method"] for r in session.log}),
                          "paths": sorted({r["path"] for r in session.log}), "hosts": sorted({r["host"] for r in session.log})}
    check("only reads (GET / read-only search POST)", reads_only)
    check("only this site was contacted", one_site, ", ".join(report["requests"]["hosts"]))
    report["finished_at"] = datetime.now(UTC).isoformat()

    out = ROOT / "runs" / ("live_jira_rehearsal" if os.environ.get("QPILOT_JIRA_REHEARSAL_URL") else "live_jira") \
        / datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    rehearsal = bool(os.environ.get("QPILOT_JIRA_REHEARSAL_URL"))
    report["rehearsal"] = rehearsal
    title = (f"# REHEARSAL against a local mock - NOT live evidence ({PROJECT})" if rehearsal
             else f"# Live Jira acceptance: {PROJECT} on {SITE}")
    lines = [title, "", f"Account: {report['account']}  ",
             f"Started {report['started_at']}, finished {report['finished_at']}", "", "## Checks", ""]
    lines += [f"- {'PASS' if c['ok'] else 'FAIL'} {c['check']}{': ' + str(c['detail']) if c['detail'] else ''}"
              for c in report["checks"]]
    lines += ["", "## Work-item types", ""] + [f"- {t['name']}: {t['count']}" + (" (sub-task)" if t["subtask"] else "")
                                               for t in report["work_item_types"]]
    for it in items:
        lines += ["", f"## {it['key']}", ""]
        if not it["imported"]:
            lines.append("Not imported.")
            continue
        lines += [f"{it['type']} · {it['status']} · {it['summary']} · v{it['version']} · {it['url']}", "",
                  f"Description: {it['description_chars']} characters; acceptance criteria: {len(it['criteria'])}", ""]
        lines += [f"- {c['id'].split('#')[1]}: {c['text']}  _(from {c['locator']})_" for c in it["criteria"]]
    lines += ["", f"Requests: {report['requests']['total']}, methods {report['requests']['methods']}, "
                  f"hosts {report['requests']['hosts']}"]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nEvidence: {out / 'report.md'}")
    db.close()

    failed = [c for c in report["checks"] if not c["ok"]]
    assert reads_only and one_site
    assert not failed, "\n".join(f"{c['check']}: {c['detail']}" for c in failed)
