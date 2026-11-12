"""Shared state passed between agents by the LangGraph orchestrator."""
from typing import Any, TypedDict


class QAState(TypedDict, total=False):
    # ---- Input
    discovery_only: bool
    contract_only: bool
    source: str            # what the user gave: a URL, a GitHub link, or a local folder
    url: str               # the website URL that will be tested
    run_id: str
    run_dir: str
    site_key: str          # name used for the baseline folder (same site => same key)

    # ---- Setup Agent (only when code was given)
    project: dict[str, Any]          # repo path, detected type, start command
    setup_error: str

    # ---- Discovery Agent
    app_map: list[dict[str, Any]]
    crawl_issues: list[dict[str, Any]]
    login: dict[str, Any]            # found a login form? outcome + evidence (never the password), note for the user
    crawl: dict[str, Any]            # route coverage: visited / not visited (page limit) / skipped / blocked
    roles: dict[str, Any]            # several user roles (TEST_ACCOUNTS): what each role may open (roles.json)

    # ---- Change Detection Agent
    changes: dict[str, Any]          # first_run, new / changed / removed / unchanged pages
    visual: dict[str, Any]           # visual check (backend/visual.py): pages the same / changed / new (visual.json)

    # ---- Test Design Agent
    test_cases: list[dict[str, Any]]
    cases_left_out: int              # designed test cases left out by MAX_TEST_CASES (the report lists the limit)

    # ---- Script Generator Agent
    scripts: list[str]
    script_sources: dict[str, str]   # file name -> "reused" | "llm" | "template" | "added"
    script_errors: list[dict[str, Any]]

    # ---- Execution Agent
    results: list[dict[str, Any]]
    rerun_only: list[str]            # set by Self-Healing: only re-run these tests

    # ---- Failure Analysis Agent
    failures: list[dict[str, Any]]

    # ---- Self-Healing Agent
    heal_round: int
    healing_log: list[dict[str, Any]]
    unhealable: list[str]            # tests we already tried and could not heal

    # ---- Report Agent
    verdict: str
    report_path: str

    # ---- A run that did not finish (main.py): it crashed, was stopped, or hit RUN_TIME_LIMIT_MIN
    incomplete: bool
    incomplete_reason: str           # plain English, shown first in the report
    stop_kind: str                   # error | ctrl_c | user_stop | run_time_limit
    stopped_at: str                  # the agent that was running

    log: list[str]

    # Native mobile adapter: the web fields above retain their original meanings.
    target_type: str
    config: dict[str, Any]
    environment: dict[str, Any]
    screens: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    discovery_issues: list[dict[str, Any]]
    unvisited: list[dict[str, Any]]
    execution_duration_s: float
    ai_unavailable: bool
    ai_warnings: list[str]
    android_design_scope: dict[str, Any]
    # User-like testing of a test build (android_interact.py): replay-verified flows, what was tried, findings
    auto_flows: list[dict[str, Any]]
    interaction: dict[str, Any]
    # A website's bot check in Android Chrome: blocked (with the plain message) or how it finished
    bot_check: dict[str, Any]
