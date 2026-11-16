# Qpilot MCP configuration and private prepared requests

Reviewed against the implementation on 2026-11-14. This guide describes the current Studio/MCP configuration flow.
Feature implementation and verification are recorded separately in [STATUS](../STATUS.md).

## Configure in Studio, run through your assistant

1. Start `ui.bat` from this checkout. In **Privacy & connections**, approve the MCP assistant. Local mode requires
   confirmation that the assistant processes tool data locally; cloud mode requires explicit data-sharing consent.
2. Install the optional MCP packages with `setup/install-mcp.bat`, copy the server configuration from Studio and
   reconnect your MCP client. The generated server name is **qpilot** and paths refer to this checkout.
3. Select Web or Android, then **AI assistant through MCP**. Enter your target and describe what to verify.
4. Review the shared test settings. For Web, choose **Configure website test** to open the same account, AI,
   exploration, expected-results, review and recording controls used in Standard testing. For Android, the same AI
   provider/model/key controls and advanced configuration move into the MCP panel. They move back when you switch
   to Standard testing; there is one set of field IDs and values.
5. Choose **Prepare assistant request**. Qpilot validates and stores this exact configuration in process-local
   memory. This step does not start Appium, an emulator, a browser or a test.
6. Review the prepared text, then paste it into the connected assistant. It calls `start_prepared_test` with the
   request ID and your explicit permission. Follow progress and results in Studio.

Preparing is separate from executing. Connecting an assistant or refreshing environment status also starts no test.

Keep Studio open with **AI assistant through MCP** selected to follow execution. When you return from the assistant
tab, Studio also picks up the latest completed MCP run and shows its recorded actions, test results and full report
link. A short run can finish before you return; its recorded steps remain available. Web flows, including approved
contract-only flows, honor **Watch in Chrome** and the configured action delay. A completed run does not reopen its
browser window.

## Android controls

Choose a trusted local APK path, an installed package, or an Android Chrome URL. A placeholder such as
`/path/to/app.apk` is not an application and fails validation. The APK path is retained locally; the prepared
assistant text shows its filename. For installed applications, the package must exist on the selected device.

The MCP panel includes device selection, Appium URL, optional activity, test-build confirmation and ownership
permission. Its shared controls include provider, model, private API key, test-account credentials, whole-app versus
configured flows, full discovered-scenario mode, Thorough, depth/screen/action/scroll/time/case settings, expectations,
requirements, flow examples, the guided flow builder, and API/SQLite checks. Permission flows retain separate
emulator policy approval.

When the user selects a closed Android emulator and confirms permission, Qpilot starts installed local Appium and
prepares the selected emulator through the existing preparation service. It does not install missing prerequisites or
authorize a private phone. Submitting the Android request waits for preparation to finish before starting the run.
Direct legacy `start_android_test` callers still need a ready environment; use a prepared request for this automatic
preparation flow.

**Account for this test run** is shared by Standard and MCP Android setup. Choose public screens only, an existing
test account, or permission to create one account. Existing-account mode requires both private login fields and
never registers an account. Create mode requires test-build confirmation: registration is attempted once, the same
credentials are reused for login and protected checks, and the next run generates a different account. Login may
repeat to isolate checks; its valid credentials stay the same. Account modes preserve app data so a local account
is not deleted between checks. An interrupted or unconfirmed registration is reported and is never blindly retried.
Verification, CAPTCHA, unavailable registration and failed login remain coverage gaps. Credentials are not copied
into assistant requests, reports or browser storage. Use a prepared request to supply existing-account details.
Legacy HTTP clients that omit the account policy retain their previous behavior; new Studio requests always include it.

Zero soft discovery limits mean continue until eligible work is exhausted. Stop, run/phase time guards, scope checks,
and protected-action rules remain. Test-build confirmation is required for form submission and other permitted test
interactions. Discovery, passing visibility checks, and exhaustive business verification are different claims.

## Private inputs and lifecycle

- Passwords, API keys, usernames and authenticator secrets entered in Studio are excluded from the prepared text.
  Input fields are cleared after successful preparation. They are not placed in browser storage or copied to chat.
- A prepared request expires after 15 minutes and is lost when Studio restarts. It is not a saved run or a reusable
  credential store. Changing settings invalidates/revokes the current prepared request; prepare again after edits.
- MCP clients cannot create, inspect or modify private configurations. They receive only an opaque request ID and a
  redacted review of the nonprivate settings. The Studio-only preparation endpoint is blocked to MCP clients.
- Starting checks current privacy approval and explicit permission again. Changed privacy mode, revoked/expired
  references and invalid settings fail before a test starts. Target and settings cannot be overridden at launch.
- A repeated successful start returns the existing job instead of starting another test. An in-progress or uncertain
  failed start remains consumed; check run history before preparing a replacement. Private inputs are discarded
  from the configuration store when startup completes or fails.

Natural-language tasks and application content may themselves contain business data. Do not enter passwords into
task descriptions or inline flow JSON. Cloud-assisted mode does not prove where an external assistant processes data.

## Qpilot naming and compatibility

New configuration uses `qpilot`, `QPILOT_UI_URL`, `QPILOT_SECRET_*` and `QPILOT_DB_*`. Both current and legacy secret/
database references resolve and are redacted. New generated contracts and UI examples use Qpilot references.

Existing `BLOWAI_UI_URL`, `BLOWAI_SECRET_*`, `BLOWAI_DB_*`, Python bridge/global aliases, wire headers and the
`blowai://workflow` resource remain accepted for older clients and saved contracts. New clients use
`qpilot://workflow` and Qpilot headers. External tool installation directories, the shared device-lock location and
the prebuilt v1.2 APK's `com.blowai.demo` package remain compatible with installed tools and recorded targets.
The checkout folder and fixture source package use `Qpilot` and `com.qpilot.demo` respectively. Renaming the
checkout requires regenerating MCP paths and reconnecting the client. Existing APK binaries are not rewritten.

The app's public labels, generated Android report header, launchers, package metadata and current guides use Qpilot.
Historical run files, recorded videos, observed APK labels and measured evidence are not rewritten.

## Updating a running installation

Close/restart Studio after updating, then use **Copy server configuration** and reconnect the MCP client so it loads
the new `start_prepared_test` tool. Updating files alone does not reload an already-running stdio process.
Use the configuration generated by the running Studio rather than a hardcoded path from another checkout.
Refreshing the browser alone does not restart Studio. Android setup checks the backend revision before preparing
or starting a test and blocks outdated servers so the account choice cannot be silently ignored.

The classic crawl/start/read tools remain available. The server now registers 12 tools. A prepared request must use
`start_prepared_test`; substituting a classic start call drops its reviewed private configuration.
