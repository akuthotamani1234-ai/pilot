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

This Cloud Agent image has **no `adb` / emulator / Appium** on PATH. Live device-matrix evidence remains open and must stay `@pytest.mark.slow` / `BLOWAI_ANDROID_E2E=1` (existing `tests/test_android_device.py`).

## Existing modules reused

- Android pipeline: `backend/android*.py`, opt-in device tests
- Visual: `backend/visual.py`
- Locale: `backend/locale_check.py`

## Gate D / F status

Still **Partial**:
- Gate D: discovery/apply now record desktop (`1366x900`) and phone (`390x844`) viewport evidence when phone checks ran (`device_matrix_evidence.json` / `device_matrix.json`). Live Android emulator + API 24+ evidence remains open.
- Gate F: portfolio evaluators + capture exist; broad live CI portfolio artifacts are not closed.
