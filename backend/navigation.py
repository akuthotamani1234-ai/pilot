"""Observed opener paths shared by discovery and generated tests."""
import inspect


def opener_path(entry: dict, selector: str, parent: str | None = None) -> list[dict]:
    controls = {}
    for group in ("buttons", "inputs", "hovers", "forms"):
        for item in entry.get(group, []):
            if item.get("selector"):
                controls.setdefault(item["selector"], dict(item, action="hover" if group == "hovers" else "click"))
    for item in entry.get("behaviour", []):
        if item.get("selector"):
            controls[item["selector"]] = dict(controls.get(item["selector"], {}), **item)
    current = parent if parent is not None else (controls.get(selector) or {}).get("revealed_by")
    seen, path = {selector}, []
    while current:
        if current in seen or len(path) >= 8:
            raise ValueError("Observed opener path contains a cycle or exceeds eight steps")
        seen.add(current)
        item = controls.get(current, {})
        path.append({"selector": current, "action": item.get("action") or "click",
                     "value": item.get("value"), "name": item.get("name") or item.get("control") or item.get("text") or ""})
        current = item.get("revealed_by")
    return list(reversed(path))


def open_path(page, path: list[dict], target: str | None = None) -> None:
    from playwright.sync_api import expect
    if len(path) > 8:
        raise ValueError("Observed opener path exceeds eight steps")
    seen = set()
    for step in path:
        if target and page.locator(target).first.is_visible():
            break
        selector = step["selector"]
        if selector in seen:
            raise ValueError("Observed opener path contains a cycle")
        seen.add(selector)
        el = page.locator(selector).first
        expect(el, "The recorded opener must be visible before using its child").to_be_visible()
        action = step.get("action") or "click"
        if action == "hover":
            el.hover(timeout=5000)
        elif action == "select":
            el.select_option(step["value"], timeout=5000)
        elif action == "tick":
            el.check(timeout=5000)
        elif action == "click":
            el.click(timeout=5000)
        else:
            raise ValueError("Unsupported opener action: " + action)
        page.wait_for_timeout(300)
    if target:
        expect(page.locator(target).first, "The recorded path must reveal the target").to_be_visible()


OPEN_PATH_HELPER = inspect.getsource(open_path)
