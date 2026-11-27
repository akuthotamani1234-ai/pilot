# Live run analysis - SauceDemo hybrid execution (26 Nov 2026)

Run: `runs/www.saucedemo.com_20261126_154559` (Jira route, mock Jira QPL-4 / QPL-5, OpenAI gpt-4o-mini, strategy
hybrid). 54 cases: 2 Jira cases + 52 exploratory. 32 passed. Every case that did not pass is classified below from
its own evidence (error, screenshot, generated code) - not from the engine's label alone.

Categories: genuine application defect, automation coding error, invalid selector, ambiguous locator, failed
prerequisite, environment issue (incl. test-state leakage), access restriction, unsupported functionality, not
executed.

| Case | Origin | Engine result | Evidence | Classification | Status now |
|---|---|---|---|---|---|
| TC-QPL-4-1 (Adding a product puts it in the cart) | Jira | Not automated | the AI's code used a broad `text=` locator, refused by the validator twice | **Automation coding error** (AI) -> not executed | validated automation is reused once proven (atlassian/automations.py, `0133e18`, `6a346db`) |
| TC-QPL-5-1 (start checkout from the cart) | Jira | Requires review | screenshot: Backpack already in the cart ("Remove", badge 1) at the start - left by an earlier test | **Environment issue: test-state leakage** (localStorage) | fixed: storage reset before every test (`0133e18`) |
| Log in with the test account and use the app | built-in | Failed (inconclusive) | "Failed to load resource: 404" | **Genuine application behaviour**: SauceDemo answers its client-rendered pages with HTTP 404 (non-functional; the pages render) | unchanged - a real observation, reported as inconclusive, not as a functional defect |
| Shop: add to cart -> open the cart | built-in | Failed (test mistake) | 'Add to cart' not found; cart already filled | **Environment issue: test-state leakage** | fixed (`0133e18`) |
| 'Add to cart' opens its panel | built-in | Failed (test-script defect) | target not unique / not present because the item was already in the cart | **Environment issue: test-state leakage** | fixed (`0133e18`) |
| 'Add to cart' adds the item (inventory) | built-in | Failed (test mistake) | screenshot: cart badge 2, Backpack and Bike Light show "Remove" | **Environment issue: test-state leakage** | fixed (`0133e18`) |
| 'Add to cart' adds the item (item 4) | built-in | Failed (test mistake) | same | **Environment issue: test-state leakage** | fixed (`0133e18`) |
| Login with valid credentials | AI exploratory | Failed (test mistake) | `expect(page.url).to_contain(...)` -> ValueError | **Automation coding error** | fixed: repaired before running (`a26b5f4`) |
| Navigate to inventory from cart | AI exploratory | Failed (test mistake) | same ValueError | **Automation coding error** | fixed (`a26b5f4`) |
| Add item to cart from inventory | AI exploratory | Failed (test mistake) | asserted the accessible name "Cart, 1 items" as visible text (it is "1") | **Automation coding error** (wrong assertion target) | still occurs with fresh AI code (seen again 27 Nov); avoided once a case's automation is validated and reused |
| Add multiple items to cart | AI exploratory | Failed (test mistake) | "Cart, 1 items" expected, 3 shown (also leaked state) | **Automation coding error** + test-state leakage | leakage fixed; assertion error as above |
| Add item to cart and check cart count | AI exploratory | Failed (test mistake) | "Cart, 1 items" expected; the cart held 4 items from earlier tests | **Automation coding error** + test-state leakage | as above |
| View item details | AI exploratory | Failed (test mistake) | `get_by_role("link", name="View details for Sauce Labs Backpack")` - no such link | **Invalid selector** (AI-invented accessible name) | regenerated per run; not a defect |
| View details for multiple items | AI exploratory | Failed (test mistake) | same invented link name | **Invalid selector** | as above |
| Open menu and navigate to About | AI exploratory | Failed (test mistake) | expected title "About"; About leaves for saucelabs.com (another site, blocked by scope) | **Automation coding error** (wrong expectation) / **access restriction** (out of scope host) | not a defect |
| Check required fields on login | AI exploratory | Failed (test mistake) | expected "Password is required"; with both fields empty the site says "Username is required" first | **Automation coding error** (wrong expectation) | not a defect |
| 1 more pages like /inventory-item.html?id open | built-in | Failed (inconclusive) | id=5 -> HTTP 404 | **Genuine application behaviour** (HTTP 404 status of client-rendered pages) | reported as inconclusive |
| Every page opens (5 pages) | built-in | Failed (inconclusive) | cart.html -> HTTP 404 | **Genuine application behaviour** (same root cause) | reported as inconclusive |
| No JavaScript errors on any page | built-in | Failed (inconclusive) | resource 404 | **Genuine application behaviour** (same root cause) | reported as inconclusive |
| Every link works (8 links) | built-in | Failed (inconclusive) | inventory.html -> HTTP 404 | **Genuine application behaviour** (same root cause) | reported as inconclusive |
| Input boxes handle wrong values (0 boxes) | built-in | Not run | no input box on the explored pages to test | **Not executed** (nothing to test) | correct |
| 'Checkout' on Swag Labs | built-in | Blocked | protected action, demo checkout not allowed for hybrid runs | **Access restriction** (by policy) | correct |

Summary of the 21 cases that did not pass:
- **Genuine application defects (functional): 0.**
- **Genuine application behaviour, non-functional: 5.** All have one root cause, HTTP 404 status codes on pages
  that render. They were reported as inconclusive, never as functional defects.
- **Test-state leakage (environment): 6** (including TC-QPL-5-1), all fixed.
- **Automation coding errors: 7** (two more also hit by the leakage). Two of them (the ValueError) are fixed. The
  rest are AI answers that vary from run to run: wrong expectation, wrong assertion target.
- **Invalid selectors: 2** (AI-invented accessible names).
- **Access restriction: 1. Not executed: 1. Not automated (TC-QPL-4-1): 1.**
- No AI automation error was reported as an application defect. All of them were labelled "Test mistake" /
  "Test-script defect" (Requires review for Jira cases) by the engine itself.

## Repeated executions (27 Nov 2026, commit `93f3c95`, one workspace)

| Run | Strategy | Jira automation | TC-QPL-4-1 | TC-QPL-5-1 | Exploratory | Note |
|---|---|---|---|---|---|---|
| 1 | requirements | generated | Requires review | Requires review | - | AI asserted the accessible name "Cart, 1 items" as text |
| 2 | requirements | generated | Requires review | Requires review | - | same AI mistake |
| 3 | requirements | generated | **Passed** | **Passed** | - | both validated automations stored |
| 4 | hybrid | 5-1 reused (revalidated) | Not run | Not run | 52 not run | the OpenAI account ran out of credits mid-run (HTTP 429 `credit_balance_exhausted`); the run stopped honestly |
| 5 | hybrid | - | Not automated | Not automated | 35 not run | no AI credits |
| 6 | hybrid | - | Not automated | Not automated | 35 not run | no AI credits |

Without reuse, a fresh AI answer passed in 1 of 3 requirement-based runs. That is the variability the automation
store removes once a case has been proven.

### After the automation store (27 Nov 2026, commits `6a346db`-`81c987f`, OpenAI account without credits)

The store was seeded from the real execution that validated both cases (run `www.saucedemo.com_20261127_040506`,
saved through `automations.save`, exactly as the bridge does after an execution).

| Run | Strategy | TC-QPL-4-1 | TC-QPL-5-1 | Automation | AI used |
|---|---|---|---|---|---|
| 7 | requirements | Passed (3 checks) | Passed (5 checks) | both reused, revalidated (store passes 1 -> 2) | none (3 optional naming calls failed - no credits - without stopping the run) |
| 8 | requirements | Passed | Passed | both reused (passes 2 -> 3) | none |
| 9 | requirements | Passed | Passed | both reused (passes 3 -> 4) | none |

Two problems found on the way and fixed:
- `a44e92c`: an optional feature-naming call stopped the run.
- `81c987f`: a proven selector (a cart row) was refused because the run's short exploration had seen an empty cart,
  and one case's AI failure stopped the whole requirement-only run.

Requirement-based: **3 of 3 consistent passes with reuse**, against 1 of 3 with fresh AI code.

Hybrid: **BLOCKED** - its exploration needs the AI, and the OpenAI account used here has no credits
(`credit_balance_exhausted`). Run 4 showed the hybrid path accepting the reused, revalidated automation before the
credits ran out. Repeat it with a funded AI account (LOCAL_ACCEPTANCE_TESTING.md section 4).
