# Feature audit and live Android verification

This is the current audit for 6 November 2026. It distinguishes implemented code, regression checks,
live execution and scope limits. Historical reports remain historical; they do not prove every current feature.

## Coverage matrix

| Capability | Implementation and evidence | Limit |
|---|---|---|
| Python framework | Existing FastAPI/LangGraph/Pytest product, extended in place | Android SDK/driver and sample applications have their own Java components |
| Playwright workflow | URL/project setup, discovery, design, scripts, execution, analysis and reports; included in the broad regression pass | A fresh full OpenAI Demoblaze run after the final web fixes has not completed |
| Nested web controls | Observed opener chains, dropdowns, menus, dialogs, forms, pagination and DOM inventory; targeted Contact values verified on Demoblaze | Bounded actions, inaccessible frames, closed shadow roots and canvas internals can leave gaps |
| Form accuracy | Logical modal forms, footer submit associations, label correction, readback, separate dialog identities | Backend acceptance requires an observed response or explicit expected behavior |
| AI grounding | Reject broad text selectors, invented heading names and unobserved messages; preserve approved account scope | Validation reduces known errors; it is not proof that any AI output is correct |
| Native Android | APK upload, installed apps, SDK/ADB/device checks, local Appium/UiAutomator2 sessions and device lock | Current live verification uses an Android 16/API 36 emulator |
| Android discovery | Native hierarchy, active-drawer scope, element identities, navigation paths and explicit action/depth/time limits; recovery replays from Home before using Back | It does not autonomously exercise every offscreen or protected workflow |
| Native locators | Unique accessibility/resource/text selectors; contextual XPath anchored to observed row labels; recorded fallback before healing | Ambiguous targets are refused; targets still need live uniqueness checks |
| Launch readiness | Every native case waits for the discovered start screen to settle, including contract flows | Cold starts have a bounded allowance; an unavailable app remains an execution error |
| Native AI | Actual OpenAI gpt-4o-mini proposals and Python generation ran on both demo apps | AI proposals currently cover up to three observed UI scenarios; domain flows need configured expectations |
| Native functional flows | Approved fill/tap/assert flows, required-field checks, synthetic credential references and explicit results | This is not automatic knowledge of an application's business rules |
| Native gestures | Approved swipe, drag and bounded scroll-to-target with alternate regions for nested gesture interception | Scroll-to-target is bounded to eight gestures and native containers |
| Business checks | Decimal calculations, approved HTTP GET/JSON-pointer and read-only SQLite checks | Other direct database adapters are not implemented |
| Hybrid WebView | Approved native/WebView/native contexts and CSS locators | Needs a debuggable supported WebView, approved origins and matching ChromeDriver |
| Android Chrome websites | Integrated URL source, DOM inventory, shared optional AI design, Appium runtime and reports; Standard and MCP workflows | Compatible device Chrome/ChromeDriver required; exploration and approved business flows remain bounded |
| Appium Inspector | Official local Inspector plugin installed; attached read-only to real sessions | Inspector is a developer inspection tool; UiAutomator2 executes the tests |
| AI key handling | Android now accepts a per-run password field; key enters only the worker environment and redaction list | It is cleared from the UI and not retained for another run |
| AI failure behavior | Provider readiness before discovery and optional refusal of rules/template fallback | A provider failure is not a passing AI run |
| Reporting | HTML, JSON, Excel, costs, errors, blocked scope and live case progress | Planned controls are counted separately from controls with passing execution evidence |
| MCP and privacy | Existing standard/MCP workflow and local/cloud consent gates; included in regressions | No connected MCP assistant was used for the current Android demonstration |
| Recovery | Bounded same-element locator repair and original assertions preserved | Recovery does not change business expectations to make a failure pass |
| Unverified environments | Physical devices and additional Android versions | Native iOS, device farms and every customer application are not verified here |

## Actual runs

- WebdriverIO native demo v2.2.0: actual OpenAI generation, 23 passed, one vertical-scroll error,
  and one blocked scope item. The app was subsequently uninstalled at the user's request.
- Sauce Labs My Demo App v2.3.0: official APK SHA-256 matched its release digest; actual OpenAI readiness,
  design and script-generation calls succeeded. The initial run exposed locator and launch issues;
  its report is retained at `runs/android_20261106_161826_5eb5f0`.
- Corrected replays use the exact same AI-generated Python, with explicit provenance and no new AI calls.
  Their approved setup steps include scrolling to offscreen quantity controls and checking the selected sort tick.
  They retain the cart-total and login expectations. Consult the final replay's summary for its actual outcomes.

The demos' login implementations are local demo behavior. A successful UI flow is not proof of production
authentication, account security or backend persistence.

## Regression evidence

- Broad non-slow regression pass: **469 passed in 1030.73 seconds**.
  Evidence: `runs/sauce_appium_verification/regressions-final.xml`.
- Subsequent native locator/startup/drawer changes: **82 focused Android checks passed in 44.59 seconds**.
- Three legacy fixtures were updated to supply observed message evidence or explicitly declared required fields.
  Unknown messages and a Save label alone are no longer treated as sufficient validation requirements.
- Slow end-to-end suites and a repeated known-defect benchmark were not all rerun in this audit.

The framework is not rated as perfect. Passing a declared suite establishes those checks on that environment;
it does not establish complete application coverage or a measured general accuracy percentage.
