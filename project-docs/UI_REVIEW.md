# Blow AI Studio UI redesign

Saved changes:
- Modern light workspace with dark navigation, vector icons, clearer typography and consistent spacing.
- Explicit Web (Playwright) and Android (Appium) platform cards.
- Focused website discovery input and an Android setup panel with collapsible advanced checks.
- Restyled execution timeline, report actions and component inventory access.
- Matching accuracy-lab screens and responsive phone layouts.
- Mobile navigation/execution drawers with close controls, backdrop and Escape handling.
- Existing submission fields and API payloads retained; platform selection locks during active runs.

Validation performed only on the frontend with stubbed read-only API responses:
- JavaScript syntax, unique static IDs and Android form/handler alignment.
- Desktop and phone rendering, mode selection and mobile drawer dismissal.
- No browser rendering errors or horizontal overflow in the reviewed phone layouts.
- No backend jobs, live crawls, Appium sessions or test engines were started.

Static previews: .snapshots/studio_preview_20261105_230125/
Full application verification remains deferred. Launch ui.bat and refresh the browser to view the updated UI.
