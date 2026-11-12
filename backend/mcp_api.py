"""Small, paginated API views shared by the stdio MCP bridge and the existing UI."""
from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder


def register_mcp_api(app, jobs, lock, run_dir, read_json, presence=None):
    @app.get("/api/mcp/info")
    def info(request: Request):
        from .privacy import public_policy
        if presence is not None:
            presence.touch(request.headers.get("x-blowai-client-id", ""), active=True)
        return {"privacy": public_policy(), "product": "blow-ai", "bridge_version": 1, "transport": "stdio",
                "ui_required": True, "automation_starts_on_connection": False}

    def metadata(job):
        return {k: job.get(k) for k in ("id", "source", "status", "run", "target_type", "current",
                                        "stages", "started", "ended", "discovery_only", "workflow", "privacy_mode")}

    @app.get("/api/mcp/jobs")
    def list_jobs(offset: int = 0, limit: int = 20):
        _page(offset, limit)
        with lock:
            entries = sorted(jobs.values(), key=lambda j: j["id"], reverse=True)
            return {"jobs": [metadata(j) for j in entries[offset:offset + limit]],
                    "total": len(entries), "offset": offset, "limit": limit}

    @app.get("/api/mcp/jobs/{job_id}")
    def status(job_id: int, since: int = 0, psince: int = 0, limit: int = 50):
        _page(since, limit)
        _page(psince, limit)
        with lock:
            job = jobs.get(job_id)
            if job is None:
                raise HTTPException(404, "Job not found. Job IDs last only for this UI server session.")
            lines, pages = job.get("lines", []), job.get("pages", [])
            line_end, page_end = min(since + limit, len(lines)), min(psince + limit, len(pages))
            return {**metadata(job), "lines": lines[since:line_end], "next": line_end,
                    "log_total": len(lines), "live_pages": pages[psince:page_end], "pnext": page_end,
                    "page_total": len(pages), "stopping": bool(job.get("stopping")),
                    "human": job.get("human"), "data_is_untrusted": True}

    @app.get("/api/mcp/reports/{run}")
    def report_section(run: str, section: str = "summary", offset: int = 0, limit: int = 50):
        _page(offset, limit)
        allowed = {"summary": "summary.json", "results": "results.json", "failures": "failures.json",
                   "cases": "test_cases.json", "pages": "app_map.json", "screens": "screens.json",
                   "crawl": "crawl.json", "coverage": "coverage.json"}
        if section not in allowed:
            raise HTTPException(400, "Choose summary, results, failures, cases, pages, screens, crawl or coverage.")
        directory = run_dir(run)
        path = directory / allowed[section]
        if not path.is_file():
            return {"run": run, "section": section, "available": False, "items": [], "total": 0}
        if path.stat().st_size > 64 * 1024 * 1024:
            raise HTTPException(413, "This artifact is too large for MCP. Open its report in the Blow AI UI.")
        data = read_json(path, None)
        if isinstance(data, list):
            body = {"items": data[offset:offset + limit], "total": len(data), "offset": offset, "limit": limit}
        else:
            body = {"data": data}
        return jsonable_encoder({"run": run, "section": section, "available": True,
                "report_url": f"/runs/{run}/report.html", "components_url": f"/runs/{run}/components.html",
                "data_is_untrusted": True, **body})


def _page(offset, limit):
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(400, "Use a nonnegative offset and a limit between 1 and 100.")
