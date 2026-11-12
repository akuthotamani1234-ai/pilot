"""Run the full QA testing pipeline.

    python main.py https://example.com                     # test a website
    python main.py localhost:8765                          # test a site running on your computer
    python main.py https://github.com/user/repo            # download code, run it, test it
    python main.py C:\\path\\to\\my-project                  # run a local project, test it
    python main.py <source> --max-pages 10 --show-browser
    python main.py <source> --scope section                # site | section | page (default: decided from the link)
    python main.py --resume <run_id>                      # go on with a run that stopped, after its last finished stage

A run ALWAYS ends with a report. When an agent crashes, Ctrl+C is pressed, the web UI's Stop button is used or the run
hits RUN_TIME_LIMIT_MIN, the report is written from everything done so far (verdict "Insufficient Evidence", with the
reason first) and the baseline is not updated. The state after every agent is saved in runs/<run>/checkpoint.sqlite,
so --resume can go on from there (the file is deleted when a run finishes).
"""
import argparse
import json
import os
import re
import shutil
import signal
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlparse

import requests

from backend import cost, runctl
from backend.agents.setup_agent import is_github, is_local_project, project_name, stop_servers
from backend.config import settings
from backend.safety import UrlError, check_target, redact

# what the person reads: "The run was stopped while <stage>"
STAGE_TEXT = {"setup": "starting the app", "discovery": "exploring the website", "change_detection": "comparing with "
              "the last run", "test_design": "writing the test cases", "review_gate": "waiting for your review",
              "script_generator": "writing the test scripts",
              "execution": "running the tests", "failure_analysis": "analysing the failures",
              "self_healing": "repairing test scripts", "report": "writing the report",
              "save_baseline": "saving the baseline", "visual_check": "comparing the look with the approved one",
              "integrations": "sending the results to Slack / Jira"}
FAILING_VERDICTS = ("Not Ready", "Insufficient Evidence")  # --exit-code: the run fails a CI job (exit code 1)
# never written to runs/<run>/run_args.json (the test account is used for one run only, keys never leave .env)
SECRET_SETTINGS = {"test_username", "test_password", "test_totp_secret", "openai_api_key", "gemini_api_key",
                   "anthropic_api_key",
                   "github_token", "slack_webhook_url", "jira_email", "jira_api_token", "webhook_token",
                   "runs_dir", "baseline_dir", "workspace_dir"}


def ollama_ready() -> bool:
    """Ollama is running and the chosen model is installed."""
    try:
        probe = settings.ollama_url.replace("//localhost", "//127.0.0.1")  # skips a slow IPv6 attempt on Windows
        from backend.privacy import local_ai_request
        tags = local_ai_request("GET", f"{probe}/api/tags", timeout=2).json().get("models", [])
    except (requests.RequestException, ValueError):
        return False
    names = {m.get("name", "") for m in tags}
    return settings.llm_model in names or f"{settings.llm_model}:latest" in names


def normalize_url(src: str) -> str:
    if "://" in src:
        return src
    if src.startswith(("localhost", "127.")):
        return "http://" + src
    return "https://" + src


# ---------------------------------------------------------------- running the agents

@contextmanager
def _checkpointer(run_dir: Path):
    """The state after every agent goes to runs/<run>/checkpoint.sqlite (None: the package is missing - no resume)."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        print("  [run] langgraph-checkpoint-sqlite is not installed: this run can't be resumed later (--resume)")
        yield None
        return
    with SqliteSaver.from_conn_string(str(run_dir / "checkpoint.sqlite")) as saver:
        yield saver


def _remove_checkpoint(run_dir: Path) -> None:
    for name in ("checkpoint.sqlite", "checkpoint.sqlite-wal", "checkpoint.sqlite-shm", "resume.json"):
        try:
            (run_dir / name).unlink(missing_ok=True)
        except OSError:
            pass


def _resume_point(graph, config: dict, stage: str) -> str | None:
    """The checkpoint just BEFORE `stage` ran: --resume runs that stage again (it did not finish: crashed / stopped)."""
    try:
        for snap in graph.get_state_history(config):  # (newest first)
            if tuple(snap.next) == (stage,):
                return snap.config["configurable"]["checkpoint_id"]
    except Exception as e:
        print(f"  [run] could not find where to resume: {str(e)[:150]}")
    return None


def _why(stage: str, error: BaseException | None) -> tuple[str, str]:
    """(kind, plain-English reason) of a run that did not finish."""
    where = STAGE_TEXT.get(stage, stage or "starting")
    if runctl.stopping():
        return runctl.kind(), f"The run was stopped while {where}: {runctl.reason()}."
    if isinstance(error, KeyboardInterrupt):
        return "ctrl_c", f"The run was stopped while {where}: you pressed Ctrl+C."
    text = redact(str(error)).strip().splitlines()
    return "error", (f"The run stopped with an error while {where}: {type(error).__name__}"
                     + (f": {text[0][:300]}" if text else "") + ". Everything done before it is in this report.")


def _fallback_report(state: dict, run_dir: Path, error: BaseException) -> dict:
    """The report itself crashed: a minimal report.html + summary.json, so a run still always has a report."""
    reason = state.get("incomplete_reason") or "The run did not finish."
    detail = redact(f"{type(error).__name__}: {(str(error).splitlines() or [''])[0][:300]}")
    (run_dir / "report.html").write_text(f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Blow AI report</title></head>
<body style="font-family:'Segoe UI',system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 16px;line-height:1.6">
<h1>❔ We couldn't test enough</h1><p>{escape(reason)}</p>
<p>The full report could not be written either ({escape(detail)}). What was done is in the files of this run folder:
pages in app_map.json, test cases in test_cases.json, results in results.json.</p></body></html>""", encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps({
        "url": state.get("url"), "source": state.get("source"), "run_id": state.get("run_id"),
        "verdict": "Insufficient Evidence", "reasons": [reason, f"The report could not be written: {detail}"],
        "gates": [], "incomplete": True, "incomplete_reason": reason, "stopped_at": state.get("stopped_at", ""),
        "limits_hit": [], "pages": len(state.get("app_map", [])), "tests": len(state.get("results", [])),
        "test_cases": len(state.get("test_cases", [])), "coverage": {}, "working_well": [], "pass_rate": 0,
        "headline": {"emoji": "❔", "title": "We couldn't test enough", "text": reason},
        "finished": datetime.now().strftime("%Y-%m-%d %H:%M")}, indent=2), encoding="utf-8")
    return {"verdict": "Insufficient Evidence", "report_path": str(run_dir / "report.html")}


def run_pipeline(state: dict | None, run_dir: Path, run_id: str, resume: bool = False) -> dict:
    """Run the agents and return the final state - ALWAYS with a report (state["report_path"]).

    resume=True: go on from runs/<run_id>/checkpoint.sqlite (state is ignored), after the last finished stage."""
    from backend import graph as graph_mod
    from backend.agents.reporter import reporter_agent

    runctl.reset()
    (run_dir / "STOP").unlink(missing_ok=True)  # (a STOP file left by the web UI's Stop button of an earlier part)
    runctl.start_watchers(run_dir, settings.run_time_limit_min)
    graph_mod.CURRENT["stage"] = ""
    config = {"configurable": {"thread_id": run_id}, "recursion_limit": 50}
    last, error, cut, done = dict(state or {}), None, False, False
    with _checkpointer(run_dir) as saver:
        graph = graph_mod.build_graph(saver, discovery_only=settings.discovery_only)
        start = state
        if resume:
            if saver is None:
                raise SystemExit("This run can't be resumed: langgraph-checkpoint-sqlite is not installed.")
            point = (json.loads((run_dir / "resume.json").read_text(encoding="utf-8")).get("checkpoint_id")
                     if (run_dir / "resume.json").exists() else None)
            if point:
                config["configurable"]["checkpoint_id"] = point
            snap = graph.get_state(config)
            if not snap.values:
                raise SystemExit(f"This run has no saved state to resume ({run_dir / 'checkpoint.sqlite'}).")
            if not snap.next:
                raise SystemExit("This run already finished - there is nothing to resume.")
            last, start = dict(snap.values), None
            print(f"  [run] resuming before: {', '.join(STAGE_TEXT.get(n, n) for n in snap.next)}")
            if any(n not in ("report", "save_baseline", "integrations") for n in snap.next):
                from backend.agents.discovery import restore_login
                note = restore_login(last)
                if note:
                    print(f"  [run] {note}")
        try:
            for s in graph.stream(start, config, stream_mode="values", durability="sync"):
                last = s
                if runctl.stopping():
                    if not s.get("report_path"):
                        cut = True
                        break
                    runctl.finished()  # (the report is written already: the run ends normally, with its baseline)
            done = not cut
        except (Exception, KeyboardInterrupt) as e:
            error, cut = e, True
            if not isinstance(e, KeyboardInterrupt):
                traceback.print_exc()
        runctl.finished()  # (no timer may interrupt the report from here on)
        stage = graph_mod.CURRENT["stage"]
        if cut and saver is not None:
            point = _resume_point(graph, config, stage)
            if point:
                (run_dir / "resume.json").write_text(json.dumps({"checkpoint_id": point, "stage": stage}),
                                                     encoding="utf-8")
                print(f"  [run] to go on later from {STAGE_TEXT.get(stage, stage)}:  python main.py --resume {run_id}")

    if done:
        _remove_checkpoint(run_dir)  # (finished: nothing to resume - the run's own files hold the results)
        return last
    if last.get("report_path"):  # (it failed after the report - while saving the baseline): the report stands
        print(f"  [run] the report was written; the baseline was not updated ({type(error).__name__ if error else 'stopped'})")
        return last
    kind, reason = _why(stage, error)
    last = dict(last, incomplete=True, incomplete_reason=reason, stop_kind=kind, stopped_at=stage,
                log=last.get("log", []) + [reason])
    print(f"\n  [run] {reason}\n  [run] writing the report with what was done so far ...")
    try:
        last.update(reporter_agent(last))
    except Exception as e:
        traceback.print_exc()
        last.update(_fallback_report(last, run_dir, e))
    return last


# ---------------------------------------------------------------- command line

def _apply(opts: dict) -> None:
    """Command-line options -> settings."""
    if opts.get("discovery_only"):
        settings.discovery_only = True
    if opts.get("max_pages") is not None:  # (0 = no limit, up to HARD_PAGE_CAP - also when .env says otherwise)
        settings.max_pages = opts["max_pages"]
    if opts.get("max_depth") is not None:
        settings.max_depth = opts["max_depth"]
    if opts.get("show_browser"):
        settings.headless = False
    if opts.get("start_cmd"):
        settings.start_cmd = opts["start_cmd"]
    if opts.get("port"):
        settings.app_port = opts["port"]
    if opts.get("max_heal") is not None:
        settings.max_heal_rounds = opts["max_heal"]
    if opts.get("reuse_tests"):
        settings.reuse_tests = True
    if opts.get("scope"):  # (overrides CRAWL_SCOPE)
        settings.crawl_scope = opts["scope"]
    if opts.get("env"):  # (overrides TEST_ENVIRONMENT)
        settings.environment = opts["env"]
    if opts.get("section"):  # only this part of the website
        settings.section_path = opts["section"]
    if opts.get("incremental"):
        settings.incremental = True
    if opts.get("allow_actions"):
        settings.allow_actions = [a.strip().lower() for a in opts["allow_actions"].split(",") if a.strip()]
    if opts.get("confirm_writes"):
        settings.confirm_writes = True


def _decide_writes(url: str) -> None:
    """Staging changes data (forms sent, records created and deleted) - on a host that does not look like a test copy
    only after the second confirmation. The decision is printed and goes into the report."""
    from backend.safety import looks_like_test_host
    if settings.environment != "staging":
        settings.writes_ok, settings.writes_note = False, ""
        return
    host = urlparse(url).hostname or "localhost"  # (a GitHub / folder project runs on this PC)
    settings.writes_ok = looks_like_test_host(host) or settings.confirm_writes
    settings.writes_note = (
        "Staging: forms are sent and records created, edited and deleted (tagged qa-<run>, cleaned up after)"
        + (f"; also allowed: {', '.join(settings.allow_actions)}" if settings.allow_actions else "") + "."
        if settings.writes_ok else
        f"Staging was chosen, but {host} does not look like a test copy and the second confirmation was not given "
        "(CONFIRM_WRITES=1 / --confirm-writes): no data was changed - forms were only checked.")
    print(f"  [run] {settings.writes_note}")


def _on_ctrl_c(signum, frame):
    """1st Ctrl+C: stop at the next safe point and write the report. 2nd: stop at once (the report is still written)."""
    if runctl.stopping():
        raise KeyboardInterrupt
    runctl.request_stop("ctrl_c", "you pressed Ctrl+C")


def main():
    try:  # Windows consoles: never crash on special characters
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Agentic AI website tester")
    ap.add_argument("source", nargs="?", help="Website URL, GitHub link, or local project folder "
                                              "(leave empty and it will ask you)")
    ap.add_argument("--max-pages", type=int, help=f"Max pages to visit (default {settings.max_pages})")
    ap.add_argument("--max-depth", type=int, help=f"How many clicks deep to go (default {settings.max_depth})")
    ap.add_argument("--show-browser", action="store_true", help="Watch the browser while it works")
    ap.add_argument("--start-cmd", help='Command to start a code project, e.g. "npm run dev -- --port {port}"')
    ap.add_argument("--port", type=int, help="Port the code project should run on")
    ap.add_argument("--max-heal", type=int, help=f"Self-healing rounds (default {settings.max_heal_rounds})")
    ap.add_argument("--env", choices=("test", "staging", "production"),
                    help="production: nothing is ever sent · test (default): forms only checked · staging: forms are "
                         "sent, records created -> edited -> deleted (tagged, cleaned up)")
    ap.add_argument("--allow-actions", metavar="LIST",
                    help="staging only: also allow delete, logout, password, pay (pay also needs TEST_PAYMENT=1)")
    ap.add_argument("--confirm-writes", action="store_true",
                    help="staging on a host that does not look like a test copy: I confirm data may be changed")
    ap.add_argument("--section", metavar="PATH",
                    help="only this part of the website, e.g. /electronics (very large sites: one part per run, then "
                         "--merge the reports)")
    ap.add_argument("--incremental", action="store_true",
                    help="with a baseline: fully test only the pages that are new or changed, smoke-check the rest")
    ap.add_argument("--merge", nargs="+", metavar="RUN",
                    help="combine the reports of these runs (run folder names) into one coverage view")
    ap.add_argument("--scope", choices=("site", "section", "page"),
                    help="What to test (default: decided from the link, CRAWL_SCOPE=auto): site = the entire website, "
                         "section = the pages under the link's folder + what their content links to, page = only it")
    ap.add_argument("--name", help="Baseline name for this site (use the same name to compare runs)")
    ap.add_argument("--no-open", action="store_true", help="Don't open the report in the browser at the end")
    ap.add_argument("--discovery-only", action="store_true",
                    help="Inventory website components only; no generated tests, baseline updates or integrations")
    ap.add_argument("--fresh", action="store_true", help="Ignore the saved baseline and generate all tests again")
    ap.add_argument("--reuse-tests", action="store_true",
                    help="Regression run: run the test scripts of the last run of this site again (no new tests)")
    ap.add_argument("--resume", metavar="RUN_ID",
                    help="Go on with a run that stopped (crashed, Ctrl+C, Stop button, time limit), after its last "
                         "finished stage. The test account is not saved: give it again in .env / TEST_USERNAME.")
    ap.add_argument("--my-test", action="append", metavar="TEXT",
                    help='Your own test in plain English, kept for this website (repeat for more), e.g. --my-test '
                         '"Search for Blue Top and add it to the cart - the cart shows it"')
    ap.add_argument("--recheck", nargs="+", metavar="ARG",
                    help="Re-check after a fix: RUN [TEST ...] runs only these tests of an earlier run again (no TEST: "
                         "every bug and open question it found) -> fixed / still failing")
    ap.add_argument("--exit-code", action="store_true",
                    help="CI: exit with code 1 when the verdict is 'Not Ready' or 'Insufficient Evidence' (else 0)")
    ap.add_argument("--approve-visual", metavar="RUN",
                    help="Approve the new look of the pages that changed in this run (visual check): later runs "
                         "compare with it")
    args = ap.parse_args()
    if args.discovery_only and (args.fresh or args.reuse_tests or args.my_test or args.recheck or args.merge
                               or args.approve_visual or args.resume):
        ap.error("--discovery-only cannot be combined with baseline, test-editing or resume options; resume uses the saved mode.")
    if args.recheck:
        from backend import recheck as rc
        run_dir = settings.runs_dir / Path(args.recheck[0]).name
        tests = args.recheck[1:] or rc.tests_of(run_dir, [f.get("id") for f in rc._json(run_dir / "failures.json", [])])
        if not tests:
            print(f"\nNothing to re-check in {run_dir}: only bugs and open questions found by a test can be re-checked.")
            sys.exit(2)
        print(f"\nRe-checking {len(tests)} test(s) of {run_dir.name} against the website as it is now ...")
        out = rc.recheck(run_dir, tests)
        if out.get("note"):
            print(f"  [recheck] {out['note']}")
        for n, r in out["results"].items():
            print(f"  {r['verdict'].upper():14} {n}" + (f"\n                 {r['error'][:200]}" if r["error"] else ""))
        return
    if args.approve_visual:
        from backend.visual import approve
        run_dir = settings.runs_dir / Path(args.approve_visual).name
        try:
            n = approve(run_dir)
        except (OSError, ValueError, KeyError) as e:
            print(f"\nThis run has no visual check to approve ({run_dir}): {e}")
            sys.exit(2)
        print(f"\nApproved the new look of {n} page(s) - the next runs compare with it.")
        return
    if args.merge:
        from backend.merge import merge_runs
        out = merge_runs([settings.runs_dir / Path(r).name for r in args.merge], settings.runs_dir)
        print(f"\nMerged {len(args.merge)} run(s): {out / 'report.html'}")
        return
    signal.signal(signal.SIGINT, _on_ctrl_c)
    if hasattr(signal, "SIGBREAK"):  # (Windows: Ctrl+Break)
        signal.signal(signal.SIGBREAK, _on_ctrl_c)

    if args.resume:
        run_id = Path(args.resume).name
        run_dir = settings.runs_dir / run_id
        try:
            saved = json.loads((run_dir / "run_args.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"\nThere is no run to resume at {run_dir} (run_args.json is missing).")
            sys.exit(2)
        if saved.get("code_project"):
            print("\nResuming is not supported for a GitHub / folder project yet (its app was stopped and would start "
                  "on a new address) - please start a new run.")
            sys.exit(2)
        for k, v in saved.get("settings", {}).items():  # the settings of the first part (never secrets)
            if hasattr(settings, k) and k not in SECRET_SETTINGS:
                setattr(settings, k, v)
        source, url = saved["source"], saved["url"]
    else:
        _apply(vars(args))
        source = (args.source or "").strip()
        while not source:  # no URL given on the command line -> just ask for it
            print("\n=== Agentic AI Website Tester ===")
            source = input("Enter the website URL to test (or a GitHub link / project folder): ").strip("﻿ \t\"")
        from backend.agents.discovery import unwrap_link
        if unwrap_link(source) != source:  # a link copied from Bing / Google results
            source = unwrap_link(source)
            print(f"  (that was a search-result link - testing the real website: {source})")
        if settings.discovery_only and (is_github(source) or is_local_project(source)):
            ap.error("--discovery-only accepts a website URL, not a repository or project folder")
        if is_github(source) or is_local_project(source):
            url = source                      # real URL is filled in by the Setup Agent
            site_key = project_name(source)
        else:
            url = normalize_url(source)
            try:
                check_target(url)  # http(s) only, no password in the address, never a cloud metadata address
            except UrlError as e:
                print(f"\nThis address can't be tested: {e}")
                sys.exit(2)
            p = urlparse(url)
            if settings.section_path and p.path in ("", "/"):  # (--section: start in that part of the website)
                url = url.rstrip("/") + "/" + settings.section_path.strip("/")
            site_key = p.hostname + (f"_{p.port}" if p.port else "")
        site_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.name or site_key)

        from backend import my_tests
        if args.fresh:  # (your own tests are yours, not the last run's: they stay)
            keep = my_tests.load(site_key)
            shutil.rmtree(settings.baseline_dir / site_key, ignore_errors=True)
            if keep:
                my_tests.save(site_key, [t["text"] for t in keep])
        if not settings.discovery_only and os.environ.get("QA_MY_TESTS_SET") == "1":  # (the chat's box: what is in it is the list)
            my_tests.save(site_key, my_tests.lines(os.environ.get("QA_MY_TESTS", "")))
        if args.my_test:
            my_tests.add(site_key, args.my_test)
        if my_tests.load(site_key):
            print(f"  [run] your own tests for this website: {len(my_tests.load(site_key))}")

        run_id = f"{site_key}_{datetime.now():%Y%m%d_%H%M%S}"
        run_dir = settings.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

    if settings.discovery_only:
        settings.auto_register = False
        settings.llm_provider, settings.llm_model, settings.vision = "none", "", "off"
        settings.environment, settings.writes_ok, settings.confirm_writes = "production", False, False
        settings.allow_actions, settings.test_payment = [], False
        settings.test_username = settings.test_password = settings.test_totp_secret = ""
        settings.test_accounts = []
        settings.writes_note = "Discovery only: no login submission, account creation, form filling or functional tests."
    if not args.resume:
        _decide_writes(url)
    if settings.llm_provider == "ollama" and not ollama_ready():
        print(f"  [llm] Ollama is not running at {settings.ollama_url} (or model '{settings.llm_model}' is not pulled).\n"
              f"        Start it with:  ollama serve   and   ollama pull {settings.llm_model}\n"
              f"        Continuing WITHOUT AI (rule-based tests).")
        if os.environ.get("QA_ALLOW_RULES_FALLBACK", "1") == "0":
            raise SystemExit("Selected AI is unavailable. No rules fallback was approved; the run did not start.")
        settings.llm_provider, settings.llm_model = "none", ""
    contract_json = os.environ.get("QA_CONTRACT_JSON", "")
    if contract_json.strip() and not args.resume:
        from backend.qa_contracts import parse_contract
        private_contract_dir = run_dir / ".private"
        private_contract_dir.mkdir(exist_ok=True)
        (private_contract_dir / "qa_contract.json").write_text(parse_contract(contract_json).model_dump_json(indent=2), encoding="utf-8")
    cost.set_run_dir(run_dir, resume=bool(args.resume))
    if not args.resume:  # what --resume needs to go on the same way (no password, no key, no test account)
        (run_dir / "run_args.json").write_text(json.dumps({
            "source": source, "url": url, "site_key": site_key, "run_id": run_id,
            "code_project": bool(is_github(source) or is_local_project(source)),
            "settings": {k: v for k, v in vars(settings).items() if k not in SECRET_SETTINGS}}, indent=2),
            encoding="utf-8")

    ai = f"{settings.llm_provider} / {settings.llm_model}" if settings.llm_provider != "none" else "none (rule-based)"
    print(f"\nSource: {source}\nLLM:    {ai}\nOutput: {run_dir}\n")

    try:
        final = run_pipeline(None if args.resume else
                             {"source": source, "url": url, "site_key": site_key, "run_id": run_id,
                              "run_dir": str(run_dir), "discovery_only": settings.discovery_only,
                              "contract_only": os.environ.get("QA_CONTRACT_ONLY") == "1",
                              "log": [], "heal_round": 0},
                             run_dir, run_id, resume=bool(args.resume))
    except SystemExit as e:
        print(f"\n{e}")
        sys.exit(2)
    finally:
        stop_servers()  # always stop an app we started, even if something crashed
        # the saved login (session cookies of the test account) is only needed while the run is going
        shutil.rmtree(run_dir / ".private", ignore_errors=True)
        (run_dir / "STOP").unlink(missing_ok=True)

    print("\n" + "\n".join(f"  - {l}" for l in final.get("log", [])))

    results = final.get("results", [])
    n = {k: sum(r["outcome"] in ks for r in results) for k, ks in
         (("passed", ("passed",)), ("failed", ("failed", "error")), ("inconclusive", ("inconclusive",)),
          ("skipped", ("skipped",)))}
    report = Path(final["report_path"]).resolve()
    print("\n" + "=" * 60)
    print("  TEST STOPPED - REPORT OF WHAT WAS DONE" if final.get("incomplete") else
          "  DISCOVERY COMPLETED - NO FUNCTIONAL TESTS RUN" if settings.discovery_only else "  TEST COMPLETED")
    print("=" * 60)
    print(f"  Website : {url}")
    print(f"  Pages   : {len(final.get('app_map', []))} visited")
    print(f"  Tests   : {len(results)} single tests - {n['passed']} passed, {n['failed']} failed, "
          f"{n['inconclusive']} inconclusive, {n['skipped']} skipped")
    try:  # the headline of the report: functional test cases (link / page / input checks are not in it)
        h = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))["headline"]
        print(f"  Functional test cases: {h['passed']} of {h['of']} passed ({h['percent']}%)")
    except (OSError, ValueError, KeyError):
        pass
    print(f"  VERDICT : {final['verdict']}")
    if final.get("incomplete"):
        print(f"  WHY     : {final['incomplete_reason']}")
    c = cost.totals(cost._calls)
    n_cases = len(final.get("test_cases", []))
    print(f"  AI cost : {cost.fmt_usd(c['cost_usd'])} total, "
          f"{cost.fmt_usd(c['cost_usd'] / n_cases if n_cases else 0)} per test case ({c['calls']} AI calls)")
    print(f"  Report  : {report}")
    print(f"  Open    : {report.as_uri()}   (Ctrl+click if the browser did not open)")
    print("=" * 60 + "\n")

    if not args.no_open:
        print("Opening the report in your browser...")
        try:
            os.startfile(report)  # noqa: S606  (Windows: our own report.html, opened with the default browser)
        except (AttributeError, OSError):
            import webbrowser  # other systems
            webbrowser.open(report.as_uri())
    if args.exit_code and (final.get("incomplete") or final.get("verdict") in FAILING_VERDICTS):
        sys.exit(1)


if __name__ == "__main__":
    main()
