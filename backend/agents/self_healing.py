"""Agent — Self-Healing.

When a test fails because the SCRIPT is outdated (e.g. a button's id changed after a frontend
update), this agent repairs the script and asks the Execution Agent to run it again.

How it repairs (in this order):
  0. A locator that matches several elements (strict mode): use the first visible one (` >> visible=true >> nth=0`).
  1. Selector matching (no AI, free, predictable):
     find the element the old selector pointed to in the OLD page data (the page itself, or - for a selector the new
     pages don't have at all - the page of the last run that had it), find the same element on the NEW page (same
     button text / same input name or label / same form), swap the selector.
  2. LLM repair (if an LLM is configured): give the AI the script, the error, old + new page data.

The golden rule: it may change HOW elements are found - never WHAT is checked.
Any repair that removes or changes assertions is rejected, so real bugs are never hidden.
A repair is only a candidate: the Execution Agent runs the repaired test AND the other tests of the same file again,
then keeps it (passes / now fails on a real check) or undoes it (still a script problem / broke another test) -
see executor._rerun_healed. The script as it was before the round is kept in healing/.
"""
import ast
import difflib
import json
import re
import shutil
from collections import Counter
from pathlib import Path

from ..human_review import proposal_fields
from ..llm import LLMError, ask_llm, extract_code, llm_enabled, load_prompt
from ..state import QAState
from .script_generator import _ident, validate_script
from .test_design import lean

SELECTOR_IN_ERROR = re.compile(r"""locator\((["'])(.+?)\1\)""")
# where Playwright names the element it could not use: its call log, or the strict-mode message (first)
SELECTOR_USED = re.compile(r"""(?:waiting for |strict mode violation: )locator\((["'])(.+?)\1\)""")
NOT_UNIQUE = re.compile(r"strict mode violation")


# ------------------------------------------------------------------ helpers

def _page_for_file(file: str, app_map: list[dict]) -> dict | None:
    stem = file[:-3] if file.endswith(".py") else file
    for p in app_map:
        i = _ident(p["slug"])
        if stem in (f"test_{i}", f"test_{i}_added", f"test_{i}_data", f"steps_{i}"):
            return p
    return None


def _page_with_selector(selector: str, app_map: list[dict]) -> dict | None:
    """The page whose control used this selector (journeys / flows use controls of several pages)."""
    return next((p for p in app_map if _find_old_element(selector, p)), None)


def _script_is_linked(test_dir: Path, name: str) -> bool:
    """A generated script that is a link, or a name that leaves the run, is not this run's file."""
    path = Path(name)
    from ..finalization import folder_is_linked
    if not name or path.is_absolute() or ".." in path.parts or folder_is_linked(test_dir):
        return True
    return folder_is_linked(test_dir / name)


def _file_with(selector: str, test_dir: Path, failed_file: str) -> str | None:
    """Which generated file holds the broken selector: the failing file, else the step module it calls."""
    from ..finalization import folder_is_linked
    if folder_is_linked(test_dir):
        return None
    names = [failed_file] + sorted(f.name for f in test_dir.glob("steps_*.py") if not f.is_symlink()) \
        + sorted(f.name for f in test_dir.glob("test_*.py") if not f.is_symlink())
    for name in dict.fromkeys(names):
        f = test_dir / name
        if _script_is_linked(test_dir, name):
            continue
        if f.exists():
            code = f.read_text(encoding="utf-8")
            if repr(selector) in code or json.dumps(selector) in code:
                return name
    return None


def _baseline_map(state: QAState) -> list[dict]:
    """The pages of the last run (the baseline) - where an old selector came from."""
    ch = state.get("changes") or {}
    if not ch.get("baseline_dir"):
        return []
    f = Path(ch["baseline_dir"], "app_map.json")
    from ..finalization import folder_is_linked
    if f.is_symlink() or folder_is_linked(f.parent):
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    except (OSError, ValueError):
        return []


def _moved_page(selector: str, state: QAState) -> tuple[dict | None, dict | None]:
    """A selector the new pages don't have at all: (the page of the LAST run that had it, the same page now) - so a
    renamed id is repaired in every test file (learned, features, journeys), not only in a page's own file."""
    from .change_detection import page_key
    old = _page_with_selector(selector, _baseline_map(state))
    if old is None:
        return None, None
    same = [p for p in state.get("app_map", []) if page_key(p["url"]) == page_key(old["url"])]
    now = next((p for p in same if bool(p.get("auth")) == bool(old.get("auth"))), None) or next(iter(same), None)
    return (old, now) if now is not None else (None, None)


def _old_page(state: QAState, new_page: dict) -> dict | None:
    ch = state.get("changes") or {}
    if not ch.get("baseline_dir"):
        return None
    f = Path(ch["baseline_dir"], "app_map.json")
    from ..finalization import folder_is_linked
    if f.is_symlink() or folder_is_linked(f.parent) or not f.exists():
        return None
    old_slug = ch.get("baseline_slug", {}).get(new_page["slug"])
    return next((p for p in json.loads(f.read_text(encoding="utf-8")) if p["slug"] == old_slug), None)


def _assertion_profile(code: str) -> dict[str, int]:
    """Number of checks (assert / expect(...)) per test / step function. Used to block 'cheating' repairs."""
    prof = {}
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.FunctionDef) and node.name.startswith(("test_", "step_", "_")):
            n = 0
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assert):
                    n += 1
                elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "expect":
                    n += 1
            prof[node.name] = n
    return prof


def _payment_literals(code: str) -> set[str]:
    """String constants that open checkout or payment."""
    from ..swarm import control_opens_payment, is_payment_url

    found: set[str] = set()
    for node in ast.walk(ast.parse(code)):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        text = node.value.strip()
        if not text:
            continue
        if is_payment_url(text) or control_opens_payment("https://shop.test/", text, "", text):
            found.add(text)
    return found


def _safe_repair(old_code: str, new_code: str, need_tests: bool = True) -> str | None:
    """Returns an error if the repaired code is not acceptable (need_tests=False: a steps_*.py module)."""
    err = validate_script(new_code, need_tests=need_tests)
    if err:
        return err
    if _payment_literals(new_code) - _payment_literals(old_code):
        return "the repair points a test at checkout or payment"
    before, after = _assertion_profile(old_code), _assertion_profile(new_code)
    if set(before) - set(after):
        return f"test functions removed: {sorted(set(before) - set(after))}"
    weaker = [t for t in before if after.get(t, 0) < before[t]]
    if weaker:
        return f"assertions removed from {weaker}"
    return _checks_unchanged(old_code, new_code)


# A repair may change HOW an element is found - never WHAT is checked. The address of an element (the string given to
# locator / frame_locator / get_by_label / get_by_placeholder / get_by_test_id) is masked; everything else of every
# assert and every expect(...).to_*(...) must stay exactly as it was (adding checks is fine).
ADDRESS_CALLS = {"locator", "frame_locator", "get_by_label", "get_by_placeholder", "get_by_test_id", "query_selector",
                 "wait_for_selector", "query_selector_all"}
CATCH_ALL = {"AssertionError", "Exception", "BaseException"}


class _MaskAddresses(ast.NodeTransformer):
    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr in ADDRESS_CALLS and node.args \
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            node.args[0] = ast.Constant(value="<address>")
        return node


def _is_expect_check(n: ast.AST) -> bool:
    return isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr.startswith("to_") \
        and isinstance(n.func.value, ast.Call) and isinstance(n.func.value.func, ast.Name) \
        and n.func.value.func.id == "expect"


def _checks(fn: ast.AST) -> list[str]:
    """Every check of a function, with element addresses masked (assert x / expect(...).to_*(...))."""
    import copy
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Assert):
            out.append(ast.dump(_MaskAddresses().visit(copy.deepcopy(n.test)), annotate_fields=False))
        elif _is_expect_check(n):
            out.append(ast.dump(_MaskAddresses().visit(copy.deepcopy(n)), annotate_fields=False))
    return out


def _escapes(tree: ast.AST) -> Counter:
    """The ways a test can be made to pass without checking: catch-all handlers, skip / xfail."""
    c = Counter()
    for n in ast.walk(tree):
        if isinstance(n, ast.ExceptHandler):
            names = {x.id for x in ast.walk(n.type) if isinstance(x, ast.Name)} if n.type else {"(bare)"}
            if names & (CATCH_ALL | {"(bare)"}):
                c["except " + "/".join(sorted(names))] += 1
        elif isinstance(n, ast.Attribute) and n.attr in ("skip", "xfail", "skipif") \
                and isinstance(n.value, (ast.Name, ast.Attribute)):
            c[f"pytest {n.attr}"] += 1
    return c


def _never_fail(tree: ast.AST) -> Counter:
    """Checks that can never fail (only inside a check: `x or 'default'` elsewhere is fine)."""
    c = Counter()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Assert):
            continue
        if isinstance(n.test, ast.Constant):
            c["an assert of a constant (it checks nothing)"] += 1
        elif any(isinstance(b, ast.BoolOp) and isinstance(b.op, ast.Or) and any(
                isinstance(v, ast.Constant) and v.value for v in b.values) for b in ast.walk(n.test)):
            c["a check was made to always pass ('or True')"] += 1
    return c


def _checks_unchanged(old_code: str, new_code: str) -> str | None:
    """None = the repair keeps every check; else why it is rejected."""
    old, new = ast.parse(old_code), ast.parse(new_code)
    old_fns = {n.name: n for n in ast.walk(old) if isinstance(n, ast.FunctionDef)}
    new_fns = {n.name: n for n in ast.walk(new) if isinstance(n, ast.FunctionDef)}
    for name, fn in old_fns.items():
        if name not in new_fns:
            return f"function {name} was removed"
        lost = Counter(_checks(fn)) - Counter(_checks(new_fns[name]))
        if lost:
            return f"a check of {name} was changed or removed (only an element's address may change)"
    # only what the REPAIR adds: an `assert True` the AI test already had (practicesoftwaretesting.com, Nov 3, 2026)
    # made every repair of its file 'unsafe' - 4 tests that only needed a unique locator stayed broken
    cheat = _never_fail(new) - _never_fail(old)
    if cheat:
        return next(iter(cheat))
    more = _escapes(new) - _escapes(old)
    if more:
        return f"the repair adds a way to pass without checking: {', '.join(sorted(more))}"
    return None


def _find_old_element(selector: str, page: dict) -> tuple[str, dict, dict | None] | None:
    """Locate what the old selector pointed to. Returns (kind, element, parent_form)."""
    for f in page.get("forms", []):
        if f.get("selector") == selector:
            return "form", f, None
        if (f.get("submit") or {}).get("selector") == selector:
            return "submit", f["submit"], f
        for fl in f.get("fields", []):
            if fl.get("selector") == selector:
                return "input", fl, f
    for b in page.get("buttons", []):
        if b.get("selector") == selector:
            return "button", b, None
    for i in page.get("inputs", []):
        if i.get("selector") == selector:
            return "input", i, None
    return None


def _find_new_selector(kind: str, old: dict, form: dict | None, new_page: dict) -> str | None:
    """Find the same element on the new page and return its selector."""
    forms = new_page.get("forms", [])
    if kind == "form":
        same = next((f for f in forms if f["index"] == old["index"]), None)
        return same and same.get("selector")
    if kind in ("submit", "button"):
        text = (old.get("text") or "").strip()
        for b in new_page.get("buttons", []):
            if text and (b.get("text") or "").strip() == text and b.get("selector"):
                return b["selector"]
        if kind == "submit" and form is not None:  # text changed too: use the submit of the same form
            same = next((f for f in forms if f["index"] == form["index"]), None)
            if same and same.get("submit") and same["submit"].get("selector"):
                return same["submit"]["selector"]
        if text and any((b.get("text") or "").strip() == text for b in new_page.get("buttons", [])):
            return f'button:has-text("{text}")'
        return None
    if kind == "input":
        name, label, typ = old.get("name"), (old.get("label") or "").strip(), old.get("type")
        cands = new_page.get("inputs", [])
        # (the choices of a group share one name and one type: only its label tells which choice it is)
        group = typ in ("radio", "checkbox")
        for test in (lambda i: name and not group and i.get("name") == name,
                     lambda i: label and (i.get("label") or "").strip() == label,
                     lambda i: typ and not group and typ not in ("text", "") and i.get("type") == typ
                     and sum(1 for x in cands if x.get("type") == typ) == 1):
            hit = next((i for i in cands if test(i)), None)
            if hit:
                return hit.get("selector") or (f'[name="{hit["name"]}"]' if hit.get("name") else None)
    return None


def _replace_selector(code: str, old: str, new: str) -> str:
    return (code.replace(repr(old), repr(new))
                .replace(json.dumps(old), json.dumps(new)))


def _page_brief(p: dict | None) -> str:
    if not p:
        return "(not available)"
    return json.dumps({k: lean(p.get(k)) for k in ("url", "title", "headings", "buttons", "inputs", "forms")}, indent=1)


# ------------------------------------------------------------------ agent

def self_healing_agent(state: QAState) -> QAState:
    if state.get("target_type") == "mobile":
        from ..android_reporting import collect_healing
        return collect_healing(state)
    run_dir = Path(state["run_dir"])
    test_dir = run_dir / "generated_tests"
    backup_dir = run_dir / "healing"
    from ..finalization import folder_is_linked
    if folder_is_linked(run_dir):
        note = "Self-healing skipped: this run's folder is a link."
        return {"heal_round": state.get("heal_round", 0), "rerun_only": [],
                "healing_log": list(state.get("healing_log") or []),
                "unhealable": list(state.get("unhealable") or []),
                "log": list(state.get("log") or []) + [note]}
    if not backup_dir.is_symlink():
        backup_dir.mkdir(exist_ok=True)
    rnd = state.get("heal_round", 0) + 1
    unhealable = list(state.get("unhealable", []))
    log = list(state.get("healing_log", []))
    to_rerun = []

    # the owner's / Jira tests that failed on a page exploring never saw: rewritten from the real page first
    ev_log, ev_rerun = evidence_repair(state, test_dir, backup_dir, rnd)
    log += ev_log
    to_rerun += ev_rerun
    tried = {e["nodeid"] for e in ev_log}

    from .failure_analysis import healable
    from ..config import settings
    targets = [] if state.get("heal_round", 0) >= settings.max_heal_rounds else [  # (an evidence-only round)
        f for f in state.get("failures", []) if healable(f) and f.get("nodeid") not in unhealable
        and f.get("nodeid") not in tried]
    print(f"  [self-healing] round {rnd}: {len(targets)} broken script(s) to repair")

    fixed: dict[str, dict] = {}  # selector -> the repair made earlier in this round (file, method, new selector)
    # (the whole error of each test: the finding keeps only its last lines - after a page snapshot those no longer
    # name the element)
    full = {r["nodeid"]: r.get("error") or "" for r in state.get("results", [])}
    for f in targets:
        err = full.get(f["nodeid"]) or f.get("error") or ""
        m = SELECTOR_USED.search(err) or SELECTOR_IN_ERROR.search(err)
        bad = m.group(2) if m else None
        entry = {"round": rnd, "file": f["file"], "test": f["test"], "nodeid": f["nodeid"],
                 "error": f["error"], "method": None, "change": None, "diff": "", "status": "pending",
                 "backup": None, "from": None, "to": None, "related": [], "rerun": None}
        # the broken selector may live in another file than the failing test (e.g. steps_<page>.py)
        holder = (_file_with(bad, test_dir, f["file"]) if bad else None) or f["file"]
        if _script_is_linked(test_dir, holder):
            entry["status"] = "could not heal"
            entry["change"] = "the script is a link"
            unhealable.append(f["nodeid"])
            log.append(entry)
            continue
        if bad and bad in fixed and fixed[bad]["file"] == holder:
            # The same file was already repaired. A different file keeps its own repair,
            # so a later failure there cannot undo the first file.
            # Only a class that may repair itself inherits that change. A test mistake,
            # or any other class that needs a person, does not.
            done = fixed[bad]
            from ..healing_policy import escalation_for
            later = escalation_for(str(f.get("category") or ""))
            if later["auto_apply"]:
                entry.update(file=done["file"], method=done["method"], backup=done["backup"], to=done["to"],
                             change=f"{bad}  ->  {done['to']} (already repaired this round)")
                entry["from"] = bad
                log.append(entry)
                to_rerun.append(f["nodeid"])
                continue
        path = test_dir / holder
        if not path.exists():
            unhealable.append(f["nodeid"])
            continue
        before = path.read_text(encoding="utf-8")
        new_page = _page_for_file(holder, state["app_map"]) or (
            _page_with_selector(bad, state["app_map"]) if bad else None) or _page_for_file(f["file"], state["app_map"])
        old_page = _old_page(state, new_page) if new_page else None
        known = any(p and _find_old_element(bad, p) for p in (new_page, old_page)) if bad else True
        if not known:  # the selector is gone from the new pages: which page had it in the last run?
            was, now = _moved_page(bad, state)
            if was is not None:
                old_page, new_page = was, now
        is_test_file = holder.startswith("test_")
        entry["file"] = holder

        after, why_not = None, ""
        # ---- 0) the locator matches several elements: the (first) visible one is meant (only HOW it is found changes;
        # 'text=Power Tools' was the menu item, the page title and a filter - two of them visible)
        if bad and NOT_UNIQUE.search(err) and "visible=true" not in bad:
            good = f"{bad} >> visible=true >> nth=0"
            candidate = _replace_selector(before, bad, good)
            if candidate != before and not _safe_repair(before, candidate, is_test_file):
                after, entry["method"], entry["change"] = candidate, "unique-locator", f"{bad}  ->  {good}"
                entry["from"], entry["to"] = bad, good
        # ---- 1) selector matching
        if after is None and bad and new_page:
            found = _find_old_element(bad, old_page or {}) or _find_old_element(bad, new_page)
            if found:
                kind, old_el, form = found
                good = _find_new_selector(kind, old_el, form, new_page)
                if good and good != bad and (repr(good) in before or json.dumps(good) in before):
                    why_not = (f"'{bad}' would become '{good}' - an element this script already uses for something "
                               "else: never repaired that way")
                elif good and good != bad:
                    candidate = _replace_selector(before, bad, good)
                    if candidate != before and not _safe_repair(before, candidate, is_test_file):
                        after, entry["method"], entry["change"] = candidate, "selector-match", f"{bad}  ->  {good}"
                        entry["from"], entry["to"] = bad, good
                elif good == bad:
                    why_not = f"selector '{bad}' still exists - the failure has another cause"
                else:
                    why_not = f"element for '{bad}' not found on the new page (feature removed or broken?)"
            else:
                why_not = f"could not identify what '{bad}' pointed to"

        # ---- 2) LLM repair
        if after is None and llm_enabled() and new_page:
            try:
                prompt = load_prompt("self_healing").format(
                    test=f["test"], error=err, code=before,
                    old_page=_page_brief(old_page), new_page=_page_brief(new_page))
                candidate = extract_code(ask_llm(prompt, agent="self_healing", page=new_page["slug"], test=f["test"]))
                if candidate.strip() == before.strip():
                    why_not = "AI says the element no longer exists"
                else:
                    problem = _safe_repair(before, candidate, is_test_file)
                    if problem:
                        why_not = f"AI repair rejected: {problem}"
                    else:
                        after, entry["method"], entry["change"] = candidate, "llm", "AI rewrote locators/steps"
            except LLMError as e:
                why_not = f"LLM failed: {e}"

        if after is not None:
            from ..healing_policy import review_repair
            verdict = review_repair(
                before, after, need_tests=is_test_file,
                failure_class=str(f.get("category") or ""),
                approval_token=str(f.get("approval_token") or ""),
            )
            if not verdict.get("allowed"):
                why_not = verdict.get("reason") or "repair refused"
                after = None
        if after is None:
            entry["status"] = "could not heal"
            entry["change"] = why_not or "no safe repair found"
            unhealable.append(f["nodeid"])
            print(f"  [self-healing] X {f['file']}::{f['test']} - {entry['change']}")
        else:
            if _script_is_linked(test_dir, holder):
                entry["status"] = "could not heal"
                entry["change"] = "the script is a link"
                unhealable.append(f["nodeid"])
                log.append(entry)
                continue
            if not backup_dir.is_symlink():
                backup = backup_dir / f"{path.stem}.round{rnd}.before.py"
                if not backup.is_symlink() and not backup.exists():
                    shutil.copy(path, backup)
                if not backup.is_symlink():
                    entry["backup"] = backup.relative_to(run_dir).as_posix()
            path.write_text(after, encoding="utf-8")
            entry.update(proposal_fields(f.get("error") or ""))
            entry["diff"] = "".join(difflib.unified_diff(
                before.splitlines(True), after.splitlines(True), "before", "after", n=1))
            if bad and entry["to"]:
                from ..healing_policy import escalation_for
                earlier = escalation_for(str(f.get("category") or ""))
                fixed[bad] = {
                    "file": holder, "method": entry["method"], "to": entry["to"],
                    "backup": entry["backup"], "auto_apply": bool(earlier["auto_apply"]),
                }
            to_rerun.append(f["nodeid"])
            print(f"  [self-healing] candidate {f['file']}::{f['test']} - {entry['change']} (runs again to decide)")
        log.append(entry)

    log_path = run_dir / "healing_log.json"
    if not log_path.is_symlink():
        log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    msg = (f"Self-healing round {rnd}: {len(to_rerun)} repair candidate(s) - they run again before anything is "
           f"called repaired; no safe repair for {len(targets) + len(tried) - len(to_rerun)}.")
    return {"heal_round": rnd, "rerun_only": to_rerun, "healing_log": log, "unhealable": unhealable,
            "log": state.get("log", []) + [msg]}


# ------------------------------------------------------------------ evidence repair (the owner's / Jira tests)
#
# A test written by the AI from the owner's / a Jira test case often fails on a page exploring never reached (a cart
# with an item, a checkout step): its locator or expected value was a GUESS about that page. When it failed, the
# generated conftest recorded what that page really showed (results.json "live_page"). The AI rewrites that ONE test
# from this evidence and the test case's own words; the rewrite is accepted only when
#   - it keeps at least as many checks, adds no way to pass without checking (skip, try/except, assert True),
#   - every value the test case itself states (quoted text, numbers) is still checked,
#   - every expected value it checks is grounded: in the test case's words, on the real page or in the explored pages,
#   - it opens no payment page.
# It then runs again (executor._rerun_healed): kept when it passes or now fails on a real check, undone otherwise - and
# healing_log.json shows the before / after and why. One round; a website defect stays a failure.
EVIDENCE_FILES = {"test_flows_ai.py"}
EVIDENCE_CATEGORIES = {"test_defect", "test_mistake", "locator"}
EVIDENCE_TRIES = 3  # (each try starts from the page the test reached last time)
PAYMENT_WORDS = re.compile(r"\bpay(?:ment)?s?\b|paypal|place[-_ ]?order|card[-_ ]?number|\bcvv\b", re.I)
CASE_VALUES = re.compile(r"""['"“‘]([^'"”’]{1,120})['"”’]|(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])""")


def evidence_targets(state: QAState) -> list[dict]:
    """Failures of the owner's / Jira tests that carry the real page they failed on (EVIDENCE_TRIES each)."""
    tries: dict[str, int] = {}
    for h in state.get("healing_log") or []:
        if h.get("method") == "evidence":
            tries[h["nodeid"]] = tries.get(h["nodeid"], 0) + 1
    by_node = {r["nodeid"]: r for r in state.get("results", []) if r.get("live_page")}
    skip = set(state.get("unhealable", []))
    return [f for f in state.get("failures", []) if f.get("file") in EVIDENCE_FILES and f.get("source") == "test"
            and f.get("category") in EVIDENCE_CATEGORIES and f.get("nodeid") in by_node and f["nodeid"] not in skip
            and tries.get(f["nodeid"], 0) < EVIDENCE_TRIES]


def _case_for(test: str, cases: list[dict]) -> dict | None:
    return next((c for c in cases if test in (c.get("tests") or []) and (c.get("my_test") or c.get("instruction"))),
                None)


def _function_source(code: str, name: str) -> tuple[int, int] | None:
    for node in ast.parse(code).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            start = (node.decorator_list[0].lineno if node.decorator_list else node.lineno) - 1
            return start, node.end_lineno
    return None


LOCATING = ADDRESS_CALLS | {"get_by_role", "get_by_text", "get_by_alt_text", "get_by_title", "nth", "filter"}


def _check_values(fn: ast.AST) -> list[str]:
    """The literal values the checks of a function expect (strings and numbers inside assert / expect(...)) - not
    the addresses that only FIND the element (locator('body'), get_by_role('button', name=...))."""
    out = []
    for n in ast.walk(fn):
        node = n.test if isinstance(n, ast.Assert) else n if _is_expect_check(n) else None
        if node is None:
            continue
        address = {id(c) for call in ast.walk(node) if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                   and call.func.attr in LOCATING for arg in [*call.args, *(k.value for k in call.keywords)]
                   for c in ast.walk(arg)}
        for c in ast.walk(node):
            if id(c) not in address and isinstance(c, ast.Constant) and isinstance(c.value, (str, int, float)) \
                    and not isinstance(c.value, bool):
                out.append(str(c.value))
    return out


def evidence_check(old_code: str, new_code: str, test: str, case: dict, live: dict, explored: str) -> str | None:
    """None = the rewrite of `test` may run again; else why it is refused."""
    err = validate_script(new_code)
    if err:
        return err
    old_fns = {n.name: n for n in ast.parse(old_code).body if isinstance(n, ast.FunctionDef)}
    new_fns = {n.name: n for n in ast.parse(new_code).body if isinstance(n, ast.FunctionDef)}
    if set(old_fns) - set(new_fns):
        return f"functions removed: {sorted(set(old_fns) - set(new_fns))}"
    for name in old_fns:  # (only `test` may change)
        if name != test and ast.dump(old_fns[name]) != ast.dump(new_fns[name]):
            return f"{name} was changed too - only {test} may be rewritten"
    old_fn, new_fn = old_fns[test], new_fns[test]
    count = lambda fn: sum(1 for n in ast.walk(fn) if isinstance(n, ast.Assert) or _is_expect_check(n))  # noqa: E731
    if count(new_fn) < count(old_fn) or count(new_fn) == 0:
        return "the rewrite checks less than before"
    src = ast.unparse(new_fn)
    if re.search(r"pytest\.(skip|xfail)|\btry\s*:|\bassert\s+True\b|if\s+False", src):
        return "the rewrite adds a way to pass without checking"
    if PAYMENT_WORDS.search(" ".join(_check_values(new_fn)) + " " + " ".join(
            c.value for c in ast.walk(new_fn) if isinstance(c, ast.Constant) and isinstance(c.value, str))):
        if not PAYMENT_WORDS.search(ast.unparse(old_fn)):
            return "the rewrite points the test at payment"
    words = " ".join(str(case.get(k) or "") for k in ("instruction", "title", "expected", "test_data")) + " " + \
        " ".join(str(s) for s in case.get("steps") or [])
    stated = {(a or b).strip() for a, b in CASE_VALUES.findall(words) if (a or b).strip()}
    new_values = " ".join(_check_values(new_fn)).casefold()
    from .script_generator import quoted_expectations
    must = [q for q in quoted_expectations(case) if q.casefold() not in new_values]
    if must:  # (the result the test case quotes is always checked - a pass without it would prove nothing)
        return f"the rewrite does not check the expected result the test case quotes: {must[0]!r}"
    kept = [v for v in stated if v.casefold() in " ".join(_check_values(old_fn)).casefold()]
    lost = [v for v in kept if v.casefold() not in new_values]
    if lost:
        return f"the rewrite no longer checks what the test case states: {lost[:3]}"
    evidence = (words + " " + json.dumps(live) + " " + explored).casefold()
    for v in _check_values(new_fn):
        v = v.strip()
        if len(v) >= 3 and not re.fullmatch(r"[\W\d_]*", v) and v.casefold() not in evidence and not any(
                ch in v for ch in "[]()*+?\\^$|"):  # (a regex / selector is an address, not an expected value)
            return f"the rewrite expects '{v[:60]}', which neither the test case nor the real page shows"
    return None


def evidence_repair(state: QAState, test_dir: Path, backup_dir: Path, rnd: int) -> tuple[list[dict], list[str]]:
    """Rewrite each target test from the real page it failed on. Returns (log entries, node ids to run again)."""
    if not llm_enabled():
        return [], []
    results = {r["nodeid"]: r for r in state.get("results", [])}
    cases = list(state.get("test_cases") or [])
    explored = json.dumps([{k: lean(p.get(k)) for k in ("url", "title", "headings", "buttons", "inputs")}
                           for p in (state.get("app_map") or [])[:15]])[:20000]
    log, rerun = [], []
    for f in evidence_targets(state):
        entry = {"round": rnd, "file": f["file"], "test": f["test"], "nodeid": f["nodeid"], "error": f.get("error"),
                 "method": "evidence", "change": None, "diff": "", "status": "pending", "backup": None,
                 "from": None, "to": None, "related": [], "rerun": None}
        path, case = test_dir / f["file"], _case_for(f["test"], cases)
        live = results[f["nodeid"]].get("live_page") or {}
        span = _function_source(path.read_text(encoding="utf-8"), f["test"]) if path.is_file() and not \
            path.is_symlink() else None
        if not case or not span:
            entry.update(status="could not heal", change="its test case or its code was not found")
            log.append(entry)
            continue
        before = path.read_text(encoding="utf-8")
        lines = before.splitlines(True)
        old_fn = "".join(lines[span[0]:span[1]])
        try:
            answer = extract_code(ask_llm(load_prompt("evidence_repair").format(
                test=f["test"], case=json.dumps({k: case.get(k) for k in (
                    "title", "instruction", "steps", "expected", "test_data")}, indent=1),
                error=(results[f["nodeid"]].get("error") or "")[-1800:], code=old_fn,
                page=json.dumps(live, indent=1)[:14000]), agent="self_healing", page="evidence", test=f["test"]))
        except LLMError as e:
            entry.update(status="could not heal", change=f"LLM failed: {e}")
            log.append(entry)
            continue
        new_span = _function_source(answer, f["test"]) if answer else None
        if not new_span:
            entry.update(status="could not heal", change="the AI did not return the test function")
            log.append(entry)
            continue
        new_fn = "".join(answer.splitlines(True)[new_span[0]:new_span[1]])
        after = "".join(lines[:span[0]]) + new_fn.rstrip("\n") + "\n" + "".join(lines[span[1]:])
        why = evidence_check(before, after, f["test"], case, live, explored) if after != before else "no change"
        if why:
            entry.update(status="could not heal", change=f"rewrite refused: {why}")
            print(f"  [self-healing] X {f['file']}::{f['test']} - {entry['change']}")
            log.append(entry)
            continue
        if not backup_dir.is_symlink():
            backup = backup_dir / f"{path.stem}.round{rnd}.before.py"  # (the file before this round)
            if not backup.exists():
                shutil.copy(path, backup)
            entry["backup"] = backup.relative_to(Path(state["run_dir"])).as_posix()
        path.write_text(after, encoding="utf-8")
        entry["change"] = f"rewritten from the page it failed on ({live.get('url', '')[:120]})"
        entry["diff"] = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), "before",
                                                     "after", n=1))
        rerun.append(f["nodeid"])
        print(f"  [self-healing] candidate {f['file']}::{f['test']} - {entry['change']} (runs again to decide)")
        log.append(entry)
    return log, rerun


def restore_function(path: Path, backup: Path, name: str) -> None:
    """Put one test function back as it was in the backup (an evidence rewrite that was not kept)."""
    now, was = path.read_text(encoding="utf-8"), backup.read_text(encoding="utf-8")
    a, b = _function_source(now, name), _function_source(was, name)
    if not a or not b:
        return
    lines, old = now.splitlines(True), was.splitlines(True)
    path.write_text("".join(lines[:a[0]]) + "".join(old[b[0]:b[1]]).rstrip("\n") + "\n" + "".join(lines[a[1]:]),
                    encoding="utf-8")
