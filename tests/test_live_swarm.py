"""Live swarm view: real per-worker screens, explorer timelines and the Hugging Face provider."""
import pytest
from fastapi.testclient import TestClient

from backend import live_frames, server
from backend.execution_events import read_events

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64


class FakePage:
    def __init__(self):
        self.shots = 0

    def screenshot(self, **kwargs):
        assert kwargs["type"] == "jpeg"
        self.shots += 1
        return JPEG


@pytest.fixture
def api(tmp_path, monkeypatch):
    root = tmp_path / "fixture-run"
    root.mkdir()
    monkeypatch.setattr(server, "RUNS", tmp_path)
    monkeypatch.setattr(server, "jobs", {7: {"run": root.name}, 8: {"run": None}})
    return TestClient(server.app, base_url="http://127.0.0.1"), root


def test_live_screen_is_served_uncached_only_for_a_real_worker_frame(api, tmp_path):
    client, root = api
    assert client.get("/api/runs/7/live/gw0").status_code == 404  # no frame yet
    assert client.get("/api/runs/7/live/Bad_Name!").status_code == 400
    assert client.get("/api/runs/8/live/gw0").status_code == 404  # run not started
    assert client.get("/api/runs/99/live/gw0").status_code == 404
    (root / "live").mkdir()
    (root / "live" / "gw0.jpg").write_bytes(JPEG)
    response = client.get("/api/runs/7/live/gw0")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    assert response.content == JPEG
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(JPEG)
    (root / "live" / "gw1.jpg").symlink_to(outside)
    assert client.get("/api/runs/7/live/gw1").status_code == 404  # a link is never followed


def test_frames_are_throttled_replaced_atomically_and_forced_for_an_action(tmp_path, monkeypatch):
    monkeypatch.setenv("QA_LIVE_FRAMES", "true")
    monkeypatch.setattr(live_frames, "_last", {})
    monkeypatch.setattr(live_frames, "_seq", {})
    page = FakePage()
    assert live_frames.write_frame(page, tmp_path, "explorer-1") == 1
    assert live_frames.write_frame(page, tmp_path, "explorer-1") is None  # within the minimum gap
    assert live_frames.write_frame(page, tmp_path, "explorer-1", force=True) == 2
    assert page.shots == 2
    files = sorted(p.name for p in (tmp_path / "live").iterdir())
    assert files == ["explorer-1.jpg"]  # no temporary files are left behind
    monkeypatch.setenv("QA_LIVE_FRAMES", "false")
    assert live_frames.write_frame(page, tmp_path, "explorer-2", force=True) is None


def test_explorer_timeline_reaches_the_dashboard_with_role_point_and_frame(tmp_path):
    log = live_frames.EventLog(tmp_path, "explorer-3", role="Explorer")
    log.emit("Open /pim", "running", url="https://example.test/pim")
    log.emit("Inspect 'Add'", "completed", url="https://example.test/pim", point=[40, 22], frame=5)
    events = read_events(tmp_path)["events"]
    assert [e["text"] for e in events] == ["Open /pim", "Inspect 'Add'"]
    assert {e["worker"] for e in events} == {"explorer-3"}
    assert events[1]["role"] == "Explorer" and events[1]["point"] == [40, 22] and events[1]["frame"] == 5
    assert events[0]["phase"] == "discovery"


def test_worker_file_names_cannot_leave_the_live_folder():
    assert live_frames.worker_file("../../etc/passwd") == "etcpasswd.jpg"
    assert live_frames.worker_file("GW0") == "gw0.jpg"
    assert live_frames.worker_file("") == "worker.jpg"


def test_explorers_wait_for_a_script_drawn_page_and_find_its_controls():
    playwright = pytest.importorskip("playwright.sync_api")
    from backend.agents.discovery import _hover_targets, _wait_rendered
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # no browser on this machine
            pytest.skip(f"Chromium unavailable: {exc}")
        page = browser.new_page(viewport={"width": 1000, "height": 600})
        # Like a single-page app: the document is empty when it loads; the menu is drawn a moment later.
        page.set_content("""<body><script>setTimeout(() => { document.body.innerHTML =
          '<nav><a href="/pim/list">PIM</a><a href="/leave"><i class="oxd-icon bi-calendar" style="display:inline-block;width:16px;height:16px"></i></a></nav>' +
          '<button aria-label="Add employee">+</button><input placeholder="Search">'; }, 400);</script></body>""")
        assert _hover_targets(page) == []  # nothing is drawn yet
        _wait_rendered(page, idle_ms=500, stable_ms=3000)
        targets = _hover_targets(page)
        browser.close()
    names = [t["name"] for t in targets]
    assert "PIM" in names and "Add employee" in names and "Search" in names
    assert "calendar icon" in names  # an icon-only link gets a readable name
    for t in targets:
        assert all(0 <= v <= 100 for v in t["point"]) and len(t["xy"]) == 2


def test_hugging_face_is_a_cloud_provider_with_its_own_key_and_model_names(monkeypatch):
    from backend import config, privacy
    assert "huggingface" in privacy.CLOUD_PROVIDERS
    assert server.key_provider("hf_abc123") == "huggingface"
    assert server.KEY_ENV["huggingface"] == "HF_TOKEN"
    assert config._model_fits("huggingface", "meta-llama/Llama-3.3-70B-Instruct")
    assert not config._model_fits("huggingface", "gpt-4o-mini")
    assert not config._model_fits("openai", "Qwen/Qwen2.5-72B-Instruct")
    assert config._model_fits("ollama", "llama3.1")


def test_hugging_face_call_uses_the_router_and_fails_closed_without_a_token(monkeypatch):
    from backend import llm
    monkeypatch.setattr(llm.settings, "llm_provider", "huggingface")
    monkeypatch.setattr(llm.settings, "llm_model", "Qwen/Qwen2.5-72B-Instruct")
    monkeypatch.setattr(llm.settings, "huggingface_api_key", "")
    import backend.privacy as privacy
    monkeypatch.setattr(privacy, "guard_provider", lambda *a, **k: None)
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: pytest.fail("no call without a token"))
    with pytest.raises(llm.LLMError, match="Hugging Face API key is missing"):
        llm._ask_once("hello", "", 0.2)
    seen = {}

    class Reply:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "{\"ok\": true}"}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 3}}

        def raise_for_status(self):
            return None

    def post(url, headers, json, timeout):
        seen.update(url=url, auth=headers["Authorization"], body=json)
        return Reply()

    monkeypatch.setattr(llm.settings, "huggingface_api_key", "hf_test_token")
    monkeypatch.setattr(llm.requests, "post", post)
    monkeypatch.setattr(llm, "_raise_with_reason", lambda r: None)
    answer, tokens_in, tokens_out = llm._ask_once("hello", "be brief", 0.2)
    assert seen["url"] == "https://router.huggingface.co/v1/chat/completions"
    assert seen["auth"] == "Bearer hf_test_token"
    assert seen["body"]["model"] == "Qwen/Qwen2.5-72B-Instruct"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "be brief"}
    assert (answer, tokens_in, tokens_out) == ("{\"ok\": true}", 11, 3)
