"use strict";
/* Requirements workspace (Jira Cloud + Confluence Cloud). Talks only to /api/requirements/* of this Studio.
   Every value from Jira, Confluence or the server is put on the page with textContent (never as HTML).
   An Atlassian API token is typed into a password box, sent once (PUT .../token) and never kept or shown again.
   A Studio access token (only when Studio login is on) lives in this tab's memory only. */
(() => {
  const $ = (id) => document.getElementById(id);
  // A browser that kept an OLDER copy of this page would run this script against screens that are not there and show
  // a blank page: say so instead (a hard reload fetches the current page).
  if (!$("view-writeback") || !$("view-builder") || !$("exForm2")) {
    const main = document.querySelector("main") || document.body;
    const note = document.createElement("div");
    note.className = "lab-card";
    note.setAttribute("role", "alert");
    note.textContent = "This page is an older copy kept by your browser. Reload it fully: Cmd+Shift+R (Mac) or " +
      "Ctrl+Shift+R (Windows). If it stays like this, restart the Studio after git pull.";
    main.prepend(note);
    return;
  }
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
    const url = path.startsWith("/api/") ? path : `/api/requirements${path}`;  // (/api/runs/...: the run's own live data)
    try { res = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) }); }
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
  const VIEWS = [...document.querySelectorAll(".rq-view")].map((s) => s.id.replace("view-", ""));
  // (older bookmarks keep working: the pages they named now live inside these)
  const ALIAS = { coverage: "reports", evidence: "reports" };
  // Only the newest load of a view may draw it: when a view is loaded again (a filter changed, a site was just
  // connected) while an older request is still answering, the older answer arriving LAST used to overwrite the newer
  // one (a filtered list showing every row again, a just-connected site shown without its token). Responses arrive
  // out of order whenever the server is busy.
  const SEQ = {};
  function newest(key) { const n = (SEQ[key] = (SEQ[key] || 0) + 1); return () => SEQ[key] === n; }
  function route() {
    if (!S.caps) return;
    const asked = location.hash.slice(1);
    if (ALIAS[asked]) { history.replaceState(null, "", `#${ALIAS[asked]}`); }
    const want = ALIAS[asked] || asked;
    const view = VIEWS.includes(want) ? want : "overview";
    for (const v of VIEWS) $(`view-${v}`).hidden = v !== view;
    for (const link of navigation) {
      if (link.dataset.view === view) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    const title = $(`view-${view}`).dataset.title;
    document.title = `Qpilot | Jira · ${title}`;
    $("crumb").textContent = title;
    banner("");
    S.view = view;
    clearTimeout(X.poll); clearTimeout(LV.timer);
    ({ overview, integrations, import: wizardOpen, explorer, analysis: analysisView, reviews,
      confluence: confluenceView, reports: reportsView, history, audit: auditView, settings: settingsView, builder,
      execution: executionCenter, agents: liveView, traceability: traceabilityView,
      writeback: writebackView })[view]?.();
    workflowChrome(view);
  }
  // the Jira group in the sidebar opens and closes; the choice is kept on this computer
  (() => {
    const group = document.querySelector(".rq-navgroup"), btn = $("navToggle");
    let closed = false;
    try { closed = localStorage.getItem("qpilot.jiraNav") === "closed"; } catch (e) { /* (private mode) */ }
    const set = (c) => { group.classList.toggle("collapsed", c); btn.setAttribute("aria-expanded", String(!c));
      try { localStorage.setItem("qpilot.jiraNav", c ? "closed" : "open"); } catch (e) { /* (private mode) */ } };
    set(closed);
    btn.addEventListener("click", () => set(btn.getAttribute("aria-expanded") === "true"));
  })();
  window.addEventListener("hashchange", () => { route(); $("rqMain").focus(); });
  document.querySelector(".rq-skip").addEventListener("click", (event) => {
    event.preventDefault();
    $("rqMain").focus();
  });

  // ---------------------------------------------------------------- 1 overview
  async function overview() {
    const stats = $("stats");
    stats.setAttribute("aria-busy", "true");
    const fresh = newest("overview");
    try {
      const o = await api("/overview");
      if (!fresh()) return;
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
      caps.generate_test_cases ? go("Generate test cases", "from accepted ideas", "#builder") : later("generate_test_cases", "Generate test cases"),
      caps.run_selected_tests ? go("Run tests", "selected, impacted or all approved", "#execution") : later("run_selected_tests", "Run selected tests"),
      caps.traceability ? go("View traceability", "story → test → real result", "#traceability") : later("traceability", "Traceability"),
      caps.defects ? go("Defects and write-back", caps.jira_write_back ? "approve and send Jira updates" : "defects; Jira writes are off", "#writeback") : later("jira_write_back", "Jira write-back")));
  }
  const OUTCOME_KIND = { completed: "ok", running: "info", cancelled: "warn", interrupted: "warn", completed_with_unautomated: "warn",
    completed_with_blocked: "warn", completed_with_review: "info", completed_with_failures: "bad", no_tests_automated: "bad", automation_failed: "bad" };
  const outcomeBadge = (ex) => badge(ex.outcome_text || ex.status, OUTCOME_KIND[ex.outcome] || "");
  const tallyText = (ex) => { const t = ex.tally; if (!t) return "";
    return `executed ${t.executed} of ${t.selected} · passed ${t.passed} · failed ${t.failed}${t.requires_review ? ` · needs review ${t.requires_review}` : ""} · blocked ${t.blocked} · not automated ${t.not_automated}${t.not_run ? ` · not run ${t.not_run}` : ""}`; };
  const statusBadge = (s) => badge(s || "—", { complete: "ok", partial: "warn", failed: "bad", cancelled: "warn", running: "info" }[s] || "");
  function navCount(n) { const c = $("navReviews"); c.hidden = !n; c.textContent = n || ""; c.setAttribute("aria-label", `${n} waiting`); }

  // ---------------------------------------------------------------- 2 integrations
  async function integrations() {
    const box = $("connCards");
    const fresh = newest("integrations");
    box.replaceChildren(...kids(h("p", { class: "small", text: "Loading connections…" })));
    try {
      const data = await api("/connections");
      if (!fresh()) return;  // (a newer load draws the cards)
      S.conns = data.connections;
      const legacy = $("legacyWarning");
      legacy.hidden = !data.defect_creation_writes_to_jira;
      legacy.textContent = data.defect_creation_writes_to_jira
        ? `Note: the older defect creation is switched on in .env (JIRA_PROJECT=${data.defect_creation_project}). Test runs will create Bug issues there. The requirements connections below never write.` : "";
      const byProduct = (p) => S.conns.filter((c) => c.product === p);
      const freeId = (p) => { const base = p === "jira" ? "jira" : "conf"; const used = new Set(S.conns.map((c) => c.id));
        for (let n = 2; ; n += 1) if (!used.has(`${base}-${n}`)) return `${base}-${n}`; };
      const cards = [];
      for (const p of ["jira", "confluence"]) {
        const mine = byProduct(p);
        if (!mine.length) { cards.push(connCard(p, null)); continue; }
        mine.forEach((c, n) => cards.push(connCard(p, c, n)));
        // another site of the same product: its own card, its own token (never the first site's)
        cards.push(h("details", { class: "lab-card rq-conn rq-conn-add" },
          h("summary", { text: p === "jira" ? "+ Connect another Jira site" : "+ Connect another Confluence site" }),
          connCard(p, null, mine.length, freeId(p))));
      }
      box.replaceChildren(...kids(...cards));
    } catch (e) { if (fresh()) box.replaceChildren(...kids(h("p", { class: "small", text: e.message }))); }
  }
  function connCard(product, conn, n = 0, newId = "") {
    const name = newId ? (product === "jira" ? "Another Jira Cloud site" : "Another Confluence Cloud site")
      : (product === "jira" ? "Jira Cloud" : "Confluence Cloud") + (conn && !conn.id.endsWith("-main") ? ` (${conn.id})` : "");
    const id = conn ? conn.id : (newId || (product === "jira" ? "jira-main" : "conf-main"));
    // (field ids follow the connection, never the card's position: the main one keeps jiraSite, jiraEmail ...)
    const sfx = id === (product === "jira" ? "jira-main" : "conf-main") ? "" : `-${id}`;
    const status = h("p", { class: "small", role: "status", "aria-live": "polite" });
    const site = h("input", { id: `${product}Site${sfx}`, type: "url", required: true, placeholder: "https://your-site.atlassian.net", value: conn ? conn.site_url : "" });
    const email = h("input", { id: `${product}Email${sfx}`, type: "email", required: true, autocomplete: "off", value: conn ? conn.email : "" });
    const types = h("input", { id: `${product}Types${sfx}`, value: conn ? conn.work_item_types.join(", ") : "Story" });
    const cred = conn ? conn.credential : { configured: false };
    const credText = cred.configured ? (cred.source === "environment" ? "token from .env" : "token saved") : "no token";
    const tokenInput = h("input", { id: `${product}Token${sfx}`, type: "password", autocomplete: "new-password", placeholder: cred.configured ? "paste a new token to replace it" : "paste the API token" });

    const save = h("form", { onsubmit: async (e) => {
      e.preventDefault();
      const host = (u) => { try { return new URL(u).hostname.toLowerCase(); } catch (err) { return u; } };
      const moved = conn && (host(conn.site_url) !== host(site.value.trim()) || conn.email.trim().toLowerCase() !== email.value.trim().toLowerCase());
      if (moved && !tokenInput.value.trim() && !confirm(`Change ${conn.id} to ${site.value.trim()}? The token saved for ${host(conn.site_url)} will not be sent to the new site: paste the API token for the new site (now, or afterwards). To keep both sites, use “Connect another Jira site” instead.`)) return;
      status.textContent = "Saving…";
      try {
        const saved = await api("/connections", { method: "POST", body: { id, product, site_url: site.value.trim(), email: email.value.trim(),
          work_item_types: product === "jira" ? list(types.value) : ["Story"] } });
        const token = tokenInput.value.trim();
        tokenInput.value = "";  // (the token leaves the page now; it is never kept)
        if (token) await api(`/connections/${encodeURIComponent(id)}/token`, { method: "PUT", body: { token } });
        status.textContent = token ? "Saved. Use “Test connection” to check it." : saved.notice || "Saved. Use “Test connection” to check it.";
        await integrations();
        const card = [...document.querySelectorAll(".rq-conn")].find((c) => c.dataset.conn === id);
        const out = card && card.querySelector("[role=status]");
        if (out) out.textContent = token ? "Saved with its token. Use “Test connection” to check it." : (saved.notice || "Saved. Paste the API token for this site, then use “Test connection”.");
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
          status.textContent = product === "jira" ? `Connected as ${r.account}. ${plural(r.projects, "project")} visible. Read-only. ` : `Connected. ${plural(r.spaces, "space")} visible. Read-only.`;
          if (product === "jira") { status.append(h("a", { class: "primary rq-action-link", href: "#import", text: "Continue to Import" })); refreshWorkflow(); }
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

    return h("section", { class: "lab-card rq-conn", "aria-label": name, "data-conn": id },
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
    const fresh = newest("preview");
    $("pvSummary").textContent = "Asking Jira…";
    const tbody = $("pvTable").tBodies[0];
    if (!more) {
      tbody.replaceChildren();
      W.selected = new Set();
      W.keys = [];
      pvCounts = { new: 0, updated: 0, unchanged: 0, reappeared: 0, unreadable: 0 };
    }
    const r = await api(`/connections/${encodeURIComponent($("wConn").value)}/preview`, { method: "POST", body });
    if (!fresh()) return;  // (a newer preview replaced this one: its rows would be counted twice)
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
    // the guided workflow: what was just imported becomes this test's selection, and the explorer opens
    const got = W.lastImport.body.mode === "space" ? [] : [...new Set([...(r.new_keys || []), ...(r.changed_keys || []), ...(r.unchanged_keys || []),
      ...(W.lastImport.body.mode === "items" ? list(W.lastImport.body.keys || "").map((k) => k.toUpperCase()).filter((k) => /^[A-Z][A-Z0-9_]*-\d+$/.test(k)) : [])])];
    if (ok && got.length && S.view === "import") {
      saveDraft({ connection_id: W.lastImport.conn, requirement_ids: got, step: "explorer" }).then(() => {
        banner(`Imported: ${got.join(", ")} selected for this test. Analyse them next.`, true);
        location.hash = "#explorer";
      }).catch((e) => banner(e.message));
    }
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
    const fresh = newest("explorer");
    if (!WF.draft) await refreshWorkflow();
    if (!fresh()) return;
    const tbody = $("exTable").tBodies[0];
    $("exTable").setAttribute("aria-busy", "true");
    const q = new URLSearchParams({ kind: "jira_issue", q: $("exQ").value, type: $("exType").value, status: $("exStatus").value,
      analysis: $("exAnalysis").value, missing: $("exMissing").checked, sort: S.ex.sort, page: S.ex.page, size: S.ex.size });
    try {
      const r = await api(`/items?${q}`);
      if (!fresh()) return;  // (the filters changed meanwhile: the newer load draws the table)
      if (S.ex.page === 1 && !$("exQ").value && !$("exType").value) fillFacets();
      document.querySelectorAll("#exTable th button").forEach((b) => {
        const k = b.dataset.sort;
        const s = S.ex.sort === k ? "ascending" : S.ex.sort === `-${k}` ? "descending" : null;
        if (s) b.parentElement.setAttribute("aria-sort", s); else b.parentElement.removeAttribute("aria-sort");
      });
      const sel = new Set(draftReqs());
      tbody.replaceChildren(...kids(...r.items.map((it) => h("tr", { class: it.present ? "" : "missing" },
        h("td", {}, h("input", { type: "checkbox", "data-key": it.key, "aria-label": `Select ${it.key}`, checked: sel.has(it.key),
          onchange: async (e) => { const s = new Set(draftReqs()); if (e.target.checked) s.add(it.key); else s.delete(it.key); await saveDraft({ requirement_ids: [...s] }); selInfo(); } })),
        h("td", {}, h("button", { class: "rq-open", type: "button", text: it.key, "aria-label": `Open ${it.key}`, onclick: () => openDetail(it.connection_id, it.key) })),
        h("td", { text: it.summary }), h("td", { text: it.type }), h("td", { text: it.priority }), h("td", { text: it.status }),
        h("td", { text: it.criteria }), h("td", { text: it.linked_pages }),
        h("td", {}, { not_analyzed: badge("not analysed"), current: badge("analysed", "ok"), stale: badge("out of date", "warn") }[it.analysis],
          it.present ? null : badge("missing", "bad")),
        h("td", { text: it.pending_reviews ? `${it.pending_reviews} pending` : it.review_status || "—" }),
        h("td", { text: it.covered === null || !it.criteria ? "—" : `${it.covered}/${it.criteria}` }),
        h("td", { text: `v${it.version}` }), h("td", { text: when(it.last_synced) })))));
      selInfo();
      if (!r.items.length) tbody.append(...kids(h("tr", {}, h("td", { colspan: 13, class: "rq-empty" },
        r.total === 0 && !$("exQ").value ? h("span", {}, "No requirements imported yet. ", h("a", { href: "#import", text: "Import from Jira" }), ".") : "Nothing matches these filters."))));
      const pages = Math.max(1, Math.ceil(r.total / r.size));
      $("exPager").replaceChildren(...kids(`${plural(r.total, "requirement")} · page ${r.page} of ${pages}`,
        h("button", { class: "secondary", type: "button", text: "Previous", disabled: r.page <= 1, onclick: () => { S.ex.page -= 1; explorer(); } }),
        h("button", { class: "secondary", type: "button", text: "Next", disabled: r.page >= pages, onclick: () => { S.ex.page += 1; explorer(); } })));
    } catch (e) { if (fresh()) tbody.replaceChildren(...kids(h("tr", {}, h("td", { colspan: 12, class: "rq-empty", text: e.message })))); }
    finally { if (fresh()) $("exTable").removeAttribute("aria-busy"); }
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
    D.tab = tab;
    $("dtBody").setAttribute("aria-labelledby", `dtTab-${tab}`);
    ({
      details: tabDetails, criteria: tabCriteria, analysis: tabAnalysis, versions: tabVersions, links: tabLinks,
      tests: tabTests, results: tabResults, trace: tabTrace,
      audit: tabAudit,
    })[tab]();
  }
  async function tabTests() {
    const body = $("dtBody");
    const req = D.data.requirement_id;
    try {
      const r = await api(`/test-cases?${new URLSearchParams({ requirement: req })}`);
      body.replaceChildren(...kids(
        h("div", { class: "rq-row" }, h("button", { class: "primary", type: "button", text: "Generate from accepted ideas", onclick: async () => {
          try { await api(`/items/${encodeURIComponent(D.conn)}/${encodeURIComponent(D.key)}/test-cases`, { method: "POST" }); tabTests(); }
          catch (err) { body.prepend(h("p", { class: "rq-issue", role: "alert", text: err.message })); }
        } }), h("a", { href: "#builder", onclick: () => $("detail").close(), text: "Open the Test Case Builder" })),
        r.test_cases.length ? h("ul", { class: "rq-audit" }, r.test_cases.map((c) => h("li", {}, h("b", { text: c.id }), caseBadge(c.status),
          h("span", { text: `${c.criterion_ids.map((x) => x.split("#")[1]).join(", ")} · ${c.title}` }), resultBadge((c.latest_result || {}).status))))
          : h("p", { class: "small", text: "No test cases yet. Accept test ideas in the Review Center, then generate them." })));
    } catch (e) { body.replaceChildren(h("p", { text: e.message })); }
  }
  async function tabResults() {
    const body = $("dtBody");
    try {
      const r = await api(`/test-cases?${new URLSearchParams({ requirement: D.data.requirement_id })}`);
      const rows = [];
      for (const c of r.test_cases) {
        const d = await api(`/test-cases/${encodeURIComponent(c.id)}`);
        d.results.forEach((x) => rows.push(h("li", {}, h("time", { text: when(x.at) }), h("b", { text: c.id }), resultBadge(x.status),
          h("span", { text: x.actual || x.reason || "" }), ...evidenceLinks(x))));
      }
      body.replaceChildren(...kids(rows.length ? h("ul", { class: "rq-audit" }, rows) : h("p", { class: "small", text: "No test case of this requirement has run yet." })));
    } catch (e) { body.replaceChildren(h("p", { text: e.message })); }
  }
  async function tabTrace() {
    const body = $("dtBody");
    try {
      const r = await api(`/traceability?${new URLSearchParams({ q: D.data.requirement_id })}`);
      const rows = r.rows.filter((x) => x.requirement === D.data.requirement_id);
      body.replaceChildren(...kids(rows.length ? h("ul", { class: "rq-audit" }, rows.map((x) => h("li", {},
        h("b", { text: x.criterion.split("#")[1] }), h("span", { text: x.criterion_text }), "→", h("span", { text: x.test_case || "no approved test" }),
        x.result ? resultBadge(x.result) : null, badge(x.coverage)))) : h("p", { class: "small", text: "Analyse this requirement first." })));
    } catch (e) { body.replaceChildren(h("p", { text: e.message })); }
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
      if (!WF.draft) await refreshWorkflow();
      const mine = new Set(draftReqs());
      const shown = mine.size && !S.rvAll ? r.reviews.filter((x) => mine.has(x.key)) : r.reviews;
      S.shownReviews = shown;
      $("rvScope").replaceChildren(...kids(mine.size ? (S.rvAll ? "All requirements' ideas. " : `Ideas of this test's requirements (${[...mine].join(", ")}). `) : "",
        mine.size ? h("button", { type: "button", class: "linklike", text: S.rvAll ? "Show only this test's" : "Show all", onclick: () => { S.rvAll = !S.rvAll; reviews(); } }) : null));
      $("rvAcceptAll").disabled = $("rvRejectAll").disabled = !r.can_review || !shown.some((x) => x.suggestion.review === "needs_review");
      box.replaceChildren(...kids(...(shown.length ? shown.map((x) => reviewCard(x, r.can_review)) : [h("p", { class: "rq-empty", text: $("rvStatus").value === "needs_review" ? (WF.state && WF.state.with_accepted ? "Nothing waiting for review. Next: Generate Test Cases." : "Nothing waiting for review.") : "Nothing here." })])));
    } catch (e) { box.replaceChildren(...kids(h("p", { class: "small", text: e.message }))); }
    finally { box.removeAttribute("aria-busy"); }
  }
  function nextActions(conn, key) {  // (after an acceptance: what to do next, one click each)
    const out = h("p", { class: "small" });
    $("rvNext").replaceChildren(h("div", { class: "lab-card rq-next" }, h("b", { text: `Accepted for ${key}. Next:` }),
      h("div", { class: "rq-row" },
        h("button", { class: "primary", type: "button", text: `Generate test cases for ${key}`, onclick: async () => {
          out.textContent = "Generating…";
          try {
            const r = await api(`/items/${encodeURIComponent(conn)}/${encodeURIComponent(key)}/test-cases`, { method: "POST" });
            out.textContent = `${plural(r.test_cases.length, "test case")} for ${key} (${r.created.length} new). Review and approve them in the Test Case Builder, then run them.`;
          } catch (err) { out.textContent = err.message; }
        } }),
        h("a", { href: "#builder", text: "Test Case Builder" }), h("a", { href: "#execution", text: "Configure and run" })), out));
  }
  function reviewCard(x, canReview) {
    const s = x.suggestion;
    const status = h("p", { class: "small", role: "status", "aria-live": "polite" });
    const decide = async (answer, edit) => {
      status.textContent = "Saving…";
      try {
        await api(`/items/${encodeURIComponent(x.connection_id)}/${encodeURIComponent(x.key)}/suggestions/${encodeURIComponent(s.id)}/review`, { method: "POST", body: edit ? { answer, edit } : { answer } });
        if (answer === "yes") nextActions(x.connection_id, x.key);
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
    if (!WF.draft) await refreshWorkflow();
    analysisFlow().catch((e) => { $("anFlow").replaceChildren(h("p", { class: "rq-issue", text: e.message })); });
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
    executedCoverage();
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

  // ---------------------------------------------------------------- Phase 4: test cases, executions, evidence, trace
  const X = { selected: new Set(), poll: null, current: "" };
  const resultBadge = (s) => s ? badge(s, { Passed: "ok", Failed: "bad", Blocked: "bad", Flaky: "warn", "Not automated": "warn", "Requires review": "info",
    Skipped: "warn", "Not run": "", Cancelled: "warn" }[s] || "") : badge("not run yet");
  const caseBadge = (s) => badge(s.replaceAll("_", " "), { approved: "ok", ready: "ok", stale: "warn", blocked: "bad",
    awaiting_approval: "info", requires_review: "info" }[s] || "");
  const runnable = (c) => ["approved", "ready"].includes(c.status);
  const evidenceLinks = (r) => (r.evidence || []).map((e) => h("a", { href: `/runs/${encodeURIComponent(r.run_folder || "")}/${e.split("/").map(encodeURIComponent).join("/")}`,
    target: "_blank", rel: "noopener", text: e.split("/").pop() }));

  async function builder() {
    await refreshWorkflow();
    if (draftCases().length) X.selected = new Set(draftCases());
    try {
      const reqs = await api("/items?kind=jira_issue&analysis=current&size=100");
      $("genReq").replaceChildren(...kids(reqs.items.length ? reqs.items.map((r) => h("option", { value: `${r.connection_id}|${r.key}`, text: `${r.key} — ${r.summary}` }))
        : [h("option", { value: "", text: "No analysed requirement yet" })]));
    } catch (e) { banner(e.message); }
    tcList();
  }
  $("genForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const [conn, key] = $("genReq").value.split("|");
    if (!key) return;
    $("genStatus").textContent = "Generating…";
    try {
      const r = await api(`/items/${encodeURIComponent(conn)}/${encodeURIComponent(key)}/test-cases`, { method: "POST" });
      $("genStatus").textContent = r.created.length + r.updated.length
        ? `${plural(r.created.length, "new test case")}, ${r.updated.length} updated, ${r.unchanged.length} unchanged${r.stale.length ? `, ${r.stale.length} now stale` : ""}.`
        : r.unchanged.length ? `Up to date: ${plural(r.unchanged.length, "test case")} unchanged.` : "No accepted test ideas for this requirement yet — accept some in the Review Center first.";
      tcList();
    } catch (err) { $("genStatus").textContent = err.message; }
  });
  ["tcQ", "tcStatus"].forEach((id) => $(id).addEventListener(id === "tcQ" ? "input" : "change", () => tcList()));
  $("tcForm").addEventListener("submit", (e) => e.preventDefault());
  const toExecution = async () => {  // (the selection is saved before the Execution Center reads it)
    if (!X.selected.size) return;
    clearTimeout(selTimer);
    await saveDraft({ test_case_ids: [...X.selected], step: "execution" });
    location.hash = "#execution";
  };
  $("tcRun").addEventListener("click", toExecution);
  $("tcContinue").addEventListener("click", toExecution);
  let selTimer;
  function selChanged() { tcCount(); clearTimeout(selTimer); selTimer = setTimeout(() => saveDraft({ test_case_ids: [...X.selected] }), 150); }
  async function tcList() {
    const tbody = $("tcTable").tBodies[0];
    try {
      const r = await api(`/test-cases?${new URLSearchParams({ q: $("tcQ").value, status: $("tcStatus").value })}`);
      S.cases = r.test_cases;
      tbody.replaceChildren(...kids(r.test_cases.map((c) => h("tr", { class: c.status === "stale" ? "missing" : "" },
        h("td", {}, h("input", { type: "checkbox", "aria-label": `Select ${c.id}`, checked: X.selected.has(c.id), disabled: !runnable(c),
          onchange: (e) => { e.target.checked ? X.selected.add(c.id) : X.selected.delete(c.id); selChanged(); } })),
        h("td", {}, h("button", { class: "rq-open", type: "button", text: c.id, "aria-label": `Open ${c.id}`, onclick: () => tcDetail(c.id) })),
        h("td", { text: c.requirement_id }), h("td", { text: c.criterion_ids.map((x) => x.split("#")[1]).join(", ") }),
        h("td", { text: c.title }), h("td", { text: c.kind }), h("td", {}, caseBadge(c.status)),
        h("td", {}, resultBadge((c.latest_result || {}).status))))));
      if (!r.test_cases.length) tbody.append(...kids(h("tr", {}, h("td", { colspan: 8, class: "rq-empty", text: "No test cases yet. Accept test ideas in the Review Center, then generate them here." }))));
      tcCount();
    } catch (e) { tbody.replaceChildren(...kids(h("tr", {}, h("td", { colspan: 8, class: "rq-empty", text: e.message })))); }
  }
  function tcCount() {
    const n = X.selected.size;
    $("tcRun").disabled = $("tcContinue").disabled = !n;
    $("tcRun").textContent = n ? `Run Selected Tests (${n})` : "Run Selected Tests";
    $("exSelCount").textContent = n;
  }
  $("tcAll").addEventListener("change", (e) => {
    (S.cases || []).filter(runnable).forEach((c) => { e.target.checked ? X.selected.add(c.id) : X.selected.delete(c.id); });
    selChanged(); tcList();
  });
  async function tcDetail(id) {
    const d = await api(`/test-cases/${encodeURIComponent(id)}`);
    const c = d.test_case;
    $("dtKey").textContent = c.id; $("dtTitle").textContent = c.title;
    $("dtMeta").replaceChildren(...kids(`${c.requirement_id} · ${c.kind} · version ${c.version} · `, caseBadge(c.status)));
    const editable = c.status !== "stale";
    const form = h("form", { class: "rq-review", onsubmit: async (e) => {
      e.preventDefault();
      try {
        await api(`/test-cases/${encodeURIComponent(id)}`, { method: "PUT", body: { title: e.target.title.value,
          steps: e.target.steps.value.split("\n").map((s) => s.trim()).filter(Boolean), expected: e.target.expected.value } });
        tcDetail(id); tcList();
      } catch (err) { banner(err.message); }
    } }, h("label", {}, "Title", h("input", { name: "title", value: c.title, required: true, minlength: 3 })),
      h("label", {}, "Steps (one per line)", h("textarea", { name: "steps", rows: 4, text: c.steps.join("\n") })),
      h("label", {}, "Expected result", h("input", { name: "expected", value: c.expected })),
      h("div", { class: "rq-row" }, h("button", { class: "secondary", type: "submit", text: "Save changes (needs approval again)" })));
    $("dtBody").replaceChildren(...kids(
      c.stale_reason ? h("div", { class: "rq-issue" }, h("b", { text: "Stale: " }), c.stale_reason, " — re-analyse the requirement, review it and generate again.") : null,
      c.blocked_reason ? h("div", { class: "rq-issue conflict" }, h("b", { text: "Not automated: " }), c.blocked_reason) : null,
      c.test_data_needs.length ? h("div", { class: "rq-issue" }, h("b", { text: "Needs test data: " }), c.test_data_needs.join("; "), " (entered in the Execution Center, never invented).") : null,
      h("dl", { class: "rq-kv" }, h("dt", { text: "Requirement" }), h("dd", { text: `${c.requirement_id} — ${c.requirement_title}` }),
        h("dt", { text: "Criteria" }), h("dd", { text: c.criterion_ids.join(", ") }), h("dt", { text: "Source" }),
        h("dd", { text: `${c.source_id} version ${c.source_version}` }), h("dt", { text: "Approved idea" }),
        h("dd", { text: `${c.suggestion_id} by ${c.reviewer || "—"}${c.edited_by ? ` (edited by ${c.edited_by})` : ""}` }),
        h("dt", { text: "Expected basis" }), h("dd", { text: c.expected_basis === "explicit" ? "quoted from the requirement" : "inferred (not stated in the requirement)" })),
      h("h3", { class: "rq-sub", text: "Preconditions" }), h("ul", { class: "rq-list" }, (c.preconditions.length ? c.preconditions : ["—"]).map((x) => h("li", { text: x }))),
      h("h3", { class: "rq-sub", text: "Steps" }), h("ol", { class: "rq-list" }, c.steps.map((x) => h("li", { text: x }))),
      h("h3", { class: "rq-sub", text: "Expected result" }), h("p", { text: c.expected }),
      h("h3", { class: "rq-sub", text: "Checks" }), h("ul", { class: "rq-list" }, c.assertions.map((x) => h("li", { text: x }))),
      h("h3", { class: "rq-sub", text: "Requirement evidence" }), c.evidence.map((ev) => h("blockquote", { class: "rq-quote", text: `${ev.source} v${ev.version} (${ev.locator}): ${ev.quote}` })),
      c.status === "awaiting_approval" && S.caps.can_review ? h("div", { class: "rq-row" }, h("button", { class: "primary", type: "button", text: "Approve this version",
        onclick: async () => { try { await api(`/test-cases/${encodeURIComponent(id)}/approve`, { method: "POST" }); tcDetail(id); tcList(); } catch (err) { banner(err.message); } } })) : null,
      editable ? h("details", {}, h("summary", { text: "Edit test case" }), form) : null,
      h("h3", { class: "rq-sub", text: `Results (${d.results.length})` }),
      d.results.length ? h("ul", { class: "rq-audit" }, d.results.map((r) => h("li", {}, h("time", { text: when(r.at) }), resultBadge(r.status),
        h("span", { text: r.actual || r.reason || "" }), ...evidenceLinks(r)))) : h("p", { class: "small", text: "Not run yet." }),
      h("h3", { class: "rq-sub", text: "History" }), h("ul", { class: "rq-audit" }, d.history.map((x) => h("li", {}, h("time", { text: when(x.at) }), `v${x.version} — ${x.event}`)))));
    document.querySelectorAll(".rq-tabs").forEach((t) => { t.hidden = true; });
    if (!$("detail").open) $("detail").showModal();
    $("detail").addEventListener("close", () => document.querySelectorAll(".rq-tabs").forEach((t) => { t.hidden = false; }), { once: true });
  }


  // ---------------------------------------------------------------- defects and controlled write-back (Phase 5)
  const WB = { canReview: false };
  async function writebackView() {
    try {
      const s = await api("/writeback");
      WB.canReview = s.can_review;
      const conns = s.connections;
      $("wbState").replaceChildren(...kids(
        h("h2", { class: "rq-sub", text: "Jira write-back" }),
        h("dl", { class: "rq-kv" },
          h("dt", { text: "Server owner" }), h("dd", {}, s.server_allows ? badge("allows write-back", "ok") : badge(`off (${s.server_setting}=1 not set)`, "warn")),
          h("dt", { text: "Write token" }), h("dd", {}, s.write_token.configured ? badge(`stored (${s.write_token.source})`, "ok") : badge("not stored", "warn"))),
        conns.length ? conns.map((c) => h("form", { class: "rq-inline rq-wbset", "aria-label": `Write-back settings for ${c.connection_id}`, onsubmit: async (e) => {
          e.preventDefault();
          const out = e.target.querySelector("output");
          try {
            await api(`/writeback/settings/${encodeURIComponent(c.connection_id)}`, { method: "PUT", body: { enabled: e.target.enabled.checked, project_key: e.target.project.value.trim(), issue_type: e.target.itype.value.trim() || "Bug" } });
            writebackView();
          } catch (err) { out.textContent = err.message; }
        } }, h("b", { text: `${c.connection_id} (${c.site_url})` }), " ", c.can_send ? badge("can send approved writes", "ok") : badge("sending blocked", "warn"),
          h("label", { class: "rq-check" }, h("input", { type: "checkbox", name: "enabled", checked: c.enabled, disabled: !s.server_allows }), " write-back on"),
          h("label", {}, "Project for defects", h("input", { name: "project", value: c.project_key, placeholder: "the story's project", size: 8 })),
          h("label", {}, "Issue type", h("input", { name: "itype", value: c.issue_type, size: 8 })),
          h("button", { class: "secondary", type: "submit", text: "Save" }), h("output", { class: "small", role: "alert" }),
          c.blocked_because.length ? h("p", { class: "small", text: `Not sent because: ${c.blocked_because.join("; ")}.` }) : null))
          : h("p", { class: "small" }, "No Jira connection yet. ", h("a", { href: "#integrations", text: "Connect Jira" }), "."),
        h("form", { class: "rq-inline", "aria-label": "Jira write token", onsubmit: async (e) => {
          e.preventDefault();
          const out = e.target.querySelector("output");
          try { await api("/writeback/token", { method: "PUT", body: { token: e.target.wtoken.value } }); e.target.wtoken.value = ""; writebackView(); }
          catch (err) { e.target.wtoken.value = ""; out.textContent = err.message; }
        } }, h("label", {}, "Write token (separate from the read token; never shown again)", h("input", { name: "wtoken", type: "password", autocomplete: "new-password", required: true })),
          h("button", { class: "secondary", type: "submit", text: "Store write token" }), h("output", { class: "small", role: "alert" }))));
      defectList();
      writesList(s.writes, conns);
    } catch (e) { $("wbState").replaceChildren(h("p", { class: "small", text: e.message })); }
  }
  $("dfStatus").addEventListener("change", () => defectList());
  $("dfForm").addEventListener("submit", (e) => e.preventDefault());
  async function defectList() {
    const tbody = $("dfTable").tBodies[0];
    try {
      const r = await api(`/defects?${new URLSearchParams({ status: $("dfStatus").value })}`);
      tbody.replaceChildren(...kids(r.defects.map((d) => h("tr", {},
        h("td", {}, h("b", { text: d.id }), h("div", { class: "small", text: d.actual })),
        h("td", { text: d.requirement_id }),
        h("td", {}, h("button", { class: "rq-open", type: "button", text: d.test_case_id, onclick: () => tcDetail(d.test_case_id) })),
        h("td", {}, badge(d.triage.replaceAll("_", " "), { likely_defect: "bad", needs_triage: "warn" }[d.triage] || "")),
        h("td", { text: d.severity }),
        h("td", {}, badge(d.status, { open: "bad", reopened: "bad", resolved: "ok" }[d.status] || ""), d.regression ? badge("regression", "warn") : null),
        h("td", { text: `${plural(d.occurrences, "time")}, last ${when(d.last_seen)}` }),
        h("td", { text: d.jira_issue || "—" }),
        h("td", {}, ["open", "reopened"].includes(d.status) && !d.jira_issue && ["likely_defect", "needs_triage"].includes(d.triage)
          ? h("button", { class: "secondary", type: "button", text: "Propose Jira bug", onclick: async (e) => {
            try { await api("/writeback/proposals", { method: "POST", body: { defect_id: d.id } }); writebackView(); }
            catch (err) { e.target.after(h("span", { class: "small", role: "alert", text: ` ${err.message}` })); }
          } }) : null,
          ["open", "reopened"].includes(d.status) && WB.canReview ? h("details", { class: "rq-dismiss" }, h("summary", { text: "Not a defect…" }),
            h("form", { onsubmit: async (e) => {
              e.preventDefault();
              try { await api(`/defects/${encodeURIComponent(d.id)}/dismiss`, { method: "POST", body: { reason: e.target.reason.value } }); defectList(); }
              catch (err) { e.target.querySelector("output").textContent = err.message; }
            } }, h("label", {}, `Why is ${d.id} not a defect?`, h("input", { name: "reason", required: true, minlength: 3 })),
              h("button", { class: "secondary", type: "submit", text: "Dismiss defect" }), h("output", { class: "small", role: "alert" }))) : null)))));
      if (!r.defects.length) tbody.append(h("tr", {}, h("td", { colspan: 9, class: "rq-empty", text: "No defects. Failed requirement tests appear here." })));
    } catch (e) { tbody.replaceChildren(h("tr", {}, h("td", { colspan: 9, class: "rq-empty", text: e.message }))); }
  }
  function writesList(writes, conns) {
    const can = Object.fromEntries(conns.map((c) => [c.connection_id, c]));
    $("wbWrites").replaceChildren(...kids(writes.length ? writes.map((w) => {
      const c = can[w.connection_id] || { can_send: false, blocked_because: ["no such Jira connection"] };
      const out = h("p", { class: "small", role: "status", "aria-live": "polite" });
      const act = async (path) => { try { await api(`/writeback/${encodeURIComponent(w.id)}/${path}`, { method: "POST" }); writebackView(); } catch (err) { out.textContent = err.message; } };
      return h("article", { class: "rq-review", "aria-label": `${w.id} ${w.operation} ${w.target}` },
        h("h3", { text: `${w.id} — ${w.operation === "add_comment" ? "comment on" : "new issue in"} ${w.target}` }),
        h("div", { class: "rq-row" }, badge(w.status, { proposed: "info", approved: "ok", sent: "ok", rejected: "", failed: "bad" }[w.status] || ""),
          w.remote_id ? badge(`Jira: ${w.remote_id}`, "ok") : null, h("span", { class: "small", text: `proposed by ${w.created_by} ${when(w.created_at)}` })),
        w.operation === "add_comment" ? h("pre", { class: "rq-pre", text: w.payload.text }) : h("div", {}, h("p", {}, h("b", { text: w.payload.summary })), h("pre", { class: "rq-pre", text: w.payload.description })),
        h("details", {}, h("summary", { text: "Exact request that would be sent" }), h("pre", { class: "rq-pre", text: JSON.stringify(w.preview, null, 2) })),
        w.last_error ? h("p", { class: "rq-issue", text: `Last attempt: ${w.last_error}` }) : null,
        h("div", { class: "rq-row" },
          w.status === "proposed" && WB.canReview ? h("button", { class: "primary", type: "button", text: "Approve", onclick: () => act("approve") }) : null,
          w.status === "proposed" && WB.canReview ? h("button", { class: "secondary", type: "button", text: "Reject", onclick: () => act("reject") }) : null,
          ["approved", "failed"].includes(w.status) ? h("button", { class: "primary", type: "button", text: w.status === "failed" ? "Retry sending" : "Send to Jira", disabled: !c.can_send,
            title: c.can_send ? "" : c.blocked_because.join("; "), onclick: () => act("send") }) : null,
          ["approved", "failed"].includes(w.status) && !c.can_send ? h("span", { class: "small", text: `Not sendable: ${c.blocked_because.join("; ")}.` }) : null),
        h("ul", { class: "rq-audit" }, w.history.map((x) => h("li", {}, h("time", { text: when(x.at) }), x.event))), out);
    }) : h("p", { class: "rq-empty", text: "No proposed writes. Propose results from an execution, or a bug from a defect." })));
  }
  // -- execution center
  async function executionCenter() {
    await refreshWorkflow();
    const d = WF.draft || {};
    if (draftCases().length) X.selected = new Set(draftCases());
    const strat = document.querySelector(`input[name=exStrategy][value=${d.strategy || "requirements"}]`);
    if (strat) strat.checked = true;
    if (d.environment) $("exEnv").value = d.environment;
    const scope = document.querySelector(`input[name=exScope][value=${S.presetScope || "selected"}]`);
    if (scope) scope.checked = true;
    if (S.presetScope && S.presetScope !== "selected") $("exAdvanced").open = true;
    S.caseCriteria = [];
    try {
      for (const c of draftCases().slice(0, 30)) {
        const one = await api(`/test-cases/${encodeURIComponent(c)}`);
        one.test_case.criterion_ids.forEach((x) => { if (!S.caseCriteria.includes(x)) S.caseCriteria.push(x); });
      }
    } catch (err) { /* (shown without criteria) */ }
    tcCount(); execSummary(); resolveTarget(); exList(); aiProviders();
  }
  document.querySelectorAll("input[name=exStrategy]").forEach((r) => r.addEventListener("change", () => {
    execSummary(); if (WF.draft) saveDraft({ strategy: r.value });
  }));
  $("exForm2").addEventListener("submit", async (e) => {
    e.preventDefault();
    const out = $("xcStatus");
    const fail = (text) => { out.replaceChildren(h("span", { class: "rq-issue", role: "alert", text })); stop(text); };
    const strategy = document.querySelector("input[name=exStrategy]:checked").value;
    const mode = document.querySelector("input[name=exScope]:checked").value;
    const selected = [...X.selected];
    const scope = { selected: { test_case_ids: selected }, requirements: { requirements: list($("exReqs").value).map((x) => x.toUpperCase()) },
      all_approved: { all_approved: true }, failed: { failed: true }, impacted: { impacted: true }, regression: { regression: true },
      epic: { epic: $("exEpic").value.trim().toUpperCase() } }[mode];
    const url = $("exUrl").value.trim();
    const android = $("xcApp").value === "android", androidApp = android && $("exAndMode").value === "installed";
    const apiRun = $("xcApp").value === "api", iosRun = $("xcApp").value === "ios";
    if (strategy !== "autonomous" && mode === "selected" && !selected.length) return fail("No test case is selected. Select approved test cases in Test Cases first (or choose Autonomous).");
    if (iosRun) {
      if (!$("exIosBundle").value.trim() && !$("exIosApp").value.trim()) { $("exIosBundle").focus(); return fail("Enter the iOS app's bundle id or app file."); }
    } else if (apiRun) {  // (a REST API: its document; no browser)
      if (!$("exApiSpec").value.trim()) { $("exApiSpec").focus(); return fail("Enter the API's OpenAPI / Swagger document address."); }
    } else if (androidApp) {  // (an installed app: no website address; Appium checks the device)
      if (!$("exDevice").value.trim()) { $("exDevice").focus(); return fail("Choose the Android device or emulator (its id from 'adb devices')."); }
      if (!$("exPackage").value.trim()) { $("exPackage").focus(); return fail("Enter the Android app's package name."); }
    } else if (!url) { $("exUrl").focus(); return fail("Target website not found. Please enter the website URL you want to test."); }
    if (!/^https?:\/\/[^\s/]+/i.test(url)) { $("exUrl").focus(); return fail("Enter a full website address starting with http:// or https://"); }
    if (!$("exAuth").checked) { $("exAuth").focus(); return fail("Confirm that you own the application or have permission to test it."); }
    if (!androidApp && !apiRun && !iosRun) {
      out.textContent = "Checking the website…";
      let reach;
      try { reach = await checkTarget(); } catch (err) { return fail(err.message); }
      if (!reach || !reach.ok) return fail(`The website could not be used: ${reach ? reach.message : "no answer"} Your selection is kept: correct the address and run again.`);
    }
    const projects = TG.projects || [];
    const target = { type: $("xcApp").value, url, authorized: true, environment: $("exEnv").value,
      test_username: $("exUser").value.trim(), test_password: $("exPass").value, llm_provider: $("exAi").value, llm_model: $("exModel").value.trim(),
      api_key: $("exKey").value, max_pages: Number($("exPages").value) || 0, page_timeout_s: Number($("exTimeout").value) || 0,
      show_browser: $("exShow").checked, record_video: $("exVideo").checked, thorough: $("exThorough").checked,
      demo_checkout: $("exDemo").checked, use_saved_account: true,
      payment_provider: $("exPayProvider").value, payment_sandbox_confirmed: $("exPayConfirm").checked,
      ...(iosRun ? { ios: { bundle_id: $("exIosBundle").value.trim(), app_path: $("exIosApp").value.trim(), udid: $("exIosUdid").value.trim(),
        platform_version: $("exIosVersion").value.trim(), appium_url: $("exIosAppium").value.trim() } } : {}),
      ...(apiRun ? { api_spec_url: $("exApiSpec").value.trim(), api_token: $("exApiToken").value,
        api_allow: [...document.querySelectorAll(".exApiAllow:checked")].map((x) => x.value) } : {}),
      ...(android ? { android_mode: $("exAndMode").value, device_id: $("exDevice").value.trim(), package_name: $("exPackage").value.trim(),
        app_activity: $("exActivity").value.trim(), appium_url: $("exAppium").value.trim() } : {}), save_target: $("tgSave").checked && projects.length > 0, project_key: projects[0] || "" };
    // preflight: the same checks the server enforces - nothing is created when the run could not test anything
    out.textContent = "Checking the AI, the browser and the website (the page is opened once)…";
    $("xcProblems").replaceChildren();
    let pre;
    try { pre = await api("/executions/preflight", { method: "POST", body: { strategy, scope, target } }); }
    catch (err) { return fail(err.message); }
    if (!pre.ok) { showProblems(pre.problems); return fail(pre.problems.find((p) => p.blocking).message); }
    $("exPass").value = ""; $("exKey").value = ""; $("exApiToken").value = "";  // (sent once, never kept in the page)
    out.textContent = `Starting the test run (AI: ${pre.ai.provider}${pre.ai.model ? ` · ${pre.ai.model}` : ""})…`;
    try {
      const r = await api("/executions", { method: "POST", body: { strategy, scope, target } });
      const ex = r.execution;
      const pre = ex.prerequisites || {};
      out.textContent = `Running ${plural(ex.case_ids.length, "test case")}${ex.excluded.length ? ` (${ex.excluded.length} left out: ${ex.excluded.map((x) => `${x.id} ${x.reason}`).join("; ")})` : ""}.`
        + ((pre.added || []).length ? ` Prerequisites added automatically: ${pre.added.join(", ")} (needed first by ${Object.keys(pre.chains || {}).join(", ")}).` : "")
        + ((pre.skipped || []).length ? ` Prerequisites that cannot run: ${pre.skipped.map((x) => `${x.requires} for ${x.case}`).join("; ")}.` : "")
        + ((pre.cycles || []).length ? ` Circular prerequisites ignored: ${pre.cycles.map((c) => c.join(" → ")).join("; ")}.` : "");
      S.presetScope = null; S.reportId = null; S.liveId = null;  // (the run just started is the one shown)
      await saveDraft({ execution_id: ex.id, target_url: url, strategy, step: "agents" });
      location.hash = "#agents";  // (the live view opens by itself: no second Run button)
    } catch (err) { fail(err.message); }
  });
  $("xcApp").addEventListener("change", () => { $("xcAndroid").hidden = $("xcApp").value !== "android"; $("xcApi").hidden = $("xcApp").value !== "api"; $("xcIos").hidden = $("xcApp").value !== "ios"; });
  // the application keeps the tester out (bot check, CAPTCHA, SSO / MFA ...): the run is paused - an authorized person
  // signs in / passes the check in their own browser and gives the run that session (only the site's own cookies)
  async function livePause(job) {
    let p;
    try { p = await api(`/api/runs/${job}/pause`); } catch (_) { return; }
    const box = $("livePause");
    if (!p || !p.paused) { box.hidden = true; box.replaceChildren(); return; }
    if (!box.hidden && box.dataset.since === String(p.since)) return;  // (already shown: keep what is typed)
    box.dataset.since = String(p.since); box.hidden = false;
    const area = h("textarea", { id: "helpState", rows: 4, placeholder: "Paste the session from your own browser: a Playwright storage state (JSON), or a Cookie header (name=value; …)" });
    const out = h("p", { class: "small", role: "status" });
    box.replaceChildren(h("div", { class: "rq-issue", role: "alert" },
      h("b", { text: `Paused — ${p.message}` }), h("p", { class: "small", text: `${p.url} · waiting up to ${p.wait_s} s · nothing is bypassed. What helps: ${p.help}.` }),
      h("label", { for: "helpState", class: "small", text: "Your session for this website" }), area,
      h("button", { type: "button", class: "secondary", text: "Give the run my session", onclick: async () => {
        const raw = area.value.trim(); let body;
        try { body = raw.startsWith("{") ? { storage_state: JSON.parse(raw) } : { cookie_header: raw }; } catch (e) { out.textContent = "That is not valid JSON."; return; }
        try { const r = await api(`/api/runs/${job}/help`, { method: "POST", body }); out.textContent = r.message; area.value = ""; } catch (err) { out.textContent = err.message; }
      } }), out));
  }

  // what the preflight found, each with the action that fixes it (the selection and the form stay as they are)
  function showProblems(problems) {
    const act = { ai: ["Choose an AI provider", () => $("exAi").focus()], choose_ai: ["Choose an AI provider", () => $("exAi").focus()],
      api_key: ["Enter the AI key", () => $("exKey").focus()], allow_cloud: ["Allow cloud AI", () => { $("aiCloud").hidden = false; $("aiConsent").focus(); }],
      start_ollama: ["Choose another AI", () => $("exAi").focus()], choose_model: ["Choose the model", () => $("exModel").focus()],
      enter_account: ["Enter the test account", () => { $("tgCreds").hidden = false; $("exUser").focus(); }],
      enter_url: ["Enter the website", () => $("exUrl").focus()], retry_or_change: ["Change the address", () => $("exUrl").focus()],
      confirm_authorization: ["Confirm permission", () => $("exAuth").focus()],
      enter_device: ["Enter the device", () => $("exDevice").focus()],
      confirm_payment: ["Confirm the sandbox", () => $("exPayConfirm").focus()], choose_payment: ["Choose the sandbox", () => $("exPayProvider").focus()], enter_package: ["Enter the app package", () => $("exPackage").focus()],
      choose_strategy: ["Choose the strategy", () => $("exDemo").focus()], select_cases: ["Select test cases", () => { location.hash = "#builder"; }],
      install_browser: ["How to install the browser", () => { location.href = "/#help"; }] };
    $("xcProblems").replaceChildren(h("div", { class: "rq-issue", role: "alert" }, h("b", { text: "Not started - this run could not test anything yet:" }),
      h("ul", { class: "rq-list" }, problems.map((p) => h("li", {}, p.message, " ",
        act[p.recovery] ? h("button", { type: "button", class: "secondary", text: act[p.recovery][0], onclick: act[p.recovery][1] }) : null)))));
  }

  // -- the AI for this run: the providers Qpilot supports, with their real readiness (never a hard-coded model)
  const AI = { list: [], privacy: null };
  async function aiProviders() {
    try {
      const r = await api("/api/providers");
      AI.list = r.providers; AI.privacy = r.privacy;
      const want = (WF.draft && WF.draft.ai_provider) || "";
      const pick = AI.list.find((p) => p.id === want) || AI.list.find((p) => p.id === r.env_provider && p.ready && p.id !== "none")
        || AI.list.find((p) => p.ready && p.id !== "none") || AI.list.find((p) => p.id === r.env_provider) || AI.list[0];
      $("exAi").replaceChildren(...AI.list.map((p) => h("option", { value: p.id, selected: pick && p.id === pick.id,
        text: `${p.name}${p.id === "none" ? " (only test cases that need no AI)" : ""} — ${p.ready ? "ready" : p.readiness_reason}` })));
      if (WF.draft && WF.draft.ai_model) $("exModel").value = WF.draft.ai_model;
      aiChanged(false);
    } catch (e) { $("aiState").textContent = e.message; }
  }
  function aiChanged(save = true) {
    const p = AI.list.find((x) => x.id === $("exAi").value);
    if (!p) return;
    $("exModels").replaceChildren(...(p.models || []).map((m) => h("option", { value: m })));
    $("exModel").placeholder = (p.models || [])[0] ? `default: ${p.models[0]}` : "the provider's default";
    const blocked = !p.allowed && AI.privacy && AI.privacy.mode === "local";
    $("aiCloud").hidden = !blocked;
    $("aiState").replaceChildren(h("p", { class: "small" }, p.ready ? badge("ready", "ok") : badge(p.readiness_reason, "warn"), " ",
      p.id === "none" ? "Approved requirement test cases need an AI: with none they cannot be automated, so such a run is not started."
        : blocked ? `Privacy is set to local-only, so ${p.name} (a cloud AI) may not be used. Allow cloud AI below, or choose a local AI.`
        : !p.ready && p.key_env ? `Enter a key for this run below, or add ${p.key_env} to the server's .env.` : p.ready ? `${p.name} will turn the test cases into browser steps.` : ""));
    if (save && WF.draft) saveDraft({ ai_provider: p.id, ai_model: $("exModel").value.trim() });
  }
  $("exAi").addEventListener("change", () => aiChanged());
  $("exModel").addEventListener("change", () => { if (WF.draft) saveDraft({ ai_model: $("exModel").value.trim() }); });
  $("aiAllow").addEventListener("click", async () => {
    if (!$("aiConsent").checked) { $("aiConsent").focus(); $("aiState").textContent = "Tick the agreement first: it says what is sent to the cloud AI."; return; }
    try {
      await api("/api/settings/privacy", { method: "PUT", body: { mode: "cloud", cloud_consent: true, allow_mcp: Boolean(AI.privacy && AI.privacy.allow_mcp) } });
      await aiProviders();
    } catch (err) { $("aiState").textContent = err.message; }
  });

  async function exList() {
    const tbody = $("exList").tBodies[0];
    try {
      const r = await api("/executions?limit=30");
      tbody.replaceChildren(...kids(r.executions.map((ex) => h("tr", {},
        h("td", {}, h("button", { class: "rq-open", type: "button", text: ex.id, onclick: () => exDetail(ex.id) })),
        h("td", { text: ex.strategy }), h("td", { text: ex.case_ids.length }), h("td", {}, statusBadge({ finished: "complete", running: "running", queued: "running", stopped: "cancelled", failed: "failed" }[ex.status] || ex.status)),
        h("td", {}, outcomeBadge(ex), h("br"), h("span", { class: "small", text: tallyText(ex) || "—" })),
        h("td", { text: when(ex.created_at) }), h("td", { text: ex.actor })))));
      if (!r.executions.length) tbody.append(...kids(h("tr", {}, h("td", { colspan: 7, class: "rq-empty", text: "No executions yet." }))));
    } catch (e) { tbody.replaceChildren(...kids(h("tr", {}, h("td", { colspan: 7, class: "rq-empty", text: e.message })))); }
  }
  async function exDetail(id) {
    clearTimeout(X.poll);
    X.current = id;
    const box = $("exDetail");
    try {
      const d = await api(`/executions/${encodeURIComponent(id)}`);
      const ex = d.execution, live = d.live || {};
      const running = ["running", "queued"].includes(ex.status);
      box.replaceChildren(...kids(h("section", { class: "lab-card" },
        h("h2", { class: "rq-sub", text: `${ex.id} — ${ex.strategy}` }),
        h("p", { class: "small" }, `${ex.target.url} · started ${when(ex.created_at)} by ${ex.actor} · `, outcomeBadge(ex),
          live.run ? h("span", {}, " · ", h("a", { href: `/runs/${encodeURIComponent(live.run)}/report.html`, target: "_blank", rel: "noopener", text: "full Qpilot report" })) : null),
        running ? h("div", {}, h("div", { class: "rq-progress", role: "progressbar", "aria-valuetext": live.current || "running" }, h("span")),
          h("p", { role: "status", "aria-live": "polite", text: live.current ? `Now: ${live.current}` : "Running…" }),
          h("button", { class: "secondary", type: "button", text: "Cancel", onclick: async () => { await api(`/executions/${encodeURIComponent(id)}/cancel`, { method: "POST" }); exDetail(id); } })) : null,
        ex.excluded && ex.excluded.length ? h("div", { class: "rq-issue" }, h("b", { text: "Not run: " }), ex.excluded.map((x) => `${x.id} (${x.reason})`).join("; ")) : null,
        d.results.length ? h("div", { class: "rq-table-wrap" }, h("table", { class: "rq-table" }, h("caption", { class: "rq-sr", text: "Results" }),
          h("thead", {}, h("tr", {}, ["Test case", "Result", "Actual result / reason", "Evidence"].map((text) => h("th", { scope: "col", text })))),
          h("tbody", {}, d.results.map((r) => h("tr", {}, h("td", {}, h("button", { class: "rq-open", type: "button", text: r.test_case_id, onclick: () => tcDetail(r.test_case_id) })),
            h("td", {}, resultBadge(r.status)), h("td", { text: r.actual || r.reason || "" }), h("td", {}, ...evidenceLinks(r))))))) : null,
        ex.exploratory && ex.exploratory.cases ? h("p", { class: "small", text: `Exploratory (not from requirements): ${ex.exploratory.cases} case(s), ${ex.exploratory.passed} passed, ${ex.exploratory.failed} failed — details in the run's report / folder.` }) : null,
        !running && d.results.length ? h("div", { class: "rq-row" }, h("button", { class: "secondary", type: "button", text: "Propose these results to Jira", onclick: async (e) => {
          try { await api("/writeback/proposals", { method: "POST", body: { execution_id: id } }); location.hash = "#writeback"; }
          catch (err) { e.target.after(h("span", { class: "small", role: "alert", text: ` ${err.message}` })); }
        } }), h("span", { class: "small", text: "Only a proposal: you see exactly what would be written, and nothing is sent without approval." })) : null)));
      if (running) X.poll = setTimeout(() => { if (location.hash === "#execution" || location.hash === "#agents") { exDetail(id); liveView(); } }, 3000);
      else exList();
    } catch (e) { box.replaceChildren(...kids(h("p", { class: "small", text: e.message }))); }
  }

  // -- traceability
  let trRows = [];
  async function traceabilityView() {
    const tbody = $("trTable").tBodies[0];
    api("/accountability").then((acc) => {  // (every requirement accounted for: the four figures kept apart)
      const s = acc.summary, pct = (v) => (v == null ? "—" : `${v} %`);
      $("trAccount").replaceChildren(h("p", { class: "small" },
        h("b", { text: `${s.requirements} requirement(s)` }), ` · requirement coverage ${pct(s.requirement_coverage)} (criteria with a passed test) · automation coverage ${pct(s.automation_coverage)} (cases that ran) · execution coverage ${pct(s.execution_coverage)} (cases with an outcome) · pass rate ${pct(s.pass_rate)}`),
        ...acc.requirements.filter((r) => r.blockers.length).map((r) => h("p", { class: "small rq-issue" }, h("b", { text: `${r.requirement}: ` }), r.blockers.join(" · "))));
    }).catch(() => {});
    try {
      const r = await api(`/traceability?${new URLSearchParams({ q: $("trQ").value, coverage: $("trCov").value })}`);
      trRows = r.rows;
      tbody.replaceChildren(...kids(r.rows.map((x) => h("tr", {}, h("td", { text: `${x.requirement} — ${x.summary}` }),
        h("td", { text: `${x.criterion.split("#")[1]}: ${x.criterion_text}` }), h("td", { text: `${x.source} v${x.source_version} · ${x.locator}` }),
        h("td", {}, x.test_case ? h("button", { class: "rq-open", type: "button", text: x.test_case, onclick: () => tcDetail(x.test_case) }) : "—"),
        h("td", {}, x.test_status ? caseBadge(x.test_status) : "—"), h("td", {}, x.result ? resultBadge(x.result) : "—"),
        h("td", { text: when(x.last_run) }), h("td", {}, ...evidenceLinks({ evidence: x.evidence, run_folder: x.run_folder })),
        h("td", {}, badge(x.coverage, { passed: "ok", failed: "bad", blocked: "bad", stale: "warn", planned: "info" }[x.coverage] || ""))))));
      if (!r.rows.length) tbody.append(...kids(h("tr", {}, h("td", { colspan: 9, class: "rq-empty", text: "Nothing to trace yet: analyse requirements first." }))));
    } catch (e) { tbody.replaceChildren(...kids(h("tr", {}, h("td", { colspan: 9, class: "rq-empty", text: e.message })))); }
  }
  $("trForm").addEventListener("submit", (e) => e.preventDefault());
  $("trQ").addEventListener("input", () => traceabilityView());
  $("trCov").addEventListener("change", () => traceabilityView());
  $("trExport").addEventListener("click", () => {
    const cols = ["requirement", "summary", "criterion", "criterion_text", "source", "source_version", "test_case", "test_status", "result", "last_run", "coverage"];
    const cell = (v) => `"${String(v ?? "").replaceAll('"', '""')}"`;
    const csv = [cols.join(","), ...trRows.map((r) => cols.map((c) => cell(r[c])).join(","))].join("\n");
    const a = h("a", { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: "traceability.csv" });
    document.body.append(a); a.click(); a.remove();
  });
  async function executedCoverage() {
    const box = $("rqExecCoverage");
    try {
      const r = await api("/coverage/execution");
      const c = r.coverage;
      const tile = (n, label, kind = "") => h("div", { class: `rq-stat ${kind}` }, h("b", { text: n }), h("span", { text: label }));
      box.replaceChildren(...kids(h("div", { class: "rq-stats" }, tile(c.requirements, "requirements"), tile(c.with_approved_scenarios, "with approved ideas"),
        tile(c.with_test_cases, "with test cases (planned)"), tile(c.executed, "executed"), tile(c.passed, "fully passed", "ok"),
        tile(c.failed, "with a failure", c.failed ? "bad" : ""), tile(c.not_tested, "not tested"), tile(c.needs_revalidation, "need revalidation", c.needs_revalidation ? "warn" : "")),
        h("p", { class: "small", text: c.basis }),
        r.impacted.length ? h("div", { class: "rq-issue" }, h("b", { text: "Changed requirements: " }), r.impacted.map((x) => `${x.id} (${x.reason})`).join("; ")) : null));
    } catch (e) { box.textContent = e.message; }
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
    } catch (e) { tbody.replaceChildren(...kids(h("tr", {}, h("td", { colspan: 13, class: "rq-empty", text: e.message })))); }
  }
  async function auditView() {
    try {
      const a = await api("/audit?limit=200");
      $("auditList").replaceChildren(...kids(...(a.events.length ? a.events.map((e) => h("li", {}, h("time", { text: when(typeof e.created_at === "number" ? e.created_at * 1000 : (e.created_at || e.at)) }),
        h("b", { text: e.action.replace("requirements.", "") }), e.allowed ? null : badge("refused", "bad"), h("span", { class: "small", text: `${e.actor}` })))
        : [h("li", { class: "small", text: "No events yet." })])));
    } catch (e) { $("auditList").replaceChildren(...kids(h("li", { class: "small", text: e.status === 403 ? "The audit trail is for administrators." : e.message }))); }
  }

  // ---------------------------------------------------------------- the guided workflow (its draft is kept on the server)
  // A draft holds what was chosen (requirements, test cases, strategy, target, execution id) - never a password or
  // key. "Done" marks come from the stores (GET /workflow), never from "the page was opened". New Test = a new draft.
  const WF = { draft: null, state: null, steps: [] };
  const STEP_LABEL = { connect: "Connect Jira", import: "Import", explorer: "Requirements", analysis: "Analyze", reviews: "Review",
    builder: "Test Cases", execution: "Execution", agents: "Live", reports: "Report" };
  const STEP_VIEW = { connect: "integrations", import: "import", explorer: "explorer", analysis: "analysis", reviews: "reviews",
    builder: "builder", execution: "execution", agents: "agents", reports: "reports" };
  const VIEW_STEP = Object.fromEntries(Object.entries(STEP_VIEW).map(([k, v]) => [v, k]));
  const LV = { id: "", job: null, cursor: "", follow: true, timer: null, workers: [], seen: new Set(), frames: {}, framed: {}, shown: {} };
  async function loadWorkflow() { const r = await api("/workflow"); WF.draft = r.draft; WF.state = r.state; WF.steps = r.steps; return r; }
  async function saveDraft(changes) {
    try {
      const r = await api("/workflow/draft", { method: "PUT", body: { draft_id: WF.draft ? WF.draft.id : "", changes } });
      WF.draft = r.draft; WF.state = r.state; WF.steps = r.steps;
    } catch (e) {
      if (e.status !== 409) throw e;
      await loadWorkflow(); banner(e.message);
    }
    paintWorkflow();
    return WF.draft;
  }
  async function refreshWorkflow() { try { await loadWorkflow(); paintWorkflow(); } catch (e) { /* the page itself still works */ } }
  const draftReqs = () => (WF.draft && WF.draft.requirement_ids) || [];
  const draftCases = () => (WF.draft && WF.draft.test_case_ids) || [];
  function paintWorkflow() {
    if (!WF.state) return;
    const done = WF.state.done;
    for (const link of navigation) {
      const step = VIEW_STEP[link.dataset.view];
      link.classList.toggle("done", Boolean(step && done[step]));
      const name = link.querySelector(".rq-nav-text").textContent;
      link.title = step && done[step] ? `${name} — done` : name;
    }
    const cur = VIEW_STEP[S.view];
    $("wfSteps").hidden = !cur; $("wfNav").hidden = !cur;
    if (!cur) return;
    const idx = WF.steps.indexOf(cur);
    const nDone = WF.steps.filter((s) => done[s]).length;
    $("wfProgress").textContent = `Workflow step ${idx + 1} of ${WF.steps.length} · ${nDone} of ${WF.steps.length} steps done`
      + (draftReqs().length ? ` · ${draftReqs().join(", ")}` : "");
    $("wfBar").style.width = `${Math.round((100 * nDone) / WF.steps.length)}%`;
    $("wfList").replaceChildren(...WF.steps.map((s, i) => h("li", { class: `${done[s] ? "done" : ""} ${s === cur ? "current" : ""}`.trim() },
      h("a", { href: `#${STEP_VIEW[s]}`, "aria-current": s === cur ? "step" : null, "aria-label": `${STEP_LABEL[s]}${done[s] ? " (done)" : ""}` },
        h("span", { class: "n", "aria-hidden": "true", text: done[s] ? "✓" : String(i + 1) }), STEP_LABEL[s]))));
    const prev = WF.steps[idx - 1];
    $("wfBack").hidden = !prev;
    $("wfBack").textContent = prev ? `Back: ${STEP_LABEL[prev]}` : "Back";
    const nx = NEXT[cur];
    $("wfNext").hidden = !nx;
    if (nx) $("wfNext").textContent = nx.label();
  }
  function workflowChrome(view) {
    $("wfMsg").textContent = ""; $("wfMsg").className = "small";
    paintWorkflow();
    if (VIEW_STEP[view]) refreshWorkflow();
  }
  function stop(text, href, action) {  // a missing prerequisite: say what and offer the way to fix it
    const msg = $("wfMsg");
    msg.className = "small bad";
    msg.replaceChildren(...kids(text, href ? h("span", {}, " ", h("a", { href, text: action })) : null));
    return true;
  }
  const NEXT = {
    connect: { label: () => "Continue to Import", go: () => (WF.state.done.connect ? go("#import")
      : stop("Connect Jira first: enter the site, the account email and an API token, then Connect.")) },
    import: { label: () => "Continue to Requirements", go: () => (!WF.state.done.connect ? stop("Import needs a connected Jira site.", "#integrations", "Connect Jira")
      : WF.state.imported ? go("#explorer") : stop("Import requirements first: choose the project or work items above, then Import & Continue.")) },
    explorer: { label: () => "Analyze Selected Requirements", go: () => (WF.state.imported ? (draftReqs().length ? analyzeSelected(draftReqs())
      : stop("Select at least one requirement: tick it in the table.")) : stop("No requirements imported yet.", "#import", "Import requirements")) },
    analysis: { label: () => "Continue to Review", go: () => (!draftReqs().length ? stop("Select the requirements to analyse first.", "#explorer", "Choose requirements")
      : WF.state.done.analysis ? go("#reviews") : stop("Analyse the selected requirements first (above).")) },
    reviews: { label: () => "Generate Test Cases", go: () => generateForSelected() },
    builder: { label: () => "Continue to Execution", go: () => (draftCases().some((c) => WF.state.runnable.includes(c)) ? go("#execution")
      : stop(WF.state.runnable.length ? "Select the test cases to run (tick them in the table)." : "No approved test case yet.", WF.state.runnable.length ? null : "#reviews", "Review and generate")) },
    execution: { label: () => "Run Tests", go: () => { $("exForm2").requestSubmit(); return false; } },
    agents: { label: () => "View Report", go: () => (WF.state.execution && WF.state.done.agents ? go("#reports")
      : stop(WF.state.execution ? "The test is still running: the report opens when it ends." : "No execution yet.", WF.state.execution ? null : "#execution", "Go to the Execution Center")) },
  };
  function go(hash) { location.hash = hash; return false; }
  $("wfBack").addEventListener("click", () => {
    const i = WF.steps.indexOf(VIEW_STEP[S.view]);
    if (i > 0) location.hash = `#${STEP_VIEW[WF.steps[i - 1]]}`;
  });
  $("wfNext").addEventListener("click", async () => {
    const nx = NEXT[VIEW_STEP[S.view]];
    if (!nx) return;
    $("wfMsg").textContent = ""; $("wfMsg").className = "small";
    try { await refreshWorkflow(); await nx.go(); }
    catch (e) { stop(e.message); }
  });

  // -- step 3: the requirements chosen in the explorer
  async function connOf(keys) {  // requirement key -> its connection (from the imported items)
    const map = {};
    for (let page = 1; page < 50; page += 1) {
      const r = await api(`/items?${new URLSearchParams({ kind: "jira_issue", size: 100, page, missing: true })}`);
      r.items.forEach((it) => { map[it.key] = it.connection_id; });
      if (page * r.size >= r.total) break;
    }
    return keys ? Object.fromEntries(keys.map((k) => [k, map[k]])) : map;
  }
  async function analyzeSelected(keys) {
    await saveDraft({ requirement_ids: keys, step: "analysis" });
    S.autoAnalyze = true;
    location.hash = "#analysis";
    return false;
  }
  $("exAnSel").addEventListener("click", () => analyzeSelected(draftReqs()));
  $("exAnAll").addEventListener("click", async () => analyzeSelected(Object.keys(await connOf())));
  $("exAllSel").addEventListener("change", async (e) => {
    const keys = [...document.querySelectorAll("#exTable tbody input[data-key]")].map((x) => x.dataset.key);
    const sel = new Set(draftReqs());
    keys.forEach((k) => (e.target.checked ? sel.add(k) : sel.delete(k)));
    await saveDraft({ requirement_ids: [...sel] }); explorer();
  });
  function selInfo() {
    const n = draftReqs().length;
    $("exSelInfo").textContent = n ? `${plural(n, "requirement")} selected: ${draftReqs().join(", ")}` : "No requirement selected.";
    $("exAnSel").disabled = !n;
  }

  // -- step 4: analyse the selected requirements, then send their ideas to the Review Center
  async function analysisFlow() {
    const box = $("anFlow");
    box.replaceChildren(h("p", { class: "small", role: "status", text: "Loading the selected requirements…" }));  // (never the previous test's result)
    const keys = draftReqs();
    if (!keys.length) { box.replaceChildren(h("div", { class: "rq-issue" }, "No requirement selected for this test. ", h("a", { href: "#explorer", text: "Choose requirements" }), ".")); return; }
    const conns = await connOf(keys);
    await refreshWorkflow();
    const rows = {};
    const list = h("div", { class: "rq-an-list" });
    const status = h("p", { class: "small", role: "status", "aria-live": "polite" });
    box.replaceChildren(h("section", { class: "lab-card" }, h("h2", { class: "rq-sub", text: `Selected requirements (${keys.length})` }), status, list));
    for (const k of keys) { rows[k] = h("article", { class: "rq-review", "aria-label": k }, h("h3", { text: k }), h("p", { class: "small", text: "…" })); list.append(rows[k]); }
    const auto = S.autoAnalyze; S.autoAnalyze = false;
    let n = 0;
    for (const k of keys) {
      n += 1;
      if (!conns[k]) { rows[k].lastChild.textContent = "Not imported in this workspace."; continue; }
      let view = null;
      if (((WF.state || {}).has_analysis || []).includes(k)) {  // (never ask for an analysis that does not exist yet)
        try { view = await api(`/items/${encodeURIComponent(conns[k])}/${encodeURIComponent(k)}/analysis`); } catch (e) { view = null; }
      }
      if (!view || (view.stale_reasons || []).length || auto) {
        if (!view || (view.stale_reasons || []).length) {
          status.textContent = `Analysing ${k} (${n} of ${keys.length})…`;
          try { view = await api(`/items/${encodeURIComponent(conns[k])}/${encodeURIComponent(k)}/analyze`, { method: "POST", body: { ai: "auto" } }); }
          catch (e) { rows[k].replaceChildren(h("h3", { text: k }), h("p", { class: "rq-issue", role: "alert", text: e.message })); continue; }
        }
      }
      if (!view) { rows[k].lastChild.textContent = "Not analysed yet."; continue; }
      const s = view.summary, a = view.analysis;
      const sugg = a.suggestions || [];
      const pending = sugg.filter((x) => x.review === "needs_review").length;
      rows[k].replaceChildren(...kids(h("h3", { text: `${k} — ${s.title}` }),
        h("div", { class: "rq-row" }, badge(`${s.criteria.length} acceptance criteria`, "info"), badge(`${sugg.length} test suggestions`, "info"),
          pending ? badge(`${pending} waiting for review`, "warn") : badge("all reviewed", "ok"),
          s.issues.length ? badge(`${s.issues.length} missing / unclear`, "warn") : null, s.conflicts.length ? badge(`${s.conflicts.length} conflicts`, "bad") : null,
          s.criteria.some((c) => !c.coverage) ? badge("coverage gaps", "warn") : null),
        h("details", {}, h("summary", { text: "Criteria, suggestions and findings" }),
          h("ul", { class: "rq-list" }, s.criteria.map((c) => h("li", { text: `${c.id.split("#")[1]}: ${c.text} (${c.from})` }))),
          h("ul", { class: "rq-list" }, sugg.map((x) => h("li", { text: `${x.title} — ${x.kind}${x.expected_outcome ? `; expected: ${x.expected_outcome}` : ""}` }))),
          s.issues.length ? h("ul", { class: "rq-list" }, s.issues.map((x) => h("li", { text: x }))) : null,
          s.conflicts.length ? h("ul", { class: "rq-list" }, s.conflicts.map((x) => h("li", { text: x.summary }))) : null)));
    }
    status.textContent = "Analysis is done for the selected requirements. Their test suggestions are in the Review Center.";
    await refreshWorkflow();
  }

  // -- step 5: generate test cases for the selected requirements' accepted ideas
  async function generateForSelected() {
    await refreshWorkflow();
    const keys = WF.state.with_accepted;
    if (!keys.length) return stop("Accept at least one test idea of the selected requirements first.");
    if (WF.state.pending_reviews) return stop(`${plural(WF.state.pending_reviews, "idea")} still waiting: accept or reject them (or use Accept all / Reject all).`);
    const conns = await connOf(keys);
    const ids = [];
    for (const k of keys) {
      const r = await api(`/items/${encodeURIComponent(conns[k])}/${encodeURIComponent(k)}/test-cases`, { method: "POST" });
      r.test_cases.filter((c) => runnable(c)).forEach((c) => ids.push(c.id));
    }
    await saveDraft({ test_case_ids: ids, step: "builder" });
    X.selected = new Set(ids);
    location.hash = "#builder";
    return false;
  }
  $("rvGenerate").addEventListener("click", async () => { try { await generateForSelected(); } catch (e) { stop(e.message); } });
  async function bulkReview(answer) {
    const cards = (S.shownReviews || []).filter((x) => x.suggestion.review === "needs_review");
    const out = $("rvScope");
    let n = 0;
    for (const x of cards) {
      out.textContent = `${answer === "yes" ? "Accepting" : "Rejecting"} ${n + 1} of ${cards.length}…`;
      try {
        await api(`/items/${encodeURIComponent(x.connection_id)}/${encodeURIComponent(x.key)}/suggestions/${encodeURIComponent(x.suggestion.id)}/review`, { method: "POST", body: { answer } });
        n += 1;
      } catch (e) { out.textContent = e.message; return; }
    }
    reviews();
  }
  $("rvAcceptAll").addEventListener("click", () => bulkReview("yes"));
  $("rvRejectAll").addEventListener("click", () => bulkReview("no"));

  // -- step 7: the target of these requirements (found, several, or asked for) and its test account
  const TG = { cand: null, account: false };
  async function resolveTarget() {
    const box = $("tgBox");
    const reqs = [...new Set([...draftReqs(), ...draftCases().map((c) => c.replace(/^TC-/, "").replace(/-\d+$/, ""))])];
    if ($("exUrl").value && WF.draft.target_url === $("exUrl").value) return;
    const before = $("exUrl").value;
    try {
      const r = await api(`/targets/resolve?${new URLSearchParams({ requirements: reqs.join(","), environment: $("exEnv").value })}`);
      TG.projects = r.projects;
      if ($("exUrl").value !== before) {  // (typed while the answer was on its way: the person's address wins)
        box.replaceChildren(h("p", { class: "small", text: r.status === "not_found" ? "Using the address you entered." : `${r.message} Using the address you entered.` }));
        accountUi();
        return;
      }
      const pick = (c) => {
        if (c.kind && c.kind !== "web") {  // (an app / API / repository: not a website for this browser run)
          $("tgNote") && $("tgNote").remove();
          box.append(h("p", { class: "rq-issue", id: "tgNote", role: "status", text: `${c.url} is ${c.kind === "api" || c.kind === "openapi" ? "an API" : c.kind === "repository" ? "a code repository" : "a mobile app"} — tested with ${c.engine}. Jira executions here run in the browser: enter the website address below, or start this target from the Test studio.` }));
          return;
        }
        TG.cand = c; $("exUrl").value = c.url; TG.account = c.has_test_account;
        saveDraft({ target_url: c.url, target_source: c.sources[0] });
        accountUi();
      };
      if (WF.draft.target_url) {
        $("exUrl").value = WF.draft.target_url;
        const c = r.candidates.find((x) => x.url === WF.draft.target_url);
        TG.account = Boolean(c && c.has_test_account); TG.cand = c || null;
        box.replaceChildren(h("p", { class: "small" }, badge("chosen", "ok"), ` ${WF.draft.target_url} — ${WF.draft.target_source || (c ? c.sources[0] : "entered by you")}. You can change it below.`));
      } else if (r.status === "found") {
        const c = r.candidates.find((x) => x.authorized);
        pick(c);
        box.replaceChildren(h("p", { class: "small" }, badge("Target website found", "ok"), ` ${c.url} — from the ${c.sources.join("; ")}. You can change it below.`));
      } else if (r.status === "multiple") {
        box.replaceChildren(h("p", { class: "small", text: r.message }), h("div", { class: "rq-tg-cand", role: "radiogroup", "aria-label": "Possible websites" },
          r.candidates.map((c) => h("label", {}, h("input", { type: "radio", name: "tgPick", value: c.url, onchange: () => pick(c) }),
            h("span", {}, h("b", { text: c.url }), c.kind && c.kind !== "web" ? h("span", { class: "small", text: ` · ${c.engine}` }) : null, h("br"), h("small", { text: c.sources.join("; ") + (c.authorized ? "" : " — not yet confirmed: confirm the permission below") }))))),
        h("p", { class: "small", text: "Or type another address below." }));
        $("exUrl").value = "";
      } else {
        box.replaceChildren(h("p", { class: "rq-issue", role: "alert", text: "Target website not found. Please enter the website URL you want to test." }));
        $("exUrl").value = "";
      }
    } catch (e) { box.replaceChildren(h("p", { class: "small", text: e.message })); }
    accountUi();
  }
  function accountUi() {
    const same = TG.cand && TG.cand.url === $("exUrl").value.trim();
    const saved = Boolean(same && TG.account);
    $("tgAccount").replaceChildren(...kids(saved ? h("p", { class: "small" }, badge("saved test account", "ok"),
      " The project's saved test account for this website is used (encrypted; it is never shown). Type another below to use it instead.")
      : h("p", { class: "small", text: "If the website needs a login, give the test account (used for this run only; tick 'remember' to keep it encrypted for this project). A website without a login needs none." })));
  }
  $("exUrl").addEventListener("change", () => { $("tgCheckOut").textContent = ""; accountUi(); if (WF.draft) saveDraft({ target_url: $("exUrl").value.trim(), target_source: "entered by you" }); });
  async function checkTarget() {
    const out = $("tgCheckOut");
    const url = $("exUrl").value.trim();
    if (!url) { out.textContent = "Enter the website address first."; return null; }
    out.textContent = "Checking the website…";
    const r = await api("/targets/check", { method: "POST", body: { url } });
    out.replaceChildren(...kids(r.ok ? badge("reachable", "ok") : badge(r.kind.replace("_", " "), "bad"), ` ${r.message}`));
    return r;
  }
  $("tgCheck").addEventListener("click", () => checkTarget().catch((e) => { $("tgCheckOut").textContent = e.message; }));
  $("exEnv").addEventListener("change", () => { if (WF.draft) saveDraft({ environment: $("exEnv").value, target_url: "" }).then(() => resolveTarget()); });
  function execSummary() {
    const reqs = draftReqs(), cases = draftCases();
    const strategy = document.querySelector("input[name=exStrategy]:checked").value;
    $("exSelCount").textContent = cases.length;
    $("xcSummary").replaceChildren(...kids(
      strategy === "autonomous" ? h("p", { class: "small", text: "Autonomous testing: no Jira requirement is needed. Qpilot explores the application (website, app or API) and tests what it finds." })
        : [h("span", { class: "small", text: "Requirements:" }), reqs.length ? reqs.map((k) => h("span", { class: "rq-chip", text: k })) : h("a", { href: "#explorer", text: "choose requirements" }),
          h("span", { class: "small", text: "Test cases:" }), cases.length ? cases.map((c) => h("span", { class: "rq-chip", text: c })) : h("a", { href: "#builder", text: "select test cases" }),
          cases.length ? h("span", { class: "small", text: `(${plural(cases.length, "test case")}; criteria: ${(S.caseCriteria || []).join(", ") || "—"})` }) : null]));
  }

  // -- step 8: live execution (the run's real events, agents and screens; only the panels scroll)
  async function liveView() {
    await refreshWorkflow();
    let recent = [];
    try { recent = (await api("/executions?limit=20")).executions || []; } catch (e) { recent = []; }
    const active = recent.filter((x) => ["running", "queued"].includes(x.status));
    let id = (S.liveId && recent.some((x) => x.id === S.liveId) && S.liveId) || (WF.draft && WF.draft.execution_id) || "";
    if (!id) id = active.length ? active[0].id : "";
    const box = $("liveBox");
    // every other execution still running is one click away (another tab's run, a re-run started from Reports)
    const others = active.filter((x) => x.id !== id);
    $("liveOthers").replaceChildren(...kids(others.length ? h("p", { class: "small" }, "Also running: ",
      ...others.map((x) => h("button", { type: "button", class: "linklike", text: `${x.id} (${x.case_ids.length} test case(s))`,
        onclick: () => { S.liveId = x.id; liveView(); } }))) : null));
    if (!id) {
      $("liveCtrl").replaceChildren(h("button", { type: "button", class: "primary", "data-newtest": "", text: "+ New Test" }));
      box.replaceChildren(h("div", { class: "lab-card" }, h("p", { class: "small", text: "No test of this workflow is running." }), h("a", { href: "#execution", text: "Go to the Execution Center" })));
      return;
    }
    if (LV.id !== id) {
      Object.assign(LV, { id, job: null, cursor: "", follow: true, workers: [], seen: new Set(), frames: {}, framed: {}, shown: {} });
      box.replaceChildren(h("div", { class: "rq-live-grid" },
        h("section", { class: "rq-panel", "aria-labelledby": "lvScTitle" }, h("h2", { id: "lvScTitle", text: "Scenarios" }), h("div", { class: "rq-panel-body", id: "lvCases" })),
        h("section", { class: "rq-panel", "aria-labelledby": "lvBrTitle" }, h("h2", { id: "lvBrTitle" }, "Browser", h("span", { class: "small", id: "lvUrl" })), h("div", { class: "rq-panel-body rq-screen", id: "lvScreens" }, h("p", { class: "small", text: "The browser screen appears when the run opens the website." }))),
        h("section", { class: "rq-panel", "aria-labelledby": "lvAgTitle" }, h("h2", { id: "lvAgTitle", text: "Agents" }), h("div", { class: "rq-panel-body", id: "lvAgents" }))),
      h("div", { class: "rq-logwrap" }, h("section", { class: "rq-panel", "aria-labelledby": "lvLogTitle" },
        h("h2", { id: "lvLogTitle" }, "Activity log", h("label", { class: "rq-check small" }, h("input", { type: "checkbox", id: "lvFollow", checked: true, onchange: (e) => { LV.follow = e.target.checked; if (LV.follow) jumpLatest(); } }), " follow new events")),
        h("div", { class: "rq-panel-body", id: "lvLogBody", onscroll: logScrolled }, h("ul", { class: "rq-log", id: "lvLog" }))),
        h("button", { type: "button", class: "secondary rq-jump", id: "lvJump", hidden: true, text: "Jump to latest", onclick: () => { LV.follow = true; $("lvFollow").checked = true; jumpLatest(); } })));
    }
    liveTick();
  }
  function logScrolled() {
    const b = $("lvLogBody");
    const atBottom = b.scrollHeight - b.scrollTop - b.clientHeight < 24;
    if (!atBottom && LV.follow) { LV.follow = false; $("lvFollow").checked = false; }
    $("lvJump").hidden = atBottom;
  }
  function jumpLatest() { const b = $("lvLogBody"); if (b) { b.scrollTop = b.scrollHeight; $("lvJump").hidden = true; } }
  async function liveTick() {
    clearTimeout(LV.timer);
    if (S.view !== "agents" || !LV.id) return;
    const id = LV.id;
    try {
      const d = await api(`/executions/${encodeURIComponent(id)}`);
      if (LV.id !== id) return;  // (a newer test was started: this answer is old)
      const ex = d.execution, live = d.live || {};
      const running = ["running", "queued"].includes(ex.status);
      LV.job = ex.run_id;
      if (running && ex.run_id) livePause(ex.run_id);
      const counts = ex.counts || {};
      const t = ex.target || {}, ai = t.llm_provider ? `AI: ${t.llm_provider}${t.llm_model ? " " + t.llm_model : ""} · ` : "";
      const bs = ex.batches || [], bdone = bs.filter((b) => b.status === "done").length;
      const batchText = bs.length ? `batch ${Math.min(bdone + 1, bs.length)} of ${bs.length} (${bdone} done) · ` : "";
      if (ex.status === "interrupted") {
        $("livePause").hidden = false;
        $("livePause").replaceChildren(h("div", { class: "rq-issue", role: "alert" }, h("b", { text: "Interrupted — " }),
          `${bdone} of ${bs.length} batches are done; the rest can go on from where it stopped. `,
          h("label", { for: "resumePass", class: "small", text: "Test password (never stored)" }), h("input", { id: "resumePass", type: "password", autocomplete: "off" }),
          h("button", { type: "button", class: "secondary", text: "Resume", onclick: async () => {
            try { await api(`/executions/${encodeURIComponent(ex.id)}/resume`, { method: "POST", body: $("resumePass").value ? { test_password: $("resumePass").value } : {} }); $("resumePass").value = ""; } catch (err) { banner(err.message); }
          } })));
      }
      $("liveSub").replaceChildren(...kids(`${ex.id} · ${ex.strategy} · ${t.url || t.api_spec_url || t.package_name || ""} · ${ai}${batchText}`, outcomeBadge(ex),
        live.elapsed != null ? ` · ${live.elapsed} s` : "", live.current ? ` · now: ${live.current}` : "",
        !running && ex.tally ? h("span", { class: "small", text: ` · ${tallyText(ex)}` }) : null));
      $("liveCtrl").replaceChildren(...kids(h("span", { class: "rq-live-stats" }, ["Passed", "Failed", "Requires review", "Blocked", "Not automated", "Not run", "Cancelled"].filter((k) => counts[k]).map((k) => resultBadge(k) && h("span", {}, resultBadge(k), ` ${counts[k]}`)),
        running ? badge(`${ex.case_ids.length} scenario(s) in this run`, "info") : null),
        running ? h("button", { type: "button", class: "secondary", text: "Cancel", onclick: async () => { await api(`/executions/${encodeURIComponent(id)}/cancel`, { method: "POST" }); liveTick(); } }) : null,
        !running ? h("a", { class: "primary rq-action-link", href: "#reports", text: "View Report" }) : null,
        !running ? h("button", { type: "button", class: "secondary", "data-newtest": "", text: "+ New Test" }) : null));
      const byCase = Object.fromEntries((d.results || []).map((r) => [r.test_case_id, r]));
      const testing = /^(execution|self_healing)$/.test(live.current || "");  // (exploring first: the cases wait)
      $("lvCases").replaceChildren(h("ul", { class: "rq-audit" }, ex.case_ids.map((c) => h("li", {}, h("b", { text: c }),
        byCase[c] ? resultBadge(byCase[c].status) : badge(!running ? "—" : testing ? "running" : `waiting (${live.current || "starting"})`, "info"),
        byCase[c] && (byCase[c].actual || byCase[c].reason) ? h("span", { class: "small", text: byCase[c].actual || byCase[c].reason }) : null))));
      if (LV.job && /^\d+$/.test(String(LV.job))) await liveRun(LV.job, running);
      if (running) LV.timer = setTimeout(liveTick, 1500);
      else refreshWorkflow();
    } catch (e) { $("liveSub").textContent = e.message; LV.timer = setTimeout(liveTick, 4000); }
  }
  async function liveRun(job, running) {
    try {
      const ev = await api(`/api/runs/${job}/events?${new URLSearchParams({ after: LV.cursor, limit: 300 })}`);
      const log = $("lvLog"), body = $("lvLogBody");
      const stick = LV.follow && body.scrollHeight - body.scrollTop - body.clientHeight < 24;
      for (const e of ev.events || []) {
        if (LV.seen.has(e.id)) continue;
        LV.seen.add(e.id);
        log.append(h("li", { class: e.status }, `${new Date(e.timestamp * 1000).toLocaleTimeString()} ${e.worker} · ${e.test} · ${e.text} (${e.status})`));
        if (e.url && e.url !== "about:blank") $("lvUrl").textContent = ` · ${e.url}`;
        if (e.worker && e.worker !== "main" && e.frame != null) {  // (the worker saved a real screen with this event)
          if (!LV.workers.includes(e.worker)) LV.workers.push(e.worker);
          LV.framed[e.worker] = e.id;
        }
      }
      while (log.children.length > 2000) log.firstChild.remove();  // (thousands of events: keep the page fast)
      if (ev.cursor) LV.cursor = ev.cursor;
      if (stick || (LV.follow && (ev.events || []).length)) jumpLatest();
      else if ((ev.events || []).length) $("lvJump").hidden = false;
    } catch (e) { /* (events start once the run has a folder) */ }
    try {
      const ag = await api(`/api/runs/${job}/agents`);
      $("lvAgents").replaceChildren(h("ul", { class: "rq-audit" }, (ag.agents || []).map((a) => h("li", {}, h("b", { text: a.name }),
        badge(a.status, { completed: "ok", running: "info", failed: "bad", skipped: "" }[a.status] || ""), a.detail ? h("span", { class: "small", text: a.detail }) : null))));
    } catch (e) { /* (no agents yet) */ }
    // every browser of the run that saved a real screen (explorers, learners, test workers gw0..): a screen is
    // reloaded only when its file changed; test workers come first
    let frames = [];
    try { frames = (await api(`/api/runs/${job}/live`)).frames || []; } catch (e) { frames = []; }
    const rank = (w) => (/^gw\d+$/.test(w) ? 0 : /^explorer/.test(w) ? 1 : 2);
    frames.sort((a, b) => rank(a.worker) - rank(b.worker) || a.worker.localeCompare(b.worker, undefined, { numeric: true }));
    for (const { worker: w, updated } of frames) {
      if (LV.shown[w] === updated) continue;
      LV.shown[w] = updated;
      try {
        const res = await fetch(`/api/runs/${job}/live/${encodeURIComponent(w)}?v=${updated}`, { headers: { "X-Agentic-QA": "1", ...(S.auth ? { Authorization: `Bearer ${S.auth}` } : {}) } });
        if (!res.ok) continue;
        const url = URL.createObjectURL(await res.blob());
        if (LV.frames[w]) URL.revokeObjectURL(LV.frames[w].src);
        if (!LV.frames[w]) {
          const img = h("img", { alt: `Live screen of ${w}` });
          LV.frames[w] = img;
          if ($("lvScreens").querySelector("p")) $("lvScreens").replaceChildren();
          const fig = h("figure", { "data-worker": w }, img, h("figcaption", { text: w === "device" ? "device — the app's screen on the simulator / device" : `${w} — ${/^gw\d+$/.test(w) ? "test browser" : "exploring browser"} of the run` }));
          const after = [...$("lvScreens").querySelectorAll("figure")].find((f) => rank(f.dataset.worker) > rank(w));
          $("lvScreens").insertBefore(fig, after || null);
        }
        LV.frames[w].src = url;
      } catch (e) { /* (no screen yet) */ }
    }
  }

  // -- step 9: reports of real executions (kept; never overwritten), coverage and history
  async function reportsView() {
    await refreshWorkflow();
    const r = await api("/executions?limit=50");
    const finished = r.executions;
    const id = S.reportId || (WF.draft && WF.draft.execution_id) || (finished.find((x) => !["running", "queued"].includes(x.status)) || {}).id;
    $("rpHistory").tBodies[0].replaceChildren(...kids(finished.map((ex) => h("tr", { class: ex.id === id ? "current" : "" },
      h("td", {}, h("button", { class: "rq-open", type: "button", text: ex.id, onclick: () => { S.reportId = ex.id; reportsView(); } })),
      h("td", { text: ex.strategy }), h("td", { text: (ex.target || {}).url || "" }), h("td", { text: ex.case_ids.length }),
      h("td", {}, statusBadge({ finished: "complete", running: "running", queued: "running", stopped: "cancelled", failed: "failed" }[ex.status] || ex.status)),
      h("td", { text: Object.entries(ex.counts || {}).map(([k, v]) => `${v} ${k}`).join(" · ") || "—" }),
      h("td", { text: when(ex.created_at) }), h("td", { text: ex.finished_at && ex.created_at ? `${Math.round((new Date(ex.finished_at) - new Date(ex.created_at)) / 1000)} s` : "—" })))));
    if (!finished.length) $("rpHistory").tBodies[0].append(h("tr", {}, h("td", { colspan: 8, class: "rq-empty", text: "No executions yet." })));
    coverageView();
    if (!id) { $("rpBox").replaceChildren(h("div", { class: "lab-card" }, h("p", { class: "small", text: "No execution yet: a report appears after a test has run." }), h("a", { href: "#execution", text: "Go to the Execution Center" }))); return; }
    const d = await api(`/executions/${encodeURIComponent(id)}`);
    const ex = d.execution, res = d.results || [];
    const count = (s) => res.filter((x) => x.status === s).length;
    const reqs = [...new Set(ex.case_ids.map((c) => c.replace(/^TC-/, "").replace(/-\d+$/, "")))];
    let trace = [], defects = [];
    try { trace = (await api("/traceability")).rows.filter((x) => reqs.includes(x.requirement)); } catch (e) { /* (shown as none) */ }
    try { defects = (await api("/defects")).defects.filter((x) => ex.case_ids.includes(x.test_case_id)); } catch (e) { /* (shown as none) */ }
    const run = (res.find((x) => x.run_folder) || {}).run_folder || "";
    const shots = res.flatMap((x) => (x.evidence || []).filter((e) => /\.(png|jpe?g)$/i.test(e)).map((e) => ({ e, x })));
    const tile = (n, label, kind = "") => h("div", { class: `rq-stat ${kind}` }, h("b", { text: n }), h("span", { text: label }));
    const failedIds = res.filter((x) => ["Failed", "Blocked", "Flaky"].includes(x.status)).map((x) => x.test_case_id);
    $("rpBox").replaceChildren(...kids(h("section", { class: "lab-card" },
      h("div", { class: "rq-head-row" }, h("div", {}, h("h2", { class: "rq-sub", text: `${ex.id} — ${ex.strategy}` }),
        h("p", { class: "small", text: `${(ex.target || {}).url || ""} · started ${when(ex.created_at)}${ex.finished_at ? ` · ended ${when(ex.finished_at)}` : ""} · by ${ex.actor} · ${reqs.join(", ")}` })),
        h("div", { class: "rq-row" },
          h("button", { type: "button", class: "secondary", text: "Rerun Failed Tests", disabled: !failedIds.length, onclick: async () => { await saveDraft({ test_case_ids: failedIds, execution_id: "" }); S.presetScope = "selected"; location.hash = "#execution"; } }),
          h("button", { type: "button", class: "secondary", text: "Run Impacted Tests", onclick: () => { S.presetScope = "impacted"; location.hash = "#execution"; } }),
          h("button", { type: "button", class: "secondary", text: "Export Report", onclick: () => {
            const blob = new Blob([JSON.stringify({ execution: ex, results: res, traceability: trace, defects }, null, 2)], { type: "application/json" });
            const a = h("a", { href: URL.createObjectURL(blob), download: `${ex.id}-report.json` }); document.body.append(a); a.click(); a.remove(); } }),
          h("a", { href: "#rpHistTitle", class: "secondary rq-action-link", text: "View Execution History" }))),
      ex.outcome === "no_tests_automated" ? h("p", { class: "rq-issue", role: "alert", text: "Execution unsuccessful — no tests were automated. Nothing was verified on the website: see the reason of each test case below." }) : null,
      h("div", { class: "rq-stats" }, tile((ex.tally || {}).selected ?? 0, "selected"), tile((ex.tally || {}).executed ?? 0, "actually executed"),
        tile(count("Passed") + count("Flaky"), "passed", "ok"), tile(count("Failed"), "failed", count("Failed") ? "bad" : ""),
        tile(count("Requires review"), "requires review (the test failed, not the website)", count("Requires review") ? "info" : ""),
        tile(count("Blocked"), "blocked", count("Blocked") ? "warn" : ""), tile(count("Not automated"), "not automated", count("Not automated") ? "bad" : ""),
        tile(count("Not run") + count("Cancelled") + count("Skipped"), "skipped / not run", ""),
        tile((ex.exploratory || {}).cases || 0, "exploratory (not from requirements)")),
      h("p", { class: "small", text: `Automation coverage ${ex.automation_coverage ?? 0}% of the selected test cases · pass rate ${ex.pass_rate == null ? "— (nothing executed)" : `${ex.pass_rate}% of the executed ones`}` }),
      h("div", { class: "rq-table-wrap" }, h("table", { class: "rq-table" }, h("caption", { class: "rq-sr", text: "Results per test case" }),
        h("thead", {}, h("tr", {}, ["Test case", "Requirement", "Result", "Assertions", "Actual result / reason", "Evidence"].map((text) => h("th", { scope: "col", text })))),
        h("tbody", {}, res.map((x) => {
          const row = trace.find((t) => t.test_case === x.test_case_id) || {};
          return h("tr", {}, h("td", {}, h("button", { class: "rq-open", type: "button", text: x.test_case_id, onclick: () => tcDetail(x.test_case_id) })),
            h("td", { text: row.requirement ? `${row.requirement} ${String(row.criterion || "").split("#")[1] || ""}` : "" }),
            h("td", {}, resultBadge(x.status)),
            h("td", { text: x.checks ? `${x.checks} check(s); expected: ${x.expected || "—"}` : x.expected || "—" }),
            h("td", { text: x.actual || x.reason || "" }), h("td", {}, ...evidenceLinks(x)));
        })))),
      shots.length ? h("div", {}, h("h3", { class: "rq-sub", text: "Screenshots" }), h("div", { class: "rq-rp-shots" }, shots.slice(0, 12).map(({ e, x }) => h("a", { href: `/runs/${encodeURIComponent(x.run_folder)}/${e.split("/").map(encodeURIComponent).join("/")}`, target: "_blank", rel: "noopener" },
        h("img", { src: `/runs/${encodeURIComponent(x.run_folder)}/${e.split("/").map(encodeURIComponent).join("/")}`, alt: `${x.test_case_id} ${x.status}`, loading: "lazy" }))))) : null,
      h("p", { class: "small" }, run ? h("span", {}, h("a", { href: `/runs/${encodeURIComponent(run)}/report.html`, target: "_blank", rel: "noopener", text: "Full Qpilot report (logs, traces, all checks)" }), " · ") : null,
        h("a", { href: "#traceability", text: `Traceability (${trace.length} row(s))` }), " · ",
        h("a", { href: "#writeback", text: `Defects (${defects.length})` }), defects.length ? ` — ${defects.map((x) => `${x.id} ${x.status}`).join(", ")}` : ""))));
  }

  // -- New Test: a fresh draft; reports, requirements and test cases are kept
  document.addEventListener("click", (e) => { const b = e.target.closest("[data-newtest]"); if (b) { e.preventDefault(); openNewTest(); } });
  async function openNewTest() {
    const box = $("ntRunning");
    box.hidden = true;
    try {
      const r = await api("/executions?limit=10");
      const run = r.executions.find((x) => ["running", "queued"].includes(x.status));
      if (run) {
        box.hidden = false;
        box.replaceChildren(h("b", { text: `${run.id} is still running. ` }), "It keeps running while you start a new test. ",
          h("a", { href: "#agents", text: "Continue watching it", onclick: async () => { $("newTest").close(); await saveDraft({ execution_id: run.id }); } }), " · ",
          h("button", { type: "button", class: "secondary", text: "Cancel it", onclick: async () => { await api(`/executions/${encodeURIComponent(run.id)}/cancel`, { method: "POST" }); box.textContent = `${run.id} is being cancelled.`; } }));
      }
    } catch (e) { /* (the choices still work) */ }
    $("newTest").showModal();
  }
  document.querySelectorAll("[data-nt]").forEach((b) => b.addEventListener("click", async () => {
    const kind = b.dataset.nt;
    if (kind === "android") { location.href = "/?target=android"; return; }
    const old = WF.draft || {};
    const start = { existing: { step: "explorer" }, import: { step: "import" },
      website: { step: "execution", requirement_ids: old.requirement_ids || [], test_case_ids: old.test_case_ids || [] },
      autonomous: { step: "execution", strategy: "autonomous" }, hybrid: { step: "explorer", strategy: "hybrid" } }[kind];
    const r = await api("/workflow/new", { method: "POST", body: { changes: start } });
    WF.draft = r.draft; WF.state = r.state; WF.steps = r.steps;
    X.selected = new Set(start.test_case_ids || []); S.reportId = null; S.presetScope = null;
    Object.assign(LV, { id: "", job: null, cursor: "", workers: [], seen: new Set(), frames: {}, framed: {}, shown: {} });
    TG.cand = null; $("exUrl").value = ""; $("exUser").value = ""; $("exPass").value = ""; $("exAuth").checked = false; $("exDemo").checked = false; $("exPayProvider").value = ""; $("exPayConfirm").checked = false;
    $("tgCheckOut").textContent = ""; $("xcStatus").textContent = ""; $("exDetail").replaceChildren();
    $("newTest").close();
    banner(`New test started (${r.draft.id}). Earlier reports are kept in Reports.`, true);
    const hash = `#${STEP_VIEW[start.step] || start.step}`;
    if (location.hash === hash) route(); else location.hash = hash;
  }));

  // ---------------------------------------------------------------- start
  async function start() {
    try {
      S.caps = await api("/capabilities");
      $("who").textContent = `Signed in as ${S.caps.actor}${S.caps.tenant !== "local" ? " · " + S.caps.tenant : ""}`;
      try {  // (which code this Studio runs - an old checkout / a server not restarted shows here)
        const v = await (await fetch("/api/version", { headers: { "X-Agentic-QA": "1" } })).json();
        if (v.commit) $("who").textContent += ` · build ${v.branch ? v.branch + " " : ""}${v.commit}`;
      } catch (_) { /* (an older server has no version) */ }
    } catch (e) { if (e.status !== 401) banner(e.message); return; }
    await refreshWorkflow();
    route();
  }
  start();
})();
