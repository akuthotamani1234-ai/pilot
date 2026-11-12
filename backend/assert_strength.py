"""How strong is each generated test's proof? Read from the code itself (AST), following the calls it makes into the
steps modules and helpers of the run:

  strong   it checks a state or a value: `expect(...).to_*`, or an assert about something other than errors
           (the sorted column, the row that contains the word, the URL, a box's value ...)
  weak     it only checks that nothing broke: console / JavaScript errors, an HTTP status, a page title
  none     no check at all (a pass would prove nothing - the sandbox reports such a test as inconclusive anyway)

A test that PASSED with only weak checks is a "smoke" test: it says the page did not break, never that a feature works.
It never makes a feature "verified" (backend/registry.py). Saved as runs/<run>/strength.json  {"file::test": strength}.
"""
import ast
import json
from pathlib import Path

# what a weak check talks about: the errors of the page, its status, its title
WEAK_NAMES = {"console_errors", "new_errors", "errors", "errors_before", "bad", "broken", "js_errors", "resp",
              "response", "status", "failed", "problems"}
WEAK_ATTRS = {"status", "title", "ok"}
RANK = {"none": 0, "weak": 1, "strong": 2}


def _assert_strength(node: ast.Assert) -> str:
    names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(node.test) if isinstance(n, ast.Attribute)}
    calls = {n.func.attr for n in ast.walk(node.test) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    if not names and not attrs:
        return "weak"  # (assert True / a constant)
    if names <= WEAK_NAMES | {"len"} and (attrs <= WEAK_ATTRS) and not (calls - {"title", "strip"}):
        return "weak"
    return "strong"


def _own(fn: ast.AST) -> str:
    """The strongest check written directly in this function."""
    best = "none"
    for n in ast.walk(fn):
        s = "none"
        if isinstance(n, ast.Assert):
            s = _assert_strength(n)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr.startswith("to_") \
                and isinstance(n.func.value, ast.Call) and isinstance(n.func.value.func, ast.Name) \
                and n.func.value.func.id == "expect":
            s = "strong"
        if RANK[s] > RANK[best]:
            best = s
    return best


def _calls(fn: ast.AST) -> list[tuple[str | None, str]]:
    """(module or None, function) of every call in the function: helper() and steps_page.step_x()."""
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name):
                out.append((None, n.func.id))
            elif isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name):
                out.append((n.func.value.id, n.func.attr))
    return out


def analyse(test_dir: Path) -> dict[str, str]:
    """{"<file>::<test function>": strong | weak | none} for every test of the run's generated files."""
    mods = {}
    for f in Path(test_dir).glob("*.py"):
        if f.name == "conftest.py":
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        mods[f.stem] = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    def strength(mod: str, name: str, seen: set) -> str:
        fn = mods.get(mod, {}).get(name)
        if fn is None or (mod, name) in seen or len(seen) > 40:
            return "none"
        seen.add((mod, name))
        best = _own(fn)
        for m, called in _calls(fn):
            if best == "strong":
                break
            target = mod if m is None else m
            if target in mods:
                s = strength(target, called, seen)
                if RANK[s] > RANK[best]:
                    best = s
        return best

    out = {}
    for mod, fns in mods.items():
        if not mod.startswith("test_"):
            continue
        for name in fns:
            if name.startswith("test_"):
                out[f"{mod}.py::{name}"] = strength(mod, name, set())
    return out


def save(run_dir: Path) -> dict[str, str]:
    data = analyse(Path(run_dir) / "generated_tests")
    (Path(run_dir) / "strength.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


def load(run_dir: Path) -> dict[str, str]:
    try:
        return json.loads((Path(run_dir) / "strength.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def of_result(r: dict, table: dict[str, str]) -> str:
    """The strength of one single test result (its function, without the [parameter] part)."""
    return table.get(f"{r.get('file')}::{(r.get('test') or '').split('[')[0]}", "strong")
