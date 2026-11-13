/* Reviewable repository changes; preparation and publication remain separate actions. */
(() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"
  })[c]);
  async function api(url, body) {
    const response = await fetch(url, body === undefined ? {} : {
      method:"POST", headers:{"Content-Type":"application/json", "X-Agentic-QA":"1"}, body:JSON.stringify(body)
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || `HTTP ${response.status}`);
    return value;
  }
  window.QpilotRepo = {
    async mount(run, host) {
      const base = `/api/runs/${encodeURIComponent(run)}/repo-fix`;
      let token = "", proposal = null, polling = false;
      host.classList.add("repository-workspace");
      host.innerHTML = '<p role="status">Loading repository repair options…</p>';
      try {
        const info = await api(base);
        if (!host.isConnected) return;
        const eligible = (info.candidates || []).filter(c => c.eligible);
        host.innerHTML = '<div class="repo-heading"><span class="eyebrow">FROM EVIDENCE TO CODE</span>' +
          '<h2>Fix with AI</h2><p>Connect your website’s source repository. Review proposed code changes and checks before creating a pull request.</p></div>' +
          `<p class="note">AI provider: <b>${esc(info.provider)}</b>. Your existing privacy policy applies to source code.</p>` +
          `<div class="fields"><label>GitHub repository<input data-repo type="url" placeholder="https://github.com/owner/repository" value="${esc(info.repo_url)}" autocomplete="off"></label>` +
          `<label>GitHub token<input data-token type="password" autocomplete="off" placeholder="${info.has_token ? "Configured token available" : "Required for private source and pull requests"}"></label></div>` +
          '<fieldset class="finding-choices"><legend>Choose findings to investigate and fix</legend>' +
          (info.candidates || []).map((c, i) => `<label class="finding-choice"><input type="checkbox" value="${esc(c.id)}" ${c.eligible && i < 5 ? "checked" : ""} ${c.eligible ? "" : "disabled"}>` +
            `<span><b>${esc(c.title)}</b><small>${esc(c.category)}${c.reason ? " · " + esc(c.reason) : ""}</small></span></label>`).join("") +
          `${!info.candidates?.length ? '<p>No triaged findings are available. Unfinished checks do not establish website defects.</p>' : ""}</fieldset>` +
          `<p class="muted small">${eligible.length} supported finding(s). Select at most five. AI may decline when the source does not establish a cause.</p>` +
          `<button class="primary" data-prepare type="button" ${eligible.length ? "" : "disabled"}>Prepare AI changes</button>` +
          '<p data-status role="status" aria-live="polite"></p><div data-preview></div>';
        const status = host.querySelector("[data-status]"), prepare = host.querySelector("[data-prepare]");
        const show = (plan) => {
          proposal = plan;
          const failed = (plan.validation || []).some(c => c.status === "failed");
          const preview = host.querySelector("[data-preview]");
          preview.innerHTML = `<div class="proposal-summary"><h3>Review proposed changes</h3><p>${esc(plan.repo)} · ${esc(plan.base_branch)} · commit <code>${esc(plan.base_commit?.slice(0, 12))}</code></p>` +
            `<p>${plan.files?.length || 0} changed file(s). These are proposed changes; the website has not been fixed or deployed.</p></div>` +
            (plan.applied || []).map(a => `<p><b>${esc(a.title)}</b><br>${esc(a.why)}</p>`).join("") +
            (plan.files || []).map(f => `<details class="file-diff" open><summary>${esc(f.path)}</summary><pre><code>${esc(f.diff)}</code></pre></details>`).join("") +
            '<h3>Validation</h3><ul class="validation-list">' + (plan.validation || []).map(c =>
              `<li class="validation-${esc(c.status)}"><b>${esc(c.name)} — ${esc(c.status)}</b><span>${esc(c.detail || "")}</span></li>`).join("") + '</ul>' +
            (plan.skipped || []).map(c => `<div class="note"><b>${esc(c.title)}</b><br>${esc(c.reason)}</div>`).join("") +
            '<label class="review-ack"><input data-reviewed type="checkbox"> I reviewed this diff and the validation limitations.</label>' +
            `<button data-publish class="primary" type="button" disabled>Create pull request</button><p data-publication role="status"></p>`;
          const publish = preview.querySelector("[data-publish]");
          preview.querySelector("[data-reviewed]").onchange = (event) => {
            publish.disabled = !event.target.checked || !plan.files?.length || failed;
          };
          publish.onclick = async () => {
            publish.disabled = true;
            const output = preview.querySelector("[data-publication]");
            output.textContent = "Creating the reviewed branch and pull request…";
            try {
              const result = await api(base + "/create", {proposal_id:proposal.proposal_id, token:token || host.querySelector("[data-token]").value});
              if (!/^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/pull\/\d+$/.test(result.pr_url || "")) throw new Error("GitHub returned an unexpected pull-request link");
              output.innerHTML = `<a href="${esc(result.pr_url)}" target="_blank" rel="noopener">Open pull request on GitHub ↗</a><p>Review and merge on GitHub, deploy, then use Recheck on the relevant findings.</p>`;
              token = ""; host.querySelector("[data-token]").value = "";
            } catch (error) { output.textContent = error.message; publish.disabled = false; }
          };
        };
        async function poll() {
          if (!host.isConnected || polling) return;
          polling = true;
          try {
            const value = await api(base);
            const state = value.preparation || {};
            status.textContent = state.detail || state.stage || state.status || "";
            if (state.status === "ready") { show(state.plan); prepare.disabled = false; }
            else if (state.status === "error") prepare.disabled = false;
            else if (state.status === "running") setTimeout(poll, 1200);
          } catch (error) { status.textContent = error.message; prepare.disabled = false; }
          finally { polling = false; }
        }
        prepare.onclick = async () => {
          const repo = host.querySelector("[data-repo]");
          if (!repo.reportValidity() || !/^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/.test(repo.value.trim())) {
            status.textContent = "Enter a GitHub repository link: https://github.com/owner/repository";
            return;
          }
          const selected = [...host.querySelectorAll('.finding-choices input:checked')].map(c => c.value);
          if (!selected.length || selected.length > 5) { status.textContent = "Select one to five supported findings."; return; }
          token = host.querySelector("[data-token]").value;
          prepare.disabled = true; proposal = null;
          host.querySelector("[data-preview]").replaceChildren();
          status.textContent = "Reading the repository snapshot and matching evidence…";
          try { await api(base + "/prepare", {repo_url:repo.value.trim(), token, selected_findings:selected}); poll(); }
          catch (error) { status.textContent = error.message; prepare.disabled = false; }
        };
        if (info.preparation?.status === "ready") show(info.preparation.plan);
        if (info.preparation?.status === "running") { prepare.disabled = true; poll(); }
      } catch (error) { host.textContent = `Repository options could not be loaded: ${error.message}`; }
    }
  };
})();
