/* Reuse Studio controls. Only a private, expiring reference reaches the assistant. */
(() => {
  const $ = id => document.getElementById(id), slot = document.createElement('section');
  slot.id = 'mcpSharedSettings'; slot.className = 'mcp-shared-settings';
  slot.innerHTML = '<h3>Test configuration</h3><p class="muted small">The same settings and workflow builders used in Standard testing. Private inputs stay on this computer.</p>' +
    '<button type="button" class="secondary" id="mcpConfigureWeb">Configure website test</button>' +
    '<div id="mcpProviderFields" class="fields"></div><div id="mcpAdvancedFields"></div><div id="mcpWebFields"></div>';
  $('copyMcpRequest').closest('.row').before(slot);
  const moved = [], controls = ['androidProvider','androidModel','androidApiKey'].map(id => $(id).closest('label'));
  controls.push($('androidAccountSettings'));
  controls.push(document.querySelector('.mobile-advanced'));
  let platform = 'web', active = false, configuredFor = '', webMove = null, prepared = '', revision = 0;
  const workflow = () => window.QpilotWorkflow || window.BlowAIWorkflow;
  function move(node, parent) {
    const marker = document.createComment('shared test settings'); node.before(marker); parent.append(node);
    return {node, marker};
  }
  function restore(item) {
    if (item.marker.isConnected) item.marker.replaceWith(item.node);
    else item.node.remove();
  }
  function invalidate() {
    revision++; $('mcpRequestPreview').hidden = true;
    if (prepared) {
      fetch('/api/settings/mcp-requests/' + encodeURIComponent(prepared), {
        method:'DELETE',headers:{'X-Agentic-QA':'1'}}).catch(() => {});
      prepared = '';
    }
  }
  async function configureWeb(target) {
    const url = new URL(target); if (!['http:','https:'].includes(url.protocol) || url.username || url.password) throw new Error('Enter a complete website URL without credentials.');
    if (webMove) { restore(webMove); webMove = null; }
    const node = await window.QpilotChat.configureMcpWeb(target);
    if (!active || platform !== 'web') return false;
    webMove = move(node,$('mcpWebFields')); configuredFor = target;
    return true;
  }
  $('mcpConfigureWeb').onclick = async event => {
    const target = $('mcpTarget').value.trim();
    const button = event.currentTarget; button.disabled = true; invalidate();
    try {
      if (await configureWeb(target))
        $('mcpPanelMessage').textContent = 'Review account, AI model, exploration and workflow settings below, then press Run it here (or prepare a request for an external assistant).';
    } catch(error) { $('mcpPanelMessage').textContent = error.message.includes('URL') ? 'Enter a complete website URL without credentials.' : error.message; }
    finally { button.disabled = false; }
  };
  // "Run it here": the same request, run by Qpilot itself with the AI model chosen in the settings - no Cursor /
  // Claude, no copy and paste. The first press opens the settings (AI model, account) when they are not shown yet.
  const runHere = document.createElement('button');
  runHere.type = 'button'; runHere.className = 'primary'; runHere.id = 'mcpRunHere'; runHere.textContent = 'Run it here with Qpilot AI';
  $('copyMcpRequest').before(runHere);
  $('copyMcpRequest').className = 'secondary';
  $('copyMcpRequest').nextElementSibling.textContent = 'Run it here uses the AI model chosen below. Or prepare a request to paste into an external MCP assistant.';
  runHere.onclick = async () => {
    const target = $('mcpTarget').value.trim(), task = $('mcpTask').value.trim();
    if (platform !== 'web') { $('mcpPanelMessage').textContent = 'Run it here is for websites. For Android, prepare the assistant request.'; return; }
    if (!target || !task) { $('mcpPanelMessage').textContent = 'Enter the website and describe what you want to check.'; return; }
    runHere.disabled = true;
    try {
      if (!webMove || configuredFor !== target) {
        invalidate();
        if (await configureWeb(target)) {
          $('mcpPanelMessage').textContent = 'Choose the AI model and account below, then press Run it here again.';
          const ai = document.querySelector('#mcpWebFields [data-provider], #mcpWebFields .provider, #mcpWebFields select');
          if (ai && ai.scrollIntoView) ai.scrollIntoView({block: 'center', behavior: 'smooth'});
        }
        return;
      }
      $('mcpPanelMessage').textContent = 'Starting…';
      await window.QpilotChat.runHere(task);
      $('mcpPanelMessage').textContent = 'Started in Qpilot with your request as its own test - follow it below.';
    } catch(error) { $('mcpPanelMessage').textContent = error.message; }
    finally { runHere.disabled = false; }
  };
  $('mcpAndroidTestBuild').addEventListener('change', () => {
    $('androidTestBuild').checked = $('mcpAndroidTestBuild').checked;
    $('androidTestBuild').dispatchEvent(new Event('change',{bubbles:true}));
  });
  $('mcpPanel').addEventListener('input', invalidate);
  $('mcpPanel').addEventListener('change', invalidate);
  window.addEventListener('blowai:privacychange', invalidate);
  window.QpilotMcpSettings = {
    mount(engine, mode, busy) {
      const enabled = mode === 'mcp';
      if (engine !== platform || active !== enabled) invalidate();
      platform = engine; active = enabled; slot.hidden = !enabled;
      if (enabled && engine === 'android' && !moved.length) {
        controls.forEach((node,index) => moved.push(move(node,$(index < 3 ? 'mcpProviderFields' : 'mcpAdvancedFields'))));
      } else if ((!enabled || engine !== 'android') && moved.length) moved.splice(0).forEach(restore);
      if ((!enabled || engine !== 'web') && webMove) { restore(webMove); webMove = null; configuredFor = ''; }
      $('mcpConfigureWeb').hidden = engine !== 'web';
      slot.querySelectorAll('input,select,textarea,button').forEach(node => { node.disabled = !!busy; });
      runHere.disabled = !!busy; runHere.hidden = engine !== 'web';
      // Preserve the shared full-coverage checkbox's count-field behavior.
      $('androidTestBuild').dispatchEvent(new Event('change'));
    },
    async prepare(engine, target, task) {
      invalidate();
      const version = revision; let settings;
      if (engine === 'android') {
        await window.QpilotAndroidAccount.ensureCompatible();
        workflow().syncToStandard();
        const data = window.QpilotChat.androidRequest(false);
        if (!data) throw new Error($('androidRunNote').textContent || 'Review the advanced workflow JSON and expected-result settings.');
        settings = Object.fromEntries(data);
        ['authorized','contract_only','interaction_testing','test_all_discovered','thorough','allow_rules_fallback'].forEach(key => settings[key] = settings[key] === 'true');
        Object.assign(settings,{app_mode:$('mcpAndroidSource').value,device_id:$('mcpAndroidDevice').value,
          appium_url:$('mcpAndroidAppiumUrl').value.trim(),app_activity:$('mcpAndroidActivity').value.trim(),
          authorized:$('mcpAndroidAuthorized').checked,interaction_testing:$('mcpAndroidTestBuild').checked});
      } else {
        if (!webMove || configuredFor !== target) throw new Error('Choose Configure website test and review the settings for this URL first.');
        settings = window.QpilotChat.webRequest();
        if (!settings) throw new Error('Review the highlighted website test settings.');
      }
      const avd = engine === 'android' ? ($('mcpAndroidDevice').selectedOptions[0]?.dataset.avd || '') : '';
      const response = await fetch('/api/settings/mcp-requests',{method:'POST',
        headers:{'Content-Type':'application/json','X-Agentic-QA':'1'},
        body:JSON.stringify({platform:engine,target,task,settings,avd_name:avd})});
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Could not prepare this configuration.');
      if (version !== revision) {
        fetch('/api/settings/mcp-requests/'+encodeURIComponent(data.request_id),{method:'DELETE',headers:{'X-Agentic-QA':'1'}}).catch(() => {});
        throw new Error('Settings changed during preparation. Review and prepare again.');
      }
      prepared = data.request_id;
      ['androidApiKey','androidTestUsername','androidTestPassword','aiKey','aiUser','aiPass','aiTotp'].forEach(id => { if ($(id)) $(id).value = ''; });
      return ['Use Qpilot MCP with the exact Studio configuration below.',
        'Target: '+data.target,'Task: '+data.task,
        'Call start_prepared_test with request_id="'+data.request_id+'" and authorized=true.',
        'Do not substitute a different start tool or change the target/settings. Private inputs remain in Studio.',
        'This request expires in 15 minutes. Check list_runs before retrying an uncertain start.',
        'Poll get_run_status, then read the report. Report blocked/untested work without inventing passes.',
        'Reviewed settings (private inputs omitted):',JSON.stringify(data.settings,null,2)].join('\n');
    }, invalidate
  };
  const current = workflow(); window.QpilotMcpSettings.mount(current.engine,current.workflow,false);
})();
