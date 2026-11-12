"""Human review (Step 11): the tool asks what it can't know, between designing the test cases and writing their code.

  questions   every test case whose expected result was only OBSERVED while exploring ("Clicking 'Load totals' showed
              'Total sales: 4560'. Is that correct?") and every rule question an earlier run left open ("The site
              accepted a return date before the departure date. Is that allowed?")
  answers     correct  -> the expected result is confirmed (expected_source = requirement)
              should be <text> -> the expected result becomes <text>
              skip     -> the case is left out
              rules:   allowed -> not asked or tested again · not allowed -> a broken rule is a product defect
  where       runs/<run>/review_request.json (the questions), runs/<run>/review_answers.json (the web UI writes it);
              the answers are kept per website in baseline/<site>/expectations.json and used by the next run without
              asking again
  when        on by default on staging (REVIEW=auto); REVIEW=on asks on every environment, REVIEW=off never. The run
              waits up to REVIEW_TIMEOUT_S (900 s) for the answers, then goes on unchanged.
  edit        (TestOptim: "review and edit what it found") the review also lists every designed test case: unticked ones
              are left out of THIS run; tests you add in plain English are designed now (test_design.my_test_cases)
              and kept for every later run of the website (backend/my_tests.py). A staging run's cleanup is never
              left out.
"""
import json
import time
from pathlib import Path

from . import runctl
from .config import settings
from .state import QAState


def _expect_file(site_key: str) -> Path:
    return settings.baseline_dir / site_key / "expectations.json"


def load_expectations(site_key: str) -> dict:
    try:
        return json.loads(_expect_file(site_key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_expectations(site_key: str, answers: dict) -> None:
    f = _expect_file(site_key)
    f.parent.mkdir(parents=True, exist_ok=True)
    known = load_expectations(site_key)
    known.update(answers)
    f.write_text(json.dumps(known, indent=2), encoding="utf-8")


def open_rule_questions(site_key: str) -> list[dict]:
    """The rule questions earlier runs left open (saved with the baseline)."""
    try:
        return json.loads((settings.baseline_dir / site_key / "open_questions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def enabled() -> bool:
    mode = (settings.review or "auto").lower()
    return mode == "on" or (mode == "auto" and settings.environment == "staging")


def _observed_question(c: dict) -> dict | None:
    s = c.get("spec") or {}
    if c.get("kind") != "learned" or c.get("oracle") != "observed":
        return None
    saw = s.get("message") or "; ".join(s.get("added") or []) or s.get("to") or ", ".join(s.get("revealed") or [])
    if not saw:
        return None
    saw = saw.replace("[shadow] ", "").replace("[frame] ", "")
    act = {"select": "Choosing an option in", "tick": "Ticking"}.get(s.get("action"), "Clicking")
    return {"tc_id": c["tc_id"], "kind": "observed", "title": c["title"],
            "question": f"{act} '{s.get('name')}' showed '{saw[:120]}'. Is that correct?",
            "choices": ["correct", "should be", "skip"], "saw": saw[:200]}


def questions(cases: list[dict], site_key: str) -> list[dict]:
    known = load_expectations(site_key)
    out = [q for q in (_observed_question(c) for c in cases) if q and q["tc_id"] not in known]
    by_tc = {c.get("tc_id"): c for c in cases}
    for q in open_rule_questions(site_key):
        if q.get("tc_id") in by_tc and q["tc_id"] not in known:
            out.append({"tc_id": q["tc_id"], "kind": "rule", "title": by_tc[q["tc_id"]]["title"],
                        "question": q["question"], "choices": ["allowed", "not allowed", "skip"]})
    return out[:40]


def apply(cases: list[dict], answers: dict) -> tuple[list[dict], int]:
    """The answers -> the test cases (confirmed, changed, or left out). Returns (cases, how many changed)."""
    out, changed = [], 0
    for c in cases:
        a = answers.get(c.get("tc_id"))
        if not a:
            out.append(c)
            continue
        choice, text = a.get("answer"), (a.get("text") or "").strip()
        changed += 1
        if choice in ("skip", "allowed"):
            continue  # (left out - an allowed rule is no rule of this website)
        c = dict(c, expected_source="requirement", oracle="requirement")
        if choice == "should be" and text:
            spec = dict(c.get("spec") or {})
            if spec.get("effect") == "message":
                spec["message"] = text
            else:
                spec["added"] = [text]
            c.update(expected=f"{text} (your answer in the review)", spec=spec)
        if choice == "not allowed":
            c["spec"] = dict(c.get("spec") or {}, confirmed=True)
        out.append(c)
    return out, changed


def review_gate_agent(state: QAState) -> QAState:
    """Between test design and the scripts: apply what you answered before; ask what is still open (and wait)."""
    site, run_dir = state.get("site_key") or "site", Path(state["run_dir"])
    cases = list(state.get("test_cases", []))
    known = load_expectations(site)
    cases, reused = apply(cases, {k: v for k, v in known.items() if any(c.get("tc_id") == k for c in cases)})
    log = state.get("log", [])
    if reused:
        log = log + [f"Review: {reused} test case(s) follow your earlier answers (expectations.json)."]
    if not enabled():
        return {"test_cases": cases, "log": log}
    qs = questions(cases, site)
    if not qs and (settings.review or "auto").lower() != "on":  # (staging's automatic review: only when it must ask)
        return {"test_cases": cases, "log": log + ["Review: nothing to ask."]}
    listed = [{"tc_id": c["tc_id"], "title": c.get("title"), "feature": c.get("feature"), "scenario": c.get("scenario"),
               "fixed": c.get("kind") == "cleanup"} for c in cases if c.get("tc_id")]
    (run_dir / "review_request.json").write_text(json.dumps({"questions": qs, "cases": listed, "asked": time.time(),
                                                             "timeout_s": settings.review_timeout_s}, indent=2),
                                                 encoding="utf-8")
    print(f"::review::{json.dumps({'questions': len(qs), 'cases': len(listed)})}", flush=True)
    print(f"  [review] {len(qs)} question(s) and {len(listed)} test case(s) for you to review in the chat (or "
          f"runs/{run_dir.name}/review_request.json) - waiting up to {settings.review_timeout_s} s", flush=True)
    answers_file, deadline = run_dir / "review_answers.json", time.time() + settings.review_timeout_s
    while time.time() < deadline and not answers_file.exists() and not runctl.stopping():
        time.sleep(1)
    if not answers_file.exists():
        return {"test_cases": cases, "log": log + ["Review: no answers in time - the test cases run as designed."]}
    try:
        got = json.loads(answers_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        got = {}
    answers = {k: v for k, v in (got.get("answers") or {}).items() if isinstance(v, dict) and v.get("answer")}
    cases, n = apply(cases, answers)
    save_expectations(site, answers)
    notes = [f"{n} answer(s) applied and saved for the next run"]
    out_ = {str(x) for x in got.get("leave_out") or []}
    if out_:  # (unticked: left out of this run only - a staging run's cleanup always runs)
        before = len(cases)
        cases = [c for c in cases if c.get("tc_id") not in out_ or c.get("kind") == "cleanup"]
        notes.append(f"{before - len(cases)} test case(s) left out by you")
    added = _add_tests(state, cases, got.get("add_tests") or [])
    if added:
        cases += added
        notes.append(f"{len(added)} test(s) of your own added (kept for the next runs too)")
    return {"test_cases": cases, "log": log + ["Review: " + "; ".join(notes) + "."]}


def _add_tests(state: QAState, cases: list[dict], texts: list) -> list[dict]:
    """Tests you added in the review, in plain English: kept for this website, and designed for this run now."""
    import re

    from . import my_tests
    from .agents.test_design import finalize_cases, my_test_cases
    site = state.get("site_key") or "site"
    known = {t["text"].lower() for t in my_tests.load(site)}
    new = [t for t in my_tests.add(site, texts) if t["text"].lower() not in known]
    if not new:
        return []
    pages = [p for p in state.get("app_map", []) if not p.get("error") and (p.get("status") or 0) < 400]
    taken = [int(m.group(1)) for c in cases for m in [re.match(r"ai_flow_(\d+)$", str(c.get("id")))] if m]
    designed = my_test_cases(pages, new, start=max(taken, default=0) + 1)
    return finalize_cases(designed, dict(state, test_cases=cases))
