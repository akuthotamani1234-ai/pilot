"""Central settings. Values come from environment variables (or a .env file)."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Tiny .env loader so we don't need an extra dependency."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0]  # allow inline comments:  MAX_PAGES=25   # comment
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass
class Settings:
    # LLM: "openai", "gemini", "anthropic", "ollama" or "none" (rule-based, no AI)
    # Default is Ollama: the model runs on your own machine, so no page data is sent to a cloud AI.
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama").lower()
    llm_model: str = os.getenv("LLM_MODEL", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    # how much text Ollama reads per request (its own default, ~4k tokens, silently cuts long page summaries)
    ollama_num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
    # seconds to wait for one cloud AI answer (free-tier Gemini can be slow); a timed-out call is retried once
    llm_timeout: int = int(os.getenv("LLM_TIMEOUT", "240"))
    # the AI LOOKS at screenshots: what every page shows, and before / after pictures of every failed test (website bug
    # or test mistake?). auto = on with a cloud AI (and an Ollama vision model), on, off. Pages with a password box are
    # never sent.
    vision: str = os.getenv("VISION", "auto").lower()
    vision_max_failures: int = int(os.getenv("VISION_MAX_FAILURES", "60"))  # failed tests looked at per run (cost)

    # A crawl-only run inventories pages without designing or executing tests.
    discovery_only: bool = False

    # Crawl limits (safety + cost control)
    # 0 = no limit -> visit EVERY page of the site (a safety cap of HARD_PAGE_CAP still applies,
    # because some sites generate endless URLs, e.g. calendars / search pages)
    max_pages: int = int(os.getenv("MAX_PAGES", "0"))
    max_depth: int = int(os.getenv("MAX_DEPTH", "0"))
    hard_page_cap: int = int(os.getenv("HARD_PAGE_CAP", "500"))
    # What to test. "auto" decides from the link: home page -> entire website, one folder (site.com/shop) ->
    # limited pages (that app), deeper / exact address -> that specific page. "site" / "section" / "page" force one.
    crawl_scope: str = os.getenv("CRAWL_SCOPE", "auto").lower()
    page_timeout_ms: int = int(os.getenv("PAGE_TIMEOUT_MS", "20000"))
    crawl_time_limit_min: float = float(os.getenv("CRAWL_TIME_LIMIT_MIN", "30"))     # stop exploring after this
    # the WHOLE run (all agents): after this the run stops and the report is written with what was done (0 = no limit)
    run_time_limit_min: float = float(os.getenv("RUN_TIME_LIMIT_MIN", "90"))
    finalization_reserve_s: float = float(os.getenv("FINALIZATION_RESERVE_S", "120"))
    discovery_budget_fraction: float = max(0.1, min(0.8, float(os.getenv("DISCOVERY_BUDGET_FRACTION", "0.4"))))
    # polite speed on a PUBLIC website: page loads per second while exploring (0 = no limit; slower after HTTP 429/503)
    max_requests_per_sec: float = float(os.getenv("MAX_REQUESTS_PER_SEC", "2"))
    # only this part of the website (--section /electronics), else decided from the link
    section_path: str = os.getenv("SECTION", "")
    # with a baseline: fully test only new / changed pages (their design or controls changed), smoke-check the rest
    incremental: bool = os.getenv("INCREMENTAL", "false").lower() == "true"
    # every page also at phone width (390 x 844): controls only a phone shows are tested, layout problems reported
    mobile_check: bool = os.getenv("MOBILE_CHECK", "true").lower() != "false"
    # Chromium: how much of the website's own JavaScript the run used (auto = on staging / a site on this PC)
    js_coverage: str = os.getenv("JS_COVERAGE", "auto").lower()
    max_interactions_per_page: int = int(os.getenv("MAX_INTERACTIONS_PER_PAGE", "15"))  # clicks to find hidden pages
    explore_repeated_controls: bool = os.getenv("EXPLORE_REPEATED_CONTROLS", "false").lower() == "true"
    pattern_samples: int = int(os.getenv("PATTERN_SAMPLES", "0"))  # 0 = visit every route; >0 samples each pattern
    max_test_cases: int = int(os.getenv("MAX_TEST_CASES", "300"))  # test cases per run (most important first)
    test_retries: int = int(os.getenv("TEST_RETRIES", "0"))        # optional re-runs of failed tests (0 = once only)
    llm_budget_usd: float = float(os.getenv("LLM_BUDGET_USD", "2"))  # AI cost limit per run; then built-in rules
    headless: bool = os.getenv("HEADLESS", "true").lower() != "false"
    slow_mo_ms: int = int(os.getenv("SLOW_MO_MS", "1000"))  # one delay per watched user action; headless stays fast
    # save a video of the test browsers in runs/<run>/videos (one per browser window; large files - off by default)
    record_video: bool = os.getenv("RECORD_VIDEO", "false").lower() == "true"
    # a one-time code / CAPTCHA at login, with a visible browser: wait this long for a PERSON to complete it (0 = never)
    human_wait_s: int = int(os.getenv("HUMAN_WAIT_S", "180"))

    # Links containing these words are never clicked/visited (avoid destructive actions)
    unsafe_link_words: list = field(default_factory=lambda: [
        "logout", "log-out", "signout", "sign-out", "delete", "remove",
        "unsubscribe", "deactivate", "cancel-account",
    ])

    # Optional robustness checks: try each input box with many values (empty, too long, symbols, emoji, ...).
    # These are typed but never submitted. Normal functional checks still exercise meaningful input behaviors.
    data_tests: bool = os.getenv("DATA_TESTS", "false").lower() != "false"
    data_max_fields: int = int(os.getenv("DATA_MAX_FIELDS", "4"))   # input boxes per page

    # Parallel test runs: how many browsers run tests at the same time (needs pytest-xdist).
    # When you watch the tests in Chrome: ONE window shows every test, one after another (slower, easy to follow).
    test_workers: int = int(os.getenv("TEST_WORKERS", "4"))

    # Self-healing: how many fix-and-rerun rounds before giving up
    max_heal_rounds: int = int(os.getenv("MAX_HEAL_ROUNDS", "2"))
    # Regression run: run the test scripts saved by the last run of this site again, instead of writing new ones
    reuse_tests: bool = os.getenv("REUSE_TESTS", "false").lower() == "true"

    # A test account for login forms (optional). With it, "login works" is tested; without it only
    # "a wrong password is rejected". Read by the tests at run time - never written into the test files.
    test_username: str = os.getenv("TEST_USERNAME", "")
    test_password: str = os.getenv("TEST_PASSWORD", "")
    # the test account has 2-step verification with an authenticator app: its setup key (base32, or the otpauth://
    # address of the QR code) - the login code is made from it like the app makes it. A secret like the password.
    test_totp_secret: str = os.getenv("TEST_TOTP_SECRET", "")
    # several user roles (optional): role:user:password, comma-separated (admin:a@x.test:Pw1,viewer:v@x.test:Pw2).
    # The first is the main account when TEST_USERNAME is empty; every other role explores the app once more and its
    # access is tested (a lower role must not open an admin page). Secrets: never saved, never shown.
    test_accounts: list = field(default_factory=lambda: [
        {"role": p[0].strip(), "username": p[1].strip(), "password": p[2]}
        for p in (a.split(":", 2) for a in os.getenv("TEST_ACCOUNTS", "").split(",") if a.count(":") >= 2)
        if p[0].strip() and p[1].strip() and p[2]])
    # no test account given and the website has a login -> sign up ONCE with fake test data (@example.com),
    # save it ENCRYPTED in accounts/<site>.json and log in with it. Off unless you allow it (the web UI asks per run):
    # creating accounts on a website is a real change to that website.
    login_enabled: bool = os.getenv("QA_LOGIN_ENABLED", "1") != "0"
    use_saved_account: bool = os.getenv("USE_SAVED_ACCOUNT", "1") != "0"
    auto_register: bool = os.getenv("AUTO_REGISTER", "false").lower() == "true"
    # Login overrides - only needed when the tester can't find the login by itself (all optional):
    login_url: str = os.getenv("LOGIN_URL", "")                    # the login page, if it is not linked from the start page
    login_user_selector: str = os.getenv("LOGIN_USER_SELECTOR", "")          # e.g. #email
    login_password_selector: str = os.getenv("LOGIN_PASSWORD_SELECTOR", "")  # e.g. #password
    login_submit_selector: str = os.getenv("LOGIN_SUBMIT_SELECTOR", "")      # e.g. button[type=submit]
    login_success_text: str = os.getenv("LOGIN_SUCCESS_TEXT", "")  # text only shown when logged in, e.g. "Dashboard"
    login_success_url: str = os.getenv("LOGIN_SUCCESS_URL", "")    # part of the address after login, e.g. /dashboard

    # Approved scope: the tester only opens the website's own host. Extra hosts that belong to the app
    # (e.g. a login on auth.example.com) can be allowed here, comma-separated; *.example.com allows sub-domains.
    allowed_hosts: list = field(default_factory=lambda: [
        h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()])
    # Paths to leave out of the crawl, comma-separated (e.g. /admin,/billing). Matched against the start of the path.
    exclude_paths: list = field(default_factory=lambda: [
        p.strip() for p in os.getenv("EXCLUDE_PATHS", "").split(",") if p.strip()])
    # test (default) | staging | production. Production needs the confirmation in the UI and keeps every safety rule:
    # nothing that changes data is ever sent. Test sends nothing either (forms are checked through a write guard); only
    # on staging forms ARE sent (tagged test data, cleaned up after) - backend/actions.py.
    environment: str = os.getenv("TEST_ENVIRONMENT", "test").lower()
    # test / staging only: the consequential actions that may be done too, comma-separated: delete, logout, password,
    # pay (pay also needs TEST_PAYMENT=1 - a payment provider's test mode). Empty = only saving / sending forms.
    allow_actions: list = field(default_factory=lambda: [
        a.strip().lower() for a in os.getenv("ALLOW_ACTIONS", "").split(",") if a.strip()])
    test_payment: bool = os.getenv("TEST_PAYMENT", "0").lower() in ("1", "true", "yes")
    # staging on a host that does not look like a test copy: data is only changed after this second confirmation
    confirm_writes: bool = os.getenv("CONFIRM_WRITES", "0").lower() in ("1", "true", "yes")
    # Human review between test design and the scripts: auto = on staging, on = always, off = never
    review: str = os.getenv("REVIEW", "auto").lower()
    review_timeout_s: int = int(os.getenv("REVIEW_TIMEOUT_S", "900"))  # how long the run waits for your answers
    # (set by main.py from the website's host: a test-looking host, or confirm_writes)
    writes_ok: bool = True
    writes_note: str = ""
    # Free text: business workflows / expected results / user roles you want covered (shown to the AI as requirements)
    requirements: str = os.getenv("QA_REQUIREMENTS", "")
    # Check links that go to OTHER websites (one GET request each, redirects not followed). false = never contact them.
    check_external_links: bool = os.getenv("CHECK_EXTERNAL_LINKS", "true").lower() != "false"

    # Visual regression (backend/visual.py): every page's picture and layout, at desktop and phone width, compared with
    # the APPROVED look of the website (baseline/<site>/visual/). A change is shown for a person to judge - never a
    # website bug by itself - and becomes the new look only when approved (or with VISUAL_AUTO_APPROVE=true).
    visual_check: bool = os.getenv("VISUAL_CHECK", "true").lower() != "false"
    visual_pixel_percent: float = float(os.getenv("VISUAL_PIXEL_PERCENT", "1"))  # changed share of a picture to report
    visual_move_px: int = int(os.getenv("VISUAL_MOVE_PX", "12"))  # an element that moved / resized more than this
    visual_max_pages: int = int(os.getenv("VISUAL_MAX_PAGES", "100"))  # pages compared per run
    visual_auto_approve: bool = os.getenv("VISUAL_AUTO_APPROVE", "false").lower() == "true"

    # Integrations (backend/integrations.py) - all optional, nothing is sent unless it is set here.
    # Slack: one message when a run finds an application defect at or above SLACK_MIN_SEVERITY (or is 'Not Ready')
    slack_webhook_url: str = os.getenv("SLACK_WEBHOOK_URL", "")
    slack_min_severity: str = os.getenv("SLACK_MIN_SEVERITY", "high").lower()
    # Jira: one issue per application defect at or above JIRA_MIN_SEVERITY (steps, expected / actual, screenshot)
    jira_url: str = os.getenv("JIRA_URL", "").rstrip("/")    # https://your-company.atlassian.net
    jira_email: str = os.getenv("JIRA_EMAIL", "")
    jira_api_token: str = os.getenv("JIRA_API_TOKEN", "")
    jira_project: str = os.getenv("JIRA_PROJECT", "")        # the project key, e.g. QA
    jira_issue_type: str = os.getenv("JIRA_ISSUE_TYPE", "Bug")
    jira_min_severity: str = os.getenv("JIRA_MIN_SEVERITY", "high").lower()
    jira_max_issues: int = int(os.getenv("JIRA_MAX_ISSUES", "10"))  # per run
    # POST /api/hooks/run (a deploy script / GitHub webhook starts a run in the open UI): only with this token
    webhook_token: str = os.getenv("WEBHOOK_TOKEN", "")
    webhook_test_url: str = os.getenv("WEBHOOK_TEST_URL", "")  # the website a hook without an address tests

    # Sandbox for the generated tests (they run in their own process with these limits)
    test_timeout_s: int = int(os.getenv("TEST_TIMEOUT_S", "180"))          # one test may take at most this long
    suite_timeout_s: int = int(os.getenv("SUITE_TIMEOUT_S", "3600"))       # the whole test run
    sandbox_memory_mb: int = int(os.getenv("SANDBOX_MEMORY_MB", "6144"))   # all browsers + pytest together
    sandbox_max_processes: int = int(os.getenv("SANDBOX_MAX_PROCESSES", "256"))

    # Release gates (the verdict is calculated from these rules - never by the AI)
    gate_block_severity: str = os.getenv("GATE_BLOCK_SEVERITY", "high").lower()     # website bugs at or above -> Not Ready
    gate_max_automation_errors: float = float(os.getenv("GATE_MAX_AUTOMATION_ERRORS", "0"))  # share of broken tests
    gate_login_required: bool = os.getenv("GATE_LOGIN_REQUIRED", "true").lower() != "false"  # app behind a login untested
    gate_min_public_pages: int = int(os.getenv("GATE_MIN_PUBLIC_PAGES", "2"))  # fewer usable pages -> not enough evidence

    # GitHub / local code input
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    server_start_timeout: int = int(os.getenv("SERVER_START_TIMEOUT", "180"))  # seconds
    start_cmd: str = os.getenv("START_CMD", "")      # override auto-detected start command
    app_port: int = int(os.getenv("APP_PORT", "0"))   # override port (0 = auto)

    runs_dir: Path = Path(os.getenv("RUNS_DIR", "runs"))
    baseline_dir: Path = Path(os.getenv("BASELINE_DIR", "baseline"))
    workspace_dir: Path = Path(os.getenv("WORKSPACE_DIR", "workspace"))


DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-flash-latest",
    "anthropic": "claude-sonnet-5-5",
    "ollama": "llama3.1",
}

CLOUD_MODEL_PREFIX = {"gemini": ("gemini",), "openai": ("gpt", "o1", "o3", "o4", "chatgpt"), "anthropic": ("claude",)}


def _model_fits(provider: str, model: str) -> bool:
    """False when the model clearly belongs to another provider (e.g. LLM_MODEL=gemini-... but provider=ollama)."""
    m = model.lower()
    if provider in CLOUD_MODEL_PREFIX:
        return m.startswith(CLOUD_MODEL_PREFIX[provider])
    return not any(m.startswith(p) for ps in CLOUD_MODEL_PREFIX.values() for p in ps)


settings = Settings()
if not settings.llm_model or not _model_fits(settings.llm_provider, settings.llm_model):
    settings.llm_model = DEFAULT_MODELS.get(settings.llm_provider, "")
if settings.test_accounts and not (settings.test_username and settings.test_password):  # the first role is the main one
    settings.test_username = settings.test_accounts[0]["username"]
    settings.test_password = settings.test_accounts[0]["password"]
    os.environ["TEST_USERNAME"], os.environ["TEST_PASSWORD"] = settings.test_username, settings.test_password
