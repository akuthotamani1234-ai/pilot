"""AI-assisted targeted testing: your plain-English instructions steer exploration, become a plan (or an honest
refusal), and the report answers each one from what really ran."""
import http.server
import json
import threading

import pytest

from backend import objective as objective_mod
from backend.agents import test_design
from backend.config import settings

PIM = ("Log in as Admin. Navigate to PIM. Test employee search by employee name and employee ID. Verify that the "
       "search results match the entered criteria. Test the reset functionality. Report any errors with screenshots.")


def test_words_point_to_the_requested_area_not_to_the_login_role():
    obj = objective_mod.Objective([{"id": "x", "text": PIM}])
    assert "pim" in obj.words and "employee" in obj.words and "admin" not in obj.words
    assert obj.score("https://h/web/index.php/pim/viewEmployeeList", "Employee List") >= 2
    assert obj.score("https://h/web/index.php/admin/viewAdminModule", "Admin") == 0
    assert objective_mod.destructive(PIM) == ""
    assert objective_mod.destructive("Delete all employees") == "Delete"


PAGES = [{"slug": "home", "url": "https://h/", "title": "Home", "auth": True, "buttons": [], "inputs": [], "forms": [],
          "links": []},
         {"slug": "employees", "url": "https://h/pim/list", "title": "Employee List", "auth": True,
          "buttons": [{"text": "Search", "selector": "button.search"}, {"text": "Reset", "selector": "button.reset"}],
          "inputs": [{"label": "Employee Name", "selector": "input.name", "type": "text"},
                     {"label": "Employee Id", "selector": "input.id", "type": "text"}],
          "forms": [], "links": []}]


def _start(tmp_path, monkeypatch, tests):
    monkeypatch.setattr(objective_mod, "_lock", threading.Lock())
    from backend import my_tests
    monkeypatch.setattr(my_tests, "load", lambda _site, **k: tests)
    objective_mod.start(tmp_path, "site", "", ai=True)


def test_destructive_request_is_refused_even_with_an_ai(tmp_path, monkeypatch):
    tests = [{"id": "D1", "text": "Delete all employees"}]
    _start(tmp_path, monkeypatch, tests)
    monkeypatch.setattr(test_design, "llm_enabled", lambda: True)
    monkeypatch.setattr(test_design, "ask_structured", lambda *a, **k: pytest.fail("no AI call for a refused request"))
    out = test_design.my_test_cases(PAGES, tests, 1, run_dir=tmp_path)
    assert out[0]["skip_reason"].startswith("Blocked: 'Delete'")
    assert objective_mod.read(tmp_path)["instructions"][0]["status"].startswith("Blocked")


def test_plan_clarification_and_full_instruction(tmp_path, monkeypatch):
    tests = [{"id": "P1", "text": PIM}, {"id": "V1", "text": "Test the employee section"}]
    _start(tmp_path, monkeypatch, tests)
    monkeypatch.setattr(test_design, "llm_enabled", lambda: True)

    def fake_ai(prompt, model, **kw):
        assert PIM in prompt  # (your exact words reach the AI)
        return [test_design.AICase(
                    title=PIM[:150], pages=["home", "employees"], test_data="name=Linda, id=0001",
                    preconditions=["logged in"], steps=["Open the 'Employee List' page", "Type the name in 'Employee Name'",
                                                        "Click 'Search'", "Click 'Reset'"],
                    expected="Exploratory: every row shows the typed name",
                    assertions=["every result row's Name -> contains the typed name"],
                    unknowns=["which employees exist in the shared demo"]),
                test_design.AICase(title="Test the employee section", steps=["Open 'Employee List'", "Look"],
                                   needs_clarification="Which part: search, add, or edit an employee?")]
    monkeypatch.setattr(test_design, "ask_structured", fake_ai)
    out = {c["my_test"]: c for c in test_design.my_test_cases(PAGES, tests, 1, run_dir=tmp_path)}
    assert not out["P1"].get("skip_reason"), out["P1"].get("skip_reason")
    assert out["P1"]["instruction"] == PIM and out["P1"]["title"].endswith("…")
    assert out["P1"]["assertions"] == ["every result row's Name -> contains the typed name"]
    assert out["V1"]["skip_reason"].startswith("Needs clarification: Which part")
    saved = {i["id"]: i for i in objective_mod.read(tmp_path)["instructions"]}
    assert saved["P1"]["status"] == "automated"
    assert saved["P1"]["plan"]["navigation"] == ["https://h/", "https://h/pim/list"]
    assert saved["P1"]["plan"]["unknowns"] == ["which employees exist in the shared demo"]
    assert saved["V1"]["status"].startswith("Needs clarification")


def test_without_an_ai_instructions_stay_not_automated(tmp_path, monkeypatch):
    tests = [{"id": "P1", "text": PIM}]
    _start(tmp_path, monkeypatch, tests)
    monkeypatch.setattr(test_design, "llm_enabled", lambda: False)
    out = test_design.my_test_cases(PAGES, tests, 1, run_dir=tmp_path)
    assert out[0]["skip_reason"].startswith("Not automated: your own tests need an AI")


def test_outcomes_come_only_from_executed_tests(tmp_path, monkeypatch):
    tests = [{"id": "P1", "text": PIM}, {"id": "N1", "text": "Check the leave balance"}]
    _start(tmp_path, monkeypatch, tests)
    cases = [{"my_test": "P1", "tests": ["test_ai_flow_1"]},
             {"my_test": "N1", "tests": [], "skip_reason": "Not automated: the website has no leave balance page"}]
    results = [{"test": "test_ai_flow_1", "outcome": "failed", "checks": 3, "error": "row 2 shows another name",
                "screenshot": "failure_screenshots/x.png", "trace": "traces/x.zip"}]
    items = {i["id"]: i for i in objective_mod.outcomes(tmp_path, cases, results)}
    assert items["P1"]["outcome"] == "failed" and items["P1"]["assertions_checked"] == 3
    assert items["P1"]["evidence"] == ["failure_screenshots/x.png", "traces/x.zip"]
    assert items["N1"]["outcome"] == "not run" and items["N1"]["status"].startswith("Not automated")
    from backend.agents.reporter import _request_html
    html = _request_html(tmp_path, list(items.values()))
    assert "Your request" in html and "row 2 shows another name" in html and "not run" in html


SITE = {"/": "<title>Home</title><h1>Home</h1>" + "".join(f"<a href='/{p}'>{p.title()}</a> " for p in
                                                          ("about", "news", "blog", "careers", "team")) +
             "<a href='/hr/employees'>Employees</a>",
        "/hr/employees": "<title>Employee List</title><h1>Employee List</h1><a href='/hr/employees/7'>Linda</a>",
        "/hr/employees/7": "<title>Employee Linda</title><h1>Linda</h1>"}


def _serve():
    class Site(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = SITE.get(self.path, "<title>Page</title><h1>Page</h1>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


@pytest.mark.parametrize("focus", [False, True])
def test_requested_pages_are_explored_first_within_the_budget(tmp_path, monkeypatch, focus):
    from backend import my_tests
    from backend.agents import discovery
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "max_pages", 3)
    monkeypatch.setattr(settings, "objective_focus", focus)
    monkeypatch.setenv("QA_OBJECTIVE_FOCUS", "1" if focus else "0")
    monkeypatch.setattr(my_tests, "load", lambda _site, **k: [{"id": "E1", "text": "Test the employees list"}])
    srv, url = _serve()
    try:
        out = discovery.discovery_agent({"url": url, "run_dir": str(tmp_path), "site_key": "t", "log": []})
    finally:
        srv.shutdown()
    visited = [p["url"].replace(url.rstrip("/"), "") for p in out["app_map"]]
    # without priority the 3-page budget would be spent on /about and /news; the requested area comes first
    assert "/hr/employees" in visited and "/hr/employees/7" in visited, visited
    obj = objective_mod.read(tmp_path)
    assert obj["focus"] is focus and obj["instructions"][0]["targets"]
    if focus:
        crawl = json.loads((tmp_path / "crawl.json").read_text(encoding="utf-8"))
        skipped = {x["url"].replace(url.rstrip("/"), ""): x["reason"] for x in crawl.get("skipped") or []}
        assert "outside the focus" in skipped.get("/about", ""), skipped  # (the start page leads to a requested page)


# ---- mistakes found in the live OpenAI run (gpt-4o-mini, OrangeHRM PIM instruction, 2026-11-22)

REAL_ANSWER = """```json
[
  {
    "title": "__PIM__",
    "priority": "high",
    "pages": ["employees", "pim_viewEmployeeList"],
    "guest": false,
    "test_data": "values typed",
    "preconditions": ["logged in"],
    "steps": ["Open the 'Employee List' page", "Type a name in 'Employee Name'", "Click 'Search'", "Click 'Reset'"],
    "expected": "The results match the typed name and the fields are cleared after reset.",
    "assertions": ["every result row's Name -> contains the typed employee name"],
    "unknowns": [],
    "needs_clarification": "",
  }
]
```""".replace("__PIM__", PIM)


def test_a_trailing_comma_in_the_ai_answer_is_accepted():
    from backend.llm import LLMError, extract_json
    assert extract_json('[{"a": 1, "b": [1, 2,],},]') == [{"a": 1, "b": [1, 2]}]
    with pytest.raises(LLMError, match="near"):  # (a real error says where, so the retry can fix it)
        extract_json('[{"a": 1 "b": 2}]')


def test_a_long_instruction_copied_as_title_does_not_reject_the_case():
    assert len(PIM) > 200
    case = test_design.AICase(title=PIM, steps=["a", "b"])
    assert len(case.title) <= 200 and case.title.endswith("…")


def test_the_real_openai_answer_becomes_an_automated_plan(tmp_path, monkeypatch):
    """The exact shape gpt-4o-mini returned: trailing comma, the 218-character instruction as title, and a page
    discovery never opened. Before the fix it was rejected twice and the instruction stayed 'not automated'."""
    tests = [{"id": "P1", "text": PIM}]
    _start(tmp_path, monkeypatch, tests)
    monkeypatch.setattr(test_design, "llm_enabled", lambda: True)
    import backend.llm as llm
    monkeypatch.setattr(llm, "ask_llm", lambda *a, **k: REAL_ANSWER)
    out = test_design.my_test_cases(PAGES, tests, 1, run_dir=tmp_path)
    assert not out[0].get("skip_reason"), out[0].get("skip_reason")
    assert out[0]["instruction"] == PIM and out[0]["pages"] == ["employees"]
    plan = objective_mod.read(tmp_path)["instructions"][0]["plan"]
    assert plan["pages_not_explored"] == ["pim_viewEmployeeList"]
    assert any("not explored by discovery" in u for u in plan["unknowns"])


def test_the_best_matching_page_is_explored_first():
    from backend.agents.discovery import _Frontier
    obj = objective_mod.Objective([{"id": "x", "text": PIM}])
    links = [("https://h/web/index.php/pim/updatePassword", "Change Password"),
             ("https://h/web/index.php/pim/configurePim", "Optional Fields"),
             ("https://h/web/index.php/pim/viewEmployeeList", "Employee List")]
    q = _Frontier(("https://h/", 0, True, True))
    q.popleft()
    for url, text in links:
        q.insert_hit((url, 1, True, True), obj.score(url, text))
    assert q.popleft()[0].endswith("viewEmployeeList")  # (link text 'Employee' beats an address that says /pim/)
    assert [x[0].rsplit("/", 1)[1] for x in q] == ["updatePassword", "configurePim"]  # (ties keep menu order)
