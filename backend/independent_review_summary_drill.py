"""Gate G: human-readable independent review summary (unsigned).

Writes a Markdown summary of checklist + hard-open blockers + evidence pack
counts for a reviewer. Does **not** sign off — ``signed_off`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "independent_review_summary_drill.json"
SUMMARY_MD = ROOT / "docs" / "ops-evidence" / "INDEPENDENT_REVIEW_SUMMARY.md"


def run_independent_review_summary_drill(*, ops_dir: Path | None = None) -> dict:
    from .independent_review_pack_drill import run_independent_review_pack_drill
    from .independent_review_readiness_drill import run_independent_review_readiness_drill
    from .remaining_blockers_drill import run_remaining_blockers_drill

    pack = run_independent_review_pack_drill(ops_dir=ops_dir)
    ready = run_independent_review_readiness_drill(ops_dir=ops_dir)
    blockers = run_remaining_blockers_drill(ops_dir=ops_dir)
    lines = [
        "# Independent review summary (unsigned)",
        "",
        f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "",
        "This summary is **not** a sign-off. An independent reviewer must complete",
        "`docs/INDEPENDENT_REVIEW_CHECKLIST.md` before Gate G can close.",
        "",
        "## Readiness",
        "",
        f"- Score: {ready.get('score')}/{ready.get('score_of')}",
        f"- Evidence artifacts hashed: {pack.get('artifact_count')}",
        f"- Hard-open blockers: {blockers.get('open_count')}",
        f"- signed_off: {ready.get('signed_off')}",
        "",
        "## Hard-open blockers",
        "",
    ]
    for row in blockers.get("blockers") or []:
        lines.append(
            f"- **{row.get('id')}** (Gate {row.get('gate')}): {row.get('label')} "
            f"— local partial {len(row.get('local_partial_present') or [])}/"
            f"{len(row.get('local_partial') or [])}"
        )
    lines.extend([
        "",
        "## Evidence pack",
        "",
        f"- Checklist: {pack.get('checklist')}",
        f"- Pack drill: `independent_review_pack.json` ({pack.get('artifact_count')} files)",
        "- Readiness: `independent_review_readiness_drill.json`",
        "",
        "## Rule",
        "",
        "Do not mark `G-review` done until a non-agent reviewer signs the checklist table.",
        "",
    ])
    md = "\n".join(lines)
    dest = Path(ops_dir) if ops_dir else SUMMARY_MD.parent
    dest.mkdir(parents=True, exist_ok=True)
    md_out = (Path(ops_dir) / "INDEPENDENT_REVIEW_SUMMARY.md") if ops_dir else SUMMARY_MD
    md_out.write_text(md, encoding="utf-8")
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_summary",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "signed_off": False,
        "summary_path": str(md_out.relative_to(ROOT)) if ops_dir is None else md_out.name,
        "artifact_count": int(pack.get("artifact_count") or 0),
        "open_blockers": int(blockers.get("open_count") or 0),
        "readiness_score": ready.get("score"),
        "ok": bool(ready.get("ok")) and pack.get("signed_off") is False,
        "reason": (
            f"Independent review summary written ({pack.get('artifact_count')} artifacts, "
            f"{blockers.get('open_count')} blockers); human sign-off still pending"
        ),
    }
    out = (
        (Path(ops_dir) / "independent_review_summary_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "independent_review_summary_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        art_md = ROOT / "artifacts" / "ops" / "INDEPENDENT_REVIEW_SUMMARY.md"
        art_md.write_text(md, encoding="utf-8")
    return evidence
