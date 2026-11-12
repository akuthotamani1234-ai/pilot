# Android testing and live Appium demonstrations

Blow AI retains its existing Playwright website pipeline and adds an Android adapter selected by
`build_graph(target_type="mobile")`. Shared test-design, script-generation, failure-analysis and report entry points
select the appropriate adapter. The existing deterministic verdict engine evaluates platform-specific evidence gates.
The HTML/CSS/JavaScript UI and its polling/status/report APIs are retained.

## What is generated

- Framework modules and controlled demo applications are handwritten and maintained by developers.
- In AI mode, the existing provider wrapper (Ollama, Gemini, OpenAI, Anthropic) proposes structured cases against a
  compact screen/element inventory. Unknown element/screen references are rejected.
- The model writes Python/Pytest functions from frozen evidence-backed plans. AST validation permits only literal
  calls to the trusted Appium adapter and requires every approved step and assertion, unchanged and in order.
- If a provider fails or its code is rejected, validated template code is used and labelled `template`.
- Every case records scenario provenance and script provenance separately. Templates are never described as AI code.

Raw hierarchies, input contents, passwords and API keys are not sent to the model. Text prompts use the existing
redaction and cost tracking. Generated tests run in a separate serial Pytest process with known secrets removed,
plugin auto-discovery disabled and an execution deadline. Generated code cannot import modules, access raw drivers,
create new fixtures, execute arbitrary expressions, weaken assertions, or call arbitrary Appium commands.

## Setup on Windows

Use Python 3.13 and the repository's existing pinned requirements. This change does not upgrade global Node packages.
The installed/checked combination is Appium Python Client 6.0.0, Selenium 4.46.0 and Appium Server 3.9.0.
The client compatibility matrix supports Python 3.10+ with Selenium 4.37+ for client 6.0+:
https://github.com/appium/python-client#compatibility-matrix

Appium 3 requires Node `^20.19.0 || ^22.12.0 || >=24.0.0` and npm 10+:
https://github.com/appium/appium/blob/master/packages/appium/docs/en/guides/migrating-2-to-3.md

Install a JDK 17+ (21 works), Android SDK command-line tools and Platform-Tools. Android Studio's Device Manager is
an alternative for creating an emulator. Use your actual SDK/JDK locations; do not copy another user's absolute path.

```powershell
$env:JAVA_HOME = "<your JDK folder>"
$env:ANDROID_SDK_ROOT = "<your Android SDK folder>"
$env:ANDROID_HOME = $env:ANDROID_SDK_ROOT
$env:PATH = "$env:JAVA_HOME\bin;$env:ANDROID_SDK_ROOT\platform-tools;$env:PATH"
$androidTools = "$env:LOCALAPPDATA\BlowAI\AndroidTools"
npm install --prefix $androidTools appium@3.9.0
$env:PATH += ";$androidTools\node_modules\.bin"
appium driver install uiautomator2@8.7.3
sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0" "emulator"
node --version
npm --version
appium --version
appium driver list --installed
adb devices -l
appium --address 127.0.0.1
```

Only run installation commands when those tools are missing. For an emulator, install a system image suitable for
your CPU and create an AVD with Android Studio. Check `emulator -accel-check` and `emulator -list-avds`. For a physical
phone enable Developer Options and USB debugging, connect it, and approve its own authorization prompt. The software
never bypasses authentication, MFA, permission dialogs or device authorization.

## Start a native run

```powershell
.\ui.bat
```

Choose **Test an Android app**, configure the local Appium URL, refresh devices and choose APK upload or installed
package/activity. APKs are checked for extension, size, archive structure and unsafe paths, and stored inside the
run's private folder. APK validation is not a security scan; use trusted test applications on a disposable emulator.
Installed-app mode requires no APK. Choose the existing configured AI provider/model or No AI.

Navigation expectations use `control label = destination title`, one per line. Displayed-value expectations use
`accessibility label = expected text`, one per line. These explicit requirements support meaningful assertions without
inventing business behavior. Example fixture requirements:

```text
About = About
Open login screen = Login
Products = Products
Cart = Cart
```

```text
Cart total = Total: $0.00
```

A free-text requirements field supplies context to AI design. It does not authorize arbitrary actions. An unknown
destination receives an inferred UI check, not a guessed success assertion. Controls without known expected behavior
remain for review. Read-only UI tests do not prove login, registration or form submission works.

The discovery engine checks the actual foreground package before reading its hierarchy, extracts normalized visible
controls and prioritized locator candidates, verifies locator uniqueness before interaction, records paths and
screenshots, and explores within screen/depth/action/time limits. Recovery navigation counts against the action
budget. Identified controls not explored are reported separately. Discovery is not complete-app certification.

Risky controls are blocked. Clearly labelled navigation to the login screen is allowed; submitting a login form is
not. Payment, purchase, delete, submit, register, mutation and security/permission actions stay blocked by default.
Secrets or credentials are never guessed. Native iOS execution is not supported by this Windows implementation.

Each real Appium session holds an OS device lock, preventing simultaneous sessions against one device. Sessions are
closed in finally blocks; cleanup errors do not erase valid discovery. Locator recovery examines the live hierarchy
and requires a unique same-element identity on the same screen. At most two alternative lookups are tried per case.
Original assertions remain unchanged; original/replacement locators, evidence and final outcome are recorded.

## Checkpoints, results and verdicts

Runs keep a private SQLite checkpoint. Resume an interrupted run using its controlled configuration:

```powershell
.venv\Scripts\python.exe -m backend.android_runner --config "runs\<run>\.private\android_config.json" --resume
```

The uploaded APK/private configuration must remain available. Completed checkpoints are returned without rerunning
tests. A resumed incomplete execution replaces that attempt's partial result stream rather than duplicating results.

Outputs include `screens.json`, `android_discovery.json`, generated Python and cases, JUnit XML, `results.json`,
`failures.json`, locator recovery evidence, `summary.json`, `cost.json`, failure screenshots, HTML and Excel reports.
The same report/case/status APIs support Android runs, including earlier Android case files.

Verdicts use the shared fixed-rule engine: failed approved assertions cause **Not Ready**; missing setup or inconclusive
infrastructure/locator execution causes **Insufficient Evidence**; unresolved blocked/inferred/limited coverage causes
**Ready with Risks**. Blocked actions and missing results are never passes. The model may explain evidence but cannot
change the deterministic verdict. No discovered destination is automatically assumed correct.

## Repeatable verification

```powershell
.venv\Scripts\python.exe -m pytest -q -m "not slow"
.venv\Scripts\python.exe -m pytest -q tests/test_android_protocol.py
# Real device, after installing the controlled demo fixture:
$env:BLOWAI_ANDROID_E2E = "1"
$env:BLOWAI_ANDROID_DEVICE = "emulator-5554"
$env:BLOWAI_ANDROID_ARTIFACTS = "$PWD\runs"
.venv\Scripts\python.exe -m pytest -q -s tests/test_android_device.py
```

The protocol tests execute actual generated Python/Pytest through the real Appium Python client against a local W3C
fixture. They are not real Android tests. The opt-in device tests check clean and seeded fixture behavior, screenshot
capture, report/verdicts, and the fixture's untouched unsafe-action counter. See `tests/android_demo/README.md`.

## Live website in Android Chrome

The dedicated demonstration reuses the existing DemoShop website. It is a handwritten transport demonstration,
separate from AI-generated native application tests and from the existing production Playwright website workflow.
Use a ChromeDriver matching the emulator's Chrome build. Obtain the matching Windows binary from Google's official
Chrome for Testing JSON endpoints/archive: https://googlechromelabs.github.io/chrome-for-testing/

```powershell
.venv\Scripts\python.exe -m tests.appium_web_demo --device emulator-5554 --chromedriver "<matching chromedriver.exe>"
```

The emulator must be visible if you want to watch. The demo opens Home, verifies Products, searches for Pear, switches
the Team tab, opens/closes a dialog and confirms destructive routes were never visited. Screenshots, JSON, HTML and
an actual device recording are saved under `runs/appium_web_live_<time>/`.

## Troubleshooting

- Missing tools: configure SDK/JDK/PATH and install only the missing components.
- Offline/unauthorized device: reconnect or approve debugging on the device; refresh the device list.
- Appium not ready: start one local server; the UI does not silently launch/install one.
- Wrong activity/package: check the installed app's launch configuration; external screens are not inspected.
- Ambiguous/changed locator: inspect hierarchy evidence; unsafe or ambiguous matches are not healed.
- Browser invalid locator: use W3C CSS selectors in the Chrome web context; native resource IDs belong to native UI.
- ChromeDriver mismatch: select a driver for the browser build, not an arbitrary latest version.
- Insufficient Evidence: review infrastructure/locator/stop evidence before drawing conclusions about app quality.


### Accuracy controls added after real verification

Structured local Ollama calls receive a JSON schema. Mobile proposals are restricted to observed short screen/element
references (translated back to canonical evidence IDs), at most three proposals and two controls per proposal. The
configured LLM timeout is honored for local models too. Code receives at most one corrective retry, then a labelled
validated-template fallback. Rejected model code is retained privately for inspection.

Native execution reuses one serial Appium session and restarts only the selected app between cases. This avoids
repeated UiAutomator2 server setup while retaining independent app state and the OS device lock. The launch check
prefers stable identifiable controls/headings over generic layout containers. User-supplied navigation expectations
are explored first within the same action limits.

Observed text changes are review findings, not automatically confirmed business defects. Explicit expected-value
contracts, such as the fixture's zero-quantity cart total, distinguish known incorrect behavior from a merely
observed value. Input expectations are never embedded as credentials in generated scripts. Screenshots of filled
inputs and external apps are omitted.

If OneDrive locks old Android build intermediates, build an isolated source copy outside OneDrive rather than
removing unrelated files. The isolated APK used for verification comes from the same fixture source.


### Verification evidence

See `ANDROID_IMPLEMENTATION_REPORT.md` for the completed implementation inventory, actual results and remaining
limits. The local evidence dashboard is `runs/android_verification_tools/index.html`.

The final worker uses the existing Windows Job Object to terminate its process tree on timeout. A private session
record lets the parent close only that run's Appium session after forced worker termination. Failures preserve the
original exception message before traceback details. A controlled stale-locator injection was also recovered on
the real emulator while preserving the generated Home text assertion.


For approved login/form execution, business rules, API/database oracles, native/WebView journeys and the accuracy lab,
see [Advanced QA configuration](13_ADVANCED_QA.md). Default discovery remains limited to safe navigation.
