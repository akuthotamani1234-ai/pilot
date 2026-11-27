# Qpilot - local acceptance testing on a MacBook Pro

This guide lets **you** perform every live validation that could not be done in the build environment. The build
environment is a Linux container with no Android device, no Mac, no payment-sandbox application, no SSO/MFA
application and no access to your Jira. Each section below says what to install, what to do, what you should see,
what to do when it goes wrong and what evidence to keep. The last section is the acceptance checklist.

Nothing here asks you to share a secret with anyone: tokens, passwords and keys are typed only into Qpilot on your
own Mac (or into your own shell), never into a chat, a ticket or a screenshot.

---

## 0. Status of each capability before you start

These are the honest columns used throughout this document:

| Column | Meaning |
|---|---|
| **Implemented** | the code exists on branch `final` |
| **Unit tested** | automated tests of its parts pass (fakes / stubs) |
| **Integration tested** | automated tests through the real HTTP routes / real browser / real generated-test runtime pass (engines or devices may be stubbed) |
| **Live tested** | run against a real application on the internet or a real device, with the result checked by a person |
| **Blocked** | live validation needs something the build environment does not have - **you** run it with this guide |
| **Failed** | a live or automated check failed and is not fixed |
| **Not tested** | no automated or live test exists |

A capability is **not** fully validated because its unit tests pass. Only your live run (section 15) closes a Blocked
item.

### Strategies x application types (what was actually executed, 26 Nov 2026)

"Routed" means the execution reached the right engine with the right cases and AI - it is NOT end-to-end execution.
"Executed (fake)" means real engine code ran every step against a simulated app/driver. Only "Live" ran against a
real application.

| Application | Requirement-based | Hybrid | Autonomous |
|---|---|---|---|
| Website | **Live**: SauceDemo via the Jira route (mock Jira + OpenAI): TC-QPL-4-1 and TC-QPL-5-1 Passed | **Live**: SauceDemo via the Jira route: 52 exploratory cases ran (32 passed, 18 failed - the failures include real SauceDemo 404s and AI test mistakes); the 2 Jira cases ended Not automated (AI used a refused `text=` locator) and Requires review (test mistake confirmed on screen) | **Live** as standard Qpilot runs (SauceDemo, OrangeHRM); not re-run through the Jira route today |
| REST API | **Live**: Petstore, 4 cases (3 passed, 1 failed on a real schema violation) | **Live**: Petstore, cases + spec-derived tests | **Live**: Petstore via the Jira route: 10 spec-derived tests (7 passed, 3 failed on real API problems) |
| Native Android | Routed + executed (fake driver); only the selected cases run. Live **BLOCKED** (no device) | Routed + executed (fake driver). Live **BLOCKED** | Routed + executed (fake driver / fixture app). Live **BLOCKED** |
| Hybrid Android | Routed; WebView context switching executed (fake driver). Live **BLOCKED** (no device, no hybrid test build) | same | same |
| Native iOS | Routed + executed (stateful fake XCUITest app: discovery, plans over every screen, a real defect fails). Live **BLOCKED** (no Mac) | Routed + executed (fake): Jira cases + discovery scenarios | Routed + executed (fake): discovery, scenarios, AI scenarios validated. Live **BLOCKED** |
| Hybrid iOS | WebView inspected in its own context and switched back (fake). Live **BLOCKED** | same | same |

### Capabilities

| Capability | Implemented | Unit | Integration | Live | Live status / what blocks it |
|---|---|---|---|---|---|
| Jira import, analysis, test-case generation, review | yes | yes | yes (mock Jira API) | **no** | Blocked: your real Jira token was not available |
| Jira execution routes + chosen AI reaches the engine | yes | yes | yes (12 type x strategy combinations) | partly | Live with a mock Jira + real OpenAI (web, API); real Jira Blocked |
| Automatic prerequisites (Jira links, preconditions) | yes | yes | yes | yes | Live: QPL-4 added for QPL-5 on SauceDemo, both Passed |
| Accurate outcome per selected case (defect / automation error / inconclusive / blocked prerequisite / not automated / not run kept apart) | yes | yes | yes (through the real collect path) | yes | Live runs show Passed, Requires review, Not automated and Blocked with reasons |
| A pass needs the quoted expected result checked at runtime | yes | yes | yes (real Chromium + generated-test runtime) | yes | Live on SauceDemo |
| Selector recovery (exact, same kind of identifier only) | yes | yes | yes | yes | Live on SauceDemo (TC-QPL-4-1) |
| Self-healing cannot change what a test checks | yes | yes | yes | yes | Live: healing rounds on SauceDemo kept the stated values |
| REST API testing (cases + autonomous schema / rule / negative / boundary / auth / validation) | yes | yes | yes | yes | Live on the public Petstore API; your API not yet |
| Native Android (APK / installed package) | yes | yes | yes (fake Appium driver / fixture app) | **no** | Blocked: no device or emulator |
| Hybrid Android (native + WebView) | yes | yes | yes (fake driver) | **no** | Blocked: no device and no hybrid test build |
| iOS native + hybrid (XCUITest) | yes | yes | yes (stateful fake app) | **no** | Blocked: no Mac / Xcode / simulator |
| Checkout up to the order button (any shop) | yes | yes | yes | yes | Live on SauceDemo |
| Demo-shop order completion (owner confirmed) | yes | yes | yes | yes | Live on SauceDemo (demo shop) |
| Payment in a provider sandbox (test cards only) | yes | yes | yes | **no** | Blocked: no application connected to a payment sandbox |
| A paying case without a sandbox is Blocked and counted (never dropped) | yes | yes | yes | n/a | - |
| Order confirmation | yes | yes | yes | yes | Live on SauceDemo ("Thank you for your order!") |
| Order history / order status | yes | yes | partly | **no** | Blocked: needs a test shop with accounts, order history and status changes |
| Bot protection detection, pause, help, resume | yes | yes | yes (real browser, local bot-check page) | **no** | Blocked: no real protected application |
| SSO / MFA pause and resume | yes | yes | yes | **no** | Blocked: no SSO / MFA test application |
| Multi-agent activity + live view (browser frames; device screen for Android / iOS) | yes | yes | yes | web yes | Live web runs: 13 agents, explorers / learners / test workers with live frames; device frames Blocked with the devices |
| New Test, history, scrolling, Next / Back; views show only their newest answer | yes | yes | yes (real Chromium UI tests, including out-of-order answers) | partly | Exercised in the build environment's browser; not on your Mac |
| Feature inventory, accountability, traceability | yes | yes | yes | yes | Built from the real SauceDemo runs |
| Batching, cancel, checkpoint, resume | yes | yes | yes | **no** | Blocked: no project with hundreds of real cases |
| Redaction (reports, logs, traces, generated code, AI prompts, API evidence) | yes | yes | yes | yes | Real SauceDemo run scanned incl. trace zips: the test password appears only in SauceDemo's own login page, which prints it |
| Credential security, authorization, tenants | yes | yes | yes | partly | Automated checks only; please re-check with your accounts |

Screenshots are pictures: Qpilot does not take a device screenshot while a typed value is on screen (Android, iOS)
and password fields are masked by the browser, but anything else a page shows is in its screenshot - review
screenshots before sharing them.
---

## 0b. What you need before you start (accounts, devices, permissions, configuration)

| Validation | Accounts / access | Device / machine | Permissions | Configuration in Qpilot |
|---|---|---|---|---|
| Real Jira integration | an Atlassian account that can **browse** the test project (QPL); an API token of that account | your Mac | read access to the project and its linked Confluence pages; **no** write permission needed (Jira write-back stays off) | Integrations: site address, e-mail, API token (section 3) |
| Website (all strategies) | a test account of the website (never a real customer's) | your Mac (Chrome via Playwright) | written permission to test the site; a test / staging environment for anything that sends forms | Execution Center: address, environment, test username / password |
| Native Android | the app's test account (if it has a login) | Android Studio emulator (or a phone with Developer options -> USB debugging on) | a **test build** of the app (debug or internal track); the right to install it | Application = Android app, device id, package, Appium server |
| Hybrid Android | as native Android | as native Android | the test build calls `WebView.setWebContentsDebuggingEnabled(true)` | as native; Appium with `--allow-insecure chromedriver_autodownload`; `QPILOT_CHROMEDRIVER_AUTODOWNLOAD=1` in `.env` |
| Native iOS | the app's test account (if it has a login) | Mac with Xcode + an iOS simulator; a real iPhone additionally needs an Apple developer team (signing) and Developer Mode on | a **simulator build** (.app) or a signed test build (.ipa) | Application = iOS app, bundle id (+ app file / UDID / Appium server) |
| Hybrid iOS | as native iOS | as native iOS | the test build sets `webView.isInspectable = true` (iOS 16.4+) | as native iOS |
| Payment sandbox | a provider **sandbox** account (Stripe test mode, Braintree sandbox, Adyen test, Razorpay test mode or PayPal sandbox buyer) | your Mac | the shop's **staging** environment must be connected to that sandbox (its test keys are configured in the shop, never in Qpilot) | Execution Center: Payment sandbox = provider, tick the sandbox confirmation, strategy Requirement-based |
| Order history | a shop test account that can place (sandbox) orders and has a "My orders" page | your Mac | staging | Jira cases "the order appears in My orders", prerequisite = the order case |
| Order status | as order history, plus someone (or a back-office job) who moves the order to the next status in the test environment within 10 minutes | your Mac | access to the shop's back office in staging (for the person, not for Qpilot) | Jira case "the order status becomes 'Shipped'"; Qpilot waits up to 10 minutes, reloading |
| Bot protection | the application owner's agreement | your Mac | a test environment with the protection switched on; or an allow-list entry for your IP | none; when paused, the help form takes your own browser session (section 11) |
| SSO | a test user of the identity provider (Okta / Entra ID / Google Workspace) assigned to the application | your Mac | the application's SSO enabled in staging | the identity provider's host in `ALLOWED_HOSTS` in `.env` (comma separated), or sign in yourself when the run pauses |
| MFA | the test user's authenticator **secret** (the text behind its QR code) - for TOTP only | your Mac | MFA enrolled for the test user | `TEST_TOTP_SECRET` in `.env`; SMS / e-mail / push MFA always pauses for you |
| Large projects | a Jira project with more than 20 approved cases | your Mac | read access | `QPILOT_BATCH_SIZE` in `.env` if you want batches other than 20 |

Secrets (tokens, passwords, TOTP secrets) go only into Qpilot's own fields or your local `.env`. Never paste them
into a ticket, a chat or a screenshot you share.

## 1. Install the tools (once)

Open **Terminal** (Applications -> Utilities -> Terminal). Each block is one command.

### 1.1 Homebrew, Git and Python 3.13

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

```bash
brew install git python@3.13
```

```bash
python3.13 --version
```

Expected: `Python 3.13.x`. (Do not use Python 3.15: some packages Qpilot needs do not install on it yet.)

### 1.2 Node.js and Appium (Android and iOS only)

```bash
brew install node
```

```bash
npm install -g appium
```

```bash
appium driver install uiautomator2
```

```bash
appium driver install xcuitest
```

```bash
appium driver list --installed
```

Expected: `uiautomator2` and `xcuitest` listed as installed.

### 1.3 Android Studio (Android only)

1. Download Android Studio from https://developer.android.com/studio and drag it to Applications.
2. Open it once and finish the setup wizard (Standard install). It installs the Android SDK, platform tools and an
   emulator image.
3. Add the SDK to your shell (Apple Silicon and Intel Macs use the same path):

```bash
echo 'export ANDROID_HOME="$HOME/Library/Android/sdk"' >> ~/.zprofile
```

```bash
echo 'export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"' >> ~/.zprofile
```

```bash
source ~/.zprofile && adb version
```

4. Java for Appium's Android driver:

```bash
brew install --cask temurin@17
```

```bash
echo 'export JAVA_HOME="$(/usr/libexec/java_home -v 17)"' >> ~/.zprofile && source ~/.zprofile
```

### 1.4 Xcode (iOS only)

1. Install **Xcode** from the App Store, open it once, accept the licence.
2. Then:

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

```bash
sudo xcodebuild -license accept
```

```bash
xcodebuild -version
```

3. Xcode -> Settings -> Platforms: add an **iOS** simulator runtime (e.g. iOS 17 or 18).

More detail: [docs/IOS_SETUP.md](docs/IOS_SETUP.md).

---

## 2. Get Qpilot and start it

### 2.1 Clone the branch that was built

```bash
git clone https://github.com/akuthotamani1234-ai/pilot.git ~/qpilot
```

```bash
cd ~/qpilot && git checkout final && git pull
```

```bash
git log --oneline -1
```

Write the commit hash down: it goes in your evidence (section 14). The Studio shows the same build stamp at the
top of the Jira page and at `http://127.0.0.1:8000/api/version`.

### 2.2 Python environment

```bash
cd ~/qpilot && python3.13 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r requirements.txt
```

```bash
.venv/bin/python -m playwright install chromium
```

### 2.3 Settings file

```bash
cp .env.example .env
```

Open `.env` in a text editor (`open -e .env`) and set **only** what you need:

| Setting | Value | Why |
|---|---|---|
| `LLM_PROVIDER` | `openai` or `anthropic` (or `gemini`) | the AI that writes the tests |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | your key | typed here on your Mac only; never shared |
| `HEADLESS` | `false` | you watch the browser during acceptance |

You can also choose the AI per execution in the Execution Center ("AI provider", "AI model", "AI key for this run");
a key typed there is used for that run only and is not stored.

### 2.4 Start the Studio

```bash
cd ~/qpilot && .venv/bin/python -m backend.server
```

Keep that Terminal window open. Open http://127.0.0.1:8000 in Safari or Chrome. The Jira workspace is at
http://127.0.0.1:8000/requirements.

Check the build:

```bash
curl -s http://127.0.0.1:8000/api/version
```

Expected: JSON with the same commit hash as `git log --oneline -1`. If it differs, an old Studio is still running:
close every Terminal running `backend.server` and start it again.

### 2.5 Optional: the automated suite on your Mac (about 40 minutes)

```bash
mv .env .env.off; .venv/bin/python -m pip install -r requirements-dev.txt; .venv/bin/python -m pytest -q -n 4 tests; mv .env.off .env
```

Expected: everything passes except tests that need a device / Mac / network you have not set up (they are skipped).
Keep the last 20 lines as evidence.

---

## 3. Jira configuration

1. Create an API token for your Atlassian account: https://id.atlassian.com/manage-profile/security/api-tokens ->
   **Create API token** -> name it `qpilot-acceptance` -> copy it. Give the account **read** access to the test
   project only.
2. In the Studio: **Jira -> Integrations** -> Jira card: **Site address** (`https://<you>.atlassian.net`), the e-mail
   of the token's account, and paste the token into **API token** (stored encrypted on your Mac, never shown again).
   Press **Connect**, then **Test connection**. It never appears in reports or logs.
3. **Import Requirements**: 1. Which Jira site -> 2. Project (e.g. `QPL`) -> 3. Work-item types and filters ->
   4. Preview -> 5. Importing -> 6. Analyze.
4. **Review Center**: accept the ideas you want; **Test Cases**: generate, open each, approve.

Expected: the imported stories show their acceptance criteria; Jira "blocks / is blocked by" links appear as
prerequisites (Test Cases -> a case -> Prerequisites). Qpilot never writes to Jira unless you approve a proposed
write under **Defects -> Proposed Jira writes**.

Troubleshooting:

| You see | Do |
|---|---|
| 401 / "could not sign in" | token copied incompletely, or e-mail is not the token's account |
| 403 / project missing | the account cannot browse that project |
| Nothing imported | the filters exclude everything: clear Status / Sprint / JQL and preview again |

Evidence: screenshot of Integrations (token field empty/masked), the import summary, the list of approved cases.

---

## 4. Website testing (all three strategies)

Use a website you own or may test (a staging site), or https://www.saucedemo.com (public test credentials
`standard_user` / `secret_sauce`).

**Execution Center** -> "What will be tested" (select cases) -> "Application under test": Application = Website,
Website address, Environment = test/staging, Test username / Test password -> "AI for automation" -> tick the
authorization confirmation -> **Start**.

| Strategy | What you select | What should happen |
|---|---|---|
| Requirement-based | 2-5 approved cases | only those cases (plus prerequisites added automatically, shown as "added: needed by ...") run; each ends Passed / Failed / Blocked / Requires review / Not automated with a reason |
| Hybrid | the same cases | the cases run **and** the site is explored; extra findings appear in the run report |
| Autonomous | no cases needed | the site is explored and tested without Jira cases |

**Live Execution** shows the browser frames, the agents (discovery, learners, script generation, execution, self-
healing, reporting) and each step ticking. Scroll the history; use **New Test**, **Next** and **Back** in the guided
workflow and confirm your selections are kept.

Expected results to check by hand:
1. A Passed case's report shows the checks that ran, including the result the Jira case quotes (e.g.
   "Thank you for your order!"). A case whose quoted result was never checked shows **inconclusive / Requires
   review**, never Passed.
2. A Failed case has a screenshot and the exact expected vs actual text.
3. No real order is placed and no payment page is submitted unless you configured section 8.

Troubleshooting: "A test is already running" -> wait or stop it in Live Execution; "Not automated: Not possible" ->
open the case: the reason says what the site lacks; "AI provider is required" -> choose one in "AI for automation".

Evidence: the execution id, the Reports page, `runs/<run>/report.html`, `runs/<run>/test_cases.json`.

---

## 5. Android emulator setup (Android Studio)

1. Android Studio -> **More Actions -> Virtual Device Manager -> Create device** -> Pixel 7 -> a system image with
   **Google APIs** (API 34) -> Finish -> press Play.
2. Check it is seen:

```bash
adb devices -l
```

Expected: `emulator-5554  device ...`. That id is the "Device id" in the Execution Center.

3. Start Appium in a second Terminal window (keep it open):

```bash
appium --address 127.0.0.1 --port 4723 --allow-insecure chromedriver_autodownload
```

(`chromedriver_autodownload` lets Appium fetch the ChromeDriver that matches the app's WebView - needed for hybrid
apps and for websites in Android Chrome. Also set `QPILOT_CHROMEDRIVER_AUTODOWNLOAD=1` in `.env` and restart the
Studio.)

Troubleshooting: `adb: command not found` -> section 1.3 step 3, then open a new Terminal; emulator `offline` ->
cold-boot it from the Device Manager; Appium "Could not find a driver" -> `appium driver install uiautomator2`.

## 6. Native APK testing

1. Use a **test build** of your app (`.apk`), or install it first: `adb install -r /path/to/app.apk`.
2. Find its package name:

```bash
adb shell pm list packages | grep -i <part-of-your-app-name>
```

3. Execution Center -> Application = **Android app** -> On Android = installed app -> Device id `emulator-5554`,
   App package `com.your.app`, Start activity (optional), Appium server `http://127.0.0.1:4723` -> select cases ->
   Start.

Run it three times, once per strategy:

| Strategy | Expected |
|---|---|
| Requirement-based | the app is explored (to find the screens), then ONLY the selected cases run; the report lists the engine's own checks as "not tested - requirement-based run" |
| Hybrid | the selected cases first, then the engine's own checks (forms, safe taps, rotation / background / Back) and AI journeys |
| Autonomous | no cases: the engine's own checks and AI journeys |

Expected: Live Execution shows the device screen (each evidence screenshot, taken only when no typed value is on
screen); each Jira case maps to its own result (`[TC-...]` tagged); screenshots per step in `runs/<run>/`. A step
the app does not support ends Not automated with the reason.

Troubleshooting: "device" / "package" problem before start -> the pre-run check names the missing field;
`INSTALL_FAILED_*` -> uninstall the old build (`adb uninstall com.your.app`).

Evidence: `adb devices -l` output, run folder, report, a screen recording (`adb shell screenrecord /sdcard/qa.mp4`,
then `adb pull /sdcard/qa.mp4`).

## 7. Hybrid APK testing (native + WebView)

Requirements for the **test build**:
- The app calls `WebView.setWebContentsDebuggingEnabled(true)` (or is a debuggable build). Without it Qpilot says
  exactly that ("The app shows a WebView, but it is not debuggable ...") and never pretends to test the web part.
- Appium started with `--allow-insecure chromedriver_autodownload` (section 5).

Steps: as section 6, with a case that crosses native and web screens (e.g. "Open Help, the FAQ page lists
'Shipping'").

Expected: `runs/<run>/` records the switches between `NATIVE_APP` and `WEBVIEW_<package>`; web steps use CSS
selectors, native steps use accessibility ids; both kinds of checks appear in the report.

Troubleshooting: "No Chromedriver found that can automate Chrome 'X'" -> Appium was not started with the
autodownload flag; several WebViews -> the result names them; close the extra screen and re-run.

## 8. Payment sandbox configuration

Only an application **connected to a payment provider's sandbox / test mode** may be used. Qpilot types only the
provider's published test cards; it refuses any other card number (Luhn-valid numbers that are not published test
cards are blocked by the test runtime).

| Provider | Test card (success) | Details |
|---|---|---|
| Stripe (test mode) | 4242 4242 4242 4242 | any future expiry (12/34), any CVC, any postal code; 4000 0000 0000 0002 = declined |
| Braintree (sandbox) | 4111 1111 1111 1111 | any future expiry, any CVV |
| Adyen (test) | 4111 1111 1111 1111 | expiry 03/2030, CVC 737 |
| Razorpay (test mode) | 4111 1111 1111 1111 | test OTP page offers success / failure |
| PayPal (sandbox) | - | a sandbox buyer account (typed as the run's test account) |
| Cash on delivery / invoice | - | nothing typed |

Steps: Execution Center -> Application = Website (your staging shop) -> **Payment sandbox** = the provider -> tick
the confirmation that the shop uses the provider's sandbox -> strategy **Requirement-based** (the sandbox is refused
for hybrid / autonomous) -> select the checkout / payment / order cases -> Start.

Expected: the order is paid with the test card on the provider's sandbox page; the confirmation page and the order
number are checked; a "declined" case shows the decline message. Then check in the provider's dashboard (test
mode) that the payment appears as a **test** payment.

Order history and order status: add cases such as "The order appears in My Orders" and "The order status becomes
'Shipped'" (link them in Jira as blocked by the order case, or set the prerequisite in Test Cases). Status waits are
bounded (up to 10 minutes, page reloaded between reads); a status that never arrives is reported inconclusive, not
Passed.

Never use a real card, a live-mode key or a production shop.

## 9. Xcode and iOS simulator setup

```bash
xcrun simctl list devices available | grep -i iphone
```

```bash
xcrun simctl boot "iPhone 15"
```

```bash
open -a Simulator
```

Install your app's **simulator build** (`.app`):

```bash
xcrun simctl install booted /path/to/YourApp.app
```

Start Appium (if not already running): `appium --address 127.0.0.1 --port 4723`.

Execution Center -> Application = **iOS app** -> Bundle id (`com.your.app`), App file (optional), Simulator / device
UDID (optional), iOS version (optional), Appium server `http://127.0.0.1:4723` -> choose a strategy -> Start.

Every iOS run first **discovers** the app: from a fresh launch it taps each safe control of each screen it finds (at
most 12 screens / 40 taps; it never taps anything that pays, orders, deletes, sends, shares, logs out or grants a
permission), records each screen's controls and screenshot, and inspects each WebView in its own context.

| Strategy | Expected |
|---|---|
| Requirement-based | the selected cases, planned by the AI over every discovered screen (each case starts from launch and walks to its screen) |
| Autonomous | scenarios from discovery (each navigation proven by a control only the new screen shows; each WebView's content plus the native screen after switching back) and up to 8 AI-designed scenarios, refused if they name a control the app does not show or would tap something risky |
| Hybrid | both |

Expected: the pre-run check passes (it names any missing piece: macOS/Xcode, Appium, the app); Live Execution shows
the simulator screen; `runs/ios_<bundle>_*/` holds `ios_screens.json` (screens, transitions, what was not tapped and
why), `screens/S*.png`, `test_cases.json` (Jira cases by id; autonomous scenarios as `IOS-AUTO-*` / `IOS-AI-*`),
screenshots per case and `ios_contexts.json` (every NATIVE_APP <-> WEBVIEW switch). A hybrid app's `WKWebView` must
set `isInspectable = true` on iOS 16.4+; otherwise its web scenarios end Not automated with exactly that reason.

To prove a real defect is reported: in a test build, break one behaviour a case checks (e.g. the cart badge) and
run again - that case must be **Failed**, not Passed or Not automated.

Real device: also give the Apple team id (WebDriverAgent signing) - see docs/IOS_SETUP.md.

## 10. REST API testing

Execution Center -> Application = **API** -> OpenAPI / Swagger document (e.g. your staging API's `openapi.json`) ->
Bearer token for this run (if needed; used for this run only, never stored or reported) -> "Requests that change
data": tick POST / PUT / PATCH / DELETE only for a test API (none = read-only; DELETE only for requirement-based runs) -> strategy -> Start.

| Strategy | Expected |
|---|---|
| Requirement-based | each case becomes API requests with status / schema / value checks; a request the run may not send is Blocked (and checks after it in the same case are Blocked, not Failed) |
| Hybrid | the cases plus the autonomous tests below |
| Autonomous | tests derived from the specification only, each kind only where the document says what must happen: **schema** (each GET without unknown input: documented status + response schema), **business rule** (a list filtered by an enum parameter that is a field of its items returns only such items), **negative** (invalid enum value, malformed path id -> a documented 4xx), **boundary** (just outside a declared minimum / maximum), **auth** (no credential on a secured operation -> documented 401 / 403, when the run has a token), **validation** (a write without its required body fields -> a documented 4xx, only for methods you ticked) |

An invalid input the API accepts (2xx) is reported as **Validation defect (invalid input accepted)**; any 5xx is a
failure.

Public practice target: `https://petstore3.swagger.io/api/v3/openapi.json` (shared sandbox: its data changes; the
26 Nov live run found a real schema violation and a real HTTP 500 on `GET /store/inventory`).

Evidence: `runs/api_<host>_*/api_results.json` (every request and answer, secrets redacted) and the report.

## 11. Protected application testing (bot protection, CAPTCHA, rate limits)

Use a test environment of **your** application that has its protection switched on. Qpilot never solves, hides from
or tricks a CAPTCHA or bot check.

Steps: run a website execution against it. Expected: Live Execution shows a **paused** banner naming the blocker
(e.g. "a bot-protection check (Cloudflare) stands in front of the application") and what helps. Then either:
- ask the owner to allow-list the tester / disable the check in the test environment and press Resume, or
- pass the check in your own browser, export that session (Chrome DevTools -> Application -> Cookies, copy as a
  `name=value; name2=value2` Cookie header, or a Playwright storage-state JSON) and paste it in the banner's help
  form. Only cookies of the application's own domain are accepted; they stay in the run's private folder and are
  deleted after use.

Expected after help: the run checks access really works and continues from where it stopped. With no help within
the wait, that part ends **Blocked** with the exact blocker - never Failed.

## 12. SSO / MFA testing

| Login type | What to configure | Expected |
|---|---|---|
| MFA with an authenticator app (TOTP) | put the **test account's** authenticator secret in `.env` as `TEST_TOTP_SECRET` | the code is generated during login; the run proceeds |
| MFA by SMS / e-mail / push | nothing | the run pauses ("the login asks for a one-time code"); sign in yourself and give the session (section 11) |
| SSO redirect (Okta, Entra ID, Google) | add the identity provider's host to `ALLOWED_HOSTS` in `.env` (comma separated) and restart the Studio, or sign in yourself when it pauses | with the host allowed and a TOTP secret: the run signs in; otherwise pause, help, resume as in section 11 |

Evidence: the pause banner screenshot, `runs/<run>/pause.json`, the resumed run's report.

## 13. Large projects (batching, cancel, checkpoint, resume)

Select more than 20 approved cases (`QPILOT_BATCH_SIZE`, default 20). Expected: Live Execution shows "batch 1 of N";
each batch's results appear as it ends; a prerequisite chain is never split. Then:
1. **Cancel** during batch 2 -> remaining batches show cancelled.
2. Start again, stop the Studio (Ctrl+C in its Terminal) during a batch, start it again -> the execution shows
   **interrupted** with **Resume**; Resume asks for the test password again (it is never stored) and continues with
   the first unfinished batch.

## 14. Evidence collection

Create one folder per acceptance session:

```bash
mkdir -p ~/qpilot-acceptance/$(date +%Y%m%d) && cd ~/qpilot
```

For each scenario keep:
1. the commit hash (`git log --oneline -1`) and `curl -s http://127.0.0.1:8000/api/version`,
2. the execution id and its Reports page (Print -> Save as PDF),
3. the run folder: `cp -R runs/<run> ~/qpilot-acceptance/$(date +%Y%m%d)/`,
4. screenshots / screen recordings (macOS: Shift-Cmd-5),
5. for devices: `adb devices -l` or `xcrun simctl list devices booted`.

Before sharing evidence with anyone, check it contains no password, token or real customer data (reports redact the
test password and API tokens; your own screenshots are not redacted).

## 15. Troubleshooting (general)

| Problem | Fix |
|---|---|
| Page at 127.0.0.1:8000 does not open | the Studio Terminal shows the error; port busy -> set `UI_PORT=8010` in `.env` |
| Build stamp differs from `git log` | an old Studio is running: stop all `backend.server` processes and start again |
| Playwright browser missing | `.venv/bin/python -m playwright install chromium` |
| AI errors / timeouts | check the key and model in "AI for automation"; the run reports the AI failure instead of guessing |
| Case "Requires review" | the test (not the app) failed: open it to see the code error; re-run once; report it if it repeats |
| Case "Blocked" | its prerequisite failed, or access / payment / device was not available - the reason says which |
| Android "No device" | `adb devices -l` must show `device`; restart the emulator |
| iOS "needs macOS with Xcode" / "No Appium server answers" | sections 1.4 and 9; Appium must be running |

## 16. Final acceptance checklist

Tick each line only when you saw it yourself. Record PASS / FAIL / BLOCKED with the evidence location.

| # | Scenario | Expected | Result | Evidence |
|---|---|---|---|---|
| 1 | Build stamp matches `git log` | same hash | | |
| 2 | Jira connection with your token | connection test OK; token never shown again | | |
| 3 | Import + analyse QPL stories | acceptance criteria shown; links become prerequisites | | |
| 4 | Generate + approve test cases | cases with steps and quoted expected results | | |
| 5 | Website, requirement-based (QPL-2..6, 12, 13) | each case has a real outcome with evidence; no false Pass | | |
| 6 | Website, hybrid | cases + exploration findings | | |
| 7 | Website, autonomous | exploration report | | |
| 8 | Prerequisite failure | dependent case Blocked (not Failed) | | |
| 9 | Live Execution | agents + live browser frames + steps | | |
| 10 | New Test / history / scroll / Next / Back | selections kept, history lists every execution | | |
| 11 | Native APK on emulator, all three strategies | requirement-based runs only the cases; hybrid / autonomous add the engine's checks | | |
| 12 | Hybrid APK | NATIVE_APP <-> WEBVIEW switches recorded, both checked | | |
| 13 | iOS simulator app, all three strategies | discovery screens + per-case outcomes; autonomous scenarios run; a broken test build fails its case | | |
| 14 | REST API (your API), all three strategies | per-case checks; autonomous schema / rule / negative / boundary tests; secrets redacted | | |
| 15 | Payment sandbox (test card) | paid on sandbox, confirmation checked; real card refused | | |
| 16 | Order history + status | order listed; status awaited or inconclusive | | |
| 17 | Bot protection | paused with blocker; resumed after help, or Blocked | | |
| 18 | SSO / MFA | TOTP login works; SMS/SSO pauses and resumes | | |
| 19 | > 20 cases | batches, cancel, interrupted -> resume | | |
| 20 | Inventory / accountability / traceability | every requirement has its four coverage figures | | |
| 21 | Security spot check | no token / password in reports, logs, run folders (`grep -R "<part of your token>" runs/` finds nothing) | | |
| 22 | Second workspace user (if enabled) | cannot see the other tenant's executions | | |

Acceptance is complete only when every line is PASS, or is BLOCKED with a reason you accept.
