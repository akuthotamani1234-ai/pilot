"""Phase 3: REST API tests - real requests, real checks (status, documented schema, JSON assertions, time), request
chains, operation-specific permission for state-changing methods, redacted evidence, Jira test cases planned by the AI
from the documented operations only, and per-case results through the existing execution / traceability path."""
import json
import os
import time

import httpx
import pytest

from backend import api_testing as at
from tests.test_requirements_execution import _accept, api  # noqa: F401

SPEC = {"openapi": "3.0.0", "servers": [{"url": "https://shop.example/api"}], "paths": {
    "/orders": {"get": {"operationId": "listOrders", "parameters": [
        {"name": "status", "in": "query", "required": True, "schema": {"type": "string", "enum": ["open", "done"]}}],
        "responses": {"200": {"content": {"application/json": {"schema": {
            "type": "array", "items": {"$ref": "#/components/schemas/Order"}}}}}}},
               "post": {"requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Order"}}}},
                        "responses": {"201": {"content": {"application/json": {"schema": {
                            "$ref": "#/components/schemas/Order"}}}}}}},
    "/orders/{id}": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {
        "$ref": "#/components/schemas/Order"}}}}, "404": {}}},
                     "delete": {"responses": {"204": {}}}}},
    "components": {"schemas": {"Order": {"type": "object", "required": ["id", "total"], "properties": {
        "id": {"type": "integer"}, "total": {"type": "number"}, "status": {"type": "string"}}}}}}


def fake_api():
    store = {1: {"id": 1, "total": 12.5, "status": "open"}}
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        path = request.url.path.removeprefix("/api")
        if request.method == "GET" and path == "/orders":
            return httpx.Response(200, json=[o for o in store.values() if o["status"] == request.url.params["status"]])
        if request.method == "POST" and path == "/orders":
            body = json.loads(request.content)
            new = {"id": max(store) + 1, "total": body.get("total"), "status": "open"}
            store[new["id"]] = new
            return httpx.Response(201, json=new)
        if path.startswith("/orders/"):
            oid = int(path.rsplit("/", 1)[1])
            if request.method == "DELETE":
                store.pop(oid, None)
                return httpx.Response(204)
            return httpx.Response(200, json=store[oid]) if oid in store else httpx.Response(404, json={"error": "no"})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_spec_operations_refs_and_smoke_tests():
    ops = at.operations(at.load_spec(json.dumps(SPEC)))
    assert {(o["method"], o["path"]) for o in ops} == {("GET", "/orders"), ("POST", "/orders"),
                                                      ("GET", "/orders/{id}"), ("DELETE", "/orders/{id}")}
    assert ops[0]["responses"]["200"]["items"]["required"] == ["id", "total"]  # ($ref resolved)
    smoke = at.smoke_tests(ops)
    assert [(t.path, t.query) for t in smoke] == [("/orders", {"status": "open"})]  # (enum value used)
    assert at.match_operation("GET", "/orders/7", ops)["path"] == "/orders/{id}"
    with pytest.raises(ValueError, match="not an OpenAPI"):
        at.load_spec('{"hello": 1}')


def test_a_chain_creates_reads_and_checks_and_state_changes_need_permission():
    client, seen = fake_api()
    ops = at.operations(SPEC)
    tests = [at.ApiTest(name="create", method="POST", path="/orders", body={"total": 30}, expect_status=[201],
                        save={"order": "id"}, checks=[at.Check(path="total", op="eq", value=30)], case="TC-1"),
             at.ApiTest(name="read back", path="/orders/{{order}}", checks=[at.Check(path="status", op="eq",
                                                                                    value="open")], case="TC-1"),
             at.ApiTest(name="delete", method="DELETE", path="/orders/{{order}}", expect_status=[204], case="TC-2"),
             at.ApiTest(name="list wrong check", path="/orders", query={"status": "open"},
                        checks=[at.Check(path="", op="len_gte", value=5)], case="TC-3")]
    res = at.run("https://shop.example/api", tests, ops=ops, allow={"POST"}, client=client, allow_local=True)
    assert [r["status"] for r in res] == ["Passed", "Passed", "Blocked", "Failed"]
    assert res[1]["request"]["url"].endswith("/orders/2") and "allows DELETE" in res[2]["reason"]
    assert "len_gte 5" in res[3]["reason"] and not any(r.method == "DELETE" for r in seen)  # (never sent)


def test_the_documented_schema_is_checked():
    def bad(request):
        return httpx.Response(200, json={"id": "seven", "status": "open"})  # (id a string, total missing)
    client = httpx.Client(transport=httpx.MockTransport(bad))
    res = at.run("https://shop.example/api", [at.ApiTest(name="get", path="/orders/7")], ops=at.operations(SPEC),
                 client=client, allow_local=True)
    assert res[0]["status"] == "Failed"
    assert "$.id: expected integer" in res[0]["reason"] and "$.total: required, missing" in res[0]["reason"]


def test_evidence_never_holds_a_secret():
    def echo(request):
        return httpx.Response(200, json={"token": "abc", "card": "4111 1111 1111 1111", "ok": True})
    client = httpx.Client(transport=httpx.MockTransport(echo))
    res = at.run("https://shop.example/api", [at.ApiTest(name="me", path="/orders/1", schema_check=False,
                                                         query={"api_key": "SECRET-123"})],
                 auth={"type": "bearer", "token": "tok-SECRET-999"}, client=client, allow_local=True)
    text = json.dumps(res)
    assert "tok-SECRET-999" not in text and "SECRET-123" not in text and "4111 1111" not in text
    assert res[0]["request"]["headers"]["Authorization"] == "[redacted]"


def test_the_ai_plan_keeps_only_documented_operations():
    ops = at.operations(SPEC)

    def ask(prompt, shape, **kw):
        plan = at._Plan
        return [plan(case="TC-1", tests=[at.ApiTest(name="ok", path="/orders/1"),
                                         at.ApiTest(name="invented", path="/invoices/1")]),
                plan(case="TC-2", tests=[], not_possible="the API has no refunds")]
    tests, why = at.tests_for_cases([{"id": "TC-1"}, {"id": "TC-2"}, {"id": "TC-3"}], ops, ask=ask)
    assert [t.name for t in tests] == ["ok"] and tests[0].case == "TC-1"
    assert why["TC-2"] == "Not automated: the API has no refunds" and "no API test" in why["TC-3"]


def test_jira_cases_run_as_api_tests_and_each_gets_its_result(api, monkeypatch):
    from backend import api_testing
    _accept(api, 2)
    api.client.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    monkeypatch.setattr(api_testing, "load_spec", lambda url: SPEC)
    monkeypatch.setattr(api_testing, "tests_for_cases", lambda cases, ops: (
        [at.ApiTest(name="list open", path="/orders", query={"status": "open"},
                    checks=[at.Check(path="[0].total", op="eq", value=12.5)], case="TC-QPL-2-1")],
        {"TC-QPL-2-2": "Not automated: no documented operation can test it"}))
    real_run = api_testing.run
    monkeypatch.setattr(api_testing, "run", lambda base, tests, **kw: real_run(
        base, tests, **{**kw, "client": fake_api()[0], "allow_local": True}))
    body = {"strategy": "requirements", "scope": {"test_case_ids": ["TC-QPL-2-1", "TC-QPL-2-2"]},
            "target": {"type": "api", "authorized": True, "api_spec_url": "https://shop.example/openapi.json",
                       "api_token": "tok-123"}}
    r = api.client.post("/api/requirements/executions", headers=api.H, json=body)
    assert r.status_code == 200, r.text
    ex_id = r.json()["execution"]["id"]
    for _ in range(100):
        e = api.client.get(f"/api/requirements/executions/{ex_id}", headers=api.H).json()
        if e["execution"]["status"] not in ("running", "queued"):
            break
        time.sleep(0.1)
    res = {x["test_case_id"]: x for x in e["results"]}
    assert res["TC-QPL-2-1"]["status"] == "Passed" and res["TC-QPL-2-2"]["status"] == "Not automated"
    assert "tok-123" not in json.dumps(e)


@pytest.mark.skipif(os.environ.get("QPILOT_LIVE_API") != "1", reason="live public API (set QPILOT_LIVE_API=1)")
def test_live_petstore_smoke_and_chain():
    url = "https://petstore3.swagger.io/api/v3/openapi.json"
    spec = at.load_spec(url)
    ops = at.operations(spec)
    res = at.run(at.base_url(spec, url), [
        at.ApiTest(name="create", method="POST", path="/pet", body={"id": 987654, "name": "qpilot", "photoUrls": []},
                   save={"pet": "id"}),
        at.ApiTest(name="read", path="/pet/{{pet}}", checks=[at.Check(path="name", op="eq", value="qpilot")])],
        ops=ops, allow={"POST"})
    assert [r["status"] for r in res] == ["Passed", "Passed"], res


def test_a_check_of_a_field_the_answer_does_not_have_is_the_tests_mistake_not_an_api_failure():
    def answer(request):
        return httpx.Response(200, json=[{"id": 1, "total": 3.0, "status": "open"}])
    client = httpx.Client(transport=httpx.MockTransport(answer))
    res = at.run("https://shop.example/api", [
        at.ApiTest(name="wrong path", path="/orders", query={"status": "open"},
                   checks=[at.Check(path="items[0].status", op="eq", value="open")], case="TC-1"),
        at.ApiTest(name="right path", path="/orders", query={"status": "open"},
                   checks=[at.Check(path="[0].status", op="eq", value="open")], case="TC-2")],
        ops=at.operations(SPEC), client=client, allow_local=True)
    assert res[0]["status"] == "Failed" and res[0]["category"] == "Test mistake"
    assert res[1]["status"] == "Passed"
    cases = {c["requirement_test"]: c for c in at.to_run_cases(res, {}, ["TC-1", "TC-2"])}
    assert cases["TC-1"]["failure_category"] == "Test mistake"  # (-> "Requires review" in the Jira result)


def test_a_check_after_a_blocked_write_is_blocked_not_a_failure():
    """Live Petstore run (26 Nov): POST /pet was blocked (writes not allowed), then GET /pet/{id} did not find
    'Fluffy' - that was reported Failed, a false failure of the API."""
    from backend.api_testing import to_run_cases
    results = [{"name": "Add", "case": "TC-1", "status": "Blocked", "reason": "Blocked: POST changes data"},
               {"name": "Get", "case": "TC-1", "status": "Failed", "reason": "name eq 'Fluffy': name = 'shpitz'"},
               {"name": "List", "case": "TC-2", "status": "Failed", "reason": "status 500"},
               {"name": "Add", "case": "TC-2", "status": "Blocked", "reason": "Blocked: POST changes data"}]
    out = {c["tc_id"]: c for c in to_run_cases(results, {}, ["TC-1", "TC-2"])}
    assert out["TC-1"]["execution_status"] == "Blocked" and "Fluffy" in out["TC-1"]["skip_reason"]
    assert out["TC-2"]["execution_status"] == "Failed"  # (a failure before the blocked step is the API's)


SPEC_OPS = [
    {"id": "list", "method": "GET", "path": "/items", "summary": "", "secured": True, "body": None,
     "params": [{"name": "status", "in": "query", "required": True, "schema": {"enum": ["open", "done"]},
                 "example": None},
                {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "minimum": 1,
                                                                                "maximum": 50}, "example": None}],
     "responses": {"200": {"type": "array", "items": {"type": "object", "required": ["id", "status"],
                                                      "properties": {"id": {"type": "integer"},
                                                                     "status": {"type": "string"}}}},
                   "400": {}, "401": {}}},
    {"id": "one", "method": "GET", "path": "/items/{id}", "summary": "", "secured": False, "body": None,
     "params": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}, "example": None}],
     "responses": {"200": {}, "404": {}}},
    {"id": "add", "method": "POST", "path": "/items", "summary": "", "secured": False,
     "body": {"type": "object", "required": ["title"]}, "params": [], "responses": {"201": {}, "422": {}}},
]


def _client(buggy=False):
    import httpx

    def answer(req):
        q = dict(req.url.params)
        if req.url.path == "/items" and req.method == "GET":
            if "Authorization" not in req.headers:
                return httpx.Response(200 if buggy else 401, json={})
            if q.get("status") not in ("open", "done"):
                return httpx.Response(200 if buggy else 400, json={})
            if "limit" in q and not 1 <= int(q["limit"]) <= 50:
                return httpx.Response(400, json={})
            rows = [{"id": 1, "status": "open"}, {"id": 2, "status": "done"}]
            return httpx.Response(200, json=rows if buggy else [r for r in rows if r["status"] == q["status"]])
        if req.url.path.startswith("/items/"):
            return httpx.Response(404, json={})
        if req.method == "POST":
            return httpx.Response(201 if buggy else 422, json={})
        return httpx.Response(500)
    return httpx.Client(transport=httpx.MockTransport(answer))


def test_autonomous_api_tests_cover_schema_rules_negatives_boundaries_auth_and_validation():
    from backend import api_testing
    tests = api_testing.explore_tests(SPEC_OPS, allow={"POST"}, authed=True)
    kinds = {t.kind for t in tests}
    assert kinds == {"schema", "business_rule", "negative", "boundary", "auth", "validation"}, kinds
    assert not any(t.method == "POST" for t in api_testing.explore_tests(SPEC_OPS))  # (no write unless allowed)
    good = api_testing.run("https://api.example", tests, auth={"type": "bearer", "token": "tkn-123456"},
                           allow={"POST"}, ops=SPEC_OPS, client=_client(), allow_local=True)
    assert [r["name"] for r in good if r["status"] != "Passed"] == []
    bad = api_testing.run("https://api.example", tests, auth={"type": "bearer", "token": "tkn-123456"},
                          allow={"POST"}, ops=SPEC_OPS, client=_client(buggy=True), allow_local=True)
    by_kind = {}
    for r in bad:
        by_kind.setdefault(r["kind"], []).append(r)
    assert all(r["status"] == "Failed" for r in by_kind["business_rule"])  # (the filter returns other items)
    assert "item(s) have status" in by_kind["business_rule"][0]["reason"]
    for k in ("negative", "auth", "validation"):
        failed = [r for r in by_kind[k] if r["status"] == "Failed"]
        assert failed and all(r["category"].startswith("Validation defect") for r in failed), k
    assert "tkn-123456" not in json.dumps(bad)  # (the credential never reaches the evidence)
