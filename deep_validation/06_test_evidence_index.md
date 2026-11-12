# 06 — Test evidence index

All new validation artifacts are in this directory. Existing logs/runs are cited in place and were not copied or altered.

## Commands run in this investigation

| Command/action | Result | Evidence |
|---|---|---|
| `pytest -p no:cacheprovider -q tests/test_qa_contracts.py` with `PYTHONDONTWRITEBYTECODE=1` | 18 passed, 5 setup errors, exit 1. Five errors were `PermissionError [WinError 5]` enumerating the user temp directory. | Prior audit output recorded in `PROJECT_AUDIT.md`; not captured to a separate raw file. |
| `pytest -p no:cacheprovider --basetemp=deep_validation\.pytest-tmp -q -n 3 --dist loadfile -m "not slow"` | 406 passed, 21 failed, 324 errors, 26.88s, exit 1. Repeated `PermissionError [WinError 5]` on `deep_validation\.pytest-tmp\popen-gw*` and Playwright subprocess creation. | `deep_validation/pytest-nonslow.txt` |
| `pytest -p no:cacheprovider --basetemp=deep_validation\serial-temp-1 -q tests\test_android_site_dialog_forms.py` | Did not produce a reliable summary; pytest emitted `PermissionError [WinError 5]` during temp fixture/session cleanup. | `deep_validation/android-site-dialog-serial.txt` |
| Python `android_environment()` probe | Appium ready, Java/SDK/UiAutomator2 available, no connected device. | Recorded in `04_android_validation.md`. |
| `emulator.exe -list-avds` | Found `blowai-api36`. | Recorded in `04_android_validation.md`. |
| Hidden AVD start + repeated `adb devices -l` | Emulator process launched, but no ADB device appeared after about 90 seconds; no test session started. | Recorded in `04_android_validation.md`. |
| `pip check` | No broken requirements found. | Prior audit output recorded in `PROJECT_AUDIT.md`. |
| `ruff check . --no-cache` | All checks passed. | Prior audit output recorded in `PROJECT_AUDIT.md`. |
| `git status --short` | Failed: workspace is not a Git repository. | Prior audit output recorded in `PROJECT_AUDIT.md`. |

## Existing execution artifacts

| Artifact | Date/scope | Result |
|---|---|---|
| `logs/appium-final-regression.xml` | 2026-11-08 Android/emulator/API/UI/runtime/contract focused suite | 176 tests: 175 pass, 1 skip, 0 failures/errors; 115.947s. |
| `logs/appium-web-regression.xml` | 2026-11-08 local web QA contract pipeline | 1 pass, 0 failures/errors; 46.154s. |
| `runs/advanced_android_20261108_162006_clean/summary.json` | Controlled clean Android app | 13 passed, 0 failed, Ready with Risks. |
| `runs/advanced_android_20261108_162418_seeded/summary.json` | Same controlled app with seeded defects | 8 passed, 5 failed, Not Ready. |
| `docs/28_APPIUM_RELIABILITY_AUDIT.md` | Historical reliability review | Explains scope, environment, defects fixed, and limits; not a fresh execution. |

## Safety/side effects

- No external websites/apps or cloud providers were contacted.
- No production source, existing tests, `.env`, prior logs, or prior run artifacts were changed.
- `deep_validation/` contains pytest raw output and pytest scratch directories created by the attempted suite runs. No cleanup was performed so no generated evidence was deleted.
- A local AVD start was attempted because the project declares `blowai-api36` and the user requested authorized emulator validation; it did not become visible to ADB, so Appium tests were not started.
