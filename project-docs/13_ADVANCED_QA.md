# Approved functional flows, backend oracles and QA accuracy

Blow AI uses Python for these features. The Java application under tests/android_demo is a controlled Android fixture,
separate from the reusable framework and generated customer tests.

## What is implemented

| Capability | Implementation |
|---|---|
| Native login and forms | Explicit approved flows, environment-based secret references, positive/negative expectations, input validation and enabled-state checks |
| Business rules | Decimal expressions over visible values and configured constants; only declared variables and + - * / are allowed |
| Backend verification | Explicit-origin HTTP GET/JSON-pointer checks and read-only SQLite SELECT checks, optionally after a UI setup flow |
| Hybrid applications | Native ? the selected app's debuggable WebView ? native; CSS in WebViews, native accessibility/resource IDs outside |
| Accuracy benchmarking | Known-defect precision/recall, false alarms, unanswered cases, missed defects and repeated-condition instability |
| Demonstration | /qa-lab builds an evidence presentation from actual saved runs and user-supplied ground truth |

These are framework features. Each application needs its own locators, approved account references and expected behavior.
Blow AI does not invent domain rules, credentials, API endpoints or database connections.

## Configure the same contract in web or Android mode

The website advanced settings and Android form both accept a QA contract JSON object. The Android form also offers
**Run only configured QA contract checks**. Without that option, explicit checks accompany the existing observed-UI
and AI-designed cases. Discovery itself continues to perform only safe navigation.

The machine-readable schema is available at GET /api/contracts/schema. Configuration contains:
- version: 1
- test_environment: true only for an approved test environment
- flows: approved actions and expected outcomes
- rules: explicitly configured numeric relations
- checks: API or database expectations
- allowed_origins: exact HTTP(S) origins for API/WebView access

Every flow must contain a result assertion. Authentication flows additionally require a submission followed by a
post-login result assertion. A flow without approval is Blocked, never Passed. Submit steps must have purpose
test_form. Payment, delete, transfer and other recognized irreversible actions remain blocked even in approved flows.
No permission dialog, MFA challenge or security protection is bypassed.

Use the examples under project-docs/examples as starting points. The default examples require you to review and
enable their approvals. They contain placeholder application selectors; replace them with your app's actual IDs.
`ecommerce-web-contract.json` is a public shop-style web template (search → open product → add to cart). Flows stay
`approved: false` until you adapt the CSS placeholders and explicitly approve them in a test environment.

## Secrets and configured databases

Store account values in the server process environment or the existing local .env, never in the JSON contract:

~~~powershell
$env:BLOWAI_SECRET_LOGIN_USERNAME = "<approved test username>"
$env:BLOWAI_SECRET_LOGIN_PASSWORD = "<approved test password>"
$env:BLOWAI_DB_QA = "C:\QA\test-data.sqlite"
.\ui.bat
~~~

The example contracts contain only secret_ref names. Password-like inputs reject inline values. Runtime input
contents are omitted from screenshots and generated code; filled forms are not captured. Approved credential values
are passed only to the trusted Android worker through its process environment; no credential file is written. These values
are redacted from the framework's logs and results. Generated workers do not inherit API keys or BLOWAI_SECRET_
environment values. The selected Appium server must also be configured appropriately for handling test credentials.

Database paths are configured by the machine operator using BLOWAI_DB_ variables. The UI accepts only a reference,
not an arbitrary server-side database path. SQLite connections use mode=ro, query_only, a SELECT-only authorizer,
disabled extension loading, a progress deadline and evidence-size limits. Queries are parameterized. This release
supports SQLite; direct PostgreSQL, SQL Server and MySQL connections are not implemented.

API checks require an approved origin, use GET only, disable redirects and environment proxy inheritance, and limit
response size/timeouts. Configure endpoints that are read-only. Bearer tokens use secret_ref environment names.
The JSON pointer identifies one scalar value; the configured expectation includes its JSON type.

## Flows and business checks

Supported step actions are tap, fill, assert_visible, assert_not_visible, assert_enabled, assert_text, assert_screen
and context. Context is native or webview. Native selectors support accessibility_id, resource_id and text.
Browser/WebView selectors use css. Locators must identify exactly one visible control before interaction.

Use expected screen titles or stable result labels to verify successful and unsuccessful login, registration,
required-field validation and state transitions. A click alone is not a verified workflow. Numeric rules parse
a single visible number using a decimal point; configure a locator around the number instead of an entire paragraph.
Expressions do not allow eval, Python function calls, attributes, exponentiation or arbitrary code.

Native cases execute through the generated Python plan mobile.assert_contract("configured_id"). AST validation
preserves this exact call and the approved contract runtime executes its assertions. The model cannot add hidden
actions or weaken the configured expectation. Contract scenario provenance is contract; generated Python provenance
is separately llm or template. Browser contracts use maintained Python runtime code, labelled contract rather than
AI-generated code, and are merged into the existing web results, failure analysis and reports.

## WebView prerequisites

The Android application must expose a debuggable Chrome-based WebView. Use an Appium server-side ChromeDriver that
matches that WebView's version. Configure its executable on the same machine:

~~~powershell
$env:BLOWAI_CHROMEDRIVER = "C:\QA\chromedriver.exe"
~~~

Automatic binary downloading and arbitrary executable paths from an API request are not enabled. The adapter selects
exactly one WEBVIEW context belonging to the selected package and checks its URL against the approved origins.
It restores the native context after each case. Missing/ambiguous contexts and driver mismatches are execution
errors, not application defects.

Reference: https://appium.github.io/appium-uiautomator2-driver/latest/guides/hybrid/

## Benchmark and presentation

Open **QA accuracy lab and demo reports** from the main page, or visit /qa-lab. Select saved runs of the same
condition, enter known expected outcomes by case ID, and add each condition to the manifest. Review it, then build
the presentation. It links back to the original reports and downloadable classifications.

A condition may contain multiple repeated runs. Instability is compared within a condition, not between deliberately
different clean/defective conditions. Infrastructure failures, blocked actions and missing results are unanswered.
They never count as true positives or clean passes. Unanswered known defects reduce known-defect recall.
A metric with no denominator is Not measured. These numbers apply only to the supplied benchmark.

~~~powershell
.venv\Scripts\python.exe -m backend.qa_benchmark --manifest .\benchmark.json --out .\runs\qa_showcase
# Reuse a live application's existing configuration, one run at a time:
.venv\Scripts\python.exe -m backend.qa_benchmark --config ".\runs\<run>\.private\android_config.json" --repeats 3
~~~

The referenced application, credentials, API and database must remain available. Controlled fixture tests use
temporary servers; replay those through their pytest command, which recreates the fixture environment.

A clear demonstration is clean ? deliberately seeded defect ? failed expectation with evidence ? corrected clean
repeat. Present locator recovery separately and preserve the original assertion. Label all seeded behavior and
show observed coverage limits.

## Verification commands

~~~powershell
.venv\Scripts\python.exe -m pytest tests/test_qa_contracts.py -q
.venv\Scripts\python.exe -m pytest tests/test_qa_web_pipeline.py -q -s
$env:BLOWAI_ADVANCED_E2E = "1"
$env:BLOWAI_ANDROID_ARTIFACTS = "$PWD\runs"
.venv\Scripts\python.exe -m pytest tests/test_qa_native_device.py -q -s
.venv\Scripts\python.exe -m pytest -n 3 --dist loadfile -m "not slow" -q
~~~

Actual results for this implementation are recorded in ADVANCED_QA_VERIFICATION.md when verification completes.
Physical phones, additional Android/WebView versions and live customer/cloud systems require their own validation.
Native iOS remains outside this Android/Windows scope.
