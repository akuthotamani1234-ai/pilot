# 04 — Android and WebView validation

**Status: PARTIALLY VERIFIED · score: 7/10 based on historical evidence; current device execution unavailable.**

## Current environment check

Read-only call to `backend.android.android_environment()` returned:

- Appium server: available at `http://127.0.0.1:4723`, ready to accept connections.
- Java: JDK 21 path detected.
- Android SDK/ADB: detected.
- UiAutomator2 driver: installed/registered; reported version 8.7.3.
- Devices: none connected.

`emulator -list-avds` found `blowai-api36`. An attempt to start it hidden was made, but after approximately 90 seconds ADB still reported no devices. No Appium session or live Android test was attempted without a device. The emulator process remained running at the time of the readiness checks; a device boot/readiness result was not achieved.

## Historical execution evidence

- `logs/appium-final-regression.xml`: 176 cases, 175 passed, 1 skipped, 0 failures/errors (2026-11-08). It includes Android environment/API/emulator/pipeline/protocol/reliability/WebView/contract tests. The skip is the opt-in browser-to-emulator UI case.
- `logs/appium-web-regression.xml`: 1 web contract pipeline test passed (2026-11-08).
- `runs/advanced_android_20261108_162006_clean/summary.json`: controlled app clean run; 13 passed, 0 failed, verdict Ready with Risks.
- `runs/advanced_android_20261108_162418_seeded/summary.json`: controlled seeded-defect run; 8 passed, 5 failed, verdict Not Ready.
- `docs/28_APPIUM_RELIABILITY_AUDIT.md` also records APK upload, installed-app and Android Chrome API runs; these were configured-flow runs and explicitly do not prove whole-app coverage.

These are genuine historical execution records, but they predate the current audit and do not replace a fresh run on the current checkout/device.

## Capability matrix

| Capability | Source/tests | Current status |
|---|---|---|
| Native launch and navigation | `android.py`, `android_app.py`, `android_pipeline.py`; Android reliability/pipeline tests | Historical unit + emulator evidence; no fresh device run. |
| Buttons, text, fields, scrolling, dialog/back/keyboard/background | `android_interact.py`, `android_scroll.py`, `android_runtime.py`; `test_android_real_tester.py`, `test_android_site_dialog_forms.py` | Mock/unit coverage exists; full fresh device validation blocked. |
| Permissions | `android_permissions.py`, QA contract schema/runtime | Approved-flow support exists; device prompt behavior not freshly verified. |
| WebView detect/context switch/restore | `qa_runtime.py`, `android.py`, `android_web.py`; `test_qa_native_device.py` and Android Web tests | Historical hybrid real-device run documented; current device unavailable. |
| CSS selectors | `qa_runtime.py` requires CSS in WebView and rejects CSS in native. `android.py` maps CSS to Appium CSS selector. | Boundary is enforced in source and tests; no fresh live selector test. |
| Native locators | accessibility ID, resource ID, UIAutomator text, XPath | Supported by source; CSS intentionally not a native strategy. |
| App crash/session loss | Android failure classification and disconnect handling tests | Historical regression coverage; no fresh device crash injection. |
| Pytest execution/reporting | `android_design.py`, `android_pipeline.py`, templates, runner | Historical mock transport and device runs; fresh tests blocked by environment. |

## Environment failure details

The current AVD process did not register in ADB; `adb devices -l` remained empty. Consequently device, Android version, Appium session context, screenshots and device log for a new test are **unavailable**. Do not interpret this as an app failure.

**Next action:** restore ADB/AVD readiness, then run the opt-in native/hybrid suite only against the controlled demo app and retain output under `deep_validation/`.
