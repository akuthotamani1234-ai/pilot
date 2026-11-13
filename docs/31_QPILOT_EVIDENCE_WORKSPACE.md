# Qpilot evidence workspace

The local UI is branded Qpilot. Existing directories, MCP names, environment prefixes and historical artifacts remain
compatible. New report pages use Qpilot branding.

## Behavior

- Watch mode uses one visible browser and one configurable delay per user action. The Studio chooses 1,000 ms;
  Fast mode uses isolated headless workers without that delay. The append-only worker timeline survives missed polls.
- The light workspace has Setup, Live run, Results and AI fixes navigation, readable action history, explicit uncertainty,
  repository selection and a diff review step before publication.
- Every reporting path reconciles saved aggregate/worker results and produces deterministic provisional findings before
  evaluating gates. Optional AI explanations are not needed to write a report. Grouped findings retain every affected node
  and case. Input-only form checks do not establish save or persistence and cannot establish business-feature verification.
- Forms resolve uniquely within their recorded container and replay their observed opener path. Required fields cannot
  silently disappear from a whole-form check. Date inputs need a grounded format. Custom checkbox labels are clicked
  through normal browser interactions; failed interactions cannot become passing checks through forced DOM changes.
- Discovery only fills inputs; authorized submissions remain in planned tests with the existing authorization and cleanup
  mechanisms. Read-only administrative navigation uses both its purpose and native navigation context; payment buttons
  and consequential routes remain protected.
- Discovery defaults to at most 40% of the overall run budget, additionally bounded by the crawl cap. Execution stops
  early enough to reserve 120 seconds for finalization. Phase durations and pending cases are saved. Read-only resume
  deselects completed tests. Interrupted write workflows require reconciliation instead of blind replay.
- Unsupported AI journeys remain in future runs' planned-case denominator with an explicit rejection reason. Changing
  media loading percentages are excluded as unstable action/oracle evidence.

## GitHub preparation and review

Qpilot downloads an isolated source snapshot pinned to the default branch's commit. It does not pull into an existing
checkout. Up to five supported product findings can be selected. Existing privacy policy, AI provider and budget controls
apply. Automation errors, environment problems and untriaged results remain investigation items.

Preparation runs in a separate process with a seven-minute bound. AI edits must match supplied source exactly once and
link to the chosen finding. Source matching rejects duplicate matches across files. The full proposal remains private;
the UI receives the diff, explanation, selected findings, base commit and validation results.

Python and JSON syntax checks are local; JavaScript syntax uses `node --check` when available. Unsupported file types and
project regression commands are visibly marked unavailable. A checked review acknowledgment enables publication. The
server verifies the proposal digest and unchanged base before publishing all reviewed files together in one commit on a
separate branch. It never merges the pull request. Duplicate publication returns the existing result.

## Immutable evidence comparison

These are report rebuilds, **not fresh website executions**. Outputs are in `review_artifacts/qpilot_validation/` beside
the repository. The source artifacts were hash-checked in regression tests and left unchanged.

| Saved run | Single-test denominator and outcomes, preserved | Planned / executed cases, preserved | Findings before → after | Consistent before → after |
|---|---|---|---|---|
| OrangeHRM, Nov 12 23:01:10 | 123: 79 passed, 35 failed, 6 inconclusive, 3 skipped | 245 / 120 | 0 → 41 provisional findings | false → true |
| Demoblaze, Nov 13 13:17:02 | 124: 120 passed, 2 failed, 2 inconclusive | 45 / 43 | 8 → 8, with case/node linkage | true → true |
| Demoblaze, Nov 13 13:46:16 | 0; stopped during discovery | 0 / 0 | 0 → 0 | true → true |

The completed Demoblaze run originally designed 64 cases but removed 19 rejected AI journeys before saving its final
45 cases. A report rebuild preserves those 45 saved cases; it does not invent the missing proposals. Future runs retain
rejected proposals with an unsupported/skipped reason.

The OrangeHRM feature denominator remains **579**: 81 PASS, 12 FAIL, 118 BLOCKED, 27 INCONCLUSIVE and 341 NOT TESTED.
Its 31 executed input-only checks are now identified separately; the workflow inventory falls from 48 to 20 cases after
excluding input-only forms. This is a classification correction, not an increase in verified business coverage. The
Demoblaze rebuild similarly identifies four input-only checks and excludes one input-only journey from its three-case
workflow inventory. All three verdicts remain Insufficient Evidence.

Rebuild into a separate, empty output directory:

```powershell
.venv\Scripts\python.exe -m backend.report_rebuild runs/<saved-run> ../review_artifacts/<new-output>
```

## Validation and practical limits

Focused local regression verification covers both Demoblaze runs, the earlier interrupted run, field/container identity,
custom controls, login dialog replay, dates, durable event cursors, source proposals, validation failure, stale bases,
duplicate publication and desktop/mobile review screens. No public demo mutation or real GitHub publication was used.
Browser previews are saved under `.snapshots/qpilot_review/`.

AI preparation currently edits existing supplied files, within a 100,000-character source context and a 25 MB compressed
repository archive limit. It can decline unsupported roots or missing evidence. Project-specific test execution and
deployment are not automatic; their absence is displayed in the review and PR. Interrupted writes need manual record
reconciliation before continuing. Older saved runs only contain their original step evidence; complete live history is
available for runs produced with the new event recorder. Compatibility does not mean historical failures became fixes.

### Validation handoff

Changes are saved locally on `feature/qpilot-evidence-workspace`; no merge or push to main was performed.
Ruff and JavaScript syntax checks passed. A completed focused regression run passed 66 tests. After the broad run
exposed integration and fixture issues, another focused check covering the seven remaining failures plus real sandbox
recording passed all 16 selected tests. Report rebuilds preserve both Demoblaze runs and account for the earlier run's
41 failed/inconclusive results without modifying source evidence.

The final full offline pass progressed beyond 90% with no failures reported before the user requested the saved changes
for their own run. That pass and additional local workflow verification were stopped before completion; there is no
final full-suite pass claim. Restart `ui.bat` and refresh Studio before testing the new backend endpoints.
The changed-file manifest is `review_artifacts/qpilot_validation/changed_files.txt` beside the repository.
