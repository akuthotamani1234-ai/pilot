# Page components and nested menus

Implementation is added; execution and verification remain deferred at the user's request.

The existing Playwright crawler now records an additional per-page DOM component inventory. This is separate from
the existing feature registry and its functional test evidence. Identifying a component never counts as passing a test.

## What is listed

- Buttons and links; ordinary and password inputs; dropdowns and their rendered option labels.
- Checkboxes, radios, switches, sliders, date pickers and file-upload controls.
- Dashboard/navigation/sidebar sections, menus, menu items, breadcrumbs and pagination containers.
- Tabs and tab panels, accordions, dialogs, alerts, status areas and tooltips.
- Forms, field groups, tables/grids with visible column names and rendered row counts.
- Headings, images, media, charts/canvas and custom web-component hosts.
- Components inside open shadow roots and the same-site frames already inspected by the crawler.

Each record includes its name, kind, locator, parent component, frame context, hidden/visible observations and
observed component-state IDs. Dropdown option-label history is bounded and contains no selected input values.
Input contents, passwords and raw HTML are not copied by the component collector.

## Interaction states

The crawler captures initial DOM inventory, the existing mobile-viewport pass, and main-document snapshots after
eligible interactions. This includes controls revealed while the URL stays unchanged. Newly visible components
are connected to the action that revealed them. A static hidden component is identified as hidden, rather than
reported as an actually observed or tested control.

Nested opener replay restores the ancestor chain before interacting with a submenu control. Chains have a maximum
depth of eight, cycle detection, live safety checks and replay actions charged against the interaction budget.
Hover-only menus participate in the existing safe exploration queue. All existing action, time and stop limits remain.

Dynamic frame contents are initially inspected within the existing same-site frame policy; after-action component
snapshots currently cover the main document. Foreign, detached and depth-limited frames retain explicit reasons.
Closed shadow internals and canvas-drawn controls cannot be claimed as inspected from DOM data.

## Where to view it

After a crawl, the run includes:
- components.html: components grouped by page, with discovery and functional-evidence columns.
- components.json: full structured component and state inventory.
- A Page component inventory link in the main HTML report.

API:
- GET /api/components/{run}: page list, component counts, state metadata and limits.
- GET /api/components/{run}?page={slug}&offset=0&limit=100: paginated records for a selected page.
- Limits are 1?500 records per API request.

An exact selector/page match to an existing control-registry record can attach its real functional evidence.
Unmatched components remain not_tested. Representative group tests do not automatically verify every repeated
component. Custom business expectations still require an explicit requirement or approved QA contract.

## Bounds and later checks

Default bounds are 20,000 DOM nodes per snapshot, 2,000 identified components per page and 24 stored component
states. Truncation and failed inspection are recorded. Lazy loading and pagination continue to use the existing
crawler's bounded exploration; this inventory does not claim that an infinite page has been exhausted.

Prepared verification: tests/test_page_inventory.py covers hidden components, input-value omission, open shadow
content, tables/dropdown metadata, state transitions and nested opener replay. These checks have not been run.
The existing crawler, observer, registry and end-to-end suites must also be rerun in the later execution phase.
