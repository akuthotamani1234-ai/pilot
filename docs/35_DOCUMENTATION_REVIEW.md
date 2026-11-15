# Documentation review — 14 November 2026

This review covers the repository's tracked Markdown and HTML documents, the new MCP configuration guide and this
review. Current product behavior is described by [README](../README.md), [STATUS](../STATUS.md),
[Android coverage](33_ANDROID_COVERAGE_WORKSPACE.md) and [MCP configuration](34_MCP_SHARED_CONFIGURATION.md).
Dated live runs retain their original measured counts, targets and limitations; they are not current acceptance results.

## Corrections

- Replaced visible legacy product branding with Qpilot across current guides, UI/launchers, package metadata,
  generated report headings and setup illustrations. Re-rendered all three Android guide PNGs from their HTML source.
  Generated GitHub branch/Jira labels and future demo-source labels also use Qpilot; existing APKs are unchanged.
- Documented the 12 MCP tools, shared account/provider/exploration/flow controls, private 15-minute prepared requests,
  explicit execution permission, idempotent startup and automatic local Android preparation.
- Corrected obsolete statements that forms/credentials, API/SQLite checks, hybrid support or automatic Appium startup
  were unavailable. Rewrote the functional test-mode guide to describe actual scope, safety and evidence.
- Marked historical deferral reports and old suite counts as dated evidence. Corrected MCP depth defaults and Android
  session-start timeout guidance. Removed fixed test counts from contributor instructions.
- Updated the project document index (Android/advanced QA/component inventory are present), regenerated the contract
  schema from the current model and migrated current example secret/database references to `QPILOT_*`.
- Checked local Markdown/HTML file links against the checkout. External URLs and live/cloud/device behavior are not
  certified by this file-link check. Setup illustrations are explicitly labelled illustrations, not execution proof.

## Compatibility identifiers

Legacy environment references, Python/JavaScript globals, wire headers, resource URI and device-lock/tool directory
names remain accepted where needed for existing installations and saved contracts. The fixture package
`com.blowai.demo` and observed historical APK labels remain identities/evidence for existing APKs.
On 15 November the checkout was renamed to `Qpilot`, the controlled APK file to
`qpilot-controlled-demo-v1.2.apk`, and the Java source package to `com.qpilot.demo`.
The prebuilt APK retains its original package and checksum; future source builds use the new package.
Current UI examples use Qpilot references.
See [migration details](34_MCP_SHARED_CONFIGURATION.md#qpilot-naming-and-compatibility).

The workspace's `review_artifacts/` folder retains the report/video review and distinct report-rebuild outputs.
Its README explains their purpose. The superseded implementation prompt and unused Clock retry configuration
were removed on 15 November. These files are outside this Git repository.

The superseded UI review and advanced-QA deferral checklist were also removed; current operation and verification
are described by the maintained guides and `STATUS.md`. Their original text remains in Git history.

## Inventory

The inventory includes application HTML to cover product labels as well as operator documentation. A current guide
may contain dated verification subsections; those subsections preserve actual results rather than implying reruns.

| Document | Review role |
| --- | --- |
| [.github/copilot-instructions.md](../.github/copilot-instructions.md) | Current guide / reference |
| [ARCHITECTURE.md](../ARCHITECTURE.md) | Current guide / reference |
| [backend/README.md](../backend/README.md) | Current guide / reference |
| [CHANGELOG.md](../CHANGELOG.md) | Dated evidence; results preserved |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Current guide / reference |
| [deep_validation/06_test_evidence_index.md](../deep_validation/06_test_evidence_index.md) | Dated evidence; results preserved |
| [deep_validation/live_runs/android_real_tester_assessment_20261112.md](../deep_validation/live_runs/android_real_tester_assessment_20261112.md) | Dated evidence; results preserved |
| [deep_validation/live_runs/mcp_ai_assisted_test_20261112.md](../deep_validation/live_runs/mcp_ai_assisted_test_20261112.md) | Dated evidence; results preserved |
| [deep_validation/live_runs/sauce_ecommerce_android_assessment_20261112.md](../deep_validation/live_runs/sauce_ecommerce_android_assessment_20261112.md) | Dated evidence; results preserved |
| [deep_validation/README.md](../deep_validation/README.md) | Current guide / reference |
| [demo-apps/README.md](../demo-apps/README.md) | Current guide / reference |
| [DEPLOYMENT.md](../DEPLOYMENT.md) | Current guide / reference |
| [docs/15_MCP_INTEGRATION.md](../docs/15_MCP_INTEGRATION.md) | Current guide / reference |
| [docs/16_WORKFLOWS_AND_PRIVACY.md](../docs/16_WORKFLOWS_AND_PRIVACY.md) | Current guide / reference |
| [docs/17_CLEAR_SETUP_AND_CRAWL_AUDIT.md](../docs/17_CLEAR_SETUP_AND_CRAWL_AUDIT.md) | Current guide / reference |
| [docs/18_RESULTS_LAYOUT.md](../docs/18_RESULTS_LAYOUT.md) | Current guide / reference |
| [docs/20_MODAL_FORMS_AND_VERIFICATION.md](../docs/20_MODAL_FORMS_AND_VERIFICATION.md) | Current guide / reference |
| [docs/21_FEATURE_AUDIT_AND_LIVE_ANDROID.md](../docs/21_FEATURE_AUDIT_AND_LIVE_ANDROID.md) | Dated evidence; results preserved |
| [docs/22_APPIUM_TESTING_GUIDE.md](../docs/22_APPIUM_TESTING_GUIDE.md) | Current guide / reference |
| [docs/24_ANDROID_CHROME_AND_GUIDED_FLOWS.md](../docs/24_ANDROID_CHROME_AND_GUIDED_FLOWS.md) | Current guide / reference |
| [docs/26_ANDROID_DEMO_ERRORS_AND_PICTURE_GUIDE.md](../docs/26_ANDROID_DEMO_ERRORS_AND_PICTURE_GUIDE.md) | Current guide / reference |
| [docs/27_RUN_ANDROID_TESTS_YOURSELF.md](../docs/27_RUN_ANDROID_TESTS_YOURSELF.md) | Current guide / reference |
| [docs/28_APPIUM_RELIABILITY_AUDIT.md](../docs/28_APPIUM_RELIABILITY_AUDIT.md) | Dated evidence; results preserved |
| [docs/29_ANDROID_FEATURE_EXPANSION.md](../docs/29_ANDROID_FEATURE_EXPANSION.md) | Dated evidence; results preserved |
| [docs/30_TEST_LIKE_A_REAL_USER.md](../docs/30_TEST_LIKE_A_REAL_USER.md) | Current guide / reference |
| [docs/31_PERFORMANCE_AND_LIMITS.md](../docs/31_PERFORMANCE_AND_LIMITS.md) | Current guide / reference |
| [docs/31_QPILOT_EVIDENCE_WORKSPACE.md](../docs/31_QPILOT_EVIDENCE_WORKSPACE.md) | Current guide / reference |
| [docs/32_ANDROID_FORM_VALIDATION_AND_READINESS.md](../docs/32_ANDROID_FORM_VALIDATION_AND_READINESS.md) | Current guide / reference |
| [docs/33_ANDROID_COVERAGE_WORKSPACE.md](../docs/33_ANDROID_COVERAGE_WORKSPACE.md) | Current guide / reference |
| [docs/34_MCP_SHARED_CONFIGURATION.md](../docs/34_MCP_SHARED_CONFIGURATION.md) | Current guide / reference |
| [docs/android-testing-visual-guide.html](../docs/android-testing-visual-guide.html) | Current guide / reference |
| [frontend/android-testing-guide.html](../frontend/android-testing-guide.html) | UI / setup illustration; branding checked |
| [frontend/chat.html](../frontend/chat.html) | UI / setup illustration; branding checked |
| [frontend/qa-lab.html](../frontend/qa-lab.html) | UI / setup illustration; branding checked |
| [frontend/README.md](../frontend/README.md) | Current guide / reference |
| [project-docs/01_PRD.md](../project-docs/01_PRD.md) | Current guide / reference |
| [project-docs/02_ARCHITECTURE.md](../project-docs/02_ARCHITECTURE.md) | Current guide / reference |
| [project-docs/03_RULES.md](../project-docs/03_RULES.md) | Current guide / reference |
| [project-docs/04_DESIGN.md](../project-docs/04_DESIGN.md) | Current guide / reference |
| [project-docs/05_EXECUTION_PROCESS.md](../project-docs/05_EXECUTION_PROCESS.md) | Current guide / reference |
| [project-docs/06_INSTALLATION.md](../project-docs/06_INSTALLATION.md) | Current guide / reference |
| [project-docs/09_ARCHITECTURE_AND_DEMO.md](../project-docs/09_ARCHITECTURE_AND_DEMO.md) | Current guide / reference |
| [project-docs/11_RELIABLE_RESULTS.md](../project-docs/11_RELIABLE_RESULTS.md) | Dated evidence; results preserved |
| [project-docs/12_ANDROID.md](../project-docs/12_ANDROID.md) | Current guide / reference |
| [project-docs/13_ADVANCED_QA.md](../project-docs/13_ADVANCED_QA.md) | Current guide / reference |
| [project-docs/14_PAGE_COMPONENT_INVENTORY.md](../project-docs/14_PAGE_COMPONENT_INVENTORY.md) | Current guide / reference |
| [project-docs/accuracy/ats_baseline_explained.md](../project-docs/accuracy/ats_baseline_explained.md) | Dated evidence; results preserved |
| [project-docs/ANDROID_IMPLEMENTATION_REPORT.md](../project-docs/ANDROID_IMPLEMENTATION_REPORT.md) | Dated evidence; results preserved |
| [project-docs/README.md](../project-docs/README.md) | Current guide / reference |
| [README.md](../README.md) | Current guide / reference |
| [SECURITY.md](../SECURITY.md) | Current guide / reference |
| [STATUS.md](../STATUS.md) | Current guide / reference |
| [tests/android_demo/README.md](../tests/android_demo/README.md) | Current guide / reference |
| [tests/README.md](../tests/README.md) | Current guide / reference |
| [docs/35_DOCUMENTATION_REVIEW.md](35_DOCUMENTATION_REVIEW.md) | This review |
