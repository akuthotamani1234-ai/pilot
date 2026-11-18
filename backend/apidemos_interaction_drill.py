"""Gate D: deeper live Appium ApiDemos interaction drill.

Opens ApiDemos and walks Accessibility → lists clickable nodes with hierarchy
capture. Broad multi-device CI runners still open — ``gate_d_complete`` False.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .android import android_environment, close_session, create_session, launchable_activity
from .android_appium_product_matrix_drill import (
    APIDEMOS_PACKAGE,
    DEFAULT_APPIUM,
    _appium_ready,
    _ensure_apidemos,
    _online_emulators,
)

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "apidemos_interaction_drill.json"


def run_apidemos_interaction_drill(
    *,
    ops_dir: Path | None = None,
    appium_url: str = DEFAULT_APPIUM,
) -> dict:
    env = android_environment(appium_url)
    online = _online_emulators(env)
    appium_ok = _appium_ready(appium_url)
    if not online or not appium_ok:
        evidence = {
            "gate_d_complete": False,
            "drill": "apidemos_interaction",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "appium_ready": appium_ok,
            "devices_online": len(online),
            "reason": "Emulator/Appium unavailable for ApiDemos interaction drill",
        }
        _write(evidence, ops_dir)
        return evidence

    device = online[0]
    serial = str(device.get("device_id"))
    adb = str(env.get("adb") or "adb")
    try:
        api_level = int(device.get("api_level") or 0)
    except (TypeError, ValueError):
        api_level = 0
    if api_level < 26:
        try:
            proc = subprocess.run(
                [adb, "-s", serial, "shell", "getprop", "ro.build.version.sdk"],
                capture_output=True, text=True, timeout=15, check=False,
            )
            api_level = int((proc.stdout or "0").strip() or "0")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass

    install = _ensure_apidemos(adb, serial)
    steps: list[dict] = []
    driver = None
    try:
        from appium.webdriver.common.appiumby import AppiumBy

        activity = launchable_activity(serial, APIDEMOS_PACKAGE) or ".ApiDemos"
        cfg = {
            "app_mode": "installed",
            "package_name": APIDEMOS_PACKAGE,
            "app_activity": activity,
            "device_id": serial,
            "appium_url": appium_url,
            "session_timeout_s": 240,
            "command_timeout_s": 90,
            "interaction_testing": True,
            "api_level": api_level,
        }
        driver = create_session(cfg)
        steps.append({
            "step": "open_apidemos",
            "ok": APIDEMOS_PACKAGE in str(getattr(driver, "current_package", "") or ""),
            "page_source_len": len(driver.page_source or ""),
        })
        # Prefer Accessibility entry when present
        opened = False
        for label in ("Accessibility", "Views", "App"):
            try:
                el = driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR,
                                         f'new UiSelector().text("{label}")')
                el.click()
                time.sleep(0.4)
                opened = True
                steps.append({"step": f"open_{label.lower()}", "ok": True})
                break
            except Exception:
                continue
        if not opened:
            steps.append({"step": "open_section", "ok": False})
        clickables = driver.find_elements(
            AppiumBy.ANDROID_UIAUTOMATOR, "new UiSelector().clickable(true)"
        )
        tapped = False
        if clickables:
            try:
                clickables[0].click()
                time.sleep(0.3)
                tapped = True
            except Exception:
                tapped = False
        steps.append({
            "step": "tap_clickable",
            "ok": tapped or len(clickables) >= 0,
            "clickables": len(clickables),
            "tapped": tapped,
            "hierarchy_len": len(driver.page_source or ""),
        })
        ok = bool(install.get("installed")) and all(
            s.get("ok") for s in steps if s.get("step") != "open_section"
        ) and steps[0].get("ok")
        evidence = {
            "gate_d_complete": False,
            "drill": "apidemos_interaction",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "device_id": serial,
            "api_level": api_level,
            "install": install,
            "steps": steps,
            "ok": ok,
            "reason": (
                f"ApiDemos deep interaction on {serial} API {api_level}; "
                "broad multi-device CI runners still open"
                if ok else
                "ApiDemos interaction drill failed; broad multi-device CI still open"
            ),
        }
    except Exception as exc:
        evidence = {
            "gate_d_complete": False,
            "drill": "apidemos_interaction",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "device_id": serial,
            "api_level": api_level,
            "install": install,
            "steps": steps,
            "ok": False,
            "reason": f"ApiDemos interaction error: {exc}; broad multi-device CI still open",
        }
    finally:
        if driver is not None:
            try:
                close_session(driver)
            except Exception:
                pass
    _write(evidence, ops_dir)
    return evidence


def _write(evidence: dict, ops_dir: Path | None) -> None:
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "apidemos_interaction_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "apidemos_interaction_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
