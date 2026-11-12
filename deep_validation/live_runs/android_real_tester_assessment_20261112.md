# Android live testing — real-tester assessment (2026-11-12)

Target: controlled demo APK `com.blowai.demo` on emulator-5554 via Appium UiAutomator2.
Final post-fix run: `runs/android_live_20261112_091845` (rules-only `LLM_PROVIDER=none`).

## Environment installed

- Android SDK at `/opt/android-sdk`, AVD `blowai-api30`, KVM emulator
- Appium 3.9.0 + uiautomator2 driver
- Demo APK from `tests/android_demo` / `demo-apps`

## Pipeline behavior (like a real tester?)

| Behavior | Observed | Verdict |
| --- | --- | --- |
| Open app and map screens | 13 screens: Home, Login, About, Registration, Dashboard, Products, Cart, Form validation, Settings, Broken scenario, Login required, Test simulations, Product details | Yes |
| Navigate menus systematically | Replay-verified taps for About, Login, Registration, Dashboard, Protected, Simulations, Products, Cart, Form, Settings, Broken, Add to cart | Yes |
| Avoid irreversible / payment / delete | PAY NOW, DELETE ACCOUNT intentionally excluded; Registration signup excluded as protected | Yes (safety-aware) |
| Fill / exercise forms | Form validation tried; login empty-field negative path attempted; valid login contract passed authentication gate | Partial |
| Device quirks | Rotation, background/resume, Back — 5/5 passed | Yes |
| Re-verify suspicious findings | Form validation assertion failure replayed twice and kept for execution | Yes |
| Honest readiness call | Verdict **Not Ready** with failed assertion + locator/infrastructure gaps | Yes |

## Final run scoreboard

- **56 passed / 1 failed / 3 error / 1 blocked** of 61 generated tests
- **User-like flows: 17 passed / 1 failed** (the failure is the retained form-validation finding)
- Authentication gate: **pass** (approved login flow)
- Package ids intact: private + public `android_package=com.blowai.demo` (no `com.blowai.[REDACTED]`)
- Private `auto_contract.json` keeps UI text such as `Welcome demo user`; public `auto_flows.json` still redacts usernames for display

## Bugs found and fixed during this Android pass

1. Username `demo` corrupted `package_name` in `screens.json` → `redact_json` + package-key restore.
2. Same username corrupted contract field `android_package` and `android://` coverage URLs → keys + URL collection.
3. Private executable contract redacted labels containing `demo`, so replay asserted `Welcome [REDACTED] user` → private `auto_contract.json` now written unredacted.

## Remaining gaps vs an expert human tester

- Login empty-field negative path stayed **inconclusive** (locator uniqueness).
- Hybrid Demo navigation inconclusive (webview/hybrid boundary).
- Two generated UI control checks failed on stale/xpath/accessibility locators (Login, Dashboard).
- Sandbox contract `protected_after_login` hit an infrastructure locator miss (auth still proven via fixture login).
- Rules-only mode: bounded exploration, not creative multi-step business journeys.

## Bottom line

Blow AI on Android **does perform like a careful automated tester**: it explores broadly, avoids dangerous actions, exercises navigation and device behavior, builds replayable flows, and fails closed with evidence. It is **not yet equivalent to an expert manual tester** on fragile locators, hybrid WebView, and some form negative paths — and the product correctly reports **Not Ready** when those gaps remain.
