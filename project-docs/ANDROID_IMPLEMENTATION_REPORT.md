# Android implementation and verification report

This is the historical first-phase report. Subsequent approved-flow, backend, hybrid and accuracy features are described in [13_ADVANCED_QA.md](13_ADVANCED_QA.md); see [current verification status](ADVANCED_QA_VERIFICATION.md).

Verified 5 November 2026. This report distinguishes implemented code, actual execution and remaining limits.
The original source checkpoint is `.snapshots/android_before_20261105_155703.zip`; this workspace has no Git repository.

## Architecture and preserved web behavior

The existing Python 3.13/FastAPI/vanilla JavaScript/LangGraph product remains in place. Website discovery,
Playwright/Pytest execution, provider wrappers, status APIs, reporting, Excel, deterministic verdicts and web fixtures
are reused. `build_graph(target_type="mobile")` selects Android adapters. Shared agent entry points dispatch by target;
Android sessions and SQLite state remain isolated from browser runs. No frontend framework migration was introduced.
Existing web CLI regression and URL-submission full-pipeline tests were actually rerun: **2 passed in 480.09s** in
no-AI mode. The existing broader cloud/AI web E2E scenarios were **NOT RERUN** in this implementation.

## Implementation inventory

| Area | Final implementation | Verification |
|---|---|---|
| Environment and sessions | `backend/android.py`: local Appium readiness, SDK/JDK/ADB/device checks, configuration validation, bounded timeouts, per-device OS lock, real UiAutomator2 sessions | Real API 36 emulator and regression checks |
| APK and installed apps | Bounded private APK upload, manifest/archive validation, package/activity configuration; no APK required for installed mode | Real browser upload and installed-app runs |
| Discovery | Foreground-package guard, normalized native hierarchy, candidate locators, fingerprints, depth/action/screen/time limits, observed navigation paths, unvisited-control records | Multi-screen native runs |
| Test design | `backend/android_design.py`: shared LLM wrapper, structured observed-reference schema, explicit navigation/value contracts, stable case IDs and provenance | Actual Ollama proposals and no-AI contracts |
| Script generation | Shared provider writes frozen-plan Python; AST validation before save and execution; at most one corrective retry; labelled safe template fallback | Actual local AI script accepted and executed; rejection regression checks |
| Execution | `backend/android_pipeline.py`, `backend/android_runtime.py`, trusted conftest: serial generated Pytest, fresh app start per case, live locator uniqueness, real assertions, JUnit/JSONL, timeout/process-tree and own-session cleanup | Real Appium tests and protocol integration |
| Failure analysis | Exception-based classification; expected/actual message, screenshots where permitted, distinct infrastructure/locator/assertion outcomes | About navigation and cart-total defects |
| Locator recovery | Unique same-element evidence on same screen, at most two attempts, original assertion preserved, original/replacement/outcome log | Unit tests plus real emulator with deliberately injected stale locator |
| Orchestration | `backend/android_graph.py`, `backend/android_runner.py`, shared QAState, private SQLite checkpoints, bounded stop/resume behavior and partial evidence | Protocol checkpoint integration and real APK runner; real interrupted-device resume **NOT VERIFIED** |
| Backend/UI | Mobile form, detected devices, provider/model, Appium URL, APK/installed mode, requirements, navigation/value expectations, live stages, existing result/report APIs | Real browser-to-APK-to-Appium-to-report E2E; zero browser page errors |
| Reporting | `backend/android_reporting.py`: shared deterministic verdict engine, mobile quality gates, evidence dashboard, HTML/JSON/Excel/cost, blocked and unvisited scope | Real clean/seeded reports; no invented whole-app accuracy metric |
| Fixtures | Existing web fixtures retained; local Android Java app adds documented clean behavior and optional bug flags, inert dangerous controls and a safety counter | Two clean and two seeded real runs; dangerous-action counter zero in navigation E2Es |

## Dependencies and environment

No dependency pin upgrades were necessary. Verified installed versions include Python 3.13.16, Appium Python Client
6.0.0, Selenium 4.46.0, Appium Server 3.9.0, UiAutomator2 8.7.3, Node 24.22.1 and JDK 21. The emulator is Android 16/API 36.
A matching official ChromeDriver was downloaded locally for the standalone Chrome demonstration; no global package
upgrade was performed. `pip check`, Ruff and frontend JavaScript syntax checks passed.

The Android fixture was built from an isolated copy of the same source outside OneDrive after locked intermediates
prevented an in-place rebuild. The verified APK is at
`%LOCALAPPDATA%\BlowAI\android-demo-verification-build\app\build\outputs\apk\debug\app-debug.apk`.

## Actual verification

- Android regression suite: **66 passed in 32.94s**.
- Final complete non-slow suite: **342 passed, 60 slow tests deselected in 1200.34s**.
- Real Android clean/seeded integration suite: **4 passed in 910.32s**.
- Real browser UI APK upload and mobile report E2E: **1 passed in 101.20s**.
- Real Android Chrome demonstration: **6 checks passed**, screenshots and actual device video saved.
- Local Ollama `qwen2.5:3b`: **3 AI-designed scenarios**, **2 actual LLM calls**, accepted **LLM-generated Python**, **5 checks passed** through Appium. No template fallback was used in that verification.
- Controlled stale-locator injection: **1 check passed** through real Appium after recovery; original Home text assertion and generated file unchanged. This deliberately supplies obsolete locator evidence; it does not claim an unplanned app defect.

The local dashboard `runs/android_verification_tools/index.html` links all successful evidence, including:

| Fixture condition | Passed | Assertion failures | Execution errors | Verdict |
|---|---:|---:|---:|---|
| Clean navigation | 10 | 0 | 0 | Ready with Risks |
| About incorrectly opens Settings | 9 | 1 | 0 | Not Ready |
| Clean zero-quantity cart | 6 | 0 | 0 | Ready with Risks |
| Incorrect cart adds $7 | 5 | 1 | 0 | Not Ready |

Blocked controls are reported separately and never counted as passes. These four fixture runs demonstrate the two
specified defects and clean comparisons; they do not establish a general precision, recall or accuracy percentage.
Earlier failed development attempts remain in `runs/`; the dashboard identifies the completed verification runs.

## Generation and safety boundaries

Framework code, the fixture app and the Chrome transport demonstration are handwritten. Native case proposals and
scripts can be generated by the shared AI providers. Rule cases and template scripts have explicit, separate
provenance. The verified local AI case is distinct from the no-AI fixture defect tests.

Generated code can execute only its approved literal plan through the trusted adapter; it has no raw driver or
arbitrary module access. Unknown evidence references and modified assertions are rejected. Discovery does not
imply a tested business workflow. Filled input contents, passwords and raw hierarchies are omitted from AI input;
screenshots of filled inputs/external apps are skipped. Private APK/checkpoint/configuration files are not served.

## Remaining limits and accuracy improvements

- Physical phones, other Android versions and cloud-provider live Android generation: **NOT VERIFIED**. Shared provider paths remain available.
- Native credential entry, login submission, registration and form submission are **not implemented as approved executable flows**; they remain blocked by default. The empty-form seeded defect is therefore **NOT VERIFIED**. Add explicit secret-safe flow contracts and fixture-only approvals before extending this coverage.
- Native iOS is outside this Android/Windows scope. Hybrid WebView context switching and general mobile-web AI discovery are not implemented; the recorded Chrome run is a separate handwritten demo.
- Discovery is bounded; most real applications require additional app-specific expected outcomes. AI-generated mobile proposals are currently restricted to observed UI evidence, at most three scenarios/two controls per proposal. They do not independently prove transactional correctness.
- Add read-only API/database checks and domain rules for totals, permissions and state transitions to obtain stronger correctness evidence than visible UI alone.
- Expand the clean/known-defect benchmark across multiple apps and repeated runs. Track false alarms, missed defects and flaky outcomes before publishing an accuracy figure.
- For presentation, show a clean run, enable a documented defect, display the exact failed assertion and screenshot, then clear the defect and rerun. Show locator recovery separately, preserving the same assertion. Label all seeded behavior.

## Start on this Windows machine

In PowerShell from the project root, use the installed local tools (the verification server may already be running):

```powershell
$env:JAVA_HOME = "$env:LOCALAPPDATA\BlowAI\jdk-21"
$env:ANDROID_SDK_ROOT = "$env:LOCALAPPDATA\Android\Sdk"
$env:ANDROID_HOME = $env:ANDROID_SDK_ROOT
$env:PATH = "$env:JAVA_HOME\bin;$env:ANDROID_SDK_ROOT\platform-tools;$env:PATH"
# Only if the local Appium server is not already running:
& "$env:USERPROFILE\Downloads\Project\node.exe" "$env:LOCALAPPDATA\BlowAI\AndroidTools\node_modules\appium\index.js" --address 127.0.0.1 --port 4723
```

Start an existing emulator in a separate terminal if it is not already visible:

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" -avd blowai-api36 -no-audio -no-snapshot-save -gpu swiftshader_indirect
```

Start the product UI in another terminal:

```powershell
.\ui.bat
```

Choose **Test an Android app**, refresh devices, select the emulator, and upload the fixture APK or use installed mode
`com.blowai.demo` / `.MainActivity`. For meaningful fixture assertions supply `About = About` and/or `Cart = Cart` as
navigation expectations and `Cart total = Total: $0.00` as the displayed-value expectation. Select Ollama for actual AI
or No AI for deterministic template verification. See `12_ANDROID.md` for portable setup, replay and troubleshooting.
