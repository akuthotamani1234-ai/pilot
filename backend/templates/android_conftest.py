"""Trusted mobile fixtures and evidence hooks, copied beside validated generated scripts."""

import json
import os
from pathlib import Path

import pytest

from backend.android import (
    AndroidEnvironmentError,
    capture_screenshot,
    close_session,
    create_session,
    inspect_driver,
    interaction_blocker,
    reset_app_data,
)
from backend.android_evidence import app_problem, device_time, read_log, save_log, start_recording, stop_recording
from backend.android_runtime import MobileRuntime, device_unavailable, read_only_case, same_screen
from backend.safety import redact

RUN = Path(os.environ["ANDROID_MOBILE_CONFIG"]).resolve().parent.parent
CONFIG = json.loads(Path(os.environ["ANDROID_MOBILE_CONFIG"]).read_text(encoding="utf-8"))
CASES = json.loads(Path(os.environ["ANDROID_MOBILE_CASES"]).read_text(encoding="utf-8"))
SCREENS = json.loads((RUN / "screens.json").read_text(encoding="utf-8"))
UNAVAILABLE = RUN / "android_execution_unavailable.json"


def _append(name, record):
    with (RUN / name).open("a", encoding="utf-8") as output:
        output.write(redact(json.dumps(record, ensure_ascii=False)) + "\n")


def _result(item, report):
    message = getattr(item, "mobile_exception_message", "")
    error = (message + "\n" + str(report.longrepr))[:2000] if report.failed else ""
    return {
        "id": item.name.removeprefix("test_"),
        "test": item.name,
        "file": item.path.name,
        "outcome": ("failed" if getattr(item, "mobile_exception_type", "") == "AssertionError" else "error")
        if report.failed
        else "inconclusive"
        if report.skipped
        else "passed",
        "error": error,
        "duration_s": report.duration,
        "exception_type": getattr(item, "mobile_exception_type", ""),
        "exception_message": message,
        "url": CONFIG.get("start_url") or "android://app",
    }


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if call.excinfo:
        item.mobile_exception_type = call.excinfo.type.__name__
        item.mobile_exception_message = redact(str(call.excinfo.value))[:1000]
        if device_unavailable(call.excinfo.value) and not UNAVAILABLE.exists():
            UNAVAILABLE.write_text(json.dumps({"case": item.name, "error": item.mobile_exception_message}), encoding="utf-8")
    if report.when == "call":
        item.mobile_report = report
    elif report.when == "setup" and report.failed:
        record = _result(item, report)
        record["outcome"] = "error"
        _append("android_results.jsonl", record)
    elif report.when == "setup" and report.skipped and UNAVAILABLE.exists():
        record = _result(item, report)
        record.update(outcome="blocked", error="Not executed after Android/device session became unavailable: "
                      + json.loads(UNAVAILABLE.read_text(encoding="utf-8"))["error"])
        _append("android_results.jsonl", record)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    if UNAVAILABLE.exists():
        pytest.skip("Android device/session is unavailable; remaining tests were not attempted.")


@pytest.fixture(scope="session")
def appium_driver():
    if (RUN / "STOP").exists():
        raise AndroidEnvironmentError("The mobile run was stopped by the user.")
    driver = create_session(CONFIG)
    session_file = RUN / ".private" / "active_appium_session.json"
    try:
        session_file.write_text(json.dumps({"session_id": driver.session_id}), encoding="utf-8")
        if CONFIG.get("app_mode") == "installed" and not interaction_blocker(CONFIG):
            # Test-build mode explored a freshly reset app: the read-only checks start from that same state.
            reset_app_data(driver, SCREENS[0]["package_name"])
        yield driver
    finally:
        cleanup = close_session(driver)
        if not cleanup:
            session_file.unlink(missing_ok=True)
        if cleanup:
            record = {
                    "id": "android_session_cleanup",
                    "test": "session_cleanup",
                    "file": "test_android_generated.py",
                    "outcome": "error",
                    "exception_type": "AndroidEnvironmentError",
                    "error": cleanup,
                }
            _append("android_cleanup.jsonl", record)
            if not UNAVAILABLE.exists():
                _append("android_results.jsonl", record)


@pytest.fixture
def mobile(request, appium_driver):
    case = next(c for c in CASES if "test_" + c["id"] == request.node.name)
    if (RUN / "STOP").exists():
        raise AndroidEnvironmentError("The mobile run was stopped by the user.")
    driver = appium_driver
    activity = CONFIG.get("app_activity")
    reuse = False
    read_only = read_only_case(case)
    if read_only and getattr(driver, "_blowai_previous_read_only", False):
        target_id = next(args[0] for method, args in case["plan"] if method == "open_screen")
        target = next(s for s in SCREENS if s["id"] == target_id)
        if not target.get("authentication_flow_id"):
            try:
                reuse = same_screen(inspect_driver(driver, {**CONFIG, "package_name": SCREENS[0]["package_name"]}), target)
            except AndroidEnvironmentError as error:
                if device_unavailable(error):
                    raise
    if CONFIG.get("app_mode") != "web" and not interaction_blocker(CONFIG):
        # Test mode: a permission prompt or the keyboard an earlier test left in front never fails this test
        from backend.android import bring_app_back

        bring_app_back(driver, {**CONFIG, "package_name": SCREENS[0]["package_name"]})
    if reuse:
        pass  # The frozen plan has no mutations; verify its screen again in open_screen.
    elif CONFIG.get("app_mode") == "web" and case.get("reset_app_data") and not interaction_blocker(CONFIG):
        # A test-mode flow on a website starts as a first-time visitor: this website's cookies and storage cleared.
        from backend.android_web import reset_site_data

        reset_site_data(driver, CONFIG)
    elif CONFIG.get("app_mode") == "web":
        driver.get(CONFIG["start_url"])
    elif case.get("reset_app_data"):
        # A test-build flow changes app data: it starts from a freshly reset app, like its discovery replay did.
        reset_app_data(driver, SCREENS[0]["package_name"])
    elif activity:
        driver.execute_script(
            "mobile: startActivity",
            {"component": SCREENS[0]["package_name"] + "/" + activity, "wait": True, "stop": True},
        )
    else:
        driver.terminate_app(SCREENS[0]["package_name"])
        driver.activate_app(SCREENS[0]["package_name"])
    runtime = MobileRuntime(driver, CONFIG, SCREENS, case, RUN)
    driver._blowai_previous_read_only = read_only
    if not reuse:
        runtime.wait_for_start()
    native = CONFIG.get("app_mode") != "web"
    package = SCREENS[0]["package_name"]
    since = device_time(CONFIG["device_id"]) if native else None  # crashes are looked up from this moment
    recording = native and not read_only and start_recording(driver)
    try:
        yield runtime
    finally:
        if native and not interaction_blocker(CONFIG):
            try:  # the next test starts with the app in front (a prompt this test raised is declined)
                from backend.android import bring_app_back

                bring_app_back(driver, {**CONFIG, "package_name": package})
                runtime.note_declined()
            except Exception as error:
                if device_unavailable(error):
                    raise
        report = getattr(request.node, "mobile_report", None)
        problem = app_problem(read_log(CONFIG["device_id"], since), package) if report and since is not None else None
        failed = bool(report and report.failed or problem)
        screenshot = (
            capture_screenshot(driver, RUN, case["id"], package)
            if report and report.failed and not runtime.sensitive
            else None
        )
        video = stop_recording(driver, RUN, case["id"], keep=failed and not runtime.sensitive) if recording else None
        logcat = (save_log(RUN, case["id"], read_log(CONFIG["device_id"], since, ("crash", "system", "main")),
                           package, CONFIG["device_id"]) if failed and since is not None else None)
        if report:
            record = _result(request.node, report)
            record.update(
                checks=runtime.checks,
                screenshot=screenshot,
                video=video,
                logcat=logcat,
                live_steps=runtime.steps,
                contract_evidence=runtime.contract_evidence,
                authentication_verified=runtime.authentication_verified,
                contract_id=case.get("contract_id"),
                auto_flow_id=case.get("auto_flow_id"),
                locator_resolutions=runtime.locator_resolutions,
                platform_recoveries=getattr(driver, "_blowai_platform_recoveries", []),
            )
            if problem:
                # A crash or ANR of the app under test is a defect, whatever the test's own assertions said.
                what = "crashed" if problem["kind"] == "crash" else "stopped responding (ANR)"
                record.update(outcome="failed", exception_type="AppCrash" if problem["kind"] == "crash" else "AppNotResponding",
                              app_problem=problem,
                              error=(f"The app {what} during this test: {problem['summary']}\n" + record["error"])[:2000])
            elif record["outcome"] == "passed" and not runtime.checks:
                record.update(outcome="inconclusive", error="No meaningful assertion was executed.")
            _append("android_results.jsonl", record)
            for entry in runtime.healing:
                _append("android_healing.jsonl", {**entry, "id": case["id"], "rerun_outcome": record["outcome"]})
