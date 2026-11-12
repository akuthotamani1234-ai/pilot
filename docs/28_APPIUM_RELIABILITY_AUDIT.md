# Appium reliability audit — 8 November 2026

This audit supersedes earlier statements that the implementation was perfect or
that passing a small demo proved complete application testing. The failed run
`android_20261108_132755_52596d` recorded 23 passes, 78 execution errors and one
blocked item. Those errors required investigation; they are retained as evidence.

## Corrections

- Native XML inventory clips controls to the app viewport and scroll containers,
  honors hidden ancestors, and excludes offscreen controls from visible tests.
  Multi-window system bars cannot become the app viewport.
- Exact text locators never use truncated long labels. Icon-font characters are
  excluded from generic text assertions. Accessibility IDs and resource IDs keep
  priority over text and contextual XPath.
- Stable native screen containers distinguish routes sharing headings or controls.
  Dynamic embedded website banners no longer create extra native routes.
  Embedded DOM interaction uses explicitly configured hybrid flows.
- Discovery and path replay wait for rendered destinations after each navigation
  hop. Loading screens cannot become recorded destination evidence. Recovery
  remains bounded and can relaunch only the selected package without wiping data.
- Repeated native tabs can reuse an actually observed destination, conserving the
  discovery budget. Action, depth, screen, time and recovery limits remain explicit.
- Read-only cases can reuse an already verified screen after another read-only
  case. Mutating flows still restart from the observed launch state.
- Launch readiness waits for the selected package during the launcher's handoff,
  without inspecting unrelated foreground apps.
- UiAutomator2 startup/install/ADB waits have bounded allowances for slow emulators.
  Android system-process ANRs produce a direct environment diagnosis rather than
  an unfinished-launch message. Known System UI Wait recovery remains bounded.
- A lost device/session stops later test attempts. Remaining tests become blocked,
  with the original infrastructure cause retained. Cleanup does not create a
  second copy of the same disconnect. Classification follows the original cause
  even when the displayed message is shortened or the loss occurred while typing.
- The setup form exposes the exploration timeout, defaulting to 300 seconds.
- The opt-in hybrid verification now uses the persistent ChromeDriver location in
  `tools/chromedriver`, rather than a deleted historical run folder.
- Explicit empty input clears the field without an empty typing command. Readback
  distinguishes a platform-reported placeholder (`showing-hint`) from retained
  input; text that failed to clear still fails. Input errors identify their
  exception class without exposing entered values.
- Appium commands request sensitive-data masking using an isolated connection
  class. Wire-level transport tests verify the header is sent on commands, because
  the installed Appium client's own header dictionary can shadow the Selenium
  configuration. See [Appium's masking mechanism](https://appium.io/docs/en/3.4/developing/sensitive/).
  This covers server log fields marked sensitive by Appium; arbitrary external
  plugins and independently configured debug logs require their own controls.

## What implemented support means

| Capability | Supported scope |
|---|---|
| Target selection | APK upload, installed package on the selected device, Android Chrome URL |
| Device startup | Start a selected installed AVD, wait for boot, reuse an existing emulator; device lock |
| Discovery | Native hierarchy or Chrome DOM, component inventory, safe navigation, saved replay paths and bounded coverage |
| Locators | Unique accessibility ID, resource ID, UIAutomator text, contextual XPath; CSS in Chrome/approved WebViews |
| Functional flows | Approved typing, validation, selections, enabled/visible/text/screen assertions and explicit result oracles |
| Gestures | Native swipe, drag and bounded scroll-to-target |
| Hybrid | Approved native/WebView/native transitions with matching ChromeDriver and origin checks |
| Business checks | Explicit displayed expectations, decimal calculations, approved HTTP GET and read-only SQLite |
| AI | Optional provider readiness, evidence-based design and validated generated Python; explicit fallback warnings |
| Execution | Serial Pytest, stop handling, device/session loss handling and cleanup |
| Evidence | Actual assertions, screenshots when privacy permits, HTML/JSON/Excel results and deterministic verdicts |

The framework does not infer every business rule or test every possible Appium
command. Discovery does not prove business correctness. Credentials, approved
flows and expected outcomes are needed for protected or application-specific
behavior. Native iOS, device farms, other database engines, arbitrary OS permission
changes and physical-device compatibility are outside this verification.

## Verification

Automated regression and real-device evidence are recorded separately. No fresh
cloud AI request is represented as verified by a rules-only run. Earlier failed
and interrupted runs are preserved; final results below must be read with their
reported scope and any blocked checks.

- Final consolidated Android/emulator/API/UI/runtime/contract regressions:
  **175 passed, 1 skipped**, `logs/appium-final-regression.xml`. The skipped
  check is the opt-in real browser-to-emulator UI test, verified separately below.
- Existing real Playwright contract pipeline: **1 passed**, correctly identifying
  its planted defects; `logs/appium-web-regression.xml`.
- Ruff on the modified Python files and JavaScript syntax checks passed.

Fresh real-device runs through the studio's API, using rules/templates:

| Entry method | Run | Functional results |
|---|---|---|
| APK upload | `android_20261108_160312_b5f56f` | 3 passed, no failures/errors |
| Installed package | `android_20261108_160615_46a10e` | 10 passed, no failures/errors |
| Android Chrome URL | `android_20261108_160943_de765c` | 2 passed, no failures/errors |

These were configured-flows-only runs. Their verdict is **Ready with Risks**:
other discovered navigation was intentionally outside their execution scope.
Passing these checks does not establish complete app coverage.

The broader run `android_20261108_154928_0a998a` was interrupted when the emulator
disappeared by itself: 48 passed, 3 errors, 35 blocked. The user confirmed it was
not a manual close. One error exposed the launcher-handoff issue; the next two
occurred as the device disappeared, with a truncated cause delaying disconnect
classification until the second error. Both code issues were corrected above.
Appium subsequently crashed during cleanup of the disconnected device and was
restarted. No Windows application crash, resource-exhaustion or display-driver
event identified the emulator's exit cause. That environmental cause remains
unconfirmed; restarting it is not proof of a permanent emulator repair.

Additional real-device verification preserves the original failures:

- Clean controlled app: `advanced_android_20261108_162006_clean`, **13 passed,
  zero errors/failures**, including login, registration validation, required-field
  validation, native/WebView transitions, calculation, HTTP and SQLite oracles.
- A direct real-device input probe confirmed that Android exposed the hint as
  nonempty text on an empty field. Empty fill, nonempty fill and clearing an
  existing value now passed. A synthetic input marker was absent from the Appium
  log while command logging remained enabled. Proof:
  `.private/verification/appium-reliability/empty-field-probe.json`.
- Initial controlled runs `advanced_android_20261108_161046_clean` and
  `advanced_android_20261108_161405_seeded` retain the empty-field error which
  prompted the fix. Their passing checks are not substituted for the fresh rerun.
- Broken controlled app: `advanced_android_20261108_162418_seeded`, **8 passed,
  5 expected assertion failures, zero automation errors**. All five intended
  failing checks were detected: empty-name validation, native total, WebView total,
  API total and database total. Verdict **Not Ready**, as expected. Both clean and
  seeded suite validations passed; `logs/appium-real-native-hybrid-final.xml`.
- Previously errored/unexecuted cases: `android_reliability_replay_20261108_162744`,
  **37 passed, no failures/errors**, using recorded discovery and fresh execution.
  `replay_provenance.json` identifies the original run and selected case IDs. This
  does not replace the interrupted run or represent a new full crawl/AI generation.
- Actual browser UI to APK upload to Appium to report: **1 passed**,
  `logs/appium-real-ui-final.xml`. It verified the exploration timeout, report and
  case APIs, saved Excel output and private-APK access restriction, with no browser
  JavaScript errors. The test now opens the modern UI's Advanced section before
  filling its fields and cleans up its own Windows server process tree.

Fresh cloud AI, physical-device compatibility and the unexplained emulator exit
remain unverified. The emulator stayed running through the subsequent verification;
that observation does not establish that the intermittent shutdown is fixed.

## Reproduce the functional checks

Follow [the three-method workflow](27_RUN_ANDROID_TESTS_YOURSELF.md).
`demo-apps/webdriverio-functional-checks.json` contains three small checks.
`demo-apps/webdriverio-expanded-checks.json` contains ten checks, adding native
dropdown selection, button dialog, invalid email, sign-up validation, horizontal
swipe, bounded vertical scroll and drag-and-drop. These are WebdriverIO-specific
examples, not general locators for every app. Review actual run outcomes before
using them as verification evidence.

Apps are installed separately on each emulator. The same downloaded APK can be
used again on a new emulator. After installation, choose the installed-app method
on that same emulator. Stop a test in Blow AI before closing its emulator or
stopping the Appium server.
