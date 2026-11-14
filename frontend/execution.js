/* Durable action history: outcomes always come from the server. */
(() => {
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
  let current = null, cursor = "", busy = false, generation = 0, rows = [], seen = new Set(), pending = null, showAll = false;
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
        current = job.id; cursor = ""; rows = []; seen = new Set(); showAll = false; generation++;
        document.getElementById("qpilotLive")?.remove();
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
