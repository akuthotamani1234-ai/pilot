"""Recover durable evidence before reporting, independently of optional AI analysis."""
import hashlib
import json
from pathlib import Path

from .safety import redact

ADVERSE = {"failed", "error", "inconclusive"}


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def finding_nodes(finding: dict) -> set[str]:
    return set(finding.get("nodeids") or []) | ({finding["nodeid"]} if finding.get("nodeid") else set())


def ingest_results(state: dict, *, recover: bool = True) -> list[dict]:
    """Keep final aggregates authoritative; recover missing worker records and torn JSONL safely."""
    root = Path(state["run_dir"])
    if not recover and "results" in state:
        return list(state.get("results") or [])
    rows = {}
    for result in read_json(root / "results.json", []) + list(state.get("results") or []):
        if result.get("nodeid"):
            rows[result["nodeid"]] = result
    for path in sorted(root.glob("results*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                result = json.loads(line)
            except ValueError:
                continue  # a killed worker may leave its final line incomplete
            if isinstance(result, dict) and result.get("nodeid"):
                rows.setdefault(result["nodeid"], result)
    return list(rows.values())


def reconcile(state: dict, *, save: bool = True, recover: bool = True) -> dict:
    """Idempotent, local finalization. Never calls a model or the tested website."""
    from .agents.failure_analysis import CATEGORY_NAME, NEXT_ACTION, _rule_classify
    from .excel import case_hits

    root = Path(state["run_dir"])
    results = ingest_results(state, recover=recover)
    cases = state.get("test_cases") or read_json(root / "test_cases.json", [])
    adverse = {r["nodeid"]: r for r in results if r.get("outcome") in ADVERSE}
    supplied = state.get("failures")
    failures = list(supplied if supplied is not None else read_json(root / "failures.json", []))
    # A successful healing result must retire its earlier finding.
    failures = [dict(f) for f in failures if f.get("source") != "test" or finding_nodes(f) & adverse.keys()]
    covered = set().union(*(finding_nodes(f) for f in failures)) if failures else set()
    for nodeid, result in adverse.items():
        if nodeid in covered:
            continue
        category, explanation, confidence = _rule_classify(result)
        if category in {"product_defect", "assertion_failure", "suspect", "rule_violation"}:
            category, confidence = "untriaged", "low"
            explanation = "Expected and observed outcomes differ; product behavior has not been independently verified."
        failures.append({
            "id": len(failures), "finding_id": "finding-" + hashlib.sha256(nodeid.encode()).hexdigest()[:16],
            "source": "test", "nodeid": nodeid, "nodeids": [nodeid],
            "file": result.get("file"), "test": result.get("test"), "page_url": result.get("url"),
            "category": category, "category_name": CATEGORY_NAME.get(category, "Untriaged result"),
            "severity": "medium" if category == "untriaged" else "low", "confidence": confidence,
            "triage_status": "provisional", "explanation": explanation,
            "next_action": NEXT_ACTION.get(category, "Review the trace and reproduce against an explicit expected outcome."),
            "error": redact(result.get("error") or ""), "screenshot": result.get("screenshot"),
            "trace": result.get("trace"), "evidence": [v for v in (result.get("screenshot"), result.get("trace")) if v],
            "steps": result.get("live_steps") or result.get("steps") or [],
        })
    for index, finding in enumerate(failures):
        finding["id"] = index
        nodes = finding_nodes(finding)
        if finding.get("source") == "test":
            finding["nodeids"] = sorted(nodes & adverse.keys())
            if finding.get("nodeid") not in adverse:
                finding["nodeid"] = finding["nodeids"][0]
        linked = [c for c in cases if any(r["nodeid"] in nodes for r in case_hits(c, results))]
        finding["case_ids"] = [c.get("tc_id") or c.get("id") for c in linked]
        finding["feature_ids"] = sorted({fid for c in linked for fid in c.get("feature_ids") or []})
        if linked:
            finding.setdefault("tc_id", linked[0].get("tc_id"))
        if not finding.get("finding_id"):
            identity = "|".join(sorted(nodes)) or f"{finding.get('test')}|{finding.get('page_url')}|{finding.get('error')}"
            finding["finding_id"] = "finding-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
    for case in cases:
        owned = {r["nodeid"] for r in case_hits(case, results)}
        case["finding_ids"] = [f["finding_id"] for f in failures if finding_nodes(f) & owned]
        # Old generated form journeys established input interaction only.
        if case.get("journey") == "form" or (case.get("kind") == "form" and (case.get("spec") or {}).get("mode") == "guard"):
            case["verification_level"] = "input_only"
            case["business_verified"] = False
            for result in case_hits(case, results):
                result["verification_level"] = "input_only"
    from .agents.reporter import fill_case_results
    fill_case_results(cases, results, failures, root / "generated_tests")
    pending = [c.get("tc_id") or c.get("id") for c in cases
               if c.get("execution_status") in {"Not run", "Pending"} and not c.get("blocked")]
    recovered = dict(state, results=results, failures=failures, test_cases=cases)
    if save:
        for name, value in (("results.json", results), ("failures.json", failures), ("test_cases.json", cases),
                            ("pending_cases.json", {"pending": pending, "completed_nodeids": sorted(
                                r["nodeid"] for r in results)})):
            (root / name).write_text(json.dumps(value, indent=2), encoding="utf-8")
    return recovered
