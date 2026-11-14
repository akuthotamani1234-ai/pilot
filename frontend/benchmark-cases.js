/* Select known truth explicitly; never derive expected results from execution outcomes. */
(() => {
  const runs = document.getElementById('runs'), field = document.getElementById('expected');
  const section = document.createElement('details'); let generation = 0, cases = [];
  section.innerHTML = '<summary>Choose known-truth cases from a run</summary><p>Mark only outcomes independently verified against requirements or deliberately seeded defects. Leave unknown cases unassessed.</p><div class="truth-cases"></div><button type="button" class="secondary">Use selected expectations</button><p class="truth-message" role="status"></p>';
  field.closest('label').before(section);
  runs.addEventListener('change', async () => {
    const run = [...runs.selectedOptions].find(option => option.value)?.value;
    const token = ++generation, list = section.querySelector('.truth-cases'); list.replaceChildren(); cases = [];
    if (!run) return;
    section.querySelector('.truth-message').textContent = 'Loading case IDs without copying observed outcomes…';
    try {
      const response = await fetch(`/api/cases/${encodeURIComponent(run)}/download`);
      if (!response.ok) throw new Error('Case inventory unavailable.');
      const data = await response.json(); if (token !== generation) return;
      if (!Array.isArray(data)) throw new Error('Case inventory is invalid.');
      cases = data;
      for (const item of cases) {
        const label = document.createElement('label'), title = document.createElement('span'), select = document.createElement('select');
        title.textContent = `${item.id} — ${item.title}`;
        for (const [value,text] of [['','Unassessed'],['passed','Clean behavior: should pass'],['failed','Known defect: should fail']]) {
          const option = document.createElement('option'); option.value = value; option.textContent = text; select.append(option);
        }
        select.dataset.caseId = item.id; select.setAttribute('aria-label',`Known expected outcome for ${item.id}`);
        label.append(title,select); list.append(label);
      }
      section.querySelector('.truth-message').textContent = `Cases from ${run}. Use the same case IDs across repeated runs.`;
    } catch(error) { if (token === generation) section.querySelector('.truth-message').textContent = error.message; }
  });
  section.querySelector('button').onclick = () => {
    const expected = Object.fromEntries([...section.querySelectorAll('select')].filter(select => select.value).map(select => [select.dataset.caseId,select.value]));
    if (!Object.keys(expected).length) { section.querySelector('.truth-message').textContent = 'Choose at least one independently known outcome.'; return; }
    field.value = JSON.stringify(expected,null,2);
    section.querySelector('.truth-message').textContent = 'Expectations copied. Review them before adding the benchmark condition.';
  };
})();
