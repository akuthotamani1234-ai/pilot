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
  counts: {
    gates_strong_or_done: number;
    gates_partial: number;
    gates_open: number;
    gates_total: number;
    phases_done?: number;
    phases_total?: number;
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
  const res = await fetch(`/api/v1/approvals?status=${encodeURIComponent(status)}`);
  if (!res.ok) throw new Error("Approvals unavailable");
  const body = await res.json();
  return body.approvals || [];
}

export async function decideApproval(id: string, answer: string): Promise<ApprovalRow> {
  const res = await fetch(`/api/v1/approvals/${encodeURIComponent(id)}/decide`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer }),
  });
  if (!res.ok) throw new Error("Decide failed");
  return res.json();
}
