# Advanced QA implementation status

The six planned feature areas are implemented in Python. Full execution is deferred at the user's request.
The final small changes to expectation descriptions, response bounds, in-memory credential delivery and stop handling have not been rerun.

| Area | Code and integration | Current validation status |
|---|---|---|
| Native login/forms | Approved flows, secret references, positive/negative outcomes and generated Appium plans | Clean emulator run passed all 13 configured checks before final small edits |
| Business rules | Bounded Decimal expressions over visible values and constants | Browser clean/defect tests and clean native/WebView checks completed |
| API/database | Explicit-origin GET/JSON pointers and configured read-only SQLite SELECT checks | Browser tests, full web pipeline and clean emulator checks completed |
| Hybrid WebView | Selected-package context switching, approved origins and native restoration | Real native to WebView to native journey passed in the clean emulator run |
| Accuracy | Known-truth precision/recall, false alarms, unanswered cases, instability and repeat CLI | Measurement regression tests completed; complete repeated-device benchmark deferred |
| Demonstration | Shared reports, QA accuracy lab, benchmark API and evidence presentation | Implementation and browser test prepared; final GUI execution deferred |

## Completed checks before deferral

- Focused advanced-QA/Android regressions: 71 passed in 50.91s.
- Existing web submission with contract checks: 1 passed in 47.79s.
  Report: runs/127.0.0.1_52659_20261105_201409/report.html.
  Approved login passed and four seeded expectations failed, yielding Not Ready.
- Clean advanced Android run: 13 passed, zero application failures and zero execution errors.
  Report: runs/advanced_android_20261105_201412_clean/report.html.
  Covers valid/invalid login and registration, empty/valid forms, native/WebView navigation, calculations,
  API expectations and read-only SQLite checks.
- Earlier failed development runs remain as diagnostic evidence and are not counted as successful verification.
- The seeded Android run was stopped at the user's request. Its partial results are not a completed benchmark.
- The complete regression suite was stopped at the user's request. No completed full-suite result is claimed for
  this phase. The previous phase's 342-pass result is historical.

## Later execution checklist

1. Run the focused QA/Android regression tests.
2. Run tests/test_qa_web_pipeline.py.
3. Enable BLOWAI_ADVANCED_E2E=1 and run tests/test_qa_native_device.py against the controlled APK.
   The suite recreates local backend resources and checks clean, seeded, and clean-repeat conditions.
4. Enable BLOWAI_QA_UI_E2E=1 and run tests/test_qa_ui.py for real contract-form and accuracy-lab interaction.
5. Run the complete non-slow regression suite.
6. Build the presentation from completed runs and independently supplied expected outcomes.

Do not start tests or live demonstrations until the user is ready for the execution phase.

## Main implementation files

- backend/qa_contracts.py: shared validated contracts, Decimal expressions and scenario provenance.
- backend/qa_runtime.py: trusted approved-flow runtime and Android/native-WebView adapter.
- backend/qa_oracles.py: bounded GET and read-only SQLite verification, private input resolution.
- backend/qa_web.py: Playwright adapter integrated with the existing website execution stage.
- backend/qa_benchmark.py: known-truth metrics, repeated Android runs and evidence presentation.
- Existing Android design/runtime/executor/conftest, shared executor/failure analysis, API and reports were extended.
- frontend/qa-lab.html and frontend/qa-lab.js provide the accuracy and presentation UI.
- Controlled Python fixtures and four advanced-QA test modules provide repeatable verification.

Each application needs its own actual locators, approved account references, expected business behavior and backend
configuration. SQLite is the supported direct database adapter; other databases require additional adapters.
Hybrid testing requires a debuggable Chrome-based WebView and a matching server-side ChromeDriver.
Physical phones, other Android/WebView versions, customer infrastructure and cloud-provider execution remain
unverified. Native iOS is outside this Android/Windows scope.

See 13_ADVANCED_QA.md for configuration and startup instructions.
Checkpoint: .snapshots/before_advanced_qa_20261105_190809.zip.


The subsequent page-component inventory and nested-menu changes are documented in 14_PAGE_COMPONENT_INVENTORY.md. They are implemented but have not been executed; include their prepared tests in the later verification phase.
