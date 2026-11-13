/* Chat page: type a website, pick the AI, then follow the agent in chat while the
   to-do list on the right ticks each step. Talks to the backend JSON API (backend/server.py). */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const usd = (x) => { x = +x || 0; return x === 0 ? "$0.00" : x < 0.01 ? "$" + x.toFixed(4) : "$" + x.toFixed(2); };
  const VERDICT_COLOR = { "Ready": "#16a34a", "Ready with Risks": "#d97706", "Not Ready": "#dc2626", "Insufficient Evidence": "#64748b" };

  // to-do items and the backend steps (LangGraph nodes) that complete them
  const TODO = [
    { id: "open", label: "Open the website", stages: ["setup"] },
    { id: "pages", label: "Discover pages & components", stages: ["discovery"] },
    { id: "changes", label: "Compare with the last test", stages: ["change_detection", "visual_check"] },
    { id: "cases", label: "Write test cases (Excel)", stages: ["test_design"] },
    { id: "scripts", label: "Write automation scripts", stages: ["script_generator"] },
    { id: "run", label: "Run the tests", stages: ["execution"] },
    { id: "analyse", label: "Analyse failures", stages: ["failure_analysis"] },
    { id: "heal", label: "Repair broken scripts", stages: ["self_healing"] },
    { id: "report", label: "Final report", stages: ["report", "save_baseline", "integrations"] },
  ];

  let providers = null, chosen = "ollama", pendingSource = "", lastCheck = {};
  let job = null, since = 0, timer = null, posted = {}, logLines = [], llmWarnings = 0, casesBusy = false;
  let mobileRun = false, mobilePreparing = false;
  let stick = true, casesKey = "";  // follow new messages? / last test-case list drawn
  let messageNumber = 0;
  let psince = 0, livePages = [], pageStats = {}, pagesBusy = false;  // the live page-by-page list
  const TITLE = document.title;
  const PREFS = "agenticqa.ai";  // last AI choice (never the API key)
  const CRAWL_PREFS_VERSION = 2;
  let providerMeta = {};
  const TECH_STACK = "Python · Playwright · PyTest";
  let chain = Promise.resolve(), chainGen = 0;  // step messages are posted in order, one after another
  let excelData = null, excelSheet = 0;  // the sheet open in the Excel viewer

  const workflow = window.BlowAIWorkflow;
  window.addEventListener("blowai:privacychange", applyProviderPrivacy);
  window.addEventListener("blowai:mcpjob", (event) => {
    const data = event.detail;
    if (timer || (job && job.id === data.id && job.status === "running")) return;
    pendingSource = data.source;
    userSays(data.source);
    say("<p>Your MCP assistant started this run. Follow its progress and use Stop here when needed.</p>");
    if (data.target_type === "android") beginMobileJob(data);
    else beginJob(data, false);
  });

  function applyProviderPrivacy() {
    const box = $("m-ai");
    if (!box) return;
    if (chosen && !workflow.providerAllowed(chosen)) chosen = "";
    box.querySelectorAll(".prov").forEach((button) => {
      button.disabled = !!timer || !workflow.providerAllowed(button.dataset.id);
      button.classList.toggle("sel", button.dataset.id === chosen);
    });
    if ($("aiReadiness")) refreshAiFields();
  }

  async function standardReady() {
    if (!workflow.loaded && !await workflow.ready) {
      say("<p>Privacy settings could not be loaded. Open Privacy &amp; connections before starting.</p>");
      return false;
    }
    if (workflow.workflow !== "standard") {
      $("mcpPanelMessage").textContent = "Send your request through the connected assistant, or choose Standard testing.";
      return false;
    }
    return true;
  }

  // ------------------------------------------------------------ start
  renderTodo({}, false);
  greet();
  loadHistory();
  resumeIfRunning();

  $("composer").addEventListener("submit", (e) => { e.preventDefault(); onSend(); });
  $("newBtn").addEventListener("click", newTest);
  $("resultsNewBtn").addEventListener("click", newTest);
  $("stopBtn").addEventListener("click", stopRun);
  $("webModeBtn").addEventListener("click", closeMobileForm);
  $("mobileModeBtn").addEventListener("click", openMobileForm);
  $("mobileCancel").addEventListener("click", closeMobileForm);
  $("mobileForm").addEventListener("submit", (e) => { e.preventDefault(); startMobileRun(); });
  $("androidMode").addEventListener("change", updateAndroidFields);
  $("androidWholeApp").addEventListener("change", () => { $("androidContractOnly").checked = !$("androidWholeApp").checked; });
  $("androidContract").addEventListener('input', () => {
    refreshAndroidPermissionPolicy();
    if ($("androidContract").value.trim()) {
      $("androidWholeApp").checked = false;
      $("androidContractOnly").checked = true;
    }
  });
  $("androidPermissionApproval").addEventListener('change', () => {
    try {
      const contract = JSON.parse($("androidContract").value);
      if (!contract.android_permissions) return;
      const approved = $("androidPermissionApproval").checked;
      contract.android_permissions.approved = approved;
      (contract.flows || []).filter(flow=>(flow.steps || []).some(step=>step.permission)).forEach(flow=>flow.approved = approved);
      $("androidContract").value = JSON.stringify(contract, null, 2);
      refreshAndroidPermissionPolicy();
    } catch (_) { $("androidRunNote").textContent = 'Correct the test-flow JSON before changing permission approval.'; }
  });
  $("androidEnvRefresh").addEventListener("click", refreshAndroidEnvironment);
  $("androidAppiumUrl").addEventListener("change", refreshAndroidEnvironment);
  $("menuBtn").addEventListener("click", () => toggleWorkspaceDrawer("side"));
  $("todoBtn").addEventListener("click", () => toggleWorkspaceDrawer("todo"));
  $("navClose").addEventListener("click", closeWorkspaceDrawers);
  $("planClose").addEventListener("click", closeWorkspaceDrawers);
  $("drawerBackdrop").addEventListener("click", closeWorkspaceDrawers);
  window.addEventListener("resize", closeWorkspaceDrawers);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeWorkspaceDrawers(); });
  $("jumpBtn").addEventListener("click", () => scrollDown(true));
  $("thread").addEventListener("scroll", () => {
    stick = atBottom();
    if (stick) $("jumpBtn").hidden = true;
  });
  // Pause immediately on upward input, including before the next poll/scroll event.
  $("thread").addEventListener("wheel", (event) => {
    if (event.deltaY < 0) stick = false;
  }, { passive: true });
  $("thread").addEventListener("keydown", (event) => {
    if (event.target.closest("input,textarea,select,[contenteditable=true]")) return;
    if (["ArrowUp", "PageUp", "Home"].includes(event.key) || (event.key === " " && event.shiftKey)) stick = false;
  });
  let touchY = null;
  $("thread").addEventListener("touchstart", (event) => {
    touchY = event.touches[0]?.clientY ?? null;
  }, { passive: true });
  $("thread").addEventListener("touchmove", (event) => {
    const y = event.touches[0]?.clientY;
    if (touchY !== null && y > touchY) stick = false;
    touchY = y ?? null;
  }, { passive: true });

  // ------------------------------------------------------------ chat helpers
  function atBottom() { const t = $("thread"); return t.scrollHeight - t.scrollTop - t.clientHeight < 2; }

  // follow new messages only while the user is at the bottom; otherwise show "New messages"
  function scrollDown(force) {
    const t = $("thread");
    if (!force && !stick) { $("jumpBtn").hidden = false; return; }
    t.style.scrollBehavior = "auto";  // jump instantly so the scroll listener sees the bottom
    t.scrollTop = t.scrollHeight;
    t.style.scrollBehavior = "";
    stick = true;
    $("jumpBtn").hidden = true;
  }

  function changeThread(change) {
    const thread = $("thread"), top = thread.scrollTop, following = stick;
    const edge = thread.getBoundingClientRect().top;
    // Stable case IDs also preserve the reading position when an earlier row grows.
    const candidates = Array.from(thread.querySelectorAll(".msg[id], [data-scroll-key]"));
    const anchor = candidates.findLast((node) => {
      const r = node.getBoundingClientRect();
      return r.top <= edge + 1 && r.bottom > edge;
    }) || candidates.find((node) => node.getBoundingClientRect().top >= edge);
    const key = anchor?.dataset.scrollKey, id = anchor?.id;
    const offset = anchor?.getBoundingClientRect().top;
    change();
    if (following) { scrollDown(); return; }
    const restored = key ? thread.querySelector(`[data-scroll-key="${CSS.escape(key)}"]`) : id ? $(id) : null;
    thread.scrollTop = top + (restored ? restored.getBoundingClientRect().top - offset : 0);
    $("jumpBtn").hidden = false;
  }

  function setTabTitle(prefix) { document.title = prefix ? `${prefix} · ${TITLE}` : TITLE; }

  function notify(title, body) {  // only when the user is on another tab
    try {
      if (document.hidden && window.Notification && Notification.permission === "granted") new Notification(title, { body });
    } catch (e) {}
  }

  // queue a chat message so a slow one (e.g. the test case table) never lands after a later step;
  // anything still queued from a previous chat is dropped by newTest()
  function later(fn) {
    const g = chainGen;
    chain = chain.then(() => (g === chainGen ? fn() : null)).catch(() => {});
  }

  function loadPrefs() { try { return JSON.parse(localStorage.getItem(PREFS)) || {}; } catch (e) { return {}; } }
  function savePrefs(p) { try { localStorage.setItem(PREFS, JSON.stringify(p)); } catch (e) {} }

  function say(html, id) {  // assistant message; with an id it can be updated later
    const el = document.createElement("div");
    el.className = "msg";
    el.dataset.scrollKey = `message:${++messageNumber}`;
    if (id) el.id = "m-" + id;
    el.innerHTML = `<div class="avatar">QA</div><div class="bubble">${html}</div>`;
    changeThread(() => $("thread").appendChild(el));
    return el.querySelector(".bubble");
  }

  function update(id, html) {
    const el = $("m-" + id);
    if (!el) { say(html, id); return; }
    const opened = new Map(Array.from(el.querySelectorAll("details[data-details-key]"),
      (node) => [node.dataset.detailsKey, node.open]));
    const focused = el.contains(document.activeElement)
      ? document.activeElement.closest("details[data-details-key]")?.dataset.detailsKey : null;
    const scrolls = Array.from(el.querySelectorAll(".scroll"), (node) => [node.scrollLeft, node.scrollTop]);
    changeThread(() => {
      el.querySelector(".bubble").innerHTML = html;
      el.querySelectorAll("details[data-details-key]").forEach((node) => {
        if (opened.has(node.dataset.detailsKey)) node.open = opened.get(node.dataset.detailsKey);
        if (focused === node.dataset.detailsKey) node.querySelector("summary")?.focus({ preventScroll: true });
      });
      el.querySelectorAll(".scroll").forEach((node, i) => {
        if (scrolls[i]) { node.scrollLeft = scrolls[i][0]; node.scrollTop = scrolls[i][1]; }
      });
    });
  }

  function userSays(text) {
    const el = document.createElement("div");
    el.className = "msg user";
    el.dataset.scrollKey = `message:${++messageNumber}`;
    el.innerHTML = `<div class="bubble">${esc(text)}</div>`;
    $("thread").appendChild(el);
    scrollDown(true);
  }

  function greet() {
    $("thread").insertAdjacentHTML("beforeend", '<div class="workspace-welcome"><div class="welcome-top"><span class="section-label">FROM PRODUCT TO PROOF</span><span class="subtle-label">One connected workflow</span></div><div class="workflow-cards"><article><span class="workflow-icon violet"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m12 3 10 5-10 5L2 8l10-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/></svg></span><span class="step-label">01 / DISCOVER</span><h3>Know your product</h3><p>Map pages, menus, and components within your selected scope.</p></article><article><span class="workflow-icon sky"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4L12 3Z"/></svg></span><span class="step-label">02 / GENERATE</span><h3>Build meaningful checks</h3><p>Turn observed controls and expected behavior into executable tests.</p></article><article><span class="workflow-icon mint"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m8 12 3 3 5-6"/><path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Z"/></svg></span><span class="step-label">03 / VERIFY</span><h3>See the evidence</h3><p>Review actual results, screenshots, coverage, and release gates.</p></article></div><div class="welcome-note"><span class="note-dot"></span>Discovery and functional verification are reported separately.</div></div>');
    setWorkspaceMode("web");
  }

  function closeWorkspaceDrawers() {
    $("side").classList.remove("open");
    $("todo").classList.remove("open");
    $("drawerBackdrop").hidden = true;
    $("menuBtn").setAttribute("aria-expanded", "false");
    $("todoBtn").setAttribute("aria-expanded", "false");
  }

  function toggleWorkspaceDrawer(id) {
    const opening = !$(id).classList.contains("open");
    closeWorkspaceDrawers();
    if (opening) {
      $(id).classList.add("open");
      $("drawerBackdrop").hidden = false;
      $(id === "side" ? "menuBtn" : "todoBtn").setAttribute("aria-expanded", "true");
    }
  }

  function lockWorkspaceMode(locked) {
    $("webModeBtn").disabled = locked;
    $("mobileModeBtn").disabled = locked;
    workflow.setBusy(locked);
  }

  function setWorkspaceMode(mode) {
    document.body.dataset.testMode = mode;
    const android = mode === "android";
    workflow.setEngine(mode);
    $("webModeBtn").classList.toggle("selected", !android);
    $("mobileModeBtn").classList.toggle("selected", android);
    $("webModeBtn").setAttribute("aria-pressed", String(!android));
    $("mobileModeBtn").setAttribute("aria-pressed", String(android));
  }

  function setComposer(enabled, placeholder) {
    $("msg").disabled = !enabled;
    $("sendBtn").disabled = !enabled;
    $("msg").placeholder = placeholder;
    if (enabled) $("msg").focus();
  }

  function newTest() {
    if (timer || mobilePreparing) return;  // a test is running or Android is booting
    if (window.QpilotLive) window.QpilotLive.reset();
    ['androidApiKey','androidTestUsername','androidTestPassword'].forEach(id => $(id).value = '');
    document.body.dataset.setupState = "idle";
    job = null; posted = {}; logLines = []; llmWarnings = 0; lastCheck = {}; casesKey = ""; chainGen++;
    mobileRun = false;
    lockWorkspaceMode(false);
    psince = 0; livePages = []; pageStats = {};
    $("thread").innerHTML = "";
    stick = true; $("jumpBtn").hidden = true;
    setTabTitle("");
    $("chatTitle").textContent = "Test studio";
    $("statusPill").hidden = true;
    $("costBox").hidden = true;
    $("todoActions").hidden = true;
    ["actExcel", "actReport", "actComponents", "actSite"].forEach((id) => ($(id).hidden = true));
    document.querySelectorAll(".recent .item").forEach((b) => b.classList.remove("on"));
    shownPast = null;
    renderTodo({}, false);
    $("mobileForm").hidden = true;
    $("mobileModeBtn").hidden = false;
    $("composer").hidden = false;
    $("composer-hint").hidden = false;
    greet();
    setComposer(true, "Paste a website URL, GitHub repo or project folder…");
    closeWorkspaceDrawers();
  }

  function updateAndroidFields() {
    const installed = $("androidMode").value === "installed";
    const web = $("androidMode").value === "web";
    $("androidApkField").hidden = installed || web;
    $("androidPackageField").hidden = !installed;
    $("androidApk").required = !installed && !web;
    $("androidPackage").required = installed;
    $("androidUrlField").hidden = !web;
    $("androidUrl").required = web;
    $("androidActivityField").hidden = web;
    refreshAndroidPermissionPolicy();
  }

  function refreshAndroidPermissionPolicy() {
    let contract = {}; try { contract = JSON.parse($("androidContract").value || '{}'); } catch (_) { /* JSON validation handles incomplete edits. */ }
    const policy = contract.android_permissions;
    $("androidPermissionPolicy").hidden = !policy;
    $("androidPermissionApproval").checked = policy?.approved === true;
    if (policy) {
      const flows = (contract.flows || []).filter(flow => (flow.steps || []).some(step=>step.permission));
      $("androidPermissionScope").textContent = `${flows.filter(flow=>flow.approved).length}/${flows.length} permission flows approved for ${policy.app_label || 'the configured app'}. Permissions: ${(policy.allowed || []).map(value=>value.replace('android.permission.','')).join(', ')}. Emulator only; OS request-history flags may change.`;
    }
  }

  async function openMobileForm() {
    if (timer || mobilePreparing) return;
    document.body.dataset.setupState = "configure";
    setWorkspaceMode("android");
    $("mobileForm").hidden = false;
    $("mobileModeBtn").hidden = false;
    $("composer").hidden = true;
    $("composer-hint").hidden = true;
    $("androidRunNote").textContent = "";
    renderMobileTodo({});
    updateAndroidFields();
    await refreshAndroidEnvironment();
  }

  function closeMobileForm() {
    if (timer || mobilePreparing) return;
    document.body.dataset.setupState = $("m-ai") ? "configure" : "idle";
    setWorkspaceMode("web");
    $("mobileForm").hidden = true;
    $("mobileModeBtn").hidden = false;
    $("composer").hidden = false;
    $("composer-hint").hidden = false;
    renderTodo({}, false);
  }

  async function refreshAndroidEnvironment() {
    if (mobilePreparing) return;
    const note = $("androidEnvNote");
    const start = $("androidStart");
    start.disabled = true;
    note.textContent = "Checking Android SDK, Java, Appium and connected devices…";
    $("androidRunNote").textContent = "Checking Android setup…";
    const device = $("androidDevice");
    const previousDevice = device.value;
    const previousAvd = device.selectedOptions[0]?.dataset.avd || "";
    device.replaceChildren(new Option("Checking devices…", ""));
    try {
      const response = await fetch("/api/android/environment?appium_url=" + encodeURIComponent($("androidAppiumUrl").value));
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not check the Android environment.");
      device.replaceChildren(new Option("Choose a device", ""));
      (data.devices || []).forEach((item) => {
        const label = `${item.device_id} · ${item.status}${item.details ? " · " + item.details : ""}`;
        const option = new Option(label, item.device_id);
        option.disabled = item.status !== "device";
        option.dataset.avd = item.avd_name || "";
        device.add(option);
      });
      const connectedNames = new Set((data.devices || []).filter(item => item.status === "device").map(item => item.avd_name));
      (data.emulators || []).filter(item => !connectedNames.has(item.name)).forEach(item => {
        const option = new Option(`${item.name} · start emulator automatically`, item.device_id);
        option.dataset.avd = item.name;
        device.add(option);
      });
      if (previousDevice && [...device.options].some((option) => option.value === previousDevice && !option.disabled)) device.value = previousDevice;
      else if (previousAvd && [...device.options].some(option => option.dataset.avd === previousAvd && !option.disabled))
        device.value = [...device.options].find(option => option.dataset.avd === previousAvd && !option.disabled).value;
      else {
        const selectable = [...device.options].filter(option => option.value && !option.disabled);
        if (selectable.length === 1) device.value = selectable[0].value;
      }
      if (data.ok) {
        note.textContent = "Android tools and a device are ready. Appium stays local to this computer.";
        $("androidRunNote").textContent = "";
        start.disabled = false;
      } else if (data.can_prepare || data.can_start_emulator) {
        note.textContent = "Ready to start. Start Android test will launch local Appium and boot your selected emulator if needed.";
        $("androidRunNote").textContent = "Appium and Android will start automatically when you click Start Android test.";
        start.disabled = false;
      } else {
        const errors = (data.errors || ["Android environment is not ready."]).map(message => message.replaceAll("`", ""));
        note.textContent = errors.join(" ");
        $("androidRunNote").textContent = errors.join(" ");
      }
    } catch (error) {
      note.textContent = error.message || "Could not check the Android environment.";
      $("androidRunNote").textContent = note.textContent;
    }
  }

  async function startMobileRun() {
    if (!await standardReady()) return;
    const form = $("mobileForm");
    if (!form.reportValidity() || timer || mobilePreparing) return;
    const mode = $("androidMode").value;
    const app = mode === "web" ? $("androidUrl").value.trim() : mode === "installed" ? $("androidPackage").value.trim() :
      (($("androidApk").files[0] || {}).name || "Uploaded APK");
    const data = new FormData();
    data.append("workflow", "standard");
    data.append("privacy_mode", workflow.mode);
    data.append("appium_url", $("androidAppiumUrl").value);
    data.append("max_depth", $("androidDepth").value);
    data.append("discovery_timeout_s", $("androidDiscoveryTimeout").value);
    data.append("max_scroll_actions", $("androidMaxScrolls").value);
    data.append("max_scrolls_per_screen", "0");
    data.append("requested_scope", JSON.stringify({
      max_depth: Number($("androidDepth").value), max_screens: Number($("androidMaxScreens").value),
      max_actions: Number($("androidMaxActions").value), max_scroll_actions: Number($("androidMaxScrolls").value),
      max_scrolls_per_screen: 0, discovery_timeout_s: Number($("androidDiscoveryTimeout").value),
      max_test_cases: Number($("androidMaxCases").value)
    }));
    data.append("expected_destinations", $("androidExpectations").value);
    data.append("requirements", $("androidRequirements").value);
    data.append("expected_values", $("androidExpectedValues").value);
    const contractText = $("androidContract").value.trim();
    if (contractText) {
      try {
        const parsedContract = JSON.parse(contractText);
        if (!parsedContract || Array.isArray(parsedContract) || typeof parsedContract !== "object") throw new Error("object required");
      } catch (_) { $("androidRunNote").textContent = "Enter a valid JSON object for the advanced checks."; return; }
    }
    if ($("androidContractOnly").checked && !contractText) {
      $("androidRunNote").textContent = "Load an app-specific example or build an approved test flow before running configured workflows only.";
      return;
    }
    data.append("qa_contract", contractText);
    data.append("contract_only", $("androidContractOnly").checked ? "true" : "false");
    // Websites too: the ticked box is the person's confirmation that it is a test / demo site they may test
    data.append("interaction_testing", $("androidTestBuild").checked ? "true" : "false");
    data.append("thorough", $("androidThorough") && $("androidThorough").checked ? "true" : "false");
    data.append("max_test_cases", $("androidMaxCases").value);
    // Test mode's limits are sent explicitly, so a run never falls back to an older server's smaller defaults
    data.append("max_interactions", $("androidMaxInteractions").value || "0");
    data.append("interaction_timeout_s", $("androidInteractionTimeout").value || "0");
    data.append("allow_rules_fallback", $("androidFallback").checked ? "true" : "false");
    if ($("androidProvider").value) data.append("llm_provider", $("androidProvider").value);
    if ($("androidModel").value.trim()) data.append("llm_model", $("androidModel").value.trim());
    if ($("androidApiKey").value.trim()) data.append("api_key", $("androidApiKey").value.trim());
    if ($("androidTestUsername").value) data.append('test_username', $("androidTestUsername").value);
    if ($("androidTestPassword").value) data.append('test_password', $("androidTestPassword").value);
    data.append("app_mode", mode);
    data.append("device_id", $("androidDevice").value);
    data.append("package_name", mode === "installed" ? $("androidPackage").value.trim() : "");
    data.append("app_activity", mode === "web" ? "" : $("androidActivity").value.trim());
    data.append("start_url", mode === "web" ? $("androidUrl").value.trim() : "");
    data.append("max_screens", $("androidMaxScreens").value);
    data.append("max_actions", $("androidMaxActions").value);
    data.append("authorized", $("androidAuthorized").checked ? "true" : "false");
    if (mode === "apk") data.append("apk", $("androidApk").files[0]);
    const selectedDevice = $("androidDevice").value;
    const selectedAvd = $("androidDevice").selectedOptions[0]?.dataset.avd || "";
    const controls = [...form.querySelectorAll("input,select,textarea,button"), $("newBtn"), $("resultsNewBtn")];
    const disabledBefore = controls.map(control => control.disabled);
    controls.forEach(control => control.disabled = true);
    mobilePreparing = true;
    lockWorkspaceMode(true);
    form.setAttribute("aria-busy", "true");
    const startLabel = $("androidStart").textContent;
    $("androidStart").textContent = "Preparing Android…";
    let preparationMessage = "Step 1 of 3 · Starting local Appium and waiting for it to be ready";
    const preparationStarted = Date.now();
    const showPreparation = () => {
      $("androidRunNote").textContent = `${preparationMessage} · ${Math.floor((Date.now() - preparationStarted) / 1000)}s elapsed`;
    };
    showPreparation();
    const preparationTimer = setInterval(showPreparation, 1000);
    try {
      const prepareStep = async stage => {
        const response = await fetch("/api/android/prepare", {
          method: "POST", headers: { "Content-Type": "application/json", "X-Agentic-QA": "1" },
          body: JSON.stringify({ device_id: selectedDevice, avd_name: selectedAvd,
            appium_url: $("androidAppiumUrl").value, authorized: $("androidAuthorized").checked, stage })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "Android could not be started.");
        return result;
      };
      await prepareStep("appium");
      preparationMessage = selectedAvd ? "Step 2 of 3 · Appium is ready. Waiting for Android to boot; this may take a few minutes" : "Step 2 of 3 · Appium is ready. Checking the selected Android device";
      showPreparation();
      const prepared = await prepareStep("device");
      data.set("device_id", prepared.device_id);
      let option = [...$("androidDevice").options].find(item => item.value === prepared.device_id);
      if (!option) {
        option = new Option(`${prepared.device_id} · ready`, prepared.device_id);
        $("androidDevice").add(option);
      }
      option.dataset.avd = prepared.avd_name || selectedAvd;
      $("androidDevice").value = prepared.device_id;
      preparationMessage = mode === "apk" ? "Step 3 of 3 · Android is ready. Uploading the private APK" : "Step 3 of 3 · Android is ready. Starting Appium tests";
      showPreparation();
      const response = await fetch("/api/mobile/runs", {
        method: "POST", headers: { "X-Agentic-QA": "1" }, body: data
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || "Could not start the Android test.");
      $("androidApiKey").value = "";
      $("androidTestUsername").value = '';
      $("androidTestPassword").value = '';
      userSays(`Test ${mode === "web" ? "Android Chrome" : "Android app"}: ${app}`);
      say("<p>Starting a local Appium + PyTest run. Discovery follows safe navigation. Only explicitly approved QA-contract flows may fill fields or submit test forms.</p>");
      beginMobileJob(result);
    } catch (error) {
      $("androidRunNote").textContent = error.message || "Could not start the Android test.";
      $("androidStart").disabled = false;
    } finally {
      clearInterval(preparationTimer);
      form.removeAttribute("aria-busy");
      $("androidStart").textContent = startLabel;
      mobilePreparing = false;
      controls.forEach((control, index) => control.disabled = disabledBefore[index]);
      if (!timer) lockWorkspaceMode(false);
    }
  }

  function beginMobileJob(data) {
    document.body.dataset.setupState = "running";
    workflow.setWorkflow(data.workflow || "standard", true);
    setWorkspaceMode("android");
    lockWorkspaceMode(true);
    mobileRun = true;
    job = data;
    since = 0;
    psince = 0;
    posted = {};
    logLines = [];
    $("chatTitle").textContent = data.source;
    $("mobileForm").hidden = true;
    $("mobileModeBtn").hidden = false;
    $("composer").hidden = true;
    $("composer-hint").hidden = true;
    $("stopBtn").hidden = false;
    $("stopBtn").disabled = false;
    setStatus("Testing Android…", "");
    setTabTitle("⏳ Testing Android…");
    $("costBox").hidden = false;
    $("todoActions").hidden = true;
    renderMobileTodo({});
    clearInterval(timer);
    timer = setInterval(poll, 900);
    poll();
  }

  function renderMobileTodo(stages) {
    const labels = {setup:"Connect to Android device",discovery:"Explore screens and extract controls",
      ...(Object.hasOwn(stages, "test_build") ? {test_build:"Exercise and replay safe test-build checks"} : {}),
      test_design:"Design mobile test cases",
      script_generator:"Generate and validate Appium scripts",execution:"Execute tests and capture evidence",failure_analysis:"Classify failures",
      self_healing:"Review locator recovery",report:"Prepare report and calculate verdict"};
    const entries = Object.entries(labels);
    const done = entries.filter(([key]) => stages[key] === "done").length;
    $("todoList").innerHTML = entries.map(([key,label]) => `<li class="${stages[key] === "done" ? "done" : stages[key] === "running" ? "running" : ""}">${esc(label)}</li>`).join("");
    $("todoMeta").textContent = `${done} / ${entries.length} stages`;
    $("todoBar").style.width = `${100 * done / entries.length}%`;
  }

  async function pollMobile() {
    if (!job) return;
    try {
      const response = await fetch(`/api/runs/${job.id}?since=${since}&psince=${psince}`);
      if (!response.ok) return;
      const result = await response.json();
      job = Object.assign(job || {}, result);
      renderMobileTodo(result.stages || {});
      $("costNow").textContent = usd((result.cost || {}).cost_usd);
      $("costCalls").textContent = `${(result.cost || {}).calls || 0} AI calls`;
      since = result.next;
      psince = result.pnext || psince;
      (result.live_pages || []).forEach((page) => {
        say(`<p>📱 Found Android screen: <b>${esc(page.title || page.activity || "screen")}</b>
          <span class="muted small">${esc(page.activity || "")}</span></p>`);
      });
      if ((result.lines || []).length) {
        const text = result.lines.join("\n");
        for (const line of result.lines) {
          if (line.startsWith("::warning::")) say(`<div class="warn">${esc(line.slice(11))}</div>`);
        }
        logLines.push(...result.lines);
        say(`<pre class="mobile-log">${esc(text)}</pre>`);
      }
      if (result.run && result.stages?.test_design === "done" && !posted.cases) {
        posted.cases = true;
        await postTestCases(result.run, true);
      }
      if (result.run && result.stages?.execution) {
        if (!posted.exec) { posted.exec = true; say(execHtml(null), "exec"); }
        loadCases(result.run);
      }
      if (result.status === "running") {
        setStatus(result.current ? `Android · ${result.current.replaceAll("_", " ")}` : "Testing Android…", "");
        return;
      }
      clearInterval(timer);
      timer = null; lockWorkspaceMode(false);
      mobileRun = false;
      $("stopBtn").hidden = true;
      $("mobileForm").hidden = false;
      $("androidStart").disabled = false;
      $("androidRunNote").textContent = result.status === "done" ? "Android run complete." : `Android run ${result.status}.`;
      setTabTitle("");
      setStatus(result.status === "done" ? "Loading results…" : `Android ${result.status}`,
        result.status === "done" ? "" : "bad");
      if (result.run && result.report_ready) {
        try {
          const response = await fetch(`/api/report/${encodeURIComponent(result.run)}`);
          if (!response.ok) throw new Error(`Report request failed (${response.status}).`);
          const report = await response.json();
          const summary = report.summary || {};
          document.body.dataset.setupState = "results";
          showQualityStatus(summary);
          $("todoMeta").textContent = "Stages finished. Review the test outcome.";
          const reasons = (summary.reasons || []).map((reason) => `<li>${esc(reason)}</li>`).join("");
          const aiWarnings = (summary.ai_warnings || []).map(warning => `<div class="warn">${esc(warning)}</div>`).join("");
          const reportUrl = `/runs/${encodeURIComponent(result.run)}/report.html`;
          const casesUrl = `/api/cases/${encodeURIComponent(result.run)}/download`;
          const excelUrl = `/api/excel/${encodeURIComponent(result.run)}/download`;
          say(`<div class="card"><p><b>${esc(summary.verdict || "Android run finished")}</b></p>
            ${summary.functional_checks ? `<p>${esc(summary.functional_checks.passed)} configured functional checks passed · ${esc(summary.ui_checks?.passed || 0)} UI checks passed · ${esc(summary.controls_needing_functional_checks_count ?? (Array.isArray(summary.controls_needing_functional_checks) ? summary.controls_needing_functional_checks.length : summary.controls_needing_functional_checks || 0))} observed controls still need functional checks.</p>` : ''}
            ${aiWarnings}${reasons ? `<ul>${reasons}</ul>` : ""}<p class="actions">
            <a class="secondary" href="${reportUrl}" target="_blank" rel="noopener">📄 Android report</a>
            ${summary.functional_checks ? `<a class="secondary" href="/runs/${encodeURIComponent(result.run)}/features.json" target="_blank" rel="noopener">Feature coverage</a>` : ''}
            ${report.excel ? `<a class="secondary" href="${excelUrl}">Excel results</a>` : ""}
            ${report.cases_available ? `<a class="secondary" href="${casesUrl}">Test cases JSON</a>` : ""}</p></div>`);
        } catch (error) {
          setStatus("Report unavailable", "warn");
          say(`<div class="warn">${esc(error.message || "The Android report could not be loaded.")}</div>`);
        }
      } else {
        setStatus("Insufficient Evidence", "warn");
        say(`<div class="warn">The Android process ended (${esc(result.status)}) before a report was ready. Review the run log above.</div>`);
      }
    } catch (error) {
      if (!posted.mobilePollError) {
        posted.mobilePollError = true;
        say(`<div class="warn">Could not refresh Android run status yet: ${esc(error.message || "local server unavailable")}. Retrying…</div>`);
      }
    }
  }

  // ------------------------------------------------------------ 1) URL -> website check -> choose the AI
  async function onSend() {
    if (!await standardReady()) return;
    const text = $("msg").value.trim();
    if (!text || timer) return;
    $("msg").value = "";
    userSays(text);
    pendingSource = text;
    document.body.dataset.setupState = "checking";
    $("chatTitle").textContent = text;
    const b = say(`<div class="typing"><i></i><i></i><i></i></div>`, "check");

    let c;
    try {
      const res = await fetch(`/api/check?source=${encodeURIComponent(text)}`);
      c = await res.json();
      if (!res.ok) throw new Error(c.detail || "check failed");
    } catch (err) {
      c = { kind: "website", ok: false, error: err.message };
    }
    if (pendingSource !== text) return;
    update("check", checkHtml(c));
    if (c.kind === "website" && c.ok) setSiteLink(c.final_url || c.url);
    lastCheck = c;
    if (c.unwrapped && c.url) {  // a Bing / Google result link: test the real website behind it
      pendingSource = c.url;
      $("chatTitle").textContent = c.url;
    }
    await askForAi();
  }

  function checkHtml(c) {
    if (c.kind === "github")
      return `<div class="card check ok"><div class="ic">✓</div><div class="t"><b>GitHub repository: ${esc(c.title)}</b>
        <span>I'll download it, start it on this PC and then test it.</span></div></div>`;
    if (c.kind === "folder")
      return `<div class="card check ok"><div class="ic">✓</div><div class="t"><b>Project folder: ${esc(c.title)}</b>
        <span>I'll start this project on this PC and then test it.</span></div></div>`;
    const unwrapped = c.unwrapped ? `<p>ℹ️ That was a <b>search-result link</b> (Bing / Google), not the website itself.
      I'll test the real website: <b>${esc(c.url)}</b></p>` : "";
    if (c.ok)
      return `${unwrapped}<p>The website is reachable. Functional testing has not started:</p><div class="card check ok"><div class="ic">✓</div><div class="t">
        <b>${esc(c.title || "Website reachable")}</b><span>HTTP ${esc(c.status)} · ${esc(c.ms)} ms · ${esc(c.final_url || c.url)}</span></div></div>`;
    return `<div class="card check bad"><div class="ic">!</div><div class="t"><b>I could not open this website${c.status ? " (HTTP " + esc(c.status) + ")" : ""}</b>
      <span>${esc(c.error || c.url)}. Check the address, or start anyway and the report will show what failed.</span></div></div>`;
  }

  async function askForAi() {
    await workflow.ready;
    await loadProviderChoices();
    const saved = loadPrefs();
    if (saved.crawlPrefsVersion !== CRAWL_PREFS_VERSION) {
      saved.pages = 0;
      saved.adv = { ...(saved.adv || {}), depth: 0 };
    }
    saved.adv = { ...(saved.adv || {}), depth: 0 }; // New setup defaults to whole-site depth.
    const remembered = saved.providerChoiceVersion === 2 && providers.find((p) =>
      p.id === saved.provider && workflow.providerAllowed(p.id));
    const localReady = providers.find((p) => p.id === "ollama" && p.ready && workflow.providerAllowed(p.id));
    chosen = remembered ? remembered.id : localReady ? localReady.id : "";
    const old = $("m-ai"); if (old) old.remove();
    say(aiPickerHtml(saved), "ai");
    document.body.dataset.setupState = "configure";
    wireAiPicker(saved);
    $("m-ai").scrollIntoView({block:"start", behavior:"smooth"});
  }

  async function loadProviderChoices() {
    try {
      const response = await fetch("/api/providers");
      if (!response.ok) throw new Error("Provider list could not be loaded.");
      const payload = await response.json();
      providers = payload.providers || [];
      providerMeta = payload.exploration || {};
    } catch (_) { providers = []; providerMeta = {}; }
  }

  function providerCardsHtml() {
    return (providers || []).map((p) => {
      const allowed = workflow.providerAllowed(p.id);
      const reason = !allowed ? "Enable cloud access in Privacy settings" :
        p.readiness_reason || (p.id === "none" ? "Rules only; no AI interpretation" :
          p.id === "ollama" ? (p.running ? "Local model available" : "Ollama is not running") :
          p.has_key ? "Configured; checked when used" : "API key required");
      return '<button type="button" class="prov ' + (p.id === chosen ? 'sel' : '') +
        '" data-id="' + esc(p.id) + '" ' + (allowed ? '' : 'disabled') + '><b>' +
        esc(p.id === "none" ? "Rules only" : p.name) + '</b><span class="bd">' +
        esc(p.id === "none" ? "No AI" : p.badge) + '</span><span class="st ' +
        (allowed && (p.ready || (p.id === "ollama" && p.running)) ? 'ok' : '') + '">' +
        esc(reason) + '</span></button>';
    }).join("") || '<p class="note">AI choices could not be loaded. Use Refresh below; no provider will be selected automatically.</p>';
  }

  function aiPickerHtml(saved) {
    const cap = providerMeta.hard_page_cap || 500, minutes = providerMeta.time_limit_min || 30;
    const thoroughCrawlMin = Math.max(60, minutes);
    const standardActions = providerMeta.default_actions || 15;
    return '<div class="test-setup"><div class="setup-heading"><div><span class="section-label">WEBSITE SETUP</span>' +
      '<h2>Choose how to explore and test</h2><p class="setup-target">' + esc(pendingSource) + '</p></div>' +
      '<button type="button" class="secondary" id="aiChangeTarget">Change URL</button></div>' +
      '<nav class="setup-sections" aria-label="Test setup sections"><a href="#setupAccount">1 Account</a>' +
      '<a href="#setupAI">2 AI engine</a><a href="#setupScope">3 Exploration</a><a href="#setupFeatures">4 More checks</a></nav>' +
      loginHtml(lastCheck) +
      '<section class="setup-section" id="setupAI"><div class="setup-section-title"><span>02</span><div><h3>Choose your AI engine</h3>' +
      '<p>See what is ready. Rules-only testing is an explicit choice.</p></div></div><div class="provs">' +
      providerCardsHtml() + '</div><div class="row setup-tools"><button type="button" class="secondary" id="aiRefresh">Refresh AI status</button>' +
      '<button type="button" class="secondary" id="aiPrivacy">Privacy settings</button></div>' +
      '<div class="fields"><label id="fModel">Installed / configured model <select id="aiModel"></select></label>' +
      '<label id="fKey" hidden>API key for this run <input id="aiKey" type="password" autocomplete="off" spellcheck="false"></label></div>' +
      '<p class="note" id="aiReadiness" role="status"></p><label class="tick" id="aiFallbackField"><input type="checkbox" id="aiFallback">' +
      '<span>If the selected AI becomes unavailable, allow a clearly labelled rules-only fallback.</span></label></section>' +
      '<section class="setup-section" id="setupScope"><div class="setup-section-title"><span>03</span><div><h3>Choose exploration scope</h3>' +
      '<p>Whole website is the default. Every limit and inaccessible area is reported.</p></div></div>' +
      '<div class="fields"><label>Exploration intensity <select id="aiIntensity" aria-describedby="aiIntensityNote">' +
      '<option value="thorough" selected>Thorough — raised budgets within safety caps</option>' +
      '<option value="standard">Standard — current defaults</option></select></label>' +
      '<label>Area to explore <select id="aiScope"><option value="site">Whole website: reachable same-site pages</option>' +
      '<option value="section">Only the URL section</option><option value="page">Only the supplied page</option></select></label>' +
      '<label>Page coverage <select id="aiCrawlMode"><option value="full">All discovered pages within safety budgets</option>' +
      '<option value="limited">Limit the number of pages</option></select></label>' +
      '<label id="aiPageBudget" hidden>Maximum pages <input id="aiPages" type="number" min="1" max="' + cap + '" value="10"></label>' +
      '<label>Exploration actions per page <input id="aiActions" type="number" min="1" max="100" value="80" data-standard-default="' + standardActions + '"></label></div>' +
      '<p class="note" id="aiIntensityNote">Thorough raises this-run budgets: ≥' + thoroughCrawlMin +
      ' min crawl time (max of 60 and your CRAWL_TIME_LIMIT_MIN), 80 actions/page (max 100), ' +
      '≥500 test cases, repeated controls, every URL pattern (PATTERN_SAMPLES=0). Still finite — HARD_PAGE_CAP (' + cap +
      '), closed shadow DOM, pay/delete/logout, and cross-origin frames stay out of reach. Unvisited pages remain listed.</p>' +
      '<p class="note" id="aiScopeNote">Whole-site route discovery, including menus, nested controls, pagination and logged-in pages when access is available. ' +
      'Safety budgets: up to ' + cap + ' pages, ≥' + thoroughCrawlMin + ' minutes when Thorough, and the selected actions per page. ' +
      'Discovered does not mean functionally verified. Standard uses about ' + standardActions + ' actions/page unless you raise it.</p></section>' +
      '<section class="setup-section" id="setupFeatures"><div class="setup-section-title"><span>04</span><div><h3>Expected behavior and additional checks</h3>' +
      '<p>All existing test, review, recording, business-rule and backend-check settings remain available here.</p></div></div>' +
      myTestsHtml(lastCheck) + advancedHtml(saved) +
      '<div class="toggles"><label><input type="checkbox" id="aiWatch" ' + (saved.watch === false ? '' : 'checked') +
      '> Watch mode: visible browser and readable steps</label><label><input type="checkbox" id="aiFresh"> Fresh baseline and scripts</label></div>' +
      '<p class="muted small">Turn off Watch for Fast mode with isolated hidden browsers. All modes retain execution evidence.</p></section>' +
      '<div class="setup-run"><p id="aiRunSummary" class="note"></p>' +
      '<label class="tick auth"><input type="checkbox" id="aiAuth" ' + (wasAuthorized(pendingSource) ? 'checked' : '') +
      '><span>I own this website or have permission to test it.</span></label>' +
      '<div class="note" id="aiNote" role="alert" hidden></div><button type="button" class="primary" id="aiStart">Explore and test website</button></div></div>';
  }

  // your own tests in plain English (kept for this website: every test of it includes them) + the review step
  function myTestsHtml(c) {
    const mine = (c && c.my_tests) || [];
    return `<details class="login-box" ${mine.length ? "open" : ""}>
        <summary>📝 Your own tests in plain English ${mine.length ? `<span class="muted small">(${mine.length} saved for this website)</span>` : '<span class="muted small">(optional)</span>'}</summary>
        <label class="wide">One test per line - the AI turns each one into steps and checks, every time this website is tested
          <textarea id="myTests" rows="3" spellcheck="false" placeholder="e.g. Search for 'Blue Top', add it to the cart - the cart shows it with its price">${esc(mine.join("\n"))}</textarea></label>
        <label class="tick"><input type="checkbox" id="myReview">
          <span><b>Let me review the test cases</b> before the scripts are written: untick the ones you don't want, add more
          tests. The run waits for you (up to 15 minutes), then goes on.</span></label>
        <p class="muted small">Needs an AI (not "No AI rules"). Saved for this website on this PC - empty the box to remove them.
          A test the website can't do is shown as "Not automated" with the reason.</p>
      </details>`;
  }

  // optional settings: empty = the tester works it out by itself
  function advancedHtml(saved) {
    const a = saved.adv || {};
    const opt = (v, label) => `<option value="${v}" ${a.env === v ? "selected" : ""}>${label}</option>`;
    return `<details class="login-box adv-box">
        <summary>⚙ Advanced settings <span class="muted small">(optional – leave empty and I decide)</span></summary>
        <div class="fields">
          <label>Environment <select id="advEnv">${opt("test", "Test")}${opt("staging", "Staging")}${opt("production", "Production")}</select></label>
          <label>Click depth (0 = no limit) <input id="advDepth" type="number" min="0" max="20" value="${esc(a.depth ?? 0)}"></label>
          <label>Page timeout in s (0 = default) <input id="advTimeout" type="number" min="0" max="300" value="${esc(a.timeout ?? 0)}"></label>
        </div>
        <label class="tick"><input type="checkbox" id="advVideo" ${a.video ? "checked" : ""}>
          <span><b>Record video</b> of the tests (saved with the run; about 10 MB per minute)</span></label>
        <label class="tick" id="advProdBox" ${a.env === "production" ? "" : "hidden"}><input type="checkbox" id="advProd">
          <span>I confirm testing a <b>production</b> website (real users and data). Forms are never submitted there – a test or staging copy is better.</span></label>
        <div id="advStagingBox" ${a.env === "staging" ? "" : "hidden"}>
          <p class="small muted">Staging = your test copy: forms are <b>sent</b> (valid and wrong values), records are
            created, found, edited and deleted (tagged <code>qa-&lt;run&gt;</code>, cleaned up after).</p>
          <label class="tick"><input type="checkbox" id="advWrites">
            <span>This really is a <b>test copy</b> – data may be changed (needed when its address has no staging / test / qa / dev in it)</span></label>
          <div class="fields">
            <label>Also allow (optional) <input id="advAllow" type="text" spellcheck="false" placeholder="delete, logout, password, pay"></label>
          </div>
          <label class="tick"><input type="checkbox" id="advPay">
            <span>The payment provider is in its <b>test mode</b> (needed for "pay")</span></label>
        </div>
        <div class="fields">
          <label>Login page URL <input id="advLoginUrl" type="text" spellcheck="false" placeholder="only if it isn't linked from the start page"></label>
          <label>Text shown only when logged in <input id="advSuccess" type="text" spellcheck="false" placeholder="e.g. Dashboard"></label>
        </div>
        <div class="fields">
          <label>User name box (CSS) <input id="advUserSel" type="text" spellcheck="false" placeholder="#email"></label>
          <label>Password box (CSS) <input id="advPassSel" type="text" spellcheck="false" placeholder="#password"></label>
          <label>Login button (CSS) <input id="advSubmitSel" type="text" spellcheck="false" placeholder="button[type=submit]"></label>
        </div>
        <div class="fields">
          <label>Also allow these hosts <input id="advHosts" type="text" spellcheck="false" placeholder="auth.example.com, *.example.com"></label>
          <label>Leave out these paths <input id="advExclude" type="text" spellcheck="false" placeholder="/admin, /billing"></label>
        </div>
        <label class="wide">Workflows, expected results, user roles (plain words, no passwords)
          <textarea id="advReq" rows="3" placeholder="e.g. A visitor can search a product, add it to the cart and see it in the cart."></textarea></label>
        <label class="wide">Advanced QA contract (optional JSON)<textarea id="webContract" rows="5" maxlength="64000" placeholder="Approved flows, business rules and backend checks"></textarea></label>
        <p class="muted small">Login boxes are only needed when the login can't be found automatically.</p>
      </details>`;
  }

  // "I may test this website" is remembered per website (on this PC only), so it is pre-ticked next time
  const AUTH_KEY = "agenticqa.authorized";
  function originOf(src) {
    try { return new URL(/^[a-z]+:\/\//i.test(src) ? src : "https://" + src).origin; } catch (e) { return src || ""; }
  }
  function wasAuthorized(src) {
    try { return (JSON.parse(localStorage.getItem(AUTH_KEY)) || []).includes(originOf(src)); } catch (e) { return false; }
  }
  function rememberAuthorized(src) {
    try {
      const list = JSON.parse(localStorage.getItem(AUTH_KEY)) || [];
      if (!list.includes(originOf(src))) localStorage.setItem(AUTH_KEY, JSON.stringify(list.concat(originOf(src)).slice(-50)));
    } catch (e) {}
  }

  // a test account, so the tester can log in and test everything behind the login (this run only, never saved)
  function loginHtml(c) {
    const configured = !!c.has_test_account;
    return '<section class="setup-section" id="setupAccount"><div class="setup-section-title"><span>01</span><div>' +
      '<h3>How should Qpilot access the website?</h3><p>Choose an account method before exploration starts.</p></div></div>' +
      '<label class="account-choice">Account method <select id="aiAccountMode"><option value="public">Public pages only</option>' +
      '<option value="existing">Use my existing test account</option><option value="signup">Create or reuse a permitted test account</option>' +
      (configured ? '<option value="configured">Use the test account configured on this computer</option>' : '') + '</select></label>' +
      '<div class="fields" id="aiCredentials" hidden><label>Email / username <input id="aiUser" type="text" autocomplete="off" spellcheck="false"></label>' +
      '<label>Password <input id="aiPass" type="password" autocomplete="new-password"></label>' +
      '<label>Authenticator setup key (optional)<input id="aiTotp" type="password" autocomplete="off"></label></div>' +
      '<label class="tick" id="aiSignupField" hidden><input type="checkbox" id="aiSignup"><span>I permit creating a test account on this website. ' +
      'Registration must be available; CAPTCHA, verification and approval requirements are reported. A created account is stored encrypted locally for reuse.</span></label>' +
      '<p class="note" id="aiAccountNote">Only publicly accessible pages will be explored. Choose an account method to include protected pages.</p></section>';
  }

  function wireAiPicker(saved) {
    bindProviderCards();
    $("aiStart").addEventListener("click", startRun);
    $("aiChangeTarget").addEventListener("click", newTest);
    $("aiPrivacy").addEventListener("click", workflow.openPrivacy);
    $("aiRefresh").addEventListener("click", async () => {
      $("aiRefresh").disabled = true;
      await loadProviderChoices();
      $("m-ai").querySelector(".provs").innerHTML = providerCardsHtml();
      bindProviderCards();
      refreshAiFields();
      $("aiRefresh").disabled = false;
    });
    $("aiAccountMode").addEventListener("change", refreshAccountFields);
    $("aiIntensity").addEventListener("change", applyExplorationIntensity);
    ["aiCrawlMode","aiScope","aiActions"].forEach((id) => $(id).addEventListener("change", () => {
      if ($("aiIntensity").value === "thorough") applyExplorationIntensity();
      else updateSetupSummary();
    }));
    $("advEnv").addEventListener("change", () => {
      $("advProdBox").hidden = $("advEnv").value !== "production";
      $("advStagingBox").hidden = $("advEnv").value !== "staging";
    });
    $("m-ai").addEventListener("input", updateSetupSummary);
    $("m-ai").querySelectorAll(".setup-sections a").forEach((link) => link.addEventListener("click", (event) => {
      event.preventDefault();
      $(link.getAttribute("href").slice(1)).scrollIntoView({block:"start",behavior:"smooth"});
    }));
    refreshAccountFields();
    refreshAiFields();
    applyProviderPrivacy();
    if (saved.providerChoiceVersion === 2 && chosen === saved.provider &&
        [...$("aiModel").options].some((o) => o.value === saved.model)) $("aiModel").value = saved.model;
    if ($("aiIntensity").value === "thorough") applyExplorationIntensity();
    else updateSetupSummary();
  }

  function bindProviderCards() {
    $("m-ai").querySelectorAll(".prov").forEach((button) => button.addEventListener("click", () => {
      chosen = button.dataset.id;
      $("m-ai").querySelectorAll(".prov").forEach((item) => item.classList.toggle("sel", item === button));
      refreshAiFields();
    }));
  }

  function refreshAccountFields() {
    const mode = $("aiAccountMode").value;
    $("aiCredentials").hidden = mode !== "existing";
    $("aiSignupField").hidden = mode !== "signup";
    $("aiAccountNote").textContent = mode === "existing" ? "The supplied test account is used for this run. Login must succeed before protected pages can be covered."
      : mode === "signup" ? "Qpilot looks for registration, creates a permitted test account when supported, then signs in. Missing signup or verification blocks are explained."
      : mode === "configured" ? "The local configured test account is used without exposing its password in this interface."
      : "Public pages only. Stored accounts and account creation will not be used.";
    updateSetupSummary();
  }

  function applyExplorationIntensity() {
    if (!$("aiIntensity")) return;
    const thorough = $("aiIntensity").value === "thorough";
    $("aiIntensityNote").hidden = !thorough;
    if (thorough) {
      // Full crawl: max_pages 0 → HARD_PAGE_CAP, site scope, repeated controls, ≥80 actions/page.
      $("aiCrawlMode").value = "full";
      $("aiScope").value = "site";
      $("aiActions").value = String(Math.max(80, Math.min(100, +$("aiActions").value || 80)));
    } else {
      // Leaving Thorough must drop Thorough-forced full/site/80 — Standard defaults only.
      const defaults = providerMeta.default_actions || 15;
      $("aiCrawlMode").value = "limited";
      $("aiScope").value = "site";
      $("aiActions").value = String(Math.min(100, Math.max(1, +defaults || 15)));
      if ($("aiPages")) $("aiPages").value = String(Math.max(1, +$("aiPages").value || 10));
    }
    updateSetupSummary();
  }

  function focusThoroughSetup() {
    if (timer) return;
    const apply = () => {
      if (!$("aiIntensity")) return;
      $("m-ai").querySelectorAll("button, input, select, textarea").forEach((x) => { x.disabled = false; });
      $("aiIntensity").value = "thorough";
      applyExplorationIntensity();
      const target = $("setupScope") || $("aiIntensity") || $("m-ai");
      target.scrollIntoView({ block: "start", behavior: "smooth" });
      $("aiIntensity").focus();
    };
    if ($("m-ai") && $("aiIntensity")) {
      apply();
      return;
    }
    if (!pendingSource) return;
    askForAi().then(apply);
  }

  function coverageReminderHtml(s, crawl, controlGaps) {
    const pagesCov = (s && s.pages_coverage) || {};
    const lim = (s && s.coverage_limitations) || {};
    const crawlInfo = crawl || (s && s.crawl) || {};
    const counts = (s && s.result_status_counts) || {};
    const cov = (s && s.coverage) || {};
    const android = s && (s.target_type === "android" || s.target_type === "mobile"
      || (Number.isFinite(cov.tested) && Number.isFinite(cov.total) && !cov.routes));
    if (android) {
      const unvisited = Array.isArray(cov.unvisited) ? cov.unvisited.length : +(cov.unvisited || 0) || 0;
      const early = s.early_stop || (s.interaction && s.interaction.stopped) || "";
      const tested = +(cov.tested || 0);
      const total = +(cov.total || 0);
      if (!unvisited && !early && !(total && tested < total) && !s.incomplete) return "";
      const bits = [];
      if (total) bits.push(tested + " of " + total + " discovered controls have passing evidence");
      if (unvisited) bits.push(unvisited + " discovered control(s) not reached");
      if (early) bits.push("stopped early: " + early);
      const detail = s.incomplete_reason || ("Coverage gaps remain: " + bits.join("; ")
        + ". This is not whole-app certification.");
      return `<div class="warn coverage-reminder" role="status"><b>Coverage reminder:</b> ${esc(detail)}` +
        `<div class="coverage-reminder-actions"><button type="button" class="secondary thorough-again" data-android="1">Run Thorough again</button></div></div>`;
    }
    const notVisited = +(pagesCov.not_visited ?? crawlInfo.not_visited_count ?? s.pages_not_visited ?? 0) || 0;
    const limitHit = !!(lim.partial || pagesCov.limit_reached || pagesCov.time_limit_reached
      || crawlInfo.limit_reached || crawlInfo.time_limit_reached
      || (lim.limits_hit && lim.limits_hit.length));
    const blocked = +(counts.BLOCKED || 0) || 0;
    const notTested = +(counts["NOT TESTED"] || 0) || 0;
    const controlMiss = +(controlGaps || 0) || 0;
    if (!notVisited && !limitHit && !blocked && !notTested && !controlMiss) return "";
    const bits = [];
    if (controlMiss) bits.push(controlMiss + " control(s) not tested");
    if (notVisited) bits.push(notVisited + " page(s) not visited");
    if (limitHit) bits.push("a safety budget or limit stopped further exploration");
    if (blocked) bits.push(blocked + " blocked");
    if (notTested && !controlMiss) bits.push(notTested + " not tested");
    const detail = lim.statement || ("Coverage gaps remain: " + bits.join("; ")
      + ". Unvisited and untested items stay listed in this report.");
    return `<div class="warn coverage-reminder" role="status"><b>Coverage reminder:</b> ${esc(detail)}` +
      `<div class="coverage-reminder-actions"><button type="button" class="secondary thorough-again">Run Thorough again</button></div></div>`;
  }

  function updateSetupSummary() {
    if (!$("aiRunSummary")) return;
    const thorough = $("aiIntensity") && $("aiIntensity").value === "thorough";
    const limited = $("aiCrawlMode").value === "limited";
    $("aiPageBudget").hidden = !limited;
    if ($("aiIntensityNote")) $("aiIntensityNote").hidden = !thorough;
    const area = $("aiScope").value === "site" ? "Whole website" : $("aiScope").value === "section" ? "URL section" : "One page";
    const account = $("aiAccountMode").selectedOptions[0].textContent;
    const provider = (providers || []).find((p) => p.id === chosen);
    const ai = provider ? (provider.id === "none" ? "Rules only, no AI interpretation" : provider.name + " / " + ($("aiModel").value || "choose a model")) : "Choose an AI engine or Rules only";
    const coverage = limited ? "up to " + $("aiPages").value + " pages" : "all discovered pages within safety budgets";
    $("aiRunSummary").textContent = (thorough ? "Thorough · " : "Standard · ") + area + " · " + coverage +
      " · " + account + " · " + ai + ". Unvisited pages and untested controls stay visible in the report.";
    $("aiScopeNote").classList.toggle("limited-scope", limited || $("aiScope").value !== "site" || +$("advDepth").value > 0);
  }

  function refreshAiFields() {
    const p = (providers || []).find((x) => x.id === chosen);
    const models = p ? (p.id === "ollama" ? p.installed || [] : p.models || []) : [];
    $("fModel").hidden = !p || p.id === "none";
    $("aiModel").innerHTML = models.map((m) => '<option value="' + esc(m) + '">' + esc(m) + '</option>').join("");
    $("fKey").hidden = !p || !p.key_env;
    $("aiKey").value = "";
    $("aiKey").placeholder = p && p.has_key ? "Configured locally; leave empty to use it" : "API key for this run only";
    $("aiFallbackField").hidden = !p || p.id === "none";
    $("aiReadiness").textContent = !p ? "Choose a ready AI engine, configure one, or explicitly select Rules only."
      : p.id === "none" ? "Rules only is selected. DOM exploration and template tests run locally; no AI interprets business behavior. Coverage gaps are reported."
      : p.id === "ollama" ? (p.running && models.length ? "Ready locally. Installed model: " + ($("aiModel").value || "") + "."
        : "Local AI is unavailable. Start Ollama and install a model, then Refresh. Choose Rules only if you want to continue without AI.")
      : p.has_key ? "Provider is configured. Its response is validated when called; page data is shared only under your approved cloud settings."
      : "This cloud provider needs an API key and approved cloud processing before it can be used.";
    updateSetupSummary();
  }

  // ------------------------------------------------------------ 2) start the run
  async function startRun() {
    if (!await standardReady()) return;
    if (chosen && !workflow.providerAllowed(chosen)) {
      $("aiNote").hidden = false;
      $("aiNote").textContent = "This AI provider is disabled by Privacy settings.";
      return;
    }
    const p = (providers || []).find((x) => x.id === chosen);
    const val = (id) => ($(id) ? $(id).value.trim() : "");
    const problems = [];  // setup checks with a clear message (the server checks the same again)
    const accountMode = $("aiAccountMode").value;
    if (!p) problems.push("Choose an AI engine or explicitly select Rules only.");
    if (p && p.id === "ollama" && (!p.running || !(p.installed || []).length) && !$("aiFallback").checked)
      problems.push("Selected local AI is unavailable. Refresh after starting it, choose Rules only, or explicitly allow fallback.");
    if (accountMode === "existing" && !(val("aiUser") && $("aiPass").value))
      problems.push("Existing account: enter both username and password.");
    if (accountMode === "signup" && !$("aiSignup").checked)
      problems.push("Confirm permission to create a test account, or choose another account method.");
    if (p && p.key_env && !p.has_key && !$("aiKey").value.trim()) problems.push(`Paste your ${p.name} API key, or choose Ollama / No AI.`);
    if (!$("aiAuth").checked) problems.push("Please confirm that you own this website or have permission to test it.");
    if (accountMode === "existing" && !!val("aiUser") !== !!$("aiPass").value) problems.push("Give both the test account's user name and its password (or neither).");
    if (val("advEnv") === "production" && !$("advProd").checked) problems.push("Tick the production confirmation, or choose Test / Staging.");
    if (!!val("advUserSel") !== !!val("advPassSel")) problems.push("Login boxes: give the user name box AND the password box (or neither).");
    if (problems.length) {
      $("aiNote").hidden = false;
      $("aiNote").textContent = problems.join(" ");
      return;
    }
    const thorough = $("aiIntensity") && $("aiIntensity").value === "thorough";
    if (thorough) applyExplorationIntensity();
    const fullCrawl = thorough || $("aiCrawlMode").value === "full";
    const standardActions = providerMeta.default_actions || 15;
    const actionsPerPage = Math.min(100, Math.max(thorough ? 80 : 1,
      +$("aiActions").value || (thorough ? 80 : standardActions)));
    const depthRaw = Math.max(0, +val("advDepth") || 0);
    // Thorough + unset depth → 12 for MCP parity; Standard keeps the advanced value (incl. 0).
    // Thorough keeps soft depth 0 (unlimited) — forcing 12 cut deep trees and hurt exploration.
    const maxDepth = depthRaw;
    const body = { workflow: "standard", privacy_mode: workflow.mode, source: pendingSource, max_pages: fullCrawl ? 0 : Math.max(1, +$("aiPages").value || 10),
                   crawl_scope: thorough ? "site" : $("aiScope").value, auth_mode: accountMode,
                   max_interactions_per_page: actionsPerPage,
                   // Full crawl alone must not imply Thorough; only Thorough (or an explicit checkbox) sets this.
                   explore_repeated_controls: !!thorough || !!($("aiExploreRepeated") && $("aiExploreRepeated").checked),
                   thorough: !!thorough,
                   allow_rules_fallback: $("aiFallback").checked,
                   show_browser: $("aiWatch").checked, fresh: $("aiFresh").checked,
                   execution_mode: $("aiWatch").checked ? "watch" : "fast", action_delay_ms: 1000,
                   authorized: true, allow_signup: accountMode === "signup" && $("aiSignup").checked, environment: val("advEnv") || "test",
                   production_confirmed: $("advProd").checked, max_depth: maxDepth,
                   writes_confirmed: val("advEnv") === "staging" && $("advWrites").checked,
                   allow_actions: val("advEnv") === "staging" ? val("advAllow") : "",
                   test_payment: val("advEnv") === "staging" && $("advPay").checked,
                   page_timeout_s: Math.min(300, Math.max(0, +val("advTimeout") || 0)),
                   login_url: val("advLoginUrl"), login_success_text: val("advSuccess"),
                   login_user_selector: val("advUserSel"), login_password_selector: val("advPassSel"),
                   login_submit_selector: val("advSubmitSel"), allowed_hosts: val("advHosts"),
                   exclude_paths: val("advExclude"), requirements: val("advReq"), record_video: $("advVideo").checked,
                   my_tests: $("myTests") ? $("myTests").value : null, review: !!($("myReview") && $("myReview").checked) };
    if ($("webContract") && $("webContract").value.trim()) {
      try { body.qa_contract = JSON.parse($("webContract").value); }
      catch (_) { $("aiNote").hidden = false; $("aiNote").textContent = "The QA contract must be valid JSON."; return; }
    }
    if (p) {
      body.llm_provider = p.id;
      body.llm_model = p.models.length ? $("aiModel").value : "";
      if ($("aiKey").value.trim()) body.api_key = $("aiKey").value.trim();
    }
    if (accountMode === "existing" && val("aiUser") && $("aiPass").value) {
      body.test_username = val("aiUser");
      body.test_password = $("aiPass").value;
    }
    if (accountMode === "existing" && val("aiTotp")) body.test_totp_secret = val("aiTotp");  // (this run only, never saved)
    savePrefs({ providerChoiceVersion: 2, provider: chosen, model: body.llm_model || "", pages: body.max_pages,
                crawlPrefsVersion: CRAWL_PREFS_VERSION, watch: body.show_browser,
                adv: { env: body.environment, depth: body.max_depth, timeout: body.page_timeout_s, video: body.record_video } });
    try {  // ask once, so we can tell the user when a long test finishes on another tab
      if (window.Notification && Notification.permission === "default") Notification.requestPermission();
    } catch (e) {}
    $("aiStart").disabled = true;
    const res = await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json", "X-Agentic-QA": "1" },
                                           body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      $("aiStart").disabled = false;
      $("aiNote").hidden = false;
      $("aiNote").textContent = data.detail || "Could not start the test.";
      return;
    }
    rememberAuthorized(pendingSource);
    $("aiPass").value = ""; $("aiKey").value = "";  // (not kept in the page once the run has them)
    $("m-ai").querySelectorAll("button, input, select, textarea").forEach((x) => (x.disabled = true));
    const aiName = p ? `${p.name}${body.llm_model ? " · " + body.llm_model : ""}` : "the AI set in .env";
    say(`<p>Starting now with <b>${esc(aiName)}</b>. Here's my plan; you can follow it in the <b>to-do list</b> on the right,
      every step gets a ✓ when it's done.${body.show_browser ? " A <b>Chrome window</b> will open so you can watch the website being tested." : ""}</p>`);
    beginJob(data, body.show_browser);
  }

  function beginJob(data, watching) {
    workflow.setWorkflow(data.workflow || "standard", true);
    document.body.dataset.setupState = "running";
    setWorkspaceMode("web");
    lockWorkspaceMode(true);
    mobileRun = false;
    job = data; since = 0; posted = { watching }; logLines = []; llmWarnings = 0; casesKey = "";
    psince = 0; livePages = []; pageStats = {};
    $("chatTitle").textContent = data.source;
    setStatus("Testing…", "");
    setTabTitle("⏳ Testing…");
    $("stopBtn").hidden = false;
    $("costBox").hidden = !data.llm || /^none/.test(data.llm);
    setComposer(false, "Testing… you can stop it at the top");
    applyUpdate(data);
    clearInterval(timer);
    timer = setInterval(poll, 900);
  }

  async function poll() {
    if (mobileRun) return pollMobile();
    if (!job) return;
    try {
      const res = await fetch(`/api/runs/${job.id}?since=${since}&psince=${psince}`);
      if (res.ok) applyUpdate(await res.json());
    } catch (e) { /* server busy - next tick */ }
  }

  async function stopRun() {
    if (!job) return;
    $("stopBtn").disabled = true;
    await fetch(`/api/runs/${job.id}/stop`, { method: "POST", headers: { "X-Agentic-QA": "1" } }).catch(() => {});
  }

  async function resumeIfRunning() {
    try {
      const d = await (await fetch("/api/runs/latest")).json();
      if (d && d.status === "running") {
        pendingSource = d.source;
        userSays(d.source);
        say("<p>This test is still running. I'll keep following it.</p>");
        if (d.target_type === "android") beginMobileJob(d);
        else beginJob(d, false);
      }
    } catch (e) {}
  }

  async function showReview(id) {
    const r = await fetch(`/api/runs/${id}/review`).then((x) => x.json()).catch(() => ({ questions: [] }));
    const qs = r.questions || [], cases = r.cases || [];
    if (!qs.length && !cases.length) return;
    const row = (q, n) => `<div class="review-q" data-tc="${esc(q.tc_id)}">
        <p><b>${n + 1}.</b> ${esc(q.question)} <span class="muted small">(${esc(q.title)})</span></p>
        ${q.choices.map((ch) => `<label class="tick"><input type="radio" name="rv${n}" value="${esc(ch)}"> <span>${esc(ch)}</span></label>`).join(" ")}
        ${q.choices.includes("should be") ? `<input type="text" class="rv-text" placeholder="what it should show" spellcheck="false">` : ""}
      </div>`;
    // every designed test case: untick to leave it out of this run (a staging run's cleanup always runs)
    const caseRow = (c) => `<label class="tick small"><input type="checkbox" class="rv-case" value="${esc(c.tc_id)}" checked ${c.fixed ? "disabled" : ""}>
        <span>${esc(c.title)} <span class="muted">· ${esc(c.feature || "")}${c.scenario ? " · " + esc(c.scenario) : ""}</span></span></label>`;
    say(`<div class="review-box"><p>🧐 <b>Before I write the scripts, please review the test cases.</b>
        I wait up to ${Math.round((r.timeout_s || 900) / 60)} minutes, then go on as designed.</p>
        ${qs.length ? `<p><b>${qs.length} question(s) only you can answer</b> <span class="muted small">(remembered for the next test of this website)</span></p>${qs.map(row).join("")}` : ""}
        ${cases.length ? `<details open><summary><b>${cases.length} test case(s)</b> <span class="muted small">– untick the ones to leave out of this run</span></summary>
          <div class="scroll" style="max-height:260px">${cases.map(caseRow).join("")}</div></details>` : ""}
        <label class="wide">Add your own tests in plain English (one per line - designed now and kept for this website)
          <textarea id="rvAdd" rows="2" spellcheck="false" placeholder="e.g. Open Products, filter by Women, every product shown is for women"></textarea></label>
        <button class="primary" id="reviewSend">Send</button> <span id="reviewNote" class="muted small"></span></div>`);
    $("reviewSend").addEventListener("click", async () => {
      const answers = {};
      document.querySelectorAll(".review-q").forEach((el) => {
        const pick = el.querySelector("input[type=radio]:checked");
        if (pick) answers[el.dataset.tc] = { answer: pick.value, text: (el.querySelector(".rv-text") || {}).value || "" };
      });
      const leave_out = [...document.querySelectorAll(".rv-case:not(:checked)")].map((x) => x.value);
      const add_tests = $("rvAdd").value.split("\n").map((x) => x.trim()).filter(Boolean);
      const res = await fetch(`/api/runs/${id}/review`, { method: "POST",
        headers: { "Content-Type": "application/json", "X-Agentic-QA": "1" }, body: JSON.stringify({ answers, leave_out, add_tests }) });
      $("reviewNote").textContent = res.ok ? `✓ Sent: ${Object.keys(answers).length} answer(s), ${leave_out.length} left out, ${add_tests.length} added - writing the scripts now.`
                                           : "Could not send.";
      $("reviewSend").disabled = res.ok;
    });
  }

  function setStatus(text, cls) {
    $("statusPill").hidden = !text;
    $("statusPill").textContent = text;
    $("statusPill").className = "pill " + (cls || "");
    const busy = /loading|testing|starting|waiting/i.test(text || "");
    if (busy) $("statusPill").setAttribute("aria-busy", "true");
    else $("statusPill").removeAttribute("aria-busy");
  }

  function showQualityStatus(summary) {
    const verdict = summary.verdict || "Outcome unavailable";
    setStatus(verdict, verdict === "Ready" ? "ok" : verdict === "Not Ready" ? "bad" : "warn");
  }

  // ------------------------------------------------------------ 3) live progress -> to-do ticks + chat messages
  function applyUpdate(d) {
    if (window.QpilotLive) window.QpilotLive.update(d);
    job = Object.assign(job || {}, d);
    since = d.next;
    logLines.push(...(d.lines || []));
    if (d.pnext != null) psince = d.pnext;
    if ((d.live_pages || []).length) {  // each page as it is opened + inspected: one live row per page
      livePages.push(...d.live_pages);
      renderPages();
    }
    const finished = d.status !== "running";
    const st = d.stages || {};
    renderTodo(st, finished, d);
    // the website asks for a one-time code / CAPTCHA: only a person may complete it (in the Chrome window)
    const h = d.human;
    if (h && h.what === "bot_check") {
      // a website's bot check (Cloudflare "Just a moment..."): only a person may complete it, on the Android device
      update("human", !h.done && !finished
        ? `<div class="warn">🔐 <b>The website shows a security check${h.kind ? " (" + esc(h.kind) + ")" : ""}.</b>
           Please complete it yourself in the <b>Android emulator window</b> - Qpilot never solves or bypasses these checks.
           I wait up to ${Math.round((h.wait_s || 180) / 60)} minutes, then continue when the real website appears.</div>`
        : h.ok ? `<p>🔐 Thank you - the security check was completed. Testing continues.</p>`
               : `<p class="muted">🔐 The security check was not completed in time - the report says what could not be tested.</p>`);
    } else if (h && !h.done && !finished) {
      update("human", `<div class="warn">🔐 <b>The website asks for ${h.what === "captcha" ? "a CAPTCHA" : "a one-time code (2-step verification)"}.</b>
        Please complete it yourself in the <b>Chrome window</b> - I never solve these. I wait up to ${Math.round((h.wait_s || 180) / 60)} minutes,
        then check that the login really worked and continue.</div>`);
    } else if (h) {
      update("human", h.ok ? `<p>🔐 Thank you - the login was completed by you and is verified. Testing continues behind the login.</p>`
                           : `<p class="muted">🔐 The code / CAPTCHA was not completed in time - only the public pages are tested.</p>`);
    }

    // the test asks you what it can't know (is what it saw correct? is a rule allowed?) - and waits for your answers
    if (d.review && !posted.review && job && job.id) {
      posted.review = 1;
      showReview(job.id);
    }

    const c = d.cost || {};
    $("costNow").textContent = usd(c.cost_usd);
    $("costCalls").textContent = `${c.calls || 0} AI calls · ${c.tokens || 0} tokens`;

    // AI timeouts / failures -> one friendly warning, updated as they happen
    const warn = (d.lines || []).filter((l) => /LLM failed|did not answer in time|AI advice skipped|explanation skipped/.test(l)).length;
    if (warn) {
      llmWarnings += warn;
      update("llmwarn", `<div class="warn">⚠ The AI was slow or failed ${llmWarnings} time(s) (e.g. a timeout). For those steps I used
        my built-in rules instead, so the test continues. Details are in the agent log.</div>`);
    }

    // what the tester decided to test: entire website / limited pages / specific page (backend/agents/discovery.py)
    const scopeLine = !posted.scope && (d.lines || []).map((l) => l.match(/\[discovery\] scope: (.+)$/)).find(Boolean);
    if (scopeLine) {
      posted.scope = 1;
      const [what, rest] = scopeLine[1].split(/ – (.*)/s);
      later(() => say(`<p>🔎 <b>${esc(what)}</b>${rest ? ` – ${esc(rest)}` : ""}</p>`));
    }
    // the website has a login: did the tester get in with the test account?
    const loginLine = !posted.login && (d.lines || []).map((l) => l.match(/\[discovery\] login: (.+)$/)).find(Boolean);
    if (loginLine) {
      posted.login = 1;
      const ok = /^Logged in/.test(loginLine[1]);
      later(() => say(ok ? `<p>🔑 ${esc(loginLine[1])}</p>` : `<div class="warn">🔑 ${esc(loginLine[1])}</div>`));
    }

    if (d.excel) setExcel(d.run);
    const done = (s) => st[s] === "done";
    const started = (s) => st[s] === "running" || st[s] === "done";
    if (done("setup") && !posted.setup && d.run) { posted.setup = 1; }
    if (done("discovery") && !posted.discovery) {
      posted.discovery = 1;
      later(() => say(`<p>✓ I found <b>${esc(d.pages ?? "the")} page(s)</b> on the website and took a screenshot of each one.</p>`));
    }
    if (started("test_design") && !posted.genCases) {
      posted.genCases = 1;
      later(() => say("<p>⏳ <b>Now designing the test cases</b> for every page and every feature found (pages behind the login first): journeys, feature tests, one large case per page, site-wide checks…</p>"));
    }
    if (done("test_design") && !posted.cases && d.run) { posted.cases = 1; const run = d.run; later(() => postTestCases(run, true)); }
    if (started("script_generator") && !posted.genScripts) {
      posted.genScripts = 1;
      later(() => say(`<p>⏳ <b>Writing the automation now…</b> <span class="muted">(tech stack: ${TECH_STACK})</span></p>`));
    }
    if (done("script_generator") && !posted.scripts) {
      posted.scripts = 1;
      const run = d.run;
      later(async () => {
        say(`<p>✓ I turned the test cases into <b>${esc(d.scripts ?? "")} automated test script(s)</b> (${TECH_STACK}).</p>`);
        if (run) await postCoverage(run);  // what the tests really use - and what they don't
      });
    }
    if (st.execution === "running" && !posted.exec) {
      posted.exec = 1;
      later(() => {
        say(execHtml(null), "exec");
        if (posted.watching) say("<p>👀 Watch the <b>Chrome window</b>: it's opening the website and running each test now.</p>");
      });
    }
    if (posted.exec && d.run && $("m-exec")) { loadCases(d.run); loadPages(d.run); }
    if (st.self_healing === "running" && !posted.heal) {
      posted.heal = 1;
      later(() => say("<p>Some test <b>scripts</b> broke (not the website). I'm repairing them and running them again, " +
                      "with the other tests of the same file – a repair is only kept when that run shows it works.</p>"));
    }

    if (finished) {
      clearInterval(timer); timer = null; lockWorkspaceMode(false);
      $("stopBtn").hidden = true; $("stopBtn").disabled = false;
      setComposer(true, "Test another website…");
      if (d.run && d.report_ready && d.status === "stopped") {  // stopped: the report of what was done until then
        setStatus("Stopped", "bad");
        setTabTitle("✗ Stopped");
        later(async () => {
          say(`<div class="warn">You stopped the test. Here is the report of what was tested until then –
            what was not reached is not tested, and not counted as passed.</div>`);
          if ($("m-exec")) await loadCases(d.run);
          await showReport(d.run, true);
        });
        loadHistory();
      } else if (d.run && d.report_ready) {
        setStatus("Loading results…", "");
        setTabTitle("✓ Done");
        const mins = Math.floor(d.elapsed / 60), secs = String(d.elapsed % 60).padStart(2, "0");
        notify("Testing completed", `${d.source || "Your website"} · ${mins}:${secs} min. The report is ready.`);
        later(async () => {
          say(`<div class="done-banner"><span class="big">✅</span><div><b>Testing completed</b>
            <span>The process ended in ${mins}:${secs} min. Review completed checks and coverage limits below.</span></div></div>`);
          if ($("m-exec")) await loadCases(d.run);  // final Passed / Failed for every test case
          await showReport(d.run, true);
        });
        loadHistory();
      } else {
        setStatus(d.status === "stopped" ? "Stopped" : "Failed", "bad");
        setTabTitle(d.status === "stopped" ? "✗ Stopped" : "✗ Failed");
        if (d.status !== "stopped") notify("Testing failed", `${d.source || "The test"} ended without a report.`);
        later(() => say(`<div class="warn">${d.status === "stopped" ? "You stopped the test." : "The test ended without a report."}</div>${logHtml()}`));
      }
    }
  }

  function renderTodo(st, finished, d) {
    const items = (d || job || {}).discovery_only ? TODO.filter((t) => ['open', 'pages', 'report'].includes(t.id)) : TODO;
    let doneCount = 0;
    $("todoList").innerHTML = items.map((t) => {
      const states = (((d || job || {}).discovery_only || (d || {}).report_view) && t.id === 'report' ? ['report'] : t.stages).map((s) => st[s]);
      let cls = "";
      if (states.some((s) => s === "running")) cls = "running";
      else if (states.every((s) => s === "done")) cls = "done";
      else if (states.some((s) => s === "done")) cls = "running";
      else if (finished) cls = job && job.status !== "done" ? "" : "skipped";
      if (cls === "done") doneCount++;
      let sub = "";
      if (d && t.id === "pages" && d.pages != null) sub = `${d.pages} page(s)`;
      if (d && t.id === "cases" && d.cases != null) sub = `${d.cases} test cases`;
      if (d && t.id === "scripts" && d.scripts != null && cls === "done") sub = `${d.scripts} script(s)`;
      if (t.id === "run" && posted.execText) sub = posted.execText;
      if (t.id === "heal" && cls === "skipped") sub = "not needed";
      return `<li class="${cls}"><span class="box"></span><span class="lbl">${esc(t.label)}${sub ? `<span class="sub">${esc(sub)}</span>` : ""}</span></li>`;
    }).join("");
    const relevant = items.filter((t) => !(finished && t.id === "heal" && !(st.self_healing))).length;
    $("todoBar").style.width = Math.round((doneCount / relevant) * 100) + "%";
    $("todoMeta").textContent = finished ? (job && job.status === "done" ? "✓ Completed" : job ? job.status : "") :
      Object.keys(st).length ? `${doneCount}/${relevant} done` : "Ready when you are";
  }

  // ------------------------------------------------------------ test cases (Excel) + live execution
  async function postTestCases(run, live) {
    const generation = chainGen;
    const current = () => generation === chainGen;
    const r = encodeURIComponent(run);
    let caseCount = 0;
    try {
      const response = await fetch(`/api/cases/${r}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const p = await response.json();
      if (!current()) return;
      if (!Array.isArray(p.cases) || typeof p.total !== "number") throw new Error("Invalid test case response");
      caseCount = p.cases.length;
      if (!caseCount) {
        const title = p.discovery_only ? "Exploration report" : live && !p.complete ? "Test cases are not ready yet" : "No test cases were generated";
        const detail = p.discovery_only
          ? "Pages and components were explored. Functional tests were not generated or run."
          : p.empty_reason || (live && !p.complete ? "Test design is still pending. No test case export is available yet." : "This run has no test cases to review. Check the report and run log for the reason.");
        say(`<div class="card result-empty" role="status"><span class="section-label">TEST CASES</span><h3>${title}</h3><p>${esc(detail)}</p></div>`);
        return;
      }
      const buttons = p.excel_available ? `<div class="actions"><button type="button" class="primary view-xl" data-run="${esc(run)}">View test cases</button>
        <a class="secondary" href="/api/excel/${r}/download">Download Excel</a></div>`
        : `<div class="actions"><a class="secondary" href="/api/cases/${r}/download">Download test cases (JSON)</a></div>`;
      const review = live ? `<div class="note review"><b>Review the test cases</b> while automation is prepared.</div>` : "";
      const large = p.cases.filter((c) => c.size === "large").length, small = p.cases.filter((c) => c.size === "small").length;
      const shown = p.cases.slice(0, 25);
      const rows = shown.map((c) => `<tr><td>${c.n}</td>
        <td>${c.size ? `<span class="size ${esc(c.size)}">${c.size === "large" ? "Large" : "Small"}</span>` : ""}</td>
        <td>${esc(c.title || c.id)}${c.steps > 1 ? ` <span class="muted small">· ${c.steps} steps</span>` : ""}</td>
        <td>${c.test_data ? `<code>${esc(c.test_data)}</code>` : '<span class="muted">—</span>'}</td>
        <td><span class="tagp ${esc(c.priority)}">${esc(c.priority)}</span></td></tr>`).join("");
      const feat = p.cases.filter((c) => /^feature_/.test(c.id)).length, blocked = p.cases.filter((c) => c.status === "Blocked").length;
      say(`<p>✓ I wrote <b>${p.total} test cases</b> and ${p.excel_available ? "saved them to Excel" : "prepared them for review"}` + (large || small
          ? `: <b>${large}</b> large end-to-end cases (journeys across pages and one case per page with everything on it),
             <b>${feat}</b> feature tests (filters, sorting, next page, wishlist, search…), <b>${small}</b> site-wide checks
             (pages open, no errors, pictures, every link, unusual values in every input box – only typed in, never sent)` +
            (blocked ? ` and <b>${blocked}</b> blocked actions (pay / order / delete / save… are never clicked without approval)` : "") + ".</p>"
          : ".</p>") + `
        <div class="card"><div class="scroll"><table class="mini"><tr><th>#</th><th>Size</th><th>Test case</th><th>Test data</th><th>Priority</th></tr>${rows}</table></div>
        ${p.total > shown.length ? `<p class="muted small">…and ${p.total - shown.length} more in the downloadable test cases.</p>` : ""}
        ${review}${buttons}</div>`);
    } catch (e) {
      if (current()) say(`<div class="warn" role="alert">Could not load test cases. Reopen this run from Recent runs to try again. No export has been confirmed.</div>`);
    }
    if (current() && !live && caseCount) await postCoverage(run);
  }

  // what was found on the pages and what gets tested - anything NOT tested is listed with the reason
  async function postCoverage(run) {
    const generation = chainGen;
    let cov;
    try {
      const res = await fetch(`/api/coverage/${encodeURIComponent(run)}`);
      cov = res.ok ? await res.json() : null;
    } catch (e) { cov = null; }
    if (generation !== chainGen || !cov || !cov.total) return;
    const missed = cov.pages.flatMap((p) => p.items.filter((i) => i.status !== "tested")
      .map((i) => ({ ...i, page: p.url.replace(/^https?:\/\/[^/]+/, "") || "/" })));
    const rows = missed.slice(0, 40).map((i) => `<tr><td>${esc(i.name)}</td><td class="muted">${esc(i.kind)}</td>
        <td class="muted">${esc(i.page)}</td><td>${esc(i.reason)}</td></tr>`).join("");
    const gapNote = missed.length
      ? coverageReminderHtml({ pages_coverage: {}, coverage_limitations: {}, result_status_counts: {} }, {}, missed.length)
      : "";
    say(`<p>🧭 <b>Coverage:</b> I found <b>${cov.total}</b> controls on ${cov.pages.length} page(s) and
        <b>${cov.tested}</b> of them get a generated script${missed.length
          ? ` — <b class="bad-count">${missed.length} control(s) not tested</b>.`
          : " – that's all of them ✅"}</p>
      <p class="muted small">Observed/scripted controls are not the same as business-verified checks.</p>
      ${(cov.notes || []).map((n) => `<div class="warn">⚠ ${esc(n)}</div>`).join("")}
      ${gapNote}
      ${missed.length ? `<div class="card"><p><b>⛔ Not tested (${missed.length})</b> – and why:</p>
        <div class="scroll"><table class="mini"><tr><th>Control</th><th>Kind</th><th>Page</th><th>Why not</th></tr>${rows}</table></div>
        ${missed.length > 40 ? `<p class="muted small">…and ${missed.length - 40} more in the Excel file (sheet "Coverage").</p>` : ""}
        <p class="muted small">The full list (tested and not tested) is in the Excel file, sheet "Coverage".</p>
        <div class="actions"><button type="button" class="secondary thorough-again">Run Thorough again</button></div></div>` : ""}`);
  }

  // ------------------------------------------------------------ Excel viewer (the real .xlsx, read-only)
  async function openExcel(run) {
    let d;
    $("excelModal").setAttribute("aria-busy", "true");
    try {
      const res = await fetch(`/api/excel/${encodeURIComponent(run)}`);
      if (!res.ok) throw new Error();
      d = await res.json();
    } catch (e) {
      $("excelModal").setAttribute("aria-busy", "false");
      alert("The Excel file is not ready yet. Wait until test design finishes, then try again.");
      return;
    }
    excelData = d; excelSheet = 0;
    $("excelFile").textContent = `${d.name || "test_cases.xlsx"} · ${run}`;
    $("excelDl").href = `/api/excel/${encodeURIComponent(run)}/download`;
    $("sheetTabs").innerHTML = d.sheets.map((s, i) =>
      `<button type="button" data-i="${i}" aria-label="Show sheet ${esc(s.name)}">${esc(s.name)} (${s.rows.length})</button>`).join("");
    $("excelSearch").value = "";
    fillFilter();
    renderSheet();
    $("excelModal").hidden = false;
    $("excelModal").setAttribute("aria-busy", "false");
    $("excelSearch").focus();
  }

  function statusCol(sheet) {
    const i = sheet.headers.indexOf("Execution Status");
    return i >= 0 ? i : sheet.headers.indexOf("Result");
  }

  function fillFilter() {  // the statuses that are really in this sheet
    const sheet = excelData.sheets[excelSheet], rc = statusCol(sheet);
    const vals = rc >= 0 ? [...new Set(sheet.rows.map((r) => r[rc]).filter(Boolean))] : [];
    $("excelFilter").innerHTML = '<option value="">All statuses</option>' + vals.map((v) => `<option>${esc(v)}</option>`).join("");
    $("excelFilter").hidden = !vals.length;
  }

  function renderSheet() {
    if (!excelData) return;
    const sheet = excelData.sheets[excelSheet], rc = statusCol(sheet);
    $("sheetTabs").querySelectorAll("button").forEach((b) => b.classList.toggle("active", +b.dataset.i === excelSheet));
    const q = $("excelSearch").value.toLowerCase(), f = $("excelFilter").value;
    const rows = sheet.rows.filter((r) => (!f || r[rc] === f) && (!q || r.join(" ").toLowerCase().includes(q)));
    $("sheet").innerHTML = `<thead><tr>${sheet.headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>` +
      rows.map((r) => `<tr>${r.map((v, i) => i === rc
        ? `<td class="st st-${esc(String(v).split(" ")[0])}">${esc(v)}</td>`
        : `<td>${esc(v)}</td>`).join("")}</tr>`).join("") + "</tbody>";
    const counts = {};
    if (rc >= 0) sheet.rows.forEach((r) => (counts[r[rc]] = (counts[r[rc]] || 0) + 1));
    $("excelCount").textContent = `Showing ${rows.length} of ${sheet.rows.length} rows` +
      (rc >= 0 ? " · " + Object.entries(counts).map(([k, n]) => `${n} ${k}`).join(" · ") : "");
  }

  function closeExcel() { $("excelModal").hidden = true; }

  $("sheetTabs").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    excelSheet = +b.dataset.i;
    fillFilter();
    renderSheet();
  });
  $("excelSearch").addEventListener("input", renderSheet);
  $("excelFilter").addEventListener("change", renderSheet);
  $("excelClose").addEventListener("click", closeExcel);
  $("excelModal").addEventListener("click", (e) => e.target.id === "excelModal" && closeExcel());
  document.addEventListener("keydown", (e) => e.key === "Escape" && !$("excelModal").hidden && closeExcel());

  // ------------------------------------------------------------ page by page: verified -> inspected -> tested
  async function loadPages(run) {  // each page's test results (live while the tests run, final afterwards)
    if (pagesBusy) return;
    pagesBusy = true;
    const generation = chainGen;
    try {
      const res = await fetch(`/api/pages/${encodeURIComponent(run)}`);
      if (!res.ok) return;
      const data = await res.json();
      if (generation !== chainGen) return;
      pageStats = Object.fromEntries(data.pages.map((p) => [p.url, p]));
      if (!livePages.length) livePages = data.pages;  // (an earlier test, opened from "Recent tests")
      renderPages();
    } catch (e) {} finally { pagesBusy = false; }
  }

  // the feature registry: every feature found, and how far it got (discovered -> tested -> verified, or why not)
  function registryHtml(r) {
    const F = r.features || {}, P = r.pages || {};
    const stat = (v, l, cls = "") => `<div class="stat ${cls}"><b>${esc(v ?? 0)}</b><span>${esc(l)}</span></div>`;
    return `<h4>🧩 Features <span class="muted small">– every feature / control found, with its own result</span></h4>
      <div class="stats">${stat(F.discovered ?? 0, "features discovered")}${stat(F.tested ?? 0, "tested")}
        ${stat(F.verified ?? 0, "verified (a checked result passed)", "good")}${stat(F.failed ?? 0, "failed", F.failed ? "bad" : "")}
        ${stat(F.blocked ?? 0, "blocked (protected)")}${stat(F.needs_login ?? 0, "need a test account")}
        ${stat(F.clicked_only ?? 0, "only clicked (no result checked)", F.clicked_only ? "bad" : "")}
        ${stat(F.inconclusive ?? 0, "inconclusive (no result could be established)", F.inconclusive ? "bad" : "")}
        ${stat(F.test_generated ?? 0, "test generated, did not run", F.test_generated ? "bad" : "")}
        ${stat(F.unresolved ?? 0, "not tested (the report says why)", F.unresolved ? "bad" : "")}</div>
      <p class="muted small">Pages ${P.discovered ?? 0} discovered · ${P.inspected ?? 0} inspected · ${P.tested ?? 0} tested ·
        ${P.verified ?? 0} verified${P.sampled_out ? ` · ${P.sampled_out} more pages of the same pattern (a sample was tested)` : ""}.
        Counted: ${esc(r.denominator || "")}.</p>`;
  }

  function renderPages() {
    if (!livePages.length) return;
    const TYPE = { listing: "list", product: "product", order_detail: "order", content: "page" };
    const auth = livePages.filter((p) => p.auth).length;
    const rows = livePages.map((p) => {
      const s = pageStats[p.url] || {};
      const path = (p.url || "").replace(/^https?:\/\/[^/]+/, "") || "/";
      const state = p.failed ? '<span class="tagp high">could not open</span>'
        : p.needs_permission ? '<span class="tagp medium">needs other permissions</span>' : "✓ opened";
      const tests = s.cases ? [s.passed && `✓ ${s.passed}`, (s.failed || s.flaky) && `✗ ${(s.failed || 0) + (s.flaky || 0)}`,
        s.blocked && `⛔ ${s.blocked}`, s.inconclusive && `? ${s.inconclusive}`, s.skipped && `– ${s.skipped}`,
        (s.pending || s.not_run) && `… ${(s.pending || 0) + (s.not_run || 0)}`].filter(Boolean).join(" · ") : "—";
      const feats = (p.features || []).filter((f) => f !== "protected").slice(0, 5).map((f) => `<span class="size small">${esc(f)}</span>`).join(" ");
      return `<tr><td>${p.n}</td>
        <td>${p.auth ? "🔒 " : ""}<b>${esc((p.title || path).slice(0, 50))}</b><br><span class="muted small">${esc(path.slice(0, 60))}</span></td>
        <td>${esc(TYPE[p.type] || p.type || "")}</td><td>${state}</td>
        <td class="small">${p.buttons ?? 0} buttons · ${p.inputs ?? 0} boxes · ${p.forms ?? 0} forms
          ${p.learned ? `<br>🧪 learned what ${p.learned} control(s) do` : ""}${p.revealed ? ` · ${p.revealed} revealed by an action` : ""}
          ${feats ? "<br>" + feats : ""}</td>
        <td class="small">${tests}</td></tr>`;
    }).join("");
    const last = livePages[livePages.length - 1];
    update("pages", `<p>🔎 <b>Page by page</b> – ${livePages.length} page(s) opened and inspected${auth ? `, <b>${auth} behind the login</b>` : ""}
        ${job && job.status === "running" && last && last.queue != null ? ` · ${last.queue} more waiting` : ""}.
        Each page: <b>verified</b> (it opens) → <b>inspected</b> (every control, its type and features) → <b>tested</b>.</p>
      <div class="card"><div class="scroll"><table class="mini"><tr><th>#</th><th>Page</th><th>Type</th><th>Verified</th><th>Inspected</th><th>Tests</th></tr>
      ${rows}</table></div><p class="muted small">🔒 = behind the login · ✓ passed · ✗ failed · ⛔ blocked (protected action) · ? inconclusive · … waiting</p></div>`);
  }

  async function loadCases(run) {
    if (casesBusy) return;
    casesBusy = true;
    const generation = chainGen;
    try {
      const res = await fetch(`/api/cases/${encodeURIComponent(run)}`);
      if (!res.ok) return;
      const txt = await res.text(), key = txt + (timer ? "|live" : "");
      if (generation !== chainGen) return;
      if (key === casesKey) return;  // nothing changed: don't redraw (no flicker, keeps the scroll)
      casesKey = key;
      update("exec", execHtml(JSON.parse(txt)));
    } catch (e) {} finally { casesBusy = false; }
  }

  function execHtml(p) {
    if (!p || !p.total) return timer
      ? `<p>Waiting for test cases...</p><div class="typing"><i></i><i></i><i></i></div>`
      : `<div class="note">No functional tests were run.</div>`;
    const icon = { Passed: "✓", Failed: "✗", Flaky: "~", Running: "◌", Skipped: "–", "Not run": "–", "Not automated": "–",
                   Inconclusive: "?", Blocked: "⛔" };
    const label = { Pending: "waiting", Automated: "waiting", Running: "running…", "Not automated": "no script" };
    const L = p.links || {};
    const all = p.total, done = p.done;
    posted.execText = `${p.done}/${p.total} test cases · ${p.passed} passed · ${p.failed} failed`;
    const linkCase = p.cases.some((c) => c.id === "site_links");  // links are one of the 15 test cases
    const linkProgress = (c) => c.id === "site_links" && L.total && L.done < L.total && L.done ? `${L.done}/${L.total} links` : "";
    // the steps of a test case: ticking live while it runs (open), the finished ones folded (a failure: open)
    const stepList = (steps, test) => `<ol class="steps">${steps.map((s) => `<li class="${s.ok === false ? "bad" : s.ok ? "ok" : ""}">
        <span>${s.ok === false ? "✗" : s.ok ? "✓" : "·"}</span> ${esc(s.text)}<i>${s.t != null ? ` ${esc(s.t)} s` : ""}</i></li>`).join("")}</ol>
        ${test ? `<span class="muted small">${esc(test)}</span>` : ""}`;
    const steps = (c) => c.steps_live && c.steps_live.length
      ? `<div class="ce live">${stepList(c.steps_live, c.steps_test)}</div>`
      : c.steps_done && c.steps_done.length
        ? `<details class="ce" data-details-key="${esc(c.id)}" ${c.status === "Failed" ? "open" : ""}><summary>${c.steps_done.length} step(s)
            ${c.status === "Failed" ? "- where it failed" : ""}</summary>${stepList(c.steps_done, c.steps_test)}</details>` : "";
    const list = p.cases.map((c) => `<div class="case ${esc(c.status.split(" ")[0])}" data-scroll-key="case:${esc(c.id)}"><span class="ci">${icon[c.status] || "○"}</span>
        <span class="ct" title="${esc(c.title)}">${c.size ? `<span class="size ${esc(c.size)}">${c.size === "large" ? "Large" : "Small"}</span> ` : ""}${esc(c.title || c.id)}${c.size ? "" : ` <span class="muted small">· ${esc(c.page)}</span>`}</span>
        <span class="cs">${esc(linkProgress(c) || label[c.status] || c.status)}</span>
        ${c.status === "Failed" && c.detail ? `<span class="ce" title="${esc(c.detail)}">${esc(c.detail)}</span>` : ""}
        ${c.status === "Running" && c.detail ? `<span class="ce why">${esc(c.detail)}</span>` : ""}
        ${c.status === "Not automated" && c.detail ? `<span class="ce why" title="${esc(c.detail)}">${esc(c.detail)}</span>` : ""}
        ${steps(c)}</div>`).join("");
    const links = L.total && !linkCase ? `<div class="case ${L.done < L.total ? (L.done ? "Running" : "") : L.broken ? "Failed" : "Passed"}">
        <span class="ci">🔗</span><span class="ct">Every link on the website (${L.total})</span>
        <span class="cs">${L.done < L.total ? `${L.done}/${L.total}` : L.broken ? `${L.broken} broken` : "all OK"}</span></div>` : "";
    return `<p>Execution progress: <b>${esc(posted.execText)}</b>${L.total ? ` · links ${L.done}/${L.total}` : ""}</p>
      <div class="card"><div class="bar"><i style="width:${all ? Math.round((done / all) * 100) : 0}%"></i></div>
      <div class="cases">${list}${links}</div></div>`;
  }

  // ------------------------------------------------------------ 4) final report
  async function showReport(run, live) {
    const generation = chainGen;
    const res = await fetch(`/api/report/${encodeURIComponent(run)}`);
    if (generation !== chainGen) return;
    if (!res.ok) throw new Error("Report could not be loaded");
    const d = await res.json();
    if (generation !== chainGen) return;
    document.body.dataset.setupState = "results";
    const s = d.summary || {}, c = d.cost;
    showQualityStatus(s);
    if (s.discovery_only || s.mode === "discovery") {
      setExcel(null);
      reports[run] = s;
      const crawl = d.crawl || s.crawl || {};
      const exploration = crawl.exploration || {};
      const pagesCov = s.pages_coverage || {};
      const lim = s.coverage_limitations || {};
      say(`<div class="card exploration-result">
        <span class="section-label">EXPLORATION REPORT</span><h2>Pages and components explored</h2>
        <p>Functional tests were not generated or run. This report shows what was discovered — not PASS/FAIL evidence for release.</p>
        ${coverageReminderHtml(s, crawl)}
        <p class="muted small">Observed/scripted controls are not the same as business-verified checks.</p>
        <div class="stats"><div class="stat"><b>${esc(pagesCov.discovered ?? ((crawl.visited ?? s.pages ?? 0) + (crawl.not_visited_count ?? 0)))}</b><span>pages discovered</span></div>
          <div class="stat"><b>${esc(pagesCov.visited ?? crawl.visited ?? s.pages ?? 0)}</b><span>pages visited</span></div>
          ${d.components_count != null ? `<div class="stat"><b>${esc(d.components_count)}</b><span>components observed</span></div>` : ""}
          <div class="stat"><b>${esc(pagesCov.not_visited ?? crawl.not_visited_count ?? 0)}</b><span>pages not visited</span></div></div>
        ${lim.statement || exploration.statement ? `<p>${esc(lim.statement || exploration.statement)}</p>` : ""}
        <div class="note">${esc(lim.limitation || exploration.limitation || "Discovery is not proof that every component state or business workflow was tested. This never claims the entire site was tested.")}</div>
        <div class="actions">${d.components_report ? `<a class="primary" target="_blank" rel="noopener" href="${esc(d.components_report)}">View component inventory</a>` : ""}
          ${d.report_html ? `<a class="secondary" target="_blank" rel="noopener" href="${esc(d.report_html)}">Open exploration report</a>` : ""}</div></div>`, "report");
      if (d.components_report) { $("actComponents").href = d.components_report; $("actComponents").hidden = false; }
      if (d.report_html) { $("actReport").href = d.report_html; $("actReport").hidden = false; }
      $("todoActions").hidden = !(d.components_report || d.report_html);
      renderTodo({setup:"done",discovery:"done",report:"done"}, true, {...s, discovery_only:true});
      $("todoMeta").textContent = "Exploration only";
      setStatus("Exploration only", "");
      await loadPages(run);
      if (generation === chainGen) { $("thread").scrollTop = 0; stick = false; $("jumpBtn").hidden = true; }
      return;
    }
    if (!live) {
      const recorded = {report:"done"};
      if (s.pages) { recorded.setup = "done"; recorded.discovery = "done"; }
      if (s.test_cases) recorded.test_design = "done";
      if (s.scripts) recorded.script_generator = "done";
      if (s.tests) recorded.execution = "done";
      if (s.healed) recorded.self_healing = "done";
      renderTodo(recorded, true, {...s, report_view:true});
      $("todoMeta").textContent = "Saved report";
      await loadPages(run);
      if (generation !== chainGen) return;
      await postTestCases(run, false);
      if (generation !== chainGen) return;
      await loadCases(run);
    } else {
      await loadPages(run);
    }
    if (generation !== chainGen) return;
    setExcel(d.excel ? run : null);
    if (d.report_html) { $("actReport").href = d.report_html; $("actReport").hidden = false; $("todoActions").hidden = false; }
    $("actComponents").hidden = !d.components_report;
    if (d.components_report) { $("actComponents").href = d.components_report; $("todoActions").hidden = false; }

    const stat = (v, l, cls = "") => `<div class="stat ${cls}"><b>${esc(v ?? 0)}</b><span>${esc(l)}</span></div>`;
    let cost = "";
    if (c && c.provider && c.provider !== "none") {
      cost = `<h4>AI cost (${esc(c.provider)}${c.model ? " · " + esc(c.model) : ""})</h4><div class="stats">
        ${stat(usd(c.cost_usd), "overall cost of the run")}
        ${stat(usd(c.avg_cost_per_case_usd), "per test case, end-to-end")}
        ${stat(usd(c.cost_per_100_cases_usd ?? (c.avg_cost_per_case_usd || 0) * 100), "per 100 test cases")}
        ${stat(c.calls + (c.failed_calls ? ` (${c.failed_calls} failed)` : ""), "AI calls", c.failed_calls ? "bad" : "")}</div>
        <p class="muted small">${esc(c.note || "")}</p>`;
    } else if (c) {
      cost = `<h4>AI cost</h4><p class="muted small">No AI was used in this run, so the AI cost is $0.00.</p>`;
    }
    const PRIO = { critical: "Fix first", high: "Fix first", medium: "Should fix", low: "Nice to fix" };
    const fixes = (d.fixes || []).slice(0, 8).map((x, i) => `<div class="fix"><span class="tagp ${esc(x.priority)}">${i + 1}. ${esc(PRIO[x.priority] || x.priority)}</span>
        <b>${esc(x.title)}</b>${x.count > 1 ? ` <span class="muted">×${x.count}</span>` : ""}
        ${x.why ? `<div class="why"><b>Why it matters:</b> ${esc(x.why)}</div>` : ""}
        <div class="how"><b>How to fix:</b> ${esc(x.fix)}</div>
        ${codeHtml(x.code)}</div>`).join("");
    const h = s.headline || { emoji: "", title: s.verdict, text: (s.reasons || []).join(" ") };
    const good = (s.working_well || []).map((g) => `<li>${esc(g)}</li>`).join("");
    reports[run] = s;
    // the run's numbers - one calculation (metrics.json); an older run has none: its own summary fields are shown
    const M = s.metrics || {}, TC = M.test_cases, ST = M.single_tests, FD = M.findings;

    // why the verdict is what it is: the release gates (fixed rules, never the AI)
    const GATE = { pass: "✓ pass", fail: "✗ fail", missing: "? no evidence", risk: "! risk" };
    const gateItems = (s.gates || []).map((g) => `<li><span class="gate ${esc(g.status)}">${GATE[g.status] || esc(g.status)}</span>
        <span><b>${esc(g.name)}</b><br><span class="muted small">${esc(g.detail)}</span></span></li>`).join("");
    const gatesHtml = gateItems ? `<h4>🚦 Release gates <span class="muted small">– the verdict is calculated from these rules, not by the AI</span></h4>
        <ul class="gates">${gateItems}</ul>` : "";
    // three different coverages - never one mixed percentage
    const cv = s.coverage;
    const P = (cv && cv.pages) || null;
    const androidCov = s.target_type === "android" || s.target_type === "mobile"
      || (cv && Number.isFinite(cv.tested) && Number.isFinite(cv.total) && !cv.routes);
    const unvisitedN = Array.isArray(cv && cv.unvisited) ? cv.unvisited.length
      : (cv && cv.unvisited != null ? +cv.unvisited : 0) || 0;
    const earlyStop = s.early_stop || (s.interaction && s.interaction.stopped) || "";
    const androidCovHtml = androidCov && cv ? `<h4>Coverage <span class="muted small">– Android (bounded, not whole-app proof)</span></h4>
      <div class="stats">
        ${stat(cv.screens ?? s.screens_visited ?? s.pages, "screens visited")}
        ${stat(`${cv.tested ?? 0} / ${cv.planned ?? 0}`, "controls with passing evidence / planned")}
        ${stat(cv.total ?? 0, "controls discovered on visited screens")}
        ${stat(unvisitedN, "discovered controls not reached", unvisitedN ? "bad" : "")}</div>
      ${earlyStop ? `<div class="warn" role="status"><b>Stopped early:</b> ${esc(earlyStop)}</div>` : ""}
      ${s.incomplete_reason ? `<p class="small muted">${esc(s.incomplete_reason)}</p>` : ""}
      <p class="small muted">No whole-app accuracy percentage is claimed. Use Thorough, test login, and approved flows to cover more on the next run.</p>` : "";
    const covHtml = androidCovHtml || (cv && cv.routes ? `<h4>Coverage <span class="muted small">– discovered → inspected → tested → verified</span></h4>
      ${P && P.discovered != null ? `<div class="stats">${stat(P.discovered, "pages discovered")}${stat(P.inspected, "pages inspected")}
        ${stat(P.tested, "pages tested")}${stat(P.verified, "pages verified (a test passed)", "good")}
        ${stat(P.logged_in, "behind the login")}${stat(P.needs_permission, "need other permissions")}</div>` : ""}
      <div class="stats">
        ${stat(`${cv.routes.visited}/${cv.routes.found}`, "pages visited / found" + (cv.routes.limit_reached ? " – STOPPED AT THE PAGE LIMIT" : ""), cv.routes.limit_reached ? "bad" : "")}
        ${stat(`${cv.components.tested}/${cv.components.found}`, "controls tested / found")}
        ${stat(`${cv.execution.executed}/${cv.execution.cases}`, "test cases run / designed")}
        ${cv.features ? stat(`${cv.features.passed}/${cv.features.tests}`, `feature tests passed (${cv.features.found} features found)`) : ""}
        ${stat(cv.execution.blocked || 0, "blocked (protected actions)")}
        ${stat(cv.execution.inconclusive || 0, "inconclusive (checked nothing)", cv.execution.inconclusive ? "bad" : "")}</div>
      ${(cv.journeys || []).length ? `<p class="small"><b>User journeys:</b> ${cv.journeys.map((j) => `${j.status === "Passed" ? "✓" : j.status === "Failed" ? "✗" : "•"} ${esc(j.title)}`).join(" · ")}</p>` : ""}
      ${cv.registry ? registryHtml(cv.registry) : ""}` : "");
    // regression: compared with the last run of this website
    const cmp = d.comparison;
    const moved = cmp && cmp.previous_run ? (cmp.cases || []).filter((c) => ["newly failing", "fixed", "still failing"].includes(c.change)) : [];
    const cmpHtml = cmp && cmp.previous_run ? `<h4>🔁 Compared with the last run</h4>
        <p class="small">Last run: <b>${esc(cmp.previous_run)}</b> (${esc(cmp.previous_verdict)}) ·
          ${Object.entries(cmp.counts || {}).map(([k, n]) => `${n} ${esc(k)}`).join(" · ")}</p>
        ${moved.length ? `<div class="scroll"><table class="mini"><tr><th>Change</th><th>Test case</th><th>Before → now</th></tr>
          ${moved.slice(0, 12).map((c) => `<tr><td>${esc(c.change)}</td><td>${esc(c.title)}</td><td>${esc(c.before || "–")} → ${esc(c.after || "–")}</td></tr>`).join("")}
        </table></div>` : ""}` : "";
    // the look of the pages vs. the approved look (visual check): a change is for a person to judge, not a bug by itself
    const V = d.visual, VC = (V && V.counts) || {};
    const vChanged = V ? (V.pages || []).filter((p) => p.status === "changed") : [];
    const visualHtml = !V ? "" : V.first_run
      ? `<h4>🖼 Visual check</h4><p class="small muted">The look of ${esc(VC.new || 0)} page(s) was saved as the approved look - the next run compares with it.</p>`
      : `<h4>🖼 Visual check <span class="muted small">– compared with the approved look; a change is for you to judge, not a bug by itself</span></h4>
        <p class="small">${esc(VC.compared || 0)} page(s) compared · <b>${esc(VC.changed || 0)} changed</b> · ${esc(VC.same || 0)} the same · ${esc(VC.new || 0)} new${VC.approved ? ` · ${esc(VC.approved)} approved` : ""}</p>
        ${vChanged.slice(0, 10).map((p) => `<div class="small"><b>${esc(p.title || p.url)}</b> <span class="muted">${esc(p.key)}</span>
          <ul>${Object.entries(p.widths || {}).flatMap(([w, r]) => (r.changes || []).map((c) => `<li>${esc(w)}: ${esc(c.detail)}</li>`)).join("")}</ul>
          ${Object.entries(p.widths || {}).filter(([, r]) => r.diff_shot).map(([w, r]) => `<a href="/runs/${encodeURIComponent(run)}/${esc(r.diff_shot)}" target="_blank">${esc(w)}: what changed (red)</a>`).join(" · ")}</div>`).join("")}
        ${vChanged.length ? `<div class="actions"><button type="button" class="secondary approve-visual" data-run="${esc(run)}">✓ Approve the new look (${vChanged.length} page${vChanged.length > 1 ? "s" : ""})</button></div>` : ""}`;
    // the bugs and open questions a test found: after a fix, re-check one - only its test runs again
    const bugs = (d.failures || []).filter((f) => f.source === "test" && f.nodeid && RECHECKABLE.includes(f.category));
    const lastCheck_ = (n) => { const h = (d.recheck || {})[n]; return h && h.length ? h[h.length - 1] : null; };
    const bugsHtml = bugs.length ? `<h4>🐞 Bugs and open questions <span class="muted small">– after a fix, re-check one: only its test runs again</span></h4>
      ${bugs.slice(0, 20).map((f) => `<div class="fix"><span class="tagp ${esc(f.severity)}">${esc(f.severity)}</span>
          <b>${esc((f.bug && f.bug.title) || f.explanation || f.test)}</b> <span class="muted small">${esc(f.category_name || f.category)}</span>
          <div class="small muted">${esc(f.page_url || "")}</div>
          <div class="rc-out small">${recheckText(lastCheck_(f.nodeid))}</div>
          <button type="button" class="secondary recheck" data-run="${esc(run)}" data-id="${esc(f.id)}" data-node="${esc(f.nodeid)}">🔁 Re-check</button></div>`).join("")}` : "";
    const I = d.integrations;
    const sentHtml = I ? `<p class="small">📣 ${I.slack ? `Slack: ${I.slack.sent ? "message sent" : esc(I.slack.why || I.slack.error || "not sent")}` : ""}
        ${I.slack && I.jira ? " · " : ""}${I.jira ? `Jira: ${esc((I.jira.created || []).length)} issue(s) created${(I.jira.created || []).length ? ` (${esc(I.jira.created.join(", "))})` : ""}${(I.jira.errors || []).length || I.jira.error || I.jira.why ? ` - ${esc((I.jira.errors || [])[0] || I.jira.error || I.jira.why)}` : ""}` : ""}</p>` : "";
    const loginWarn = s.login_outcome && !["success", "not_required"].includes(s.login_outcome)
      ? `<div class="warn">🔑 ${esc(s.login_note)}</div>` : "";

    say(`<p>${live ? "All done! " : ""}Here is the <b>final report</b>:</p>
      <div class="card">
        <div class="verdict" style="--vc:${VERDICT_COLOR[s.verdict] || "#64748b"}">
          <div class="v-row"><span class="v-emoji">${esc(h.emoji)}</span><div><b>${esc(h.title)}</b><p>${esc(h.text)}</p></div>
          ${s.pass_rate != null ? `<div class="v-rate" title="${esc(M.headline ? M.headline.denominator : "")}"><b>${esc(s.pass_rate)}%</b><span>${M.headline ? `functional test cases passed (${esc(M.headline.passed)} of ${esc(M.headline.of)})` : "passed"}</span></div>` : ""}</div></div>
        ${coverageReminderHtml(s, d.crawl || s.crawl)}
        <p class="muted small">Observed/scripted controls are not the same as business-verified checks.</p>
        ${(s.ai_warnings || []).map(warning => `<div class="warn">${esc(warning)}</div>`).join("")}
        ${good ? `<h4>✅ What works well</h4><ul class="goodlist">${good}</ul>` : ""}
        ${s.result_status_counts ? `<div class="stats">
          ${stat(s.result_status_counts.PASS, "PASS", "good")}
          ${stat(s.result_status_counts.FAIL, "FAIL", s.result_status_counts.FAIL ? "bad" : "")}
          ${stat(s.result_status_counts.BLOCKED, "BLOCKED")}
          ${stat(s.result_status_counts.SKIPPED, "SKIPPED")}
          ${stat(s.result_status_counts["NOT TESTED"], "NOT TESTED")}
          ${stat(s.result_status_counts.INCONCLUSIVE, "INCONCLUSIVE", s.result_status_counts.INCONCLUSIVE ? "bad" : "")}</div>` : ""}
        <div class="stats">
          ${stat(s.pages_visited ?? s.pages, "pages visited")}
          ${s.pages_not_visited != null ? stat(s.pages_not_visited, "pages not visited", s.pages_not_visited ? "bad" : "") : ""}
          ${TC ? stat(`${TC.passed} / ${TC.planned}`, `test cases passed (${TC.failed} failed, ${TC.blocked} blocked, ${TC.inconclusive + TC.skipped} inconclusive / skipped)`, TC.failed ? "bad" : "good") : stat(s.test_cases, "test cases")}
          ${ST ? stat(`${ST.groups.links.passed} / ${ST.groups.links.total}`, "link checks passed (counted on their own)") : stat(s.passed, "tests passed", "good")}
          ${FD ? stat(FD.application_defects, "application defects", FD.application_defects ? "bad" : "good") : stat(s.bugs ?? 0, "suspected website bugs", s.bugs ? "bad" : "good")}
          ${FD ? stat(FD.test_problems, "test-script / locator problems (not website bugs)") : ""}
          ${stat((s.healed || 0) + (s.repaired_real_failure || 0), "scripts repaired (checked by running them again)")}</div>
        ${M.consistency ? `<p class="small">${M.consistent ? "✓ All totals add up" : "✗ Some totals do NOT add up"} (${M.consistency.filter((c) => c.ok).length} of ${M.consistency.length} consistency checks passed) ·
          ${(M.rates || []).map((r) => `${esc(r.name)}: ${esc(r.passed)}/${esc(r.of)}`).join(" · ")}</p>` : ""}
        ${loginWarn}
        ${gatesHtml}
        ${covHtml}
        ${cmpHtml}
        ${visualHtml}
        ${sentHtml}
        ${cost}
        ${fixes ? `<h4>Suggested fixes</h4>${fixes}` : "<h4>Suggested fixes</h4><p class='muted'>No suggested fixes recorded. Review missing evidence and skipped checks before judging readiness.</p>"}
        ${bugsHtml}
        <div class="actions">
          ${d.excel ? `<a class="secondary" href="/api/excel/${encodeURIComponent(run)}/download">⬇ Download Excel</a>` : ""}
          ${d.cases_available ? `<a class="secondary" href="/api/cases/${encodeURIComponent(run)}/download">Download test cases (JSON)</a>` : ""}
          ${d.report_html ? `<a class="primary" href="${esc(d.report_html)}" target="_blank" style="text-decoration:none">📄 Open full report</a>` : ""}
          ${(d.videos || []).map((v, i) => `<a class="secondary" href="${esc(v)}" target="_blank">🎬 Video${d.videos.length > 1 ? " " + (i + 1) : ""}</a>`).join("")}
          ${s.target_type === "android" ? "" : (s.source || s.url ? `<button type="button" class="secondary rerun" data-run="${esc(run)}">🔁 Run the same tests again</button>
            <button type="button" class="secondary schedule" data-run="${esc(run)}">⏰ Repeat this test</button>` : "")}
        </div>
        ${live ? logHtml() : d.console && d.console.length ? `<details class="log"><summary>Agent log</summary><pre>${esc(d.console.join("\n"))}</pre></details>` : ""}
      </div>`, "report");
    offerRepoFix(run);
  }

  // "Code now -> Change to" under a fix, with a Copy button
  function codeHtml(c) {
    if (!c || !c.before) return "";
    const who = c.how === "ai" ? "written by the AI - check it before you use it" : "built-in rule";
    return `<div class="code">
      <div class="code-lbl bad">Code now${c.page ? ` <span class="muted">· in ${esc(c.page)}</span>` : ""}</div>
      <pre>${esc(c.before)}</pre>
      ${c.after ? `<div class="code-lbl ok">Change to <span class="muted">· ${who}</span>
          <button type="button" class="copy" data-copy="${esc(c.after)}">📋 Copy</button></div>
        <pre class="after">${esc(c.after)}</pre>`
        : `<div class="code-lbl muted">Change this line as described above (select an AI to get the corrected code written for you).</div>`}
    </div>`;
  }

  $("thread").addEventListener("click", async (e) => {
    const thoroughBtn = e.target.closest(".thorough-again");
    if (thoroughBtn) {
      if (thoroughBtn.dataset.android === "1") {
        setWorkspaceMode("android");
        if ($("androidThorough")) $("androidThorough").checked = true;
        if ($("androidTestBuild")) $("androidTestBuild").checked = true;
        $("mobileForm")?.scrollIntoView({ behavior: "smooth", block: "start" });
        say(`<div class="note">Thorough is on for Android: the next run raises discovery and user-like budgets within safety caps. Add a test login if the app has auth. Still not a whole-app guarantee.</div>`);
        return;
      }
      focusThoroughSetup();
      return;
    }
    const v = e.target.closest(".view-xl");
    if (v) { openExcel(v.dataset.run); return; }
    const again = e.target.closest(".rerun");
    if (again) { offerRerun(again.dataset.run); return; }
    const look = e.target.closest(".approve-visual");
    if (look) { approveVisual(look); return; }
    const rc = e.target.closest(".recheck");
    if (rc) { recheckBug(rc); return; }
    const sch = e.target.closest(".schedule");
    if (sch) { offerSchedule(sch.dataset.run); return; }
    const b = e.target.closest(".copy");
    if (!b) return;
    try {
      await navigator.clipboard.writeText(b.dataset.copy);
      b.textContent = "✓ Copied";
    } catch (err) {
      b.textContent = "Select the code and press Ctrl+C";
    }
    setTimeout(() => (b.textContent = "📋 Copy"), 2000);
  });

  // ------------------------------------------------------------ regression: run the same tests again, then compare
  const reports = {};  // run -> its summary (for "Run the same tests again")

  async function offerRerun(run) {
    if (timer) {
      say(`<div class="warn">A test is already running. Stop it first, then use <b>Run the same tests again</b>.</div>`);
      return;
    }
    let s = reports[run] || {};
    if (!(s.source || s.url) || s.target_type == null) {
      try {
        const d = await (await fetch(`/api/report/${encodeURIComponent(run)}`)).json();
        if (d && d.summary) { s = d.summary; reports[run] = s; }
      } catch (e) { /* keep empty; warn below */ }
    }
    const src = s.source || s.url;
    if (s.target_type === "android") {
      say(`<div class="warn">Android runs cannot use <b>Run the same tests again</b> here. Start a new Android test from the Android form (scripts are regenerated for that device session).</div>`);
      return;
    }
    if (!src) {
      say(`<div class="warn">This report has no website URL, so the same tests cannot be re-run. Start a new test from the composer.</div>`);
      return;
    }
    const id = "rerun-" + run.replace(/\W/g, "");
    say(`<p>🔁 <b>Regression run:</b> I'll run the <b>same test scripts</b> from <b>${esc(run)}</b> against <b>${esc(src)}</b>
        (no new tests are written), then show which cases started failing, were fixed, or still fail.</p>
      <div class="card">
        ${s.authenticated ? `<p class="small">Those tests log in. The test account is never saved, so give it again
          (leave empty if it is in .env).</p><div class="fields">
          <label>Email / user name <input id="${id}-user" type="text" autocomplete="off" spellcheck="false"></label>
          <label>Password <input id="${id}-pass" type="password" autocomplete="new-password"></label></div>` : ""}
        <label class="tick auth"><input type="checkbox" id="${id}-auth" ${wasAuthorized(src) ? "checked" : ""}>
          <span>I own this website, or I have written permission to test it.</span></label>
        <div class="note" id="${id}-note" hidden></div>
        <div class="actions"><button type="button" class="primary" id="${id}-go">▶ Run the same tests again</button></div>
      </div>`, id);
    $(`${id}-go`).addEventListener("click", () => startRerun(run, src, id));
  }

  async function startRerun(run, src, id) {
    if (!await standardReady()) {
      say(`<div class="warn">Switch to <b>Standard testing</b> (not MCP) to run the same website tests again.</div>`);
      return;
    }
    const note = $(`${id}-note`), user = $(`${id}-user`), pass = $(`${id}-pass`);
    const problem = !$(`${id}-auth`).checked ? "Please confirm that you may test this website."
      : user && !!user.value.trim() !== !!pass.value ? "Give both the user name and the password (or neither)." : "";
    if (problem) { note.hidden = false; note.textContent = problem; return; }
    if (!providers) {
      try { providers = (await (await fetch("/api/providers")).json()).providers; } catch (e) { providers = []; }
    }
    const prefs = loadPrefs();  // the AI used last time, if it needs no key that has to be pasted again
    const prov = providers.find((p) => p.id === prefs.provider && workflow.providerAllowed(p.id) && (!p.key_env || p.has_key));
    const prior = reports[run] || {};
    const body = {
      workflow: "standard", privacy_mode: workflow.mode, source: src, authorized: true,
      reuse_tests: true, reuse_from_run: run, show_browser: false,
      llm_provider: prov ? prov.id : "none", llm_model: prov ? prefs.model || "" : "",
      environment: prior.environment || "test",
      auth_mode: prior.auth_mode || (prior.authenticated ? "existing" : "auto"),
      thorough: !!prior.thorough,
      crawl_scope: prior.crawl_scope || "auto",
    };
    if (user && user.value.trim()) { body.test_username = user.value.trim(); body.test_password = pass.value; }
    $(`${id}-go`).disabled = true;
    note.hidden = false; note.textContent = "Starting regression run with the same scripts…";
    const res = await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json", "X-Agentic-QA": "1" },
                                           body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { $(`${id}-go`).disabled = false; note.hidden = false; note.textContent = data.detail || "Could not start."; return; }
    if (pass) pass.value = "";
    $("m-" + id).querySelectorAll("button, input").forEach((x) => (x.disabled = true));
    rememberAuthorized(src);
    pendingSource = src;
    renderTodo({}, false);
    beginJob(data, false);
  }

  // ------------------------------------------------------------ 5) apply the fixes to the website's repo (Pull Request)
  async function offerRepoFix(run) {
    say('<div id="qpilotRepository"></div>', 'qpilot-repository');
    await window.QpilotRepo.mount(run, $("qpilotRepository"));
  }

  async function postJSON(url, body) {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Agentic-QA": "1" },
                                   body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }

  // re-check after a fix (backend/recheck.py): only this finding's test runs again, against the website as it is now
  const RECHECKABLE = ["product_defect", "rule_violation", "suspect", "assertion_failure"];
  function recheckText(r) {
    if (!r) return "";
    const head = r.verdict === "fixed" ? "✓ <b>Fixed</b> - the test passes now"
      : r.verdict === "still failing" ? "✗ <b>Still failing</b>" : `? <b>${esc(r.verdict)}</b>`;
    return `${head} <span class="muted">(re-checked ${esc(r.when)})</span>${r.error && r.verdict !== "fixed" ? `<br><span class="muted">${esc(r.error.slice(0, 200))}</span>` : ""}`;
  }

  async function recheckBug(btn) {
    const run = btn.dataset.run, out = btn.parentElement.querySelector(".rc-out");
    btn.disabled = true;
    out.textContent = "⏳ Re-checking - only this test runs again (about a minute)…";
    try {
      await postJSON(`/api/runs/${encodeURIComponent(run)}/recheck`, { failure_ids: [+btn.dataset.id] });
    } catch (err) {
      btn.disabled = false;
      out.textContent = err.message;
      return;
    }
    for (let i = 0; i < 300; i++) {
      await new Promise((r) => setTimeout(r, 4000));
      const s = await fetch(`/api/runs/${encodeURIComponent(run)}/recheck`).then((x) => x.json()).catch(() => null);
      if (!s || s.status.running) continue;
      const h = (s.history || {})[btn.dataset.node] || [];
      out.innerHTML = s.status.error ? esc(`Could not re-check: ${s.status.error}`) : recheckText(h[h.length - 1]);
      btn.disabled = false;
      return;
    }
  }

  // the visual check: this run's look of the changed pages becomes the approved look the next runs compare with
  async function approveVisual(btn) {
    btn.disabled = true;
    try {
      const r = await postJSON(`/api/visual/${encodeURIComponent(btn.dataset.run)}/approve`, {});
      btn.textContent = `✓ Approved the new look of ${r.approved} page(s) - the next runs compare with it`;
    } catch (err) {
      btn.disabled = false;
      btn.textContent = `Could not approve: ${err.message}`;
    }
  }

  function logHtml() {
    return logLines.length ? `<details class="log"><summary>Agent log (${logLines.length} lines)</summary><pre>${esc(logLines.slice(-500).join("\n"))}</pre></details>` : "";
  }

  // ------------------------------------------------------------ side panel bits
  function setExcel(run) {
    if (!run) { $("actExcel").hidden = true; return; }
    $("actExcel").href = `/api/excel/${encodeURIComponent(run)}/download`;
    $("actExcel").hidden = false;
    $("todoActions").hidden = false;
  }

  function setSiteLink(url) {
    if (!/^https?:\/\//i.test(url || "")) return;
    $("actSite").href = url;
    $("actSite").hidden = false;
    $("todoActions").hidden = false;
  }

  let shownPast = null;  // the previous test open in the chat right now

  async function loadHistory() {
    $("recent").setAttribute("aria-busy", "true");
    $("recent").innerHTML = '<span class="muted small" role="status">Loading recent runs…</span>';
    try {
      const response = await fetch("/api/history");
      if (!response.ok) throw new Error("Could not load recent runs.");
      const runs = await response.json();
      if (!Array.isArray(runs) || !runs.length) {
        $("recent").innerHTML = '<span class="muted small" role="status">No tests yet. Configure a website or Android app to see runs here.</span>';
      } else {
        $("recent").innerHTML = runs.map((r) => {
          const label = (r.url || r.run || "").replace(/^https?:\/\//, "");
          const verdict = r.incomplete || r.verdict === "incomplete" ? "incomplete" : (r.verdict || "—");
          const incomplete = r.incomplete || verdict === "incomplete";
          return `<div class="item${r.run === shownPast ? " on" : ""}${incomplete ? " incomplete" : ""}" data-run="${esc(r.run)}">
        <button type="button" class="open" data-run="${esc(r.run)}" aria-label="Open run ${esc(label)}">
          <span class="r-url">${esc(label)}</span>
          <span class="r-meta">${esc(r.date)} · ${esc(verdict)}</span></button>
        <button type="button" class="del" data-run="${esc(r.run)}" title="Delete this test and its runs folder"
          aria-label="Delete run ${esc(label)}"><span aria-hidden="true">🗑</span> Delete</button>
      </div>`;
        }).join("");
        $("recent").querySelectorAll(".open").forEach((b) => b.addEventListener("click", () => openPast(b)));
        $("recent").querySelectorAll(".del").forEach((b) => b.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          deleteTest(b);
        }));
      }
    } catch (e) {
      $("recent").innerHTML = `<span class="muted small" role="alert">Could not load recent runs. ${esc(e.message || "Check that the UI server is running.")}</span>`;
    } finally {
      $("recent").removeAttribute("aria-busy");
    }
    loadSchedules();
  }

  // scheduled tests (they run while this window is open): the list in the sidebar, ✕ deletes one
  const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  function scheduleWhen(s) {
    return s.every === "hourly" ? `every hour at :${s.at.slice(3)}` : s.every === "weekly" ? `every ${DAYS[s.day]} ${s.at}` : `every day ${s.at}`;
  }
  async function loadSchedules() {
    $("schedules").setAttribute("aria-busy", "true");
    $("schedules").innerHTML = '<span class="muted small" role="status">Loading schedules…</span>';
    try {
      const response = await fetch("/api/schedules");
      if (!response.ok) throw new Error("Could not load schedules.");
      const items = await response.json();
      $("schedules").innerHTML = Array.isArray(items) && items.length ? items.map((s) => `<div class="item">
        <span class="open"><span class="r-url">🕒 ${esc(s.source.replace(/^https?:\/\//, ""))}</span>
          <span class="r-meta">${esc(scheduleWhen(s))} · next ${esc(s.next.replace("T", " "))}${s.missed ? ` · ${esc(s.missed)} missed (window closed)` : ""}${s.last_error ? ` · ⚠ ${esc(s.last_error)}` : ""}</span></span>
        <button type="button" class="del sched-del" data-id="${esc(s.id)}" title="Delete this schedule" aria-label="Delete schedule for ${esc((s.source || "").replace(/^https?:\/\//, ""))}">✕</button>
      </div>`).join("") : '<span class="muted small" role="status">None yet — open a completed report and press ⏰ Repeat this test.</span>';
      $("schedules").querySelectorAll(".sched-del").forEach((b) => b.addEventListener("click", async () => {
        if (!confirm("Delete this scheduled test? (Its past reports stay.)")) return;
        await fetch(`/api/schedules/${encodeURIComponent(b.dataset.id)}`, { method: "DELETE", headers: { "X-Agentic-QA": "1" } });
        loadSchedules();
      }));
    } catch (e) {
      $("schedules").innerHTML = `<span class="muted small" role="alert">Could not load schedules. ${esc(e.message || "Try refreshing the page.")}</span>`;
    } finally {
      $("schedules").removeAttribute("aria-busy");
    }
  }

  // "⏰ Repeat this test": every hour / day / week, with this run's website and settings
  function offerSchedule(run) {
    const id = `sch${Date.now()}`;
    say(`<div class="card"><p>⏰ <b>Repeat this test</b> with the same website and settings. It runs while this window
        (ui.bat) is open and the PC is on - a time missed while it was closed is skipped, never started later.
        A test account and AI key are only used when they are in .env (what you typed in the chat is never saved).</p>
      <div class="fields">
        <label>How often <select id="${id}-every"><option value="daily">Every day</option><option value="hourly">Every hour</option><option value="weekly">Every week</option></select></label>
        <label>At <input id="${id}-at" type="time" value="07:00"></label>
        <label id="${id}-dayf" hidden>On <select id="${id}-day">${DAYS.map((d, i) => `<option value="${i}">${d}</option>`).join("")}</select></label>
      </div>
      <div class="actions"><button type="button" class="primary" id="${id}-go">Save the schedule</button> <span id="${id}-note" class="muted small"></span></div></div>`);
    $(`${id}-every`).addEventListener("change", () => { $(`${id}-dayf`).hidden = $(`${id}-every`).value !== "weekly"; });
    $(`${id}-go`).addEventListener("click", async () => {
      try {
        const s = await postJSON("/api/schedules", { run, every: $(`${id}-every`).value, at: $(`${id}-at`).value || "07:00",
                                                     day: +$(`${id}-day`).value || 0 });
        $(`${id}-note`).textContent = `✓ Saved: ${scheduleWhen(s)} - next run ${s.next.replace("T", " ")}`;
        $(`${id}-go`).disabled = true;
        loadSchedules();
      } catch (err) {
        $(`${id}-note`).textContent = err.message;
      }
    });
  }

  async function deleteTest(btn) {
    const run = btn.dataset.run;
    const row = btn.closest(".item") || btn.parentElement;
    const name = (row.querySelector(".r-url") || {}).textContent || run;
    const when = (row.querySelector(".r-meta") || {}).textContent || "";
    if (!confirm(`Delete this test and its folder under runs/?\n\n${name}\n${when}\n\n` +
                 "Report, Excel, screenshots and scripts are removed permanently. This cannot be undone.")) return;
    btn.disabled = true;
    btn.textContent = "Deleting…";
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(run)}`, { method: "DELETE", headers: { "X-Agentic-QA": "1" } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status === 409) {
          throw new Error((data.detail || "This test cannot be deleted right now.") +
            " Stop the run if it is still going, close any open Excel/report files from this run, then try again.");
        }
        throw new Error(data.detail || `HTTP ${res.status}`);
      }
      row.remove();  // drop from Recent immediately; folder is gone on the server
      if (shownPast === run) { shownPast = null; newTest(); }  // viewing that run → clear chat
      await loadHistory();
      // Confirm it did not reappear (folder truly gone).
      const still = [...document.querySelectorAll("#recent .item")].some((el) => el.dataset.run === run);
      if (still) {
        throw new Error("The run is still listed after delete. Refresh the page, then try Delete again.");
      }
    } catch (e) {
      btn.disabled = false;
      btn.innerHTML = '<span aria-hidden="true">🗑</span> Delete';
      alert("Could not delete the test: " + e.message);
      await loadHistory();
    }
  }

  async function openPast(btn) {
    if (timer) return;
    newTest();
    btn.parentElement.classList.add("on");
    const run = btn.dataset.run;
    shownPast = run;
    document.body.dataset.setupState = "results";
    closeWorkspaceDrawers();
    const url = btn.querySelector(".r-url").textContent;
    $("thread").innerHTML = "";
    $("chatTitle").textContent = url;
    userSays(url);
    setStatus("Previous test", "");
    renderTodo({}, false);
    $("todoMeta").textContent = "Loading saved report";
    const generation = chainGen;
    try {
      await showReport(run, false);
      if (generation === chainGen) { $("thread").scrollTop = 0; stick = false; $("jumpBtn").hidden = true; }
    } catch (e) {
      if (generation === chainGen) say(`<div class="warn" role="alert">Could not load this report. Reopen it from Recent runs to try again.</div>`);
    }
  }

  window.BlowAIChat = { updateAndroidFields };
})();
