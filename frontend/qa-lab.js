"use strict";
const byId = (id) => document.getElementById(id);

function setStatus(message, { busy = false, alert = false } = {}) {
  const status = byId("status");
  status.textContent = message;
  status.setAttribute("role", alert ? "alert" : "status");
  if (busy) status.setAttribute("aria-busy", "true");
  else status.removeAttribute("aria-busy");
}

async function refresh() {
  const runs = byId("runs");
  const refreshBtn = byId("refresh");
  refreshBtn.disabled = true;
  refreshBtn.setAttribute("aria-busy", "true");
  runs.setAttribute("aria-busy", "true");
  setStatus("Loading completed runs…", { busy: true });
  try {
    const response = await fetch("/api/history");
    if (!response.ok) throw new Error("Could not read completed runs. Check that the UI server is running.");
    const items = await response.json();
    runs.replaceChildren();
    if (!Array.isArray(items) || !items.length) {
      const option = document.createElement("option");
      option.disabled = true;
      option.value = "";
      option.textContent = "No completed runs yet — finish a test in Test studio first.";
      runs.append(option);
      setStatus("No completed runs available yet. Run a test, then refresh this list.");
    } else {
      for (const run of items) {
        const option = document.createElement("option");
        option.value = run.run;
        // textContent keeps run ids and verdicts from becoming HTML.
        option.textContent = `${run.run} | ${run.verdict}`;
        runs.append(option);
      }
      setStatus(`${items.length} completed run(s) loaded. Select runs for a condition.`);
    }
  } catch (error) {
    runs.replaceChildren();
    const option = document.createElement("option");
    option.disabled = true;
    option.value = "";
    option.textContent = "Could not load runs";
    runs.append(option);
    setStatus(error.message || "Could not read completed runs.", { alert: true });
  } finally {
    runs.removeAttribute("aria-busy");
    refreshBtn.disabled = false;
    refreshBtn.removeAttribute("aria-busy");
  }
}

byId("refresh").addEventListener("click", refresh);
byId("add").addEventListener("click", () => {
  try {
    const manifest = JSON.parse(byId("manifest").value);
    if (!manifest || !Array.isArray(manifest.groups)) throw new Error("Manifest must be JSON with a groups array.");
    const expected = JSON.parse(byId("expected").value);
    const runs = Array.from(byId("runs").selectedOptions, (option) => option.value).filter(Boolean);
    const name = byId("condition").value.trim();
    if (!name || !runs.length || !Object.keys(expected || {}).length) {
      throw new Error("Enter a condition name, select one or more completed runs, and supply known expected outcomes as JSON.");
    }
    manifest.groups.push({ name, runs, expected });
    byId("manifest").value = JSON.stringify(manifest, null, 2);
    setStatus("Condition added. Review the manifest before building.");
  } catch (error) {
    setStatus(
      error instanceof SyntaxError
        ? "Expected outcomes and the manifest must be valid JSON objects."
        : (error.message || "Could not add this condition."),
      { alert: true },
    );
  }
});
byId("build").addEventListener("click", async () => {
  const build = byId("build");
  build.disabled = true;
  build.setAttribute("aria-busy", "true");
  byId("report").hidden = true;
  setStatus("Building evidence report…", { busy: true });
  try {
    const manifest = JSON.parse(byId("manifest").value);
    if (!manifest.groups || !manifest.groups.length) {
      throw new Error("Add at least one condition before building the evidence report.");
    }
    const response = await fetch("/api/qa/benchmark", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Agentic-QA": "1" },
      body: JSON.stringify(manifest),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "The benchmark could not be built.");
    byId("report").href = result.report;
    byId("report").hidden = false;
    const unstable = (result.measurement && result.measurement.unstable_cases) || [];
    setStatus(`Evidence presentation ready. ${unstable.length} unstable repeated case(s).`);
  } catch (error) {
    setStatus(
      error instanceof SyntaxError
        ? "The manifest must be valid JSON before building."
        : (error.message || "The benchmark could not be built."),
      { alert: true },
    );
  } finally {
    build.disabled = false;
    build.removeAttribute("aria-busy");
  }
});
refresh();
