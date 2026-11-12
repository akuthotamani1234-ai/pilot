# Reusable Android demos

These files are kept outside `runs` so clearing history does not remove them.

- `android.wdio.native.app.v2.2.0.apk`: official WebdriverIO demo app.
  Package: `com.wdiodemoapp`.
- `mda-2.3.0-27.apk`: Sauce Labs Android demo app (real ecommerce catalog/cart/login).
  Package: `com.saucelabs.mydemoapp.android`. Launchable activity is
  `.view.activities.SplashActivity` (MainActivity is not exported).
- `sauce-cart-checks.json`: approved native flow for adding the Sauce Labs
  Backpack and verifying its name and price in the cart. It does not submit an order.
- `sauce-ecommerce-thorough-checks.json`: catalog visibility + cart verification
  contract used for live ecommerce Android runs.
- `webdriverio-functional-checks.json`: the three approved native functional
  checks used in the successful live demonstration. These checks apply to
  WebdriverIO, not the Sauce Labs app.
- `chrome-dropdown-checks.json`: the two approved checks for
  `https://the-internet.herokuapp.com/dropdown` in Android Chrome.
- `webdriverio-expanded-checks.json`: ten native functional checks, including
  dropdowns, validation, dialogs, swiping, scrolling and drag-and-drop.
  See the [current reliability audit](../docs/28_APPIUM_RELIABILITY_AUDIT.md)
  for execution evidence and scope limits.
- `apk-source.json`: public download provenance for the WebdriverIO APK.
- `webdriverio-complete-checks.json`: 33 configured WebdriverIO v2.2.0 flows,
  including menus, demo account validation, persistence and optional permissions.
  Seven permission flows start unapproved. These additions await your live run.
- `controlled-sandbox-checks.json`: seven local fixture checks for login,
  protected access, session persistence, logout and safe order/removal previews.
- `blow-ai-controlled-demo-v1.2.apk`: compiled local fixture for those seven
  checks. `controlled-apk-build.json` records its checksum and build provenance.
  It has not been installed or live tested after the expansion.

Copy a checks file's contents into the studio's **Approved test flows and
business checks (JSON)** field. Tick configured-flows-only to reproduce that
bounded example.

Full workflow: [Run Android tests yourself](../docs/27_RUN_ANDROID_TESTS_YOURSELF.md).

Latest samples, private test credentials and permission setup:
[Expanded Android workflow](../docs/29_ANDROID_FEATURE_EXPANSION.md).
You can also load these examples from the Advanced settings sample picker.
