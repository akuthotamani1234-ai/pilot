# iOS testing - what a live run needs

Qpilot tests iOS apps (native and hybrid) through Appium's XCUITest driver (`backend/ios.py`). A Jira execution with
the application type "iOS app" checks every item below before it starts and names whatever is missing; nothing is
started on a machine that cannot run it.

| Need | How |
|---|---|
| macOS with Xcode | Install Xcode from the App Store, open it once, then `xcode-select --install` and `sudo xcodebuild -license accept`. |
| A simulator, or an authorized device | Simulator: open Xcode -> Settings -> Platforms, add an iOS runtime, then boot one (`xcrun simctl boot "iPhone 15"`). Device: connect it, trust the Mac, turn on Developer Mode (Settings -> Privacy & Security), note its UDID (`xcrun xctrace list devices`). |
| Appium 2 with the XCUITest driver | `npm install -g appium`, then `appium driver install xcuitest`, then start `appium` (default `http://127.0.0.1:4723`). Point the Execution Center's "Appium server" to it. |
| The app | A simulator build (`.app`, or a zipped `.app`) or a device build (`.ipa`) to install, or the bundle id of an app already installed. |
| Device signing (real devices only) | The WebDriverAgent must be signed: give the Apple team id (`xcodeOrgId`) and, if needed, a unique `updatedWDABundleId`. |
| Hybrid apps (WebView content) | The test build's `WKWebView` must be inspectable: on iOS 16.4+ set `webView.isInspectable = true` in debug / test builds. Without it Qpilot reports that the WebView cannot be inspected; it never pretends to drive it. |

What a run does: it opens an Appium XCUITest session, reads the real screen (the XCUI hierarchy: buttons, texts,
fields with their accessibility ids and labels), has the AI plan each approved test case only over controls that
screen shows (a plan naming a control the screen does not show is refused), runs the steps, switches to the app's
WebView for CSS steps and back to native for the others (recorded in `ios_contexts.json`), keeps a screenshot per case
and writes each case's outcome to the run's `test_cases.json` (Passed, Failed, Not automated with the reason).

Live status: built and tested against a fake Appium driver; no Mac / simulator / device was available while it was
built, so live iOS validation is BLOCKED until a Mac with the items above runs it.
