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

  function androidSource() {
    return ($("mcpAndroidSource") && $("mcpAndroidSource").value) || "apk";
  }

  function updateMcpTargetLabel() {
    const android = state.engine === "android";
    const source = androidSource();
    const mobileWeb = android && source === "web";
    const apk = android && source === "apk";
    const label = $("mcpTargetLabel");
    const input = $("mcpTarget");
    if (!label || !input) return;
    // Set label before paint when switching engines so "Website URL" does not flash on Android MCP.
    label.textContent = mobileWeb ? "Website URL in Android Chrome"
      : android ? (apk ? "Trusted APK path" : "Installed Android package")
      : "Website URL";
    input.placeholder = android && !mobileWeb
      ? (apk ? "/path/to/app.apk" : "com.example.myapp")
      : "https://your-test-site.example";
  }

  function render() {
    document.body.dataset.workflow = state.workflow;
    $("standardWorkflowBtn").classList.toggle("selected", state.workflow === "standard");
    $("mcpWorkflowBtn").classList.toggle("selected", state.workflow === "mcp");
    $("standardWorkflowBtn").setAttribute("aria-pressed", String(state.workflow === "standard"));
    $("mcpWorkflowBtn").setAttribute("aria-pressed", String(state.workflow === "mcp"));
    $("standardWorkflowBtn").disabled = state.busy;
    $("mcpWorkflowBtn").disabled = state.busy;
    $("copyMcpRequest").disabled = state.busy;
    const label = !state.loaded ? "Privacy unavailable" : state.privacy.mode === "local" ? "Local only" : "Cloud assisted";
    $("privacyStatusBtn").textContent = label;
    $("workflowPrivacyBadge").textContent = label;
    $("workflowPrivacyBadge").dataset.mode = state.loaded ? state.privacy.mode : "unknown";
    $("privacySave").disabled = state.busy || !state.loaded;
    $("privacyForm").querySelectorAll("input").forEach((input) => { input.disabled = state.busy || !state.loaded; });
    const android = state.engine === "android";
    const source = androidSource();
    const installed = android && source === "installed";
    $("mcpPanel").hidden = state.workflow !== "mcp";
    $("mcpAndroidSourceLabel").hidden = !android;
    $("mcpAndroidSource").hidden = !android;
    $("mcpAndroidControls").hidden = !android;
    if ($("mcpAndroidActivityLabel")) $("mcpAndroidActivityLabel").hidden = !installed;
    if ($("mcpAndroidActivity")) $("mcpAndroidActivity").hidden = !installed;
    updateMcpTargetLabel();
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

  async function refreshMcpAndroidEnvironment() {
    const note = $("mcpAndroidEnvNote");
    const device = $("mcpAndroidDevice");
    const appium = ($("mcpAndroidAppiumUrl") && $("mcpAndroidAppiumUrl").value.trim()) || "http://127.0.0.1:4723";
    if (!note || !device) return;
    const previousDevice = device.value;
    const previousAvd = device.selectedOptions[0]?.dataset.avd || "";
    note.textContent = "Checking Android SDK, Java, Appium and connected devices…";
    device.replaceChildren(new Option("Checking devices…", ""));
    try {
      const response = await fetch("/api/android/environment?appium_url=" + encodeURIComponent(appium));
      const data = await response.json();
      if (!response.ok) throw new Error(detail(data, "Could not check the Android environment."));
      device.replaceChildren(new Option("Choose a device", ""));
      (data.devices || []).forEach((item) => {
        const label = `${item.device_id} · ${item.status}${item.details ? " · " + item.details : ""}`;
        const option = new Option(label, item.device_id);
        option.disabled = item.status !== "device";
        option.dataset.avd = item.avd_name || "";
        device.add(option);
      });
      const connectedNames = new Set((data.devices || []).filter((item) => item.status === "device").map((item) => item.avd_name));
      (data.emulators || []).filter((item) => !connectedNames.has(item.name)).forEach((item) => {
        const option = new Option(`${item.name} · start emulator automatically`, item.device_id);
        option.dataset.avd = item.name;
        device.add(option);
      });
      if (previousDevice && [...device.options].some((option) => option.value === previousDevice && !option.disabled)) {
        device.value = previousDevice;
      } else if (previousAvd && [...device.options].some((option) => option.dataset.avd === previousAvd && !option.disabled)) {
        device.value = [...device.options].find((option) => option.dataset.avd === previousAvd && !option.disabled).value;
      } else {
        const selectable = [...device.options].filter((option) => option.value && !option.disabled);
        if (selectable.length === 1) device.value = selectable[0].value;
      }
      if (data.ok) note.textContent = "Android tools and a device are ready. Appium stays local to this computer.";
      else if (data.can_start_emulator) {
        note.textContent = "Choose an emulator. Your assistant can start it when the prepared request runs.";
      } else {
        note.textContent = (data.errors || ["Android environment is not ready."]).join(" ")
          + " Start Appium with `appium --address 127.0.0.1`, connect a device, then refresh.";
      }
    } catch (error) {
      note.textContent = error.message || "Could not check the Android environment.";
      device.replaceChildren(new Option("Refresh device status first", ""));
    }
  }

  function syncFromStandard() {
    if (state.engine === "web") {
      const msg = $("msg");
      if (msg && msg.value.trim()) {
        state.targets.web = msg.value.trim();
        if ($("mcpTarget")) $("mcpTarget").value = state.targets.web;
      }
      return;
    }
    const mode = $("androidMode");
    if (mode && $("mcpAndroidSource")) {
      const value = mode.value === "web" || mode.value === "installed" || mode.value === "apk" ? mode.value : "apk";
      $("mcpAndroidSource").value = value;
    }
    const source = androidSource();
    if (source === "web" && $("androidUrl") && $("androidUrl").value.trim()) {
      $("mcpTarget").value = $("androidUrl").value.trim();
    } else if (source === "installed" && $("androidPackage") && $("androidPackage").value.trim()) {
      $("mcpTarget").value = $("androidPackage").value.trim();
    } else if (source === "apk") {
      // MCP keeps a path string (not a file upload). Prefer an existing MCP path; else neutral placeholder.
      if (!($("mcpTarget").value || "").trim() || !/\.apk$/i.test($("mcpTarget").value)) {
        $("mcpTarget").value = "/path/to/app.apk";
      }
    }
    if ($("androidAppiumUrl") && $("mcpAndroidAppiumUrl")) {
      $("mcpAndroidAppiumUrl").value = $("androidAppiumUrl").value || "http://127.0.0.1:4723";
    }
    if ($("androidActivity") && $("mcpAndroidActivity")) {
      $("mcpAndroidActivity").value = $("androidActivity").value || "";
    }
    if ($("androidTestBuild") && $("mcpAndroidTestBuild")) {
      $("mcpAndroidTestBuild").checked = !!$("androidTestBuild").checked;
    }
    if ($("androidAuthorized") && $("mcpAndroidAuthorized")) {
      $("mcpAndroidAuthorized").checked = !!$("androidAuthorized").checked;
    }
    if ($("androidDevice") && $("mcpAndroidDevice") && $("androidDevice").value) {
      const std = $("androidDevice");
      const mcp = $("mcpAndroidDevice");
      let option = [...mcp.options].find((item) => item.value === std.value);
      if (!option && std.value) {
        option = new Option(std.selectedOptions[0]?.textContent || std.value, std.value);
        option.dataset.avd = std.selectedOptions[0]?.dataset.avd || "";
        mcp.add(option);
      }
      if (option) mcp.value = std.value;
    }
    state.targets.android = $("mcpTarget").value;
  }

  function syncToStandard() {
    if (state.engine === "web") {
      const target = ($("mcpTarget") && $("mcpTarget").value.trim()) || "";
      if (target && $("msg") && !$("msg").disabled) $("msg").value = target;
      state.targets.web = target;
      return;
    }
    const source = androidSource();
    if ($("androidMode")) $("androidMode").value = source;
    const target = ($("mcpTarget") && $("mcpTarget").value.trim()) || "";
    if (source === "web" && $("androidUrl")) $("androidUrl").value = target;
    else if (source === "installed" && $("androidPackage")) $("androidPackage").value = target;
    if ($("androidAppiumUrl") && $("mcpAndroidAppiumUrl")) {
      $("androidAppiumUrl").value = $("mcpAndroidAppiumUrl").value || "http://127.0.0.1:4723";
    }
    if ($("androidActivity") && $("mcpAndroidActivity")) {
      $("androidActivity").value = $("mcpAndroidActivity").value || "";
    }
    if ($("androidTestBuild") && $("mcpAndroidTestBuild")) {
      $("androidTestBuild").checked = !!$("mcpAndroidTestBuild").checked;
    }
    if ($("androidAuthorized") && $("mcpAndroidAuthorized")) {
      $("androidAuthorized").checked = !!$("mcpAndroidAuthorized").checked;
    }
    state.targets.android = target;
    if (typeof window.BlowAIChat !== "undefined" && window.BlowAIChat.updateAndroidFields) {
      window.BlowAIChat.updateAndroidFields();
    } else if ($("androidMode")) {
      $("androidMode").dispatchEvent(new Event("change"));
    }
  }

  function buildAndroidPrepareText(target, task) {
    const source = androidSource();
    const device = ($("mcpAndroidDevice") && $("mcpAndroidDevice").value.trim()) || "<device_id>";
    const appium = ($("mcpAndroidAppiumUrl") && $("mcpAndroidAppiumUrl").value.trim()) || "http://127.0.0.1:4723";
    const activity = ($("mcpAndroidActivity") && $("mcpAndroidActivity").value.trim()) || "";
    const testBuild = !!($("mcpAndroidTestBuild") && $("mcpAndroidTestBuild").checked);
    const lines = [
      "Use Blow AI MCP for Android Appium testing.",
      "Task: " + task,
      "1. Call get_android_environment with appium_url=" + appium + ".",
      "2. After confirming readiness and my permission, call start_android_test with:",
      "   - device_id=" + device,
      "   - app_mode=" + source,
      source === "apk" ? "   - apk_path=" + target
        : source === "web" ? "   - start_url=" + target
        : "   - package_name=" + target,
      "   - authorized=true",
      "   - appium_url=" + appium,
      "   - test_build=" + (testBuild ? "true" : "false"),
    ];
    if (source === "installed" && activity) lines.push("   - app_activity=" + activity);
    lines.push("Check privacy settings and connection first. Confirm my permission and scope before starting.");
    lines.push("Use approved expected results; report untested components and discovery limits. Show progress and the final report in Blow AI Studio.");
    return lines.join("\n");
  }

  async function prepareRequest() {
    const target = $("mcpTarget").value.trim(), task = $("mcpTask").value.trim();
    if (!target || !task) {
      $("mcpPanelMessage").textContent = "Enter a target and describe what you want to check.";
      return;
    }
    if (state.engine === "android") {
      if (!$("mcpAndroidAuthorized") || !$("mcpAndroidAuthorized").checked) {
        $("mcpPanelMessage").textContent = "Confirm ownership / permission before preparing the Android request.";
        $("mcpAndroidAuthorized").focus();
        return;
      }
      if (!$("mcpAndroidDevice") || !$("mcpAndroidDevice").value) {
        $("mcpPanelMessage").textContent = "Choose an Android device (Refresh if the list is empty).";
        return;
      }
    }
    if (state.engine === "web" || androidSource() === "web") {
      try {
        const url = new URL(target);
        if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error();
      } catch (_) {
        $("mcpPanelMessage").textContent = "Enter a complete website URL without an embedded password.";
        return;
      }
    } else if (androidSource() === "apk" && !/\.apk$/i.test(target)) {
      $("mcpPanelMessage").textContent = "Enter the path to a trusted .apk on this computer (for example /path/to/app.apk).";
      return;
    } else if (androidSource() === "installed" && !/^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$/.test(target)) {
      $("mcpPanelMessage").textContent = "Enter an installed Android package, such as com.example.myapp.";
      return;
    }
    const text = state.engine === "android"
      ? buildAndroidPrepareText(target, task)
      : ("Use Blow AI with Playwright for " + target + ".\nTask: " + task
        + "\nCheck the current privacy settings and connection first. Confirm my permission and scope before starting."
        + "\nUse approved expected results; report untested components and discovery limits. Show progress and the final report in Blow AI.");
    $("mcpRequestPreview").value = text;
    $("mcpRequestPreview").hidden = false;
    const copied = await copyText(text);
    $("mcpPanelMessage").textContent = copied
      ? "Request prepared and copied. Review it, then paste it into your connected assistant."
      : "Request prepared below. Review and copy it into your connected assistant.";
  }

  function setEngine(engine) {
    const next = engine === "android" ? "android" : "web";
    if (next !== state.engine) {
      state.targets[state.engine] = $("mcpTarget").value;
      state.engine = next;
      updateMcpTargetLabel();  // before restoring value / paint
      $("mcpTarget").value = state.targets[next] || "";
      $("mcpRequestPreview").hidden = true;
      if (state.workflow === "mcp") syncFromStandard();
    }
    render();
    if (state.workflow === "mcp" && state.engine === "android") refreshMcpAndroidEnvironment();
  }

  function setWorkflow(workflow, force) {
    if (state.busy && !force) return;
    const next = workflow === "mcp" ? "mcp" : "standard";
    if (next === "mcp" && state.workflow !== "mcp") syncFromStandard();
    if (next === "standard" && state.workflow === "mcp") syncToStandard();
    state.workflow = next;
    render();
    if (state.workflow === "mcp") {
      loadConnection();
      if (state.engine === "android") refreshMcpAndroidEnvironment();
    }
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
    const source = androidSource();
    if (source === "apk" && !/\.apk$/i.test(($("mcpTarget").value || "").trim())) {
      $("mcpTarget").value = "/path/to/app.apk";
    } else if (source !== "apk") {
      $("mcpTarget").value = "";
    }
    $("mcpRequestPreview").hidden = true;
    updateMcpTargetLabel();
    render();
  });
  $("mcpAndroidEnvRefresh").addEventListener("click", refreshMcpAndroidEnvironment);
  $("mcpAndroidAppiumUrl").addEventListener("change", refreshMcpAndroidEnvironment);
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
    ready: null, providerAllowed, setEngine, setWorkflow, syncFromStandard, syncToStandard,
    refreshMcpAndroidEnvironment,
    setBusy(value) { state.busy = !!value; render(); },
    get workflow() { return state.workflow; },
    get mode() { return state.loaded ? state.privacy.mode : null; },
    get loaded() { return state.loaded; },
    get engine() { return state.engine; },
    openPrivacy,
  };
  window.BlowAIWorkflow.ready = loadPrivacy();
  loadConnection();
  window.setInterval(() => { if (state.workflow === "mcp" && !document.hidden) loadConnection(); }, 5000);
})();
