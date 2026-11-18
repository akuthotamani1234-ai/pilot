"""QX-A10 / Gate D+F: cross-platform business journey comparison drill.

Walks the same DemoStore browse→about journey on Chromium/Firefox/WebKit and
records Android Appium Settings open→interact steps when an emulator+Appium
session is available. Differences are reported; ``must_match`` fails only when
required. Gate completeness stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .journey_map import compare_journey

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "cross_platform_journey_drill.json"


def _web_steps(engine: str, store_url: str) -> list[str]:
    """Deterministic browse→about steps (optional link follow is best-effort only).

    Windows CI often lacks Playwright WebKit; engines that launch must still
    emit the same required steps so ``must_match`` stays honest.
    """
    from playwright.sync_api import sync_playwright

    steps: list[str] = []
    with sync_playwright() as pw:
        browser_type = getattr(pw, engine)
        browser = browser_type.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(store_url, wait_until="domcontentloaded")
            steps.append("open_home")
            page.goto(store_url.rstrip("/") + "/about", wait_until="domcontentloaded")
            steps.append("open_about")
            # Best-effort only — never let optional navigation diverge must_match.
            try:
                link = page.locator("a").first
                if link.count():
                    link.click(timeout=1500)
            except Exception:
                pass
        finally:
            browser.close()
    return steps


def _android_steps() -> list[str] | None:
    """Best-effort Appium Settings journey; None when emulator/Appium unavailable."""
    try:
        from .android import android_environment, close_session, create_session, launchable_activity
        from .android_appium_product_matrix_drill import _appium_ready
    except Exception:
        return None
    if not _appium_ready("http://127.0.0.1:4723"):
        return None
    env = android_environment("http://127.0.0.1:4723")
    devices = env.get("devices") if isinstance(env.get("devices"), list) else []
    online = [
        d for d in devices
        if isinstance(d, dict)
        and str(d.get("status") or "").lower() in {"device", "online"}
        and str(d.get("device_id") or "").startswith("emulator-")
    ]
    if not online:
        return None
    serial = str(online[0].get("device_id"))
    try:
        api = int(online[0].get("api_level") or 0)
    except (TypeError, ValueError):
        api = 0
    if api and api < 26:
        return None
    pkg = "com.android.settings"
    act = launchable_activity(serial, pkg) or ".Settings"
    cfg = {
        "app_mode": "installed",
        "package_name": pkg,
        "app_activity": act,
        "device_id": serial,
        "appium_url": "http://127.0.0.1:4723",
        "session_timeout_s": 180,
        "command_timeout_s": 60,
        "interaction_testing": True,
    }
    steps: list[str] = []
    driver = None
    try:
        from appium.webdriver.common.appiumby import AppiumBy

        driver = create_session(cfg)
        steps.append("open_settings")
        els = driver.find_elements(AppiumBy.ANDROID_UIAUTOMATOR, "new UiSelector().clickable(true)")
        if els:
            els[0].click()
            steps.append("tap_first_clickable")
        steps.append("capture_hierarchy")
    except Exception:
        return None
    finally:
        if driver is not None:
            try:
                close_session(driver)
            except Exception:
                pass
    return steps


def run_cross_platform_journey_drill(*, ops_dir: Path | None = None) -> dict:
    from tests.demo_store import DemoStore

    store = DemoStore().start()
    steps_by_surface: dict[str, list[str]] = {}
    errors: list[str] = []
    try:
        for engine in ("chromium", "firefox", "webkit"):
            try:
                steps_by_surface[f"web.{engine}"] = _web_steps(engine, store.url)
            except Exception as exc:
                errors.append(f"{engine}: {exc}"[:160])
    finally:
        try:
            store.stop()
        except Exception:
            pass

    android = _android_steps()
    if android:
        steps_by_surface["android.emulator"] = android

    # Web engines must match each other; Android is a different product surface.
    web_only = {k: v for k, v in steps_by_surface.items() if k.startswith("web.")}
    web_cmp = compare_journey("demostore_browse_about", web_only, must_match=True)
    full_cmp = compare_journey("demostore_plus_android", steps_by_surface, must_match=False)

    # ≥1 web engine with required steps; when ≥2 engines ran, they must match.
    # (Playwright WebKit is unavailable on Windows runners.)
    web_ok = (
        len(web_only) >= 1
        and all(len(v) >= 2 for v in web_only.values())
        and (web_cmp.get("status") == "matched" if len(web_only) >= 2 else True)
    )
    evidence = {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "cross_platform_journey",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "surfaces": sorted(steps_by_surface),
        "steps_by_surface": steps_by_surface,
        "web_compare": web_cmp,
        "full_compare": full_cmp,
        "errors": errors,
        "ok": web_ok,
        "reason": (
            f"Cross-platform journey on {', '.join(sorted(steps_by_surface)) or 'none'}; "
            f"web must_match={web_cmp.get('status')} engines={len(web_only)}; "
            "broader release-journey matrix still open"
        ),
    }

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "cross_platform_journey_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "cross_platform_journey_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
