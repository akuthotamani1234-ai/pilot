# Android form validation and testing readiness

The recording `android.mp4` and run `android_20261113_152701_c7dbb5` show useful automation, but do not establish
complete manual-tester coverage. The run inspected nine screens and produced 55 results: 52 passed, one failed,
one error and one blocked. Its user-like coverage list has 29 passed, one failed and 28 not-tested entries.
The recorded form checks belong to the Webview URL form. Opening the Login menu item did not produce login
validation cases. A navigation check passing is not evidence that the form was exercised.

## Form-screen correction

The actual app's Login screen has an activity/scroller identity shared with a product-detail screen. Without an
additional discriminator, discovery and test-build exploration can reuse the product screen instead of recording
Login, so its fields never reach the form-testing phase.

Screen identity now includes a digest of the native input schema and observed submit labels, based on stable control
identifiers and password metadata. It excludes entered text. Typing preserves its identity; Login, Signup and product screens
under the same shell remain distinct. Drawer identity and embedded WebView handling retain their separate paths.

In an authorized test-build run, Signup now receives empty-form and invalid-input checks before valid registration.
Empty checks explicitly clear password boxes through an internal private reference, preserving the contract rule
that sensitive fields never use inline values. Existing replay, action restrictions and secret masking still apply.
Test data is generated for the run. Successful login needs a supplied test account, an account registered during the
run, or an explicitly advertised sample account in the app. Signup is tested only when the application exposes it.
CAPTCHA and human verification remain explicit limits.

## What is already implemented

The Android implementation provides local Appium/emulator preparation, bounded native and Android Chrome
discovery, user-like taps and fills, scrolling, approved contract flows, replay verification, test-build form checks,
rotation/background/Back checks, scoped permission testing, crash/ANR evidence, locator recovery and reports.
These capabilities have different prerequisites and do not mean every Appium command or every application feature
has been tested. Device-feature screens may be opened while their camera/location/biometric actions remain
protected or unverified. Filled-form recordings are not retained because they can expose credentials.

## Appium Inspector

Inspector is an optional development/debugging client. It does not replace functional assertions. For the default
local server, use host `127.0.0.1`, port `4723`, path `/`, SSL off, and Android/UiAutomator2 capabilities with the
selected device's `udid` and the target APK or installed package. Both Appium and the selected device must be ready.
Use a separate Inspector session while Qpilot is idle so two clients do not drive the same device simultaneously.

The [official server settings](https://appium.github.io/appium-inspector/latest/session-builder/server-details/)
and [requirements](https://appium.github.io/appium-inspector/latest/quickstart/requirements/) describe the connection.
Inspector can also [attach to an existing session](https://appium.github.io/appium-inspector/latest/session-builder/attach-to-session/).
On Appium 3, automatic session discovery needs a separately enabled insecure feature; manually supplying a session
ID does not. Qpilot does not enable that feature automatically. Actual Inspector connectivity needs its own smoke
check; an Appium readiness check alone does not verify the Inspector application.

## Recommended priorities

1. Extend the form matrix with app-specific required fields, boundaries, password confirmation and server-side
   errors. Add session expiry and approved authentication recovery. Verify outcomes against defined requirements.
2. Extend existing QA contracts with API/database evidence for authorized business outcomes, including persistence
   and cleanup of run-owned data. Retained field values alone must not receive business-verification credit.
3. Add a masked Android action timeline: intended control, action, expected result, observed result and elapsed
   time, linked to the current test. Preserve failed attempts and retries.
4. Promote coverage gaps in the UI: unvisited screens, forms not exercised, missing credentials, unsupported
   controls, permission limits and budget stops. Keep those separate from passed checks.
5. Use the existing Accuracy Lab with known-good scenarios and deliberately seeded defects to measure missed
   defects, false alarms and repeatability. Do not publish an unsupported accuracy percentage.
6. Broaden validation across a real Android phone, multiple Android versions and screen sizes, and explicit
   offline/slow-network, permission, keyboard and lifecycle scenarios.

Appium Inspector is useful for reliable locator selection; adding more AI models is not the first accuracy fix.
For accessibility coverage, consider Android's [Accessibility Scanner and Accessibility Test Framework](https://developer.android.com/guide/topics/ui/accessibility/views/testing-views)
alongside manual accessibility checks. These are optional additions, not prerequisites for fixing form discovery.

Offline regressions cover shared-shell form identity, typing stability, form scheduling, private password clearing,
Signup validation, and the existing native/browser form journeys. A live device smoke check and CI are separate
evidence; historical reports are preserved rather than relabeled as new successful runs.
