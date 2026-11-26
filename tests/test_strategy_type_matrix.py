"""Every application type x every testing strategy, through the real Jira execution route: which engine gets the run,
which cases it gets, and the AI the user chose reaching that engine. The engines themselves are stubbed (they are
covered by their own tests and by the live runs); the device / Mac / payment pre-run checks are stubbed OK here
(they have their own tests: test_execution_preflight.py, test_ios.py, test_hybrid_android.py)."""
import pytest

from backend import requirements_api as rapi
from tests.test_requirements_execution import _accept, api  # noqa: F401

TARGETS = {
    "web": {"url": "https://shop.example/"},
    "api": {"type": "api", "api_spec_url": "https://api.example/openapi.json"},
    "android": {"type": "android", "package_name": "com.example.shop", "device_id": "emulator-5554"},
    "ios": {"type": "ios", "ios": {"bundle_id": "com.example.shop"}},
}


@pytest.fixture
def routed(api, monkeypatch):
    _accept(api, 2)
    api.client.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    seen = []

    def job(kind, **info):
        n = 900 + len(seen)
        api.server.jobs[n] = {"id": n, "status": "running", "run": ""}
        seen.append({"engine": kind, **info})
        return n
    monkeypatch.setattr(api.server, "_launch_run", lambda req, caller: {"id": job(
        "web", cases=[t["tc"] for t in req.requirement_tests or []], only=req.requirements_only,
        ai=req.llm_provider)})
    monkeypatch.setattr(rapi, "_launch_api", lambda t, tests, ids, explore=False: job(
        "api", cases=sorted(ids), ai=t.llm_provider, explore=explore))
    monkeypatch.setattr(rapi, "_launch_ios", lambda t, tests, ids, strategy="": job(
        "ios", cases=sorted(ids), ai=t.llm_provider, strategy=strategy))
    monkeypatch.setattr(rapi, "_launch_android", lambda t, texts, a, x, only=False: job(
        "android", cases=sorted(s.split("]")[0][1:] for s in texts), ai=t.llm_provider, only=only))
    monkeypatch.setattr(rapi.execution_preflight, "check", lambda **kw: {
        "ok": True, "problems": [], "needs_ai": True, "ai": {"provider": kw["llm_provider"] or "openai", "model": ""}})
    monkeypatch.setattr(rapi, "_watch", lambda *a, **k: None)
    return api, seen


@pytest.mark.parametrize("kind", list(TARGETS))
@pytest.mark.parametrize("strategy", ["requirements", "hybrid", "autonomous"])
def test_each_type_and_strategy_reaches_its_engine_with_the_chosen_ai(routed, kind, strategy):
    api, seen = routed
    scope = {"test_case_ids": ["TC-QPL-2-1", "TC-QPL-2-2"]} if strategy != "autonomous" else {}
    body = {"strategy": strategy, "scope": scope,
            "target": {"authorized": True, "llm_provider": "anthropic", **TARGETS[kind]}}
    r = api.client.post("/api/requirements/executions", headers=api.H, json=body)
    assert r.status_code == 200, r.text
    assert len(seen) == 1 and seen[0]["engine"] == kind  # (one engine: the one for this application type)
    assert seen[0]["ai"] == "anthropic"  # (the AI chosen in the Execution Center reaches the engine)
    if strategy != "autonomous":
        assert seen[0]["cases"] == ["TC-QPL-2-1", "TC-QPL-2-2"]
    if kind in ("web", "android"):
        assert seen[0]["only"] is (strategy == "requirements")  # (hybrid / autonomous also explore the site)
    if kind == "ios":
        assert seen[0]["strategy"] == strategy  # (the iOS engine discovers the app for autonomous / hybrid)
    if kind == "api":
        assert seen[0]["explore"] is (strategy != "requirements")  # (+ read-only smoke tests over the whole API)
    ex = r.json()["execution"]
    assert ex["strategy"] == strategy and ex["target"].get("type", "web") in (kind, "web")


def test_ios_allows_every_strategy():
    from backend import execution_preflight
    env = dict(case_count=2, url="", authorized=True, app_type="ios", llm_provider="openai", api_key="sk-x",
               ios={"bundle_id": "com.example.shop"})
    for strategy, n in (("autonomous", 0), ("hybrid", 2), ("requirements", 2)):
        pre = execution_preflight.check(strategy=strategy, **{**env, "case_count": n})
        assert not [p for p in pre["problems"] if p["code"] == "strategy"]  # (only the Mac / Appium checks remain)


def test_api_autonomous_adds_read_only_smoke_tests_for_every_simple_get():
    from backend import api_testing
    ops = [{"method": "GET", "path": "/pets", "params": [], "responses": {"200": {}}, "operation_id": "list"},
           {"method": "GET", "path": "/pets/{id}", "params": [{"name": "id", "in": "path", "required": True,
                                                               "schema": {"type": "integer"}}], "responses": {}},
           {"method": "POST", "path": "/pets", "params": [], "responses": {}}]
    smoke = api_testing.smoke_tests(ops)
    assert [(t.method, t.path) for t in smoke] == [("GET", "/pets")]  # (no write, no unknown id)
