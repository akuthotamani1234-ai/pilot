export type GateRow = {
  id: string;
  label: string;
  status: string;
  note?: string;
};

export type BlueprintProgress = {
  complete: boolean;
  rule: string;
  active?: GateRow | null;
  gates: GateRow[];
  upcoming: GateRow[];
  blockers?: GateRow[];
  counts: {
    gates_strong_or_done: number;
    gates_partial: number;
    gates_open: number;
    gates_total: number;
    phases_done?: number;
    phases_total?: number;
    blockers_open?: number;
  };
};

export type EnterpriseReadiness = {
  gate_g_complete: boolean;
  gate_i_complete: boolean;
  ready: string[];
  missing: string[];
  blueprint?: BlueprintProgress;
  ops?: { gate_h_complete: boolean; missing: string[]; ready?: string[] };
};

export type ApprovalRow = {
  id: string;
  kind: string;
  subject: string;
  detail: string;
  status: string;
  answer: string;
  reason: string;
  created_at: number;
  decided_at: number | null;
};

/** Optional bearer from localStorage `qpilot_dashboard_token` when QPILOT_DASHBOARD_TOKEN is set server-side. */
function authHeaders(extra?: HeadersInit): HeadersInit {
  const headers: Record<string, string> = {};
  if (extra) {
    const base = new Headers(extra);
    base.forEach((value, key) => {
      headers[key] = value;
    });
  }
  try {
    const token = localStorage.getItem("qpilot_dashboard_token") || "";
    if (token.trim()) headers.Authorization = `Bearer ${token.trim()}`;
  } catch {
    /* private mode / non-browser */
  }
  return headers;
}

export async function loadBlueprint(): Promise<BlueprintProgress> {
  const direct = await fetch("/api/v1/blueprint/progress");
  if (direct.ok) return direct.json();
  const ready = await fetch("/api/v1/enterprise/readiness");
  if (!ready.ok) throw new Error("Blueprint progress unavailable");
  const body = (await ready.json()) as EnterpriseReadiness;
  if (!body.blueprint) throw new Error("Blueprint payload missing");
  return body.blueprint;
}

export async function loadReadiness(): Promise<EnterpriseReadiness> {
  const ready = await fetch("/api/v1/enterprise/readiness");
  if (!ready.ok) throw new Error("Enterprise readiness unavailable");
  return ready.json();
}

export async function loadApprovals(status = "pending"): Promise<ApprovalRow[]> {
  const res = await fetch(`/api/v1/approvals?status=${encodeURIComponent(status)}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Approvals unavailable");
  const body = await res.json();
  return body.approvals || [];
}

export async function decideApproval(id: string, answer: string): Promise<ApprovalRow> {
  const res = await fetch(`/api/v1/approvals/${encodeURIComponent(id)}/decide`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ answer }),
  });
  if (!res.ok) throw new Error("Decide failed");
  return res.json();
}

/** Exchange an OIDC authorization code via Studio callback helper. */
export async function exchangeSsoCode(code: string, state = ""): Promise<{
  ok: boolean;
  access_token?: string;
  reason?: string;
  gate_i_complete?: boolean;
}> {
  const qs = new URLSearchParams({ code, state });
  const res = await fetch(`/api/sso/callback?${qs.toString()}`);
  const body = await res.json().catch(() => ({}));
  return body;
}

export function saveDashboardToken(token: string): void {
  try {
    if (token.trim()) localStorage.setItem("qpilot_dashboard_token", token.trim());
    else localStorage.removeItem("qpilot_dashboard_token");
  } catch {
    /* ignore */
  }
}

export function loadDashboardToken(): string {
  try {
    return localStorage.getItem("qpilot_dashboard_token") || "";
  } catch {
    return "";
  }
}
