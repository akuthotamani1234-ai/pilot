import json
import os
import time
from pathlib import Path

import pytest

from backend.android import create_session, inspect_driver

CONFIG = json.loads(Path(os.environ["ANDROID_MOBILE_CONFIG"]).read_text(encoding="utf-8"))
CASES = json.loads(Path(os.environ["ANDROID_MOBILE_CASES"]).read_text(encoding="utf-8"))


def _find(driver, locator):
    from appium.webdriver.common.appiumby import AppiumBy

    strategies = {
        "accessibility_id": AppiumBy.ACCESSIBILITY_ID,
        "resource_id": AppiumBy.ID,
        "text": AppiumBy.ANDROID_UIAUTOMATOR,
        "xpath": AppiumBy.XPATH,
    }
    strategy = locator["strategy"]
    value = locator["value"]
    if strategy == "text":
        value = f"new UiSelector().text({json.dumps(value)})"
    return driver.find_element(strategies[strategy], value)


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_android_case(case):
    driver = create_session(CONFIG)
    try:
        before = inspect_driver(driver, CONFIG)
        if case["kind"] == "screen":
            assert before["elements"], "The launched app has no inspectable UI elements."
            return
        if before["fingerprint"] != case["before_fingerprint"]:
            pytest.skip("The app did not open on the screen observed during discovery.")
        _find(driver, case["locator"]).click()
        deadline = time.monotonic() + 10
        after = inspect_driver(driver, CONFIG)
        while after["fingerprint"] == before["fingerprint"] and time.monotonic() < deadline:
            time.sleep(0.25)
            after = inspect_driver(driver, CONFIG)
        assert after["fingerprint"] == case["expected_fingerprint"], (
            f"Expected the observed screen after '{case['title']}', "
            f"but found '{after['screen_name']}'."
        )
        expected_name = case.get("expected_screen_name")
        if expected_name:
            assert expected_name.casefold() in after["screen_name"].casefold(), (
                f"Expected a screen named '{expected_name}', but found '{after['screen_name']}'."
            )
    finally:
        driver.quit()
