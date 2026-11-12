"""One coverage view of several runs (a very large website tested in parts: --section /electronics, --section /books
...):  python main.py --merge <run1> <run2> ...   ->  runs/merged_<time>/report.html + summary.json

The numbers of the runs are ADDED (each run counts its own part); the verdict is the worst one of them; every run's
limits are listed. Nothing is re-measured: it reads each run's summary.json (coverage_card) and crawl.json.
"""
import html
import json
from datetime import datetime
from pathlib import Path

WORST = ["Ready", "Ready with Risks", "Insufficient Evidence", "Not Ready"]


def _read(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _add(total: dict, part: dict) -> dict:
    for k, v in (part or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            total[k] = total.get(k, 0) + v
    return total


def merge_runs(run_dirs: list[Path], runs_dir: Path) -> Path:
    runs, card = [], {"pages": {}, "frames": {}, "features": {}, "tests": {}, "data": {}}
    kinds: dict = {}
    for d in run_dirs:
        s = _read(d / "summary.json", None)
        if not s:
            print(f"  [merge] {d.name}: no summary.json - left out")
            continue
        crawl = _read(d / "crawl.json", {})
        c = s.get("coverage_card") or {}
        for part in card:
            _add(card[part], c.get(part) or {})
        for k in c.get("items") or []:
            t = kinds.setdefault(k["kind"], {"kind": k["kind"], "found": 0, "fully_tested": 0, "smoke": 0})
            _add(t, k)
        runs.append({"run": d.name, "verdict": s.get("verdict"), "section": crawl.get("section") or "/",
                     "pages": s.get("pages"), "limits": c.get("limits_hit") or [], "reason": (s.get("reasons") or [""])[0]})
    verdict = max((r["verdict"] for r in runs if r["verdict"] in WORST), key=WORST.index, default="Insufficient Evidence")
    out = runs_dir / f"merged_{datetime.now():%Y%m%d_%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    summary = {"merged": [r["run"] for r in runs], "verdict": verdict, "runs": runs,
               "coverage_card": dict(card, items=sorted(kinds.values(), key=lambda k: -k["found"]))}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    e = html.escape
    rows = "".join(f"<tr><td>{e(r['run'])}</td><td>{e(r['section'])}</td><td>{e(str(r['verdict']))}</td>"
                   f"<td>{r['pages']}</td><td>{e(', '.join(r['limits']) or '-')}</td></tr>" for r in runs)
    part = lambda name: " · ".join(f"<b>{v}</b> {e(k.replace('_', ' '))}" for k, v in card[name].items())  # noqa: E731
    items = "".join(f"<li>{e(k['kind'])}: {k['fully_tested']} fully tested, {k['smoke']} smoke-checked, "
                    f"{k['found']} found</li>" for k in summary["coverage_card"]["items"][:30])
    (out / "report.html").write_text(f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Blow AI - merged report</title></head>
<body style="font-family:'Segoe UI',system-ui,sans-serif;max-width:980px;margin:32px auto;padding:0 16px;line-height:1.5">
<h1>Merged report: {e(verdict)}</h1><p>{len(runs)} run(s), each testing its own part of the website. The worst verdict
counts; the numbers below are added up.</p>
<table border="1" cellpadding="6" style="border-collapse:collapse"><tr><th>Run</th><th>Part</th><th>Verdict</th>
<th>Pages</th><th>Limits hit</th></tr>{rows}</table>
<h2>Coverage (all runs)</h2><ul><li>Pages: {part('pages')}</li><li>Frames: {part('frames')}</li>
<li>Features: {part('features')}</li><li>Tests: {part('tests')}</li><li>Test data: {part('data')}</li></ul>
{f'<h2>Per page type</h2><ul>{items}</ul>' if items else ''}
<p style="color:#666">Each run's own report has the details: open runs/&lt;run&gt;/report.html.</p></body></html>""",
                                      encoding="utf-8")
    return out
