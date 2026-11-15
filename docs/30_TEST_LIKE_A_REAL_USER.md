# Android functional test mode

Reviewed 2026-11-14. Test mode exercises eligible controls, forms and workflows on an explicitly approved test build
or demo environment. It requires ownership/permission and does not guarantee every screen, input combination or
business rule. See [coverage and continuation](33_ANDROID_COVERAGE_WORKSPACE.md) for the current scope model.

## Configure a run

1. Restart `ui.bat` after updating. Choose Android/Appium and Standard testing or an approved MCP assistant.
2. Select an APK, installed package or Android Chrome URL and the intended emulator/device.
3. Confirm permission and the test-build option. Configure test-account credentials, expected results and any
   approved flows. Use the guided builder for app-specific steps and read-only API/SQLite assertions.
4. Leave **Test all discovered scenarios** selected to remove interaction-count and generated-case cutoffs for
   test-build work. Discovery depth/screens/actions, time guards, scope and protected-action checks still apply.
5. Standard: click **Start Android test**. MCP: prepare the reviewed request and have the assistant call
   `start_prepared_test`. Both paths prepare installed local Appium and the selected emulator before starting.
   Missing tools or an unauthorized USB phone still need user setup. Refresh and mode selection start no test.

Do not put passwords or keys into task descriptions or inline contracts. The private Studio account fields and
`QPILOT_SECRET_*` references provide test inputs. MCP preparation copies only an expiring opaque reference plus
redacted settings. See [private configuration](34_MCP_SHARED_CONFIGURATION.md).

## Supported behavior and evidence

Android Chrome inventories rendered DOM controls and can explore same-origin menus, routes, dialogs and scroll
states. Test-build interaction supports eligible login/signup, validation, dropdown, search, cart and form flows.
Each dialog keeps its own identity; a Contact form does not inherit a Log in result merely because both use OK.
Support depends on reachable, uniquely identifiable controls and actual outcomes; a website name alone proves no
feature works. Read-only discovery does not authorize submissions.

Native testing inventories visible hierarchy controls, menus and observed screen paths. Approved interactions can
exercise input, navigation, sorting, quantity/cart changes and configured login outcomes. Actual device features,
hybrid context changes and permissions need their own supported configuration and approvals. Permission behavior
follows the selected policy; permission approval is not inferred from the generic test-build checkbox.

Exploration observes and replays candidate interactions. Accepted plans retain expected assertions. Conventional
negative checks and explicitly configured expectations may remain as failures instead of being discarded because
the application disagrees. Input readback, action completion, visible control presence and business correctness
are different evidence. Failures, execution errors and unexplored work must remain visible.

Fresh-start isolation clears the selected app's local data or target browser storage as configured. It cannot undo
server-side account creation or submissions. A resumed interrupted mutation stays blocked until reconciled;
completed cases are not repeated automatically.

## Protected work and barriers

Payment/checkout, destructive actions, account deletion, password changes, reset/crash controls, external sharing,
calls/SMS and out-of-scope targets retain their safety rules. Supported approved login/logout flows do not authorize
unrelated protected actions. Blocked controls are reported with reasons and are never counted as passing tests.
Physical-device data clearing is restricted; use an emulator or a suitable approved APK workflow.

Qpilot does not bypass authentication, device authorization, CAPTCHA or bot protection. A detected website security
check permits a bounded manual-completion window in the emulator. If it remains, the run reports that the target
was blocked; content behind it was not tested.

## Current limits

| Control | Default / interpretation |
| --- | --- |
| Screens, actions, depth and discovery time | `0` = until eligible work is exhausted; positive configured limits still apply |
| Discovery scrolls | `0` = until no readable viewport changes, up to the 100-gesture hard cap; positive limits still apply |
| Interaction tries / interaction time | `0` = no soft cutoff; full discovered-scenario mode removes the try cutoff |
| Generated cases | configured cap defaults to 300; full discovered-scenario test mode removes that cutoff |
| Thorough | raises positive soft limits; preserves zero as until exhausted |
| Emergency discovery/interaction phase guard | six hours when the corresponding time setting is zero |
| Whole-run time, Stop and scope | still enforced |

These are coverage controls, not performance measurements. A full run can take substantial time. There is no
promise of unlimited exploration, access to opaque frames/closed shadow roots, or all possible edge cases.

## Read the results

The report and Android coverage panel show scenario status, assertions, expected/actual outcomes, control coverage
and exploration gaps. Filter passed, failed, error, blocked, pending, skipped and inconclusive work. The live action
timeline records masked starts/completions and can recover after refresh. Counted results come from run files.

Saved `auto_flows.json` contains reusable approved-plan references rather than passwords. Private inputs must be
supplied again when needed. **Resume unfinished tests** keeps completed evidence and selects safely pending work;
starting a fresh run is a separate action. Passing a demo or presence check does not establish whole-app accuracy.
