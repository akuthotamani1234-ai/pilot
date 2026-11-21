"""Run an approved numeric browser contract while the full web crawl continues."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, BrokenBarrierError

from .agents.discovery import discovery_agent
from .config import settings
from .finalization import write_text_unless_linked
from .page_status import page_testable
from .qa_contracts import parse_contract
from .qa_web import _contract_paths_linked, run_contracts


def discover_with_contract(state):
    if (not settings.headless or settings.review != "off" or settings.test_workers < 2
            or state.get("resuming") or state.get("discovery_only") or state.get("contract_only")):
        return discovery_agent(state)

    run_dir = Path(state["run_dir"])
    if _contract_paths_linked(run_dir):
        return discovery_agent(state)
    path = run_dir / ".private" / "qa_contract.json"
    try:
        value = path.read_text(encoding="utf-8") if path.exists() else os.getenv("QA_CONTRACT_JSON", "")
        contract = parse_contract(value)
    except (ValueError, OSError):
        return discovery_agent(state)
    if (not contract.test_environment or not contract.rules or contract.flows or contract.checks
            or contract.android_package or contract.test_mode):
        return discovery_agent(state)

    future = None
    crawl_start_ns = last_inventory_ns = 0
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="qpilot-contract") as pool:
        # Give both browsers a chance to finish starting before a small crawl runs out of pages.
        # Release discovery immediately on setup errors and bound the wait for a slow browser.
        def mark_start():
            nonlocal crawl_start_ns
            crawl_start_ns = time.time_ns()

        ready = Barrier(2, action=mark_start, timeout=20)

        def meet():
            try:
                ready.wait()
            except BrokenBarrierError:
                pass

        def execute():
            try:
                return run_contracts(run_dir, state["url"], contract, on_first_page=meet)
            finally:
                ready.abort()

        def start():
            nonlocal crawl_start_ns, future
            future = pool.submit(execute)
            meet()
            if not crawl_start_ns:
                mark_start()

        def inventoried(entry):
            nonlocal last_inventory_ns
            if page_testable(entry):
                last_inventory_ns = time.time_ns()

        discovery = discovery_agent(state, on_visit_start=start, on_inventory=inventoried)
        if future is None:
            return discovery
        try:
            output = future.result()
        except Exception:
            # Ordinary execution handles browser startup and configuration failures with its usual reporting.
            return discovery
    if output["results"]:
        discovery["discovery_contract"] = output
        if not last_inventory_ns:
            discovery.update(output)
        discovery["crawl"]["contract_execution"] = {
            "crawl_start_ns": crawl_start_ns,
            "last_inventory_ns": last_inventory_ns,
            "overlapped_cases": [
                row["id"] for row in output["results"]
                if row["outcome"] in ("passed", "failed") and row.get("assertions_started_ns", 0)
                and row["assertions_started_ns"] < last_inventory_ns and row["assertions_finished_ns"] > crawl_start_ns
            ],
        }
        write_text_unless_linked(run_dir, "contract_overlap.json", json.dumps(discovery["crawl"]["contract_execution"]))
    return discovery
