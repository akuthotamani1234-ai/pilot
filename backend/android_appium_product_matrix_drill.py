"""Gate D: live Appium UiAutomator2 product-matrix drill on an online emulator.

Exercises system apps (Settings / Contacts / Chrome) plus a third-party sample
APK (Appium ApiDemos) via the product ``create_session`` path. Modern
UiAutomator2 requires API 26+; API 24 smoke evidence remains separate. Broad
CI product-matrix artifacts still open — ``gate_d_complete`` stays False.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

from .android import android_environment, close_session, create_session, launchable_activity
from .device_matrix import evaluate_matrix

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "android_appium_product_matrix_drill.json"
APIDEMOS_APK = ROOT / "demo-apps" / "ApiDemos-debug.apk"
APIDEMOS_URL = (
    "https://github.com/appium/appium/raw/master/packages/appium/"
    "sample-code/apps/ApiDemos-debug.apk"
)
APIDEMOS_PACKAGE = "io.appium.android.apis"

# Product portfolio: installed launcher apps present on Google APIs AVDs.
PRODUCT_APPS = (
    {"id": "settings", "package": "com.android.settings"},
    {"id": "contacts", "package": "com.android.contacts"},
    {"id": "chrome", "package": "com.android.chrome"},
)

DEFAULT_APPIUM = "http://127.0.0.1:4723"


def _ensure_apidemos(adb: str, device_id: str) -> dict:
    """Download (if needed) and install Appium ApiDemos as a third-party APK."""
    result = {"package": APIDEMOS_PACKAGE, "installed": False, "apk": str(APIDEMOS_APK)}
    try:
        APIDEMOS_APK.parent.mkdir(parents=True, exist_ok=True)
        if not APIDEMOS_APK.is_file() or APIDEMOS_APK.stat().st_size < 10_000:
            with urllib.request.urlopen(APIDEMOS_URL, timeout=60) as resp:  # noqa: S310
                APIDEMOS_APK.write_bytes(resp.read())
        result["apk_bytes"] = APIDEMOS_APK.stat().st_size
        proc = subprocess.run(
            [adb, "-s", device_id, "install", "-r", str(APIDEMOS_APK)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).lower()
        result["install_rc"] = proc.returncode
        result["installed"] = proc.returncode == 0 and "success" in out
        if not result["installed"]:
            result["install_error"] = ((proc.stdout or "") + (proc.stderr or ""))[:300]
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        result["install_error"] = str(e)[:300]
    return result


def _appium_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/status", timeout=5) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        return bool((payload.get("value") or {}).get("ready"))
    except (OSError, ValueError, TypeError):
        return False


def _online_emulators(env: dict) -> list[dict]:
    devices = env.get("devices") if isinstance(env.get("devices"), list) else []
    out = []
    for d in devices:
        if not isinstance(d, dict):
            continue
        status = str(d.get("status") or "").lower()
        device_id = str(d.get("device_id") or "")
        if status not in {"device", "online"} or not device_id.startswith("emulator-"):
            continue
        out.append(d)
    return out


def _exercise_app(*, device_id: str, package: str, appium_url: str, api_level: int) -> dict:
    activity = launchable_activity(device_id, package) or ""
    cfg = {
        "app_mode": "installed",
        "package_name": package,
        "app_activity": activity,
        "device_id": device_id,
        "appium_url": appium_url,
        "session_timeout_s": 240,
        "command_timeout_s": 90,
        "interaction_testing": True,
        "api_level": api_level,
    }
    t0 = time.time()
    driver = None
    try:
        from appium.webdriver.common.appiumby import AppiumBy

        driver = create_session(cfg)
        current = str(getattr(driver, "current_package", "") or "")
        source_len = len(driver.page_source or "")
        clickables = driver.find_elements(
            AppiumBy.ANDROID_UIAUTOMATOR, "new UiSelector().clickable(true)"
        )
        interacted = False
        if clickables:
            try:
                clickables[0].click()
                time.sleep(0.5)
                interacted = True
            except Exception:
                interacted = False
        ok = bool(current) and source_len > 0
        return {
            "package": package,
            "activity": activity or cfg.get("app_activity"),
            "ok": ok,
            "outcome": "passed" if ok else "failed",
            "seconds": round(time.time() - t0, 1),
            "current_package": current,
            "page_source_len": source_len,
            "clickables": len(clickables),
            "interacted": interacted,
        }
    except Exception as e:
        return {
            "package": package,
            "activity": activity,
            "ok": False,
            "outcome": "error",
            "seconds": round(time.time() - t0, 1),
            "error": str(e)[:400],
        }
    finally:
        if driver is not None:
            try:
                close_session(driver)
            except Exception:
                pass


def _linked_matrix() -> dict:
    return {
        "gate_d_complete": False,
        "ok": False,
        "drill": "android_appium_product_matrix",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_android_appium_product_matrix_drill(
    *,
    ops_dir: Path | None = None,
    appium_url: str = DEFAULT_APPIUM,
) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    if ops_dir is not None and folder_is_linked(Path(ops_dir)):
        return _linked_matrix()

    env = android_environment(appium_url)
    online = _online_emulators(env)
    appium_ok = _appium_ready(appium_url)

    if not online:
        evidence = {
            "gate_d_complete": False,
            "drill": "android_appium_product_matrix",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "appium_ready": appium_ok,
            "devices_online": 0,
            "apps": [],
            "matrix_rows": [],
            "reason": (
                "No online emulator — boot an API 26+ AVD and start Appium before "
                "the product matrix can advance"
            ),
        }
    elif not appium_ok:
        evidence = {
            "gate_d_complete": False,
            "drill": "android_appium_product_matrix",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "appium_ready": False,
            "devices_online": len(online),
            "device_id": str(online[0].get("device_id")),
            "apps": [],
            "matrix_rows": [],
            "reason": f"Appium not ready at {appium_url}",
        }
    else:
        device = online[0]
        serial = str(device.get("device_id"))
        try:
            api_level = int(device.get("api_level") or device.get("android_version") or 0)
        except (TypeError, ValueError):
            api_level = 0
        if api_level < 26:
            # Probe via adb if environment cache is stale.
            try:
                adb = str(env.get("adb") or "adb")
                proc = subprocess.run(
                    [adb, "-s", serial, "shell", "getprop", "ro.build.version.sdk"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                api_level = int((proc.stdout or "0").strip() or "0")
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass

        if api_level < 26:
            evidence = {
                "gate_d_complete": False,
                "drill": "android_appium_product_matrix",
                "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "ok": False,
                "appium_ready": True,
                "devices_online": len(online),
                "device_id": serial,
                "api_level": api_level,
                "apps": [],
                "matrix_rows": [],
                "reason": (
                    f"Emulator {serial} is API {api_level}; modern UiAutomator2 "
                    "requires API 26+. Keep API24 adb smoke separate; boot API 26+ for Appium."
                ),
            }
        else:
            adb = str(env.get("adb") or "adb")
            third_party = _ensure_apidemos(adb, serial)
            apps = []
            for spec in PRODUCT_APPS:
                row = _exercise_app(
                    device_id=serial,
                    package=spec["package"],
                    appium_url=appium_url,
                    api_level=api_level,
                )
                row["kind"] = "system"
                apps.append(row)
            apk_row = _exercise_app(
                device_id=serial,
                package=APIDEMOS_PACKAGE,
                appium_url=appium_url,
                api_level=api_level,
            )
            apk_row["kind"] = "third_party_apk"
            apk_row["install"] = third_party
            if not third_party.get("installed") and not apk_row.get("ok"):
                apk_row["ok"] = False
                apk_row["outcome"] = "blocked"
                apk_row.setdefault(
                    "error",
                    third_party.get("install_error") or "ApiDemos APK not installed",
                )
            apps.append(apk_row)
            passed = [a for a in apps if a.get("ok")]
            system_passed = [a for a in passed if a.get("kind") == "system"]
            apk_passed = [a for a in passed if a.get("kind") == "third_party_apk"]
            rows = []
            if passed:
                rows.append(
                    {
                        "surface": "android",
                        "device_id": serial,
                        "form": "emulator",
                        "api_level": api_level,
                        "outcome": "passed",
                        "source": "android_appium_product_matrix",
                        "apps_passed": [a["package"] for a in passed],
                        "third_party_apk": bool(apk_passed),
                    }
                )
            scored = evaluate_matrix(rows)
            evidence = {
                "gate_d_complete": False,
                "drill": "android_appium_product_matrix",
                "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "ok": len(system_passed) >= 2 and bool(apk_passed),
                "appium_ready": True,
                "appium_url": appium_url,
                "device_id": serial,
                "api_level": api_level,
                "devices_online": len(online),
                "apps": apps,
                "apps_passed": len(passed),
                "apps_total": len(apps),
                "system_apps_passed": len(system_passed),
                "third_party_apk_passed": bool(apk_passed),
                "third_party_install": third_party,
                "matrix_rows": rows,
                "android_profiles_verified": [
                    p for p in (scored.get("verified") or []) if p.startswith("android.")
                ],
                "reason": (
                    f"Live Appium product matrix on {serial} API {api_level}: "
                    f"{len(system_passed)} system + "
                    f"{'ApiDemos APK' if apk_passed else 'no third-party APK'}; "
                    "broad multi-device CI product-matrix artifacts still open"
                ),
            }

    text = json.dumps(evidence, indent=2)
    name = "android_appium_product_matrix_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_matrix()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_matrix()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
        rows_name = "android_live_matrix_rows.json"
        rows_dir = ROOT / "docs" / "ops-evidence"
        rows_path = rows_dir / rows_name
        if not folder_is_linked(rows_path) and not folder_is_linked(rows_dir):
            prior: list = []
            if rows_path.is_file():
                try:
                    loaded = json.loads(rows_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, list):
                        prior = loaded
                except (OSError, ValueError):
                    prior = []
            merged = list(prior) + list(evidence.get("matrix_rows") or [])
            rows_dir.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(rows_dir, rows_name, json.dumps(merged, indent=2))
    return evidence
