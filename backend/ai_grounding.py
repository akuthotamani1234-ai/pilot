"""Reject common unsupported AI assertions before they become executable tests."""
import ast
import re


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
    headings = {str(h.get("text", "") if isinstance(h, dict) else h).strip().casefold()
                for page in pages for h in page.get("headings", [])}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "locator" and node.args and isinstance(node.args[0], ast.Constant):
            selector = node.args[0].value
            if not isinstance(selector, str):
                continue
            if selector.strip().startswith("text=") or ">> text=" in selector:
                return "Use observed link selectors or get_by_role with an exact name; broad text= locators also match descriptions"
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
                    return "Bare heading selectors are ambiguous and the document title is not a heading. Use observed heading names or expect(page).to_have_title"
        if node.func.attr == "get_by_text":
            if not any(k.arg == "exact" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords):
                return "Use exact=True for text locators, or an observed role/name or href selector"
        if (node.func.attr == "get_by_role" and node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "heading"):
            name = next((k.value.value for k in node.keywords
                         if k.arg == "name" and isinstance(k.value, ast.Constant)), None)
            if isinstance(name, str) and name.strip().casefold() not in headings:
                return "The heading name was not observed: " + repr(name) + ". Document titles and menu labels are not heading evidence"
    for assertion in (n for n in ast.walk(tree) if isinstance(n, ast.Assert)):
        if not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_said"
                   for n in ast.walk(assertion)):
            continue
        for compare in (n for n in ast.walk(assertion) if isinstance(n, ast.Compare)):
            if isinstance(compare.left, ast.Constant) and isinstance(compare.left.value, str) and any(
                    isinstance(op, ast.In) for op in compare.ops):
                expected = compare.left.value.casefold().removeprefix("alert: ").strip()
                if expected and expected not in known_messages:
                    return "The asserted message text was not observed or required: " + repr(compare.left.value) + ". Check a grounded result or explicitly skip unknown evidence"
    return None
