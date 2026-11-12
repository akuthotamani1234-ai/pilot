# Android Chrome integration and guided functional checks

## Using the interface

Launch `ui.bat`. For a website on an Android device, select **Android testing**, then choose **Website in Android Chrome** under App source. Enter its URL, select a connected device and choose your AI/privacy settings. APK and package fields are hidden for this target. Android Chrome runs through the same job API, bounded discovery, test design, validated Python generation, Appium execution, live progress and HTML/Excel reporting as native Android.

For desktop website testing, continue using **Web testing / Playwright**. Both engines retain the Standard and approved MCP workflows. The MCP `start_android_test` tool now accepts `app_mode="web"` and `start_url`; APK and installed-package modes remain supported.

In the test configuration, use **Build a test flow** to add actions and expected results. The editor supports ordered clicks, typed test values, browser dropdown selection and explicit assertions. Mark form submissions as **Submit approved test form**. An authentication flow must include a submission followed by result evidence. The editor validates the flow before adding it to the existing configuration and preserves other flows, calculations and backend checks. Advanced JSON remains available.

**Validate configured checks** reviews the flow/rule/check counts, required private references and approvals without starting automation. A click by itself is not a passing functional check. Unknown business rules still need requirements; the product does not invent a correct expected outcome.

For passwords/tokens, enter a reference such as `secret:BLOWAI_SECRET_TEST_PASSWORD` in the builder. Configure the corresponding value privately in the launch environment or local `.env`, and restart the UI after changing it. Actual secrets must not be entered in contract JSON. They are resolved only for trusted execution and omitted from generated test data, screenshots and model input. The existing web account fields remain available for discovery login.

## What Android Chrome discovers

The crawler reads the rendered DOM using the actual Appium Chrome session. It records controls, headings, unique CSS locators, input capabilities, navigation links and dropdown choices. Input values are omitted. Safe same-origin navigation, semantic expandable menus and nested states can be explored within the selected limits. Ordinary form submissions and downloads are excluded from discovery; approved functional flows perform data entry and submissions.

The DOM inventory is bounded to 1500 rendered nodes per screen, with an explicit discovery issue if truncated. Selected screen/action/depth/time/case limits remain visible in the report. Arbitrary hidden states, closed shadow roots, cross-origin frames and every possible business workflow are not guaranteed to be discovered. External-origin content is not inspected after navigation leaves the approved origins.

The Android report now includes **Control inventory** with observed locators and dropdown choices, plus a full `screens.json` link. The table displays at most 500 recorded controls; the JSON retains the bounded recorded inventory. Coverage and case URLs use the website URL for Chrome targets. Only completed passing checks count as execution evidence.

## Runtime corrections found during verification

- Appium's attribute API can return an input's original HTML attribute instead of its typed DOM value. Browser field readback and input identification now use DOM properties.
- Shortened container text is inventory context, not an exact expected label. Automatic text assertions are restricted to comparable, untruncated leaf text; other controls still receive visibility checks. Explicit expected-result assertions remain intact.
- Browser contracts wait for a unique visible control after navigation instead of checking an unfinished page immediately.
- Expected-text assertions wait up to eight seconds for the declared result and re-resolve a replaced element. They retain the exact expected text; the old page heading is not treated as the final result during asynchronous navigation.
- Accessibility skip links are keyboard-focused before a generated journey clicks them.
- Browser contract cleanup returns to its browser context; native and hybrid cleanup retain their native default.
- Browser dropdown steps select the configured value and assert it was retained, in both Playwright and Appium.
- Appium session startup has a separate bounded 180-second default (configurable from 60–300 seconds), followed by the ordinary command timeout. A live Chrome startup took 58.32 seconds, explaining the previous fragile 60-second limit.
- The environment checker verifies Appium's registered UiAutomator2 package and actual entrypoint before invoking the CLI. A CLI timeout is reported as an inability to verify, not proof that the driver is absent. The corrected local check completed in 0.38 seconds.
- Native startup requires meaningful controls/text, rather than accepting an empty activity hierarchy. Multi-window inspection exposes blocking platform dialogs. Only the known Android **System UI isn't responding → Wait** control can be recovered automatically, at most twice per session; recovery is recorded and makes coverage carry risk. Permission prompts, application ANRs and destructive system actions are not approved by this recovery.

Chrome must be installed on the device and have a compatible ChromeDriver on the host. An explicit `BLOWAI_CHROMEDRIVER` takes priority. Otherwise, the product can reuse a matching driver from `tools/chromedriver/chromedriver.exe` or the existing managed verification-tool folder after comparing major versions. Appium's own driver selection remains the fallback when no managed match is found. No driver download or system-wide change is silently performed. See the [official UiAutomator2 capabilities reference](https://appium.github.io/appium-uiautomator2-driver/latest/reference/capabilities/) for Chrome mode and driver requirements.

## Verification evidence

Artifacts are under `runs/integration_gap_verification`. `release-regressions.xml` records **201 passing combined regressions** in 92.16 seconds. `verified-platform.xml` records 78 focused checks. JavaScript syntax and Ruff checks passed. The final evidence manifest records the exact source checkpoint and test reports.

The fresh Playwright run `the-internet.herokuapp.com_20261107_200422` completed 14 checks, all passing, including valid demo login and empty-login validation. Its verdict is **Ready with Risks**, with a deliberately limited page scope. Earlier broader verification runs and their failures remain unchanged.

The selected completed runs are:

| Engine and scope | Passed checks | Failed / errors | Blocked scope cases | Run |
|---|---:|---:|---:|---|
| Playwright login page | 14 | 0 / 0 | 0 | `the-internet.herokuapp.com_20261107_200422` |
| Android Chrome login and DOM | 6 | 0 / 0 | 1 | `android_20261107_202756_717c66` |
| Android Chrome dropdown and DOM | 6 | 0 / 0 | 1 | `android_20261107_203028_4e6bfd` |
| Native Sauce demo configured flows | 11 | 0 / 0 | 0 | `android_20261107_203423_6880f6` |

All four verdicts are **Ready with Risks**, retaining bounded discovery and unresolved scope. The native run records one bounded System UI Wait recovery and confirms a cart total of **59.98 expected / 59.98 actual**. Recovery is not counted as a passing application feature.

Open `/runs/integration_gap_verification/index.html` on the running UI server for the consolidated overview and actual HTML/Excel reports. `selected_live_results.json` retains counts, exact report hashes, scope and contract results; `verification.json` links this evidence to the source checkpoint. These public demo runs use **No AI (rules)** and explicitly approved contracts. They are not evidence of a fresh cloud-model call. Optional AI design remains connected to the shared pipeline; an AI-assisted live retest requires a working provider/model and consent.

The native verification uses the previously verified contract from `sauce_ai_replay_20261106_165209`. An earlier attempt used the older initial contract revision, which checked controls after their menu/screen had closed; those failed attempts are retained. The corrected verification restores the existing approved interaction sequence rather than weakening the assertions. Passing these selected flows does not establish complete application coverage.

The local emulator also became unresponsive during earlier attempts, including a visible Android System UI ANR. Its installed apps/data were preserved while the owned emulator and test Appium service were restarted. The recovered-device verification uses software graphics. Interrupted/device-failure attempts remain separate from completed application checks; platform recovery must not be presented as a passing app feature.
