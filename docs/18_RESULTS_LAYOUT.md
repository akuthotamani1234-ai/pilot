# Results layout and empty-state correction

Saved results use a dedicated results view. The engine/workflow cards, URL composer, and configuration forms stay on the setup screen; a compact New test action restores that screen. The thread occupies the available height, messages do not shrink, short landing screens can scroll, and responsive navigation closes after selecting history. Completion icons and scrollbars are corrected.

Discovery reports show pages inspected and components observed, with inventory/report links and an explicit statement that functional tests were not generated or run. They do not render an empty case table or offer absent Excel artifacts.

The cases API reports structured-case availability and Excel availability independently. Empty results, HTTP failures, and malformed responses never announce successful test generation/export. Android completion links also depend on artifact availability. Navigation generation checks discard stale report, pages, cases, coverage, and repository-fix responses.

Saved progress uses recorded stage evidence rather than marking every stage complete.

Validation:
- 85 checks passed across results layout, rendered pages/setup, privacy/workflow, MCP, and server regressions.
- The final icon/progress polish was followed by the focused results/server checks.
- JavaScript syntax checks passed.
- The running app was checked against the existing SauceDemo discovery audit: 12 inspected pages, 600 observed components, no functional tests claimed.
- Desktop viewports 1440x900, 1137x687, 1024x529 and mobile 390x844 were checked using intercepted fixtures.
- No new public crawl or Android functional execution was performed for this presentation fix.
