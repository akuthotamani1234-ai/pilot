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
  $('mcpConfigureWeb').onclick = async event => {
    const target = $('mcpTarget').value.trim();
    const button = event.currentTarget; button.disabled = true; invalidate();
    try {
      const url = new URL(target); if (!['http:','https:'].includes(url.protocol) || url.username || url.password) throw new Error('Enter a complete website URL without credentials.');
      if (webMove) { restore(webMove); webMove = null; }
      const node = await window.QpilotChat.configureMcpWeb(target);
      if (!active || platform !== 'web') return;
      webMove = move(node,$('mcpWebFields')); configuredFor = target;
      $('mcpPanelMessage').textContent = 'Review account, AI, exploration and workflow settings below, then prepare the request.';
    } catch(error) { $('mcpPanelMessage').textContent = error.message; }
    finally { button.disabled = false; }
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
      // Preserve the shared full-coverage checkbox's count-field behavior.
      $('androidTestBuild').dispatchEvent(new Event('change'));
    },
    async prepare(engine, target, task) {
      invalidate();
      const version = revision; let settings;
      if (engine === 'android') {
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
