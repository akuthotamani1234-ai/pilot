# Native Android form reliability

The live WebdriverIO v2.2.0 run on 15 November exposed Login/Sign up mode
selectors above the input fields being counted as extra submit buttons. When
complete bounds and common ancestry prove that exactly one candidate is below
all fields and every other candidate is above them, Qpilot selects that lower
submission. Multiple lower candidates or missing geometry remain ambiguous.
The saved device hierarchy now identifies the two-field Login form correctly;
this snapshot check alone does not establish a passing live form execution.

This change addresses the General Store behavior in the supplied `9.mp4` recording and saved run
`android_20261114_233335_45f80d`. Qpilot detected the name input but missed its unfamiliar submission label,
explored country choices as separate actions, and later encountered Android/ADB failures. These are separate
automation and environment issues; neither proves an application defect.

## Existing engine and targeted changes

The engine remains Python Appium client → Appium server → UiAutomator2 → Android. No WebdriverIO migration or new
dependency is required. Login/signup checks, private input delivery, value readback, device locks, safe resume and
existing reports remain in use.

- Native form recognition can associate an unfamiliar **single safe primary button** with its input container.
  Several possible submissions require a scoped approved flow; Qpilot does not guess among them. Cancel/navigation
  buttons and protected actions cannot become fallback submissions. Sidebar inputs are excluded when a nearer form
  container identifies the relevant fields.
- Standard native Spinners and radio groups join the form workflow. Qpilot observes one safe visible dropdown
  alternative, verifies selection, and records a reusable `select` step. Country options are not separately credited
  as completed business workflows. Radio selection is also asserted before submission. Multiple radio controls with
  no exposed group are treated as ambiguous instead of being combined into one guessed group.
- Native checkboxes are not inferred as required and are not auto-accepted. A flow that depends on consent or another
  checkbox needs an explicitly reviewed test flow; without that, successful form submission remains unverified.
- Nested form fields are retained only when one observed container holds the complete recognized field set. If Qpilot
  cannot scope all relevant fields to the submit control, it leaves the form unclassified instead of testing a partial
  login or signup.
- Android dropdown rows may be `CheckedTextView`, or standard `android:id/text1` TextViews inside a ListView.
  Both layouts are supported. Arbitrary custom pickers still require a reviewed explicit tap flow.
- UiAutomator2 can expose a short-lived Android validation Toast under a system package. Qpilot retains only the
  `android.widget.Toast` text from the immediate post-action snapshot, ignores the generic "Toast message" placeholder,
  and leaves all other system-package UI out of the screen. It verifies a Toast from the live hierarchy XML instead
  of keeping a WebElement that becomes stale as soon as Android dismisses the message. Stable screen identity does not
  depend on a Toast.
- Native UIA lookups use a shorter idle wait so a Toast stays queryable. Qpilot still waits for stable screen
  observations before it records a destination or continues exploration.
- A positive form result needs a configured destination, a verified new destination anchor, or a non-error success
  message. Disappearance alone, a blank/error page, or a message such as “not saved” cannot establish success.
  Observed regression checks remain distinct from independently specified business expectations.
- A successfully replayed native form can contribute its destination and setup steps to subsequent exploration.
  List screens reached from a form now enter the same first-safe-item and screen-control checks as the launch/menu
  screens. Isolation and replay remain required for independent mutations; reducing repeated option tests does not
  authorize reuse of an uncertain submission.
- An AI journey cannot submit a recognized native form without its input setup. Deliberate empty/invalid-input
  testing uses validation checks or an explicitly configured workflow.
- Recorded UiAutomator proxy/socket failures and ADB transport-closed failures are classified as session loss.
  Assertion and missing-locator errors retain their distinct classification. Session loss during input is propagated
  without entered values, and an uncertain submission is not automatically repeated.

Checkout, payments, destructive controls, external-target scope, test-build approval and private-data masking retain
their existing guards. This change does not claim coverage of every application or every input combination.

## Configure a native selection

The guided flow builder exposes `select` in native Android mode. Supply a standard Spinner's stable resource ID and
the **visible option text**, rather than a browser option's HTML value. Native selections are marked `test_form` and
require the existing flow/test-environment approval. They verify that the selected label was retained.

```json
{
  "action": "select",
  "locator": {"strategy": "resource_id", "value": "com.example:id/country"},
  "value": "Albania",
  "purpose": "test_form"
}
```

Add an expected-result assertion to the approved flow. Configure actual product/login success expectations instead
of copying whatever result a faulty app happened to produce. Passwords and account credentials still use private
references; never put them into this JSON.

## Verification and limits

The added fixtures reproduce the recorded entry-form structure, unfamiliar button labels, both standard native
dropdown layouts, grouped selection and submission, wrong selection readback, ambiguous buttons, sidebar inputs,
misleading success messages, and loss during input. Existing Android and QA suites cover the shared engine and guards.
Desktop/mobile browser fixtures verify that the flow builder produces approved native-selection steps without
starting device automation.

Current completed test counts and real-device acceptance results are recorded in [STATUS](../STATUS.md). Offline
fixtures alone are not evidence that the supplied APK passed. Live environment failures and partial attempts must
remain separate from completed acceptance. A stopped emulator, System UI ANR or crashed instrumentation cannot be
fixed merely by choosing another form label or increasing exploration limits.
