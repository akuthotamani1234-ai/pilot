"""The tester's own tests must not depend on your .env (no AI calls, no visible browser, no slow motion,
no real test account). These values are set before backend.config reads .env, so they win."""
import os

os.environ.update({
    "LLM_PROVIDER": "none", "LLM_MODEL": "", "HEADLESS": "true", "SLOW_MO_MS": "0", "MAX_PAGES": "0", "MAX_DEPTH": "0",
    "AUTO_REGISTER": "false", "TEST_USERNAME": "", "TEST_PASSWORD": "", "TEST_WORKERS": "1", "ALLOWED_HOSTS": "",
    "EXCLUDE_PATHS": "", "LOGIN_URL": "", "LOGIN_USER_SELECTOR": "", "LOGIN_PASSWORD_SELECTOR": "",
    "LOGIN_SUBMIT_SELECTOR": "", "LOGIN_SUCCESS_TEXT": "", "LOGIN_SUCCESS_URL": "", "QA_REQUIREMENTS": "",
    "CRAWL_SCOPE": "auto", "MAX_HEAL_ROUNDS": "2", "VISION": "auto", "VISION_MAX_FAILURES": "60",
    # live screens are for watching a run; they change worker timing that crawl tests count on (test_live_swarm.py)
    "QA_LIVE_FRAMES": "false",
    # crawl tests count requests in a fixed order; the parallel control learners have their own tests
    "EXPLORE_WORKERS": "0",
    # the applications' feature inventories (backend/inventory.py) of test runs never land in the repository
    "QPILOT_INVENTORY_DIR": os.path.join(__import__("tempfile").gettempdir(), "qpilot-test-inventory"),
})


# ---------------------------------------------------------------- the generated tests' conftest, loaded in-process
# backend/templates/conftest.py is made for a generated-test run: loading it patches Playwright's classes for the
# whole process (Page.goto refuses checkout and payment pages, Locator clicks are guarded, page.request only reads...)
# and adds pytest.qa_step. A test of this repo that loads it must leave the next tests an unpatched Playwright,
# or they skip ("Blocked: checkout or payment ...") or behave differently depending on which worker ran what before.

import importlib.util
from pathlib import Path

import pytest

_TEMPLATE_CONFTEST = Path(__file__).resolve().parent.parent / "backend" / "templates" / "conftest.py"


def _patchable():
    """The Playwright classes the template conftest patches."""
    from playwright._impl._sync_base import SyncBase
    from playwright.sync_api import APIRequestContext, Locator, Page
    return (Page, Locator, APIRequestContext, SyncBase)


def _snapshot() -> dict:
    snap = {cls: dict(vars(cls)) for cls in _patchable()}
    snap[pytest] = {"qa_step": vars(pytest).get("qa_step", _MISSING)}
    return snap


_MISSING = object()


def _restore(snap: dict) -> None:
    for owner, before in snap.items():
        if owner is pytest:
            if before["qa_step"] is _MISSING:
                vars(pytest).pop("qa_step", None)
            else:
                pytest.qa_step = before["qa_step"]
            continue
        now = dict(vars(owner))
        for name in now.keys() - before.keys():
            delattr(owner, name)
        for name, value in before.items():
            if now.get(name, _MISSING) is not value:
                setattr(owner, name, value)


def _changes(snap: dict) -> list[str]:
    out = []
    for owner, before in snap.items():
        if owner is pytest:
            if vars(pytest).get("qa_step", _MISSING) is not before["qa_step"]:
                out.append("pytest.qa_step")
            continue
        now = vars(owner)
        out += [f"{owner.__name__}.{n}" for n in sorted(set(now) ^ set(before))]
        out += [f"{owner.__name__}.{n}" for n in sorted(set(now) & set(before)) if now[n] is not before[n]]
    return out


@pytest.fixture
def template_conftest():
    """Load backend/templates/conftest.py as a module; Playwright and pytest are restored after the test."""
    snap = _snapshot()
    loaded = []

    def load(name: str = "qa_template_conftest"):
        spec = importlib.util.spec_from_file_location(name, _TEMPLATE_CONFTEST)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        loaded.append(module)
        return module
    yield load
    _restore(snap)


@pytest.fixture(autouse=True)
def _playwright_left_unpatched(request):
    """Every test leaves Playwright's classes as it found them (catches the next in-process load of the template)."""
    snap = _snapshot()
    yield
    changed = _changes(snap)
    if changed:
        _restore(snap)  # (the next tests still get a clean Playwright)
        pytest.fail(f"{request.node.nodeid} left Playwright patched: {', '.join(changed[:8])}. Load "
                    "backend/templates/conftest.py through the template_conftest fixture.", pytrace=False)


# ---------------------------------------------------------------- the execution preflight (backend/execution_preflight)
# Starting a Jira execution now checks the AI and opens the website once in a real browser. Tests that start an
# execution with a replaced run launcher get a ready stub instead - no network, no AI. Tests of the preflight itself
# are marked real_preflight.

@pytest.fixture(autouse=True)
def _execution_preflight_stub(request, monkeypatch):
    if request.node.get_closest_marker("real_preflight"):
        return
    import backend.execution_preflight as pre
    monkeypatch.setattr(pre, "ai_status", lambda requested="", model="", api_key="": {
        "requested": requested, "configured": "stub", "privacy_mode": "local", "model": model, "provider": requested,
        "ready": True, "reason": "", "recovery": ""})
    monkeypatch.setattr(pre, "browser_probe", lambda url, timeout_s=25: {
        "ok": True, "browser": True, "login_form": False, "title": "", "final_url": url, "error": ""})
