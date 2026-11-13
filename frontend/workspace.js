/* Workflow navigation points at actual evidence panes, never changes execution state. */
(() => {
  const targets = {setup:'.workspace-hero',live:'#qpilotLive',results:'#m-report',fixes:'#qpilotRepository'};
  document.querySelectorAll('[data-workspace-step]').forEach(button => {
    button.onclick = () => {
      const node = document.querySelector(targets[button.dataset.workspaceStep]);
      if (!node) return;
      node.scrollIntoView({behavior:'smooth',block:'start'});
      node.setAttribute('tabindex','-1'); node.focus({preventScroll:true});
      document.querySelectorAll('[data-workspace-step]').forEach(b => b.removeAttribute('aria-current'));
      button.setAttribute('aria-current','step');
    };
  });
  function sync() {
    const state = document.body.dataset.setupState;
    const current = state === 'running' ? 'live' : state === 'results' ? 'results' : 'setup';
    document.querySelectorAll('[data-workspace-step]').forEach(button => {
      const step = button.dataset.workspaceStep;
      button.disabled = !document.querySelector(targets[step]) || (step === 'setup' && state === 'running');
      if (step === current) button.setAttribute('aria-current','step');
      else button.removeAttribute('aria-current');
    });
  }
  new MutationObserver(sync).observe(document.body,{attributes:true,attributeFilter:['data-setup-state']});
  new MutationObserver(sync).observe(document.getElementById('thread') || document.querySelector('main.chat'),{childList:true,subtree:true});
  sync();
})();
