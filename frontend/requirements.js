"use strict";
/* Requirements workspace (Jira Cloud + Confluence Cloud). Talks only to /api/requirements/* of this Studio.
   Every value from Jira, Confluence or the server is put on the page with textContent (never as HTML).
   An Atlassian API token is typed into a password box, sent once (PUT .../token) and never kept or shown again.
   A Studio access token (only when Studio login is on) lives in this tab's memory only. */
(() => {
  const $ = (id) => document.getElementById(id);
  const S = { auth: "", caps: null, conns: [], wizard: { step: 1, types: [], selected: new Set(), keys: [], token: "", job: null },
              ex: { page: 1, size: 25, sort: "key" }, poll: null };

  // ---------------------------------------------------------------- tiny DOM helper (text only)
  function h(tag, props, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === false || v === null || v === undefined) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "dataset") Object.assign(el.dataset, v);
      else el.setAttribute(k, v === true ? "" : String(v));
    }
    for (const kid of children.flat()) if (kid !== null && kid !== undefined && kid !== false)
      el.append(...kids(kid instanceof Node ? kid : document.createTextNode(String(kid))));
    return el;
  }
  // replaceChildren / append do not flatten lists or skip empty parts: every call goes through kids()
  const kids = (...parts) => parts.flat(Infinity).filter((x) => x !== null && x !== undefined && x !== false);
  const badge = (text, kind = "") => h("span", { class: `rq-badge ${kind}`, text });
  const when = (iso) => { if (!iso) return "—"; const d = new Date(iso); return isNaN(d) ? String(iso) : d.toLocaleString(); };
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const list = (s) => String(s || "").split(",").map((x) => x.trim()).filter(Boolean);

  // ---------------------------------------------------------------- API
  class ApiError extends Error { constructor(msg, status, detail) { super(msg); this.status = status; this.detail = detail; } }
  async function api(path, { method = "GET", body } = {}) {
    const headers = { "X-Agentic-QA": "1" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (S.auth) headers.Authorization = `Bearer ${S.auth}`;
    let res;
    try { res = await fetch(`/api/requirements${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) }); }
    catch (e) { throw new ApiError("The Studio server could not be reached. Is it still running?", 0); }
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (res.status === 401) { showSignin(); throw new ApiError("Sign in to continue.", 401); }
    if (!res.ok) {
      const d = data && data.detail;
      const msg = typeof d === "string" ? d : d && d.message ? `${d.message}${d.hint ? " — " + d.hint : ""}`
        : Array.isArray(d) ? d.map((x) => x.msg).join("; ") : `Request failed (${res.status})`;
      throw new ApiError(res.status === 403 ? `Not allowed: ${msg}` : msg, res.status, d);
    }
    return data;
  }
  function banner(text, ok = false) {
    const b = $("banner");
    if (!text) { b.hidden = true; return; }
    b.textContent = text; b.className = `rq-banner${ok ? " ok" : ""}`; b.hidden = false;
    b.setAttribute("role", ok ? "status" : "alert");
  }
  function showSignin() { $("signin").hidden = false; $("signinToken").focus(); }
  $("signinForm").addEventListener("submit", (e) => {
    e.preventDefault(); S.auth = $("signinToken").value.trim(); $("signinToken").value = "";
    $("signin").hidden = true; start();
  });

  // ---------------------------------------------------------------- routing
  const navigation = [...document.querySelectorAll(".rq-nav a[data-view]")];
  const VIEWS = navigation.map((link) => link.dataset.view);
  function route() {
    if (!S.caps) return;
    const view = VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview";
    for (const v of VIEWS) $(`view-${v}`).hidden = v !== view;
    for (const link of navigation) {
      if (link.dataset.view === view) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    document.title = `Qpilot | ${$(`view-${view}`).dataset.title}`;
    banner("");
    ({ overview, integrations, import: wizardOpen, explorer, analysis: analysisView, reviews,
      confluence: confluenceView, coverage: coverageView, history, settings: settingsView })[view]?.();
  }
  window.addEventListener("hashchange", () => { route(); $("rqMain").focus(); });
  document.querySelector(".rq-skip").addEventListener("click", (event) => {
    event.preventDefault();
    $("rqMain").focus();
  });

  // ---------------------------------------------------------------- 1 overview
  async function overview() {
    const stats = $("stats");
    stats.setAttribute("aria-busy", "true");
    try {
      const o = await api("/overview");
      const tile = (n, label, kind = "") => h("div", { class: `rq-stat ${kind}` }, h("b", { text: n }), h("span", { text: label }));
      stats.replaceChildren(...kids(tile(o.requirements, "requirements imported"), tile(o.pages, "Confluence pages"),
        tile(o.criteria, "acceptance criteria (analysed)"), tile(o.analysed, "analysed"),
        tile(o.pending_reviews, "ideas waiting for review", o.pending_reviews ? "warn" : ""),
        tile(o.conflicts_open, "open conflicts", o.conflicts_open ? "bad" : ""),
        tile(o.stale_analyses, "analyses out of date", o.stale_analyses ? "warn" : ""),
        tile(o.missing, "no longer in Atlassian", o.missing ? "warn" : "")));
      $("ovConnections").replaceChildren(...kids(o.connections.length
        ? h("ul", { class: "rq-list" }, o.connections.map((c) => h("li", {}, h("b", { text: c.id }), ` ${c.product} · ${c.site_url} `,
            c.credential ? badge("token set", "ok") : badge("no token", "warn"))))
        : h("p", { class: "small" }, "No site connected yet. ", h("a", { href: "#integrations", text: "Connect Jira" }), ".")));
      const last = o.last_import;
      $("ovSync").replaceChildren(...kids(last ? h("dl", { class: "rq-kv" },
        h("dt", { text: "Finished" }), h("dd", { text: when(last.finished_at) }),
        h("dt", { text: "Connection" }), h("dd", { text: last.connection_id }),
        h("dt", { text: "Mode" }), h("dd", { text: last.mode }),
        h("dt", { text: "Status" }), h("dd", {}, statusBadge(last.status)),
        h("dt", { text: "New / changed" }), h("dd", { text: `${last.result.new || 0} / ${last.result.changed || 0}` }))
        : h("p", { class: "small" }, "Nothing imported yet. ", h("a", { href: "#import", text: "Start an import" }), ".")));
      actionsPanel(o.capabilities);
      navCount(o.pending_reviews);
    } catch (e) { stats.replaceChildren(...kids(h("p", { class: "small", text: e.message }))); banner(e.message); }
    finally { stats.removeAttribute("aria-busy"); }
  }
  function actionsPanel(caps) {
    const coming = (S.caps && S.caps.coming) || {};
    const go = (label, sub, href) => h("a", { class: "primary rq-action", href }, h("span", { text: label }), h("small", { text: sub }));
    const later = (key, label) => h("div", { class: "rq-coming", role: "note" }, h("b", { text: label }), `Not available yet — comes with ${coming[key] || "a later phase"}.`);
    $("actions").replaceChildren(...kids(
      caps.import_requirements ? go("Import requirements", "read stories from Jira", "#import") : null,
      caps.analyze_requirements ? go("Analyze requirements", "criteria, gaps, conflicts", "#analysis") : null,
      caps.review_suggestions ? go("Review suggestions", "accept, correct or reject ideas", "#reviews") : null,
      caps.generate_test_cases ? null : later("generate_test_cases", "Generate test cases"),
      caps.run_selected_tests ? null : later("run_selected_tests", "Run selected tests"),
      caps.run_impacted_tests ? null : later("run_impacted_tests", "Run impacted tests"),
      caps.run_all_approved_tests ? null : later("run_all_approved_tests", "Run all approved tests")));
  }
  const statusBadge = (s) => badge(s || "—", { complete: "ok", partial: "warn", failed: "bad", cancelled: "warn", running: "info" }[s] || "");
  function navCount(n) { const c = $("navReviews"); c.hidden = !n; c.textContent = n || ""; c.setAttribute("aria-label", `${n} waiting`); }

  // ---------------------------------------------------------------- 2 integrations
  async function integrations() {
    const box = $("connCards");
    box.replaceChildren(...kids(h("p", { class: "small", text: "Loading connections…" })));
    try {
      const data = await api("/connections");
      S.conns = data.connections;
      const legacy = $("legacyWarning");
      legacy.hidden = !data.defect_creation_writes_to_jira;
      legacy.textContent = data.defect_creation_writes_to_jira
        ? `Note: the older defect creation is switched on in .env (JIRA_PROJECT=${data.defect_creation_project}). Test runs will create Bug issues there. The requirements connections below never write.` : "";
      const byProduct = (p) => S.conns.filter((c) => c.product === p);
      box.replaceChildren(...kids(connCard("jira", byProduct("jira")[0]), connCard("confluence", byProduct("confluence")[0])));
    } catch (e) { box.replaceChildren(...kids(h("p", { class: "small", text: e.message }))); }
  }
  function connCard(product, conn) {
    const name = product === "jira" ? "Jira Cloud" : "Confluence Cloud";
    const id = conn ? conn.id : (product === "jira" ? "jira-main" : "conf-main");
    const status = h("p", { class: "small", role: "status", "aria-live": "polite" });
    const site = h("input", { id: `${product}Site`, type: "url", required: true, placeholder: "https://your-site.atlassian.net", value: conn ? conn.site_url : "" });
    const email = h("input", { id: `${product}Email`, type: "email", required: true, autocomplete: "off", value: conn ? conn.email : "" });
    const types = h("input", { id: `${product}Types`, value: conn ? conn.work_item_types.join(", ") : "Story" });
    const cred = conn ? conn.credential : { configured: false };
    const credText = cred.configured ? (cred.source === "environment" ? "token from .env" : "token saved") : "no token";
    const tokenInput = h("input", { id: `${product}Token`, type: "password", autocomplete: "new-password", placeholder: cred.configured ? "paste a new token to replace it" : "paste the API token" });

    const save = h("form", { onsubmit: async (e) => {
      e.preventDefault(); status.textContent = "Saving…";
      try {
        await api("/connections", { method: "POST", body: { id, product, site_url: site.value.trim(), email: email.value.trim(),
          work_item_types: product === "jira" ? list(types.value) : ["Story"] } });
        const token = tokenInput.value.trim();
        tokenInput.value = "";  // (the token leaves the page now; it is never kept)
        if (token) await api(`/connections/${encodeURIComponent(id)}/token`, { method: "PUT", body: { token } });
        status.textContent = "Saved. Use “Test connection” to check it.";
        integrations();
      } catch (err) { tokenInput.value = ""; status.textContent = err.message; }
    } },
      h("label", { for: site.id }, "Site address", site),
      h("label", { for: email.id }, "Account email", email),
      product === "jira" ? h("label", { for: types.id }, "Work-item types to import (comma separated)", types) : null,
      h("label", { for: tokenInput.id }, "API token ", h("span", { class: "small", text: "(stored encrypted, never shown again)" }), tokenInput),
      h("div", { class: "rq-row" }, h("button", { class: "primary", type: "submit", text: conn ? "Save changes" : "Connect" })));

    const discovery = h("div", { "aria-live": "polite" });
    const jira = product === "jira";
    const collection = jira ? "projects" : "spaces";
    const actions = conn ? h("div", { class: "rq-row" },
      h("button", { class: "secondary", type: "button", text: "Test connection", onclick: async () => {
        status.textContent = "Testing…";
        try { const r = await api(`/connections/${encodeURIComponent(id)}/test`, { method: "POST" });
          status.textContent = product === "jira" ? `Connected as ${r.account}. ${plural(r.projects, "project")} visible. Read-only.` : `Connected. ${plural(r.spaces, "space")} visible. Read-only.`;
        } catch (err) { status.textContent = err.message; }
      } }),
      h("button", { class: "secondary", type: "button", text: jira ? "Discover projects" : "Discover spaces", onclick: async () => {
        discovery.textContent = "Loading…";
        try {
          const data = await api(`/connections/${encodeURIComponent(id)}/${collection}`);
          discovery.replaceChildren(data[collection].length ? h("ul", { class: "rq-list" },
            data[collection].map((entry) => h("li", {}, `${entry.key} — ${entry.name}`,
              jira ? null : h("button", { class: "secondary rq-space-import", type: "button",
                text: `Import space ${entry.key}`, onclick: () => {
                  if (W.job || W.submitting) { discovery.textContent = "An import is already active in this tab."; return; }
                  W.lastImport = { conn: id, body: { mode: "space", space_key: entry.key } };
                  location.hash = "import";
                  submitImport();
                } }))))
            : h("p", { class: "small", text: `No ${collection} are visible to this account.` }));
        } catch (err) { discovery.textContent = err.message; }
      } }),
      cred.configured && cred.source === "studio" ? h("button", { class: "secondary", type: "button", text: "Remove token", onclick: async () => {
        try { await api(`/connections/${encodeURIComponent(id)}/token`, { method: "DELETE" }); integrations(); } catch (err) { status.textContent = err.message; }
      } }) : null,
      h("button", { class: "secondary", type: "button", text: "Disconnect", onclick: async () => {
        if (!confirm(`Disconnect ${name}? Imported requirements stay; the saved token is removed.`)) return;
        try { await api(`/connections/${encodeURIComponent(id)}`, { method: "DELETE" }); integrations(); } catch (err) { status.textContent = err.message; }
      } })) : null;

    return h("section", { class: "lab-card rq-conn", "aria-label": name },
      h("h3", {}, name, conn ? badge("configured", "info") : badge("not connected"), badge("read-only", "info"),
        conn ? badge(credText, cred.configured ? "ok" : "warn") : null),
      conn ? h("p", { class: "small" }, `Last successful import: ${when(conn.last_success)}`) : null,
      save, actions, status, discovery);
  }

  // ---------------------------------------------------------------- 3 import wizard
  const W = S.wizard;
  function wizardStep(n) {
    W.step = n;
    document.querySelectorAll("#wizard .rq-step").forEach((p) => { p.hidden = Number(p.dataset.panel) !== n; });
    document.querySelectorAll("#wizardSteps li").forEach((li) => {
      const s = Number(li.dataset.step);
      if (s === Math.min(n, 5)) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
      li.classList.toggle("done", s < Math.min(n, 5));
    });
    const first = document.querySelector(`#wizard [data-panel="${n}"] h2`);
    if (first) { first.tabIndex = -1; first.focus(); }
  }
  const mode = () => document.querySelector("input[name=wMode]:checked").value;
  async function wizardOpen() {
    try {
      const data = await api("/connections");
      S.conns = data.connections;
      const jiras = S.conns.filter((c) => c.product === "jira");
      $("wConn").replaceChildren(...kids(...jiras.map((c) => h("option", { value: c.id, text: `${c.id} — ${c.site_url}` }))));
      $("wConf").replaceChildren(...kids(h("option", { value: "", text: "(do not read pages)" }),
        ...S.conns.filter((c) => c.product === "confluence").map((c) => h("option", { value: c.id, text: c.id }))));
      $("wConnHelp").replaceChildren(...kids(jiras.length ? "" : h("span", {}, "No Jira connection yet. ", h("a", { href: "#integrations", text: "Connect Jira first" }), ".")));
      document.querySelector('[data-panel="1"] [data-next="2"]').disabled = !jiras.length;
    } catch (e) { banner(e.message); }
    if (!W.job && !W.submitting && W.step !== 5) wizardStep(1);
  }
  document.querySelectorAll("#wizard [data-next]").forEach((b) => b.addEventListener("click", async () => {
    const to = Number(b.dataset.next);
    try {
      if (to === 2) await stepProject();
      if (to === 3 && W.step === 2) await stepTypes();
      if (to === 4) await stepPreview();
      if (to === 6) $("anStatus").textContent = "";
      wizardStep(to);
    } catch (e) { banner(e.message); }
  }));
  async function stepProject() {
    const items = mode() === "items";
    $("wKeysBox").hidden = !items;
    $("issueResults").replaceChildren();
    $("issuePicker").open = false;
    if (!items) {
      $("wProjectBox").hidden = false;
      await loadProjects();
    } else {
      $("wProjectBox").hidden = true;
    }
  }
  async function loadProjects() {
    const sel = $("wProject");
    sel.replaceChildren(...kids(h("option", { value: "", text: "Loading projects…" })));
    const r = await api(`/connections/${encodeURIComponent($("wConn").value)}/projects`);
    sel.replaceChildren(...kids(...(r.projects.length ? r.projects.map((p) => h("option", { value: p.key, text: `${p.key} — ${p.name}` }))
      : [h("option", { value: "", text: "No projects visible to this account" })])));
  }
  $("issuePicker").addEventListener("toggle", async () => {
    if (!$("issuePicker").open) return;
    $("wProjectBox").hidden = false;
    try { await loadProjects(); }
    catch (error) { $("issueResults").textContent = error.message; }
  });
  $("findIssues").addEventListener("click", async () => {
    const output = $("issueResults");
    const project = $("wProject").value;
    const query = $("issueQuery").value.trim();
    if (!project || !query) { output.textContent = "Choose a project and enter part of a summary."; return; }
    output.textContent = "Searching Jira…";
    const button = $("findIssues");
    button.disabled = true;
    try {
      const result = await api(`/connections/${encodeURIComponent($("wConn").value)}/preview`,
        { method: "POST", body: { filters: { project, text: query }, limit: 25 } });
      output.replaceChildren(...kids(
        result.next_page_token ? h("p", { class: "small", text: "Showing the first page. Refine the search to find more specific matches." }) : null,
        result.items.length ? h("ul", { class: "rq-list" }, result.items.filter((item) => item.state !== "unreadable").map((item) =>
          h("li", {}, h("button", { type: "button", class: "rq-open", text: `Add ${item.key} — ${item.summary}`, onclick: (event) => {
            const keys = $("wKeys");
            keys.value = [keys.value.trim(), item.key].filter(Boolean).join(", ");
            event.currentTarget.textContent = `${item.key} added`;
            event.currentTarget.disabled = true;
          } })))) : h("p", { text: "No matching work items." })));
    } catch (error) { output.textContent = error.message; }
    finally { button.disabled = false; }
  });
  async function stepTypes() {
    const box = $("wTypes");
    $("wFilters").hidden = mode() === "items";
    $("wFilters").open = mode() === "jql";
    if (mode() === "items") { box.replaceChildren(...kids(h("p", { class: "small", text: "Specific work items are imported whatever their type." }))); return; }
    if (!$("wProject").value) throw new Error("Choose a project.");
    box.replaceChildren(...kids(h("p", { class: "small", text: "Reading the project's work-item types…" })));
    const r = await api(`/connections/${encodeURIComponent($("wConn").value)}/projects/${encodeURIComponent($("wProject").value)}/types`);
    W.types = r.types;
    box.replaceChildren(...kids(...r.types.map((t) => h("label", {}, h("input", { type: "checkbox", name: "wType", value: t.name, checked: t.selected }),
      ` ${t.name} `, h("span", { class: "small", text: t.subtask ? "(sub-task)" : `(${t.count ?? "?"})` })))));
  }
  function filters() {
    const f = { project: $("wProject").value, types: [...document.querySelectorAll("input[name=wType]:checked")].map((x) => x.value),
      statuses: list($("fStatus").value), priorities: list($("fPriority").value), labels: list($("fLabels").value),
      epic: $("fEpic").value.trim().toUpperCase(), sprint: $("fSprint").value.trim(), assignee: $("fAssignee").value,
      created_from: $("fCreatedFrom").value, created_to: $("fCreatedTo").value, updated_from: $("fUpdatedFrom").value,
      updated_to: $("fUpdatedTo").value, text: $("fText").value.trim(), jql: $("fJql").value.trim() };
    for (const k of Object.keys(f)) if (f[k] === "" || (Array.isArray(f[k]) && !f[k].length && k !== "types")) delete f[k];
    return f;
  }
  $("fJqlCheck").addEventListener("click", async () => {
    const out = $("fJqlResult");
    out.textContent = "Checking…";
    try { const r = await api(`/connections/${encodeURIComponent($("wConn").value)}/jql/validate`, { method: "POST", body: { project: $("wProject").value, jql: $("fJql").value } });
      out.textContent = r.valid ? "Jira accepts this filter." : `Not valid: ${r.errors.join("; ")}`;
    } catch (e) { out.textContent = e.message; }
  });
  let pvToken = "";
  let pvCounts;
  function updatePreviewSelection() {
    const all = $("pvAll");
    all.checked = W.keys.length > 0 && W.selected.size === W.keys.length;
    all.indeterminate = W.selected.size > 0 && !all.checked;
    all.disabled = !W.keys.length;
    $("startImport").disabled = !W.selected.size && (mode() === "items" || W.keys.length > 0);
  }
  async function stepPreview(more = false) {
    if (mode() !== "items" && !document.querySelectorAll("input[name=wType]:checked").length) throw new Error("Choose at least one work-item type.");
    if (mode() === "jql" && !$("fJql").value.trim()) throw new Error("Enter a JQL filter.");
    const body = mode() === "items" ? { keys: $("wKeys").value } : { filters: filters() };
    if (mode() === "items" && !$("wKeys").value.trim()) throw new Error("Enter one or more work-item keys or links.");
    body.limit = 50; if (more) body.next_page_token = pvToken;
    $("pvSummary").textContent = "Asking Jira…";
    const tbody = $("pvTable").tBodies[0];
    if (!more) {
      tbody.replaceChildren();
      W.selected = new Set();
      W.keys = [];
      pvCounts = { new: 0, updated: 0, unchanged: 0, reappeared: 0, unreadable: 0 };
    }
    const r = await api(`/connections/${encodeURIComponent($("wConn").value)}/preview`, { method: "POST", body });
    pvToken = r.next_page_token || "";
    $("pvMore").hidden = !pvToken;
    if (r.items.length) tbody.querySelector(".rq-empty")?.closest("tr").remove();
    for (const it of r.items) {
      pvCounts[it.state] += 1;
      W.keys.push(it.key);
      W.selected.add(it.key);
      const box = h("input", { type: "checkbox", checked: true, "aria-label": `Import ${it.key}`,
        onchange: (e) => {
          if (e.target.checked) W.selected.add(it.key);
          else W.selected.delete(it.key);
          updatePreviewSelection();
        } });
      const state = { new: badge("new", "info"), updated: badge("updated", "warn"), unchanged: badge("unchanged"), reappeared: badge("back again", "warn"), unreadable: badge("unreadable", "bad") }[it.state];
      tbody.append(...kids(h("tr", {}, h("td", {}, box), h("td", { text: it.key }), h("td", { text: it.summary || it.error || "" }),
        h("td", { text: it.type || "" }), h("td", { text: it.status || "" }), h("td", {}, state || it.state))));
    }
    updatePreviewSelection();
    const shown = Object.values(pvCounts).reduce((sum, count) => sum + count, 0);
    if (!tbody.rows.length) tbody.append(...kids(h("tr", {}, h("td", { colspan: 6, class: "rq-empty" }, "Nothing matches. Check the project, the work-item types and the filters."))));
    const total = r.estimated_total ?? "?";
    $("pvSummary").textContent = `${plural(shown, "work item")} shown of about ${total}. ${pvCounts.new} new, ${pvCounts.updated} updated, ${pvCounts.unchanged} unchanged.`
      + (pvCounts.reappeared ? ` ${pvCounts.reappeared} back again.` : "")
      + (pvCounts.unreadable ? ` ${pvCounts.unreadable} unreadable.` : "")
      + (r.inaccessible.length ? ` Not found or not permitted: ${r.inaccessible.join(", ")}.` : "");
  }
  $("pvMore").addEventListener("click", async () => {
    const button = $("pvMore");
    button.disabled = true;
    try { await stepPreview(true); }
    catch (e) { banner(e.message); }
    finally { button.disabled = false; }
  });
  $("pvAll").addEventListener("change", (e) => {
    $("pvTable").querySelectorAll("tbody input[type=checkbox]").forEach((b) => { b.checked = e.target.checked; });
    W.selected = e.target.checked ? new Set(W.keys) : new Set();
    updatePreviewSelection();
  });
  $("newImport").addEventListener("click", () => { wizardStep(1); wizardOpen(); });
  $("startImport").addEventListener("click", () => runImport().catch((e) => banner(e.message)));
  $("impRetry").addEventListener("click", () => {
    if (W.job) {
      $("impRetry").hidden = true;
      watch(W.job);
    } else {
      submitImport();
    }
  });
  async function runImport() {
    const conn = $("wConn").value;
    let body;
    const allTicked = W.selected.size === W.keys.length;
    if (mode() === "items" || !allTicked) {
      if (!W.selected.size) throw new Error("Tick at least one work item.");
      body = { mode: "items", keys: [...W.selected].join(","), include: [...document.querySelectorAll("input[name=wInclude]:checked")].map((x) => x.value),
               confluence_connection: $("wConf").value || "" };
    } else body = { mode: mode() === "jql" ? "full" : mode(), filters: filters() };
    W.lastImport = { conn, body };
    await submitImport();
  }
  async function submitImport() {
    const { conn, body } = W.lastImport;
    W.submitting = true;
    wizardStep(5);
    $("impResult").replaceChildren(); $("impRetry").hidden = true; $("toAnalyze").hidden = true; $("impCancel").hidden = true;
    $("impBar").className = "rq-progress"; $("impStatus").textContent = "Starting…";
    $("newImport").hidden = true;
    try {
      const job = await api(`/connections/${encodeURIComponent(conn)}/imports`, { method: "POST", body });
      W.job = job.id;
      $("impCancel").hidden = false;
      watch(job.id);
    } catch (e) {
      $("impStatus").textContent = e.message;
      $("impBar").className = "rq-progress failed";
      $("impRetry").hidden = false;
      $("newImport").hidden = false;
    } finally { W.submitting = false; }
  }
  $("impCancel").addEventListener("click", async () => {
    if (!W.job) return;
    try { await api(`/imports/${W.job}/cancel`, { method: "POST" }); $("impStatus").textContent = "Stopping after the current page…"; } catch (e) { banner(e.message); }
  });
  function watch(id) {
    clearTimeout(S.poll);
    const tick = async () => {
      try {
        const j = await api(`/imports/${id}`);
        const p = j.progress || {};
        if (j.status === "running") {
          $("impStatus").textContent = `Reading… ${p.pages || 0} page(s), ${p.new || 0} new, ${p.changed || 0} changed, ${p.unchanged || 0} unchanged.`;
          $("impBar").setAttribute("aria-valuetext", $("impStatus").textContent);
          S.poll = setTimeout(tick, 700); return;
        }
        W.job = null;
        showResult(j);
      } catch (e) { $("impStatus").textContent = e.message; $("impRetry").hidden = false; }
    };
    tick();
  }
  function showResult(j) {
    const r = j.result || {};
    const ok = ["complete", "partial"].includes(j.status);
    $("impBar").className = `rq-progress ${ok ? "done" : "failed"}`;
    $("impCancel").hidden = true;
    $("impRetry").hidden = j.status === "complete";
    $("impStatus").textContent = j.status === "failed" ? `The import failed: ${j.error || r.error || "unknown error"}`
      : j.status === "cancelled" ? "Cancelled. The next import continues where this one stopped."
      : `Import ${j.status} in ${r.duration_s ?? "?"} s.`;
    const tile = (n, label) => h("div", { class: "rq-stat" }, h("b", { text: n }), h("span", { text: label }));
    const sections = [h("div", { class: "rq-result" }, tile(r.new || 0, "new"), tile((r.changed || 0) + (r.reappeared || 0), "updated"),
      tile(r.unchanged || 0, "unchanged"), tile((r.missing || []).length + (r.inaccessible || []).length, "missing / not accessible"),
      tile((r.failed_items || []).length, "failed"), tile(Object.values(r.criteria_extracted || {}).reduce((a, b) => a + b, 0), "criteria found"),
      tile((r.needs_analysis || []).length, "need analysis"))];
    const block = (title, items, kind = "") => items && items.length ? h("div", { class: `rq-issue ${kind}` }, h("b", { text: title }), h("ul", { class: "rq-list" }, items.map((x) => h("li", { text: typeof x === "string" ? x : `${x.requirement}: ${x.reasons.join("; ")}` })))) : null;
    sections.push(block("Warnings", r.warnings), block("Failed items", r.failed_items, "conflict"), block("Not found or not permitted", r.inaccessible),
      block("No longer in Jira (kept, marked missing)", r.missing), block("Analysed requirements now out of date", r.affected),
      r.last_success ? h("p", { class: "small", text: `Last successful import: ${when(r.last_success)}` }) : null);
    $("impResult").replaceChildren(...kids(...sections));
    const needsAnalysis = new Set(r.needs_analysis || []);
    W.imported = W.lastImport.body.mode === "space" ? [] : [...(r.new_keys || []), ...(r.changed_keys || [])]
      .filter((key) => needsAnalysis.has(key));
    W.importConn = W.lastImport.conn;
    $("toAnalyze").hidden = !(S.caps && S.caps.capabilities.analyze_requirements) || !W.imported.length;
    $("newImport").hidden = false;
  }
  $("anRun").addEventListener("click", async () => {
    const keys = W.imported || [];
    const out = $("anStatus");
    let done = 0;
    for (const key of keys) {
      out.textContent = `Analysing ${key} (${done + 1} of ${keys.length})…`;
      try { await api(`/items/${encodeURIComponent(W.importConn)}/${encodeURIComponent(key)}/analyze`, { method: "POST", body: { ai: $("anAi").checked ? "auto" : "off" } }); done += 1; }
      catch (e) { out.textContent = `${key}: ${e.message}`; return; }
    }
    out.replaceChildren(...kids(`${plural(done, "requirement")} analysed. `, h("a", { href: "#reviews", text: "Review the ideas" }), " or ", h("a", { href: "#explorer", text: "open the requirements" }), "."));
  });
  document.querySelectorAll("input[name=wMode]").forEach((r) => r.addEventListener("change", () => { W.selected = new Set(); }));

  // ---------------------------------------------------------------- 4 explorer
  let exTimer;
  ["exQ", "exType", "exStatus", "exAnalysis", "exMissing"].forEach((id) => $(id).addEventListener(id === "exQ" ? "input" : "change", () => {
    clearTimeout(exTimer); exTimer = setTimeout(() => { S.ex.page = 1; explorer(); }, id === "exQ" ? 250 : 0);
  }));
  $("exForm").addEventListener("submit", (e) => e.preventDefault());
  document.querySelectorAll("#exTable th button").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.sort;
    S.ex.sort = S.ex.sort === k ? `-${k}` : k; explorer();
  }));
  async function explorer() {
    const tbody = $("exTable").tBodies[0];
    $("exTable").setAttribute("aria-busy", "true");
    const q = new URLSearchParams({ kind: "jira_issue", q: $("exQ").value, type: $("exType").value, status: $("exStatus").value,
      analysis: $("exAnalysis").value, missing: $("exMissing").checked, sort: S.ex.sort, page: S.ex.page, size: S.ex.size });
    try {
      const r = await api(`/items?${q}`);
      if (S.ex.page === 1 && !$("exQ").value && !$("exType").value) fillFacets();
      document.querySelectorAll("#exTable th button").forEach((b) => {
        const k = b.dataset.sort;
        const s = S.ex.sort === k ? "ascending" : S.ex.sort === `-${k}` ? "descending" : null;
        if (s) b.parentElement.setAttribute("aria-sort", s); else b.parentElement.removeAttribute("aria-sort");
      });
      tbody.replaceChildren(...kids(...r.items.map((it) => h("tr", { class: it.present ? "" : "missing" },
        h("td", {}, h("button", { class: "rq-open", type: "button", text: it.key, "aria-label": `Open ${it.key}`, onclick: () => openDetail(it.connection_id, it.key) })),
        h("td", { text: it.summary }), h("td", { text: it.type }), h("td", { text: it.priority }), h("td", { text: it.status }),
        h("td", { text: it.criteria }), h("td", { text: it.linked_pages }),
        h("td", {}, { not_analyzed: badge("not analysed"), current: badge("analysed", "ok"), stale: badge("out of date", "warn") }[it.analysis],
          it.present ? null : badge("missing", "bad")),
        h("td", { text: it.pending_reviews ? `${it.pending_reviews} pending` : it.review_status || "—" }),
        h("td", { text: it.covered === null || !it.criteria ? "—" : `${it.covered}/${it.criteria}` }),
        h("td", { text: `v${it.version}` }), h("td", { text: when(it.last_synced) })))));
      if (!r.items.length) tbody.append(...kids(h("tr", {}, h("td", { colspan: 12, class: "rq-empty" },
        r.total === 0 && !$("exQ").value ? h("span", {}, "No requirements imported yet. ", h("a", { href: "#import", text: "Import from Jira" }), ".") : "Nothing matches these filters."))));
      const pages = Math.max(1, Math.ceil(r.total / r.size));
      $("exPager").replaceChildren(...kids(`${plural(r.total, "requirement")} · page ${r.page} of ${pages}`,
        h("button", { class: "secondary", type: "button", text: "Previous", disabled: r.page <= 1, onclick: () => { S.ex.page -= 1; explorer(); } }),
        h("button", { class: "secondary", type: "button", text: "Next", disabled: r.page >= pages, onclick: () => { S.ex.page += 1; explorer(); } })));
    } catch (e) { tbody.replaceChildren(...kids(h("tr", {}, h("td", { colspan: 12, class: "rq-empty", text: e.message })))); }
    finally { $("exTable").removeAttribute("aria-busy"); }
  }
  async function fillFacets() {
    try {
      const all = await api("/items?kind=jira_issue&size=100&missing=true");
      for (const [id, field, label] of [["exType", "type", "All types"], ["exStatus", "status", "All statuses"]]) {
        const keep = $(id).value;
        const values = [...new Set(all.items.map((i) => i[field]).filter(Boolean))].sort();
        $(id).replaceChildren(...kids(h("option", { value: "", text: label }), ...values.map((v) => h("option", { value: v, text: v }))));
        $(id).value = keep;
      }
    } catch (e) { /* the table already shows the error */ }
  }

  // ---------------------------------------------------------------- requirement detail (details, analysis, versions, links)
  const D = { conn: "", key: "", data: null, tab: "" };
  async function openDetail(conn, key, tab = "details") {
    D.conn = conn; D.key = key; D.data = null;
    $("dtKey").textContent = key; $("dtTitle").textContent = "Loading…"; $("dtMeta").textContent = "";
    $("dtBody").replaceChildren();
    if (!$("detail").open) $("detail").showModal();
    try {
      const result = await api(`/items/${encodeURIComponent(conn)}/${encodeURIComponent(key)}`);
      if (D.conn !== conn || D.key !== key) return;
      D.data = result;
      const d = D.data;
      $("dtTitle").textContent = d.title;
      $("dtMeta").replaceChildren(...kids(`${d.fields.type || d.kind} · ${d.fields.status || ""} · version ${d.version} · synced ${when(d.retrieved_at)} `,
        d.present ? null : badge("no longer in Atlassian", "bad"), " ", h("a", { href: d.url, target: "_blank", rel: "noopener noreferrer", text: "Open in Atlassian" })));
      showTab(tab);
    } catch (e) { $("dtTitle").textContent = key; $("dtBody").replaceChildren(...kids(h("p", { text: e.message }))); }
  }
  $("dtClose").addEventListener("click", () => $("detail").close());
  document.querySelectorAll(".rq-tabs [role=tab]").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  document.querySelector(".rq-tabs").addEventListener("keydown", (e) => {
    const tabs = [...document.querySelectorAll(".rq-tabs [role=tab]")];
    const i = tabs.indexOf(document.activeElement);
    if (i < 0 || !["ArrowRight", "ArrowLeft"].includes(e.key)) return;
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    next.focus(); showTab(next.dataset.tab);
  });
  function showTab(tab) {
    document.querySelectorAll(".rq-tabs [role=tab]").forEach((t) => { t.setAttribute("aria-selected", String(t.dataset.tab === tab)); t.tabIndex = t.dataset.tab === tab ? 0 : -1; });
    if (!D.data) return;
    const upcoming = (phase, text) => $("dtBody").replaceChildren(
      h("p", {}, badge(`Upcoming · Phase ${phase}`, "info")), h("p", { text }));
    D.tab = tab;
    $("dtBody").setAttribute("aria-labelledby", `dtTab-${tab}`);
    ({
      details: tabDetails, criteria: tabCriteria, analysis: tabAnalysis, versions: tabVersions, links: tabLinks,
      tests: () => upcoming(4, "Executable tests will appear after requirement-to-test generation is available."),
      results: () => upcoming(4, "Results will appear after requirement-linked execution is available."),
      trace: () => upcoming(5, "Requirement-to-run and evidence relationships will appear with traceability."),
      audit: tabAudit,
    })[tab]();
  }
  async function tabAudit() {
    const body = $("dtBody");
    const current = D.data;
    const link = h("a", { href: "#history", onclick: () => $("detail").close(), text: "View workspace audit events" });
    body.replaceChildren(h("p", { role: "status", text: "Loading analysis and review history…" }));
    try {
      const result = await api(`/items/${encodeURIComponent(D.conn)}/${encodeURIComponent(D.key)}/analysis`);
      if (D.data !== current || D.tab !== "audit") return;
      body.replaceChildren(h("h3", { class: "rq-sub", text: "Analysis and review history" }),
        h("ul", { class: "rq-audit" }, result.history.map((entry) => h("li", {},
          h("time", { text: when(entry.analyzed_at) }), entry.event))), link);
    } catch (error) {
      if (D.data !== current || D.tab !== "audit") return;
      body.replaceChildren(h("p", { text: error.status === 404 ? "No analysis or review events yet." : error.message }), link);
    }
  }
  function criterionCard(c) {
    return h("article", { class: "rq-criterion" },
      h("header", {}, h("b", { text: c.id.split("#")[1] }), c.automatable ? null : badge("not automatable", "warn"), badge(c.extraction === "rules" ? "copied from source" : c.extraction, "info")),
      h("p", { text: c.text }),
      c.automatable ? null : h("p", { class: "small", text: c.not_automatable_reason }),
      h("blockquote", { class: "rq-quote", text: c.citation.quote }),
      h("p", { class: "rq-cite", text: `${c.citation.source} v${c.citation.version} · ${c.citation.locator}` }));
  }
  function tabDetails() {
    const d = D.data, f = d.fields;
    $("dtBody").replaceChildren(...kids(
      d.stale_reasons.length ? h("div", { class: "rq-issue" }, h("b", { text: "The analysis is out of date: " }), d.stale_reasons.join("; ")) : null,
      h("dl", { class: "rq-kv" }, h("dt", { text: "Type" }), h("dd", { text: f.type || d.kind }), h("dt", { text: "Status" }), h("dd", { text: f.status || "—" }),
        h("dt", { text: "Priority" }), h("dd", { text: f.priority || "—" }), h("dt", { text: "Labels" }), h("dd", { text: (f.labels || []).join(", ") || "—" }),
        h("dt", { text: "Parent" }), h("dd", { text: f.parent || "—" }), h("dt", { text: "Sources" }), h("dd", { text: d.sources.map((s) => `${s.id} v${s.version}`).join(", ") })),
      h("h3", { class: "rq-sub", text: "Description" }), h("div", { class: "rq-desc", text: f.description || f.title || "(empty)" }),
      ...criteriaContent(d)));
  }
  function tabCriteria() {
    $("dtBody").replaceChildren(...criteriaContent(D.data));
  }
  function criteriaContent(d) {
    return kids(
      d.fields.acceptance_criteria ? h("div", {}, h("h3", { class: "rq-sub", text: "Acceptance criteria field" }),
        h("div", { class: "rq-desc", text: d.fields.acceptance_criteria })) : null,
      h("h3", { class: "rq-sub", text: `Acceptance criteria found (${d.criteria.length})` }),
      d.criteria.length ? d.criteria.map(criterionCard) : h("p", { class: "small", text: "None found in this work item. Qpilot does not invent criteria: ask the owner to add them (an 'Acceptance Criteria' heading or AC1:, AC2: lines)." }));
  }
  async function tabAnalysis() {
    const body = $("dtBody");
    const caps = (S.caps || {}).capabilities || {};
    const run = (ai) => h("button", { class: ai ? "secondary" : "primary", type: "button", text: ai ? "Analyze with AI (if allowed)" : "Analyze (rules)", disabled: !caps.analyze_requirements,
      onclick: async () => {
        body.prepend(h("p", { class: "small", role: "status", text: "Analysing…" }));
        try { await api(`/items/${encodeURIComponent(D.conn)}/${encodeURIComponent(D.key)}/analyze`, { method: "POST", body: { ai: ai ? "auto" : "off" } }); await openDetail(D.conn, D.key, "analysis"); }
        catch (e) { banner(e.message); }
      } });
    const selected = D.data;
    const active = () => D.data === selected && D.tab === "analysis";
    body.textContent = "Loading analysis…";
    let view = null;
    try { view = await api(`/items/${encodeURIComponent(D.conn)}/${encodeURIComponent(D.key)}/analysis`); }
    catch (e) { if (e.status !== 404) { if (active()) body.replaceChildren(h("p", { text: e.message })); return; } }
    if (!active()) return;
    if (!view) { body.replaceChildren(...kids(h("p", { class: "small", text: "Not analysed yet." }), h("div", { class: "rq-row" }, run(false), run(true)))); return; }
    const a = view.analysis;
    const byKind = (k) => a.issues.filter((i) => i.kind === k);
    const issueBlock = (title, items, kind = "") => h("section", {}, h("h3", { class: "rq-sub", text: `${title} (${items.length})` }),
      items.length ? items.map((i) => h("div", { class: `rq-issue ${kind}` }, h("b", { text: (i.criterion_ids || []).map((x) => x.split("#")[1]).join(", ") || a.requirement.id }), " ", i.detail || i.summary,
        ...(i.citations || []).map((c) => h("blockquote", { class: "rq-quote", text: `${c.source.source_id} v${c.source.version} (${c.locator}): ${c.quote}` }))))
        : h("p", { class: "small", text: "None found." }));
    body.replaceChildren(...kids(
      h("div", { class: "rq-row" }, run(false), run(true), badge(`AI: ${a.ai}`, a.ai === "used" ? "info" : ""), h("span", { class: "small", text: a.ai_note })),
      view.stale_reasons.length ? h("div", { class: "rq-issue" }, h("b", { text: "Out of date: " }), view.stale_reasons.join("; ")) : null,
      h("p", { class: "small", text: `Analysed ${when(a.analyzed_at)} by ${a.actor} at ${Object.entries(a.source_versions).map(([k, v]) => `${k.split(":").pop()} v${v}`).join(", ")}.` }),
      h("h3", { class: "rq-sub", text: `Extracted acceptance criteria (${a.requirement.criteria.length})` }),
      a.requirement.criteria.map((c) => h("div", { class: "rq-criterion" }, h("header", {}, h("b", { text: c.id.split("#")[1] }), badge((a.coverage[c.id] || "").replace("_", " "), { covered: "ok", uncovered: "warn", ambiguous: "warn", blocked: "bad", pending_review: "info" }[a.coverage[c.id]] || "")),
        h("p", { text: c.text }), h("p", { class: "small", text: a.coverage_reason[c.id] || "" }))),
      issueBlock("Missing requirements", byKind("missing_criteria")), issueBlock("Ambiguous", byKind("ambiguous")),
      issueBlock("Incomplete", byKind("incomplete")), issueBlock("Duplicates", byKind("duplicate")),
      issueBlock("Contradictions", byKind("contradictory"), "conflict"), issueBlock("Conflicts between Jira and Confluence", a.conflicts, "conflict"),
      h("h3", { class: "rq-sub", text: `Test ideas (${a.suggestions.length})` }),
      a.suggestions.length ? a.suggestions.map(suggestionLine) : h("p", { class: "small", text: "No ideas: criteria that are vague, disputed or not automatable get none until they are clarified." }),
      h("p", { class: "small" }, "Decide ideas in the ", h("a", { href: "#reviews", onclick: () => $("detail").close(), text: "Review center" }), ". Turning approved ideas into runnable tests comes with Phase 4."),
      h("h3", { class: "rq-sub", text: "History" }), h("ul", { class: "rq-audit" }, view.history.map((x) => h("li", {}, h("time", { text: when(x.analyzed_at) }), x.event)))));
  }
  const suggestionLine = (s) => h("div", { class: "rq-criterion" },
    h("header", {}, h("b", { text: s.title }), badge(s.kind, "info"), badge(s.basis === "explicit" ? "quoted outcome" : "inferred", s.basis === "explicit" ? "ok" : "warn"),
      badge(s.origin === "ai" ? "AI idea" : "rule idea"), badge(s.review.replace("_", " "), s.review === "accepted" ? "ok" : s.review === "rejected" ? "bad" : "")),
    s.expected_outcome ? h("p", { class: "small", text: `Expected: ${s.expected_outcome}` }) : null,
    s.note ? h("p", { class: "small", text: s.note }) : null);
  async function tabVersions() {
    const body = $("dtBody");
    try {
      const r = await api(`/items/${encodeURIComponent(D.conn)}/${encodeURIComponent(D.key)}/versions`);
      body.replaceChildren(...kids(h("div", { class: "rq-table-wrap" }, h("table", { class: "rq-table" }, h("caption", { class: "rq-sr", text: "Versions" }),
        h("thead", {}, h("tr", {}, ["Version", "Changed in Atlassian", "Read by Qpilot", "Title", "Content"].map((t) => h("th", { scope: "col", text: t })))),
        h("tbody", {}, r.versions.slice().reverse().map((v) => h("tr", {}, h("td", { text: `v${v.version}` }), h("td", { text: when(v.updated) }),
          h("td", { text: when(v.retrieved_at) }), h("td", { text: v.title }), h("td", {}, h("details", {}, h("summary", { text: "show" }),
            h("div", { class: "rq-desc", text: v.fields.description || (v.fields.sections || []).map((s) => (s.path || []).join(" > ")).join("\n") || "" }))))))))));
    } catch (e) { body.replaceChildren(...kids(h("p", { text: e.message }))); }
  }
  function tabLinks() {
    const d = D.data;
    $("dtBody").replaceChildren(...kids(d.links.length ? h("ul", { class: "rq-list" }, d.links.map((l) => h("li", {},
      l.imported ? h("button", { class: "rq-open", type: "button", text: `${l.key} ${l.title}`, onclick: () => openDetail(l.connection_id, l.key) }) : h("span", { text: l.key }),
      " ", badge(l.relation.replace("_", " "), "info"), " ", h("span", { class: "small", text: l.found_via }),
      l.imported ? (l.present ? null : badge("missing", "bad")) : badge("not imported", "warn"))))
      : h("p", { class: "small", text: "No linked Confluence pages or work items. Import with “Linked Confluence pages” to read the pages a story links to." })));
  }

  // ---------------------------------------------------------------- 6 review center
  $("rvStatus").addEventListener("change", () => reviews());
  let rvTimer; $("rvQ").addEventListener("input", () => { clearTimeout(rvTimer); rvTimer = setTimeout(reviews, 250); });
  async function reviews() {
    const box = $("rvList");
    box.setAttribute("aria-busy", "true");
    try {
      const r = await api(`/reviews?${new URLSearchParams({ status: $("rvStatus").value, q: $("rvQ").value })}`);
      $("rvWho").textContent = r.can_review ? `You review as “${r.reviewer}”. Each decision is recorded with your name.` : "You can read the ideas, but decisions need a named, signed-in reviewer.";
      if ($("rvStatus").value === "needs_review") navCount(r.total);
      box.replaceChildren(...kids(...(r.reviews.length ? r.reviews.map((x) => reviewCard(x, r.can_review)) : [h("p", { class: "rq-empty", text: $("rvStatus").value === "needs_review" ? "Nothing waiting for review." : "Nothing here." })])));
    } catch (e) { box.replaceChildren(...kids(h("p", { class: "small", text: e.message }))); }
    finally { box.removeAttribute("aria-busy"); }
  }
  function reviewCard(x, canReview) {
    const s = x.suggestion;
    const status = h("p", { class: "small", role: "status", "aria-live": "polite" });
    const decide = async (answer, edit) => {
      status.textContent = "Saving…";
      try {
        await api(`/items/${encodeURIComponent(x.connection_id)}/${encodeURIComponent(x.key)}/suggestions/${encodeURIComponent(s.id)}/review`, { method: "POST", body: edit ? { answer, edit } : { answer } });
        reviews();
      } catch (e) { status.textContent = e.message; }
    };
    const editForm = h("form", { hidden: true, onsubmit: (e) => { e.preventDefault();
      decide("yes", { title: e.target.title.value, steps: e.target.steps.value.split("\n").map((l) => l.trim()).filter(Boolean), expected_outcome: e.target.expected.value }); } },
      h("label", {}, "Title", h("input", { name: "title", value: s.title, required: true, minlength: 3 })),
      h("label", {}, "Steps (one per line)", h("textarea", { name: "steps", rows: 3, text: (s.steps || []).join("\n") })),
      h("label", {}, "Expected outcome", h("input", { name: "expected", value: s.expected_outcome || "" })),
      h("p", { class: "small", text: "An expected outcome that is no longer word for word in the requirement is marked “inferred”." }),
      h("div", { class: "rq-row" }, h("button", { class: "primary", type: "submit", text: "Accept with changes" })));
    const pending = s.review === "needs_review";
    return h("article", { class: "rq-review", "aria-label": s.title },
      h("h3", { text: s.title }),
      h("div", { class: "rq-row" }, h("button", { class: "rq-open", type: "button", text: `${x.key} — ${x.requirement_title}`, onclick: () => openDetail(x.connection_id, x.key, "analysis") }),
        badge(s.kind, "info"), badge(s.basis === "explicit" ? "quoted outcome" : "inferred", s.basis === "explicit" ? "ok" : "warn"),
        badge(s.origin === "ai" ? "AI idea" : "rule idea"), s.destructive ? badge(`changes data: ${s.destructive}`, "bad") : null, x.stale ? badge("requirement changed", "warn") : null),
      s.steps && s.steps.length ? h("ol", { class: "rq-list" }, s.steps.map((t) => h("li", { text: t }))) : null,
      s.expected_outcome ? h("p", { class: "small", text: `Expected: ${s.expected_outcome}` }) : h("p", { class: "small", text: "The requirement gives no expected result for this idea." }),
      s.note ? h("p", { class: "small", text: s.note }) : null,
      h("details", {}, h("summary", { text: `Requirement evidence (${x.criteria.length})` }), x.criteria.map(criterionCard)),
      pending ? null : h("p", { class: "small" }, `${s.review === "accepted" ? "Accepted" : "Rejected"} by ${s.reviewer || x.decided_by}${x.decided_at ? " on " + when(x.decided_at * 1000) : ""}.`,
        s.edited_by ? ` Corrected by ${s.edited_by}; originally “${s.original.title}”.` : ""),
      pending && canReview ? h("div", { class: "rq-row" },
        h("button", { class: "primary", type: "button", text: "Accept", onclick: () => decide("yes") }),
        h("button", { class: "secondary", type: "button", text: "Edit", "aria-expanded": "false", onclick: (e) => { editForm.hidden = !editForm.hidden; e.target.setAttribute("aria-expanded", String(!editForm.hidden)); } }),
        h("button", { class: "secondary", type: "button", text: "Reject", onclick: () => decide("no") })) : null,
      editForm, status);
  }

  // ---------------------------------------------------------------- 7 confluence
  async function confluenceView() {
    const left = $("cfSpaces");
    left.replaceChildren(...kids(h("p", { class: "small", text: "Loading pages…" })));
    try {
      const query = new URLSearchParams({ kind: "confluence_page", size: 100, missing: true,
        sort: "summary", q: $("cfSearch").value });
      const r = await api(`/items?${query}`);
      if (!r.items.length && query.get("q").trim()) {
        left.textContent = "No pages match your search.";
        return;
      }
      if (!r.items.length) { left.replaceChildren(...kids(h("p", { class: "small" }, "No Confluence pages imported yet. Connect Confluence in ", h("a", { href: "#integrations", text: "Integrations" }), ", then import a space or the pages your stories link to."))); return; }
      const spaces = new Map();
      for (const page of r.items) {
        const space = page.space || "(no space)";
        if (!spaces.has(space)) spaces.set(space, []);
        spaces.get(space).push(page);
      }
      left.replaceChildren(...[...spaces].map(([space, pages]) => h("section", {},
        h("h3", { class: "rq-sub", text: `${space} (${pages.length})` }),
        confluenceTree(pages, left))));
    } catch (e) { left.replaceChildren(...kids(h("p", { class: "small", text: e.message }))); }
  }
  function confluenceTree(pages, panel) {
    const byKey = new Map(pages.map((page) => [`${page.connection_id}/${page.key}`, page]));
    const children = new Map();
    const roots = [];
    for (const page of pages) {
      const parent = byKey.get(`${page.connection_id}/${page.parent_id}`);
      if (!parent || parent === page) { roots.push(page); continue; }
      if (!children.has(parent)) children.set(parent, []);
      children.get(parent).push(page);
    }
    const visited = new Set();
    const branch = (page) => {
      if (visited.has(page)) return null;
      visited.add(page);
      const button = h("button", { type: "button", onclick: (event) => {
        panel.querySelector("[aria-current=true]")?.removeAttribute("aria-current");
        event.currentTarget.setAttribute("aria-current", "true");
        showPage(page);
      } }, page.summary, " ", page.present ? null : badge("missing", "bad"));
      const nested = (children.get(page) || []).map(branch).filter(Boolean);
      return h("li", {}, button, nested.length ? h("ul", { class: "rq-pages rq-nested-pages" }, nested) : null);
    };
    return h("ul", { class: "rq-pages" }, roots.map(branch), pages.map(branch));
  }
  async function showPage(p) {
    const box = $("cfPage");
    box.replaceChildren(...kids(h("p", { class: "small", text: "Loading…" })));
    try {
      const d = await api(`/items/${encodeURIComponent(p.connection_id)}/${encodeURIComponent(p.key)}`);
      const sections = d.fields.sections || [];
      const headings = sections.map((section) => (section.path || []).join(" › ") || "Top of page");
      const stories = d.links.filter((l) => l.kind === "jira_issue");
      box.replaceChildren(...kids(h("h2", { text: d.title }),
        h("p", { class: "small" }, `Confluence version ${d.fields.confluence_version} · read ${when(d.retrieved_at)} · `, h("a", { href: d.url, target: "_blank", rel: "noopener noreferrer", text: "Open in Confluence" })),
        h("h3", { class: "rq-sub", text: `Related Jira stories (${stories.length})` }),
        stories.length ? h("ul", { class: "rq-list" }, stories.map((l) => h("li", {}, l.imported ? h("button", { class: "rq-open", type: "button", text: `${l.key} ${l.title}`, onclick: () => openDetail(l.connection_id, l.key) }) : l.key, " ", badge(l.relation, "info")))) : h("p", { class: "small", text: "None found." }),
        h("h3", { class: "rq-sub", text: `Criteria taken from this page (${d.criteria.length})` }), d.criteria.map(criterionCard),
        h("h3", { class: "rq-sub", text: `Headings (${sections.length})` }),
        sections.length > 1 ? h("ul", { class: "rq-pages", "aria-label": "Page sections" },
          headings.map((heading, index) => h("li", {}, h("button", { type: "button", text: heading, onclick: () => {
            const section = $(`cfSection-${index}`);
            section.focus({ preventScroll: true });
            section.scrollIntoView({ block: "start" });
          } })))) : null,
        sections.map((s, index) => h("div", { id: `cfSection-${index}`, tabindex: -1, class: `rq-section${s.requirement_like ? " req" : ""}` },
          h("h4", {}, headings[index], " ", s.requirement_like ? badge("requirement section", "info") : null),
          h("ul", { class: "rq-list" }, (s.blocks || []).slice(0, 12).map((b) => h("li", { text: b.text }))))),
        h("p", { class: "small" }, h("button", { class: "secondary", type: "button", text: "Versions and analysis", onclick: () => openDetail(p.connection_id, p.key, "versions") }))));
    } catch (e) { box.replaceChildren(...kids(h("p", { text: e.message }))); }
  }

  for (const [id, render] of [["analysisSearchForm", analysisView], ["cfSearchForm", confluenceView]]) {
    $(id).addEventListener("submit", (event) => { event.preventDefault(); render(); });
  }
  async function analysisView() {
    const panel = $("analysisItems");
    const query = new URLSearchParams({ kind: "jira_issue", q: $("analysisSearch").value, size: 25 });
    panel.textContent = "Loading requirements…";
    try {
      const result = await api(`/items?${query}`);
      panel.replaceChildren(result.items.length ? h("div", { class: "lab-card" },
        h("p", { class: "small", text: `Showing ${result.items.length} of ${result.total} requirements.` }),
        h("ul", { class: "rq-list" }, result.items.map((item) => h("li", {},
          h("button", { type: "button", class: "rq-open", text: `${item.key} — ${item.summary}`,
            onclick: () => openDetail(item.connection_id, item.key, "analysis") })))))
        : h("p", {}, "No matching requirements. ", h("a", { href: "#import", text: "Import from Jira" }), "."));
    } catch (error) { panel.textContent = error.message; }
  }
  async function coverageView() {
    const panel = $("rqCoverage");
    panel.textContent = "Loading coverage…";
    const label = (status) => status.replaceAll("_", " ");
    const counts = (values) => Object.entries(values).map(([status, count]) => `${count} ${label(status)}`).join(" · ");
    try {
      const result = await api("/coverage");
      panel.replaceChildren(...kids(
        h("p", { class: "small", text: result.basis }),
        result.requirements.length ? h("div", {},
          h("p", { text: counts(result.totals) }),
          h("div", { class: "rq-table-wrap" }, h("table", { class: "rq-table" },
            h("caption", { class: "rq-sr", text: "Approved coverage by requirement" }),
            h("thead", {}, h("tr", {}, ["Requirement", "Criteria", "Coverage", "Analysis"].map((text) => h("th", { scope: "col", text })))),
            h("tbody", {}, result.requirements.map((row) => h("tr", {},
              h("th", { scope: "row", text: row.title }), h("td", { text: row.criteria }),
              h("td", { text: counts(row.coverage) || "—" }),
              h("td", {}, row.stale ? badge("Out of date", "warn") : badge("Current", "ok"))))))))
          : h("p", { text: "No analysed requirements yet." })));
    } catch (error) { panel.textContent = error.message; }
  }
  function settingsView() {
    const caps = S.caps;
    const values = {
      "Signed-in user": caps.actor,
      "Workspace": caps.tenant,
      "Review permission": caps.can_review ? "Can sign review decisions" : "Can view review decisions",
      "Atlassian access": caps.read_only_atlassian ? "Read-only" : "Check server configuration",
    };
    $("rqSettings").replaceChildren(...Object.entries(values).flatMap(([name, text]) => [h("dt", { text: name }), h("dd", { text })]));
  }

  // ---------------------------------------------------------------- sync history + audit
  async function history() {
    const tbody = $("hsTable").tBodies[0];
    try {
      const r = await api("/imports?limit=100");
      const rows = [...r.running.map((j) => ({ finished_at: "", connection_id: j.connection_id, mode: j.mode, status: "running", actor: j.actor, result: j.progress || {} })), ...r.runs];
      tbody.replaceChildren(...kids(...rows.map((x) => h("tr", {}, h("td", { text: when(x.finished_at) }), h("td", { text: x.connection_id }), h("td", { text: x.mode }),
        h("td", {}, statusBadge(x.status)), h("td", { text: x.result.new ?? 0 }), h("td", { text: (x.result.changed ?? 0) + (x.result.reappeared ?? 0) }),
        h("td", { text: x.result.unchanged ?? 0 }), h("td", { text: (x.result.missing || []).length + (x.result.inaccessible || []).length }),
        h("td", { text: Array.isArray(x.result.failed_items) ? x.result.failed_items.length : x.result.failed_items || 0 }),
        h("td", { text: x.result.duration_s !== undefined ? `${x.result.duration_s} s` : "—" }), h("td", { text: x.actor }),
        h("td", { text: x.scope || "—" })))));
      if (!rows.length) tbody.append(...kids(h("tr", {}, h("td", { colspan: 12, class: "rq-empty", text: "No imports yet." }))));
    } catch (e) { tbody.replaceChildren(...kids(h("tr", {}, h("td", { colspan: 12, class: "rq-empty", text: e.message })))); }
    try {
      const a = await api("/audit?limit=100");
      $("auditList").replaceChildren(...kids(...(a.events.length ? a.events.map((e) => h("li", {}, h("time", { text: when(e.created_at ? e.created_at * 1000 : e.at) }),
        h("b", { text: e.action.replace("requirements.", "") }), e.allowed ? null : badge("refused", "bad"), h("span", { class: "small", text: `${e.actor}` })))
        : [h("li", { class: "small", text: "No events yet." })])));
    } catch (e) { $("auditList").replaceChildren(...kids(h("li", { class: "small", text: e.status === 403 ? "The audit trail is for administrators." : e.message }))); }
  }

  // ---------------------------------------------------------------- start
  async function start() {
    try {
      S.caps = await api("/capabilities");
      $("who").textContent = `Signed in as ${S.caps.actor}${S.caps.tenant !== "local" ? " · " + S.caps.tenant : ""}`;
    } catch (e) { if (e.status !== 401) banner(e.message); return; }
    route();
  }
  start();
})();
