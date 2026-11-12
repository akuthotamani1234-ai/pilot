# Android functional testing: added features and your next run

The latest additions have unit, protocol and mocked-browser checks. **Live
execution of these additions is deferred at your request.** A built APK is
available for your own run; compilation does not prove its tests pass.
The earlier live evidence is recorded separately in
[the reliability audit](28_APPIUM_RELIABILITY_AUDIT.md).

## Verification of this expansion

- Final unit, mocked Appium/W3C protocol and intercepted-browser suite:
  **244 passed, three real-browser cases deliberately deselected**;
  `logs/appium-feature-expansion-final.xml`.
- Python lint for the backend and changed test files passed. Both modified
  frontend scripts passed Node syntax checks.
- The v1.2 fixture compiled offline. The APK's ZIP integrity and SHA-256 match
  `demo-apps/controlled-apk-build.json`. No installation or live test of v1.2
  was performed after expansion.
- The examples validate as 33 WebdriverIO flows (seven blocked until permission
  approval), seven controlled fixture flows and two Android Chrome flows.
  Validation is not a passing live execution result.

## What changed

- Native discovery visits sibling routes before deeper routes, recognizes
  semantic menu drawers and keeps separate embedded-WebView containers.
- Bounded vertical scrolling inventories controls actually rendered below the
  fold. Recorded scroll containers allow tests to find those controls again.
  Unknown containers, exhausted budgets and unvisited routes stay reported as gaps.
- Approved flows support setup/login dependencies, relaunch without clearing app
  data, switch/checkbox state assertions, gestures and scroll-to-target actions.
- Private test-account fields supply credentials to the worker for that run.
  Saved flows contain secret references rather than the supplied credentials.
- Explicit emulator permission flows can set, request, allow/deny and verify
  supported permissions, then restore the original granted/denied states.
- The visual flow builder exposes those actions, setup flows and timeouts.
  The sample picker can load an example or undo that replacement without running it.
- Reports link `features.json` and distinguish configured functional checks,
  UI checks and observed controls still needing functional checks. There is no
  claim that every feature or every possible state in an app was tested.
- The default designer now replays safe navigation whose destination was
  actually observed during discovery, then checks that destination. It samples
  repeated catalogue labels and prices instead of creating a separate test for
  every repeated card. Business behavior still requires expected results or an
  approved flow.
- The submitted exploration scope is bound to the values shown in the form.
  If those values change before submission, the run is rejected so a displayed
  depth cannot silently become a different saved depth. A stopped run records
  remaining cases as blocked/not run rather than application execution errors.

## Start the studio

1. Finish or stop any existing job. Restart the Blow AI terminal and double-click
   **ui.bat** so the server loads the latest code. Keep its terminal open.
2. Select **Android testing — Appium**, then **Standard testing**.
3. Refresh device status. Select `blowai-api36` (automatic emulator start) or an
   available Android device. A closed selected emulator starts when you click
   **Start Android test**. Keep it running for the entire job; minimizing is okay.
4. Reuse the local Appium server if ready. Otherwise start it in PowerShell:

   ```powershell
   & "$env:LOCALAPPDATA\BlowAI\AndroidTools\node_modules\.bin\appium.cmd" --address 127.0.0.1
   ```

5. For your first verification, select **No AI (rules)**. Configured functional
   flows do not need an AI key. To use cloud AI later, enable its privacy setting,
   select the provider/model and enter the key in the app. Disable rules fallback
   when you specifically want an unavailable AI to stop the run.

## Choose one of the three app sources

| Source | What you supply | Where to get it | Where it belongs |
|---|---|---|---|
| Upload an APK | Android `.apk` installation file | Your developer/build pipeline, or an official demo release | Choose it directly from Downloads or any accessible folder; no copying or unzipping required |
| Already installed on the device | Package identifier, such as `com.wdiodemoapp` | The developer/Android manifest; use the known demo identifier for this example | The app must already be installed on the particular selected emulator/device |
| Website in Android Chrome | A website URL | Your test website | Enter it in Website URL; no application APK or native package needed |

Installing an APK on one emulator does not install it on another. On a new
emulator, use Upload an APK again. For a newly supplied app, its expected results
and locators need their own configuration; a WebdriverIO sample is app-specific.

## Run the 33-flow WebdriverIO example

1. For an APK, select `demo-apps/android.wdio.native.app.v2.2.0.apk`.
   Alternatively use the same file directly in Downloads. If not downloaded,
   open the official [v2.2.0 release](https://github.com/webdriverio/native-demo-app/releases/tag/v2.2.0),
   expand **Assets** and download `android.wdio.native.app.v2.2.0.apk`.
   Do not select the source ZIP or an iOS file.
2. Or select **Already installed on the device**, select the emulator where
   WebdriverIO is installed and enter package **com.wdiodemoapp**.
   Leave Launch activity blank for automatic launcher detection.
3. Expand **Advanced checks and exploration settings**. Under **Sample test
   flows**, select **WebdriverIO v2.2 — 33 configured flows**, then click
   **Load selected example**. It replaces the JSON field; **Undo example** restores
   the previous value. Loading does not start a test.
4. Enter a disposable test email such as `blowai-demo@example.test` in the private
   test-username field and a disposable password of at least eight characters
   in the private test-password field. These supply
   `BLOWAI_SECRET_TEST_USERNAME` and `BLOWAI_SECRET_TEST_PASSWORD` for this run.
   WebdriverIO's sample login/signup uses local demo alerts, not a real account backend.
5. Tick **Run only the configured test flows and business checks**. Set Maximum
   test cases to at least **33**. The configured flows have their own bounded
   deadlines; exploration limits do not increase functional-flow coverage.
6. The sample contains **26 approved flows and seven permission drafts**.
   Leave the permission approval unticked to keep those seven blocked. To test
   them on the selected emulator, review the listed permissions, then explicitly
   tick the emulator permission approval. This also enables the seven drafts.
7. Review authorization, then click **Start Android test** yourself. Wait for the
   report rather than assuming the sample's expected results all passed.
8. Review menu destinations, input/switch/dropdown/dialog validation, gestures,
   demo login/signup, storage save/readback/clear, pinning and optional permission
   results. Download Excel and open **Feature coverage** for the JSON breakdown.

The example is tailored to WebdriverIO **v2.2.0** and the provided emulator.
OS-specific photo permissions can differ on older Android releases. A mismatch
must be investigated; it is not evidence of a product defect by itself.

## Run the seven controlled protected-flow and preview checks

1. Start a new Android run and choose **Upload an APK**.
2. Choose `demo-apps/blow-ai-controlled-demo-v1.2.apk`.
   Its offline build and checksum are recorded in `demo-apps/controlled-apk-build.json`.
   It has not been installed or live tested after these additions.
3. In Advanced settings, load **Blow AI fixture — protected flows and safe previews**.
4. Enter **demo** and **demo123** in the private test-account fields.
5. Enable configured-flows-only and set Maximum test cases to at least **7**.
6. Review authorization, start the test and review every actual outcome.

These checks cover a signed-out access wall, setup login before protected access,
session persistence after relaunch, logout, order preview and removal preview.
The preview controls perform no real purchase or account deletion. Actual
irreversible operations remain blocked by the execution policy.

## Run the Android Chrome example

1. Start a new Android run, select the emulator and **Website in Android Chrome**.
2. Set Website URL to `https://the-internet.herokuapp.com/dropdown`.
3. Load **Android Chrome — dropdown selection checks**, enable configured-flows-only
   and set Maximum test cases to at least **2**.
4. Complete any first-use Chrome prompts on the emulator before starting.
5. Review authorization, start the test and review the two actual results.

## Permissions, scope and stopping

Permission automation requires a native app, a selected emulator, explicit
flow/policy approval, a supported declared permission and a matching app name on
the system prompt. It does not grant arbitrary permissions or operate on a
physical device. Standard Android/Google permission controllers and English
prompt text are supported; other OS/controller/language variants need verification.
The original granted/denied states are restored after the flow, including a failed
assertion. Restoration errors remain errors. Android request-history flags may
change; this is not a complete device-settings rollback.

Use the studio's **Stop** control to stop a job. Wait for cleanup and its final
status. Closing the emulator mid-run disconnects the device. To stop the Appium
server after jobs finish, use Ctrl+C in its terminal. Appium Inspector is an
optional locator/session inspection tool; automated execution uses UiAutomator2
and does not require opening Inspector.

An unexplored screen, blocked flow, missing assertion or unavailable credential
still limits the evidence. Test-specific business requirements, backend checks
and appropriate disposable data remain necessary. The earlier unexpected emulator
shutdown's root cause is unconfirmed. Fresh cloud-AI and physical-device validation,
and live verification of the latest expanded suite, are still pending.
