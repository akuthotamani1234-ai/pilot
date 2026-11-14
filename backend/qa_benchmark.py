"""Known-truth measurement and repeatability evidence across web and Android runs.

These numbers apply ONLY to the supplied known-truth cases. They are not overall product accuracy
and must never be published as a site-wide or app-wide accuracy percentage.
"""

import argparse
import html
import json
import os
import platform
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from .qa_contracts import Model


class Group(Model):
    name: str = Field(min_length=1, max_length=100)
    runs: list[str] = Field(min_length=1, max_length=30)
    expected: dict[str, str] = Field(min_length=1, max_length=300)


class Manifest(Model):
    groups: list[Group] = Field(min_length=1, max_length=30)


def run_path(root, name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}", name):
        raise ValueError("Use run IDs, not filesystem paths")
    path = (Path(root) / name).resolve(strict=True)
    path.relative_to(Path(root).resolve())
    return path


def measure(root, value):
    manifest = Manifest.model_validate(value)
    if sum(len(group.runs) * len(group.expected) for group in manifest.groups) > 5000:
        raise ValueError("A benchmark may contain at most 5000 run/case expectations")
    counts = Counter(tp=0, fp=0, tn=0, fn=0, unanswered_positive=0, unanswered_negative=0)
    rows, instability = [], []
    for group in manifest.groups:
        outcomes = defaultdict(list)
        if any(v not in ("passed", "failed") for v in group.expected.values()):
            raise ValueError("Known outcomes must be passed (clean) or failed (known defect)")
        for run in group.runs:
            directory = run_path(root, run)
            results = json.loads((directory / "results.json").read_text(encoding="utf-8"))
            by_id = defaultdict(list)
            for result in results:
                by_id[result.get("id") or result.get("test", "").removeprefix("test_")].append(result)
            for case_id, expected in group.expected.items():
                hits = by_id.get(case_id, [])
                assertions = [
                    r for r in hits if r.get("outcome") == "failed" and
                    r.get("exception_type") in ("AssertionError", "AppCrash", "AppNotResponding")
                ]
                actual = (
                    "failed"
                    if assertions
                    else "passed"
                    if hits and all(r.get("outcome") == "passed" and r.get("checks", 1) > 0 for r in hits)
                    else "unanswered"
                )
                category = (
                    ("tp" if actual == "failed" else "fn" if actual == "passed" else "unanswered_positive")
                    if expected == "failed"
                    else ("fp" if actual == "failed" else "tn" if actual == "passed" else "unanswered_negative")
                )
                counts[category] += 1
                outcomes[case_id].append(actual)
                rows.append(
                    {
                        "group": group.name,
                        "run": run,
                        "case_id": case_id,
                        "expected": expected,
                        "actual": actual,
                        "classification": category,
                    }
                )
        for case_id, observed in outcomes.items():
            if len(set(observed)) > 1:
                instability.append({"group": group.name, "case_id": case_id, "outcomes": observed})

    def ratio(top, bottom):
        return round(top / bottom, 4) if bottom else None

    return {
        "counts": dict(counts),
        "precision": ratio(counts["tp"], counts["tp"] + counts["fp"]),
        "recall": ratio(counts["tp"], counts["tp"] + counts["fn"] + counts["unanswered_positive"]),
        "answered_coverage": ratio(counts["tp"] + counts["tn"] + counts["fp"] + counts["fn"], sum(counts.values())),
        "missed_defects": counts["fn"] + counts["unanswered_positive"],
        "unstable_cases": instability,
        "rows": rows,
        "overall_accuracy_percent": None,  # never invented; known-truth metrics above are not site/app accuracy
        "scope": "Only the supplied known-truth cases and repeated conditions; not general product accuracy.",
        "metric_labels": {
            "precision": "Known-truth defect precision (TP/(TP+FP)). Not overall product accuracy.",
            "recall": ("Known-truth known-defect recall (TP/(TP+FN+unanswered positives)). "
                       "Unanswered positives reduce recall. Not overall accuracy."),
            "answered_coverage": ("Share of known-truth expectations answered with pass or fail. "
                                  "Not site/app coverage and not overall accuracy."),
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "runs_root": str(Path(root).resolve()),
            "measured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }


def save_showcase(root, manifest, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result = measure(root, manifest)
    (output / "benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    esc = lambda value: html.escape(str(value), quote=True)  # noqa: E731
    rows = []
    for row in result["rows"]:
        link = Path(os.path.relpath(run_path(root, row["run"]) / "report.html", output)).as_posix()
        rows.append(
            "<tr><td>"
            + esc(row["group"])
            + '</td><td><a href="'
            + esc(link)
            + '">'
            + esc(row["run"])
            + "</a></td><td>"
            + esc(row["case_id"])
            + "</td><td>"
            + esc(row["expected"])
            + "</td><td>"
            + esc(row["actual"])
            + "</td></tr>"
        )

    def percentage(value):
        return "Not measured" if value is None else f"{value * 100:.1f}%"

    env = result["environment"]
    document = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qpilot | QA evidence</title><style>
body{margin:0;background:#f0f3fa;color:#17243d;font:16px/1.6 system-ui}main{max-width:1180px;margin:auto;padding:30px}header{background:#152442;color:white;padding:30px;border-radius:18px}section{background:white;padding:24px;border-radius:16px;margin:20px 0}.cards{display:flex;gap:16px;flex-wrap:wrap}.cards article{background:white;border:1px solid #dce4f2;padding:20px;flex:1;border-radius:12px}.cards strong{display:block;font-size:28px}.cards span{display:block;color:#5b6b86;font-size:13px;margin-top:6px}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:12px;border-bottom:1px solid #ddd}a{color:#4f46cb}.scroll{overflow:auto}code{overflow-wrap:anywhere}</style><main><header><h1>QA results you can verify</h1><p>Compare clean and known-defect runs. Inspect the assertions, screenshots and unchanged recovery evidence. These cards are known-truth metrics only — not overall product accuracy.</p></header><div class="cards"><article><strong>PRECISION</strong><span>Known-truth defect precision</span></article><article><strong>RECALL</strong><span>Known-defect recall (unanswered positives reduce it)</span></article><article><strong>COVERAGE</strong><span>Answered known-truth expectations (not site coverage)</span></article><article><strong>UNSTABLE</strong><span>Unstable repeated cases</span></article></div><section><h2>Known-truth execution evidence</h2><div class="scroll"><table><tr><th>Condition</th><th>Actual run</th><th>Case</th><th>Expected</th><th>Observed</th></tr>ROWS</table></div></section><section><h2>Measurement scope</h2><p>SCOPE</p><p>Overall product accuracy is not measured here (overall_accuracy_percent remains unset). Infrastructure failures, blocked flows and missing results are unanswered; they never count as true positives or clean passes. Missed known defects include unanswered positive cases. Flakiness is compared only within the same named condition.</p><p>Environment: Python ENV_PYTHON on ENV_PLATFORM; runs root <code>ENV_ROOT</code>; measured at ENV_WHEN (UTC).</p><p><a href="benchmark.json">Download measurements and classifications</a></p></section></main></html>"""
    for key, value in {
        "PRECISION": percentage(result["precision"]),
        "RECALL": percentage(result["recall"]),
        "COVERAGE": percentage(result["answered_coverage"]),
        "UNSTABLE": len(result["unstable_cases"]),
        "ROWS": "".join(rows),
        "SCOPE": esc(result["scope"]),
        "ENV_PYTHON": esc(env["python"]),
        "ENV_PLATFORM": esc(env["platform"]),
        "ENV_ROOT": esc(env["runs_root"]),
        "ENV_WHEN": esc(env["measured_at"]),
    }.items():
        document = document.replace(key, str(value))
    (output / "report.html").write_text(document, encoding="utf-8")
    return result


def repeat_android(config_file, repeats, root):
    import shutil
    import sys
    from datetime import datetime

    from .android_pipeline import _run_mobile_process
    from .android_runner import _read_config

    config, _ = _read_config(Path(config_file))
    if not 1 <= repeats <= 10:
        raise ValueError("Repeats must be between 1 and 10")
    ids = []
    for index in range(repeats):
        run_id = "repeat_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(index + 1)
        directory = Path(root) / run_id
        private = directory / ".private"
        private.mkdir(parents=True)
        current = dict(config)
        if current["app_mode"] == "apk":
            shutil.copyfile(current["apk_path"], private / "app.apk")
            current["apk_path"] = str((private / "app.apk").resolve())
        path = private / "android_config.json"
        path.write_text(json.dumps(current), encoding="utf-8")
        completed, timed_out = _run_mobile_process(
            [sys.executable, "-m", "backend.android_runner", "--config", str(path.resolve())], os.environ.copy(), 3600
        )
        (directory / "repeat.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
        if timed_out or not (directory / "results.json").exists():
            raise RuntimeError("The repeat did not finish; inspect its preserved evidence: " + run_id)
        ids.append(run_id)
    return ids


def main():
    parser = argparse.ArgumentParser(
        description="Measure known-truth QA runs, build a showcase, or repeat an Android configuration."
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--out", type=Path, default=Path("runs/qa_showcase"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.config:
        print(json.dumps({"runs": repeat_android(args.config, args.repeats, args.runs_root)}, indent=2))
    elif args.manifest:
        result = save_showcase(args.runs_root, json.loads(args.manifest.read_text(encoding="utf-8")), args.out)
        print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    else:
        parser.error("Provide --manifest or --config")


if __name__ == "__main__":
    main()
