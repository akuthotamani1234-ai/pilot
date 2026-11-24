"""Read-only command line for the Jira / Confluence requirements connectors.

    python -m backend.atlassian check   --site https://<site>.atlassian.net --email you@company.com
    python -m backend.atlassian connect --id jira-main --site ... --email ... [--types Story,Task]
    python -m backend.atlassian projects --connection jira-main
    python -m backend.atlassian types    --connection jira-main --project QPL
    python -m backend.atlassian sync     --connection jira-main --project QPL [--types Story,Task] [--full]
    python -m backend.atlassian show     --connection jira-main QPL-2
    python -m backend.atlassian analyze  --connection jira-main QPL-2
    python -m backend.atlassian spaces   --connection conf-main
    python -m backend.atlassian sync-space --connection conf-main --space ENG

The API token is NEVER an argument: it is read from the environment variable named by --token-env (default
JIRA_READ_API_TOKEN for Jira, CONFLUENCE_API_TOKEN for Confluence), e.g. a line in .env. A value that looks like a
token is refused as a name. Every command only reads Atlassian; nothing here can create or change an issue or a page
(client.Client refuses any write). Results go to the tenant-scoped store (runs/.requirements.sqlite) and the audit log.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from collections.abc import Callable

from ..safety import redact
from . import analysis, confluence, credentials, jira, store, sync
from .client import AtlassianError, Client
from .models import DEFAULT_TOKEN_REF, ISSUE_KEY, Connection, Product, SourceKind, safe_error

DEFAULT_TENANT = "local"


def legacy_write_status(environ=None) -> dict:
    """Whether the OLDER opt-in defect creation (backend/integrations.py) would write Bug issues to Jira on runs."""
    import os
    env = os.environ if environ is None else environ
    names = ("JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT")
    active = all((env.get(n) or "").strip() for n in names)
    return {"active": active, "project": (env.get("JIRA_PROJECT") or "").strip() if active else "",
            "site": (env.get("JIRA_URL") or "").strip().rstrip("/") if active else ""}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m backend.atlassian", description=__doc__.split("\n\n")[0])
    p.add_argument("--tenant", default=DEFAULT_TENANT, help="tenant id (default: local)")
    p.add_argument("--db", default="", help="requirements database (default: runs/.requirements.sqlite)")
    p.add_argument("--json", action="store_true", help="print JSON")
    p.add_argument("--base-url", default="", help=argparse.SUPPRESS)  # tests: a local mock on 127.0.0.1 only
    sub = p.add_subparsers(dest="command", required=True)

    def site_args(s):
        s.add_argument("--site", required=True, help="https://<your-site>.atlassian.net")
        s.add_argument("--email", required=True, help="the Atlassian account email the API token belongs to")
        s.add_argument("--token-env", default="", help="NAME of the environment variable holding the API token")
        s.add_argument("--product", choices=["jira", "confluence"], default="jira")
        s.add_argument("--types", default="Story", help="work-item types to import, comma separated")

    site_args(sub.add_parser("check", help="test a connection without saving it"))
    c = sub.add_parser("connect", help="test a connection and save it (no token is saved)")
    c.add_argument("--id", required=True)
    site_args(c)
    for name, helptext in (("projects", "list Jira projects"), ("spaces", "list Confluence spaces")):
        sub.add_parser(name, help=helptext).add_argument("--connection", required=True)
    t = sub.add_parser("types", help="work-item types of a project, with counts")
    t.add_argument("--connection", required=True)
    t.add_argument("--project", required=True)
    s = sub.add_parser("sync", help="import (read) the project's work items")
    s.add_argument("--connection", required=True)
    s.add_argument("--project", required=True)
    s.add_argument("--types", default="", help="override the connection's work-item types (comma separated)")
    s.add_argument("--full", action="store_true", help="read everything again (also marks deleted items missing)")
    s.add_argument("--max-pages", type=int, default=None)
    ss = sub.add_parser("sync-space", help="import (read) a Confluence space")
    ss.add_argument("--connection", required=True)
    ss.add_argument("--space", required=True)
    ss.add_argument("--full", action="store_true")
    for name, helptext in (("show", "a stored work item: fields, versions, criteria"),
                           ("analyze", "rules-only analysis of a stored work item (no AI)")):
        x = sub.add_parser(name, help=helptext)
        x.add_argument("--connection", required=True)
        x.add_argument("key")
    return p


def _types(text: str) -> list[str]:
    return [x.strip() for x in (text or "").split(",") if x.strip()]


def _connection_from_args(args, connection_id: str) -> Connection:
    return Connection(id=connection_id, tenant_id=args.tenant, product=args.product, site_url=args.site,
                      email=args.email, token_ref=args.token_env or DEFAULT_TOKEN_REF[args.product],
                      work_item_types=_types(args.types) or ["Story"])


def _client(args, connection: Connection) -> Client:
    return Client(connection, secret=credentials.resolver(args.tenant, allow_env=True), base_url=args.base_url, max_retries=2,
                  max_wait=30.0)


def _test(client: Client, connection: Connection) -> dict:
    if connection.product == Product.jira:
        who = jira.myself(client)
        return {"account": who["display_name"] or who["account_id"], "active": who["active"],
                "projects": len(jira.projects(client))}
    spaces = confluence.spaces(client)
    return {"spaces": len(spaces)}


def _stored(db, args) -> Connection:
    conn = store.get_connection(db, args.tenant, args.connection)
    if conn is None:
        raise LookupError(f"no saved connection {args.connection!r} for tenant {args.tenant!r} (use connect first)")
    return conn


def run(argv: list[str] | None = None, out: Callable[[str], None] = print) -> int:
    args = _parser().parse_args(argv)
    actor = f"cli:{getpass.getuser()}"

    def say(data, text: str = ""):
        out(json.dumps(data, indent=2, default=str) if args.json else (text or json.dumps(data, default=str)))

    db = store.connect(args.db or None)
    try:
        if args.command in ("check", "connect"):
            conn = _connection_from_args(args, args.id if args.command == "connect" else f"{args.product}-check")
            result = {"site": conn.site_url, "product": conn.product.value, "read_only": conn.read_only,
                      "token_env": conn.token_ref, "work_item_types": conn.work_item_types, **_test(_client(args, conn), conn)}
            legacy = legacy_write_status()
            if legacy["active"]:
                result["warning"] = (f"The older defect creation is ON (JIRA_URL / JIRA_EMAIL / JIRA_API_TOKEN / "
                                     f"JIRA_PROJECT are set): Qpilot runs will CREATE Bug issues in "
                                     f"{legacy['project']}. Clear JIRA_PROJECT to keep Jira read-only.")
            if args.command == "connect":
                store.save_connection(db, conn)
                result["saved"] = conn.id
            say(result, "\n".join(f"{k}: {v}" for k, v in result.items()))
            return 0
        conn = _stored(db, args)
        client = _client(args, conn)
        if args.command == "projects":
            rows = jira.projects(client)
            say(rows, "\n".join(f"{p['key']:<12} {p['name']}" for p in rows) or "no projects visible")
        elif args.command == "types":
            types = jira.work_item_types(client, args.project)
            counts = {c["name"]: c["count"] for c in jira.type_counts(client, args.project, types)}
            rows = [{**t, "count": counts.get(t["name"])} for t in types]
            chosen = {x.lower() for x in conn.work_item_types}
            say(rows, "\n".join(f"{'*' if t['name'].lower() in chosen else ' '} {t['name']:<20} "
                                f"{'sub-task' if t['subtask'] else (str(t['count']) + ' items')}" for t in rows)
                + "\n(* = imported by this connection)")
        elif args.command == "sync":
            result = sync.sync_jira(db, conn, client, tenant_id=args.tenant, project=args.project,
                                    issue_types=_types(args.types) or None, actor=actor, full=args.full,
                                    max_pages=args.max_pages)
            say(result, _sync_text(result))
            return 0 if result["status"] in ("complete", "running") else 1
        elif args.command == "spaces":
            rows = confluence.spaces(client)
            say(rows, "\n".join(f"{s.get('key', ''):<12} {s.get('name', '')}" for s in rows) or "no spaces visible")
        elif args.command == "sync-space":
            result = sync.sync_confluence_space(db, conn, client, tenant_id=args.tenant, space_key=args.space,
                                                actor=actor, full=args.full)
            say(result, _sync_text(result))
            return 0 if result["status"] in ("complete", "running") else 1
        elif args.command in ("show", "analyze"):
            key = args.key.strip()
            kind = SourceKind.jira_issue if ISSUE_KEY.match(key) else SourceKind.confluence_page
            root = f"{conn.id}:{kind.value}:{key}"
            item = store.get_source(db, args.tenant, root)
            if not item:
                raise LookupError(f"{key} is not stored for this connection (run sync first)")
            if args.command == "show":
                req = analysis.build_requirement(db, args.tenant, root)
                data = {"key": key, "version": item["source"].version, "present": item["present"],
                        "url": item["source"].url, "fields": item["content"],
                        "versions": [{"version": v["source"].version, "updated": v["source"].updated.isoformat(),
                                      "hash": v["source"].content_hash[:12]}
                                     for v in store.history(db, args.tenant, root)],
                        "criteria": [{"id": c.id, "text": c.text, "locator": c.citations[0].locator,
                                      "automatable": c.automatable} for c in req.criteria]}
                say(data, _show_text(data))
            else:
                result = analysis.analyze(db, args.tenant, root, ai="off", actor=actor)
                say(analysis.summary(result))
        return 0
    except (AtlassianError, LookupError, ValueError, PermissionError) as error:
        out(f"error: {redact(safe_error(error))}")
        return 1
    finally:
        db.close()


def _sync_text(r: dict) -> str:
    lines = [f"status: {r['status']}  new: {r.get('new', 0)}  changed: {r.get('changed', 0)}  "
             f"unchanged: {r.get('unchanged', 0)}  pages read: {r.get('pages', 0)}"]
    if r.get("work_item_types"):
        lines.append("work-item types: " + ", ".join(r["work_item_types"]))
    lines += [f"failed: {x}" for x in r.get("failed_items", [])]
    lines += [f"missing now: {x}" for x in r.get("missing", [])]
    lines += [f"WARNING: {w}" for w in r.get("warnings", [])]
    if r.get("error"):
        lines.append(f"error: {r['error']}")
    return "\n".join(lines)


def _show_text(d: dict) -> str:
    f = d["fields"]
    lines = [f"{d['key']}  {f.get('summary', f.get('title', ''))}",
             f"type: {f.get('type', '')}  status: {f.get('status', '')}  priority: {f.get('priority', '')}  "
             f"version: {d['version']}{'' if d['present'] else '  (no longer in Atlassian)'}",
             f"link: {d['url']}", "", "description:", f.get("description", "") or "(empty)", "",
             f"acceptance criteria ({len(d['criteria'])}):"]
    lines += [f"  {c['id'].split('#')[-1]}: {c['text']}   [{c['locator']}]"
              + ("" if c["automatable"] else "  (not automatable)") for c in d["criteria"]]
    if not d["criteria"]:
        lines.append("  none found - the analysis will report 'missing criteria' (none are invented)")
    return "\n".join(lines)


def main() -> None:
    sys.exit(run())
