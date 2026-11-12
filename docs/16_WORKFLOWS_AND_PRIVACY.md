# Workflow selection and privacy

Open ui.bat. After selecting Playwright or Appium, choose one of two workflows:

- **Standard testing:** configure the target, review test cases where supported, generate Python scripts, execute and review evidence/reports.
- **AI assistant through MCP:** connect an MCP client, approve its data access in Privacy & connections, prepare a task request, and paste it into that assistant. The existing Python engines perform the work and the UI follows MCP-started jobs.

There is no embedded general-purpose MCP assistant in the Studio. The request builder prepares text for your selected external client. It supports website URLs, installed Android packages and explicitly chosen trusted APK paths. Connecting or preparing a request does not start testing.

## Privacy defaults

Privacy & connections is available in the navigation and from the status button in the header.

**Local only** is the default, including when preferences are missing or invalid. Blow AI accepts rules or loopback Ollama, blocks cloud AI providers, and disables automatic Slack/Jira result sharing. Child workers receive the selected policy; cloud/integration credentials are blanked so their .env loader cannot restore them. The outbound AI request boundary independently checks the policy, including resumed/re-check workflows. Local model requests bypass environment proxies and refuse redirects.

This setting controls Blow AI's AI requests and automatic report sharing. The application under test, approved API/DB verification endpoints, package installation during setup and explicitly requested repository operations still involve their respective services. It is not a machine-wide network sandbox.

**Cloud assisted** requires explicit confirmation before saving. It enables selecting configured cloud providers. Page/DOM content, screenshots, results and logs may be shared with the selected model, approved assistant or configured report integration. Backend checks apply even when an API caller skips the UI; stale privacy mode values are rejected.

Privacy changes are locked while an active test or re-check is running. Stop it or wait before changing the workspace policy.

## MCP access is a separate approval

MCP data access is disabled by default in either privacy mode. The assistant can check the connection and the server can report presence without reading run data. Other MCP reads and starts require approval in the UI.

In local-only mode, approving MCP also requires the user's declaration that the assistant processes its tool data locally. A desktop client can use a cloud model; its installation location alone does not establish privacy. Blow AI cannot independently verify where an external assistant processes data. If unsure, leave MCP access disabled and use Standard testing with rules/local Ollama.

MCP tools cannot change the privacy policy. Policy settings are stored locally in .private/privacy.json and excluded from source checkpoints/version control. Only the user-facing Settings API can update them. Standard run authorization, production confirmation, target scope checks and device locks still apply.

The approved MCP client can read public run history and report sections. Existing credential redaction and private cookie/session-file exclusions remain in place; application content itself may still contain sensitive business data.

## Connection status

The MCP server reports its real process lifetime to the UI; tool registration alone performs no network calls. Status distinguishes:

- **Not connected:** no recent server heartbeat.
- **Access needs approval:** a server is online but MCP data access is blocked.
- **Server online:** the server is available and no assistant request has been observed yet.
- **Assistant available:** an assistant has contacted Blow AI and its server remains online.

Presence expires after 35 seconds without a heartbeat. Presence describes server availability, not test success or a guarantee about assistant processing location. The UI follows new running MCP jobs while the MCP workflow is selected.

Restart ui.bat and reconnect the MCP client after updating the code so both use the current policy enforcement.

## Verification status

Checked: Python in-memory compilation, JavaScript syntax, SDK registration, route registration, HTML IDs, and isolated desktop/mobile previews with every API request intercepted. The preview uses fixture devices and settings; it performs no actual device checks, backend writes, MCP protocol sessions or test runs.

Prepared for the later verification stage:

    .venv\Scripts\python.exe -B -m pytest tests/test_privacy_workflow.py tests/test_mcp_integration.py -q

These regression checks and live Playwright/Appium/MCP verification remain deferred at the user's request.
