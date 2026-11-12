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


def _file_with(selector: str, test_dir: Path, failed_file: str) -> str | None:
    """Which generated file holds the broken selector: the failing file, else the step module it calls."""
    names = [failed_file] + sorted(f.name for f in test_dir.glob("steps_*.py")) \
        + sorted(f.name for f in test_dir.glob("test_*.py"))
    for name in dict.fromkeys(names):
        f = test_dir / name
        if f.exists():
            code = f.read_text(encoding="utf-8")
            if repr(selector) in code or json.dumps(selector) in code:
                return name
    return None


def _baseline_map(state: QAState) -> list[dict]:
    """The pages of the last run (the baseline) - where an old selector came from."""
    ch = state.get("changes") or {}
    f = Path(ch["baseline_dir"], "app_map.json") if ch.get("baseline_dir") else None
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f and f.exists() else []
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
    if not f.exists():
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


def _safe_repair(old_code: str, new_code: str, need_tests: bool = True) -> str | None:
    """Returns an error if the repaired code is not acceptable (need_tests=False: a steps_*.py module)."""
    err = validate_script(new_code, need_tests=need_tests)
    if err:
        return err
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
    backup_dir.mkdir(exist_ok=True)
    rnd = state.get("heal_round", 0) + 1
    unhealable = list(state.get("unhealable", []))
    log = list(state.get("healing_log", []))
    to_rerun = []

    from .failure_analysis import healable
    targets = [f for f in state.get("failures", []) if healable(f) and f.get("nodeid") not in unhealable]
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
        if bad and bad in fixed:  # an earlier test already got this selector repaired this round
            done = fixed[bad]
            entry.update(file=done["file"], method=done["method"], backup=done["backup"], to=done["to"],
                         change=f"{bad}  ->  {done['to']} (already repaired this round)")
            entry["from"] = bad
            log.append(entry)
            to_rerun.append(f["nodeid"])
            continue
        # the broken selector may live in another file than the failing test (e.g. steps_<page>.py)
        holder = (_file_with(bad, test_dir, f["file"]) if bad else None) or f["file"]
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

        if after is None:
            entry["status"] = "could not heal"
            entry["change"] = why_not or "no safe repair found"
            unhealable.append(f["nodeid"])
            print(f"  [self-healing] X {f['file']}::{f['test']} - {entry['change']}")
        else:
            backup = backup_dir / f"{path.stem}.round{rnd}.before.py"
            if not backup.exists():  # the file as it was before THIS round (kept: evidence, and to undo the repair)
                shutil.copy(path, backup)
            entry["backup"] = backup.relative_to(run_dir).as_posix()
            path.write_text(after, encoding="utf-8")
            entry["diff"] = "".join(difflib.unified_diff(
                before.splitlines(True), after.splitlines(True), "before", "after", n=1))
            if bad and entry["to"]:
                fixed[bad] = {"file": holder, "method": entry["method"], "to": entry["to"], "backup": entry["backup"]}
            to_rerun.append(f["nodeid"])
            print(f"  [self-healing] candidate {f['file']}::{f['test']} - {entry['change']} (runs again to decide)")
        log.append(entry)

    (run_dir / "healing_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    msg = (f"Self-healing round {rnd}: {len(to_rerun)} repair candidate(s) - they run again before anything is "
           f"called repaired; no safe repair for {len(targets) - len(to_rerun)}.")
    return {"heal_round": rnd, "rerun_only": to_rerun, "healing_log": log, "unhealable": unhealable,
            "log": state.get("log", []) + [msg]}
