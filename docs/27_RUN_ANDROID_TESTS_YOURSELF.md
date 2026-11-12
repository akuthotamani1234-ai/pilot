# Run Android tests yourself

For the latest 33-flow example, private credential fields and optional emulator
permission checks, follow the [expanded Android workflow](29_ANDROID_FEATURE_EXPANSION.md).
Those additions await your live verification; the smaller workflows below
describe the earlier verified examples.

The on-screen picture-guide links have been removed. Use this written workflow.
The previous run history has been cleared; downloaded demo apps and
the checks used in the successful live demonstration are kept in `demo-apps`.

## 1. Start the tools

1. Open your **Blow Ai** project folder.
2. You can leave the emulator closed. Select its name in the studio's
   **Android device** list; **Start Android test** opens it automatically and
   waits for Android to finish booting. To open it manually instead, run:

   ```powershell
   & "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" -avd blowai-api36 -gpu auto -memory 2048 -cores 2 -no-snapshot-load -no-snapshot-save
   ```

   If it is already running, reuse it. Wait until Android finishes booting.
   Keep the emulator running throughout the test. You may minimize its window;
   clicking its X button shuts Android down and disconnects it from Appium.
   Android Studio users can also start the device from **Device Manager**.
3. Start Appium in another PowerShell window:

   ```powershell
   & "$env:LOCALAPPDATA\BlowAI\AndroidTools\node_modules\.bin\appium.cmd" --address 127.0.0.1
   ```

   Keep that terminal open. If the studio already reports that Appium is ready,
   reuse the running server instead of starting a second one on port 4723.
4. Double-click **ui.bat** in the project root. Keep its terminal open while
   using Blow AI. It opens the studio in your browser, normally at
   <http://127.0.0.1:8000/>.
5. Select **Android testing — Appium**, then **Standard testing**.
6. Click **Refresh device status**. Under **Android device**, select the running
   `emulator-5554` or `blowai-api36 · start emulator automatically` when it is closed.
7. The form either reports a ready device or says it will start the selected
   emulator. Clicking **Start Android test** reopens a closed emulator, waits for
   boot, then submits the test. This can take a few minutes. A disabled Start
   button has an explanation in the form; resolve missing tools before continuing.
8. Select **AI provider → No AI (rules)** for your first attempt. Leave the model
   and API key blank. These saved functional checks do not require an AI key.

## 2. Method one: upload an APK

The APK is an app's installation file. You do not need to unzip it or install it
manually before choosing this method.

1. Under **App source**, select **Upload an APK**.
2. In **APK file**, click **Choose file** and select:

   ```text
   demo-apps\android.wdio.native.app.v2.2.0.apk
   ```

   This path is relative to your Blow Ai project folder. A second demo is
   `demo-apps\mda-2.3.0-27.apk`; use the WebdriverIO APK for the steps here.
3. Leave **Launch activity** blank for automatic launcher detection.
4. Expand **Advanced checks and exploration settings**.
5. Leave **Appium server URL** as `http://127.0.0.1:4723`.
6. Open `demo-apps\webdriverio-functional-checks.json` in VS Code or Notepad.
   Select all text with Ctrl+A and copy it with Ctrl+C.
7. Paste the complete JSON into **Approved test flows and business checks (JSON)**.
8. Tick **Run only the configured test flows and business checks**.
9. To reproduce the small live demonstration, use:

   | Field | Value |
   |---|---:|
   | Maximum screens | 1 |
   | Maximum safe navigation actions | 0 |
   | Maximum exploration depth | 1 |
   | Maximum test cases | 8 |

   Zero safe-navigation actions disables extra crawler navigation, not the
   actions inside the explicitly approved functional flows.
10. Tick the app permission checkbox above **Start Android test**.
11. Click **Start Android test**.
12. Watch the emulator. Blow AI installs and launches the APK, then checks typed
    input echo, switching on and off, and empty-login validation.
13. Wait for the final report and review all results. The saved example contains
    three functional tests; their result depends on the actual execution.

### Where to get another APK

For this demo, open the official
[WebdriverIO release](https://github.com/webdriverio/native-demo-app/releases/tag/v2.2.0),
expand **Assets**, and download `android.wdio.native.app.v2.2.0.apk`.
If GitHub's asset widget does not load, its
[direct asset list](https://github.com/webdriverio/native-demo-app/releases/expanded_assets/v2.2.0)
shows the same release downloads. Choose the Android `.apk`, rather than the
iOS archive or source-code ZIP. You can save it in Downloads or `demo-apps`;
the file picker accepts either location.

For your own application, obtain its APK from your development team or build
pipeline. The demonstration's locators and expected results are specific to
WebdriverIO and must be replaced for a different app.

## 3. Method two: test an already-installed app

1. Finish method one on the emulator. Keep that app installed.
2. Start a new Android test in the studio.
3. Select **App source → Already installed on the device**.
4. Select the same emulator.
5. In **Installed app package name**, enter:

   ```text
   com.wdiodemoapp
   ```

   This is the app's Android identifier, not its display name or APK filename.
   For another application, get its package name from the developer, Android
   manifest or Android package tools.
6. Leave **Launch activity** blank. If a different app requires an explicit
   activity, use the launcher activity supplied by its developer.
7. Choose **No AI (rules)**.
8. Paste `demo-apps\webdriverio-functional-checks.json` into the approved-flows
   field, tick configured-flows-only and use the limits from method one.
9. Tick permission and click **Start Android test**.
10. Watch the emulator and review the final report. This runs the same three
    checks through the installed-package method, without uploading an APK.

If installing manually instead, drag the APK from File Explorer onto the
running emulator, wait for installation, and confirm the app opens. Installing
on one emulator does not install it on a different emulator.

## 4. Method three: test a website in Android Chrome

1. Open Chrome on the emulator once. Finish any first-use prompts and confirm
   the emulator can load a website.
2. Start a new Android test in Blow AI.
3. Select **App source → Website in Android Chrome**.
4. Select your emulator.
5. In **Website URL**, enter:

   ```text
   https://the-internet.herokuapp.com/dropdown
   ```

6. Choose **No AI (rules)**. No application APK, package name or launch activity
   is needed for this method.
7. Expand Advanced settings and paste the complete contents of
   `demo-apps\chrome-dropdown-checks.json` into the approved-flows field.
8. Tick configured-flows-only and use the same limits table above.
9. Tick permission and click **Start Android test**.
10. Watch Chrome inside the emulator. The two checks verify the page heading
    and selection/readback of Option 1, Option 2 and Option 1 again.
11. Review the actual results in the final report.

## 5. Read results and choose a wider scope

- **Passed** means that selected test met its expected result.
- **Failed** means an assertion did not match its expected result.
- **Execution error** means automation could not complete conclusively.
- **Blocked** or **unexplored** functionality remains outside passing evidence.
- Download Excel or open the Android report from the result links.

The three methods describe how the target starts. They do not guarantee that
every feature in that target was tested. To explore beyond the saved example,
uncheck configured-flows-only and start with depth 3, 20 screens, 30 safe
navigation actions and 100 test cases. Supply expectations, test data and
approved flows for your application's business behavior. Login-protected
functionality needs an approved login flow and appropriate test credentials.

After rules testing works, you can optionally choose an AI provider/model and
enter a valid API key in the app. Cloud assistance requires the corresponding
privacy consent. To verify AI availability explicitly, turn off rules fallback;
otherwise review any visible fallback warning in the result.
