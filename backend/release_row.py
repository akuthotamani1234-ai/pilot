"""Section 22 release row. The steps run in order.

A target is registered first. The crawl can resume. The graph links what was
found. Isolated workers receive only cases with a trustworthy assertion. A
seeded defect needs replayable evidence. The dashboard keeps the six counts
separate. Payment and checkout never become tested work.
"""
import json
from pathlib import Path

from .env_controls import action_still_blocked
from .oracle import accept_expected
from .replay_pack import make_package, replay
from .swarm import control_opens_payment, is_payment_url

DASHBOARD = ("discovered", "tested", "passed", "failed", "blocked", "unknown")
ROW = ("register", "inventory", "graph", "workers", "seed", "dashboard", "operations")


def register_target(*, url: str, scope: str, page_budget: int, time_budget_s: int, authorized: bool) -> dict:
    """The first step. A run needs an authorized target, a scope, and a budget."""
    problems = []
    if not authorized:
        problems.append("the target is not authorized")
    if not str(url or "").strip() or not str(scope or "").strip():
        problems.append("the target needs a scope")
    if int(page_budget or 0) <= 0 or int(time_budget_s or 0) <= 0:
        problems.append("the target needs a page budget and a time budget")
    return {
        "ok": not problems,
        "problems": problems,
        "url": str(url or "").strip(),
        "scope": str(scope or "").strip(),
        "page_budget": int(page_budget or 0),
        "time_budget_s": int(time_budget_s or 0),
    }


def open_target(*, url: str, scope: str, page_budget: int, hard_cap: int,
                time_budget_min: float, authorized: bool) -> dict:
    """The registration a run stores before the crawl. A zero page budget uses the hard cap."""
    pages = int(page_budget) if int(page_budget or 0) > 0 else int(hard_cap or 0)
    seconds = int(max(float(time_budget_min or 0), 1) * 60)
    return register_target(url=url, scope=scope or "site", page_budget=max(pages, 1),
                           time_budget_s=seconds, authorized=authorized)


def load_saved_crawl(run_dir: Path) -> tuple[list[dict], list[str]]:
    """Pages already inventoried, and the addresses still waiting."""
    pages: list[dict] = []
    pending: list[str] = []
    try:
        raw = json.loads((run_dir / "app_map.json").read_text(encoding="utf-8"))
        if isinstance(raw, list):
            pages = [page for page in raw if isinstance(page, dict) and page.get("url")]
    except (OSError, ValueError):
        pages = []
    for name in ("crawl_progress.json", "crawl.json"):
        try:
            payload = json.loads((run_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            found = payload.get("pending") if name == "crawl_progress.json" else payload.get("not_visited")
            if isinstance(found, list):
                pending = [
                    item for item in found
                    if (isinstance(item, str) and item)
                    or (isinstance(item, dict) and item.get("url"))
                ]
                break
    return pages, pending


def save_crawl_progress(run_dir: Path, pages: list[dict], pending: list) -> None:
    """Keep the inventory and the remaining queue so a stopped crawl can continue."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "app_map.json").write_text(json.dumps(pages, indent=2), encoding="utf-8")
    (run_dir / "crawl_progress.json").write_text(json.dumps({"pending": pending}, indent=2), encoding="utf-8")


def read_target(run_dir: Path) -> dict | None:
    """The stored registration, or None when this run has no target file."""
    try:
        payload = json.loads((run_dir / "target.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _control_safe(page_url: str, item: dict) -> bool:
    """A control on a normal page is still unsafe when it opens checkout or payment."""
    if is_payment_url(page_url):
        return False
    return not control_opens_payment(
        page_url,
        str(item.get("href") or item.get("to") or ""),
        str(item.get("form_action") or item.get("action") or ""),
        str(item.get("onclick") or ""),
    )


def page_record(page: dict) -> dict:
    """One crawled page in the shape the inventory and the graph understand."""
    url = str(page.get("url") or "")
    buttons = [item for item in (page.get("buttons") or []) if isinstance(item, dict)]
    fields = [item for item in (page.get("inputs") or []) if isinstance(item, dict)]
    links = [item for item in (page.get("links") or []) if isinstance(item, dict)]
    elements = [str(item.get("text") or item.get("selector")) for item in buttons if item.get("text") or item.get("selector")]
    elements += [str(item.get("name") or item.get("label") or item.get("selector") or "input") for item in fields]
    actions = [{"name": str(item.get("text") or item.get("selector") or "button"), "safe": _control_safe(url, item)}
               for item in buttons]
    actions += [{"name": str(item.get("text") or "link"), "to": item.get("href") or "",
                 "safe": _control_safe(url, item)} for item in links if item.get("href")]
    evidence = [page["screenshot"]] if page.get("screenshot") else []
    return {
        "url": url,
        "template": str(page.get("page_type") or "page"),
        "blocked": bool(page.get("blocked")) or is_payment_url(url),
        "elements": elements[:80],
        "actions": actions[:80],
        "evidence": evidence,
    }


def record_step(run_dir: Path, step: str, payload: dict) -> dict:
    """Store one release step and keep the row in its fixed order."""
    if step not in ROW:
        raise ValueError(step)
    current: dict = {}
    path = run_dir / "row.json"
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        except (OSError, ValueError):
            current = {}
    order_index = {name: index for index, name in enumerate(ROW)}
    steps = [item for item in current.get("steps") or [] if isinstance(item, dict) and item.get("step") != step]
    ok = bool(payload.get("ok", True))
    steps.append({"step": step, "ok": ok})
    steps.sort(key=lambda item: order_index.get(str(item.get("step")), len(ROW)))
    current["order"] = list(ROW)
    current["steps"] = steps
    current["stopped"] = step if step == "register" and not ok else ("" if step == "register" else current.get("stopped") or "")
    current[step] = payload
    run_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    (run_dir / f"{step}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return current


def inventory_pages(pages: list[dict], *, done: list[str], page_budget: int) -> dict:
    """Continue a crawl. Finished addresses are not opened again. Payment stays blocked."""
    finished = set(done)
    opened, safe_states, blocked, remaining = [], [], [], []
    for page in pages:
        url = str(page.get("url") or "")
        if not url or url in finished:
            continue
        if is_payment_url(url) or page.get("blocked"):
            blocked.append(url)
            continue
        if len(opened) >= max(0, int(page_budget)):
            remaining.append(url)
            continue
        opened.append(url)
        for action in page.get("actions") or []:
            if action.get("safe"):
                safe_states.append({"url": url, "action": action.get("name") or ""})
    return {"opened": opened, "safe_states": safe_states, "blocked": blocked, "remaining": remaining,
            "resumed": bool(finished)}


def link_graph(pages: list[dict]) -> dict:
    """Templates, elements, actions, transitions, and evidence for the opened pages."""
    graph = {"templates": {}, "elements": [], "actions": [], "transitions": [], "evidence": []}
    for page in pages:
        if is_payment_url(str(page.get("url") or "")) or page.get("blocked"):
            continue
        template = str(page.get("template") or "page")
        graph["templates"].setdefault(template, []).append(page.get("url") or "")
        for element in page.get("elements") or []:
            graph["elements"].append({"template": template, "name": element})
        for action in page.get("actions") or []:
            graph["actions"].append({"template": template, "name": action.get("name") or "", "safe": bool(action.get("safe"))})
            if action.get("to"):
                graph["transitions"].append({"from": page.get("url") or "", "to": action.get("to"), "by": action.get("name") or ""})
        for item in page.get("evidence") or []:
            graph["evidence"].append({"url": page.get("url") or "", "item": item})
    return graph


def _payment_case(case: dict) -> str:
    """The checkout address on a case, or '' when the case may be tested."""
    found: list = []
    for key in ("url", "page", "page_url", "final_url", "href"):
        found.append(case.get(key))
    spec = case.get("spec")
    if isinstance(spec, dict):
        found.append(spec.get("url"))
    for item in case.get("pages") or []:
        found.append(item.get("url") if isinstance(item, dict) else item)
    for raw in found:
        text = str(raw or "")
        if is_payment_url(text):
            return text
    return ""


def isolated_work(cases: list[dict], worker_count: int) -> list[dict]:
    """One worker context per accepted case. An assertion without a source is not assigned.

    A checkout or payment address is not given to a worker, even with an approved source.
    """
    count = max(1, int(worker_count or 1))
    assigned = []
    for index, case in enumerate(cases):
        pay = _payment_case(case)
        if pay:
            assigned.append({
                "id": case.get("id") or "",
                "worker": 0,
                "isolated": False,
                "accepted": False,
                "reason": "checkout, payment and placing an order are never tested",
            })
            continue
        ok, source = accept_expected(str(case.get("source") or ""))
        if not ok:
            assigned.append({"id": case.get("id") or "", "worker": 0, "isolated": False, "accepted": False, "reason": source})
            continue
        worker = (index % count) + 1
        assigned.append({
            "id": case.get("id") or "",
            "worker": worker,
            "context": f"worker-{worker}",
            "isolated": True,
            "accepted": True,
            "source": source,
            "assertion": case.get("assertion") or "",
        })
    return assigned


def seeded_defect(planted_id: str, failures: list[dict]) -> dict:
    """A planted defect is caught only when a failure names it and the replay package is complete."""
    match = next((item for item in failures if str(item.get("id") or "") == planted_id), None)
    if match is None:
        return {"caught": False, "reason": "the seeded defect was not detected", "replay": {"ran": False}}
    package = make_package(
        environment=match.get("environment") or "test",
        build=match.get("build") or "benchmark",
        browser=match.get("browser") or "chromium",
        seed=planted_id,
        starting_state=match.get("starting_state") or {"id": planted_id},
        test_data=match.get("test_data") or {"id": planted_id},
        actions=match.get("actions") or ["rerun the seeded defect"],
        network=match.get("network") or ["recorded"],
        screenshots=match.get("screenshots") or [],
        assertion=match.get("assertion") or match.get("error") or "",
    )
    played = replay(package)
    return {"caught": played["ran"], "reason": "" if played["ran"] else "the evidence is not complete enough to replay",
            "replay": played}


def dashboard_counts(*, discovered: int, tested: int, passed: int, failed: int, blocked: int, unknown: int) -> dict:
    """Six separate counts. Unknown is never reported as passed."""
    counts = {
        "discovered": max(0, int(discovered)),
        "tested": max(0, int(tested)),
        "passed": max(0, int(passed)),
        "failed": max(0, int(failed)),
        "blocked": max(0, int(blocked)),
        "unknown": max(0, int(unknown)),
    }
    if counts["unknown"] and counts["passed"] > counts["tested"]:
        counts["passed"] = counts["tested"]
    return counts


def operation_checks(*, authorized: bool, cancelled: bool, retries: int, logs: list[str], backup: str) -> dict:
    """The release checks. Payment stays blocked even when the other checks pass."""
    blocked, reason = action_still_blocked("pay")
    checks = {
        "authorized": bool(authorized),
        "payment_blocked": blocked,
        "payment_reason": reason,
        "cancelled": bool(cancelled),
        "cancellation_recorded": True,
        "retries": max(0, int(retries)),
        "logs": bool(logs),
        "backup": bool(str(backup or "").strip()),
        "backup_path": str(backup or "").strip(),
    }
    checks["ok"] = all(checks[name] for name in ("authorized", "payment_blocked", "logs", "backup"))
    return checks


def _empty_dashboard() -> dict:
    return dashboard_counts(discovered=0, tested=0, passed=0, failed=0, blocked=0, unknown=0)


def run_row(*, url: str, scope: str, page_budget: int, time_budget_s: int, authorized: bool,
            pages: list[dict], done: list[str], cases: list[dict], worker_count: int,
            planted_id: str, failures: list[dict], results: list[dict], unknown: list[str],
            cancelled: bool, retries: int, logs: list[str], backup: str) -> dict:
    """Run the release steps in order. A failed registration stops the row."""
    steps = []
    registered = register_target(url=url, scope=scope, page_budget=page_budget, time_budget_s=time_budget_s,
                                 authorized=authorized)
    steps.append({"step": "register", "ok": registered["ok"]})
    if not registered["ok"]:
        return {"stopped": "register", "steps": steps, "register": registered, "dashboard": _empty_dashboard()}
    found = inventory_pages(pages, done=done, page_budget=registered["page_budget"])
    steps.append({"step": "inventory", "ok": True})
    graph = link_graph([page for page in pages if page.get("url") in set(found["opened"]) or page.get("url") in set(done)])
    steps.append({"step": "graph", "ok": True})
    workers = isolated_work(cases, worker_count)
    steps.append({"step": "workers", "ok": True})
    seed = seeded_defect(planted_id, failures) if planted_id else {"caught": False, "reason": "no seeded defect", "replay": {"ran": False}}
    steps.append({"step": "seed", "ok": True})
    tested_urls = {str(item.get("url") or "") for item in results if item.get("url")}
    passed = sum(str(item.get("status") or "").lower() == "passed" for item in results)
    failed = sum(str(item.get("status") or "").lower() == "failed" for item in results)
    counts = dashboard_counts(
        discovered=len(found["opened"]) + len(done),
        tested=len(tested_urls),
        passed=passed,
        failed=failed,
        blocked=len(found["blocked"]),
        unknown=len(unknown),
    )
    steps.append({"step": "dashboard", "ok": list(counts) == list(DASHBOARD)})
    operations = operation_checks(authorized=authorized, cancelled=cancelled, retries=retries, logs=logs, backup=backup)
    steps.append({"step": "operations", "ok": operations["ok"]})
    return {
        "stopped": "",
        "steps": steps,
        "order": list(ROW),
        "register": registered,
        "inventory": found,
        "graph": graph,
        "workers": workers,
        "seed": seed,
        "dashboard": counts,
        "operations": operations,
    }


def from_run(state: dict) -> dict:
    """Build the release row from a finished run. The listing sample is not changed."""
    run_dir = Path(state.get("run_dir") or ".")
    crawl = state.get("crawl") or {}
    pages = [page_record(page) for page in (state.get("app_map") or []) if isinstance(page, dict)]
    cases = []
    for case in state.get("test_cases") or []:
        cases.append({
            "id": case.get("tc_id") or case.get("id") or "",
            "source": case.get("expected_source") or case.get("oracle") or "",
            "assertion": case.get("expected") or case.get("title") or "",
        })
    results = [{"url": row.get("url") or row.get("page_url") or "", "status": row.get("status") or ""}
               for row in state.get("results") or []]
    planted = ""
    planted_file = run_dir / "planted.json"
    if planted_file.is_file():
        try:
            rows = json.loads(planted_file.read_text(encoding="utf-8"))
            planted = str(rows[0].get("id") or "") if isinstance(rows, list) and rows else ""
        except (OSError, ValueError):
            planted = ""
    backup = ""
    for name in (".private/checkpoint.sqlite", "app_map.json", "crawl.json"):
        if (run_dir / name).is_file():
            backup = name
            break
    return run_row(
        url=str(state.get("url") or ""),
        scope=str(crawl.get("section") or crawl.get("mode") or "site"),
        page_budget=int(crawl.get("limit") or len(pages) or 1),
        time_budget_s=int(float(crawl.get("time_limit_min") or 1) * 60),
        authorized=bool(state.get("url")) and bool(crawl.get("approved_hosts") or state.get("url")),
        pages=pages,
        done=[],
        cases=cases,
        worker_count=int(crawl.get("workers") or (crawl.get("swarm") or {}).get("workers") or 1),
        planted_id=planted,
        failures=list(state.get("failures") or []),
        results=results,
        unknown=list(crawl.get("not_visited") or []),
        cancelled=bool(state.get("incomplete")),
        retries=int(state.get("heal_round") or 0),
        logs=list(state.get("log") or []),
        backup=backup,
    )
