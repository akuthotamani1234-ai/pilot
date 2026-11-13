"""The Orchestrator ("Quality Manager"): connects all agents with LangGraph.

  setup ─▶ discovery ─▶ change_detection ─▶ visual_check ─▶ test_design ─▶ script_generator ─▶ execution
    │          │                                                                    │              ▲    │
    │          │                                                                    │              │    ▼
    │          │                                                                    │      self_healing ◀─ failure_analysis
    │          │                                                                    │      (broken scripts,     │
    │          │                                                                    │       max N rounds)       │
    └──────────┴──── (setup failed / site down / no scripts) ───────────────────────┴──────────────────────▶ report
                                                                                                              │
                                                                     save_baseline ─▶ integrations ─▶ END
(visual_check: optional, VISUAL_CHECK; integrations: Slack / Jira, only when set in .env)
"""
import os
import time
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from .agents.change_detection import change_detection_agent, save_baseline_agent
from .agents.discovery import discovery_agent
from .agents.executor import execution_agent
from .agents.failure_analysis import failure_analysis_agent, healable
from .agents.reporter import reporter_agent
from .agents.script_generator import script_generator_agent
from .agents.self_healing import self_healing_agent
from .agents.setup_agent import setup_agent
from .agents.test_design import test_design_agent
from .config import settings
from .integrations import integrations_agent
from .page_status import page_testable
from .review import review_gate_agent
from .state import QAState
from .visual import visual_check_agent

# ---------------------------------------------------------------- routing decisions

def after_setup(state: QAState) -> str:
    if state.get("setup_error"):
        return "report"
    return "test_design" if state.get("contract_only") else "discovery"


def after_discovery(state: QAState) -> str:
    ok = [p for p in state.get("app_map", []) if page_testable(p)]
    return "change_detection" if ok else "failure_analysis"


def after_scripts(state: QAState) -> str:
    return "execution" if state.get("scripts") or state.get("contract_only") else "failure_analysis"


def after_test_design(state: QAState) -> str:
    return "script_generator" if state.get("contract_only") else "review_gate"


def after_analysis(state: QAState) -> str:
    """Broken SCRIPTS (not website bugs) and rounds left? -> try to heal them."""
    if state.get("contract_only"):
        return "report"
    if state.get("heal_round", 0) >= settings.max_heal_rounds:
        return "report"
    skip = set(state.get("unhealable", []))
    broken = [f for f in state.get("failures", []) if healable(f) and f.get("nodeid") not in skip]
    return "self_healing" if broken else "report"


def after_healing(state: QAState) -> str:
    return "execution" if state.get("rerun_only") else "report"


def after_report(state: QAState) -> str:
    """A contract-only run reports its approved flows without changing site baselines or integrations."""
    return END if state.get("contract_only") else "save_baseline"


# ---------------------------------------------------------------- live progress (for the web UI)

CURRENT = {"stage": ""}  # the agent running right now (main.py names it when a run crashes or is stopped)


def _traced(name, agent):
    """Remember the running agent, and print '::stage::<name>::start/done' around it when QA_EVENTS=1 (the web UI
    reads these)."""
    events = os.environ.get("QA_EVENTS") == "1"

    def run(state: QAState) -> QAState:
        CURRENT["stage"] = name
        if events:
            print(f"::stage::{name}::start", flush=True)
        from .scheduling import record_phase
        started, status = time.monotonic(), "interrupted"
        try:
            out = agent(state)
            status = "completed"
        finally:
            if state.get("run_dir"):
                record_phase(Path(state["run_dir"]), name, started, status)
        if events:
            print(f"::stage::{name}::done", flush=True)
        return out
    return run


# ---------------------------------------------------------------- graph

def build_graph(checkpointer=None, target_type="web", discovery_only=False):
    """checkpointer: saves the state after every agent (runs/<run>/checkpoint.sqlite), so `main.py --resume` can go on
    after the last finished stage."""
    if target_type == "mobile":
        from .android_graph import build_android_graph
        return build_android_graph(checkpointer=checkpointer)
    if target_type != "web":
        raise ValueError("Unsupported QA target type")
    g = StateGraph(QAState)
    if discovery_only:
        from .discovery_report import discovery_report
        for name, agent in (("setup", setup_agent), ("discovery", discovery_agent), ("report", discovery_report)):
            g.add_node(name, _traced(name, agent))
        g.add_edge(START, "setup")
        g.add_conditional_edges("setup", after_setup, ["discovery", "report"])
        g.add_edge("discovery", "report")
        g.add_edge("report", END)
        return g.compile(checkpointer=checkpointer)
    for name, agent in [
        ("setup", setup_agent),
        ("discovery", discovery_agent),
        ("change_detection", change_detection_agent),
        ("visual_check", visual_check_agent),
        ("test_design", test_design_agent),
        ("review_gate", review_gate_agent),
        ("script_generator", script_generator_agent),
        ("execution", execution_agent),
        ("failure_analysis", failure_analysis_agent),
        ("self_healing", self_healing_agent),
        ("report", reporter_agent),
        ("save_baseline", save_baseline_agent),
        ("integrations", integrations_agent),
    ]:
        g.add_node(name, _traced(name, agent))

    g.add_edge(START, "setup")
    g.add_conditional_edges("setup", after_setup, ["discovery", "test_design", "report"])
    g.add_conditional_edges("discovery", after_discovery, ["change_detection", "failure_analysis"])
    g.add_edge("change_detection", "visual_check")
    g.add_edge("visual_check", "test_design")
    g.add_conditional_edges("test_design", after_test_design, ["script_generator", "review_gate"])
    g.add_edge("review_gate", "script_generator")
    g.add_conditional_edges("script_generator", after_scripts, ["execution", "failure_analysis"])
    g.add_edge("execution", "failure_analysis")
    g.add_conditional_edges("failure_analysis", after_analysis, ["self_healing", "report"])
    g.add_conditional_edges("self_healing", after_healing, ["execution", "report"])
    g.add_conditional_edges("report", after_report, ["save_baseline", END])
    g.add_edge("save_baseline", "integrations")
    g.add_edge("integrations", END)
    return g.compile(checkpointer=checkpointer)
