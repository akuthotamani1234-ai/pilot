import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend import android, server

HEADERS = {"X-Agentic-QA": "1"}
DEVICE_ENVIRONMENT = {
    "ok": True,
    "appium": {"available": True, "url": "http://127.0.0.1:4723"},
    "appium_cli": True,
    "uiautomator2": True,
    "android_sdk": "C:\\Android\\Sdk",
    "java": "C:\\Java\\bin\\java.exe",
    "adb": "C:\\Android\\Sdk\\platform-tools\\adb.exe",
    "devices": [{"device_id": "emulator-5554", "status": "device", "details": ""}],
    "errors": [],
    "driver_output": "",
}


class FakeProcess:
    pid = 12345
    stdout = io.StringIO("")


class FakeThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


@pytest.fixture
def client():
    return TestClient(server.app, base_url="http://127.0.0.1:8000")


def test_android_environment_endpoint_reports_prerequisite_state(client, monkeypatch):
    status = {**DEVICE_ENVIRONMENT, "ok": False, "errors": ["Appium server is not running."]}
    monkeypatch.setattr(android, "android_environment", lambda: status)

    response = client.get("/api/android/environment")

    assert response.status_code == 200
    assert response.json()["errors"] == ["Appium server is not running."]


def test_mobile_run_requires_explicit_ownership_confirmation(client):
    response = client.post(
        "/api/mobile/runs",
        headers=HEADERS,
        data={
            "app_mode": "installed",
            "package_name": "com.example.demo",
            "device_id": "emulator-5554",
        },
    )

    assert response.status_code == 400
    assert "permission" in response.json()["detail"]


def _asgi_mobile_post(extra_headers: list[tuple[bytes, bytes]]):
    """POST /api/mobile/runs at the ASGI layer so Content-Length can be omitted or forged."""
    import asyncio

    body = b"app_mode=installed&package_name=com.example.demo&device_id=emulator-5554&authorized=true"
    headers = [
        (b"host", b"127.0.0.1:8000"),
        (b"x-agentic-qa", b"1"),
        (b"content-type", b"application/x-www-form-urlencoded"),
        *extra_headers,
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/mobile/runs",
        "raw_path": b"/api/mobile/runs",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }
    messages = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(server.app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    payload = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], json.loads(payload.decode() or "{}")


def test_mobile_upload_rejects_missing_or_oversized_content_length():
    status, body = _asgi_mobile_post([])
    assert status == 411
    assert "Content-Length" in body["detail"]
    status, body = _asgi_mobile_post([(b"content-length", b"not-a-number")])
    assert status == 400
    assert "Invalid upload Content-Length" in body["detail"]
    status, body = _asgi_mobile_post([(b"content-length", str(502 * 1024 * 1024).encode())])
    assert status == 413
    assert "500 MB" in body["detail"]


def test_mobile_run_checks_environment_before_accepting_an_apk(client, monkeypatch):
    monkeypatch.setattr(android, "android_environment", lambda *_args: DEVICE_ENVIRONMENT)
    apk = io.BytesIO(b"not an apk archive")
    response = client.post(
        "/api/mobile/runs",
        headers=HEADERS,
        data={"app_mode": "apk", "device_id": "emulator-5554", "authorized": "true"},
        files={"apk": ("app.apk", apk, "application/vnd.android.package-archive")},
    )

    assert response.status_code == 400
    assert "valid APK archive" in response.json()["detail"]


def test_mobile_run_stores_apk_privately_and_uses_the_existing_job_status_api(client, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "RUNS", tmp_path)
    monkeypatch.setattr(server, "jobs", {})
    monkeypatch.setattr(server, "_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_reader", lambda *_args: None)
    monkeypatch.setattr(server.threading, "Thread", FakeThread)
    monkeypatch.setattr(server.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(android, "android_environment", lambda *_args: DEVICE_ENVIRONMENT)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as apk_file:
        apk_file.writestr("AndroidManifest.xml", b"manifest")
        apk_file.writestr("classes.dex", b"dex")

    response = client.post(
        "/api/mobile/runs",
        headers=HEADERS,
        data={"app_mode": "apk", "device_id": "emulator-5554", "authorized": "true"},
        files={"apk": ("demo.apk", archive.getvalue(), "application/vnd.android.package-archive")},
    )

    assert response.status_code == 200, response.json()
    job = response.json()
    assert job["target_type"] == "android"
    assert job["status"] == "running"
    private = tmp_path / job["run"] / ".private"
    config = json.loads((private / "android_config.json").read_text(encoding="utf-8"))
    assert config["apk_path"] == str((private / "app.apk").resolve())
    assert (private / "app.apk").is_file()
    with pytest.raises(android.AndroidEnvironmentError, match="only on this computer"):
        android.validate_mobile_config(
            {
                "app_mode": "installed",
                "package_name": "com.example.demo",
                "device_id": "emulator-5554",
                "appium_url": "http://192.168.1.10:4723",
            }
        )


def test_mobile_provider_switch_uses_existing_shared_default_model(client, monkeypatch, tmp_path):
    captured = {}

    def start(*_args, **kwargs):
        captured["provider"] = kwargs["env"]["LLM_PROVIDER"]
        captured["model"] = kwargs["env"]["LLM_MODEL"]
        return FakeProcess()

    monkeypatch.setattr(server, "RUNS", tmp_path)
    monkeypatch.setattr(server, "jobs", {})
    monkeypatch.setattr(server, "_audit", lambda *_a, **_k: None)
    monkeypatch.setattr(server.threading, "Thread", FakeThread)
    monkeypatch.setattr(server.subprocess, "Popen", start)
    monkeypatch.setattr(android, "android_environment", lambda *_a: DEVICE_ENVIRONMENT)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5:3b")
    response = client.post(
        "/api/mobile/runs",
        headers=HEADERS,
        data={
            "app_mode": "installed",
            "package_name": "com.example.demo",
            "device_id": "emulator-5554",
            "authorized": "true",
            "llm_provider": "openai",
        },
    )
    assert response.status_code == 200, response.text
    assert captured["provider"] == "openai"
    assert captured["model"] == next(
        provider["models"][0] for provider in server.PROVIDERS if provider["id"] == "openai"
    )


def test_mobile_api_key_goes_only_to_the_worker_environment(client,monkeypatch,tmp_path):
    captured={}
    def start(*args,**kwargs):
        captured.update(kwargs['env'])
        return FakeProcess()
    monkeypatch.setattr(server,'RUNS',tmp_path)
    monkeypatch.setattr(server,'jobs',{})
    monkeypatch.setattr(server,'_audit',lambda *a,**k:None)
    monkeypatch.setattr(server.threading,'Thread',FakeThread)
    monkeypatch.setattr(server.subprocess,'Popen',start)
    monkeypatch.setattr(android,'android_environment',lambda *a:DEVICE_ENVIRONMENT)
    from backend.privacy import PrivacyPolicy
    monkeypatch.setattr('backend.privacy.load_policy',lambda:PrivacyPolicy(mode='cloud',cloud_consent=True))
    fake_key='test-ephemeral-provider-value'
    response=client.post('/api/mobile/runs',headers=HEADERS,data={'app_mode':'installed','package_name':'com.example.demo','device_id':'emulator-5554','authorized':'true','llm_provider':'openai','api_key':fake_key,'allow_rules_fallback':'false','max_test_cases':'24'})
    assert response.status_code==200,response.text
    assert captured['OPENAI_API_KEY']==fake_key
    assert fake_key not in response.text
    config=(tmp_path/response.json()['run']/'.private'/'android_config.json').read_text()
    assert fake_key not in config
    assert json.loads(config)['max_test_cases']==24
    assert json.loads(config)['allow_rules_fallback'] is False
