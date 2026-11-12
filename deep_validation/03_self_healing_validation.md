# 03 — Self-healing validation

**Status: PARTIALLY VERIFIED · score: 6/10**

## Source inspected

- Web self-healing: `backend/agents/self_healing.py`, `backend/agents/executor.py`, `backend/agents/script_generator.py`.
- Android recovery: `backend/android_pipeline.py`, `backend/android_runtime.py`, `backend/android.py`.
- Safety checks: `validate_script()` in `backend/agents/script_generator.py`; Android generated-code AST checks in `backend/android_design.py`.

The intended rule is to repair element location while preserving the original assertion. Source has bounded attempts, rejects edits that weaken/change checks, and Android recovery requires a unique same-element candidate. A prior report records an emulator stale-locator injection that recovered without changing the assertion. These are source and historical-evidence claims, not a fresh full matrix.

## Controlled change matrix

| Change injected | Required outcome | Evidence/status in this audit |
|---|---|---|
| ID changes | Repair only if a unique same element is evidenced; retain original assertion | Historical unit coverage for unique recovery; this exact current scenario not freshly executed. |
| CSS class changes | Same as above | Not separately verified. |
| Accessible name changes | Require evidence that it is still the same target; otherwise ask/reject | Not separately verified. |
| Element moves in DOM | Repair only to a unique, same element; retain assertion | General uniqueness/recovery tests exist; exact current scenario not freshly executed. |
| Duplicate matching elements | Reject ambiguous candidate; do not select first | `logs/appium-final-regression.xml` includes passing `test_locator_recovery_requires_unique_same_element_and_keeps_assertions`; confidence medium for covered Android path. |
| Element disappears | Leave unresolved/failed or inconclusive; do not fabricate replacement | Bounded recovery source; exact end-to-end current run not performed. |
| Element behavior changes | Preserve failure of original expected behavior | Seeded defects remain failed in historical controlled Android run; not a selector-only recovery case. |
| Expected application result becomes wrong | Must continue failing; never “heal” the expected value | Historical `test_explicit_value_requirements_are_not_replaced_by_observed_wrong_values` and AST weakened-assertion tests pass in the 2026-11-08 regression XML. |

## Assertion-preservation report

- Historical test evidence: `logs/appium-final-regression.xml` has 46 `test_android_improvements` cases and 16 `test_native_accuracy` cases; all are recorded without failure/error. It includes tests named `test_locator_recovery_requires_unique_same_element_and_keeps_assertions`, `test_mobile_ast_validation_rejects_escapes_and_weakened_assertions[...]`, and `test_explicit_value_requirements_are_not_replaced_by_observed_wrong_values`.
- Historical controlled emulator: `docs/28_APPIUM_RELIABILITY_AUDIT.md` describes a stale-locator recovery probe and seeded app defects that continued to fail. Details are historical, dated 2026-11-08.
- Fresh execution: no new selector-healing scenario ran successfully in this validation. Full pytest was blocked by temp/subprocess permission failures; no connected Android device became available.
- A web-specific fresh execution comparing original/repaired test source and rerunning it was **not** completed.

**Pass/fail:** core preservation safeguards are historically verified; full requested selector matrix is not verified.  
**Confidence:** medium for guarded Android healing, low for general web healing and all selector-change types.  
**Limitation:** changed behavior is not a selector problem. Healing must never turn a changed application result into a pass.

## Next action

Rerun the self-healing unit and controlled-fixture tests in a working pytest environment. Add isolated cases only after the test environment can execute tests, and keep source snapshots/assertion diffs in `deep_validation/`.
