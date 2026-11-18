# Qpilot X — Phase 5 Android + portfolio gates

**Date:** 2026-11-18  
**Branch:** `cursor/qpilot-x-phase0-baseline-f72b`

## What landed

| Blueprint need | Change |
|---|---|
| Gate D device matrix | `backend/device_matrix.py` — required web desktop/phone + Android emulator/API24+ profiles; verified only with executed evidence |
| Gate F portfolios | `backend/portfolio_gates.py` — a11y / visual / performance / locale / safe-security; missing evidence = `unknown` (never pass) |
| Offline proof | `tests/test_device_matrix.py`, `tests/test_portfolio_gates.py` |

## Environment note

Default PR CI is Windows quick tests (no emulator). Live Android evidence is opt-in:
local AVD + Appium, or a future ubuntu+KVM workflow job. Contract:
`docs/ops-evidence/android_appium_ci_contract.json`. Keep slow paths behind
`@pytest.mark.slow` / live drills (existing `tests/test_android_device.py`).

## Existing modules reused

- Android pipeline: `backend/android*.py`, opt-in device tests
- Live drills: `android_emulator_smoke_drill`, `android_appium_product_matrix_drill`
- Visual: `backend/visual.py`
- Locale: `backend/locale_check.py`

## Gate D / F status

Still **Partial**:
- Gate D: web desktop+phone viewports + live API24 adb smoke + live API30 Appium
  product matrix (Settings/Contacts/Chrome + ApiDemos APK). Broad multi-device CI
  artifacts remain open (`D-android`).
- Gate F: portfolio evaluators + capture exist; broad live CI portfolio artifacts are not closed.
