/* Guided expected-result configuration shared by Playwright and Appium. */
(() => {
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const actions = ["tap", "fill", "select", "assert_text", "assert_visible", "assert_not_visible", "assert_enabled", "assert_checked", "assert_screen", "open", "assert_alert"];
  const nativeActions = ["context", "swipe", "drag", "scroll_to", "relaunch", "permission_state", "request_permission", "handle_permission", "assert_permission",
    "back", "rotate", "background", "hide_keyboard", "long_press"];
  const permissionNames = ["CAMERA", "RECORD_AUDIO", "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION", "POST_NOTIFICATIONS", "READ_MEDIA_IMAGES", "READ_MEDIA_VIDEO", "READ_MEDIA_AUDIO", "READ_MEDIA_VISUAL_USER_SELECTED", "READ_EXTERNAL_STORAGE"];
  let field, previousFocus;
  const dialog = document.createElement("dialog");
  dialog.className = "flow-dialog";
  dialog.setAttribute("aria-labelledby", "flowTitle");
  dialog.innerHTML = `<form id="flowForm"><div class="flow-heading"><div><span class="section-label">EXPECTED BEHAVIOR</span><h2 id="flowTitle">Build a test flow</h2></div><button type="button" class="secondary" id="flowClose" aria-label="Close test flow builder">Close</button></div>
    <p>Add the actions in order, then assert the result you expect. Use observed locators from your component inventory or Inspector.</p>
    <label>Flow name<input id="flowName" required maxlength="180" placeholder="Login reaches the dashboard"></label>
    <div class="fields"><label>Run this setup flow first<select id="flowSetup"><option value="">Start from the launch screen</option></select></label><label>Flow timeout (seconds)<input id="flowTimeout" type="number" min="10" max="300" value="90" required></label></div>
    <label>Approved WebView origins (optional)<input id="flowOrigins" placeholder="https://your-test-site.example, one origin per line"></label>
    <div id="flowSteps"></div><button type="button" class="secondary" id="flowAdd">Add step</button>
    <p class="note">For passwords or tokens, enter a reference such as <code>secret:BLOWAI_SECRET_TEST_PASSWORD</code>. Configure its value privately in the test environment. Do not type passwords here.</p>
    <label class="tick"><input type="checkbox" id="flowAuth">This flow verifies login (requires a submission and a result assertion)</label>
    <label class="tick"><input type="checkbox" id="flowApproved">I approve this flow and its test data</label>
    <label class="tick"><input type="checkbox" id="flowEnvironment">This is an approved test environment</label>
    <div id="flowPermissionSettings" hidden><label>App name shown on Android permission prompts<input id="flowPermissionApp" maxlength="100" placeholder="Exact app display name"></label><label class="tick"><input type="checkbox" id="flowPermissionApproved">I approve the listed permissions on the selected emulator. Original permissions will be restored after this test.</label></div>
    <p id="flowMessage" role="status" aria-live="polite"></p>
    <div class="flow-actions"><button type="submit" class="primary">Validate and add flow</button></div></form>`;
  document.body.append(dialog);
  const $ = id => dialog.querySelector("#"+id);
  const close = () => { dialog.close(); previousFocus?.focus(); };
  $("flowClose").onclick = close;
  dialog.addEventListener("cancel", () => previousFocus?.focus());

  function addStep(action = "assert_visible") {
    if ($("flowSteps").children.length >= 40) return;
    const row = document.createElement("fieldset");
    row.className = "flow-step";
    const web = field.id === "webContract" || document.getElementById("androidMode")?.value === "web";
    const strategies = web ? ["css"] : ["accessibility_id", "resource_id", "text", "xpath", "css"];
    const availableActions = web ? actions : [...actions.filter(a => a !== "select"), ...nativeActions];
    row.innerHTML = `<legend>Step</legend><label>Action<select class="flow-action">${availableActions.map(a=>`<option ${a===action?"selected":""}>${a}</option>`).join("")}</select></label>
      <label class="flow-locator-field">Locator type<select class="flow-strategy">${strategies.map(s=>`<option>${s}</option>`).join("")}</select></label>
      <label class="flow-wide flow-locator-field">Locator<input class="flow-locator" maxlength="500" placeholder="${web?"#username":"Observed unique locator"}"></label>
      <label class="flow-target-field">Destination locator type<select class="flow-target-strategy">${strategies.map(s=>`<option>${s}</option>`).join("")}</select></label>
      <label class="flow-wide flow-target-field">Destination locator<input class="flow-target" maxlength="500" placeholder="Target control for drag or scroll-to"></label>
      <label class="flow-wide flow-value-field">Test value or expected result<input class="flow-value" maxlength="1000" autocomplete="off" placeholder="Expected text, dropdown value, or secret:BLOWAI_SECRET_..."></label>
      <label class="flow-permission-field">Android permission<select class="flow-permission">${permissionNames.map(p=>`<option value="android.permission.${p}">${p}</option>`).join("")}</select></label>
      <label class="flow-wide flow-permissions-field">All permissions requested together (optional)<input class="flow-permissions" maxlength="700" placeholder="Comma-separated full Android permission names, including the selected one"></label>
      <label class="flow-purpose-field">Click purpose<select class="flow-purpose"><option value="navigation">Navigation</option><option value="test_form">Approved form or test-data action</option></select></label>
      <button type="button" class="secondary flow-remove">Remove step</button>`;
    const refresh = () => {
      const selected = row.querySelector('.flow-action').value;
      const permission = ['permission_state','request_permission','handle_permission','assert_permission'].includes(selected);
      const show = (name, visible) => row.querySelectorAll('.flow-'+name+'-field').forEach(label => { label.hidden = !visible; label.querySelectorAll('input,select').forEach(input => input.disabled = !visible); });
      show('locator', !['assert_screen','context','relaunch','permission_state','handle_permission','assert_permission','back','rotate','background','hide_keyboard','open','assert_alert'].includes(selected));
      show('target', ['drag','scroll_to'].includes(selected));
      show('permission', permission);
      show('permissions', selected === 'request_permission');
      show('purpose', selected === 'tap');
      show('value', ['fill','select','assert_text','assert_screen','assert_enabled','assert_checked','context','swipe','scroll_to','permission_state','handle_permission','assert_permission','rotate','background','open','assert_alert'].includes(selected));
      const hint = row.querySelector('.flow-value');
      hint.placeholder = selected === 'open' ? 'https:// address of a page on the approved website' : selected === 'assert_alert' ? 'Expected browser message, for example Product added.' : selected === 'rotate' ? 'portrait or landscape' : selected === 'background' ? 'seconds in the background (1-30)' : selected === 'context' ? 'native or webview' : ['swipe','scroll_to'].includes(selected) ? 'up, down, left or right' : selected === 'handle_permission' ? 'allow_while_using, allow_once, allow or deny' : ['permission_state','assert_permission'].includes(selected) ? 'granted or denied' : ['assert_checked','assert_enabled'].includes(selected) ? 'true or false' : 'Expected value, or secret:BLOWAI_SECRET_...';
      refreshPermissionSettings();
    };
    row.querySelector('.flow-action').onchange = refresh;
    row.querySelector(".flow-remove").onclick = () => { row.remove(); refreshPermissionSettings(); };
    $("flowSteps").append(row);
    refresh();
  }
  function refreshPermissionSettings() {
    const needed = [...dialog.querySelectorAll('.flow-action')].some(select => ['permission_state','request_permission','handle_permission','assert_permission'].includes(select.value));
    $('flowPermissionSettings').hidden = !needed;
  }
  $("flowAdd").onclick = () => addStep();

  async function validate(contract) {
    const response = await fetch("/api/contracts/validate", {method:"POST", headers:{"Content-Type":"application/json","X-Agentic-QA":"1"},body:JSON.stringify({contract})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Check the test steps and expected results.");
    return data;
  }

  $("flowForm").onsubmit = async event => {
    event.preventDefault();
    $("flowMessage").textContent = "Validating the flow…";
    const submit = $("flowForm").querySelector('[type="submit"]');
    if (submit) { submit.disabled = true; submit.setAttribute("aria-busy", "true"); }
    try {
      const contract = field.value.trim() ? JSON.parse(field.value) : {version:1,flows:[],rules:[],checks:[],allowed_origins:[]};
      const steps = [...$("flowSteps").children].map(row => {
        const get = name => row.querySelector(".flow-"+name).value.trim();
        const action = get("action"), value = get("value");
        const step = {action};
        if (!['assert_screen','context','relaunch','permission_state','handle_permission','assert_permission','back','rotate','background','hide_keyboard','open','assert_alert'].includes(action)) step.locator = {strategy:get("strategy"),value:get("locator")};
        if (action === "tap") step.purpose = get("purpose");
        if (['drag','scroll_to'].includes(action)) step.target = {strategy:get('target-strategy'),value:get('target')};
        if (['permission_state','request_permission','handle_permission','assert_permission'].includes(action)) step.permission = get('permission');
        if (action === 'request_permission' && get('permissions')) step.permissions = get('permissions').split(',').map(value=>value.trim()).filter(Boolean);
        if (["fill","select","assert_text","assert_screen","assert_enabled","assert_checked","context","swipe","scroll_to","permission_state","handle_permission","assert_permission","rotate","background","open","assert_alert"].includes(action)) {
          if (action === "fill" && value.startsWith("secret:")) step.secret_ref = value.slice(7);
          else step.value = value;
        }
        return step;
      });
      if (!steps.length) throw new Error("Add at least one step and an expected-result assertion.");
      const flow = {id:"flow_"+Date.now(),title:$("flowName").value.trim(),steps,
        approved:$("flowApproved").checked,authentication:$("flowAuth").checked,timeout_s:Number($('flowTimeout').value)};
      if ($('flowSetup').value) flow.setup_flow = $('flowSetup').value;
      if (!flow.approved || !$("flowEnvironment").checked) throw new Error("Review and approve the flow and its test environment before adding it.");
      contract.flows = [...(contract.flows || []),flow];
      contract.test_environment = true;
      if ($('flowOrigins').value.trim()) contract.allowed_origins = [...new Set([...(contract.allowed_origins || []), ...$('flowOrigins').value.split(/[,\n]/).map(value=>value.trim()).filter(Boolean)])];
      const permissions = [...new Set(steps.flatMap(step=>[step.permission,...(step.permissions || [])]).filter(Boolean))];
      if (permissions.length) {
        if (!$('flowPermissionApproved').checked || !$('flowPermissionApp').value.trim()) throw new Error('Approve the emulator permissions and provide the app name shown on its prompts.');
        contract.android_permissions = {approved:true,app_label:$('flowPermissionApp').value.trim(),allowed:[...new Set([...(contract.android_permissions?.allowed || []),...permissions])],emulator_only:true,restore_after_flow:true};
      }
      const result = await validate(contract);
      const encoded = JSON.stringify(result.compact_contract || result.contract,null,2);
      if (encoded.length > 64000) throw new Error('This configuration exceeds 64 KB. Split the flows into separate runs.');
      field.value = encoded;
      field.dispatchEvent(new Event("input",{bubbles:true}));
      const note = document.querySelector(`[data-flow-review="${field.id}"]`);
      note.textContent = `${result.flows} configured flows · ${result.rules} business rules · ${result.checks} backend checks. Ready for execution review.`;
      close();
    } catch(error) {
      $("flowMessage").textContent = error instanceof SyntaxError
        ? "Correct the existing JSON before adding another flow."
        : (error.message || "Could not validate this flow. Check the steps and try again.");
    } finally {
      if (submit) { submit.disabled = false; submit.removeAttribute("aria-busy"); }
    }
  };

  function mount() {
    ["androidContract","webContract"].forEach(id => {
      const target = document.getElementById(id);
      if (!target || document.querySelector(`[data-flow-tools="${id}"]`)) return;
      const tools = document.createElement("div");
      tools.className = "flow-tools wide";
      tools.dataset.flowTools = id;
      tools.innerHTML = id === 'androidContract'
        ? `<div class="actions"><button type="button" class="secondary flow-open">Build a test flow</button></div><p class="muted small" data-flow-review="${esc(id)}" role="status">Build a feature workflow, or leave this empty for whole-app exploration.</p>`
        : `<div class="actions"><button type="button" class="secondary flow-open">Build a test flow</button><button type="button" class="secondary flow-check">Validate configured checks</button></div><p class="muted small" data-flow-review="${esc(id)}" role="status">Configure actions and expected results here. Discovery alone does not verify a business workflow.</p>`;
      if (id === 'androidContract') {
        const samples = document.createElement('div');
        samples.className = 'actions flow-samples';
        samples.innerHTML = '<label>Sample test flows<select class="flow-example" aria-label="Sample Android test flows"><option value="">Loading examples…</option></select></label><button type="button" class="secondary flow-load-example">Load selected example</button><button type="button" class="secondary flow-undo-example" hidden>Undo example</button>';
        tools.append(samples);
        let examples = [];
        const renderExamples = () => {
          const mode = document.getElementById('androidMode')?.value === 'web' ? 'web' : 'native';
          samples.querySelector('select').innerHTML = '<option value="">Choose an app-specific example</option>' + examples.filter(example=>(example.app_mode || 'native') === mode).map(example=>`<option value="${esc(example.id)}">${esc(example.name)}</option>`).join('');
        };
        document.getElementById('androidMode')?.addEventListener('change', renderExamples);
        fetch('/api/contracts/examples').then(response=>response.json()).then(data=> {
          examples = data.examples || []; renderExamples();
        }).catch(()=>{ samples.querySelector('select').innerHTML = '<option value="">Examples unavailable</option>'; });
        let previous = '';
        samples.querySelector('.flow-load-example').onclick = async () => {
          const selected = samples.querySelector('select').value;
          if (!selected) return;
          const note = tools.querySelector('[data-flow-review]');
          try {
            const response = await fetch('/api/contracts/examples/' + encodeURIComponent(selected));
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'The example could not be loaded.');
            previous = target.value;
            target.value = JSON.stringify(data.contract, null, 2);
            samples.querySelector('.flow-undo-example').hidden = false;
            target.dispatchEvent(new Event('input', {bubbles:true}));
            note.textContent = `${data.name}. ${data.note} Account flows use the private test-account fields above. Nothing has executed.`;
          } catch(error) { note.textContent = error.message; }
        };
        samples.querySelector('.flow-undo-example').onclick = () => {
          target.value = previous;
          target.dispatchEvent(new Event('input', {bubbles:true}));
          samples.querySelector('.flow-undo-example').hidden = true;
          tools.querySelector('[data-flow-review]').textContent = 'Previous flow configuration restored.';
        };
      }
      const slot = id === 'androidContract' ? document.getElementById('androidFlowToolsSlot') : null;
      if (slot) slot.append(tools);
      else target.closest("label").before(tools);
      tools.querySelector(".flow-open").onclick = () => {
        field = target; previousFocus = document.activeElement;
        $("flowForm").reset(); $("flowSteps").replaceChildren(); $("flowMessage").textContent = "";
        let existing = {}; try { existing = JSON.parse(target.value || '{}'); } catch (_) { /* Validation explains invalid JSON on submission. */ }
        $('flowSetup').innerHTML = '<option value="">Start from the launch screen</option>' + (existing.flows || []).map(flow=>`<option value="${esc(flow.id)}">${esc(flow.title)}</option>`).join('');
        $('flowPermissionApp').value = existing.android_permissions?.app_label || '';
        addStep(); dialog.showModal(); $("flowName").focus();
      };
      const checkButton = tools.querySelector(".flow-check");
      if (checkButton) checkButton.onclick = async () => {
        const note = tools.querySelector("[data-flow-review]");
        try {
          const result = await validate(JSON.parse(target.value || "{}"));
          note.textContent = `${result.flows} flows · ${result.rules} rules · ${result.checks} backend checks. `+
            (!result.test_environment_approved || result.unapproved_flows.length ? "Approval is still required. " : "")+
            (result.required_secret_refs.length ? `Private input references: ${result.required_secret_refs.join(", ")}. ` : "")+result.note;
        } catch(error) { note.textContent = error instanceof SyntaxError ? "Correct the JSON before validation." : error.message; }
      };
    });
  }
  new MutationObserver(mount).observe(document.getElementById("thread"), {childList:true,subtree:true});
  mount();
})();
