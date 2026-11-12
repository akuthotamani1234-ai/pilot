# Execution scrolling fixes and Appium recording review

## What was reviewed

Both supplied recordings were sampled at 32 positions each and compared with saved run artifacts. This is a sampled review, not a frame-by-frame review of approximately 57 minutes of video. Contact sheets and timestamps are in `runs/appium_recording_review_20261106_171527`.

My rating of the **recorded demo experience is 5/10**. Some genuine native interactions and assertions are visible, but stale Inspector screenshots, intermediate failures and confusing progress navigation make the demonstration unreliable to follow. This rating is not a measured application coverage percentage and is not a rating of every current code path.

- In `2.mp4`, approximately 08:37–16:10, Inspector repeatedly shows the splash screen while the emulator shows the menu, product details or login. Inspector's displayed snapshot is not reliable evidence of the emulator's current state in those frames.
- Around 17:15–24:48, the separate replay page reaches **23 passed, 1 error, 1 blocked**, with an Insufficient Evidence verdict. Its URL identifies the intermediate `sauce_ai_replay_20261106_163820` run.
- Around 30:11–32:20, the emulator is at an Android location permission prompt while that replay page is already complete. Those later device interactions cannot be counted as passing tests from the completed run.
- In `Recording 2026-11-06 162443.mp4`, an earlier run shows a 401 error. Later, around 21:00–24:06, the main UI shows a long nested execution list, changing test steps and intermediate failures. These are not proof of a clean full-app run.

## Reproduced UI defects and changes

The previous browser code considered a reader within 120 pixels of the bottom to be following live output. A small upward scroll was therefore undone by new messages. Case polling replaced the execution HTML, closing user-expanded steps. The case list also had its own 460-pixel vertical scrollbar inside the main message scrollbar.

The execution/results workspace now has one main vertical scrolling surface. Wheel, touch and keyboard scrolling can reach every case; wide tables retain horizontal scrolling. Test names and failure details wrap. The header and Stop remain accessible in short windows and at phone width. The welcome panel is hidden during execution and results.

Live refresh preserves expanded/collapsed steps, focused step summaries, table scroll offsets and the visible case/message position, including when an earlier case grows. Scrolling upward pauses following; **Follow latest** explicitly resumes it. The results area is keyboard focusable and named for accessibility. These shared changes apply to both engine views. Excel remains a separate scrollable viewer.

## Verification of this change

The initial five focused browser checks failed against the old code: three viewport checks exposed the nested scrolling list; expanded steps were lost; a new update moved the reader by 126 pixels after a small upward scroll.

After the fixes, **52 checks passed** in 69.06 seconds across `test_results_layout.py`, `test_privacy_workflow.py` and `test_setup_and_rendered_pages.py`. Coverage includes live Android and web progress views, desktop/short-window/phone layouts, wheel and keyboard scrolling, expanded-step retention, reading position during updates, explicit resumption of following, existing result artifacts and Excel scrolling/filtering during execution. JavaScript syntax and Ruff checks passed.

The browser checks intercept HTTP requests; they do not start an AI request, an Appium session or a website test. Screenshots at 1440×900, 1024×529 and 390×844 show open steps surviving an update with **0 pixels** of movement and no browser errors. See `runs/ui_scroll_verification/results.xml`, `visual_checks.json` and `execution-*.png`.

## What the saved Android result proves

The later `sauce_ai_replay_20261106_165209` result has **24 passed, 0 failed, 0 errors and 1 blocked scope case**, with verdict **Ready with Risks**, across four discovery screens. It is a different run from the failed intermediate replay visible for much of the recording.

Its 24 passing checks comprise 11 configured functional contracts, 3 AI-designed UI visibility cases and 10 rule-based launch/navigation/visibility checks. They are not 24 independent business features. The generated Python was reused unchanged from the original OpenAI run; the functional contracts were explicitly configured. This does not establish fully autonomous business-test design.

The coverage gate records 31 controls blocked during discovery, one inferred scenario and four unexplored controls. Some discovery-blocked controls are exercised by explicit approved contracts; these counts must not be presented as 31 independent functional failures. Complete checkout/payment, every product and menu, WebView, camera/QR, location and biometric flows are not established by this selected suite. Neither the recordings nor the green selected checks justify a claim that the whole app is perfectly tested.

No fresh native/cloud run was performed for this UI change. Historical reports are unchanged. Refresh an open Blow AI page, or launch `ui.bat`, to load the saved frontend changes.
