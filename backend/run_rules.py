"""Live Qpilot X rules. Each pipeline stage runs the rules that belong to it.

The product sample is not raised. Payment, delete, and logout stay blocked.
A trend does not replace the verdict of the run it was read from.
"""
import json
import os
from pathlib import Path

from .agent_eval import evaluate, model_change_allowed
from .config import settings
from .data_lifecycle import (
    choose_remote_delete,
    ingest_created,
    load_lifecycle,
    production_environment,
    save_lifecycle,
)
from .dependency_fault import inject_fault
from .env_controls import CONTROLS, action_still_blocked, enable_control
from .journey_map import compare_journey
from .locale_check import check_locale, keep_sample
from .mutation_score import score_planted
from .plugins import review_plugin
from .quality_trends import cluster_runs, keep_verdict
from .replay_pack import make_package, replay
from .schema_diff import diff_specs
from .sessions import RoleBook

ORDER = (
    "sessions",
    "environment",
    "locale",
    "schema",
    "plugins",
    "lifecycle",
    "dependency",
    "replay",
    "mutation",
    "journeys",
    "evaluation",
    "trends",
)


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _store(run_dir: Path, name: str, payload: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    current = _read(run_dir / "qx_live.json")
    if not isinstance(current, dict):
        current = {}
    current["order"] = list(ORDER)
    current[name] = payload
    (run_dir / "qx_live.json").write_text(json.dumps(current, indent=2), encoding="utf-8")
    (run_dir / f"qx_{name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def priority_urls(site_key: str) -> list[str]:
    """Areas the previous runs asked the next crawl to open first."""
    from .my_tests import baseline_folder
    payload = _read(baseline_folder(site_key or "site") / "next_priority.json")
    if isinstance(payload, dict) and isinstance(payload.get("next_priority"), list):
        return [str(item) for item in payload["next_priority"] if item]
    if isinstance(payload, list):
        return [str(item) for item in payload if item]
    return []


def sessions_for(state: dict) -> dict:
    """One session book for this run. Passwords are not stored."""
    run_id = str(state.get("run_id") or Path(state.get("run_dir") or "run").name)
    book = RoleBook(run_id)
    roles = state.get("roles") or {}
    inner = roles.get("roles") if isinstance(roles.get("roles"), dict) else roles
    if not isinstance(inner, dict):
        inner = {}
    for name, info in inner.items():
        if name == "main" or not isinstance(info, dict):
            continue
        book.add_role(str(name), f"vault:{name}")
        pages = info.get("pages") or {}
        if isinstance(pages, dict):
            for url, result in pages.items():
                access = result.get("access") if isinstance(result, dict) else result
                book.record_access(str(name), str(url), str(access).lower() in {"ok", "opened"})
        if str(info.get("login") or "").lower() in {"expired", "session_expired"}:
            book.expire(str(name))
    return book.public()


def _asked(name: str) -> bool:
    """A control runs only when this run asked for it. Being allowed is not the same as being on."""
    return os.getenv(name.upper(), "").strip().lower() in {"1", "true", "yes"}


def environment_for(environment: str) -> dict:
    """Staging may use a control only when this run asked for it. Payment, delete, and logout stay blocked."""
    controls = {}
    for name in sorted(CONTROLS):
        allowed, reason = enable_control(environment, name)
        enabled = allowed and _asked(name)
        controls[name] = {"enabled": enabled, "allowed": allowed, "reason": name if enabled else reason}
    blocked = {}
    for kind in ("pay", "delete", "logout"):
        still, reason = action_still_blocked(kind)
        blocked[kind] = {"blocked": still, "reason": reason}
    return {"environment": environment or "test", "controls": controls, "blocked": blocked}


def locale_for(state: dict) -> dict:
    """Compare a supplied locale and keep the small product sample."""
    run_dir = Path(state.get("run_dir") or ".")
    crawl = state.get("crawl") or {}
    swarm = crawl.get("swarm") or {}
    sample = int(swarm.get("sample") or settings.swarm_sample or 0)
    catalog = sum(len((page.get("itemLinks") or {}).get("links") or []) for page in state.get("app_map") or [])
    kept = keep_sample(sample, catalog or sample)
    payload = _read(run_dir / "locale.json")
    observed = payload.get("observed") if isinstance(payload, dict) and isinstance(payload.get("observed"), dict) else {}
    expected = payload.get("expected") if isinstance(payload, dict) and isinstance(payload.get("expected"), dict) else {}
    if observed or expected:
        result = check_locale(observed, expected)
        result["checked"] = True
    else:
        result = {"checked": False, "ok": True, "checks": []}
    result["sample"] = kept
    result["sample_unchanged"] = True
    return result


def schema_for(state: dict) -> dict:
    """Diff this run's API spec against the last accepted spec before tests trust it."""
    run_dir = Path(state.get("run_dir") or ".")
    current = _read(run_dir / "api_spec.json")
    previous = _read(run_dir / "api_spec_previous.json")
    if previous is None:
        site = str(state.get("site_key") or "")
        if site:
            from .my_tests import baseline_folder
            previous = _read(baseline_folder(site) / "api_spec.json")
    if not isinstance(current, dict) or not isinstance(previous, dict):
        return {"compared": False, "broken": [], "trust_broken": False}
    diff = diff_specs(previous, current)
    diff["compared"] = True
    return diff


def reviewed_plugins(root: Path | None = None) -> list[dict]:
    """Review every plugin. One that turns a lock off is refused."""
    folder = (root or Path(".")) / "plugins"
    if not folder.is_dir():
        return []
    reviewed = []
    for path in sorted(folder.glob("*.json")):
        payload = _read(path)
        if isinstance(payload, dict):
            reviewed.append({"file": path.name, **review_plugin(payload)})
    return reviewed


def plugin_cases(root: Path | None = None) -> list[dict]:
    """Accepted plugin assertions become test cases. Refused plugins add none."""
    cases = []
    for plugin in reviewed_plugins(root):
        if not plugin.get("accepted"):
            continue
        for index, assertion in enumerate(plugin.get("assertions") or []):
            text = str(assertion).strip()
            if not text:
                continue
            cases.append({
                "id": f"plugin_{plugin['file']}_{index}",
                "kind": "plugin",
                "type": "functional",
                "priority": "medium",
                "title": text[:140],
                "expected": text,
                "expected_source": "business_rule",
                "oracle": "business_rule",
                "steps": [f"Check the plugin assertion: {text}"],
                "scenario": text[:180],
                "spec": {"name": plugin["file"]},
                "page": "",
            })
    return cases


def lifecycle_for(state: dict, *, finish: bool = False) -> dict:
    """Prepare each worker's records and persist them for a later confirmed cleanup.

    Finish reloads the durable lifecycle, ingests ``created.jsonl`` tags, and only
    marks cleaned when ``created_jsonl_delete`` (or synthetic-unused proof) confirms.
    """
    run_dir = Path(state.get("run_dir") or ".")
    environment = str(state.get("environment") or settings.environment or "test")
    crawl = state.get("crawl") or {}
    swarm = crawl.get("swarm") or {}
    count = int(swarm.get("workers") or settings.test_workers or 1)
    workers = list(range(1, max(count, 1) + 1))
    if production_environment(environment):
        return {"refused": "production customer data is not used as fixture data", "prepared": [], "cleaned": [],
                "cleanup": {"confirmed": [], "failed": [], "complete": False, "local_only": False}}
    life = load_lifecycle(run_dir, run_id=run_dir.name, environment=environment)
    for worker in workers:
        life.prepare(worker)
    ingested = []
    cleanup = {"confirmed": [], "failed": [], "complete": True, "local_only": False}
    if finish:
        ingested = ingest_created(life, run_dir)
        cleanup = life.cleanup_confirmed(remote_delete=choose_remote_delete(run_dir, state))
    save_lifecycle(run_dir, life)
    prepared = [life.snapshot(worker) for worker in sorted(set(workers) | set(life._by_worker))]
    return {
        "refused": "",
        "prepared": prepared,
        "cleaned": cleanup["confirmed"],
        "cleanup": cleanup,
        "ingested_created": len(ingested),
        "durable": True,
    }


def dependency_for(environment: str) -> dict:
    """A named, permitted dependency can be marked unavailable on test or staging."""
    service = os.getenv("DEPENDENCY_FAULT", "").strip()
    permitted = os.getenv("DEPENDENCY_PERMITTED", "").strip().lower() in {"1", "true", "yes"}
    if not service:
        return {"injected": False, "reason": "no dependency fault was requested"}
    return inject_fault(environment, service, permitted=permitted)


def replay_for(failures: list[dict], environment: str) -> list[dict]:
    """A failure can be replayed only when its package is complete."""
    packages = []
    for failure in failures:
        package = make_package(
            environment=failure.get("environment") or environment or "test",
            build=failure.get("file") or failure.get("build") or "unknown",
            browser=failure.get("browser") or "chromium",
            seed=str(failure.get("nodeid") or failure.get("id") or failure.get("test") or "0"),
            starting_state={"url": failure.get("page_url") or failure.get("url") or ""},
            test_data={"test": failure.get("test") or ""},
            actions=[failure.get("test") or "rerun the failed test"],
            network=failure.get("network") or failure.get("network_notes") or ["recorded"],
            screenshots=[item for item in (failure.get("screenshot"),) if item] or list(failure.get("evidence") or []),
            assertion=(failure.get("error") or failure.get("explanation") or "")[:500],
        )
        packages.append({"id": failure.get("nodeid") or failure.get("id") or "", "replay": replay(package)})
    return packages


def mutation_for(run_dir: Path, failures: list[dict]) -> dict:
    """Score planted defects against the failures this run reported."""
    planted = _read(run_dir / "planted.json")
    if not isinstance(planted, list):
        return {"scored": False, "caught": [], "missed": [], "false_reports": [], "qpilot_defects": []}
    reported = [str(item.get("id") or item.get("tc_id") or "") for item in failures if item.get("id") or item.get("tc_id")]
    score = score_planted([row for row in planted if isinstance(row, dict)], reported)
    score["scored"] = True
    return score


def journeys_for(state: dict) -> list[dict]:
    """Compare one business journey across the surfaces this run recorded."""
    run_dir = Path(state.get("run_dir") or ".")
    supplied = _read(run_dir / "journeys.json")
    if isinstance(supplied, list) and supplied:
        compared = []
        for journey in supplied:
            if not isinstance(journey, dict):
                continue
            steps = journey.get("steps") if isinstance(journey.get("steps"), dict) else {}
            compared.append(compare_journey(
                str(journey.get("id") or "journey"),
                {str(name): [str(step) for step in value] for name, value in steps.items() if isinstance(value, list)},
                must_match=bool(journey.get("must_match")),
            ))
        return compared
    web = [str(page.get("url") or "") for page in (state.get("app_map") or []) if page.get("url")][:40]
    surfaces = {"web": web}
    mobile = _read(run_dir / "mobile_steps.json")
    if isinstance(mobile, list):
        surfaces["android"] = [str(step) for step in mobile]
    if not web and "android" not in surfaces:
        return []
    return [compare_journey("crawl", surfaces, must_match=False)]


def evaluation_for(results: list[dict]) -> dict:
    """Store accuracy, cost, and reliability. A model change waits on this record."""
    tasks = []
    for row in results:
        status = str(row.get("status") or row.get("outcome") or "").lower()
        tasks.append({
            "id": row.get("nodeid") or row.get("test") or row.get("id") or "",
            "expected": "passed",
            "actual": "passed" if status == "passed" else "other",
            "failed": status not in {"passed", "skipped"},
            "unsupported": bool(row.get("unsupported")),
            "cost": float(row.get("cost") or 0),
        })
    scored = evaluate(tasks)
    allowed, reason = model_change_allowed(scored)
    scored["model_change_allowed"] = allowed
    scored["reason"] = reason
    return scored


def trends_for(state: dict, verdict: str, failures: list[dict],
               results: list[dict] | None = None) -> dict:
    """Cluster repeated failures. The verdict of this run stays as it was."""
    run_dir = Path(state.get("run_dir") or ".")
    areas = [str(item.get("category") or item.get("page_url") or "") for item in failures
             if item.get("category") or item.get("page_url")]
    flaky_now = [
        str(row.get("nodeid") or row.get("id") or row.get("test") or "")
        for row in (results or [])
        if row.get("flaky")
    ]
    runs = [{"verdict": verdict, "failures": areas, "flaky": flaky_now}]
    parent = run_dir.parent
    if parent.is_dir():
        for path in sorted(parent.glob("*/summary.json")):
            if path.parent == run_dir:
                continue
            summary = _read(path)
            if isinstance(summary, dict) and isinstance(summary.get("qx_areas"), list):
                prior_flaky = summary.get("flaky") if isinstance(summary.get("flaky"), list) else []
                runs.append({"verdict": summary.get("verdict") or "", "failures": summary.get("qx_areas") or [],
                             "flaky": prior_flaky})
    trends = cluster_runs(runs)
    trends["verdict"] = keep_verdict(verdict, trends)
    site = str(state.get("site_key") or "")
    if site and trends["next_priority"]:
        from .my_tests import baseline_folder
        folder = baseline_folder(site)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "next_priority.json").write_text(
            json.dumps({"next_priority": trends["next_priority"]}, indent=2), encoding="utf-8")
    return trends


def apply_discovery(state: dict) -> dict:
    """Sessions, environment controls, locale, schema, and plugins after the crawl."""
    run_dir = Path(state["run_dir"])
    environment = str(state.get("environment") or settings.environment or "test")
    rules = {
        "sessions": sessions_for(state),
        "environment": environment_for(environment),
        "locale": locale_for(state),
        "schema": schema_for(state),
        "plugins": reviewed_plugins(),
    }
    for name, payload in rules.items():
        _store(run_dir, name, payload if isinstance(payload, dict) else {"items": payload})
    return rules


def apply_execution(state: dict, *, finish: bool = False) -> dict:
    """Worker data and a dependency fault decision before the results are trusted.

    The suite starts with the records still ready. finish=True cleans this run's records after the browsers stop.
    """
    run_dir = Path(state["run_dir"])
    environment = str(state.get("environment") or settings.environment or "test")
    rules = {"lifecycle": lifecycle_for(state, finish=finish), "dependency": dependency_for(environment)}
    for name, payload in rules.items():
        _store(run_dir, name, payload)
    return rules


def apply_analysis(state: dict, failures: list[dict]) -> dict:
    """Replay packages and the mutation score for this run's failures."""
    run_dir = Path(state["run_dir"])
    environment = str(state.get("environment") or settings.environment or "test")
    packages = replay_for(failures, environment)
    replay_payload = {"packages": packages}
    # Persist packages before run_saved so the same call can re-execute complete ones.
    _store(run_dir, "replay", replay_payload)
    from .replay_pack import run_saved
    try:
        executed = run_saved(run_dir, limit=3)
    except Exception as exc:
        executed = {"ran": False, "reason": f"replay execute failed: {type(exc).__name__}", "results": {},
                    "selected": []}
    replay_payload["execution"] = executed
    rules = {
        "replay": replay_payload,
        "mutation": mutation_for(run_dir, failures),
    }
    for name, payload in rules.items():
        _store(run_dir, name, payload)
    return rules


def apply_report(state: dict, *, verdict: str, failures: list[dict], results: list[dict]) -> dict:
    """Journeys, the stored evaluation, and trends that do not rewrite this verdict."""
    run_dir = Path(state["run_dir"])
    rules = {
        "journeys": {"compared": journeys_for(state)},
        "evaluation": evaluation_for(results),
        "trends": trends_for(dict(state, run_dir=str(run_dir)), verdict, failures, results),
    }
    for name, payload in rules.items():
        _store(run_dir, name, payload)
    return rules
