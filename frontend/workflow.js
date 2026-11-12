/* Shared workflow selection and server-enforced privacy settings. No automation starts here. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const state = { engine: "web", workflow: "standard", busy: false, loaded: false, privacy: null,
    connection: null, lastAttachedId: null, targets: { web: "", android: "" } };
  let focusBeforePrivacy = null;

  function detail(data, fallback) {
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((item) => item.msg || "").join(" ");
    return fallback;
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(detail(data, "The workspace could not complete this request."));
    return data;
  }

  function render() {
    document.body.dataset.workflow = state.workflow;
    $("standardWorkflowBtn").classList.toggle("selected", state.workflow === "standard");
    $("mcpWorkflowBtn").classList.toggle("selected", state.workflow === "mcp");
    $("standardWorkflowBtn").setAttribute("aria-pressed", String(state.workflow === "standard"));
    $("mcpWorkflowBtn").setAttribute("aria-pressed", String(state.workflow === "mcp"));
    $("standardWorkflowBtn").disabled = state.busy;
    $("mcpWorkflowBtn").disabled = state.busy;
    $("mcpPanel").hidden = state.workflow !== "mcp";
    $("copyMcpRequest").disabled = state.busy;
    const label = !state.loaded ? "Privacy unavailable" : state.privacy.mode === "local" ? "Local only" : "Cloud assisted";
    $("privacyStatusBtn").textContent = label;
    $("workflowPrivacyBadge").textContent = label;
    $("workflowPrivacyBadge").dataset.mode = state.loaded ? state.privacy.mode : "unknown";
    $("privacySave").disabled = state.busy || !state.loaded;
    $("privacyForm").querySelectorAll("input").forEach((input) => { input.disabled = state.busy || !state.loaded; });
    const android = state.engine === "android";
    const apk = android && $("mcpAndroidSource").value === "apk";
    const mobileWeb = android && $("mcpAndroidSource").value === "web";
    $("mcpAndroidSourceLabel").hidden = !android;
    $("mcpAndroidSource").hidden = !android;
    $("mcpTargetLabel").textContent = mobileWeb ? "Website URL in Android Chrome" : android ? (apk ? "Trusted APK path" : "Installed Android package") : "Website URL";
    $("mcpTarget").placeholder = android && !mobileWeb ? (apk ? "C:\\Apps\\my-test-app.apk" : "com.example.myapp") : "https://your-test-site.example";
    $("mcpTask").placeholder = android ? "Explore screens and verify the approved navigation expectations."
      : "List dashboard menus and dropdowns, then test the approved login flow.";
    updateAndroidProviders();
    renderConnection();
  }

  function updateAndroidProviders() {
    const select = $("androidProvider");
    if (!select) return;
    Array.from(select.options).forEach((option) => {
      option.disabled = !!option.value && !providerAllowed(option.value);
    });
    if (select.value && !providerAllowed(select.value)) {
      select.value = "ollama";
      $("androidModel").value = "";
    }
    select.options[0].textContent = state.loaded && state.privacy.mode === "cloud"
      ? "Use configured provider" : "Use local configuration";
  }

  function providerAllowed(provider) {
    return state.loaded && state.privacy.allowed_providers.includes(provider);
  }

  async function loadPrivacy() {
    try {
      state.privacy = await api("/api/settings/privacy");
      state.loaded = true;
      render();
      window.dispatchEvent(new CustomEvent("blowai:privacychange", { detail: state.privacy }));
      return true;
    } catch (error) {
      state.loaded = false;
      $("privacyMessage").textContent = error.message + " Start ui.bat and reopen Settings.";
      render();
      return false;
    }
  }

  function privacyFields(event) {
    const cloud = $("privacyCloud").checked;
    $("privacyCloudConsentField").hidden = !cloud;
    $("privacyLocalAssistantField").hidden = cloud || !$("privacyAllowMcp").checked;
    if (event && !state.busy) $("privacyMessage").textContent = "Save to apply these settings to new runs.";
  }

  async function openPrivacy() {
    focusBeforePrivacy = document.activeElement;
    $("privacyModal").hidden = false;
    document.body.classList.add("privacy-open");
    await loadPrivacy();
    if (state.loaded) {
      const p = state.privacy;
      $("privacyLocal").checked = p.mode === "local";
      $("privacyCloud").checked = p.mode === "cloud";
      $("privacyCloudConsent").checked = p.cloud_consent;
      $("privacyAllowMcp").checked = p.allow_mcp;
      $("privacyLocalAssistant").checked = p.local_assistant_confirmed;
      $("privacyMessage").textContent = state.busy
        ? "A test is running. You can review privacy now and change it after the run stops."
        : "Local only is the default. MCP access requires approval of the assistant you connect.";
    }
    privacyFields();
    $("privacyClose").focus();
  }

  function closePrivacy() {
    $("privacyModal").hidden = true;
    document.body.classList.remove("privacy-open");
    if (focusBeforePrivacy && focusBeforePrivacy.isConnected) focusBeforePrivacy.focus();
  }

  async function savePrivacy(event) {
    event.preventDefault();
    if (state.busy || !state.loaded) return;
    const cloud = $("privacyCloud").checked;
    const allow = $("privacyAllowMcp").checked;
    if (cloud && !$("privacyCloudConsent").checked) {
      $("privacyMessage").textContent = "Confirm the data-sharing explanation before enabling Cloud assisted.";
      $("privacyCloudConsent").focus();
      return;
    }
    if (!cloud && allow && !$("privacyLocalAssistant").checked) {
      $("privacyMessage").textContent = "Confirm that your MCP assistant processes data locally, or leave MCP access off.";
      $("privacyLocalAssistant").focus();
      return;
    }
    $("privacySave").disabled = true;
    try {
      state.privacy = await api("/api/settings/privacy", { method: "PUT",
        headers: { "Content-Type": "application/json", "X-Agentic-QA": "1" },
        body: JSON.stringify({ mode: cloud ? "cloud" : "local", cloud_consent: cloud,
          allow_mcp: allow, local_assistant_confirmed: !cloud && allow }) });
      state.loaded = true;
      render();
      window.dispatchEvent(new CustomEvent("blowai:privacychange", { detail: state.privacy }));
      closePrivacy();
      loadConnection();
    } catch (error) {
      $("privacyMessage").textContent = error.message;
      $("privacySave").disabled = false;
    }
  }

  function renderConnection() {
    const status = $("mcpConnectionStatus"), note = $("mcpConnectionNote");
    const c = state.connection;
    status.className = "mcp-state";
    if (!c) {
      status.textContent = "Connection not checked";
      note.textContent = "Start the UI and connect your MCP assistant using the configuration below.";
      return;
    }
    const allowed = state.loaded && state.privacy.mcp_allowed;
    if (!c.server_online) {
      status.textContent = "Not connected";
      note.textContent = "Connect an MCP client to this workspace. Copy the configuration below; connecting does not start a test.";
    } else if (!allowed) {
      status.textContent = "Access needs approval";
      status.classList.add("pending");
      note.textContent = "The MCP server is online. Open Privacy settings to approve your assistant before it can read results or start tests.";
    } else if (c.assistant_active) {
      status.textContent = "Assistant available";
      status.classList.add("ready");
      note.textContent = "Your assistant has reached Blow AI and its server is online. Send the prepared request in that assistant; runs appear here.";
    } else {
      status.textContent = "Server online";
      note.textContent = "The MCP server is online and awaiting an assistant request. Ask your assistant to check the Blow AI connection.";
    }
  }

  async function loadConnection() {
    try {
      state.connection = await api("/api/mcp/connection");
      renderConnection();
      if (state.workflow === "mcp" && !state.busy) {
        const latest = await api("/api/runs/latest");
        if (latest && latest.workflow === "mcp" && latest.status === "running"
            && latest.id !== state.lastAttachedId) {
          state.lastAttachedId = latest.id;
          window.dispatchEvent(new CustomEvent("blowai:mcpjob", { detail: latest }));
        }
      }
    } catch (_) {
      state.connection = null;
      renderConnection();
    }
  }

  async function copyText(text) {
    try {
      if (navigator.clipboard) { await navigator.clipboard.writeText(text); return true; }
    } catch (_) {}
    return false;
  }

  async function copyConfig() {
    $("mcpPanelMessage").textContent = "Preparing configuration…";
    try {
      const text = JSON.stringify(await api("/api/mcp/config"), null, 2);
      $("mcpConfigText").textContent = text;
      $("mcpConfigText").hidden = false;
      const copied = await copyText(text);
      $("mcpPanelMessage").textContent = copied
        ? "Configuration copied. Add it to your MCP client's server settings and reconnect."
        : "Configuration is shown above. Select and copy it into your MCP client's server settings.";
    } catch (error) { $("mcpPanelMessage").textContent = error.message; }
  }

  async function prepareRequest() {
    const target = $("mcpTarget").value.trim(), task = $("mcpTask").value.trim();
    if (!target || !task) {
      $("mcpPanelMessage").textContent = "Enter a target and describe what you want to check.";
      return;
    }
    if (state.engine === "web" || $("mcpAndroidSource").value === "web") {
      try {
        const url = new URL(target);
        if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error();
      } catch (_) {
        $("mcpPanelMessage").textContent = "Enter a complete website URL without an embedded password.";
        return;
      }
    } else if ($("mcpAndroidSource").value === "apk" && !/\.apk$/i.test(target)) {
      $("mcpPanelMessage").textContent = "Enter the path to a trusted .apk on this computer.";
      return;
    } else if ($("mcpAndroidSource").value === "installed" && !/^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$/.test(target)) {
      $("mcpPanelMessage").textContent = "Enter an installed Android package, such as com.example.myapp.";
      return;
    }
    const text = "Use Blow AI with " + (state.engine === "web" ? "Playwright for " : $("mcpAndroidSource").value === "web" ? "Appium Android Chrome for " : $("mcpAndroidSource").value === "apk" ? "Appium for trusted APK " : "Appium for installed package ")
      + target + ".\nTask: " + task
      + "\nCheck the current privacy settings and connection first. Confirm my permission and scope before starting."
      + "\nUse approved expected results; report untested components and discovery limits. Show progress and the final report in Blow AI.";
    $("mcpRequestPreview").value = text;
    $("mcpRequestPreview").hidden = false;
    const copied = await copyText(text);
    $("mcpPanelMessage").textContent = copied
      ? "Request prepared and copied. Review it, then paste it into your connected assistant."
      : "Request prepared below. Review and copy it into your connected assistant.";
  }

  function setEngine(engine) {
    if (engine !== state.engine) {
      state.targets[state.engine] = $("mcpTarget").value;
      state.engine = engine;
      $("mcpTarget").value = state.targets[engine];
      $("mcpRequestPreview").hidden = true;
    }
    render();
  }

  function setWorkflow(workflow, force) {
    if (state.busy && !force) return;
    state.workflow = workflow === "mcp" ? "mcp" : "standard";
    render();
    if (state.workflow === "mcp") loadConnection();
    window.dispatchEvent(new CustomEvent("blowai:workflowchange", { detail: state.workflow }));
  }

  ["privacyStatusBtn", "privacySettingsBtn", "mcpPrivacyBtn"].forEach((id) => $(id).addEventListener("click", openPrivacy));
  ["privacyClose", "privacyCancel"].forEach((id) => $(id).addEventListener("click", closePrivacy));
  $("privacyModal").addEventListener("click", (event) => { if (event.target === $("privacyModal")) closePrivacy(); });
  $("privacyForm").addEventListener("submit", savePrivacy);
  ["privacyLocal", "privacyCloud", "privacyAllowMcp", "privacyCloudConsent", "privacyLocalAssistant"].forEach((id) => $(id).addEventListener("change", privacyFields));
  $("standardWorkflowBtn").addEventListener("click", () => setWorkflow("standard"));
  $("mcpWorkflowBtn").addEventListener("click", () => setWorkflow("mcp"));
  $("mcpAndroidSource").addEventListener("change", () => {
    $("mcpTarget").value = "";
    $("mcpRequestPreview").hidden = true;
    render();
  });
  $("copyMcpConfig").addEventListener("click", copyConfig);
  $("copyMcpRequest").addEventListener("click", prepareRequest);
  document.addEventListener("keydown", (event) => {
    if ($("privacyModal").hidden) return;
    if (event.key === "Escape") { closePrivacy(); return; }
    if (event.key === "Tab") {
      const focusable = Array.from($("privacyModal").querySelectorAll("button:not(:disabled),input:not(:disabled),[tabindex='0']"))
        .filter((item) => item.getClientRects().length);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });

  window.BlowAIWorkflow = {
    ready: null, providerAllowed, setEngine, setWorkflow,
    setBusy(value) { state.busy = !!value; render(); },
    get workflow() { return state.workflow; },
    get mode() { return state.loaded ? state.privacy.mode : null; },
    get loaded() { return state.loaded; },
    openPrivacy,
  };
  window.BlowAIWorkflow.ready = loadPrivacy();
  loadConnection();
  window.setInterval(() => { if (state.workflow === "mcp" && !document.hidden) loadConnection(); }, 5000);
})();
