"use strict";
const byId = (id) => document.getElementById(id);
async function refresh() {
  try {
    const response = await fetch("/api/history");
    if (!response.ok) throw new Error("Could not read completed runs.");
    const runs = await response.json();
    byId("runs").replaceChildren();
    for (const run of runs) {
      const option = document.createElement("option");
      option.value = run.run;
      option.textContent = `${run.run} | ${run.verdict}`;
      byId("runs").append(option);
    }
  } catch (error) { byId("status").textContent = error.message; }
}
byId("refresh").addEventListener("click", refresh);
byId("add").addEventListener("click", () => {
  try {
    const manifest = JSON.parse(byId("manifest").value);
    const expected = JSON.parse(byId("expected").value);
    const runs = Array.from(byId("runs").selectedOptions, (option) => option.value);
    const name = byId("condition").value.trim();
    if (!name || !runs.length || !Object.keys(expected).length) throw new Error("Enter a condition, select its runs and supply known expectations.");
    manifest.groups.push({ name, runs, expected });
    byId("manifest").value = JSON.stringify(manifest, null, 2);
    byId("status").textContent = "Condition added. Review the manifest before building.";
  } catch (error) { byId("status").textContent = error.message; }
});
byId("build").addEventListener("click", async () => {
  byId("build").disabled = true;
  byId("report").hidden = true;
  try {
    const manifest = JSON.parse(byId("manifest").value);
    const response = await fetch("/api/qa/benchmark", { method: "POST", headers: { "Content-Type": "application/json", "X-Agentic-QA": "1" }, body: JSON.stringify(manifest) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "The benchmark could not be built.");
    byId("report").href = result.report;
    byId("report").hidden = false;
    byId("status").textContent = `Evidence presentation ready. ${result.measurement.unstable_cases.length} unstable repeated cases.`;
  } catch (error) { byId("status").textContent = error.message; }
  finally { byId("build").disabled = false; }
});
refresh();
