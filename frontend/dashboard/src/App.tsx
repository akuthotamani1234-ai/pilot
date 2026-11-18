import { useEffect, useState } from "react";
import { loadBlueprint, loadReadiness, type BlueprintProgress, type EnterpriseReadiness } from "./api";

function badge(status: string): string {
  if (status === "strong" || status === "done") return "done";
  if (status === "active") return "now";
  if (status === "partial") return "partial";
  return "next";
}

export function App() {
  const [blueprint, setBlueprint] = useState<BlueprintProgress | null>(null);
  const [readiness, setReadiness] = useState<EnterpriseReadiness | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [bp, ready] = await Promise.all([loadBlueprint(), loadReadiness()]);
        if (cancelled) return;
        setBlueprint(bp);
        setReadiness(ready);
        setError("");
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="shell">
      <header className="hero">
        <p className="brand">Qpilot</p>
        <h1>Enterprise readiness</h1>
        <p className="lede">
          React/TypeScript dashboard for blueprint gates. Gates A–J stay incomplete until live evidence lands.
        </p>
      </header>

      {error ? <p className="error" role="alert">{error}</p> : null}
      {loading ? <p className="muted">Loading progress…</p> : null}

      {blueprint ? (
        <section className="panel" aria-labelledby="gatesTitle">
          <div className="panel-head">
            <h2 id="gatesTitle">Blueprint gates</h2>
            <p>
              {blueprint.counts.gates_strong_or_done} strong · {blueprint.counts.gates_partial} partial ·{" "}
              {blueprint.counts.gates_open} open / {blueprint.counts.gates_total}
            </p>
          </div>
          <p className="rule">{blueprint.rule}</p>
          {blueprint.active ? (
            <p className="now">
              Now: <strong>{blueprint.active.label}</strong>
            </p>
          ) : null}
          <ol className="gates">
            {blueprint.gates.map((gate) => (
              <li key={gate.id} className={badge(gate.status)}>
                <span className="pill">{badge(gate.status)}</span>
                <span>
                  <strong>{gate.label}</strong>
                  <small>{gate.note}</small>
                </span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {readiness ? (
        <section className="panel" aria-labelledby="readyTitle">
          <div className="panel-head">
            <h2 id="readyTitle">Backend foundations</h2>
            <p>
              G {readiness.gate_g_complete ? "complete" : "partial"} · I{" "}
              {readiness.gate_i_complete ? "complete" : "partial"} · H{" "}
              {readiness.ops?.gate_h_complete ? "complete" : "open"}
            </p>
          </div>
          <p>
            <strong>Ready:</strong> {(readiness.ready || []).join(", ") || "none"}
          </p>
          <p>
            <strong>Open:</strong> {(readiness.missing || []).slice(0, 8).join(", ") || "none"}
          </p>
        </section>
      ) : null}
    </div>
  );
}
