"""Run one native Android QA pipeline in a child process."""

import argparse
import html
import json
import sys
import traceback
from pathlib import Path

from .android import AndroidEnvironmentError, validate_mobile_config
from .android_pipeline import reporter_agent

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"


def _read_config(path: Path) -> tuple[dict, Path]:
    path = path.resolve()
    try:
        relative = path.relative_to(RUNS.resolve())
    except ValueError as e:
        raise AndroidEnvironmentError("Android run configuration must be inside the runs folder.") from e
    if path.parent.name != ".private" or not path.is_file() or len(relative.parts) != 3:
        raise AndroidEnvironmentError("Android run configuration is missing or is not in a private run folder.")
    run_dir = path.parent.parent
    config = json.loads(path.read_text(encoding="utf-8"))
    config = validate_mobile_config(config)
    if config["app_mode"] == "apk":
        apk = Path(config.get("apk_path", "")).resolve()
        try:
            apk.relative_to((run_dir / ".private").resolve())
        except ValueError as e:
            raise AndroidEnvironmentError("The APK must be stored in this run's private upload folder.") from e
    return config, run_dir


def main() -> int:
    import signal

    from langgraph.checkpoint.sqlite import SqliteSaver

    from . import cost, runctl
    from .config import settings
    from .graph import build_graph
    from .safety import redact

    parser = argparse.ArgumentParser(description="Run native Android QA with Appium.")
    parser.add_argument("--config", required=True, help=argparse.SUPPRESS)
    parser.add_argument("--resume", action="store_true", help="Continue from this run's last SQLite checkpoint")
    args = parser.parse_args()
    try:
        config, run_dir = _read_config(Path(args.config))
    except (OSError, ValueError, AndroidEnvironmentError) as e:
        print("Android run configuration error: " + redact(str(e)), file=sys.stderr)
        return 2
    run_id = run_dir.name
    source = (f"Android Chrome {config['start_url']}" if config["app_mode"] == "web" else
              f"Android app {config['package_name']}" if config["package_name"] else "Uploaded Android APK")
    state = {
        "config": config,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "source": source,
        "target_type": "mobile",
        "log": [],
    }
    print(f"Source: {source}\nOutput: {run_dir}", flush=True)
    cost.set_run_dir(run_dir, resume=args.resume)
    runctl.reset()
    runctl.start_watchers(run_dir, settings.run_time_limit_min)

    def stopped(_signal, _frame):
        runctl.request_stop("ctrl_c", "Android run interrupted")

    signal.signal(signal.SIGINT, stopped)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, stopped)
    thread = {"configurable": {"thread_id": run_id}, "recursion_limit": 40}
    try:
        with SqliteSaver.from_conn_string(str(run_dir / ".private" / "checkpoint.sqlite")) as saver:
            graph = build_graph(checkpointer=saver, target_type="mobile")
            try:
                saved = graph.get_state(thread)
                if args.resume and saved.values and saved.values.get("test_cases"):
                    from .android_pipeline import execution_agent, failure_analysis_agent
                    # Discovery is not replayed: it may have created test accounts.
                    resumed = {**saved.values, "config": config, "incomplete": False,
                               "incomplete_reason": "", "stop_kind": "", "setup_error": None}
                    resumed.update(execution_agent(resumed))
                    resumed.update(failure_analysis_agent(resumed))
                    final = {**resumed, **reporter_agent(resumed)}
                elif args.resume and saved.values:
                    final = graph.invoke(None, thread) if saved.next else saved.values
                else:
                    final = graph.invoke(state, thread)
            except (Exception, KeyboardInterrupt) as e:
                state = {**state, **graph.get_state(thread).values}
                from .android_pipeline import failure_analysis_agent, read_jsonl, self_healing_agent

                partial = read_jsonl(run_dir / "android_results.jsonl")
                if partial:
                    state["results"] = partial
                    state.update(failure_analysis_agent(state))
                    state.update(self_healing_agent(state))
                state.update(
                    incomplete=True,
                    incomplete_reason=redact(str(e))[:300] or "Run interrupted",
                    setup_error="The Android pipeline did not finish.",
                )
                final = {**state, **reporter_agent(state)}
    except Exception as e:
        traceback.print_exc()
        message = redact(str(e))[:500]
        report_path = run_dir / "report.html"
        report_path.write_text(
            "<!doctype html><meta charset='utf-8'><h1>Insufficient Evidence</h1><p>" + html.escape(message) + "</p>",
            encoding="utf-8",
        )
        (run_dir / "summary.json").write_text(
            json.dumps(
                {
                    "target_type": "android",
                    "run_id": run_id,
                    "source": source,
                    "verdict": "Insufficient Evidence",
                    "incomplete": True,
                    "reasons": [message],
                }
            ),
            encoding="utf-8",
        )
        final = {"verdict": "Insufficient Evidence", "report_path": str(report_path)}
    finally:
        runctl.finished()
        (run_dir / "STOP").unlink(missing_ok=True)
    if not Path(final.get("report_path", "")).is_file():
        return 1
    print("Verdict: " + final.get("verdict", "Insufficient Evidence"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
