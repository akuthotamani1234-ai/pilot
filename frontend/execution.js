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
      '<p class="live-swarm-note">Each screen is that browser\'s latest real screenshot. Its cursor sits where that browser last acted, taken at the same moment.</p>' +
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
    const explorer = /^explorer-(\d+)$/i.exec(key);
    return match ? `Agent ${Number(match[1]) + 1}` : explorer ? `Explorer ${explorer[1]}` : `Worker ${key}`;
  }
  // The role of the task a worker is doing right now, from the kind of test it runs (or the event's own role).
  function roleOf(event) {
    if (!event) return "";
    if (event.role) return event.role;
    const file = String(event.nodeid || "").split("::")[0], name = String(event.test || "");
    if (/invalid|negative|wrong|unusual|boundary|empty|too_long/i.test(name)) return "Negative";
    if (/test_all_links/.test(file)) return "Explorer";
    if (/test_(checks|mobile|site|a11y|visual|perf|security|locale)/.test(file)) return "Quality";
    if (/test_(api|schema)/.test(file)) return "API";
    if (/test_(journeys|learned|forms|features|my_tests|ai_)/.test(file)) return "Functional";
    return "Tester";
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
    // One phase at a time: the explorers while discovering, the test agents once tests run.
    let slots = workerSlots(rows);
    const testing = slots.filter((key) => /^gw\d+$/i.test(key));
    slots = (testing.length ? testing : slots).sort((a, b) => a.localeCompare(b, undefined, {numeric: true}));
    const stage = node.querySelector("#liveSwarm");
    if (slots.length < 2) { stage.hidden = true; return; }
    stage.hidden = false;
    node.querySelector("#liveSwarmTitle").textContent = testing.length ? "Test agents working at once" :
      "Explorers discovering at once";
    node.querySelector("#liveSwarmCount").textContent = `${slots.length} live browsers`;
    const grid = node.querySelector("#liveSwarmGrid");
    [...grid.children].forEach((card) => { if (!slots.includes(card.dataset.key)) card.remove(); });
    slots.forEach((key, index) => {
      let card = grid.querySelector(`[data-key="${CSS.escape(key)}"]`);
      if (!card) {
        card = document.createElement("article");
        card.dataset.key = key;
        card.innerHTML = `<div class="swarm-worker-head"><b><i class="swarm-dot"></i><span class="swarm-name"></span>` +
          `<em class="swarm-role"></em></b><span class="swarm-state"></span></div>` +
          `<div class="swarm-browser"><div class="swarm-stage"><img class="swarm-screen" alt="" hidden>` +
          `<span class="swarm-ring" hidden></span>` +
          `<span class="swarm-cursor" hidden aria-hidden="true"><svg viewBox="0 0 16 20" width="18" height="22">` +
          `<path d="M1 1 L1 16 L5 12 L8 19 L11 17.6 L8 11 L14 11 Z" /></svg><span class="swarm-tag"></span></span></div>` +
          `<span class="swarm-address"></span><span class="swarm-action"></span></div>`;
        grid.append(card);
      }
      const event = latest.get(key);
      const state = String(event?.status || "waiting").toLowerCase();
      const active = event && /running|started|pending/.test(state);
      const role = roleOf(event);
      card.className = `swarm-worker swarm-c${index % 6} swarm-${state.replace(/[^a-z]/g, "")}${active ? " is-active" : ""}`;
      card.querySelector(".swarm-name").textContent = workerName(key);
      card.querySelector(".swarm-role").textContent = role ? ` · ${role}` : "";
      card.querySelector(".swarm-state").textContent = state;
      card.querySelector(".swarm-address").textContent = event?.url || event?.case_title || "No action recorded yet";
      card.querySelector(".swarm-action").textContent = event?.text || "Waiting for an assigned task";
      // The newest real screenshot this worker saved; reloaded only when the worker recorded a new frame.
      const framed = [...rows].reverse().find((e) => workerKey(e.worker) === key && e.frame != null) || event;
      const version = framed ? `${framed.id}` : "";
      const img = card.querySelector(".swarm-screen");
      if (current && version && img.dataset.version !== version) {
        img.dataset.version = version;
        const next = new Image();
        next.onload = () => { img.src = next.src; img.hidden = false; card.classList.add("has-screen"); };
        next.src = `/api/runs/${encodeURIComponent(current)}/live/${encodeURIComponent(key)}?v=${encodeURIComponent(version)}`;
      }
      const point = positions.get(key)?.point;
      const pointer = card.querySelector(".swarm-cursor"), ring = card.querySelector(".swarm-ring");
      card.querySelector(".swarm-tag").textContent = `${workerName(key)}${role ? " · " + role : ""}`;
      pointer.hidden = ring.hidden = !point;
      pointer.classList.toggle("flip-x", Boolean(point && point[0] > 62));
      pointer.classList.toggle("flip-y", Boolean(point && point[1] > 82));
      if (point) {
        for (const el of [pointer, ring]) { el.style.setProperty("--cursor-x", `${point[0]}%`); el.style.setProperty("--cursor-y", `${point[1]}%`); }
      }
    });
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
