# Local MCP implementation status

Implemented: official SDK 2.3.0 stdio server, 11 tools, workflow resource, loopback API adapter, shared worker controls,
bounded logs/report sections, paginated page/component catalogs, streamed APK uploads, website-only source validation,
and a separate discovery-only graph/report. Added optional dependency pins, Windows setup/launcher, generated client
example, integration documentation and prepared regression checks.

Checked without automation: Python syntax/in-memory compilation, SDK tool/schema registration (11 tools),
client path existence, dependency consistency (pip check: no broken requirements).
No test tool or MCP protocol session was invoked during these checks.

Still deferred by user request: prepared regression checks, MCP client initialize/list/call round trips, live discovery,
full Playwright/Appium execution and regression verification. Existing historical test results do not verify this new code.

Normal app launch: ui.bat.
Optional first-time MCP setup: setup/install-mcp.bat.
Generated client example: mcp-config.local.json (merge into the selected client's server settings).
Guide: docs/15_MCP_INTEGRATION.md.
No IDE/global client settings were changed.

## Workflow/privacy update

Added both workflow cards after engine selection, a Privacy & connections dialog with local-only defaults, explicit cloud and MCP consent, backend enforcement, worker policy snapshots, outbound AI safeguards, expiring MCP presence, request/configuration preparation and UI monitoring of MCP-started jobs. Privacy cannot change during active runs/re-checks. Assistant processing location is a user declaration, not independently verified.

Isolated desktop/mobile UI previews passed with mocked APIs. Python/JS syntax and registration checks passed. The new tests/test_privacy_workflow.py regressions and all live execution remain deferred. No user privacy preferences or global client settings were changed during implementation.

## Phase 10 offline slice — AI provider + MCP error handling

Additive offline hardening (no live provider or MCP client sessions):

- Clearer `LLMError` messages for missing API keys, timeouts, connection failures, HTTP 401/403/404/429/5xx,
  invalid provider JSON, unexpected response shapes, and structured-response validation after a corrective retry.
- Cloud providers are refused before any outbound call when the API key is blank; failures remain `LLMError` so
  existing rules/template fallback paths keep working.
- MCP bridge maps invalid JSON replies, timeouts, HTTP 400/403/404/409/413/5xx and disabled privacy access to
  actionable `BridgeError` text (secrets still redacted). Corrupt report JSON returns HTTP 422 instead of invented data.

Offline unit/protocol-ish coverage: `tests/test_llm_provider_errors.py` and extended `tests/test_mcp_integration.py`.
Still not claimed: live MCP initialize/list/call round trips, real OpenAI/Gemini/Anthropic/Ollama calls, or full UI runs.
