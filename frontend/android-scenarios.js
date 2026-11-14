/* Draft review and read-only backend oracles; no execution happens here. */
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const dialog = document.createElement('dialog'); dialog.className = 'flow-dialog';
  dialog.setAttribute('aria-label','Draft an Android scenario');
  dialog.innerHTML = '<form method="dialog"><h2>Draft an Android scenario</h2><p>Use a completed discovery run. Describe the workflow, expected result and private test-data references. The configured AI provider and privacy policy apply.</p>' +
    '<label>Requirements<textarea id="scenarioRequest" rows="4" maxlength="6000" placeholder="Open login, fill secret:BLOWAI_SECRET_TEST_USERNAME and secret:BLOWAI_SECRET_TEST_PASSWORD, then verify the account screen."></textarea></label>' +
    '<button type="button" class="secondary scenario-generate">Generate draft</button>' +
    '<label>Review and edit the proposed configuration<textarea id="scenarioReview" rows="12" spellcheck="false"></textarea></label>' +
    '<p class="scenario-basis"></p><label class="tick"><input type="checkbox" id="scenarioApprove">I reviewed navigation, expected outcomes and test-data references, and approve this test environment.</label>' +
    '<p class="scenario-message" role="status"></p><div class="actions"><button type="button" class="primary scenario-add">Add reviewed scenario</button><button type="submit" class="secondary">Cancel</button></div></form>';
  document.body.append(dialog); let run = '', previousFocus;
  dialog.addEventListener('close', () => previousFocus?.focus());
  window.QpilotScenarios = {open(id) {
    run = id; previousFocus = document.activeElement; dialog.querySelector('form').reset();
    dialog.querySelector('.scenario-message').textContent = ''; dialog.querySelector('.scenario-basis').textContent = '';
    dialog.showModal(); dialog.querySelector('textarea').focus();
  }};
  dialog.querySelector('.scenario-generate').onclick = async event => {
    const button = event.currentTarget, message = dialog.querySelector('.scenario-message'); button.disabled = true;
    message.textContent = 'Drafting from observed controls…';
    try {
      const response = await fetch(`/api/android/runs/${encodeURIComponent(run)}/scenario-draft`, {
        method:'POST', headers:{'Content-Type':'application/json','X-Agentic-QA':'1'},
        body:JSON.stringify({instructions:document.getElementById('scenarioRequest').value})});
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Draft failed.');
      document.getElementById('scenarioReview').value = JSON.stringify(data.contract,null,2);
      document.getElementById('scenarioApprove').checked = false;
      dialog.querySelector('.scenario-basis').textContent = data.expected_basis; message.textContent = data.note;
    } catch (error) { message.textContent = error.message; } finally { button.disabled = false; }
  };
  async function validate(contract) {
    const response = await fetch('/api/contracts/validate',{method:'POST',headers:{'Content-Type':'application/json','X-Agentic-QA':'1'},body:JSON.stringify({contract})});
    const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Invalid check configuration.');
    return data.compact_contract;
  }
  function save(field, contract) {
    const value = JSON.stringify(contract,null,2); if (value.length > 64000) throw new Error('Configuration exceeds 64 KB. Split the scenarios.');
    field.value = value; field.dispatchEvent(new Event('input',{bubbles:true}));
    const details = field.closest('details'); if (details) details.open = true;
  }
  dialog.querySelector('.scenario-add').onclick = async event => {
    const button = event.currentTarget; button.disabled = true;
    try {
      if (!document.getElementById('scenarioApprove').checked) throw new Error('Review and approve the scenario before adding it.');
      const draft = JSON.parse(document.getElementById('scenarioReview').value);
      const field = document.getElementById('androidContract'), existing = JSON.parse(field.value || '{"version":1}');
      if (existing.android_package && draft.android_package && existing.android_package !== draft.android_package) throw new Error('The draft belongs to a different application.');
      if (!draft.flows?.length || draft.rules?.length || draft.checks?.length) throw new Error('Review one workflow draft at a time.');
      const stamp = Date.now();
      const flows = draft.flows.map((flow,index) => ({...flow,id:`reviewed_${stamp}_${index}`,approved:true}));
      const combined = {...existing,android_package:existing.android_package || draft.android_package,
        test_environment:true,flows:[...(existing.flows || []),...flows]};
      save(field,await validate(combined)); dialog.close(); field.scrollIntoView({block:'center'});
    } catch (error) { dialog.querySelector('.scenario-message').textContent = error.message; }
    finally { button.disabled = false; }
  };
  const backend = document.createElement('dialog'); backend.className = 'flow-dialog';
  backend.setAttribute('aria-label','Verify API or database outcomes');
  backend.innerHTML = '<form><h2>Verify API or database outcomes</h2><p>Attach a read-only check after a UI workflow, or run it independently. An attached check executes with that workflow once.</p>' +
    '<label>Check title<input name="title" required maxlength="180"></label><label>UI workflow<select name="flow"></select></label>' +
    '<label>Source<select name="kind"><option value="http">HTTP GET</option><option value="sqlite">Read-only SQLite</option></select></label>' +
    '<div class="http-fields"><label>Approved API URL<input name="url" placeholder="https://test.example/api/status"></label><label>Expected HTTP status<input name="status" type="number" value="200" min="100" max="599"></label>' +
    '<label>JSON pointer<input name="pointer" placeholder="/state"></label><label>Optional bearer token reference<input name="token" placeholder="BLOWAI_SECRET_API_TOKEN"></label></div>' +
    '<div class="db-fields" hidden><label>Database reference<input name="database" placeholder="BLOWAI_DB_TEST"></label><label>SELECT query<textarea name="query" placeholder="SELECT status FROM orders WHERE id = ?"></textarea></label>' +
    '<label>Parameters as a JSON array<input name="parameters" value="[]"></label></div><label>Expected scalar as JSON<input name="expected" required placeholder="&quot;active&quot;, 3, true or null"></label>' +
    '<label class="tick"><input name="approved" type="checkbox" required>I approve this read-only source in my test environment.</label>' +
    '<p class="backend-message" role="status"></p><div class="actions"><button class="primary" type="submit">Add check</button><button class="secondary backend-close" type="button">Cancel</button></div></form>';
  document.body.append(backend); let target;
  backend.querySelector('.backend-close').onclick = () => backend.close();
  backend.querySelector('[name=kind]').onchange = event => {
    backend.querySelector('.http-fields').hidden = event.target.value !== 'http'; backend.querySelector('.db-fields').hidden = event.target.value !== 'sqlite';
  };
  backend.querySelector('form').onsubmit = async event => {
    event.preventDefault(); const submit = backend.querySelector('[type=submit]'); submit.disabled = true;
    try {
      const values = new FormData(event.target), get = name => String(values.get(name) || '').trim();
      const contract = JSON.parse(target.value || '{"version":1}');
      const check = {id:'backend_'+Date.now(),title:get('title'),kind:get('kind'),expected:JSON.parse(get('expected'))};
      if (check.kind === 'http') {
        Object.assign(check,{url:get('url'),status:Number(get('status')),json_pointer:get('pointer')});
        if (get('token')) check.token_ref = get('token');
        // Explicitly approved above; the server still validates target and origin policy.
        contract.allowed_origins = [...new Set([...(contract.allowed_origins || []),new URL(check.url).origin])];
      } else Object.assign(check,{database_ref:get('database'),query:get('query'),parameters:JSON.parse(get('parameters'))});
      if (get('flow')) {
        const flow = contract.flows?.find(flow => flow.id === get('flow')); if (!flow) throw new Error('Workflow is no longer available.');
        flow.backend_checks = [...(flow.backend_checks || []),check.id];
      }
      contract.checks = [...(contract.checks || []),check]; contract.test_environment = true;
      save(target,await validate(contract)); backend.close();
    } catch (error) { backend.querySelector('.backend-message').textContent = error.message; }
    finally { submit.disabled = false; }
  };
  function mount() {
    document.querySelectorAll('[data-flow-tools]').forEach(tools => {
      if (tools.querySelector('.backend-open')) return;
      const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary backend-open'; button.textContent = 'Add API / database check';
      tools.querySelector('.actions')?.append(button);
      button.onclick = () => {
        target = document.getElementById(tools.dataset.flowTools); let existing;
        try { existing = JSON.parse(target.value || '{}'); } catch (_) { target.reportValidity(); return; }
        backend.querySelector('form').reset(); backend.querySelector('.backend-message').textContent = '';
        backend.querySelector('.http-fields').hidden = false; backend.querySelector('.db-fields').hidden = true;
        backend.querySelector('[name=flow]').innerHTML = '<option value="">Independent read-only check</option>' +
          (existing.flows || []).map(flow => `<option value="${esc(flow.id)}">${esc(flow.title)}</option>`).join('');
        backend.showModal(); backend.querySelector('input').focus();
      };
    });
  }
  new MutationObserver(mount).observe(document.getElementById('thread'),{subtree:true,childList:true}); mount();
})();
