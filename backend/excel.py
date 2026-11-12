"""Writes the test cases to an Excel workbook:  runs/<run_id>/test_cases.xlsx

  Sheet "Test Cases"   -> every designed test case with its Test Steps, Automation Status and Execution Status
  Sheet "Test Results" -> every executed test (added by the Report step, with Pass/Fail and errors)
  Sheet "Cost Summary" -> what the run cost (AI tokens, $, time), added by the Report step

The workbook is rewritten as the run moves on:
  after Test Design       -> Automation = Pending,               Execution = Pending
  after Script Generation -> Automation = Automated / Not automated, Execution = Pending
  after the Report        -> Execution = Passed / Failed / Flaky / Skipped / Not run, plus cost per case
"""
import re
from pathlib import Path

CASES_HEADERS = ["#", "Test ID", "Page", "URL", "Feature", "Element", "Test Case", "Type", "Scenario", "Priority",
                 "Risk", "Preconditions", "Test Data", "Test Data Ref", "Test Steps", "Executed Steps",
                 "Expected Result", "Actual Result", "Automation Status", "Automated By", "Execution Status", "Details",
                 "Evidence", "Requirement / Workflow", "Skip / Block Reason", "Exec Time (s)", "AI Tokens",
                 "AI Cost (USD)"]
RESULTS_HEADERS = ["#", "Script", "Test", "Execution Status", "Duration (s)", "Checks", "Flaky", "Healed",
                   "Steps executed", "Failed at step", "Error", "Screenshot", "Trace", "Page URL"]
WIDTHS_CASES = [5, 14, 18, 38, 18, 22, 44, 11, 11, 10, 9, 30, 28, 24, 46, 56, 40, 40, 16, 14, 16, 50, 34, 26, 30, 12,
                11, 13]


def executed_steps(c: dict, results: list[dict] | None) -> str:
    """Every step the case's test(s) really did, in order ('1. ✓ Open /cart' ... '✗' where it failed): its own
    single tests - a failing one first."""
    if not results:
        return ""
    hits = [r for r in case_hits(c, results) if r.get("live_steps")]
    hits.sort(key=lambda r: r.get("outcome") not in ("failed", "error"))
    out = []
    for r in hits[:3]:
        if len(hits) > 1:
            out.append(f"[{r.get('test')}]")
        out += [f"{i}. {'✓' if s.get('ok') else '✗' if s.get('ok') is False else '·'} {s.get('text')}"
                for i, s in enumerate(r["live_steps"][:40], start=1)]
    return "\n".join(out)
WIDTHS_RESULTS = [5, 30, 50, 16, 12, 8, 8, 8, 60, 40, 70, 30, 30, 40]
SCENARIOS = ("happy", "negative", "edge", "workflow", "state")

FILL = {"Passed": "C6EFCE", "Failed": "FFC7CE", "Flaky": "FFEB9C", "Skipped": "E7E6E6", "Inconclusive": "FCE4D6",
        "Blocked": "D9D2E9",
        "Pending": "DDEBF7", "Not run": "F2F2F2", "Automated": "C6EFCE", "Not automated": "FFC7CE"}
SOURCE_NAME = {"llm": "AI", "template": "Template", "reused": "Reused", "added": "AI/Template (new elements)"}


def _ident(s: str) -> str:  # same rule as script_generator._ident (test file / function names)
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", s).strip("_").lower()
    return s if s and not s[0].isdigit() else f"t_{s}"


def _short_error(err: str | None) -> str:
    """The error in a few words: from the line that SAYS what went wrong ('AssertionError: ...'), not pytest's detail
    lines below it ('where x = ...')."""
    if not err:
        return ""
    lines = [l.strip() for l in err.splitlines() if l.strip()]
    key = [l for l in lines if l.startswith("E ")]
    first = next((n for n, l in enumerate(key) if re.search(r"\w+(Error|Exception)\b:|\bTimeout\b", l)), None)
    return " | ".join(key[first:first + 3] if first is not None else (key or lines)[-3:])[:400]


def _outcome(r: dict) -> str:
    if r["outcome"] == "blocked":
        return "Blocked"
    if r["outcome"] == "passed":
        return "Passed"
    if r["outcome"] == "skipped":
        return "Skipped"
    if r["outcome"] == "inconclusive":
        return "Inconclusive"  # ran, but checked nothing - not counted as passed
    return "Flaky" if r.get("flaky") else "Failed"


# The order the test files run in (the same list is in templates/conftest.py, which sorts the tests):
# the large end-to-end cases first, then the small checks, the link checks last.
RUN_ORDER = (("test_journeys", 0), ("test_checks", 1), ("test_flows", 1), ("test_site", 2), ("_data", 3),
             ("test_all_links", 4))


def file_rank(name: str) -> int:
    return next((r for key, r in RUN_ORDER if key in name), 2)


def _case_files(case: dict) -> list[str]:
    if case.get("files") is not None:  # the designed test cases say where their code is
        return list(case["files"])
    base = f"test_{_ident(case['page'])}"
    return [f"{base}.py", f"{base}_added.py", f"{base}_data.py"]


def _case_names(case: dict) -> set[str]:
    """Test function names of a case; a name ending in * means 'every test starting with this'."""
    if case.get("tests"):
        return set(case["tests"])
    cid = _ident(case["id"])
    names = {f"test_{cid}"}
    if cid == "buttons_click":  # the template implements this case as one parametrized test per button
        names.add("test_button_click")
    return names


def name_matches(test: str, names: set[str]) -> bool:
    test = test.split("[")[0]
    return any(test == n or (n.endswith("*") and test.startswith(n[:-1])) for n in names)


def def_pattern(name: str) -> str:
    """Regex for the `def` line of a test function name (prefix names end in *)."""
    return rf"^\s*def {re.escape(name[:-1])}\w*\(" if name.endswith("*") else rf"^\s*def {re.escape(name)}\("


def case_hits(case: dict, results: list[dict]) -> list[dict]:
    """The executed test(s) that implement this designed case."""
    if case.get("target_type") == "mobile" or str(case.get("id", "")).startswith("android_"):
        return [r for r in results if r.get("id") == case["id"]]
    files, names = set(_case_files(case)), _case_names(case)
    return [r for r in results if r["file"] in files and name_matches(r["test"], names)]


def automation_status(case: dict, test_dir: Path | None) -> tuple[str, str]:
    """('Automated' | 'Not automated' | 'Pending', how) - looks for the case's test function in the scripts."""
    if not test_dir or not test_dir.is_dir():
        return "Pending", ""
    if case.get("kind") == "contract" and not case.get("blocked") and (test_dir.parent / "qa_contracts.json").exists():
        return "Automated", "Trusted QA contract runtime"
    names = _case_names(case)
    for name in _case_files(case):
        f = test_dir / name
        if not f.exists():
            continue
        code = f.read_text(encoding="utf-8", errors="replace")
        if any(re.search(def_pattern(n), code, re.M) for n in names):
            first = code.split("\n", 1)[0]
            src = first.split(":", 1)[1].strip() if first.startswith("# generated by:") else ""
            return "Automated", SOURCE_NAME.get(src, src.title())
    return "Not automated", ""


def case_result(case: dict, results: list[dict] | None) -> tuple[str, str]:
    """Execution status of one designed case: find the test function(s) that implement it."""
    if results is None:
        return "Pending", ""
    if case.get("blocked"):  # a protected action: never run without explicit approval
        return "Blocked", case.get("skip_reason") or "Protected action - needs explicit approval"
    hits = case_hits(case, results)
    if not hits:
        if case.get("skip_reason"):  # nothing to check on this website (e.g. no pictures at all)
            return "Skipped", case["skip_reason"]
        return "Not run", "No test with this name ran (see the Test Results sheet for this page's script)."
    outs = [_outcome(r) for r in hits]
    bad = [r for r in hits if _outcome(r) in ("Failed", "Flaky")]
    if "Failed" in outs:
        res = "Failed"
    elif "Flaky" in outs:
        res = "Flaky"
    elif all(o == "Skipped" for o in outs):
        why = next((r.get("error") for r in hits if (r.get("error") or "").startswith("Blocked")), "")
        if why:  # the AI's test reached a protected action (pay, order, delete...): it was not clicked
            return "Blocked", why
        why = next((r.get("error") for r in hits if (r.get("error") or "").startswith("Not run")), "")
        if why:  # the website did not answer at all (it was down): nothing is known about this case
            return "Not run", why
        res = "Skipped"
    elif "Inconclusive" in outs and "Passed" not in outs:
        res = "Inconclusive"
    else:
        res = "Passed"
    detail = (_short_error(bad[0].get("error")) + (f" (+{len(bad) - 1} more failed)" if len(bad) > 1 else "")) if bad \
        else (f"{len(hits)} check(s) passed" if len(hits) > 1 else "")
    notes = [r["note"] for r in hits if r.get("note")]
    if notes and res == "Passed":  # a step this website did not allow is said, never hidden behind "passed"
        detail = f"{detail or 'All checks passed'}; not possible on this website: {'; '.join(notes)[:300]}"
    return res, detail


def _style_sheet(ws, widths: list[int], status_cols: list[int]):
    from openpyxl.styles import Alignment, Font, PatternFill

    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F2A44")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 22
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)
        for col in status_cols:
            res = row[col - 1]
            if res.value in FILL:
                res.fill = PatternFill("solid", fgColor=FILL[res.value])
                res.font = Font(bold=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _cost_sheet(wb, cost: dict):
    from openpyxl.styles import Font

    from .cost import fmt_usd

    ws = wb.create_sheet("Cost Summary")
    ws.append(["Item", "Value"])
    rows = [
        ("AI provider / model", f"{cost['provider']} / {cost['model']}".strip(" /") or "none (rule-based)"),
        ("Price per 1M tokens (in / out)", f"${cost['price_per_million']['input']} / ${cost['price_per_million']['output']}"),
        ("TOTAL AI cost for the run", fmt_usd(cost["cost_usd"])),
        ("Average AI cost per test case (end-to-end)", fmt_usd(cost["avg_cost_per_case_usd"])),
        ("Test cases", cost["test_cases"]),
        ("AI calls", cost["calls"]),
        ("Input tokens", cost["tokens_in"]),
        ("Output tokens", cost["tokens_out"]),
        ("Time spent waiting for AI (s)", cost["llm_seconds"]),
        ("Test execution time (s)", cost["test_exec_seconds"]),
        ("Whole run time (s)", cost["run_seconds"]),
        ("Note", cost["note"]),
        ("", ""),
        ("Cost by agent", ""),
    ] + [(f"  {a}", f"{fmt_usd(t['cost_usd'])}  ({t['calls']} calls, {t['tokens_in'] + t['tokens_out']} tokens)")
         for a, t in cost["by_agent"].items()]
    for r in rows:
        ws.append(list(r))
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 70
    for c in ws[1]:
        c.font = Font(bold=True)
    ws["A4"].font = ws["B4"].font = Font(bold=True, size=12)


def _coverage_sheet(wb, run_dir: Path):
    """Every control found on every page: tested, or not tested and why (from coverage.json)."""
    import json

    from openpyxl.styles import Font, PatternFill

    f = Path(run_dir) / "coverage.json"
    if not f.exists():
        return
    data = json.loads(f.read_text(encoding="utf-8-sig"))
    # after the run, each control's own result (registry.json): planned -> executed -> its verdict, how strong its proof
    # is (a state / value checked, or only "no errors" = smoke) and the test cases that decided it
    try:
        reg = json.loads((Path(run_dir) / "registry.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        reg = {}
    from .registry import STATUS_TEXT
    by_sel = {x["selector"]: x for x in (reg.get("features") or {}).values() if x.get("selector")}
    ws = wb.create_sheet("Coverage")
    ws.append(["Page", "Control", "Kind", "Planned", "Executed", "Verdict", "Strength", "Evidence", "Why not / note",
               "Frame", "Shadow DOM"])  # (row 1 = headers, also for the web viewer)
    for c in ws[1]:
        c.font = Font(bold=True)
    good = {"verified"}
    for p in data["pages"]:
        for it in p["items"]:
            feat = by_sel.get(it.get("selector")) or {}
            dec = feat.get("decided_by") or []
            planned = "Yes" if it["status"] == "tested" or feat.get("tests") else "No"
            executed = ("Yes" if any(x["status"] in ("Passed", "Failed", "Flaky", "Inconclusive") for x in dec) else
                        "No" if feat else "-")
            verdict = STATUS_TEXT.get(feat.get("status"), feat.get("status")) if feat.get("decided_by") is not None \
                else ("planned" if planned == "Yes" else "not tested")
            passed = [x for x in dec if x["status"] in ("Passed", "Flaky")]
            strength = ("strong" if any(x.get("strong", True) for x in passed) else "weak (smoke)" if passed else "")
            evidence = "; ".join(f"{x['tc_id']} {x['status']}" + (f": {x['why'][:60]}" if x.get("why") else "")
                                 for x in dec[:3])
            ws.append([p["url"], it["name"], it["kind"], planned, executed, verdict, strength, evidence,
                       feat.get("why") or it["reason"], it.get("frame", ""), it.get("shadow", "")])
            cell = ws.cell(row=ws.max_row, column=6)
            cell.fill = PatternFill("solid", fgColor="C6EFCE" if feat.get("status") in good else
                                    "FFC7CE" if feat.get("status") == "failed" else
                                    "FFEB9C" if planned == "Yes" else "F2F2F2")
    ws.append([])
    ws.append([f"Total: {data['tested']} of {data['total']} controls found on the pages have a test planned"])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    for col, w in zip("ABCDEFGHIJK", (50, 40, 24, 10, 10, 30, 14, 50, 60, 36, 30)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


REGISTRY_FILL = {"verified": "C6EFCE", "failed": "FFC7CE", "blocked": "D9D2E9", "needs_login": "FFEB9C",
                 "clicked_only": "FCE4D6", "unresolved": "FCE4D6", "inconclusive": "FCE4D6", "test_generated": "FFEB9C"}


def _summary_sheet(wb, metrics: dict):
    """The run's numbers - all from one calculation (backend/metrics.py) - with what each percentage is a share
    of, and the checks that the totals add up."""
    from openpyxl.styles import Font, PatternFill

    from .metrics import summary_lines
    ws = wb.create_sheet("Summary")
    ws.append(["What", "Passed", "Of", "%", "Counted (the denominator)"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in metrics["rates"]:
        ws.append([r["name"], r["passed"], r["of"], r["percent"] if r["percent"] is not None else "-", r["denominator"]])
    ws.append([])
    for line in summary_lines(metrics):
        ws.append([line])
    ws.append([])
    ws.append(["Consistency check", "OK?", "", "", "Details"])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    for c in metrics["consistency"]:
        ws.append([c["check"], "yes" if c["ok"] else "NO", "", "", c["detail"]])
        ws.cell(row=ws.max_row, column=2).fill = PatternFill("solid", fgColor="C6EFCE" if c["ok"] else "FFC7CE")
    for col, w in zip("ABCDE", (52, 10, 10, 8, 110)):
        ws.column_dimensions[col].width = w


def scenario_counts(tc_ids: list[str], cases: list[dict]) -> str:
    """'2 happy, 1 negative, 1 edge' - the kinds of scenario of these test cases (and the main kinds missing)."""
    kind = {c.get("tc_id"): c.get("scenario") for c in cases}
    got = [kind.get(t) for t in tc_ids if kind.get(t)]
    have = ", ".join(f"{got.count(s)} {s}" for s in SCENARIOS if s in got)
    missing = [s for s in ("happy", "negative", "edge") if s not in got]
    return have + (f" (no {' / '.join(missing)})" if have and missing else "")


def _registry_sheet(wb, run_dir: Path, cases: list[dict] | None = None):
    """Every feature found (registry.json): its id, level, page, evidence, test cases, their kinds of scenario and its
    status - and why."""
    import json

    from openpyxl.styles import Font, PatternFill

    f = Path(run_dir) / "registry.json"
    if not f.exists():
        return
    reg = json.loads(f.read_text(encoding="utf-8-sig"))
    ws = wb.create_sheet("Features")
    ws.append(["Feature ID", "Level", "Kind", "Feature / control", "Page(s)", "Status", "Why", "Test cases",
               "Scenarios (happy / negative / edge)", "What exploring saw", "AI: feature (category) - expected", "Frame",
               "Shadow DOM"])
    for c in ws[1]:
        c.font = Font(bold=True)
    from .registry import STATUS_TEXT
    for x in reg["features"].values():
        ev = x.get("evidence") or {}
        saw = (f"{ev.get('effect')}: {ev.get('message') or ev.get('to') or ''}".strip(": ") if ev else "")
        ai = f"{x['ai_feature']} ({x.get('ai_category')}) - {x.get('ai_expected', '')}" if x.get("ai_feature") else ""
        ws.append([x["id"], x["level"], x["kind"], x["name"], ", ".join(x["pages"][:3]),
                   STATUS_TEXT.get(x["status"], x["status"]), x.get("why", ""),
                   ", ".join(t["tc_id"] + ("" if t["how"] == "verifies" else f" ({t['how']})") for t in x["tests"][:6]),
                   scenario_counts([t["tc_id"] for t in x["tests"]], cases or []),
                   saw[:120], ai[:200], x.get("frame", ""), x.get("shadow", "")])
        ws.cell(row=ws.max_row, column=6).fill = PatternFill("solid", fgColor=REGISTRY_FILL.get(x["status"], "F2F2F2"))
    counts = (reg.get("counts") or {}).get("features") or {}
    if counts:
        ws.append([])
        ws.append([f"Features: {counts.get('discovered', 0)} discovered · {counts.get('tested', 0)} tested · "
                   f"{counts.get('verified', 0)} verified · {counts.get('failed', 0)} failed · {counts.get('blocked', 0)} "
                   f"blocked · {counts.get('needs_login', 0)} need a test account · {counts.get('unresolved', 0)} not tested"])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    for col, w in zip("ABCDEFGHIJKLM", (13, 10, 14, 36, 36, 14, 60, 34, 30, 50, 60, 30, 26)):
        ws.column_dimensions[col].width = w


def write_workbook(run_dir: Path, cases: list[dict], results: list[dict] | None = None,
                   cost: dict | None = None, metrics: dict | None = None) -> Path | None:
    """Create / overwrite test_cases.xlsx. Returns its path, or None if openpyxl is not installed."""
    try:
        from openpyxl import Workbook
    except ImportError:
        print("  [excel] openpyxl is not installed - skipping test_cases.xlsx (pip install openpyxl)")
        return None

    run_dir = Path(run_dir)
    test_dir = run_dir / "generated_tests"
    case_cost = {(c["page"], c["id"]): c for c in (cost or {}).get("per_case", [])}

    wb = Workbook()
    ws = wb.active
    ws.title = "Test Cases"
    ws.append(CASES_HEADERS)
    for n, c in enumerate(cases, start=1):
        steps = c.get("steps") or []
        steps = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, start=1)) if isinstance(steps, list) else str(steps)
        auto, how = automation_status(c, test_dir)
        res, detail = case_result(c, results)
        if auto == "Not automated" and res == "Not run":
            detail = c.get("automation_note") or "No automated script could be written for this case."
        cc = case_cost.get((c.get("page", ""), c.get("id", "")), {})
        lines = lambda v: "\n".join(map(str, v)) if isinstance(v, list) else str(v or "")  # noqa: E731
        ws.append([n, c.get("tc_id") or c.get("id", ""), c.get("page", ""), c.get("url", ""), c.get("feature", ""),
                   c.get("element", ""), c.get("title", ""), c.get("type", ""), c.get("scenario", ""),
                   c.get("priority", ""), c.get("risk", ""),
                   lines(c.get("preconditions")), str(c.get("test_data") or ""), c.get("test_data_ref", ""), steps,
                   executed_steps(c, results), str(c.get("expected", "")), c.get("actual_result", "") if results is not None else "", auto, how,
                   res, detail, lines(c.get("evidence")), c.get("requirement", ""), c.get("skip_reason", ""),
                   cc.get("exec_s", ""), cc.get("tokens", ""), cc.get("cost_usd", "")])
    _style_sheet(ws, WIDTHS_CASES, [CASES_HEADERS.index("Automation Status") + 1,
                                    CASES_HEADERS.index("Execution Status") + 1])

    if results is not None:
        ws2 = wb.create_sheet("Test Results")
        ws2.append(RESULTS_HEADERS)
        for n, r in enumerate(results, start=1):
            steps = r.get("live_steps") or []  # (every step the test did - conftest.py; 'steps' = a journey's own)
            failed_at = next((f"{i}. {s['text']}" for i, s in enumerate(steps, start=1) if s.get("ok") is False), "")
            ws2.append([n, r.get("file", ""), r.get("test", ""), _outcome(r), r.get("duration_s", ""),
                        r.get("checks", ""), "yes" if r.get("flaky") else "",
                        f"round {r['healed_round']}" if r.get("healed_round") else "",
                        "\n".join(f"{i}. {'✓' if s.get('ok') else '✗' if s.get('ok') is False else '·'} {s['text']}"
                                  for i, s in enumerate(steps[:40], start=1)), failed_at,
                        _short_error(r.get("error")), r.get("screenshot") or "", r.get("trace") or "", r.get("url") or ""])
        _style_sheet(ws2, WIDTHS_RESULTS, [RESULTS_HEADERS.index("Execution Status") + 1])

    if cost:
        _cost_sheet(wb, cost)
    _coverage_sheet(wb, run_dir)
    _registry_sheet(wb, run_dir, cases)
    if metrics:
        _summary_sheet(wb, metrics)

    path = run_dir / "test_cases.xlsx"
    try:
        wb.save(path)
    except PermissionError:  # the file is open in Excel right now
        path = run_dir / "test_cases_results.xlsx"
        wb.save(path)
        print(f"  [excel] test_cases.xlsx is open in Excel - saved as {path.name} instead")
    print(f"  [excel] wrote {path}")
    return path
