"""Qpilot is public branding; legacy contracts, clients and secret guards still work."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from backend import privacy, server
from backend.android_interact import flow_secrets, generated_secrets
from backend.mcp_bridge import BlowAIBridge, QpilotBridge
from backend.qa_contracts import parse_contract
from backend.qa_oracles import resolve_private_inputs
from backend.safety import clean_env, redact
from setup.mcp_config import configuration


@pytest.mark.parametrize('prefix', ['QPILOT','BLOWAI'])
def test_both_contract_reference_families_resolve_private_aliases(prefix):
    other = 'BLOWAI' if prefix == 'QPILOT' else 'QPILOT'
    ref = prefix+'_SECRET_PASSWORD'
    db = prefix+'_DB_TEST'
    raw = {'test_environment':True,'flows':[{'id':'login','title':'Login','approved':True,
        'steps':[{'action':'fill','locator':{'strategy':'css','value':'#password'},'secret_ref':ref},
                 {'action':'assert_visible','locator':{'strategy':'css','value':'#account'}}]}],
        'checks':[{'id':'stored','title':'Stored status','kind':'sqlite','database_ref':db,
                   'query':'SELECT status FROM account','expected':'active'}]}
    inputs = resolve_private_inputs(parse_contract(raw),{other+'_SECRET_PASSWORD':'private-value',other+'_DB_TEST':'private.sqlite'})
    assert inputs['secrets'][ref] == 'private-value' and inputs['databases'][db] == 'private.sqlite'


def test_both_names_are_redacted_and_stripped_from_untrusted_worker_environments(monkeypatch):
    env = {'QPILOT_SECRET_ACCOUNT':'new-private','BLOWAI_SECRET_ACCOUNT':'old-private',
           'QPILOT_DB_TEST':'new.sqlite','BLOWAI_DB_TEST':'old.sqlite','PATH':'safe-path'}
    for key,value in env.items():
        if '_SECRET_' in key:
            monkeypatch.setenv(key,value)
    assert clean_env(env) == {'PATH':'safe-path'}
    assert 'new-private' not in redact('new-private old-private')
    assert 'old-private' not in redact('new-private old-private')


def test_new_auto_flows_use_qpilot_and_old_saved_values_remain_available():
    assert all(key.startswith('QPILOT_SECRET_') for key in generated_secrets())
    values = flow_secrets({'BLOWAI_SECRET_TEST_PASSWORD':'private-password'},
                         {'BLOWAI_SECRET_AUTO_ACCOUNT_USERNAME':'saved-user'})
    assert values['QPILOT_SECRET_TEST_PASSWORD'] == 'private-password'
    assert values['QPILOT_SECRET_AUTO_ACCOUNT_USERNAME'] == values['BLOWAI_SECRET_AUTO_ACCOUNT_USERNAME'] == 'saved-user'


def test_bridge_name_configuration_and_resource_aliases(tmp_path, monkeypatch):
    pytest.importorskip('mcp.server')
    from backend.mcp_server import build_server
    assert BlowAIBridge is QpilotBridge
    data = configuration(tmp_path)
    assert set(data['mcpServers']) == {'qpilot'}
    assert 'QPILOT_UI_URL' in data['mcpServers']['qpilot']['env']
    monkeypatch.setenv('QPILOT_UI_URL','http://127.0.0.1:8123')
    monkeypatch.setenv('BLOWAI_UI_URL','http://127.0.0.1:8124')
    monkeypatch.setattr(QpilotBridge,'verify',lambda self:{'product':'qpilot','bridge_version':1})
    instance = build_server()
    async def inspect():
        assert '8123' in str(await instance.call_tool('get_connection_info',{}))
        current = await instance.read_resource('qpilot://workflow')
        legacy = await instance.read_resource('blowai://workflow')
        assert 'start_prepared_test' in str(current) and str(current) == str(legacy)
    asyncio.run(inspect())


def test_current_and_legacy_wire_handshakes_preserve_privacy(tmp_path,monkeypatch):
    monkeypatch.setattr(privacy,'POLICY_PATH',tmp_path/'privacy.json')
    client = TestClient(server.app,base_url='http://127.0.0.1:8000')
    current = client.get('/api/mcp/info',headers={'X-Qpilot-Client':'mcp'}).json()
    legacy = client.get('/api/mcp/info',headers={'X-BlowAI-Client':'mcp'}).json()
    assert current['product'] == current['display_name'].lower() == 'qpilot'
    assert legacy['product'] == 'blow-ai' and legacy['display_name'] == 'Qpilot'
    assert not current['privacy']['mcp_allowed']
    assert 'test_password' not in json.dumps(current)
