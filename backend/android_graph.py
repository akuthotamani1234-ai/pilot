"""LangGraph pipeline for native Android runs; the existing website graph is unchanged."""

import traceback

from langgraph.graph import END, START, StateGraph

from .android import AndroidEnvironmentError
from .android_pipeline import (
    AndroidState,
    discovery_agent,
    execution_agent,
    failure_analysis_agent,
    reporter_agent,
    script_generator_agent,
    self_healing_agent,
    setup_agent,
    test_design_agent,
)


def _setup(state: AndroidState) -> AndroidState:
    try:
        return setup_agent(state)
    except AndroidEnvironmentError as e:
        return {"setup_error": str(e), "log": state.get("log", []) + [f"Android setup failed: {e}"]}


def _traced(name, agent):
    def run(state: AndroidState) -> AndroidState:
        from pathlib import Path

        if name != "report" and (Path(state["run_dir"]) / "STOP").exists():
            return {"setup_error": "The mobile run was stopped by the user.", "incomplete": True}
        print(f"::stage::{name}::start", flush=True)
        try:
            result = agent(state)
        except Exception as e:
            traceback.print_exc()
            message = f"Android {name} failed: {type(e).__name__}: {str(e).splitlines()[0][:300]}"
            result = {"setup_error": state.get("setup_error") or message, "log": state.get("log", []) + [message]}
        print(f"::stage::{name}::done", flush=True)
        return result

    return run


def _after_setup(state: AndroidState) -> str:
    return "report" if state.get("setup_error") else "discovery"


def _after_discovery(state: AndroidState) -> str:
    return "report" if state.get("setup_error") else "test_design"


def build_android_graph(checkpointer=None):
    graph = StateGraph(AndroidState)
    for name, agent in (
        ("setup", _setup),
        ("discovery", discovery_agent),
        ("test_design", test_design_agent),
        ("script_generator", script_generator_agent),
        ("execution", execution_agent),
        ("failure_analysis", failure_analysis_agent),
        ("self_healing", self_healing_agent),
        ("report", reporter_agent),
    ):
        graph.add_node(name, _traced(name, agent))
    graph.add_edge(START, "setup")
    graph.add_conditional_edges("setup", _after_setup, ["discovery", "report"])
    graph.add_conditional_edges("discovery", _after_discovery, ["test_design", "report"])
    graph.add_conditional_edges(
        "test_design",
        lambda s: "report" if s.get("setup_error") else "script_generator",
        ["report", "script_generator"],
    )
    graph.add_conditional_edges(
        "script_generator", lambda s: "report" if s.get("setup_error") else "execution", ["report", "execution"]
    )
    graph.add_edge("execution", "failure_analysis")
    graph.add_edge("failure_analysis", "self_healing")
    graph.add_edge("self_healing", "report")
    graph.add_edge("report", END)
    return graph.compile(checkpointer=checkpointer)
