"""Agent — Change Detection.

Compares the pages found NOW with the pages saved from the LAST run (the "baseline")
and tells the other agents what changed in the frontend:

    new       -> page did not exist last time        => generate new tests
    changed   -> buttons / inputs / forms changed    => reuse old tests (+ tests for new elements);
                                                        Self-Healing fixes them if they break
    unchanged -> same as before                      => reuse old tests
    removed   -> page existed before, gone now       => reported

The baseline lives in   baseline/<site_key>/   and is updated at the end of every run.
"""
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from ..config import settings
from ..page_status import page_testable
from ..state import QAState


def page_key(url: str) -> str:
    """Path + query (+ #/route of a single-page app), so the same page matches even if host/port
    changes (e.g. localhost:3000 vs :5173)."""
    p = urlparse(url)
    route = p.fragment if p.fragment.startswith("/") else ""
    return (p.path.rstrip("/") or "/") + (f"?{p.query}" if p.query else "") + (f"#{route}" if route else "")


def fingerprint(page: dict) -> dict:
    """The parts of a page we care about when deciding if it 'changed'."""
    return {
        "title": page.get("title") or "",
        "headings": page.get("headings", []),
        "buttons": sorted(f"{b.get('text','')}|{b.get('selector')}" for b in page.get("buttons", [])),
        "inputs": sorted(f"{i.get('label') or i.get('name')}|{i.get('type')}|{i.get('selector')}|req={i.get('required')}"
                         for i in page.get("inputs", [])),
        "forms": sorted(f"{f.get('selector')}|{len(f.get('fields', []))} fields" for f in page.get("forms", [])),
        "links": sorted({page_key(l["href"]) for l in page.get("links", [])}),
    }


def diff_pages(old: dict, new: dict) -> list[str]:
    """Human-readable list of differences between two versions of a page."""
    a, b = fingerprint(old), fingerprint(new)
    out = []
    if a["title"] != b["title"]:
        out.append(f"title: '{a['title']}' -> '{b['title']}'")
    for part in ("headings", "buttons", "inputs", "forms", "links"):
        removed = [x for x in a[part] if x not in b[part]]
        added = [x for x in b[part] if x not in a[part]]
        out += [f"{part[:-1]} removed: {x}" for x in removed[:8]]
        out += [f"{part[:-1]} added: {x}" for x in added[:8]]
    return out


def baseline_path(site_key: str) -> Path:
    return settings.baseline_dir / site_key


def saved_tests(site_key: str) -> dict | None:
    """The test scripts + test cases saved by the last run of this site (for a regression run), or None."""
    b = baseline_path(site_key)
    files = sorted((b / "tests").glob("*.py")) if (b / "tests").is_dir() else []
    if not files or not (b / "test_cases.json").exists():
        return None
    meta = json.loads((b / "meta.json").read_text(encoding="utf-8")) if (b / "meta.json").exists() else {}
    return {"files": files, "cases": json.loads((b / "test_cases.json").read_text(encoding="utf-8")), "meta": meta}


def change_detection_agent(state: QAState) -> QAState:
    bdir = baseline_path(state["site_key"])
    old_map_file = bdir / "app_map.json"
    current = [p for p in state["app_map"] if page_testable(p)]

    if not old_map_file.exists():
        changes = {"first_run": True, "baseline_dir": None, "baseline_origin": "",
                   "page_status": {p["slug"]: "new" for p in current},
                   "baseline_slug": {}, "new": [p["url"] for p in current],
                   "changed": [], "unchanged": [], "removed": []}
        msg = f"Change detection: first run for '{state['site_key']}' - no baseline yet, all {len(current)} pages are new."
    else:
        old_pages = {page_key(p["url"]): p for p in json.loads(old_map_file.read_text(encoding="utf-8"))
                     if page_testable(p)}
        meta = json.loads((bdir / "meta.json").read_text(encoding="utf-8")) if (bdir / "meta.json").exists() else {}
        status, old_slug, new, changed, unchanged = {}, {}, [], [], []
        for p in current:
            old = old_pages.get(page_key(p["url"]))
            if old is None:
                status[p["slug"]] = "new"
                new.append(p["url"])
                continue
            old_slug[p["slug"]] = old["slug"]
            d = diff_pages(old, p)
            if d:
                status[p["slug"]] = "changed"
                changed.append({"url": p["url"], "details": d})
            else:
                status[p["slug"]] = "unchanged"
                unchanged.append(p["url"])
        seen = {page_key(p["url"]) for p in current}
        removed = [old["url"] for k, old in old_pages.items() if k not in seen]
        changes = {"first_run": False, "baseline_dir": str(bdir), "baseline_origin": meta.get("origin", ""),
                   "baseline_date": meta.get("date", ""), "page_status": status, "baseline_slug": old_slug,
                   "new": new, "changed": changed, "unchanged": unchanged, "removed": removed}
        msg = (f"Change detection: {len(new)} new, {len(changed)} changed, {len(unchanged)} unchanged, "
               f"{len(removed)} removed pages (compared with run of {meta.get('date', '?')}).")
        for c in changed:
            print(f"  [changes] CHANGED {c['url']}")
            for line in c["details"]:
                print(f"            - {line}")
        for u in new:
            print(f"  [changes] NEW     {u}")
        for u in removed:
            print(f"  [changes] REMOVED {u}")

    Path(state["run_dir"], "changes.json").write_text(json.dumps(changes, indent=2), encoding="utf-8")
    return {"changes": changes, "log": state.get("log", []) + [msg]}


def save_baseline_agent(state: QAState) -> QAState:
    """Last step: remember this run as the new baseline, so the next run can compare against it."""
    ok_pages = [p for p in state.get("app_map", []) if page_testable(p)]
    if not ok_pages:
        return {"log": state.get("log", []) + ["Baseline: not updated (no pages loaded this run)."]}
    run_dir = Path(state["run_dir"])
    bdir = baseline_path(state["site_key"])
    tests_dir = bdir / "tests"
    if tests_dir.exists():
        for f in tests_dir.glob("*.py"):
            f.unlink()
    tests_dir.mkdir(parents=True, exist_ok=True)

    for f in (run_dir / "generated_tests").glob("*.py"):  # test files + the steps_*.py they import
        if f.name != "conftest.py":  # (the sandbox fixtures always come fresh from backend/templates)
            (tests_dir / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    (bdir / "app_map.json").write_text(json.dumps(state["app_map"], indent=2), encoding="utf-8")
    # the rule questions of this run ("... Is that allowed?"): the next run's review asks them (backend/review.py)
    questions = [{"tc_id": f.get("tc_id"), "question": re.sub(r"\s*\([^)]*\)\s*$", "", f.get("explanation") or "")}
                 for f in state.get("failures", []) if f.get("category") == "rule_violation" and f.get("tc_id")]
    (bdir / "open_questions.json").write_text(json.dumps(questions, indent=2), encoding="utf-8")
    (bdir / "test_cases.json").write_text(json.dumps(state.get("test_cases", []), indent=2), encoding="utf-8")
    m = urlparse(state["url"])
    (bdir / "meta.json").write_text(json.dumps({
        "origin": f"{m.scheme}://{m.netloc}", "source": state.get("source"),
        "run_id": state["run_id"], "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }, indent=2), encoding="utf-8")
    from ..visual import keep_new_looks  # the look of the pages seen for the first time (a changed look waits for you)
    looks = keep_new_looks(run_dir, state["site_key"])
    return {"log": state.get("log", []) + [f"Baseline: saved to {bdir} (next run compares against this one)."
                                           + (f" The look of {looks} new page(s) was added." if looks else "")]}
