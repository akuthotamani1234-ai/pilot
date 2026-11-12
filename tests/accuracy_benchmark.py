"""The accuracy benchmark: the WHOLE agent (main.py: discovery -> tests -> execution -> report) against a practice shop
whose pages, features and planted bugs are known - first clean, then with its planted bugs - measured against its
truth manifest (backend/accuracy.py). No AI, hidden browser, its own runs/ and baseline/ folders (your runs/ is not
touched). Takes several minutes:

    .venv\\Scripts\\python.exe -m tests.accuracy_benchmark --out project-docs/accuracy/after.json
    .venv\\Scripts\\python.exe -m tests.accuracy_benchmark --site classic --out project-docs/accuracy/classic_after.json

  demo     tests/demo_store.py    a modern shop behind a two-step login (6 planted bugs)
  classic  tests/classic_shop.py  an older template shop: index.php?rt=<route>, plain-list menus (3 planted bugs)
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from backend.accuracy import measure, summary_line

ROOT = Path(__file__).resolve().parent.parent


def _site(name: str):
    """(site class, its test account, its truth manifest)."""
    if name == "classic":
        from tests.classic_shop import EMAIL, PASSWORD, ClassicShop
        return ClassicShop, (EMAIL, PASSWORD), "classic_shop_truth.json"
    if name == "admin":
        from tests.admin_portal import AdminPortal
        return AdminPortal, (), "truth/admin_portal.json"
    if name == "travel":
        from tests.travel_site import TravelSite
        return TravelSite, (), "truth/travel_site.json"
    from tests.demo_store import EMAIL, PASSWORD, DemoStore
    return DemoStore, (EMAIL, PASSWORD), "demo_store_truth.json"


# the environment each site is measured on: AdminPortal's B7 (an edited name is not saved) needs the form really sent
SITE_ENV = {"admin": {"TEST_ENVIRONMENT": "staging", "ALLOW_ACTIONS": "delete"}}


def _visited(store) -> list:
    return list(store.visited) + [f"POST {p['path']}" for p in getattr(store, "posts", [])]


def truth(name: str = "demo") -> dict:
    return json.loads((ROOT / "tests" / _site(name)[2]).read_text(encoding="utf-8"))


TRUTH = truth("demo")


def run_agent(store, work: Path, extra_env: dict | None = None, account: tuple | None = None) -> tuple[Path, str]:
    """main.py against the store (logged in with `account`, default: DemoStore's test account; () = no account).
    Returns (run folder, its output)."""
    if account is None:
        from tests.demo_store import EMAIL, PASSWORD
        account = (EMAIL, PASSWORD)
    env = os.environ.copy()
    env.update({"LLM_PROVIDER": "none", "HEADLESS": "true", "SLOW_MO_MS": "0", "TEST_WORKERS": "3",
                "RUNS_DIR": str(work / "runs"), "BASELINE_DIR": str(work / "baseline"),
                "WORKSPACE_DIR": str(work / "ws"), "TEST_USERNAME": account[0] if account else "",
                "TEST_PASSWORD": account[1] if account else "",
                "AUTO_REGISTER": "false", "RECORD_VIDEO": "false", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                **(extra_env or {})})
    r = subprocess.run([sys.executable, "main.py", store.url, "--no-open", "--max-pages", "0", "--max-depth", "0"],
                       check=False, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=3600)
    if r.returncode != 0:
        raise RuntimeError(f"main.py failed ({r.returncode}):\n{r.stdout[-3000:]}\n{r.stderr[-2000:]}")
    runs = sorted((work / "runs").iterdir(), key=lambda p: p.stat().st_mtime)
    return runs[-1], r.stdout


def benchmark(work: Path, extra_env: dict | None = None, site: str = "demo", mode: str = "first") -> dict:
    """first: a fresh run on the clean site and one on the buggy site. regression: the clean site's run is the
    baseline, then ITS tests run again (REUSE_TESTS) on the buggy site - as a regression suite would. both: all three."""
    shop, account, _ = _site(site)
    env = dict(SITE_ENV.get(site, {}), **(extra_env or {}))
    out = {"site": site, "mode": mode}
    for bugs in (False, True):
        if mode == "regression" and bugs:
            break
        store = shop(bugs=bugs).start()
        try:
            run, _ = run_agent(store, work / ("buggy" if bugs else "clean"), env, account)
            out["buggy" if bugs else "clean"] = measure(run, truth(site), bugs, _visited(store))
            out["buggy" if bugs else "clean"]["run_dir"] = str(run)
        finally:
            store.stop()
    if mode in ("regression", "both"):  # the clean run's baseline + scripts, run again on the buggy site
        store = shop(bugs=True).start()
        try:
            base = work / "clean"
            run, _ = run_agent(store, base, dict(env, REUSE_TESTS="true"), account)
            out["regression"] = measure(run, truth(site), True, _visited(store))
            out["regression"]["run_dir"] = str(run)
        finally:
            store.stop()
    return out


def remeasure(path: Path) -> dict:
    """Measure the kept runs of an earlier benchmark again (e.g. after the truth manifest got more precise), so the
    before / after numbers always use the same yardstick. The 'never requested' check is kept from the first time."""
    old = json.loads(path.read_text(encoding="utf-8"))
    site = old.get("site", "demo")
    out = {"site": site}
    for name in ("clean", "buggy"):
        m = measure(old[name]["run_dir"], truth(site), name == "buggy")
        m["truth"]["never_requested_but_done"] = old[name]["truth"].get("never_requested_but_done", [])
        out[name] = dict(m, run_dir=old[name]["run_dir"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Accuracy benchmark on a practice shop (clean + planted bugs)")
    ap.add_argument("--site", choices=("demo", "classic", "admin", "travel"), default="demo",
                    help="which practice site (default: demo)")
    ap.add_argument("--mode", choices=("first", "regression", "both"), default="first",
                    help="first = fresh runs on the clean and the buggy site; regression = the clean run's tests again "
                         "on the buggy site; both")
    ap.add_argument("--out", help="write the numbers to this JSON file")
    ap.add_argument("--keep", help="keep the run folders here (default: a temporary folder)")
    ap.add_argument("--remeasure", help="measure the kept runs of this earlier result file again (no new runs)")
    a = ap.parse_args()
    if a.remeasure:
        m = remeasure(Path(a.remeasure))
        for name in ("clean", "buggy"):
            print(f"{name:5s}: {summary_line(m[name])}")
        Path(a.out or a.remeasure).write_text(json.dumps(m, indent=2), encoding="utf-8")
        return
    work = Path(a.keep) if a.keep else Path(tempfile.mkdtemp(prefix="agentic-qa-accuracy-"))
    work.mkdir(parents=True, exist_ok=True)
    m = benchmark(work, site=a.site, mode=a.mode)
    for name in ("clean", "buggy", "regression"):
        if name in m:
            print(f"{name:10s}: {summary_line(m[name])}")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(m, indent=2), encoding="utf-8")
        print(f"written: {a.out}")


if __name__ == "__main__":
    main()
