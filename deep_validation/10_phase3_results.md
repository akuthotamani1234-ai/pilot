# Phase 3 results — AI test generation — 2026-11-10

## Scope

Phase 3 reviewed website test design, structured AI case validation, prompts, generated-case grounding, owner-authored test conversion, final case fields, and the script-generation grounding caller. The code change is additive and limited to unsupported exact quoted expected text. Existing case formats, rules-mode planning, APIs, and provider configuration are preserved.

## Finding and change

`backend/agents/test_design.py` already requests expectations grounded in crawler observations or owner requirements, validates structured case fields, rejects AI cases that reference missing features, and marks expectations explicitly prefixed `Exploratory:` as exploratory. However, it accepted an exact quoted message such as `"Order confirmed."` as a normal end-to-end expectation even when neither the crawler nor the owner supplied that text.

Added `_unsupported_expected_quote(...)` and used it in both `ai_flows(...)` and `my_test_cases(...)`:

- Exact quoted phrases in an AI expected result are checked against the crawler's site summary and owner-provided requirements/test text.
- If a phrase is unsupported, the case remains present, retains its original expectation, gets an explanatory `Exploratory:` prefix, and is classified as exploratory for reporting and execution semantics.
- Observed messages and phrases explicitly requested by the owner remain unchanged.
- Rules-only cases and unquoted expectations are not rewritten by this narrow guard.

This avoids turning one specific unsupported exact-message claim into a normal verified expectation. It does not prove the semantic correctness of every unquoted AI business assertion.

## Verification

Environment: Windows, Python 3.13.16, pytest 9.1.1. Tests used fresh isolated Windows Temp basetemps, `-B`, `-p no:cacheprovider`, and `PYTHONDONTWRITEBYTECODE=1`.

| Check | Result | Evidence |
|---|---|---|
| New unsupported expected-message regressions | Passed for AI website journeys and owner-authored tests; exact text absent from evidence/request is marked exploratory. | `phase3-ai-regression-focused.txt` |
| AI test-design, AI-grounding, and case-optimization regression files | 67 passed; no failures. | `phase3-ai-regression-focused.txt` |
| Final complete serial non-slow suite | 754 passed, 65 deselected in 1495.05s (24m55s); exit 0. | `phase3-pytest-nonslow-final.txt` |
| Ruff on changed source/tests | Passed. | `ruff check backend/agents/test_design.py tests/test_rules.py tests/test_testoptim_missing.py --no-cache` |

The first full non-slow run after the initial whole-site change passed 753 tests. An additional owner-authored test case was then covered, and the final full run above verifies the final code state.

The 287-entry Phase 0 SHA-256 manifest was rechecked: 277 entries are unchanged; the 10 expected differences are `backend/agents/discovery.py`, `backend/agents/test_design.py`, `tests/test_extensions.py`, `tests/test_big_store.py`, `tests/test_rules.py`, `tests/test_testoptim_missing.py`, `CHANGELOG.md`, `FEATURE_VERIFICATION_MATRIX.md`, `MASTER_TODO.md`, and `PROJECT_IMPLEMENTATION_STATUS.md`. No manifest entry is missing.

## Existing functionality reviewed

- Built-in planning already produces focused feature/control checks, journeys, positive and negative paths, form-data and boundary checks, navigation, authentication, and protected-action cases.
- Structured AI flows use discovered page/component summaries, observed behavior, and supplied requirements. The schema validates titles, steps, expected results, priority, pages, guest state, and test-data shape.
- `finalize_cases(...)` assigns stable unique IDs, page/feature references, preconditions, test-data references, pending result fields, evidence lists, and execution status fields.
- Generated scripts have a separate validation and grounding pass in `backend/agents/script_generator.py` and `backend/ai_grounding.py`.
- AI failures fall back to built-in rule-based tests; no live provider was contacted during this phase.

## Remaining limits and manual verification

- The exact-quote check is intentionally narrow. It does not semantically prove unquoted expectations, numeric business rules, or every claimed state transition. Use QA contracts or owner requirements for those expectations; otherwise they need human review.
- Mocked-provider tests establish deterministic handling of AI outputs, not the quality of a real OpenAI, Anthropic, Gemini, or Ollama response. Live provider calls require separate explicit authorization and applicable privacy/cost review.
- The broad test suite excludes 65 slow tests. The separate Phase 2 BigStore slow acceptance test passed; Android/device tests and UI E2E are outside this phase.

## Phase gate

Phase 3 is complete for the verified change and regression scope above. Phase 4 (Playwright/Pytest execution improvements) has not started and requires owner approval.
