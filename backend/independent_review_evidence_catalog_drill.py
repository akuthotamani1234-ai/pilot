"""Gate G: catalog ops-evidence files for independent reviewers (unsigned).

Indexes ``docs/ops-evidence`` into a machine-readable catalog with gate tags.
Does **not** sign off — ``signed_off`` / ``gate_g_complete`` stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPS = ROOT / "docs" / "ops-evidence"
EVIDENCE = OPS / "independent_review_evidence_catalog_drill.json"

GATE_HINTS = (
    ("gate_a", ("gate_a", "swarm", "durable")),
    ("gate_b", ("gate_b", "demo_store", "mutation")),
    ("gate_c", ("gate_c", "classic", "travel", "admin")),
    ("gate_d", ("android", "appium", "device", "api24", "multi_api", "hosted_runner", "ci_artifact")),
    ("gate_e", ("healing", "failure_matrix", "flaky")),
    ("gate_f", ("browser", "portfolio", "multi_browser")),
    ("gate_g", ("independent_review", "tenancy", "rbac", "remaining_blockers")),
    ("gate_h", ("multi_region", "failover", "cutover", "paging", "oncall", "minio", "redis", "postgres")),
    ("gate_i", ("sso", "oidc", "idp", "principal_bootstrap", "auth")),
    ("gate_j", ("benchmark", "seeded", "demo")),
)


def _tag_gates(name: str) -> list[str]:
    lower = name.lower()
    tags = []
    for gate, needles in GATE_HINTS:
        if any(n in lower for n in needles):
            tags.append(gate)
    return tags or ["untagged"]


def run_independent_review_evidence_catalog_drill(*, ops_dir: Path | None = None) -> dict:
    src = Path(ops_dir) if ops_dir else OPS
    entries = []
    if src.is_dir():
        for path in sorted(src.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".json", ".md"}:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            entries.append({
                "name": path.name,
                "bytes": size,
                "gates": _tag_gates(path.name),
            })
    by_gate: dict[str, int] = {}
    for row in entries:
        for g in row["gates"]:
            by_gate[g] = by_gate.get(g, 0) + 1
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_evidence_catalog",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "signed_off": False,
        "entries": entries,
        "entry_count": len(entries),
        "by_gate": by_gate,
        "ok": len(entries) >= 20,
        "reason": (
            f"Independent review evidence catalog {len(entries)} files; "
            "signed_off remains False until external review"
            if len(entries) >= 20
            else "Evidence catalog thin; independent sign-off still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else OPS
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "independent_review_evidence_catalog_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "independent_review_evidence_catalog_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
