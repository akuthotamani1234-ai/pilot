"""How much of the website's own JavaScript the run executed (Step 18, Chromium only).

Chromium's precise coverage (CDP Profiler) is taken in the crawler (each page) and in the tests (conftest.py, each
test) and written as the covered byte ranges of every script: runs/<run>/jscov/*.jsonl  {url: {length, covered}}.
The report merges them: "the run executed X % of the website's JavaScript" - and lists the website's OWN scripts
(not other websites') with the lowest coverage: each one points to features the tool may have missed.
On by default on staging and for a site on this PC (JS_COVERAGE=auto); on / off force it. CSS is not measured.
"""
import json
from pathlib import Path
from urllib.parse import urlparse

from .config import settings


def enabled(local_target: bool) -> bool:
    mode = settings.js_coverage
    return mode == "on" or (mode == "auto" and (settings.environment == "staging" or local_target))


def start(page):
    """A CDP session that records precise (block) coverage of this tab - None if the browser can't (not Chromium)."""
    try:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Profiler.enable")
        cdp.send("Profiler.startPreciseCoverage", {"callCount": True, "detailed": True})
        return cdp
    except Exception:
        return None


def covered_ranges(functions: list[dict]) -> tuple[int, list[list[int]]]:
    """(script length, covered [start, end) intervals) from V8's block coverage: the innermost range decides a byte -
    applied outer first, inner last (the order V8 lists them in, sorted by start)."""
    spans = sorted(((r["startOffset"], r["endOffset"], r["count"]) for f in functions for r in f.get("ranges") or []),
                   key=lambda r: (r[0], -(r[1] - r[0])))
    if not spans:
        return 0, []
    length = max(e for _s, e, _c in spans)
    marks = bytearray(length)
    for s, e, c in spans:
        marks[s:e] = (b"\x01" if c > 0 else b"\x00") * (e - s)
    out, pos = [], 0
    while True:  # (the covered stretches, found at C speed - a script can be megabytes long)
        s = marks.find(1, pos)
        if s < 0:
            break
        e = marks.find(0, s)
        e = length if e < 0 else e
        out.append([s, e])
        pos = e
    return length, out


def take(cdp) -> dict:
    """{script url: {"length", "covered"}} since the last take (the counters start again)."""
    if cdp is None:
        return {}
    try:
        res = cdp.send("Profiler.takePreciseCoverage").get("result") or []
    except Exception:
        return {}
    out = {}
    for script in res:
        url = script.get("url") or ""
        if not url.startswith("http"):
            continue
        length, covered = covered_ranges(script.get("functions") or [])
        if length:
            out[url] = {"length": length, "covered": covered}
    return out


def append(run_dir: Path, name: str, data: dict) -> None:
    if not data:
        return
    d = Path(run_dir) / "jscov"
    d.mkdir(exist_ok=True)
    with (d / f"{name}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(data) + "\n")


def _union(a: list[list[int]], b: list[list[int]]) -> list[list[int]]:
    out = []
    for s, e in sorted(a + b):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def summary(run_dir: Path, host: str) -> dict | None:
    """Every take of the run merged: the share of the website's OWN JavaScript that ran, and its least-used scripts."""
    d = Path(run_dir) / "jscov"
    if not d.is_dir():
        return None
    scripts: dict[str, dict] = {}
    for f in d.glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                data = json.loads(line)
            except ValueError:
                continue
            for url, v in data.items():
                s = scripts.setdefault(url.split("#")[0], {"length": v["length"], "covered": []})
                s["length"] = max(s["length"], v["length"])
                s["covered"] = _union(s["covered"], v["covered"])
    own = {u: s for u, s in scripts.items() if urlparse(u).hostname == host}
    total = sum(s["length"] for s in own.values())
    ran = sum(min(e, s["length"]) - st for s in own.values() for st, e in s["covered"])
    per = sorted(({"script": u, "percent": round(100 * sum(e - st for st, e in s["covered"]) / s["length"], 1),
                   "bytes": s["length"]} for u, s in own.items() if s["length"] >= 200), key=lambda x: x["percent"])
    out = {"own_scripts": len(own), "own_bytes": total, "percent": round(100 * ran / total, 1) if total else None,
           "other_scripts": len(scripts) - len(own), "least_used": per[:8]}
    (Path(run_dir) / "jscov.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
