import { useEffect, useState } from "react";
import {
  decideApproval,
  exchangeSsoCode,
  loadApprovals,
  loadBlueprint,
  loadDashboardToken,
  loadReadiness,
  saveDashboardToken,
  type ApprovalRow,
  type BlueprintProgress,
  type EnterpriseReadiness,
} from "./api";

function badge(status: string): string {
  if (status === "strong" || status === "done") return "done";
  if (status === "active") return "now";
  if (status === "partial") return "partial";
  return "next";
}

export function App() {
  const [blueprint, setBlueprint] = useState<BlueprintProgress | null>(null);
  const [readiness, setReadiness] = useState<EnterpriseReadiness | null>(null);
  const [approvals, setApprovals] = useState<ApprovalRow[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [token, setToken] = useState(() => loadDashboardToken());
  const [ssoCode, setSsoCode] = useState("");
  const [ssoNote, setSsoNote] = useState("");

  async function refreshApprovals() {
    const rows = await loadApprovals("pending");
    setApprovals(rows);
  }

  function onSaveToken() {
    saveDashboardToken(token);
    setSsoNote(token.trim() ? "Bearer token saved for approvals" : "Token cleared");
  }

  async function onExchangeCode() {
    setSsoNote("Exchanging…");
    try {
      const result = await exchangeSsoCode(ssoCode.trim());
      if (result.ok && result.access_token && result.principal_bound !== false) {
        saveDashboardToken(result.access_token);
        setToken(result.access_token);
        const role = result.role ? ` as ${result.role}` : "";
        setSsoNote(`OIDC code exchanged${role}; token saved (hosted IdP still open)`);
      } else {
        setSsoNote(result.principal_reason || result.reason || "SSO exchange failed");
      }
    } catch (err) {
      setSsoNote(err instanceof Error ? err.message : "SSO exchange failed");
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [bp, ready, pending] = await Promise.all([
          loadBlueprint(),
          loadReadiness(),
          loadApprovals("pending").catch(() => [] as ApprovalRow[]),
        ]);
        if (cancelled) return;
        setBlueprint(bp);
        setReadiness(ready);
        setApprovals(pending);
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

  async function onDecide(id: string, answer: string) {
    setBusyId(id);
    try {
      await decideApproval(id, answer);
      await refreshApprovals();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decide failed");
    } finally {
      setBusyId("");
    }
  }

  return (
    <div className="shell">
      <header className="hero">
        <p className="brand">Qpilot</p>
        <h1>Enterprise readiness</h1>
        <p className="lede">
          React/TypeScript dashboard for blueprint gates and approvals. Gates A–J stay incomplete until live evidence lands.
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
          {blueprint.roadmap ? (
            <div className="roadmap">
              {(
                [
                  ["landed", "Implemented", blueprint.roadmap.landed || []],
                  ["now", "Where we are", blueprint.roadmap.now || []],
                  ["next", "Where we are going", blueprint.roadmap.next || []],
                ] as const
              ).map(([id, title, rows]) =>
                rows.length ? (
                  <div key={id} className={`roadmap-section roadmap-${id}`}>
                    <h3>{title}</h3>
                    <ol className="gates">
                      {rows.map((row) => (
                        <li key={row.id} className={badge(row.status)}>
                          <span className="pill">{badge(row.status)}</span>
                          <span>
                            <strong>{row.label}</strong>
                            <small>
                              {row.note
                                || (row.local_partial_score_of
                                  ? `Local Partial ${row.local_partial_score}/${row.local_partial_score_of}`
                                  : "")
                                || (id === "next" ? "Blocker" : "")}
                            </small>
                          </span>
                        </li>
                      ))}
                    </ol>
                  </div>
                ) : null,
              )}
            </div>
          ) : (blueprint.blockers || []).length ? (
            <>
              <p className="now">
                Hard-open blockers: {blueprint.counts.blockers_open ?? blueprint.blockers?.length}
              </p>
              <ol className="gates">
                {(blueprint.blockers || []).map((row) => (
                  <li key={row.id} className="open">
                    <span className="pill">next</span>
                    <span>
                      <strong>{row.label}</strong>
                      <small>
                        {row.note
                          || (row.local_partial_score_of
                            ? `Local Partial ${row.local_partial_score}/${row.local_partial_score_of}`
                            : "Blocker")}
                      </small>
                    </span>
                  </li>
                ))}
              </ol>
            </>
          ) : null}
        </section>
      ) : null}

      <section className="panel" aria-labelledby="ssoTitle">
        <div className="panel-head">
          <h2 id="ssoTitle">Dashboard auth / SSO helper</h2>
          <p>Gate I — loopback OIDC callback; hosted IdP login still open</p>
        </div>
        <label className="field">
          Bearer token
          <input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Paste JWT / dashboard bearer"
            autoComplete="off"
          />
        </label>
        <div className="actions">
          <button type="button" onClick={onSaveToken}>
            Save token
          </button>
        </div>
        <label className="field">
          Authorization code
          <input
            value={ssoCode}
            onChange={(e) => setSsoCode(e.target.value)}
            placeholder="OIDC code from /authorize redirect"
            autoComplete="off"
          />
        </label>
        <div className="actions">
          <button type="button" onClick={onExchangeCode} disabled={!ssoCode.trim()}>
            Exchange via /api/sso/callback
          </button>
        </div>
        {ssoNote ? <p className="muted">{ssoNote}</p> : null}
      </section>

      <section className="panel" aria-labelledby="approvalsTitle">
        <div className="panel-head">
          <h2 id="approvalsTitle">Approvals</h2>
          <p>{approvals.length} pending · Gate I incomplete without auth</p>
        </div>
        {approvals.length === 0 ? (
          <p className="muted">No pending approvals. Create one via POST /api/v1/approvals.</p>
        ) : (
          <ul className="gates">
            {approvals.map((row) => (
              <li key={row.id} className="partial">
                <span className="pill">pending</span>
                <span>
                  <strong>
                    {row.kind}: {row.subject}
                  </strong>
                  <small>{row.detail || row.reason}</small>
                  <span className="actions">
                    <button type="button" disabled={busyId === row.id} onClick={() => onDecide(row.id, "yes")}>
                      Accept
                    </button>
                    <button type="button" disabled={busyId === row.id} onClick={() => onDecide(row.id, "no")}>
                      Reject
                    </button>
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {readiness ? (
        <section className="panel" aria-labelledby="readyTitle">
          <div className="panel-head">
            <h2 id="readyTitle">Backend foundations</h2>
            <p>
              G {readiness.gate_g_complete ? "complete" : "partial"} · I{" "}
              {readiness.gate_i_complete ? "complete" : "partial"} · H{" "}
              {readiness.ops?.gate_h_complete ? "complete" : "partial"}
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
