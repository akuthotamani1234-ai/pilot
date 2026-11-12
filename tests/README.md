# tests/ – testing the tester

These tests check Blow AI itself. They need **no internet, no AI and no test account**. `conftest.py` switches the
AI off and resets every setting that `.env` could change, and the websites they test are practice websites that run
on this PC.

## Running them
First install the test-only packages once: `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`.

```powershell
.venv\Scripts\python.exe -m pytest -q -n 3 --dist loadfile -m "not slow"   # quick check: 276 tests
.venv\Scripts\python.exe -m pytest -q -n 3 --dist loadfile                 # everything: 330 tests
.venv\Scripts\python.exe -m pytest -q tests/test_safety.py                 # one file
```
- `-n 3 --dist loadfile` runs 3 test files at the same time (pytest-xdist), keeping each file's tests together.
- **slow** marks the files that run the whole tester (`main.py`) or a real sandboxed test run. Each takes minutes.
- Use pytest's normal temp folder: a `--basetemp` inside a long path can make Windows paths too long.
- Times on the test laptop (16 GB, no graphics card), measured when the suite had 204 quick / 255 tests in all: the
  quick check took about 4 min, everything 1 h 10 min to 2 h. The suite has grown since, so allow a little longer.
  Don't run other heavy jobs at the same time: with little free memory the full suite took 1 h 52 min instead of
  1 h 11 min, and one end-to-end run went past its 20-minute limit. That test passes in about 7 minutes on its own.
- Don't edit `backend/` while the slow tests run: each starts a fresh `main.py`, which would mix two versions.

## The practice websites
Small local websites with known content, some with planted bugs. Each starts on a port of your choice:

| File | Website | Start it by hand |
|---|---|---|
| `demo_app.py` | **DemoShop**: public pages, a login (`demo` / `Demo#1234`), MFA and CAPTCHA variants, forms, a 404 link, a JavaScript error | `python tests\demo_app.py 8765` |
| `demo_store.py` | **DemoStore**: a shop behind a two-step login (`demo@store.test` / `Store#2024`): search, filters, sort, pages, cart, wishlist, orders | `python tests\demo_store.py 8766` |
| `classic_shop.py` | **ClassicShop**: an older template shop (`?rt=<route>` pages, `classic@shop.test` / `Classic#2024`), 3 planted bugs | `python tests\classic_shop.py 8767 bugs` |
| `admin_portal.py` | **AdminPortal**: iframes, shadow DOM, a users table with create / edit / delete, reports; bugs B1–B7 | `python tests\admin_portal.py 8768 bugs` |
| `travel_site.py` | **TravelSite**: flight booking with date ranges, passengers, totals; bugs T1–T6 | `python tests\travel_site.py 8769 bugs` |
| `big_store.py` | **BigStore**: 2,000 products (`shopper@big.test` / `Big#Store2026`); bugs S1–S3 | `python tests\big_store.py 8770 bugs slugs` |

Add `bugs` to start the copy with the planted bugs. What is really on each website, and each planted bug, is written
in its truth file: `demo_store_truth.json`, `classic_shop_truth.json` and `truth/*.json`.

## The accuracy benchmark
`accuracy_benchmark.py` runs the whole tester against a practice website and scores the run against its truth file:
what was found, what was missed and the false alarms.
```powershell
.venv\Scripts\python.exe -m tests.accuracy_benchmark --site admin --mode both
.venv\Scripts\python.exe -m tests.accuracy_benchmark --site travel --mode both
```
`--mode first` tests a fresh copy (clean and buggy), `--mode regression` runs the clean run's tests again on the
buggy copy, and `both` does both.

## What the test files cover
| Files | What they check |
|---|---|
| `test_core.py`, `test_rules.py`, `test_metrics.py`, `test_registry.py` | the rules: test design, script checks, failure categories, release gates, the report's numbers, stable ids |
| `test_safety.py`, `test_server.py`, `test_sandbox.py` | approved scope, secret removal, encrypted accounts, the local-only web server, the sandbox |
| `test_login_discovery.py`, `test_deep_exploration.py`, `test_observe.py`, `test_stay_in_section.py` | login, crawling, learning what controls do, staying in the section given |
| `test_classic_markup.py`, `test_frames_shadow.py`, `test_stronger_checks.py`, `test_forms_and_writes.py`, `test_rules_between_fields.py` | page structures, iframes and shadow DOM, sort / search / page-size checks, forms per environment, rules between fields |
| `test_run_always_reports.py`, `test_extensions.py` | a run always ends with a report; review, page discovery, roles, phone width, JS coverage, large sites |
| `test_like_a_user.py`, `test_testoptim_missing.py`, `test_visual_and_integrations.py` | going through a site like a user; 2-step login codes, multi-step forms, your own tests, review, re-check, scheduled runs; the visual check, Slack / Jira, the webhook |
| `test_end_to_end.py`, `test_classic_shop.py`, `test_accuracy.py`, `test_proof.py`, `test_big_store.py` | the whole tester on the practice websites, measured against their truth |
| `test_*_lessons.py` | mistakes found on real websites (each file names the run it came from), so they never come back |
| `test_android_site.py` + `android_fake_site.py` | Android test mode on a website: a fake shop in "Android Chrome" (menus, cart, login, bot checks) driven through the real pipeline |
| `test_android_site_dialog_forms.py` | the same shop with demoblaze-like pop-up dialogs (`FakeShop(dialogs=True)`): Log in / Sign up / Contact links are menu entries, their dialogs become states and every box is filled; the page reader's toggle decision in a real Chromium page |

## Adding a test
- **Every fixed mistake gets a test** that fails without the fix. A mistake found on a real website goes into that
  website's `test_<site>_lessons.py` file (or a new one), with a docstring saying what went wrong and in which run.
- Prefer a small page served by Playwright's `page.route` or a practice website over a real website: the tests must
  not need the internet.
- Mark a new file that runs `main.py` as slow: `pytestmark = pytest.mark.slow`.
- Check the code before you hand it over: `.venv\Scripts\python.exe -m ruff check .`
- GitHub Actions (`.github/workflows/ci.yml`) runs ruff and the quick tests on every push and Pull Request; started
  by hand with *full* ticked, it runs the slow tests too.
