"""Gate G: independent review findings template (unsigned).

Writes a reviewer findings Markdown template so a human can record issues.
Does **not** collect a signature — ``signed_off`` / ``gate_g_complete`` stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "independent_review_findings_template_drill.json"
TEMPLATE = ROOT / "docs" / "ops-evidence" / "INDEPENDENT_REVIEW_FINDINGS.md"

TEMPLATE_BODY = """# Independent review findings (unsigned)

Status: **awaiting independent reviewer**

| Field | Value |
| --- | --- |
| Reviewer | _TBD_ |
| Date | _TBD_ |
| Pack | `independent_review_handoff_pack_drill.json` |
| Sign-off | **not signed** |

## Findings

| ID | Severity | Gate | Finding | Status |
| --- | --- | --- | --- | --- |
| F-001 | _TBD_ | _TBD_ | _Record finding here_ | open |

## Decision

- [ ] Approve with no blocking findings
- [ ] Approve with follow-ups
- [ ] Request changes (block Gate G)

Signature: ______________________  Date: __________

> Agent-generated template only. External human review required.
"""


def _linked_template() -> dict:
    return {
        "gate_g_complete": False,
        "ok": False,
        "signed_off": False,
        "drill": "independent_review_findings_template",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_independent_review_findings_template_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked
    if ops_dir is not None and folder_is_linked(Path(ops_dir)):
        return _linked_template()
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    md_out = (
        (Path(ops_dir) / "INDEPENDENT_REVIEW_FINDINGS.md")
        if ops_dir else TEMPLATE
    )
    out = (
        (Path(ops_dir) / "independent_review_findings_template_drill.json")
        if ops_dir else EVIDENCE
    )
    if folder_is_linked(dest) or folder_is_linked(md_out) or folder_is_linked(out):
        return _linked_template()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, md_out.name, TEMPLATE_BODY):
        return _linked_template()
    if folder_is_linked(md_out):
        return _linked_template()
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_findings_template",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "unsigned_template",
        "template_path": str(md_out.relative_to(ROOT) if md_out.is_relative_to(ROOT) else md_out),
        "signed_off": False,
        "ok": md_out.is_file() and "not signed" in md_out.read_text(encoding="utf-8"),
        "reason": (
            "Independent review findings template written (unsigned); "
            "external sign-off still open"
        ),
    }
    if not write_text_unless_linked(dest, out.name, json.dumps(evidence, indent=2)):
        return _linked_template()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "independent_review_findings_template_drill.json"
        if not folder_is_linked(art) and not folder_is_linked(art.parent):
            art.parent.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art.parent, art.name, json.dumps(evidence, indent=2))
    return evidence
