"""MCP uses the same configured controls without copying credentials into chat."""

import pytest
from playwright.sync_api import expect

from backend import privacy
from tests import test_mcp_prepared, test_qpilot_ui

ui = test_qpilot_ui.ui
prepared = test_mcp_prepared.prepared


def bind_profiles(page, client):
    captured = []
    def route(request):
        body = request.request.post_data_json
        captured.append(body)
        result = client.post('/api/settings/mcp-requests',json=body)
        request.fulfill(status=result.status_code,json=result.json())
    page.route('**/api/settings/mcp-requests',route)
    page.route('**/api/settings/mcp-requests/*',lambda route: route.fulfill(json={'revoked':True}))
    page.route('**/api/android/environment**',lambda route: route.fulfill(json={
        'ok':True,'execution_revision':3,'devices':[{'device_id':'emulator-5554','status':'device','avd_name':'test-avd'}]}))
    return captured


@pytest.mark.parametrize('width,height', [(1440,900),(390,844)])
def test_android_shared_settings_prepare_exact_private_configuration(ui, prepared, width, height):
    page, _, errors = ui
    client, store, launched, devices = prepared
    captured = bind_profiles(page,client)
    page.set_viewport_size({'width':width,'height':height})
    page.locator('#mobileModeBtn').click()
    page.locator('#mcpWorkflowBtn').click()
    page.locator('#mcpAndroidSource').select_option('installed')
    page.locator('#mcpTarget').fill('com.example.fixture')
    page.locator('#mcpTask').fill('Verify login and displayed account details')
    page.locator('#mcpAndroidAuthorized').check()
    page.locator('#mcpAndroidTestBuild').check()
    page.locator('#androidProvider').select_option('none')
    page.locator('#mcpSharedSettings .mobile-advanced > summary').click()
    page.locator('#androidAccountMode').select_option('existing')
    page.locator('#androidTestUsername').fill('private-user')
    page.locator('#androidTestPassword').fill('private-password')
    page.locator('#androidMaxScreens').fill('8')
    page.locator('#androidDepth').fill('3')
    page.locator('#androidExpectations').fill('About = About')
    page.locator('#copyMcpRequest').click()
    expect(page.locator('#mcpRequestPreview')).to_be_visible()
    prompt = page.locator('#mcpRequestPreview').input_value()
    assert 'start_prepared_test' in prompt and 'authorized=true' in prompt
    assert 'private-user' not in prompt and 'private-password' not in prompt
    assert captured[0]['settings']['max_screens'] == '8'
    assert captured[0]['settings']['max_depth'] == '3'
    assert captured[0]['settings']['test_all_discovered'] is True
    assert len(store.entries) == 1 and not launched and not devices
    assert page.locator('#androidTestPassword').input_value() == ''
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    # The one shared field moves back without duplicating IDs or dropping nonprivate settings.
    page.locator('#standardWorkflowBtn').click()
    expect(page.locator('#mobileForm #androidMaxScreens')).to_have_value('8')
    assert page.locator('#androidMaxScreens').count() == 1
    assert page.locator('#mcpRequestPreview').is_hidden()
    assert not errors


@pytest.mark.parametrize('width,height', [(1440,900),(390,844)])
def test_web_reuses_account_provider_limits_and_workflow_builder(ui, prepared, width, height):
    page, _, errors = ui
    page.set_viewport_size({'width':width,'height':height})
    client, _, launched, devices = prepared
    captured = bind_profiles(page,client)
    page.locator('#mcpWorkflowBtn').click()
    page.locator('#mcpTarget').fill('https://example.test/')
    page.locator('#mcpTask').fill('Verify the account screen')
    page.locator('#mcpConfigureWeb').click()
    expect(page.locator('#mcpWebFields #aiAccountMode')).to_be_visible()
    page.locator('#aiAccountMode').select_option('existing')
    page.locator('#aiUser').fill('private-user')
    page.locator('#aiPass').fill('private-password')
    page.locator('.prov[data-id=none]').click()
    page.locator('#aiAuth').check()
    page.locator('#mcpWebFields .adv-box > summary').click()
    page.locator('#advDepth').fill('4')
    expect(page.locator('[data-flow-tools="webContract"] .flow-open')).to_be_visible()
    page.locator('#copyMcpRequest').click()
    expect(page.locator('#mcpRequestPreview')).to_be_visible()
    assert captured[0]['settings']['test_password'] == 'private-password'
    assert captured[0]['settings']['max_depth'] == 4
    assert 'private-password' not in page.locator('#mcpRequestPreview').input_value()
    assert not launched and not devices and not errors
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    folder = test_qpilot_ui.ROOT / '.snapshots' / 'mcp_docs'
    folder.mkdir(exist_ok=True)
    page.screenshot(path=str(folder / f'web-settings-{width}.png'),full_page=True)


def test_cloud_key_is_kept_in_studio_and_never_written_to_prompt_or_storage(ui, prepared):
    page, _, errors = ui
    client, store, launched, devices = prepared
    privacy.save_policy(privacy.PrivacyPolicy(mode='cloud',cloud_consent=True,allow_mcp=True))
    captured = bind_profiles(page,client)
    page.route('**/api/settings/privacy',lambda route: route.fulfill(json={
        'mode':'cloud','cloud_consent':True,'allow_mcp':True,'mcp_allowed':True,
        'allowed_providers':['none','ollama','openai']}))
    page.reload()
    page.locator('#mobileModeBtn').click()
    page.locator('#mcpWorkflowBtn').click()
    page.locator('#mcpAndroidSource').select_option('installed')
    page.locator('#mcpTarget').fill('com.example.fixture')
    page.locator('#mcpTask').fill('Check the home screen')
    page.locator('#mcpAndroidAuthorized').check()
    page.locator('#androidProvider').select_option('openai')
    page.locator('#androidModel').fill('fixture-model')
    page.locator('#androidApiKey').fill('sk-fixture-private-key')
    page.locator('#copyMcpRequest').click()
    expect(page.locator('#mcpRequestPreview')).to_be_visible()
    assert captured[0]['settings']['api_key'] == 'sk-fixture-private-key'
    assert next(iter(store.entries.values()))['settings']['llm_provider'] == 'openai'
    assert 'sk-fixture-private-key' not in page.locator('#mcpRequestPreview').input_value()
    assert 'sk-fixture-private-key' not in page.evaluate('JSON.stringify(localStorage)')
    assert page.locator('#androidApiKey').input_value() == ''
    assert not launched and not devices and not errors


def test_changing_settings_revokes_the_previous_prepared_request(ui, prepared):
    page, _, errors = ui
    client, _, _, _ = prepared
    bind_profiles(page,client)
    page.locator('#mobileModeBtn').click()
    page.locator('#mcpWorkflowBtn').click()
    page.locator('#mcpAndroidSource').select_option('installed')
    page.locator('#mcpTarget').fill('com.example.fixture')
    page.locator('#mcpTask').fill('Check home')
    page.locator('#mcpAndroidAuthorized').check()
    page.locator('#androidProvider').select_option('none')
    page.locator('#copyMcpRequest').click()
    expect(page.locator('#mcpRequestPreview')).to_be_visible()
    revoked = []
    page.route('**/api/settings/mcp-requests/*',lambda route: (
        revoked.append(route.request.url),route.fulfill(json={'revoked':True})))
    page.locator('#androidModel').fill('changed-model')
    expect(page.locator('#mcpRequestPreview')).to_be_hidden()
    page.wait_for_timeout(100)
    assert len(revoked) == 1 and not errors
