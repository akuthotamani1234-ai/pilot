# Android coverage workspace

Choose an APK, installed application or Android Chrome target. Qpilot starts local Appium and prepares the selected
device when Start test is pressed. Selecting Android or checking environment status remains read-only.

## All discovered scenarios

The advanced Android option **Test all discovered scenarios** is selected by default. With test-build mode enabled,
it removes interaction-count and generated-test-count cutoffs. Distinct eligible controls are scoped to their
observed screen rather than globally sampled by label. The internal generated-flow inventory can exceed 100 flows;
the public user-supplied contract keeps its input-size limits.

The MCP Android start tool exposes the same `test_all_discovered` setting. It takes effect only with the separately
confirmed `test_build=true`; it does not authorize test-build interactions by itself.

Stop, time limits, selected discovery depth/screens/actions, external-target scope, and action guards still apply.
Menus, permissions, payments, account deletion, reset/crash buttons and other protected actions retain their rules.
Full coverage is a request to test discovered work, not a guarantee of infinite exploration or every business rule.
Unknown expectations require requirements or configured checks. The report must retain real failures and gaps.

Screen identity distinguishes forms with matching shells, ignores numeric quantity headings, and separates active
dialogs from their underlying screen. Controls behind a dialog are not treated as disappeared controls.

## Coverage and live actions

The Android coverage panel lists scenario status, assertion counts, expected outcomes and reasons. Filter by passed,
failed, error, blocked, pending, skipped or inconclusive. Exploration gaps and control-level coverage remain visible.
A presence-only UI check does not give a button or form a passing functional result. A shared locator such as OK
does not give unrelated screens credit.

Android actions write append-only per-process event files as they start and finish. Browser refresh/reconnection
uses the same durable event cursor as web runs. Filling inputs hides all entered values; exceptions expose their
type in the live timeline rather than their raw message. Assertion completion is distinct from action completion.

## Continue unfinished work

**Resume unfinished tests** appears when a saved checkpoint and validated scripts have safely resumable cases.
It prepares the original selected device, uses the original app scope, keeps the worker's completed results, and
selects only pending case IDs. It does not repeat discovery, completed failures, or completed successful mutations.

An interrupted data-changing case stays blocked because resetting local app data cannot undo a server-side
signup or submission. Reconcile its data before starting another run. Older runs without an attempt journal cannot
prove which mutations started, so only their unexecuted read-only checks can resume automatically.
Private references must still resolve in the local environment. An API key/account supplied only to a previous
request is not persisted for reuse. Starting a new full run is separate from continuing unfinished work.

## Reviewable AI scenarios

After discovery completes, choose **Draft a scenario with AI**. Describe navigation, expected behavior and private
data references, for example `BLOWAI_SECRET_TEST_USERNAME`. Qpilot uses its configured provider under the existing
privacy policy and binds draft targets to observed controls (up to 300 controls per draft request). It does not send
input contents or private files. Invalid references and inline credential fills are rejected.

Review and edit the draft, its expected-result basis and navigation, then approve the test environment before adding
it to the Android configuration. Adding a draft does not execute it. Unknown controls or rules require another
discovery run or explicit configuration; AI output is not evidence of a successful test.

## API and database outcomes

**Add API / database check** in the flow tools supports HTTP GET plus status/JSON-pointer/scalar expectations, or a
read-only SQLite SELECT with parameters and a scalar expectation. Tokens use `BLOWAI_SECRET_*`; local database paths
use `BLOWAI_DB_*` environment references. Metadata services, unapproved origins, HTTP mutations and SQL writes remain
blocked by the existing oracle implementation. Other database engines are not implemented by this wizard.

Attach checks to an existing UI workflow to verify its UI assertions followed by backend assertions in the same
test. The generated plan does not create a second standalone test for attached checks or repeat the UI submission.
An incorrect stored outcome remains a failed test even if the UI showed success. Separate independent checks are
also available. Approval of the UI flow remains required.

## Known-truth accuracy

Accuracy Lab can load real case IDs from the first selected run. Explicitly mark clean behavior as expected passed,
or an independently verified/seeded defect as expected failed. Unknown cases remain unassessed. Repeat the same IDs
under the same conditions to measure instability. Expected outcomes are never copied from actual results.

App crashes and ANRs count as detected known defects; infrastructure failures and explicit zero-assertion passes
remain unanswered. Precision, recall and answered coverage describe only supplied known-truth cases. They are not
an overall app accuracy percentage. The existing controlled Android fixture and app-specific example contracts
can be used for repeatable known-truth scenarios; their results do not establish coverage of arbitrary APKs.
