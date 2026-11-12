# Modal forms and verification accuracy

## Review evidence
Reviewed sampled frames across Recording 2026-11-06 130108.mp4 (22m46s) together with the stored Demoblaze run.
The recorded run was rated 3/10: it spent excessive effort on media widgets, missed dialog forms and values, and failed to reopen complete nested paths. The previous claim that all features were implemented was broader than the verification supported.
Review frames are in runs/recording_review_20261106_135617.

## Corrections
- Extract native forms, ARIA form regions and visible dialog input groups, including associated footer buttons.
- Merge forms found after opening dialogs into the page model.
- Store observed opener paths and replay them for discovered forms and generated learned-control tests (bounded to eight steps, with cycle refusal).
- Fill modal forms after reopening their parent dialogs, and read back intended values.
- Hidden recorded fields produce an explicit skipped result instead of silently counting as tested.
- Count a discovered form as filled only after values were actually populated.
- Exclude media-player controls from hover-menu inference and media timers from validation/status messages.
- Resolve duplicated label targets using the adjacent or nearest preceding label, and keep accessible names consistent. This fixed Demoblaze Contact Name incorrectly receiving email data.
- Use a strict default automation-error threshold of zero. Unresolved script errors block a Ready verdict; clean execution does not fail the zero threshold.
- During active execution, show progress in the available workspace rather than large disabled setup controls.

## Validation
27 passed: modal accuracy, observation, crawl priority, metrics and DOM inventory regressions.
77 passed: forms/write protection, results layout, privacy workflow, MCP integration and server regressions.
After the duplicate-label/accessibility correction, all 9 focused modal/accuracy tests passed (these repeat earlier modal tests and add one label regression).
Python source parsing and frontend JavaScript syntax checks passed.

A targeted real-site Contact check confirmed:
Email = qa-run-f1@example.com
Name = QA qa-run-f1
Message = QA test qa-run-f1
Send clicks = 0
Evidence: runs/modal_form_final_verification/20261106_150744/RESULT.json and contact-correct-values.png.
Earlier targeted checks that exposed the label error are retained.

## Remaining validation
A fresh full Demoblaze pipeline with the selected OpenAI model is still required.
OpenAI was subsequently used for actual Android demo design and Python generation with keys entered directly in the app.
No API key was read or exported by the review tools. See 21_FEATURE_AUDIT_AND_LIVE_ANDROID.md for current evidence.
The separate fresh full Playwright retest after the final web fixes remains outstanding.
The old 93-check report and its 10 failures were not rewritten as passing.
Login coverage still depends on the selected account mode and approved credentials/signup permissions.
