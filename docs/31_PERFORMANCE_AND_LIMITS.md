# Performance and known limits

**Phase 14 note:** Record the configured caps and measure a real run before changing defaults for speed.
This document lists **config limits**, not measured throughput. No benchmark numbers are invented here.

Primary settings live in `backend/config.py` (overridable from `.env`). README also summarizes the common ones.

## Rule: measure first

1. Run a representative local target (practice site or authorized fixture) with the current defaults.
2. Write down wall time, pages visited, tests run, workers used, and which limit stopped the run (if any).
3. Only then change one cap or worker setting and re-measure.
4. Keep Windows as the product/runtime target; do not assume Linux Job Object / DPAPI behavior matches.

Interrupted or budget-stopped runs already report **Insufficient Evidence** with the limit that was hit
(`RUN_TIME_LIMIT_MIN`, crawl budget, stop, and similar). That is the honest signal — not a guessed “% slower.”

## Crawl and discovery caps

| Setting | Default | Role |
|---|---|---|
| `MAX_PAGES` | `0` (no soft limit) | Soft visit budget. `0` means visit every eligible page until another limit stops the run. |
| `HARD_PAGE_CAP` | `500` | Safety ceiling so endless URL generators (calendars, search) cannot grow forever. |
| `MAX_DEPTH` | `0` | Soft click/link depth; `0` means no soft depth limit. |
| `CRAWL_SCOPE` | `auto` | Home → site; folder → section; deeper URL → that page (or forced `site` / `section` / `page`). |
| `CRAWL_TIME_LIMIT_MIN` | `30` | Stop exploring after this many minutes. |
| `RUN_TIME_LIMIT_MIN` | `90` | Whole-run wall clock; report what finished so far. `0` disables. |
| `PAGE_TIMEOUT_MS` | `20000` | Per-page load wait while crawling. |
| `MAX_REQUESTS_PER_SEC` | `2` | Polite rate on public sites (`0` = uncapped; slows further after HTTP 429/503). |
| `MAX_INTERACTIONS_PER_PAGE` | `15` | Clicks used to uncover hidden routes on one page. |
| `PATTERN_SAMPLES` | `0` | `0` = visit every route pattern; `>0` samples that many per pattern (large catalogs). |
| `SECTION` / `EXCLUDE_PATHS` | empty | Narrow or skip path prefixes. |

A run that hits a crawl or time limit is incomplete by design. Coverage claims must stay bounded by what was visited.

### Thorough mode (Studio + MCP)

**Thorough** raises **this-run only** budgets (it does not rewrite `.env` defaults permanently):

| This-run override | Floor |
|---|---|
| `EXPLORE_REPEATED_CONTROLS` | `true` |
| `MAX_INTERACTIONS_PER_PAGE` | at least `80` (still capped at `100`) |
| `CRAWL_TIME_LIMIT_MIN` | at least `60` (never lowered if already higher) |
| `MAX_TEST_CASES` | at least `500` |
| `PATTERN_SAMPLES` | `0` (every URL pattern) |
| `QA_THOROUGH` | `1` (job log notes Thorough budgets) |

Studio defaults intensity to Thorough (`max_pages=0` within `HARD_PAGE_CAP`). MCP `crawl_website` / `start_web_test` post the same Thorough fields with depth default `12`. Coverage stays finite: closed shadow DOM, pay/delete/logout, and cross-origin frames remain out of reach. Scripted controls ≠ business-verified checks.

## Test volume and parallelism

| Setting | Default | Role |
|---|---|---|
| `MAX_TEST_CASES` | `300` | Cap on generated cases (priority order). |
| `TEST_WORKERS` | `4` | Parallel browsers via pytest-xdist. Lower on small machines; visible Chrome uses one window serially. |
| `TEST_RETRIES` | `0` | Optional re-runs of failed tests. |
| `TEST_TIMEOUT_S` | `180` | Per-test timeout inside the sandbox. |
| `SUITE_TIMEOUT_S` | `3600` | Whole generated suite timeout. |
| `MAX_HEAL_ROUNDS` | `2` | Self-heal fix-and-rerun rounds. |
| `DATA_MAX_FIELDS` | `4` | Robustness inputs probed per page when data tests are on. |

Memory scales with open browsers. README notes testing on a 16 GB laptop; reduce `TEST_WORKERS` when memory is tight.
That is guidance, not a measured matrix for every PC.

## Sandbox and Windows-only process limits

| Setting | Default | Role |
|---|---|---|
| `SANDBOX_MEMORY_MB` | `6144` | Memory ceiling for browsers + pytest together (Windows Job Object). |
| `SANDBOX_MAX_PROCESSES` | `256` | Process count ceiling for the generated-test Job Object. |

On Windows, generated pytest **fails closed** if Job Object limits cannot be created or assigned (Phase 4).
Linux does not provide the same Job Object / DPAPI account store; treat Linux as offline/regression exploration only,
not the supported deploy target. See [DEPLOYMENT.md](../DEPLOYMENT.md).

## AI / vision cost and time bounds

| Setting | Default | Role |
|---|---|---|
| `LLM_TIMEOUT` | `240` | Seconds to wait for one provider answer. |
| `LLM_BUDGET_USD` | `2` | Soft spend cap per run; then built-in rules. |
| `VISION_MAX_FAILURES` | `60` | Failed tests the vision path may inspect (cost). |
| `OLLAMA_NUM_CTX` | `16384` | Local context window hint for Ollama. |

Timeouts and missing keys must surface as clear errors / rules fallback — never as invented pass rates.

## Visual, review, and integration caps

| Setting | Default | Role |
|---|---|---|
| `VISUAL_MAX_PAGES` | `100` | Visual comparisons per run. |
| `REVIEW_TIMEOUT_S` | `900` | How long a run waits for human review answers. |
| `JIRA_MAX_ISSUES` | `10` | Issues opened per run when Jira is configured. |
| `SERVER_START_TIMEOUT` | `180` | Seconds to wait for a local app under test to start. |

## What “performance work” is allowed later

- Re-measure with unchanged code first; keep evidence under `runs/` or `deep_validation/`.
- Prefer lowering soft budgets (`MAX_PAGES`, `CRAWL_TIME_LIMIT_MIN`, `TEST_WORKERS`) for large sites over silent scope expansion.
- Do not publish latency, pages/hour, or accuracy percentages unless counted from that run’s own files
  (`backend/metrics.py`, `backend/report_clarity.py`, reporting honesty in Phases 12–13).
- Known-truth benchmark metrics (`backend/qa_benchmark.py`) are labelled as precision / recall / answered
  expectations for the supplied cases only; `overall_accuracy_percent` stays unset unless a future live
  measurement fills it from real denominators.

## Related docs

- [README — Configure / Troubleshooting](../README.md)
- [DEPLOYMENT.md](../DEPLOYMENT.md) — Windows primary; Linux not a supported shared deploy
- [Clear setup and crawl audit](17_CLEAR_SETUP_AND_CRAWL_AUDIT.md) — exploration defaults and remaining coverage limits
- [STATUS.md](../STATUS.md) — implementation vs verification
