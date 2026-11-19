"""Rebuild a saved report into a separate directory; source evidence stays immutable."""
import json
import shutil
from pathlib import Path

from .finalization import read_json

METADATA = ("app_map.json", "results.json", "test_cases.json", "crawl.json", "components.json", "registry.json",
            "execution.json", "failures.json", "login.json", "visual.json", "llm_usage.jsonl", "created.jsonl")


def rebuild(source: Path, destination: Path) -> dict:
    from .agents.change_detection import relative_path_is_linked, run_read_block
    source_path, dest_path = Path(source), Path(destination)
    blocked = run_read_block(source_path)
    if blocked:
        raise ValueError(blocked)
    if dest_path.is_symlink() or (dest_path.parent.exists() and dest_path.parent.is_symlink()):
        raise ValueError("This run's folder is a link.")
    source, destination = source_path.resolve(), dest_path.resolve()
    if destination == source or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("Rebuild output must be separate from historical run artifacts")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Choose a new or empty rebuild output directory")
    destination.mkdir(parents=True, exist_ok=True)
    for name in METADATA:
        item = source / name
        if item.is_symlink() or not item.exists():
            continue
        shutil.copy2(item, destination / name)
    for folder in ("generated_tests", "html"):
        folder_path = source / folder
        if folder_path.is_symlink() or not folder_path.is_dir():
            continue
        shutil.copytree(folder_path, destination / folder, ignore=_ignore_linked)
    for path in source.glob("results*.jsonl"):
        if path.is_symlink():
            continue
        shutil.copy2(path, destination / path.name)
    pages, results = read_json(source / "app_map.json", []), read_json(source / "results.json", [])
    evidence = {r[key] for r in pages + results for key in ("screenshot", "trace") if r.get(key)}
    for name in evidence:
        if relative_path_is_linked(source_path, str(name)):
            continue
        original = (source / name).resolve()
        if original.is_relative_to(source) and original.is_file() and not (source_path / name).is_symlink():
            target = destination / original.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
    old = read_json(source / "summary.json", {})
    args = read_json(source / "run_args.json", {})
    state = {"run_dir": str(destination), "run_id": destination.name, "source": old.get("source") or args.get("source"),
             "url": old.get("url") or args.get("url"), "site_key": args.get("site_key") or source.name,
             "app_map": pages, "results": results, "test_cases": read_json(source / "test_cases.json", []),
             "crawl": read_json(source / "crawl.json", {}), "login": read_json(source / "login.json", {}),
             "failures": read_json(source / "failures.json", []), "incomplete": bool(old.get("incomplete")),
             "incomplete_reason": old.get("incomplete_reason") or "", "stopped_at": old.get("stopped_at"),
             "log": ["Report rebuilt from immutable evidence: " + source.name]}
    from .agents.reporter import reporter_agent
    reporter_agent(state)
    new = read_json(destination / "summary.json", {})
    comparison = {"source": str(source), "output": str(destination), "before": {
        "single_tests": old.get("metrics", {}).get("single_tests", {}), "cases": old.get("metrics", {}).get("test_cases", {}),
        "findings": old.get("findings"), "consistent": old.get("metrics", {}).get("consistent")},
        "after": {"single_tests": new["metrics"]["single_tests"], "cases": new["metrics"]["test_cases"],
                  "findings": new.get("findings"), "consistent": new["metrics"]["consistent"]}}
    from .finalization import write_text_unless_linked
    if not write_text_unless_linked(destination, "rebuild_comparison.json", json.dumps(comparison, indent=2)):
        raise ValueError("This run's folder is a link.")
    return comparison


def _ignore_linked(folder, names):
    """Leave cache folders and links out of a rebuilt copy."""
    skip = {"__pycache__", ".pytest_cache"}
    base = Path(folder)
    for name in names:
        if (base / name).is_symlink():
            skip.add(name)
    return skip


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    options = parser.parse_args()
    rebuilt = rebuild(options.source, options.destination)
    print(json.dumps({"before_findings": rebuilt["before"]["findings"], "after_findings": rebuilt["after"]["findings"],
                      "consistent": rebuilt["after"]["consistent"], "report": str(options.destination / "report.html")}))
