"""Reject common unsupported AI assertions before they become executable tests.

Grounding rules (reusable — never site-specific hardcoding):
  * selectors / headings / controls / expected messages must appear in observed page state or an explicit contract
  * invented business records (e.g. "John Doe") are refused unless seeded/observed
  * brittle toast-wrapper / icon class matches are refused; prefer message text + semantic severity
  * role-based tables are fine without assuming a native <table>
  * failures here are exploratory/unsupported reasons — never confirmed product defects
"""
import ast
import re

# Common invented demo people — not evidence unless the page/contract actually lists them.
INVENTED_PEOPLE = re.compile(
    r"\b(john(?:\s+doe)?|jane(?:\s+doe)?|foo\s+bar|asdf|lorem(?:\s+ipsum)?|test\s+user\s+1)\b",
    re.I,
)
# Toast / snackbar wrapper shells that AI often matches by class instead of message+severity.
TOAST_WRAPPER = re.compile(
    r"(?:^|[.#\[ ])(?:oxd-toast|toast(?:-container)?|snackbar|MuiSnackbar|alert-wrapper|notification-wrapper)\b",
    re.I,
)
NATIVE_TABLE_ONLY = re.compile(r"^table(?:\s|>|$)|^\s*table\b", re.I)


def account_permission_reason(case: dict, *, allow_signup: bool, has_account: bool) -> str:
    text = " ".join([str(case.get("title") or ""), str(case.get("expected") or ""),
                     *map(str, case.get("steps") or [])]).lower()
    signup = re.search(r"sign ?up|register|registration|create an account", text)
    submits = re.search(r"submit|register|creat|success", text)
    if signup and submits and not allow_signup:
        return "Account creation was not approved for this run"
    negative = re.search(r"wrong|invalid|incorrect|reject|nonexistent|does not exist|not log|fail", text)
    if re.search(r"log ?in|sign ?in", text) and not negative and not has_account:
        if re.search(r"logged in|welcome|dashboard|success|test account", text):
            return "A successful login needs an approved test account"
    return ""


def _observed_text(pages: list[dict], requirements: str = "") -> str:
    bits = [requirements or ""]
    for page in pages:
        bits.append(str(page.get("title") or ""))
        for h in page.get("headings", []):
            bits.append(str(h.get("text", "") if isinstance(h, dict) else h))
        for b in page.get("behaviour", []):
            bits.append(str(b.get("message") or ""))
        bits.extend(str(m) for m in (page.get("seen") or {}).get("messages", []) or [])
        for group in ("buttons", "inputs", "links", "forms"):
            for el in page.get(group, []) or []:
                bits.append(str(el.get("text") or el.get("label") or el.get("name") or el.get("placeholder") or ""))
        for name in (page.get("itemNames") or page.get("productNames") or [])[:40]:
            bits.append(str(name))
        for row in (page.get("tables") or []):
            for cell in (row.get("sample") or row.get("headers") or [])[:40]:
                bits.append(str(cell))
    return " ".join(bits).casefold()


def _observed_selectors(pages: list[dict]) -> set[str]:
    out: set[str] = set()
    for page in pages:
        for group in ("buttons", "inputs", "links", "forms", "hovers", "draggables"):
            for el in page.get(group, []) or []:
                sel = el.get("selector")
                if isinstance(sel, str) and sel.strip():
                    out.add(sel.strip())
                if group == "forms":
                    sub = (el.get("submit") or {}).get("selector")
                    if isinstance(sub, str) and sub.strip():
                        out.add(sub.strip())
                    for field in el.get("fields") or []:
                        fsel = field.get("selector")
                        if isinstance(fsel, str) and fsel.strip():
                            out.add(fsel.strip())
        for t in page.get("tables") or []:
            for key in ("selector", "search", "page_size"):
                sel = t.get(key)
                if isinstance(sel, str) and sel.strip():
                    out.add(sel.strip())
    return out


def invented_record_problem(text: str, pages: list[dict], requirements: str = "") -> str | None:
    """Reject invented business people/records unless they appear in observation or requirements."""
    known = _observed_text(pages, requirements)
    for match in INVENTED_PEOPLE.finditer(text or ""):
        name = match.group(0).strip()
        if name.casefold() not in known:
            return (f"Invented business record {name!r} was not observed or seeded. "
                    "Use run-owned tagged data or an observed/required name — unsupported, not a product defect")
    return None


def grounding_problem(code: str, pages: list[dict], requirements: str = "") -> str | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None  # the existing syntax validator reports this
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    messages = [str(b.get("message") or "") for page in pages for b in page.get("behaviour", [])]
    messages += [str(message) for page in pages for message in (page.get("seen") or {}).get("messages", [])]
    messages.append(requirements)
    known_messages = " ".join(messages).casefold()
    known_text = _observed_text(pages, requirements)
    headings = {str(h.get("text", "") if isinstance(h, dict) else h).strip().casefold()
                for page in pages for h in page.get("headings", [])}
    observed_sels = _observed_selectors(pages)
    # Case / step text may also invent people outside the script AST constants — checked on whole code.
    people = invented_record_problem(code, pages, requirements)
    if people:
        return people

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "locator" and node.args and isinstance(node.args[0], ast.Constant):
            selector = node.args[0].value
            if not isinstance(selector, str):
                continue
            if selector.strip().startswith("text=") or ">> text=" in selector:
                return ("Use observed link selectors or get_by_role with an exact name; "
                        "broad text= locators also match descriptions")
            if TOAST_WRAPPER.search(selector) and "text=" not in selector and "has-text" not in selector:
                return ("Prefer the toast/alert message text and semantic severity "
                        "(error/ok via role=alert / status), not a brittle toast wrapper/icon selector")
            if NATIVE_TABLE_ONLY.match(selector.strip()) and "role" not in selector:
                # Allow only when a native table was observed; otherwise ask for role-based grid.
                has_native = any((t.get("selector") or "").startswith("table") or t.get("native")
                                 for page in pages for t in page.get("tables") or [])
                if not has_native:
                    return ("Do not assume a native <table>; use an observed role=table / grid / rowgroup "
                            "selector from the page model")
            if re.fullmatch(r"h[1-6]", selector.strip(), re.I):
                parent = node
                count_only = False
                for _ in range(5):
                    parent = parents.get(parent)
                    if parent is None:
                        break
                    if isinstance(parent, ast.Attribute) and parent.attr in ("count", "to_have_count"):
                        count_only = True
                if not count_only:
                    return ("Bare heading selectors are ambiguous and the document title is not a heading. "
                            "Use observed heading names or expect(page).to_have_title")
            # Long CSS ids/classes that look recorded but never appeared in observation — reject (hard).
            if (observed_sels and selector.strip() not in observed_sels
                    and re.search(r"[#.\[]", selector) and len(selector.strip()) > 3
                    and not selector.strip().startswith(("text=", "xpath=", "internal:"))):
                return (f"Selector {selector.strip()!r} was not observed on the page. "
                        "Use get_by_role / get_by_label against an observed control — "
                        "unsupported locator, not a product defect")
        if node.func.attr == "get_by_text":
            if not any(k.arg == "exact" and isinstance(k.value, ast.Constant) and k.value.value is True
                       for k in node.keywords):
                return "Use exact=True for text locators, or an observed role/name or href selector"
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                needle = node.args[0].value.strip()
                if needle and needle.casefold() not in known_text:
                    people = invented_record_problem(needle, pages, requirements)
                    if people:
                        return people
                    if INVENTED_PEOPLE.search(needle):
                        return (f"Text {needle!r} was not observed on the page or in requirements. "
                                "Unsupported assertion — not a confirmed product defect")
        if (node.func.attr == "get_by_role" and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "heading"):
            name = next((k.value.value for k in node.keywords
                         if k.arg == "name" and isinstance(k.value, ast.Constant)), None)
            if isinstance(name, str) and name.strip().casefold() not in headings:
                return ("The heading name was not observed: " + repr(name)
                        + ". Document titles and menu labels are not heading evidence")
        if (node.func.attr == "get_by_role" and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in ("table", "grid", "row", "rowgroup", "columnheader", "cell")):
            # Role-based tables are explicitly allowed even when no native <table> exists.
            pass
    for assertion in (n for n in ast.walk(tree) if isinstance(n, ast.Assert)):
        if not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_said"
                   for n in ast.walk(assertion)):
            continue
        for compare in (n for n in ast.walk(assertion) if isinstance(n, ast.Compare)):
            if isinstance(compare.left, ast.Constant) and isinstance(compare.left.value, str) and any(
                    isinstance(op, ast.In) for op in compare.ops):
                expected = compare.left.value.casefold().removeprefix("alert: ").strip()
                if expected and expected not in known_messages:
                    return ("The asserted message text was not observed or required: "
                            + repr(compare.left.value)
                            + ". Check a grounded result or explicitly skip unknown evidence")
    return None


def unsupported_reason(problem: str) -> str:
    """Human-facing skip/block reason: exploratory/unsupported, never a product-defect claim."""
    text = (problem or "").strip() or "The proposed script is not grounded in observed page state or a contract"
    if text.lower().startswith("unsupported"):
        return text
    return f"Unsupported (exploratory): {text}. Not reported as a product defect."
