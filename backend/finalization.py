"""Recover durable evidence before reporting, independently of optional AI analysis."""
import hashlib
import json
from pathlib import Path

from .safety import redact

ADVERSE = {"failed", "error", "inconclusive"}


def folder_is_linked(path: Path) -> bool:
    """True when this folder, or a folder on the way to it, is a link."""
    path = Path(path)
    if path.is_symlink():
        return True
    return any(parent.is_symlink() for parent in path.parents)


def path_unless_linked(folder: Path, name: str) -> Path | None:
    """A real file path in this folder. A link, or a name that leaves the folder, is refused."""
    folder = Path(folder)
    path = folder / name
    if (not name or folder_is_linked(folder) or path.is_symlink()
            or Path(name).is_absolute() or ".." in Path(name).parts):
        return None
    return path


def write_bytes_unless_linked(path: Path, data: bytes) -> bool:
    """Write bytes at this path. A linked file or folder is left untouched."""
    path = Path(path)
    if path.is_symlink() or folder_is_linked(path.parent):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def copy_unless_linked(src: Path, dest: Path) -> bool:
    """Copy onto a real file. A linked destination is left untouched."""
    import shutil
    dest = Path(dest)
    if dest.is_symlink() or folder_is_linked(dest.parent):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return True


def append_text_unless_linked(path: Path, text: str) -> bool:
    """Append to a real file. A linked file or folder is left untouched."""
    path = Path(path)
    parent = path.parent
    if path.is_symlink() or folder_is_linked(parent):
        return False
    try:
        if not parent.exists():
            parent.mkdir(exist_ok=True)
        if path.is_symlink() or folder_is_linked(parent) or not parent.is_dir():
            return False
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
    except OSError:
        return False
    return True


def write_text_unless_linked(run_dir: Path, name: str, text: str) -> bool:
    """Write one file in this run. A link, or a name that leaves the run, is left untouched."""
    path = path_unless_linked(Path(run_dir), name)
    if path is None:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def private_file(run_dir: Path, name: str) -> Path | None:
    """A real file in this run's private folder. A link, or a name that leaves it, is refused."""
    run_dir = Path(run_dir)
    if not name or Path(name).is_absolute() or "/" in name or "\\" in name or name in {".", ".."}:
        return None
    private = run_dir / ".private"
    if folder_is_linked(run_dir) or private.is_symlink():
        return None
    private.mkdir(exist_ok=True)
    path = private / name
    if path.is_symlink():
        return None
    return path


def save_login_state(run_dir: Path, write) -> bool:
    """Save this run's login. A linked private folder or auth file is not written."""
    auth_path = private_file(run_dir, "auth.json")
    if auth_path is None:
        return False
    write(str(auth_path))
    return True


def _path_is_linked(path: Path) -> bool:
    path = Path(path)
    return path.is_symlink() or folder_is_linked(path.parent)


def read_json(path: Path, default):
    if _path_is_linked(path):
        return default
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def finding_nodes(finding: dict) -> set[str]:
    return set(finding.get("nodeids") or []) | ({finding["nodeid"]} if finding.get("nodeid") else set())


def ingest_results(state: dict, *, recover: bool = True) -> list[dict]:
    """Keep final aggregates authoritative; recover missing worker records and torn JSONL safely."""
    root = Path(state["run_dir"])
    if folder_is_linked(root):
        return [] if recover or "results" not in state else list(state.get("results") or [])
    if not recover and "results" in state:
        return list(state.get("results") or [])
    rows = {}
    for result in read_json(root / "results.json", []) + list(state.get("results") or []):
        if isinstance(result, dict) and result.get("nodeid"):
            rows[result["nodeid"]] = result
    for path in sorted(root.glob("results*.jsonl")):
        if path.is_symlink():
            continue
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
    if folder_is_linked(root):
        return dict(state)
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
            dest = root / name
            if folder_is_linked(root) or dest.is_symlink():
                continue
            dest.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return recovered
