"""Browser adapter for the same approved contracts used by native and hybrid QA."""

import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from .qa_contracts import contract_cases, origin, parse_contract
from .qa_oracles import resolve_private_inputs
from .qa_runtime import ContractRuntime
from .safety import Scope, guard_context, redact


class BrowserContractAdapter:
    def __init__(self, page, start_url, contract, stop_path=None):
        if contract.android_package:
            raise ValueError('These test flows target a native Android app, not a Playwright website')
        if contract.test_mode:
            raise ValueError('These flows were made by Android test mode; run them in an Android Chrome test-mode run')
        self.page, self.start_url, self.contract = page, start_url, contract
        self.stop_path = Path(stop_path) if stop_path else None
        self.origins = {origin(start_url), *[origin(u) for u in contract.allowed_origins]}

    def guard(self):
        if self.stop_path and self.stop_path.exists():
            raise InterruptedError("The approved browser flow was stopped by the user")
        if origin(self.page.url) not in self.origins:
            raise ValueError("The browser contract left its approved origins")

    def context(self, target):
        if target != "native":
            raise ValueError("WebView context steps belong to Android; browser flows use CSS directly")

    def find(self, locator, optional=False):
        self.guard()
        if locator.strategy != "css":
            raise ValueError("Browser contracts require CSS locators")
        selected = self.page.locator(locator.value)
        deadline = time.monotonic() + (0 if optional else 8)
        while True:
            self.guard()
            visible = [selected.nth(i) for i in range(selected.count()) if selected.nth(i).is_visible()]
            if visible or time.monotonic() >= deadline:
                break
            self.page.wait_for_timeout(100)
        if not visible and optional:
            return None
        if len(visible) != 1:
            raise ValueError("The browser locator must select exactly one visible control")
        return visible[0]

    def assert_screen(self, title):
        assert self.page.title().casefold() == title.casefold(), "The expected page title was not reached."

    @staticmethod
    def identity(element):
        return " ".join(
            [element.inner_text(), *[(element.get_attribute(k) or "") for k in ("id", "name", "aria-label", "type")]]
        )

    @staticmethod
    def input_sensitive(element):
        return element.evaluate("element => ['INPUT','TEXTAREA'].includes(element.tagName)")

    @staticmethod
    def tap(element):
        element.click(timeout=10000)

    def open(self, url):
        """Open a page inside the approved origins (an `open` flow step)."""
        if origin(url) not in self.origins:
            raise ValueError("The browser contract may open only pages of its approved origins")
        self.page.goto(url, timeout=30000)
        self.guard()

    @staticmethod
    def fill(element, value):
        element.fill(value, timeout=10000)

    @staticmethod
    def select(element, value):
        element.select_option(value=value, timeout=10000)
        assert element.input_value() == value, "Dropdown selection was not retained"

    @staticmethod
    def swipe(element, direction):
        raise ValueError("Swipe steps currently require native Android testing")

    @staticmethod
    def drag(element, target):
        raise ValueError("Drag steps currently require native Android testing")

    @staticmethod
    def scroll_to(container, target, direction):
        raise ValueError("Scroll-to-target steps currently require native Android testing")

    @staticmethod
    def text(element):
        return element.inner_text()

    @staticmethod
    def enabled(element):
        return element.is_enabled()

    @staticmethod
    def checked(element):
        if element.get_attribute('type') in {'checkbox', 'radio'}:
            return element.is_checked()
        if element.get_attribute('role') in {'switch', 'checkbox', 'radio'}:
            return element.get_attribute('aria-checked') == 'true'
        raise ValueError('Checked-state assertions require a checkbox, switch or radio control')

    @staticmethod
    def visible(element):
        return element.is_visible()


def run_contracts(run_dir, url, contract_value, headless=True):
    from playwright.sync_api import sync_playwright

    contract = parse_contract(contract_value)
    from .android_design import normalize_case

    cases = [normalize_case(c) for c in contract_cases(contract)]
    for case in cases:
        case.update(
            target_type="web",
            platform="web",
            url=url,
            page="contract",
            preconditions=["Approved test environment", "Target website reachable"],
            pages=["contract"],
            files=["qa_contracts.json"],
            tests=["test_" + case["id"]],
            script_source="contract",
        )
    Path(run_dir, "qa_contracts.json").write_text(contract.model_dump_json(indent=2), encoding="utf-8")
    private = resolve_private_inputs(contract)
    results = []
    secrets = list(private["secrets"].values())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            for case in cases:
                started = time.monotonic()
                record = {
                    "id": case["id"],
                    "contract_id": case["contract_id"],
                    "title": case["title"],
                    "file": "qa_contracts.json",
                    "test": "test_" + case["id"],
                    "nodeid": "qa_contracts.json::test_" + case["id"],
                    "url": url,
                    "outcome": "blocked" if case["blocked"] else "passed",
                    "checks": 0,
                    "error": "",
                }
                if not case["blocked"]:
                    context = browser.new_context()
                    scope = Scope(url, [urlsplit(u).hostname for u in contract.allowed_origins])
                    guard_context(context, scope, [])

                    # Enforce approved origins on every navigation, before sending its request.
                    def route_request(route):
                        request = route.request
                        if request.is_navigation_request() and origin(request.url) not in {
                            origin(url),
                            *[origin(u) for u in contract.allowed_origins],
                        }:
                            route.abort("blockedbyclient")
                        else:
                            route.fallback()

                    context.route("**/*", route_request)
                    page = context.new_page()
                    runtime = ContractRuntime(
                        BrowserContractAdapter(page, url, contract, stop_path=Path(run_dir) / "STOP"), contract.model_dump(), private
                    )
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        runtime.execute(case["contract_id"])
                    except Exception as error:
                        record.update(
                            outcome="failed" if isinstance(error, AssertionError) else "error",
                            exception_type=type(error).__name__,
                            error_type=type(error).__name__,
                            error=redact(str(error), secrets),
                        )
                    finally:
                        record.update(
                            checks=runtime.checks,
                            contract_evidence=runtime.evidence,
                            live_steps=runtime.steps,
                            authentication_verified=runtime.authentication_verified,
                        )
                        context.close()
                record["duration_s"] = round(time.monotonic() - started, 3)
                results.append(record)
        finally:
            browser.close()
    Path(run_dir, "contract_results.json").write_text(redact(json.dumps(results, indent=2), secrets), encoding="utf-8")
    return {"test_cases": cases, "results": results}


def execute_pipeline_contracts(state):
    path = Path(state["run_dir"]) / ".private" / "qa_contract.json"
    value = path.read_text(encoding="utf-8") if path.exists() else os.environ.get("QA_CONTRACT_JSON", "")
    if not value.strip():
        return {"test_cases": [], "results": []}
    # This is maintained framework code; arbitrary generated Python is never executed here.
    try:
        return run_contracts(state["run_dir"], state["url"], value)
    except Exception as error:
        from .android_design import normalize_case

        try:
            configured = contract_cases(parse_contract(value))
        except ValueError:
            configured = [
                {
                    "id": "contract_configuration",
                    "contract_id": "configuration",
                    "title": "QA contract configuration",
                    "kind": "contract",
                    "expected": "The explicit QA configuration is valid.",
                }
            ]
        cases, results = [], []
        for case in configured:
            case = normalize_case(case)
            case.update(target_type="web", platform="web", url=state["url"], files=["qa_contracts.json"])
            cases.append(case)
            results.append(
                {
                    "id": case["id"],
                    "contract_id": case.get("contract_id"),
                    "file": "qa_contracts.json",
                    "test": "test_" + case["id"],
                    "nodeid": "qa_contracts.json::test_" + case["id"],
                    "url": state["url"],
                    "outcome": "blocked" if case.get("blocked") else "error",
                    "checks": 0,
                    "duration_s": 0,
                    "error_type": "ContractConfigurationError",
                    "exception_type": "ContractConfigurationError",
                    "error": redact(str(error))[:500],
                }
            )
        Path(state["run_dir"], "contract_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        return {"test_cases": cases, "results": results}
