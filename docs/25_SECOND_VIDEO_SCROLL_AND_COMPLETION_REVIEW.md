# Review of 5.mp4: scrolling and completion

This review concerns only `5.mp4`, as requested. The 47-minute, 8.5-second recording was sampled at 64 timestamps and compared with saved execution reports. It was not watched frame by frame. Review frames and contact sheets are in `runs/appium_recording_review_20261107_211754/2`.

## What the second video establishes

- Approximately 00:00–07:30 shows an earlier native report with **Insufficient Evidence**, a cart-total error and all eight pipeline stages finished. The matched `android_20261107_194323_542f49` report records **7 passed and 4 execution errors**. Finished stages do not mean all application tests passed.
- Around 13:28–15:42, the Playwright results are visible while the emulator overlaps the studio. The later saved Playwright run has 14 passing executed checks, within a limited page scope.
- Around 20:12–24:41, the Android dropdown attempt stalls, then error output includes ADB/SDK-query timeouts and an Insufficient Evidence verdict. These attempts cannot be counted as passing functionality.
- Around 27:40–40:24, the Android **System UI isn't responding** dialog is visible, while a large emulator console covers much of the studio. That platform dialog blocks phone interactions, including scrolling. Covered windows also prevent the video from demonstrating that the studio underneath can be operated. The video alone does not identify which browser pane received each wheel action.
- Around 41 minutes onward, native screens change again. The final frames show two cart items and total **59.98**. That visible total is consistent with the final native contract result; it is not proof of full-app coverage or a visible completion report, which is covered by other windows.

The final saved native run `android_20261107_203423_6880f6` completed **11 configured checks, all passing**, with no failed assertions or execution errors. Its verdict is **Ready with Risks**, including four controls left unexplored during crawling and one recorded System UI Wait recovery. Some controls classified by discovery can also be exercised by explicit approved flows; the discovery count is not a count of four proven failing features. The whole application was not established to be 100% tested. Earlier failures remain saved separately.

## Additional UI problems reproduced and fixed

The earlier execution-list fix did not cover every setup/navigation pane. New browser checks reproduced these remaining problems:

- At 1024×529, the Android form was only about 105 pixels tall because landing content consumed the available height. Android configuration now enters the configuration state, hides the welcome content, uses compact spacing in short windows and gives the form a usable independent scroll area. Start and the authorization checkbox remain reachable while the header stays visible.
- The navigation footer was clipped in a 480-pixel-high window. The navigation pane now scrolls as a whole, with its recent-run list and footer reachable. Scrollbars have a more usable width and stable space.
- Android could show a green **Android complete** badge even when its report said **Insufficient Evidence**. Completed live runs and saved reports now display their actual verdict in the header. Ready with Risks and insufficient evidence use an attention color; Not Ready uses the failure color. Loading or unavailable reports are not shown as successful.
- Android configuration now displays the Android execution plan, and switching back restores the website plan. If setup prevents Start, the reason is also shown near Start rather than only above the scrolled form.

The execution plan and results are separate scrolling panes. Its eight stage markers indicate pipeline progress, not a percentage of the application proven correct.

## Verification

The first targeted run reproduced eight failures: three cramped setup layouts, an unreachable navigation footer and four incorrect completion verdict labels. The execution-plan wheel check already worked and was retained as a regression.

After the changes, **65 UI, editor, privacy and rendering checks passed**, including existing live-follow/reading-position and Excel tests. Additional focused checks cover the final engine-plan labels and disabled-Start explanation. JavaScript syntax and Ruff passed. Reports and screenshots are in `runs/second_video_scroll_verification`.

The running local UI was checked at 1024×529: Start was reachable by scrolling, the earlier failed report displayed Insufficient Evidence in its header, and the final native report displayed Ready with Risks. The device environment was not ready during that read-only UI check; no new Appium, Playwright target-site or cloud-AI run was started. These UI checks do not add application coverage to the historical reports.
