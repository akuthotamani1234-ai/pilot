# Website setup and route-coverage verification

After a URL is entered, setup shows four visible sections: Account, AI engine, Exploration, and More checks.
The account choice is explicit: public only, existing test account, permitted signup/reuse, or a configured local account.
Public-only runs do not reuse saved accounts. Signup requires permission and a registration route; verification barriers
are reported rather than bypassed.

AI cards show actual local-model availability, missing keys and privacy blocks. The installed local model is preferred
when available. Rules only is an explicit choice. The new UI asks whether a selected AI may fall back to rules;
without approval, local-model startup failure blocks starting and exhausted provider requests stop the run.
Cloud processing remains subject to the existing separate privacy approval.

Whole-site scope and all discovered pages are the defaults. An old saved two-page limit or click depth is not silently reused.
The page count, per-page action budget, hard safety cap, time budget, exclusions, protected actions and login barriers still
bound exploration. All discovered eligible routes processed is a narrower statement than every possible business state tested.

## Crawl fixes

- HTTP 404 routes with positive client-rendered application evidence remain eligible for UI exploration and test generation.
  Their original status is preserved and reported. Genuine error documents, 401/403, rate limits and server failures are not overridden.
- Repeated product cards with JavaScript navigation are recognised without inventing hrefs.
- Empty ARIA-labelled controls remain clickable controls rather than being mistaken for bookmarks.
- Changes to a cart badge or other label are component states, not new opener chains.
- Visible targets do not replay obsolete openers. Hidden nested targets still replay their ancestor chain with bounds.
- Report headlines distinguish route exploration, registered feature coverage and functional test pass rate.
- Report summaries keep PASS / FAIL / BLOCKED / SKIPPED / NOT TESTED / INCONCLUSIVE separate, list pages
  discovered / visited / not visited, and state coverage limitations when crawl or time limits leave work unvisited.
  They never invent an overall site accuracy percentage.
- The HTML response disables caching, and JS/CSS references include content hashes to prevent mixed old/new UI files.

## Real public-site audit

Target: https://www.saucedemo.com/ using its published standard demo account.
Completed audit: runs/saucedemo_route_audit_20261106_093748/.

- 12 pages visited; 11 authenticated pages.
- 600 observed DOM components across those pages (observations include repeated controls on different pages).
- 37 exploration actions; 35 learned effects; no action failures.
- Zero discovered eligible routes left pending.
- Inventory, cart, all six product detail pages and three dynamic catalog variants were reached.
- Checkout, logout and remove actions were blocked and recorded. No purchase was completed.
- No functional test pass rate is claimed for this route audit.

The earlier five-minute audit was partial and is retained as evidence of the original cart-opener problem.
The completed audit's AUDIT_RESULT.json, crawl.json, app_map.json and components.html provide the detailed evidence.
Its temporary browser authentication was removed after the audit.

The installed local qwen2.5:3b model was separately called with a minimal noncustomer prompt and replied READY.
The real updated UI was checked against the backend: account inputs visible, installed model selected, whole-site scope
selected, and no page-count restriction. Static desktop/mobile previews also passed.

## Regression verification

The final setup/crawl/privacy/MCP/API suite passed (70 tests), login and crawl checks passed (21 tests), and the final
cart/nested-navigation checks passed (18 tests). These groups overlap; their counts must not be added as a unique total.
Live full-business-flow verification across every site and both engines is not implied by this scoped validation.
