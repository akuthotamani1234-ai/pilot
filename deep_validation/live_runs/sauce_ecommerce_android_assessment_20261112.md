# Android ecommerce live assessment — 2026-11-12

## Target choice

User selected **#1 nopCommerce**. From this cloud environment:

- `https://demo.nopcommerce.com` and nopCommerce marketing sites return **Cloudflare 403**
- Official Play package `com.nopcommerce.nopcommerce_mobile` has **no public APK/source** reachable here (GitHub mobile repo 404)

**Executable stand-in used:** Sauce Labs **My Demo App** `com.saucelabs.mydemoapp.android` (APK `demo-apps/mda-2.3.0-27.apk`) — real Android ecommerce flows (catalog, PDP, cart, login, menu). Feature checklist mapped from the nopCommerce mobile feature list.

Setup watcher kept Appium + emulator + UI under `/tmp/blowai-watch/setup_watcher.log`.

## Primary live run

`runs/android_live_sauce_ecom_20261112_094348`

| Metric | Result |
| --- | --- |
| Screens discovered | 10 (Products, Navigation menu, No Items/cart empty, Sauce Labs Backpack, Login, Webview, Drawing, About, Biometrics, Virtual USB) |
| User-like flows | **33 passed / 2 failed** of 35 |
| Generated tests | 37 passed / 1 failed / 22 error / 1 blocked |
| Auth gate | **pass** (demo login succeeded) |
| Verdict | **Not Ready** |

### Behaved like a real tester

- Opened catalog and product details; added to cart; changed quantity; removed items
- Exercised menu destinations (Catalog, WebView, Drawing, About, FingerPrint, Virtual USB, Login)
- Declined dangerous/permission prompts; **excluded** Reset App State, Crash, Proceed To Checkout, Start/Stop Observing
- Negative login (empty, locked-out) + successful login + logout
- Device: rotation, background/resume, Back
- Retained a quantity-boundary assertion failure for replay (lowest count → expected `1`, saw `0`)

### Gaps found and fixed

1. **Non-exported MainActivity** — Appium `startActivity` Permission Denial.  
   Fix: resolve LAUNCHER via `cmd package resolve-activity`, retry session with SplashActivity, persist activity into `.private/android_config.json`, and fall back in `android_conftest.py`.
2. **nopCommerce unreachable** — documented; Sauce MDA used as ecommerce Android fixture with thorough contract `demo-apps/sauce-ecommerce-thorough-checks.json`.

### Remaining gaps vs expert manual QA

- Search / Wishlist / Orders not present in this demo app (N/A)
- Checkout intentionally blocked (correct safety)
- Wrong-password login negative path still flaky (`ControlMissing`)
- Quantity-at-zero assertion still fails (product finding retained)

## Verification run after launcher/conftest fixes

`runs/android_live_sauce_ecom_20261112_100729`

| Metric | Before fix (094348) | After (100729) |
| --- | ---: | ---: |
| Passed tests | 37 | **43** |
| Infrastructure/`startActivity` export errors | 22 | **0** export denials (3 other infra) |
| User-like passed | 33/35 | 21/23 (smaller budget) |
| Verdict | Not Ready | Not Ready (honest) |

## Evidence

- Logs: `deep_validation/live_runs/android_live_sauce_ecom_20261112_094348.log`, `..._100729.log`
- Walkthrough video: `/opt/cursor/artifacts/blowai-sauce-ecommerce-android-live.mp4`
- Catalog / product / studio screenshots under `/opt/cursor/artifacts/sauce-ecom-*` and `blowai-studio-android-live.webp`
