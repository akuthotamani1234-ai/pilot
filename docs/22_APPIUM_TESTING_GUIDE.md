# Testing with Appium in Blow AI

Start the product by double-clicking `ui.bat`. Choose Android/Appium, then Standard testing or your approved
MCP workflow. Select a connected emulator/device and upload an APK or enter its installed package.
Alternatively, choose **Website in Android Chrome** and enter its URL. Choose the AI provider/model. A replacement API key can be entered in the per-run field; do not place it in chat,
test contracts or generated Python. Set the scope, review the expected behavior and start.

## Different kinds of testing

| Kind | What it checks | Setup |
|---|---|---|
| Native UI | Android controls, text, enabled states and navigation | UiAutomator2 and a device/emulator |
| Functional flows | Data entry, validation, login and state changes | Approved flows with actual result assertions and credential references |
| Gestures | Swipes, drag destinations and scrolling to a declared target | Observed container/target locators and a bounded approved flow |
| Business rules | For example, quantity times unit price equals the cart total | Explicit numeric sources and expected formula |
| Hybrid | Native controls plus an embedded WebView | Debuggable WebView, approved origins and matching ChromeDriver |
| Mobile web | A website in Android Chrome, discovered through its DOM | Main source picker: Website in Android Chrome; compatible ChromeDriver required |
| Regression | Repeat saved tests after app/framework changes | The same validated script, expectations and traceable source run |
| API/database | Read-only verification behind UI outcomes | Approved GET endpoints or configured read-only SQLite references |

Smoke, regression, positive/negative validation and exploratory checks are test purposes. They can use the same
Appium engine. Performance, security, accessibility audits and every hardware/permission/biometric scenario
need their own specific checks; running Appium does not automatically perform them.

## Inspector and locators

Appium Inspector displays the screen hierarchy and helps inspect/check selectors. It is not the execution engine.
The Appium server's UiAutomator2 driver executes the generated Python tests. The current local Inspector is at
`http://127.0.0.1:4725/inspector/`; this dedicated demo server was started with the Inspector plugin enabled.

Prefer a unique accessibility ID or resource ID. Native exact-text queries use UiAutomator selectors.
For repeated product rows, use contextual XPath anchored to an observed unique row label; do not select the first
matching element merely because several elements share an ID. The runtime checks uniqueness before interacting.
Not every locator strategy should be forced onto every element. CSS belongs to WebView/browser contexts.

## What a result means

A click or a discovered component is not a passing functional test. A test must assert its expected result.
Missing locators, startup failures and incomplete observations remain errors/inconclusive results. Blocked controls
remain blocked, and scope limits are listed. Review the HTML report and Excel results, including errors and
unvisited controls, before treating a run as sufficient for release.

See `21_FEATURE_AUDIT_AND_LIVE_ANDROID.md` for the implemented/verified/remaining feature matrix.
See `24_ANDROID_CHROME_AND_GUIDED_FLOWS.md` for the integrated Chrome workflow, guided test-flow editor and fresh verification evidence.
