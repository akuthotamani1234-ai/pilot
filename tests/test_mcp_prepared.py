"""Prepared requests retain exact settings without exposing or replaying private inputs."""
import inspect

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import mcp_prepared, privacy, server
from backend.mcp_prepared import PreparedRequests, register_prepared_api


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(privacy, "POLICY_PATH", tmp_path / "privacy.json")
    privacy.save_policy(privacy.PrivacyPolicy(allow_mcp=True, local_assistant_confirmed=True))
    launched, devices = [], []
    async def mobile(**values):
        launched.append(values)
        return {"id": len(launched), "status": "running", "target_type": "android", "workflow": "mcp"}
    mobile.__signature__ = inspect.signature(server.start_mobile_run)
    def web(request):
        launched.append(request.model_dump())
        return {"id": len(launched), "status": "running", "target_type": "web", "workflow": "mcp"}
    async def device(request):
        devices.append(request.model_dump())
        return {"device_id": "emulator-5554"}
    def provider(requested, mode):
        return privacy.select_provider(requested, "none", "http://127.0.0.1:11434", mode)
    app = FastAPI()
    register_prepared_api(app, server.RunRequest, web, mobile, device, server.AndroidPrepareRequest,
                          provider, server.key_provider, server.KEY_ENV)
    return TestClient(app), app.state.prepared_mcp_requests, launched, devices


def android(**extra):
    return {"platform": "android", "target": "com.example.fixture", "task": "Verify login and its expected result",
            "avd_name": "test-avd", "settings": {"app_mode": "installed", "device_id": "avd:test-avd",
            "authorized": True, "llm_provider": "none", "interaction_testing": True,
            "test_all_discovered": True, "thorough": True, "max_screens": 0, "max_depth": 0,
            "test_username": "private-user", "test_password": "private-password", **extra}}


def prepare(client, body):
    response = client.post('/api/settings/mcp-requests', json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_prepare_is_read_only_and_response_never_contains_credentials(prepared):
    client, store, launched, devices = prepared
    body = android()
    body['task'] = 'Sign in as private-user using private-password'
    data = prepare(client, body)
    assert not launched and not devices
    assert 'private-user' not in str(data) and 'private-password' not in str(data)
    assert data['private_inputs_configured'] and data['expires_in_s'] == 900
    assert 'test_username' not in data['settings'] and 'test_password' not in data['settings']
    assert len(store.entries) == 1


def test_start_preserves_configuration_starts_selected_device_and_is_idempotent(prepared):
    client, store, launched, devices = prepared
    data = prepare(client, android(max_actions=70, expected_destinations='About = About', max_test_cases=280))
    url = f"/api/mcp/prepared/{data['request_id']}/start"
    first = client.post(url, json={'authorized': True})
    second = client.post(url, json={'authorized': True})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() and len(launched) == 1
    values = launched[0]
    assert values['test_username'] == 'private-user' and values['test_password'] == 'private-password'
    assert values['device_id'] == 'emulator-5554' and devices[0]['avd_name'] == 'test-avd'
    assert values['package_name'] == 'com.example.fixture'
    assert values['max_actions'] == 150  # existing Thorough floor, normalized before review
    assert values['max_test_cases'] == 280 and values['test_all_discovered']
    assert 'About' in values['expected_destinations']
    assert 'private-password' not in repr(store.entries)
    assert 'private-password' not in first.text


def test_web_setup_and_backend_checks_reach_the_existing_web_launcher(prepared):
    client, _, launched, devices = prepared
    data = prepare(client, {'platform':'web', 'target':'https://example.test/', 'task':'Verify the account page',
       'settings':{'authorized':True,'llm_provider':'none','auth_mode':'existing','test_username':'private-user',
                   'test_password':'private-password','max_pages':8,'max_depth':3,'environment':'staging',
                   'writes_confirmed':True,'review':True,'record_video':True,
                   'qa_contract':{'test_environment':True,'allowed_origins':['https://example.test'],
                                 'checks':[{'id':'status','title':'API status','kind':'http',
                                            'url':'https://example.test/status','expected':True}]}}})
    response = client.post(f"/api/mcp/prepared/{data['request_id']}/start",json={'authorized':True})
    assert response.status_code == 200 and not devices and len(launched) == 1
    values = launched[0]
    assert values['website_only'] and values['workflow'] == 'mcp' and values['writes_confirmed']
    assert values['max_pages'] == 8 and values['max_depth'] == 3
    assert values['qa_contract']['checks'][0]['id'] == 'status'
    assert values['test_password'] == 'private-password' and values['review']


@pytest.mark.parametrize('permission', [False, 'true', 1, None])
def test_start_requires_exact_explicit_permission(prepared, permission):
    client, _, launched, devices = prepared
    data = prepare(client, android())
    result = client.post(f"/api/mcp/prepared/{data['request_id']}/start",json={'authorized':permission})
    assert result.status_code in (400,422) and not launched and not devices


def test_revocation_expiry_and_changed_privacy_do_not_start_tests(prepared):
    client, store, launched, devices = prepared
    identifier = prepare(client, android())['request_id']
    client.delete('/api/settings/mcp-requests/'+identifier)
    assert client.post(f'/api/mcp/prepared/{identifier}/start',json={'authorized':True}).status_code == 410
    identifier = prepare(client, android())['request_id']
    privacy.save_policy(privacy.PrivacyPolicy(mode='cloud',cloud_consent=True,allow_mcp=True))
    assert client.post(f'/api/mcp/prepared/{identifier}/start',json={'authorized':True}).status_code == 409
    store.entries[identifier]['expires'] = 0
    assert client.post(f'/api/mcp/prepared/{identifier}/start',json={'authorized':True}).status_code == 410
    assert not launched and not devices


def test_unknown_overrides_and_invalid_validation_never_echo_private_inputs(prepared):
    client, _, launched, devices = prepared
    body = android()
    del body['task']
    response = client.post('/api/settings/mcp-requests',json=body)
    assert response.status_code == 422 and 'private-password' not in response.text
    data = prepare(client, android())
    response = client.post(f"/api/mcp/prepared/{data['request_id']}/start",json={'authorized':True,'api_key':'private-key'})
    assert response.status_code == 422 and 'private-key' not in response.text
    response = client.post('/api/settings/mcp-requests',json=android(max_screens=999))
    assert response.status_code == 400 and 'private-password' not in response.text
    assert not launched and not devices


def test_placeholder_apk_is_rejected_before_any_device_operation(prepared):
    client, _, launched, devices = prepared
    body = android(app_mode='apk')
    body['target'] = '/path/to/app.apk'
    response = client.post('/api/settings/mcp-requests',json=body)
    assert response.status_code == 400 and not launched and not devices


def test_only_studio_can_stage_private_inputs_for_mcp(tmp_path, monkeypatch):
    monkeypatch.setattr(privacy, 'POLICY_PATH', tmp_path/'privacy.json')
    privacy.save_policy(privacy.PrivacyPolicy(allow_mcp=True,local_assistant_confirmed=True))
    client = TestClient(server.app,base_url='http://127.0.0.1:8000')
    for header in ('X-Qpilot-Client','X-BlowAI-Client'):
        response = client.post('/api/settings/mcp-requests',json=android(),
                               headers={header:'mcp','X-Agentic-QA':'1'})
        assert response.status_code == 403


def test_registry_capacity_failure_and_atomic_claim():
    clock = [0.0]
    store = PreparedRequests(lambda: clock[0])
    identifier = store.put({'mode':'local','settings':{'api_key':'private-value'}})
    store.claim(identifier,'local')
    with pytest.raises(HTTPException) as caught:
        store.claim(identifier,'local')
    assert caught.value.status_code == 409
    store.fail(identifier)
    assert 'private-value' not in repr(store.entries)
    clock[0] = 901
    with pytest.raises(HTTPException) as caught:
        store.claim(identifier,'local')
    assert caught.value.status_code == 410
    for _ in range(mcp_prepared.MAX_PREPARED_REQUESTS):
        store.put({'mode':'local'})
    with pytest.raises(HTTPException) as caught:
        store.put({'mode':'local'})
    assert caught.value.status_code == 429


def test_failed_preparation_service_consumes_reference_and_drops_private_inputs(prepared, monkeypatch):
    client, store, launched, devices = prepared
    identifier = prepare(client, android())['request_id']

    def unavailable(*args, **kwargs):
        raise HTTPException(503,'Selected device is unavailable')

    # The existing preparation function receives this validated request before any launch.
    monkeypatch.setattr(server.AndroidPrepareRequest,'__init__',unavailable)
    route = f'/api/mcp/prepared/{identifier}/start'
    assert client.post(route,json={'authorized':True}).status_code == 503
    assert client.post(route,json={'authorized':True}).status_code == 409
    assert 'private-password' not in repr(store.entries) and 'private-user' not in repr(store.entries)
    assert not launched and not devices
