# Android demo error fixes and picture guide

Reviewed the supplied runs `android_20261107_232240_9ea56b`,
`android_20261107_233157_3ab029` and `android_20261107_233420_c1e9d5`.
The installed-app run failed before test execution. Zero failed test cases in
that report did not mean a successful launch.

## Changes

- Native Appium sessions accept a splash-to-main activity handoff, with a
  60-second wait and the installed package kept as the wait target. Foreground
  package checks continue to prevent inspecting unrelated apps.
- Android AI readiness uses one request with a 20-second timeout budget.
  Design and script generation use 90-second call/stage budgets. These are
  per-call settings, not temporary mutations of shared global configuration.
  A failed readiness check prevents more calls to the failing provider in that
  run when rules fallback was approved. Disabling fallback stops the run.
- AI fallback is recorded in state, summary JSON, the quality gates, the HTML
  report and the studio. A passing application check does not verify AI access.
- Discovery counts new navigation separately from bounded recovery actions.
  Action, screen, depth, stop and time limits have distinct explanations.
  Repeated Home controls can reuse observed destination evidence; labels alone
  are not accepted as proof of a destination, and explicit expectations remain
  eligible for execution.
- If Back exits the native app, recovery activates only the selected package.
  It waits for the app to render before deciding whether its parent screen was
  restored. Unrelated foreground content is not inspected. Genuine restoration
  failures remain visible rather than being counted as successful discovery.
- Chrome screen labels include the URL path, distinguishing pages that share
  one site-wide title. Query values are omitted from the display label.
- The Android card mentions APKs, installed apps and Chrome websites. A
  three-row explanation appears beside App source.
- A persistent **Android guide** link stays in the studio header during Android
  setup, execution and results. It opens a separate tab without interrupting
  the run. The setup guide and PNGs are served locally under `/static/`.

## Verification

- Combined Android, API, privacy and browser regression suite: **141 passed**.
- Final recovery, guide visibility and results-layout suite after the final
  changes: **55 passed**.
- JavaScript syntax and Ruff passed.
- Two real installed Sauce Labs Appium sessions reached MainActivity: automatic
  launcher detection and an explicit SplashActivity configuration.
- A real bounded installed-app pipeline completed: **8 passed, 1 blocked,
  0 failed, 0 errors**, verdict **Ready with Risks**. Report:
  `runs/android_installed_launch_fix_20261108_095147/report.html`.
- That pipeline exposed a further parent-restoration problem. After fixing it,
  a fresh real discovery check inspected Products and Navigation menu, performed
  one exploration action and two recovery actions, and recorded **no discovery
  issues**. Evidence: `runs/android_error_fix_checks/recovery-settled/verification.json`.
- The actual running studio's guide button opened all three visual instructions
  in a new tab. Automated checks also kept the link visible during simulated
  execution on desktop and mobile viewport sizes. Those UI checks are not
  additional real device test runs.

Earlier failed verification attempts are retained in the verification directory;
`final.xml`, `final-recovery.xml` and the settled recovery proof contain the
successful final checks. A timing race in the polling-test helper was corrected
to wait explicitly for the next status response before checking its poll count.

## Open the pictures

With the local studio running:

- Guide: <http://127.0.0.1:8000/static/android-testing-guide.html>
- APK: <http://127.0.0.1:8000/static/android-testing-images/1-apk.png>
- Installed app: <http://127.0.0.1:8000/static/android-testing-images/2-installed.png>
- Chrome: <http://127.0.0.1:8000/static/android-testing-images/3-chrome.png>

These are setup illustrations, not live device screenshots. The APK sources
are the official Sauce Labs/WebdriverIO GitHub releases; an existing Sauce Labs
APK is also in `runs/sauce_appium_verification/mda-2.3.0-27.apk`.

No `.env` file or API credentials were changed. No cloud AI calls were made in
this verification. An invalid external API key still needs replacement in the
app; visible fallback warnings prevent mistaking a rules run for verified AI
access. The new live checks establish the selected launch/recovery behavior,
not 100% application coverage or fresh verification of all three execution modes.
