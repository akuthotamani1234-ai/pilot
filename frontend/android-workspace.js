/* Android coverage and safe continuation. Verdicts and counts come from the API. */
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let current = '', updated = 0, busy = false, generation = 0;
  function panel() {
    let node = document.getElementById('androidCoverage');
    if (node) return node;
    node = document.createElement('section'); node.id = 'androidCoverage'; node.className = 'live-workspace';
    node.innerHTML = '<span class="eyebrow">ANDROID COVERAGE</span><h2>What was actually tested</h2>' +
      '<p class="coverage-scope"></p><div class="coverage-counts actions"></div>' +
      '<label>Filter scenarios<select class="coverage-filter"><option value="">All statuses</option>' +
      ['passed','failed','error','blocked','pending','skipped','inconclusive'].map(value => `<option>${value}</option>`).join('') +
      '</select></label><div class="coverage-cases"></div><details><summary>Exploration gaps and controls</summary><div class="coverage-gaps"></div></details>' +
      '<div class="actions"><button type="button" class="secondary coverage-resume" hidden>Resume unfinished tests</button>' +
      '<button type="button" class="secondary coverage-draft">Draft a scenario with AI</button>' +
      '<a class="secondary" href="/qa-lab" target="_blank" rel="noopener">Accuracy Lab</a></div><p class="coverage-message" role="status"></p>';
    document.getElementById('thread')?.prepend(node);
    node.querySelector('.coverage-resume').onclick = async event => {
      const button = event.currentTarget; button.disabled = true;
      const message = node.querySelector('.coverage-message');
      message.textContent = 'Preparing the original device and preserving completed results…';
      try {
        const response = await fetch(`/api/android/runs/${encodeURIComponent(current)}/resume`, {
          method:'POST', headers:{'X-Agentic-QA':'1'}});
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not resume.');
        document.dispatchEvent(new CustomEvent('qpilot:android-resume', {detail:data}));
      } catch (error) { message.textContent = error.message; }
      finally { button.disabled = false; }
    };
    node.querySelector('.coverage-draft').onclick = () => window.QpilotScenarios?.open(current);
    return node;
  }
  function render(data, job) {
    const node = panel();
    node.querySelector('.coverage-scope').textContent = data.scope;
    node.querySelector('.coverage-counts').innerHTML = Object.entries(data.counts).map(([key,value]) =>
      `<span class="status-chip">${esc(key)}: ${esc(value)}</span>`).join('');
    const renderCases = () => {
      const filter = node.querySelector('.coverage-filter').value;
      const rows = data.cases.filter(row => !filter || row.status === filter);
      node.querySelector('.coverage-cases').innerHTML = rows.length ? '<ol class="live-timeline">' + rows.map(row =>
        `<li class="event-${esc(row.status)}"><span class="event-state">${esc(row.status)}</span><div>` +
        `<b>${esc(row.title)}</b><small>${row.functional ? 'Functional scenario' : 'UI check'} · ${esc(row.checks)} assertions</small>` +
        `<details><summary>Expected result and reason</summary><p>${esc(row.expected)}</p><p>${esc(row.reason)}</p></details></div></li>`).join('') + '</ol>' : '<p>No scenarios in this status yet.</p>';
    };
    renderCases(); node.querySelector('.coverage-filter').onchange = renderCases;
    node.querySelector('.coverage-gaps').innerHTML = [...data.gaps,...data.unvisited,...data.controls.filter(row => row.status !== 'passed')].map(row =>
      `<p><b>${esc(row.screen || row.category || 'Discovery')}: ${esc(row.name || row.label || '')}</b> — ${esc(row.reason || row.status || 'No passing functional check')}</p>`).join('') || '<p>No recorded gaps yet. Discovery may still be running.</p>';
    node.querySelector('.coverage-resume').hidden = job.status === 'running' || !data.resume.can_resume;
    node.querySelector('.coverage-draft').disabled = job.status === 'running';
    const uncertain = data.resume.uncertain;
    node.querySelector('.coverage-message').textContent = uncertain.length ?
      `${uncertain.length} interrupted action(s) require data reconciliation before another run. Resume will leave them blocked.` : '';
  }
  window.QpilotAndroid = {async update(job) {
    if (job.target_type !== 'android' || !job.run) return;
    if (current !== job.run) { current = job.run; updated = 0; generation++; document.getElementById('androidCoverage')?.remove(); }
    if (busy || (job.status === 'running' && Date.now() - updated < 4000)) return;
    busy = true; updated = Date.now(); const token = generation;
    try {
      const response = await fetch(`/api/android/runs/${encodeURIComponent(current)}/coverage`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Coverage is unavailable.');
      if (token === generation) render(data, job);
    } catch (error) { if (token === generation) panel().querySelector('.coverage-message').textContent = error.message; }
    finally { busy = false; }
  }};
})();
