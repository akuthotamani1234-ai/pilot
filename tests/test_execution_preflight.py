"""A Jira execution that cannot automate anything is never started (reported 26 Nov 2026: 18 approved test cases ran,
the execution said 'Complete', and every case was 'Not automated: your own tests need an AI ... choose an AI in the
chat'). Root cause: with privacy local-only, privacy.select_provider turns the configured cloud AI (LLM_PROVIDER) into
'none' without an error, the Execution Center sent no AI choice, and nothing checked before the run."""
# ruff: noqa: F811  (pytest fixtures shared from test_requirements_execution are parameters here)
import http.server
import json
import threading

import pytest

from backend import execution_preflight as pre, privacy
from backend.atlassian import bridge
from tests.test_requirements_execution import _accept, api  # noqa: F401

pytestmark = pytest.mark.real_preflight


@pytest.fixture
def policy(tmp_path, monkeypatch):
    monkeypatch.setattr(privacy, "POLICY_PATH", tmp_path / "privacy.json")
    return lambda mode: privacy.save_policy(privacy.PrivacyPolicy(mode=mode, cloud_consent=mode == "cloud"))


def test_a_cloud_ai_under_local_only_privacy_is_reported_not_silently_dropped(policy, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")
    s = pre.ai_status()  # (the Execution Center's old default: 'as configured')
    assert s["provider"] == "none" and not s["ready"] and s["recovery"] == "allow_cloud"
    assert "local-only" in s["reason"]
    s = pre.ai_status("openai")  # (chosen explicitly: refused by privacy, with the way out)
    assert not s["ready"] and s["recovery"] == "allow_cloud"
    policy("cloud")
    s = pre.ai_status("openai", "gpt-4o-mini")
    assert s["ready"] and s["provider"] == "openai" and s["model"] == "gpt-4o-mini"
    monkeypatch.delenv("OPENAI_API_KEY")
    s = pre.ai_status("openai")
    assert not s["ready"] and s["recovery"] == "api_key"
    assert pre.ai_status("openai", api_key="sk-for-this-run")["ready"]  # (a key for this run only)
    assert not pre.ai_status("none")["ready"]


def _ready_probe(login=False):
    return lambda url, timeout_s=25: {"ok": True, "browser": True, "login_form": login, "title": "", "final_url": url,
                                      "error": ""}


def test_no_execution_is_created_when_no_ai_can_automate_the_selected_cases(api, policy, monkeypatch):
    from backend import requirements_api as rapi
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")
    monkeypatch.setattr(rapi, "PREFLIGHT_PROBE", _ready_probe())
    launched = []
    monkeypatch.setattr(api.server, "_launch_run", lambda req, caller: launched.append(req) or {"id": 1})
    _accept(api, 2)
    api.client.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    body = {"strategy": "requirements", "scope": {"test_case_ids": ["TC-QPL-2-1", "TC-QPL-2-2"]},
            "target": {"url": "https://www.saucedemo.com/", "authorized": True, "test_username": "standard_user",
                       "test_password": "secret_sauce"}}
    check = api.client.post("/api/requirements/executions/preflight", headers=api.H, json=body).json()
    assert not check["ok"] and check["needs_ai"]
    ai = next(p for p in check["problems"] if p["code"] == "ai")
    assert ai["message"].startswith("An AI provider is required to automate these 2 test cases")
    assert ai["recovery"] == "allow_cloud" and "secret_sauce" not in json.dumps(check)
    r = api.client.post("/api/requirements/executions", headers=api.H, json=body)
    assert r.status_code == 409 and "AI provider is required" in r.json()["detail"]
    assert launched == [] and api.client.get("/api/requirements/executions", headers=api.H).json()["executions"] == []
    # with the AI allowed (privacy) the same selection starts, and the run gets exactly the AI that was checked
    policy("cloud")
    r = api.client.post("/api/requirements/executions", headers=api.H, json=body)
    assert r.status_code == 200, r.text
    assert launched[0].llm_provider == "openai"


def test_a_website_with_a_login_form_needs_a_test_account_before_the_run(api, policy, monkeypatch):
    from backend import requirements_api as rapi
    policy("cloud")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-used")
    monkeypatch.setattr(rapi, "PREFLIGHT_PROBE", _ready_probe(login=True))
    _accept(api, 1)
    api.client.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    body = {"strategy": "requirements", "scope": {"test_case_ids": ["TC-QPL-2-1"]},
            "target": {"url": "https://www.saucedemo.com/", "authorized": True}}
    check = api.client.post("/api/requirements/executions/preflight", headers=api.H, json=body).json()
    assert [p["code"] for p in check["problems"]] == ["login"] and check["problems"][0]["recovery"] == "enter_account"
    body["target"].update(test_username="standard_user", test_password="secret_sauce")
    assert api.client.post("/api/requirements/executions/preflight", headers=api.H, json=body).json()["ok"]


class _Pages(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        html = {"/login": "<form><input name=u><input type=password name=p><button>Login</button></form>",
                "/open": "<h1>Welcome</h1>",
                "/spa": "<div id=root></div><script>setTimeout(() => document.getElementById('root').innerHTML ="
                        " '<input type=password>', 300)</script>"}[self.path]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, *a):
        pass


def test_the_browser_probe_opens_the_real_page_and_sees_a_login_form_even_when_scripts_draw_it():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Pages)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        login = pre.browser_probe(base + "/login")
        assert login["ok"] and login["browser"] and login["login_form"]
        assert not pre.browser_probe(base + "/open")["login_form"]
        assert pre.browser_probe(base + "/spa")["login_form"]  # (SauceDemo draws its form with JavaScript)
    finally:
        srv.shutdown()


@pytest.mark.parametrize(("counts", "status", "outcome"), [
    ({"Not automated": 18}, "finished", "no_tests_automated"),
    ({"Passed": 3}, "finished", "completed"),
    ({"Passed": 2, "Failed": 1}, "finished", "completed_with_failures"),
    ({"Passed": 2, "Blocked": 1}, "finished", "completed_with_blocked"),
    ({"Passed": 2, "Not automated": 1}, "finished", "completed_with_unautomated"),
    ({"Cancelled": 3}, "stopped", "cancelled"),
    ({}, "running", "running"),
])
def test_the_execution_outcome_never_calls_unautomated_tests_complete(counts, status, outcome):
    ids = [f"TC-QPL-2-{n}" for n in range(1, sum(counts.values()) + 1)] or ["TC-QPL-2-1"]
    out = bridge.outcome_of({"status": status, "counts": counts, "case_ids": ids})
    assert out["outcome"] == outcome
    if outcome == "no_tests_automated":
        assert out["outcome_text"] == "Execution unsuccessful - no tests were automated"
        assert out["tally"]["executed"] == 0 and out["pass_rate"] is None and out["automation_coverage"] == 0


@pytest.mark.parametrize(("category", "status"), [
    ("Test mistake - checked on screen: the website did the right thing", "Requires review"),
    ("Test-script defect (the generated code is wrong)", "Requires review"),
    ("Locator / interaction failure (not proof of a website bug)", "Failed"),
    ("Application defect (potential website bug)", "Failed"),
])
def test_a_failure_of_the_generated_test_itself_is_not_reported_as_a_failed_requirement(category, status):
    """Live QPL-3 run: four AI ideas failed as 'test mistake - the website did the right thing' and the run said
    'Completed with failures'."""
    case = {"title": "Sort products by name (Z to A)", "execution_status": "Failed", "failure_category": category}
    assert bridge._result_status(case) == status
    out = bridge.outcome_of({"status": "finished", "counts": {"Passed": 5, status: 4}, "case_ids": list("abcdefghi")})
    assert out["outcome"] == ("completed_with_review" if status == "Requires review" else "completed_with_failures")
    assert out["tally"]["executed"] == 9


def test_ai_ideas_that_repeat_a_rule_idea_or_have_no_basis_are_dropped():
    from types import SimpleNamespace as N

    from backend.atlassian.analysis import useful_ai_ideas
    c2 = N(id="QPL-3#AC-2", text="Sorting by Price (low to high) shows the prices in ascending order")
    c4 = N(id="X#AC-1", text="After 3 failed attempts the account is locked")
    rules = [{"criterion": c2, "kind": "positive", "title": "Verify sorting by Price (low to high)"}]
    ai = [{"criterion": c2, "kind": "positive", "title": "Sort products by price (low to high)"},
          {"criterion": c2, "kind": "negative", "title": "Attempt to sort products by price with invalid input"},
          {"criterion": c2, "kind": "security", "title": "Verify untrusted data handling on products page"},
          {"criterion": c2, "kind": "boundary", "title": "Sorting keeps the order after adding an item to the cart"},
          {"criterion": c4, "kind": "security", "title": "The account stays locked after the third failed attempt"}]
    assert [i["title"] for i in useful_ai_ideas(ai, rules)] == [
        "Sorting keeps the order after adding an item to the cart",
        "The account stays locked after the third failed attempt"]


def test_login_criteria_no_longer_get_generic_security_ideas():
    from types import SimpleNamespace as N

    from backend.atlassian.analysis import SECURITY_RULE
    assert not SECURITY_RULE.search("A user with a valid username and password is taken to the Products page")
    assert not SECURITY_RULE.search("A wrong password shows 'Username and password do not match'")
    assert SECURITY_RULE.search("The password is masked") and N


def test_the_studio_says_which_code_it_runs():
    """A problem reported again after it was fixed: first rule out an old checkout / a server not restarted."""
    from fastapi.testclient import TestClient

    from backend import server
    v = TestClient(server.app, base_url="http://127.0.0.1:8000").get("/api/version", headers={"X-Agentic-QA": "1"}).json()
    import subprocess
    head = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert v["commit"] == head and v["started_at"]


@pytest.mark.real_preflight
@pytest.mark.parametrize("env, policy_mode, provider, why", [
    ({"LLM_PROVIDER": "none"}, "cloud", "", "No AI is selected"),                         # .env LLM_PROVIDER=none
    ({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-x"}, "local", "", "local-only"),     # cloud AI under local privacy
    ({"LLM_PROVIDER": "ollama"}, "cloud", "ollama", "Ollama"),                           # Ollama not running
    ({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-x"}, "cloud", "none", "No AI"),      # 'no AI' chosen for the run
])
def test_a_studio_run_with_your_own_tests_never_starts_without_an_ai(monkeypatch, tmp_path, env, policy_mode,
                                                                     provider, why):
    """The three ways a run used to start with no AI and end with every own test 'Not automated'."""
    from backend import server
    for k in ("LLM_PROVIDER", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(privacy, "POLICY_PATH", tmp_path / "privacy.json")
    (tmp_path / "privacy.json").write_text(json.dumps({"mode": policy_mode, "cloud_consent": policy_mode == "cloud"}))
    monkeypatch.setattr(server, "providers", lambda: {"providers": [
        {"id": "ollama", "name": "Ollama (local)", "running": False, "installed": [],
         "readiness_reason": "Ollama is not running"},
        {"id": "openai", "name": "OpenAI", "has_key": True, "models": ["gpt-4o-mini"]}]})
    started = []
    monkeypatch.setattr(server, "_validate", lambda req, source: None)
    req = server.RunRequest(source="https://shop.example/", authorized=True, llm_provider=provider or None,
                            my_tests="Add a product to the cart and check the badge shows 1")
    with pytest.raises(server.HTTPException) as refused:
        started.append(server._launch_run(req, None))
    assert refused.value.status_code == 409 and "AI provider is required" in refused.value.detail
    assert why.lower() in refused.value.detail.lower() and not started
