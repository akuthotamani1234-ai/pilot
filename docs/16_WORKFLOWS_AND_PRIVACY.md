# Workflow selection and privacy

Open ui.bat. After selecting Playwright or Appium, choose one of two workflows:

- **Standard testing:** configure the target, review test cases where supported, generate Python scripts, execute and review evidence/reports.
- **AI assistant through MCP:** connect an MCP client, approve its data access in Privacy & connections, prepare a task request, and paste it into that assistant. The existing Python engines perform the work and the UI follows MCP-started jobs.

There is no embedded general-purpose MCP assistant in the Studio. The request builder prepares text for your selected external client. It supports website URLs, installed Android packages and explicitly chosen trusted APK paths. Connecting or preparing a request does not start testing.

## Privacy defaults

Privacy & connections is available in the navigation and from the status button in the header.

**Local only** is the default, including when preferences are missing or invalid. Qpilot accepts rules or loopback Ollama, blocks cloud AI providers, and disables automatic Slack/Jira result sharing. Child workers receive the selected policy; cloud/integration credentials are blanked so their .env loader cannot restore them. The outbound AI request boundary independently checks the policy, including resumed/re-check workflows. Local model requests bypass environment proxies and refuse redirects.

This setting controls Qpilot's AI requests and automatic report sharing. The application under test, approved API/DB verification endpoints, package installation during setup and explicitly requested repository operations still involve their respective services. It is not a machine-wide network sandbox.

**Cloud assisted** requires explicit confirmation before saving. It enables selecting configured cloud providers. Page/DOM content, screenshots, results and logs may be shared with the selected model, approved assistant or configured report integration. Backend checks apply even when an API caller skips the UI; stale privacy mode values are rejected.

Privacy changes are locked while an active test or re-check is running. Stop it or wait before changing the workspace policy.

## MCP access is a separate approval

MCP data access is disabled by default in either privacy mode. The assistant can check the connection and the server can report presence without reading run data. Other MCP reads and starts require approval in the UI.

In local-only mode, approving MCP also requires the user's declaration that the assistant processes its tool data locally. A desktop client can use a cloud model; its installation location alone does not establish privacy. Qpilot cannot independently verify where an external assistant processes data. If unsure, leave MCP access disabled and use Standard testing with rules/local Ollama.

MCP tools cannot change the privacy policy. Policy settings are stored locally in .private/privacy.json and excluded from source checkpoints/version control. Only the user-facing Settings API can update them. Standard run authorization, production confirmation, target scope checks and device locks still apply.

The approved MCP client can read public run history and report sections. Existing credential redaction and private cookie/session-file exclusions remain in place; application content itself may still contain sensitive business data.

## Connection status

The MCP server reports its real process lifetime to the UI; tool registration alone performs no network calls. Status distinguishes:

- **Not connected:** no recent server heartbeat.
- **Access needs approval:** a server is online but MCP data access is blocked.
- **Server online:** the server is available and no assistant request has been observed yet.
- **Assistant available:** an assistant has contacted Qpilot and its server remains online.

Presence expires after 35 seconds without a heartbeat. Presence describes server availability, not test success or a guarantee about assistant processing location. The UI follows new running MCP jobs while the MCP workflow is selected.

Restart ui.bat and reconnect the MCP client after updating the code so both use the current policy enforcement.

## Shared configuration and private handoff

Both workflows use the same configuration controls and existing run engines. MCP preparation stores an exact,
expiring configuration in Studio memory; the assistant receives only its reference and a redacted review.
It does not receive the entered password, API key or authenticator secret. Preparing starts no automation.
`start_prepared_test` rechecks permission/privacy and launches the existing run path. UI changes revoke the current
reference; startup results are idempotent after success. See [the current flow](34_MCP_SHARED_CONFIGURATION.md).

## Verification status

Current automated checks and their limits are recorded in [STATUS](../STATUS.md). Browser configuration tests use
intercepted APIs; they do not establish live device, third-party MCP host or cloud-provider compatibility.
Historical live evidence is kept separately under `deep_validation/live_runs` with its original run scope and counts.
