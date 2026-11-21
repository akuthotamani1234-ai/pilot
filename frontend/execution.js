/* Durable action history: outcomes always come from the server. */
(() => {
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
  let current = null, cursor = "", busy = false, generation = 0, rows = [], seen = new Set(), pending = null, showAll = false, declaredWorkers = 0;
  function panel() {
    let node = document.getElementById("qpilotLive");
    if (node) return node;
    node = document.createElement("section");
    node.id = "qpilotLive";
    node.className = "live-workspace";
    node.setAttribute("aria-label", "Live execution");
    document.getElementById("thread")?.prepend(node);
    node.innerHTML = '<div class="live-heading"><div><span class="eyebrow">LIVE EXECUTION</span>' +
      '<h2>See every action</h2></div><span id="livePhase" class="status-chip">Preparing</span></div>' +
      '<p id="liveCurrent" role="status" aria-live="polite">Preparing the test environment…</p><p id="liveExpected" class="live-explanation"></p>' +
      '<p id="liveMode" class="live-explanation"></p>' +
      '<section id="liveSwarm" class="live-swarm" hidden aria-labelledby="liveSwarmTitle">' +
      '<div class="live-swarm-head"><div><span class="eyebrow">SWARM VIEW</span><h3 id="liveSwarmTitle">Parallel workers</h3></div>' +
      '<span id="liveSwarmCount" class="status-chip">0 workers</span></div>' +
      '<p class="live-swarm-note">Each cursor marks the most recent visible action target recorded by that browser worker.</p>' +
      '<div id="liveSwarmGrid" class="live-swarm-grid" aria-live="polite"></div></section>' +
      '<div class="live-toolbar"><button id="liveFollow" type="button" class="secondary" aria-pressed="true">Following latest</button>' +
      '<span id="liveCount">0 recorded events</span></div>' +
      '<ol id="liveTimeline" class="live-timeline" aria-label="Recorded actions"></ol>' +
      '<button id="liveEarlier" type="button" class="secondary" hidden>Show earlier events</button>' +
      '<p id="liveConnection" class="muted small" role="status"></p>';
    node.querySelector("#liveFollow").onclick = (event) => {
      const following = event.currentTarget.getAttribute("aria-pressed") !== "true";
      event.currentTarget.setAttribute("aria-pressed", String(following));
      event.currentTarget.textContent = following ? "Following latest" : "Follow latest";
    };
    node.querySelector("#liveEarlier").onclick = () => { showAll = true; render(); };
    return node;
  }
  function render() {
    const node = panel(), list = node.querySelector("#liveTimeline");
    const following = node.querySelector("#liveFollow").getAttribute("aria-pressed") === "true";
    const previous = list.scrollTop;
    list.innerHTML = (showAll ? rows : rows.slice(-200)).map((event) =>
      `<li class="event-${esc(event.status)}"><span class="event-state">${esc(event.status)}</span>` +
      `<div><b>${esc(event.text)}</b><small>${esc(event.case_title || event.test)} · ${esc(event.worker)} · ${esc(event.elapsed)}s</small>` +
      `${event.url ? `<small>${esc(event.url)}</small>` : ""}` +
      `${event.expected ? `<small>Expected: ${esc(event.expected)}</small>` : ""}` +
      `${event.observed ? `<small>Observed: ${esc(event.observed)}</small>` : ""}` +
      `${event.selector ? `<details><summary>Target details</summary><code>${esc(event.selector)}</code></details>` : ""}</div></li>`).join("");
    node.querySelector("#liveCount").textContent = `${rows.length} recorded events`;
    node.querySelector("#liveEarlier").hidden = showAll || rows.length <= 200;
    list.scrollTop = following ? list.scrollHeight : previous;
    const last = rows[rows.length - 1];
    if (last) node.querySelector("#liveCurrent").textContent = `${last.text} — ${last.status}`;
    node.querySelector("#liveExpected").textContent = last?.expected ? `Expected: ${last.expected}` : "";
    renderSwarm(node);
  }
  function workerKey(value) {
    const name = String(value || "").trim();
    return name && name !== "main" ? name : "";
  }
  function workerName(key) {
    const match = /^gw(\d+)$/i.exec(key);
    return match ? `Worker ${Number(match[1]) + 1}` : `Worker ${key}`;
  }
  function workerSlots(events) {
    const names = [...new Set(events.map((event) => workerKey(event.worker)).filter(Boolean))];
    const pytestWorkers = names.filter((name) => /^gw\d+$/i.test(name));
    if (declaredWorkers > 1 && (pytestWorkers.length || !names.length)) {
      for (let i = 0; i < declaredWorkers; i += 1) {
        const key = `gw${i}`;
        if (!names.includes(key)) names.push(key);
      }
    }
    return names;
  }
  function renderSwarm(node) {
    const latest = new Map(), positions = new Map();
    rows.forEach((event) => {
      const key = workerKey(event.worker);
      if (key) {
        latest.set(key, event);
        if (positions.get(key)?.url !== event.url) positions.delete(key);
        if (Array.isArray(event.point) && event.point.length === 2 &&
            event.point.every((n) => Number.isFinite(n) && n >= 0 && n <= 100)) positions.set(key, event);
      }
    });
    const slots = workerSlots(rows);
    const stage = node.querySelector("#liveSwarm");
    if (slots.length < 2) { stage.hidden = true; return; }
    stage.hidden = false;
    node.querySelector("#liveSwarmCount").textContent = `${slots.length} workers`;
    node.querySelector("#liveSwarmGrid").innerHTML = slots.map((key) => {
      const event = latest.get(key);
      const state = String(event?.status || "waiting").toLowerCase();
      const active = event && /running|started|pending/.test(state);
      const action = event?.text || "Waiting for an assigned test";
      const page = event?.url || event?.case_title || event?.test || "No action recorded yet";
      const point = positions.get(key)?.point;
      const cursor = point ? `<span class="swarm-cursor" style="--cursor-x:${point[0]}%;--cursor-y:${point[1]}%" aria-hidden="true">➤</span>` : "";
      return `<article class="swarm-worker swarm-${esc(state)}${active ? " is-active" : ""}">` +
        `<div class="swarm-worker-head"><b>${esc(workerName(key))}</b><span>${esc(state)}</span></div>` +
        `<div class="swarm-browser"><span class="swarm-address">${esc(page)}</span>` +
        cursor +
        `<span class="swarm-action">${esc(action)}</span></div></article>`;
    }).join("");
  }
  async function poll(job, token) {
    if (busy) { pending = job; return; }
    busy = true;
    try {
      let count;
      do {
        const response = await fetch(`/api/runs/${job.id}/events?after=${encodeURIComponent(cursor)}`);
        if (!response.ok) throw new Error(`Progress connection: HTTP ${response.status}`);
        const data = await response.json();
        if (token !== generation) return;
        cursor = data.cursor;
        count = data.events.length;
        for (const event of data.events) {
          if (!seen.has(event.id)) { seen.add(event.id); rows.push(event); }
        }
        render();
        panel().querySelector("#liveConnection").textContent = count ? "Progress saved locally." :
          "Connected. Waiting for the next action; the current action may still be running.";
      } while (count === 150 && token === generation);
    } catch (error) {
      if (token === generation) panel().querySelector("#liveConnection").textContent =
        `${error.message}. History is retained; reconnecting on the next update.`;
    } finally {
      busy = false;
      if (pending) { const next = pending; pending = null; poll(next, generation); }
    }
  }
  window.QpilotLive = {
    update(job) {
      if (current !== job.id) {
        current = job.id; cursor = ""; rows = []; seen = new Set(); showAll = false; declaredWorkers = 0; generation++;
        document.getElementById("qpilotLive")?.remove();
      }
      for (const line of (job.lines || [])) {
        const match = String(line).match(/\[discovery\] swarm: (\d+) workers\b|\[discovery\] swarm chose \d+ of \d+ products \((\d+) workers\)/);
        if (match) declaredWorkers = Math.max(declaredWorkers, Number(match[1] || match[2] || 0));
      }
      const node = panel();
      node.querySelector("#liveMode").textContent = job.target_type === "android" ?
        "Android actions are saved as they execute. Form input values are hidden. A completed action does not by itself prove the scenario passed." :
        "Watch: one visible Chrome window, one action at a time. Fast: isolated hidden workers.";
      node.querySelector("#livePhase").textContent = job.status === "running" ?
        (job.current || "Preparing").replaceAll("_", " ") : `Process ${job.status}`;
      if (job.id) poll(job, generation);
    },
    reset() { current = null; pending = null; generation++; document.getElementById("qpilotLive")?.remove(); }
  };
})();
