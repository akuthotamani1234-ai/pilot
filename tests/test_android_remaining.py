"""Coverage expansion must preserve scope, business assertions and device state."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from backend import android_pipeline
from backend.android import extract_screen, safe_navigation_elements
from backend.android_permissions import PermissionSession
from backend.qa_contracts import PermissionPolicy, contract_case_budget, contract_cases, parse_contract
from backend.qa_runtime import AndroidContractAdapter, ContractRuntime

CAMERA = 'android.permission.CAMERA'
PACKAGE = 'com.example.fixture'
CONTROLLER = 'com.android.permissioncontroller'


def test_breadth_first_discovery_does_not_consume_depth_on_sibling_tabs(tmp_path, monkeypatch):
    graph = {'Root': ['About', 'Settings'], 'About': ['Settings'], 'Settings': ['Dashboard'], 'Dashboard': []}

    class Element:
        def __init__(self, driver, target):
            self.driver, self.target = driver, target

        def is_displayed(self):
            return True

        def is_enabled(self):
            return True

        def click(self):
            self.driver.history.append(self.driver.name)
            self.driver.name = self.target

    class Driver:
        name = 'Root'
        current_package = PACKAGE
        current_activity = '.Main'

        def __init__(self):
            self.history = []

        @property
        def page_source(self):
            return '<hierarchy><node class="android.widget.TextView" text="' + self.name + '"/>' + ''.join(
                '<node class="android.widget.Button" resource-id="' + PACKAGE + ':id/' + target + '" text="' + target + '" clickable="true"/>'
                for target in graph[self.name]) + '</hierarchy>'

        def find_elements(self, by, value):
            return [Element(self, target) for target in graph[self.name] if value.endswith('/' + target)]

        def back(self):
            self.name = self.history.pop() if self.history else 'Root'

        def terminate_app(self, _):
            self.name = 'Root'

        def activate_app(self, _):
            self.name = 'Root'

        def quit(self):
            pass

    driver = Driver()
    monkeypatch.setattr(android_pipeline, 'create_session', lambda _: driver)
    monkeypatch.setattr(android_pipeline.time, 'sleep', lambda _: None)
    result = android_pipeline.discovery_agent({'config': {'app_mode': 'installed', 'package_name': PACKAGE,
        'device_id': 'emulator-5554', 'max_depth': 2, 'max_actions': 20, 'max_screens': 10}, 'run_dir': str(tmp_path)})
    screens = {s['screen_name']: s for s in result['screens']}
    assert len(screens['Settings']['path']) == 1
    assert len(screens['Dashboard']['path']) == 2
    assert not result['discovery_issues']
    assert driver.name == 'Root'


def test_react_native_menu_panel_excludes_background_controls():
    result = extract_screen('''<hierarchy>
      <node class="android.widget.Button" content-desc="Home" clickable="true"/>
      <node class="android.view.ViewGroup" content-desc="tab-side-menu-panel">
        <node class="android.widget.Button" text="Login" clickable="true"/>
        <node class="android.widget.Button" content-desc="side-menu-item-forms" clickable="true"/>
      </node></hierarchy>''', PACKAGE, 'fixture', '.Main')
    assert result['screen_name'] == 'Navigation menu'
    assert [e['text'] or e['accessibility_id'] for e in safe_navigation_elements(result)] == ['Login', 'side-menu-item-forms']


def flow(identifier, setup=None, approved=True, timeout=90):
    return {'id': identifier, 'title': identifier, 'approved': approved, 'setup_flow': setup, 'timeout_s': timeout,
            'steps': [{'action': 'assert_visible', 'locator': {'strategy': 'text', 'value': 'Dashboard'}}]}


def test_login_setup_chains_have_bounded_budgets_and_recursive_approval():
    contract = parse_contract({'test_environment': True, 'flows': [flow('login'), flow('protected', 'login', timeout=180)]})
    assert contract_case_budget(contract, 'protected') == 270
    contract.flows[0].approved = False
    assert all(c['blocked'] for c in contract_cases(contract))
    with pytest.raises(ValueError, match='cycle'):
        parse_contract({'flows': [flow('a', 'b'), flow('b', 'a')]})
    with pytest.raises(ValueError, match='600'):
        parse_contract({'flows': [flow('a', timeout=300), flow('b', 'a', timeout=300), flow('c', 'b')]})


def test_setup_login_executes_before_protected_checks():
    class Adapter:
        def __init__(self):
            self.events = []

        def guard(self):
            pass

        def context(self, _):
            pass

        def find(self, locator):
            return locator.value

        def identity(self, _):
            return 'Login'

        def enabled(self, _):
            return True

        def tap(self, _):
            self.events.append('login')

        def input_sensitive(self, _):
            return False

        def text(self, _):
            return 'Dashboard'

        def visible(self, _):
            self.events.append('protected')
            return True

    login = flow('login')
    login.update(authentication=True, steps=[
        {'action': 'tap', 'purpose': 'test_form', 'locator': {'strategy': 'text', 'value': 'Login'}},
        {'action': 'assert_text', 'locator': {'strategy': 'text', 'value': 'Dashboard'}, 'value': 'Dashboard'}])
    adapter = Adapter()
    runtime = ContractRuntime(adapter, {'test_environment': True, 'flows': [login, flow('protected', 'login')]})
    runtime.execute('protected')
    assert adapter.events == ['login', 'protected']
    assert runtime.authentication_verified and runtime.checks == 2


class PermissionDriver:
    current_context = 'NATIVE_APP'

    def __init__(self, granted=False):
        self.current_package = PACKAGE
        self.granted = {CAMERA} if granted else set()
        self.changes = []
        self.clicks = []
        self.message = 'Allow Fixture App to take pictures and record video?'

    def execute_script(self, name, args):
        assert args['appPackage'] == PACKAGE
        if name == 'mobile: getPermissions':
            return [CAMERA] if args['type'] == 'requested' else sorted(self.granted)
        assert name == 'mobile: changePermissions' and args['target'] == 'pm'
        self.changes.append(args)
        if args['action'] == 'grant':
            self.granted.add(args['permissions'][0])
        else:
            self.granted.discard(args['permissions'][0])

    def terminate_app(self, package):
        assert package == PACKAGE
        self.current_package = PACKAGE

    def find_elements(self, by, value):
        assert by == 'id'
        if not value.startswith(CONTROLLER + ':id/'):
            return []
        driver = self
        name = value.rsplit('/', 1)[-1]
        if name not in {'permission_message', 'permission_allow_foreground_only_button', 'permission_deny_button'}:
            return []

        class Element:
            text = driver.message

            def is_displayed(self):
                return True

            def get_attribute(self, name):
                assert name == 'package'
                return driver.current_package

            def click(self):
                driver.clicks.append(name)
                if name == 'permission_allow_foreground_only_button':
                    driver.granted.add(CAMERA)
                driver.current_package = PACKAGE
        return [Element()]


def permission_session(driver, device='emulator-5554'):
    return PermissionSession(driver, {'package_name': PACKAGE, 'device_id': device},
                             PermissionPolicy(approved=True, app_label='Fixture App', allowed=[CAMERA]), lambda: None)


def request_button(driver, controller=CONTROLLER):
    class Element:
        def is_enabled(self):
            return True

        def click(self):
            driver.current_package = controller
    return Element()


@pytest.mark.parametrize('original', [True, False])
@pytest.mark.parametrize('choice', ['allow_while_using', 'deny'])
@pytest.mark.parametrize('controller', [CONTROLLER, 'com.google.android.permissioncontroller'])
def test_permission_prompts_are_scoped_and_original_state_is_restored(original, choice, controller):
    driver = PermissionDriver(original)
    session = permission_session(driver)
    session.set_state(CAMERA, 'denied')
    session.request(request_button(driver, controller), CAMERA, 'permission-switch-camera')
    result = session.handle(CAMERA, choice)
    assert result['state'] == ('denied' if choice == 'deny' else 'granted')
    session.restore()
    assert (CAMERA in driver.granted) == original


@pytest.mark.parametrize('message', ['Allow Another App to take pictures?', 'Allow Fixture App to record audio?'])
def test_wrong_app_or_permission_group_is_never_accepted(message):
    driver = PermissionDriver()
    driver.message = message
    session = permission_session(driver)
    session.request(request_button(driver), CAMERA, 'Camera permission')
    with pytest.raises(ValueError, match='does not match'):
        session.handle(CAMERA, 'allow_while_using')
    session.restore()
    assert not driver.clicks and not driver.granted


def test_permission_actions_cannot_control_a_phone_or_bypass_irreversible_actions():
    driver = PermissionDriver()
    with pytest.raises(ValueError, match='emulator'):
        permission_session(driver, 'physical-phone').set_state(CAMERA, 'granted')
    session = permission_session(driver)
    with pytest.raises(ValueError, match='irreversible'):
        session.request(request_button(driver), CAMERA, 'Delete account permission')
    assert not driver.changes


def test_permission_changes_are_restored_after_a_failed_assertion(monkeypatch):
    contract = parse_contract({'test_environment': True,
        'android_permissions': {'approved': True, 'app_label': 'Fixture App', 'allowed': [CAMERA]},
        'flows': [{'id': 'permission', 'title': 'Permission', 'approved': True, 'steps': [
            {'action': 'permission_state', 'permission': CAMERA, 'value': 'granted'},
            {'action': 'assert_permission', 'permission': CAMERA, 'value': 'denied'}]}]})
    driver = PermissionDriver()
    adapter = AndroidContractAdapter(driver, {'package_name': PACKAGE, 'device_id': 'emulator-5554'}, contract)
    monkeypatch.setattr(adapter.permissions, 'relaunch', lambda: None)
    monkeypatch.setattr(adapter, 'context', lambda _: None)
    with pytest.raises(AssertionError, match='Unexpected Android permission state'):
        ContractRuntime(adapter, contract.model_dump()).execute('permission')
    assert not driver.granted and len(driver.changes) == 2


def test_permission_steps_need_an_explicit_policy():
    with pytest.raises(ValueError, match='permission policy'):
        parse_contract({'test_environment': True, 'flows': [{'id': 'permission', 'title': 'Permission', 'approved': True, 'steps': [
            {'action': 'assert_permission', 'permission': CAMERA, 'value': 'denied'}]}]})


def test_run_credentials_are_worker_only_and_never_saved_in_configuration(tmp_path, monkeypatch):
    from backend import android, server
    from tests.test_android_api import DEVICE_ENVIRONMENT, FakeProcess, FakeThread

    captured = {}

    def launch(*_, **kwargs):
        captured.update({key: kwargs['env'].get(key) for key in ('BLOWAI_SECRET_TEST_USERNAME', 'BLOWAI_SECRET_TEST_PASSWORD')})
        return FakeProcess()

    monkeypatch.setattr(server, 'RUNS', tmp_path)
    monkeypatch.setattr(server, 'jobs', {})
    monkeypatch.setattr(server, '_audit', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server.threading, 'Thread', FakeThread)
    monkeypatch.setattr(server.subprocess, 'Popen', launch)
    monkeypatch.setattr(android, 'android_environment', lambda *_: DEVICE_ENVIRONMENT)
    with TestClient(server.app, base_url='http://127.0.0.1') as client:
        result = client.post('/api/mobile/runs', headers={'X-Agentic-QA': '1'}, data={
            'authorized': 'true', 'app_mode': 'installed', 'device_id': 'emulator-5554',
            'package_name': PACKAGE, 'llm_provider': 'none', 'test_username': 'private-test-user',
            'test_password': 'private-test-password',
        })
    assert result.status_code == 200
    assert captured == {'BLOWAI_SECRET_TEST_USERNAME': 'private-test-user', 'BLOWAI_SECRET_TEST_PASSWORD': 'private-test-password'}
    saved = (tmp_path / result.json()['run'] / '.private/android_config.json').read_text(encoding='utf-8') + result.text
    assert 'private-test-user' not in saved and 'private-test-password' not in saved


@pytest.mark.parametrize('choice', ['allow', 'deny'])
def test_declared_media_request_handles_each_permission_prompt_and_restores_state(choice):
    audio = 'android.permission.READ_MEDIA_AUDIO'
    images = 'android.permission.READ_MEDIA_IMAGES'

    class Driver(PermissionDriver):
        stage = 0

        def execute_script(self, name, args):
            if name == 'mobile: getPermissions' and args['type'] == 'requested':
                return [audio, images]
            return super().execute_script(name, args)

        def find_elements(self, by, value):
            driver = self
            name = value.rsplit('/', 1)[-1]
            if name not in {'permission_message', 'permission_allow_button', 'permission_deny_button'}:
                return []

            class Element:
                @property
                def text(self):
                    return 'Allow Fixture App to access music and audio files?' if driver.stage == 0 else 'Allow Fixture App to access photos?'

                def get_attribute(self, _):
                    return CONTROLLER

                def is_displayed(self):
                    return True

                def click(self):
                    if name == 'permission_allow_button':
                        driver.granted.add(audio if driver.stage == 0 else images)
                    driver.stage += 1
                    if driver.stage == 2:
                        driver.current_package = PACKAGE
            return [Element()]

    driver = Driver()
    policy = PermissionPolicy(approved=True, app_label='Fixture App', allowed=[audio, images])
    session = PermissionSession(driver, {'device_id': 'emulator-5554', 'package_name': PACKAGE}, policy, lambda: None)
    session.request(request_button(driver), images, 'Photo library permission', [images, audio])
    evidence = session.handle(images, choice)
    assert len(evidence['prompt_groups']) == 2
    assert driver.granted == ({audio, images} if choice == 'allow' else set())
    session.restore()
    assert not driver.granted


def test_permission_stop_does_not_accept_a_prompt_and_still_allows_cleanup(tmp_path):
    driver = PermissionDriver()
    session = permission_session(driver)
    session.stop_path = tmp_path / 'STOP'
    session.request(request_button(driver), CAMERA, 'Camera permission')
    session.stop_path.write_text('stop')
    with pytest.raises(InterruptedError):
        session.handle(CAMERA, 'allow_while_using')
    session.restore()
    assert not driver.clicks and not driver.granted


def test_offscreen_inventory_and_replay_use_observed_controls_and_restore_the_top(tmp_path):
    from backend.android_design import normalize_screens
    from backend.android_scroll import discover_viewports, seek_observed

    class Element:
        def __init__(self, driver, name):
            self.driver, self.name, self.id = driver, name, name

        def is_displayed(self):
            return self.name != 'Bottom' or self.driver.viewport == 1

    class Driver:
        current_package = PACKAGE
        current_activity = '.Main'
        viewport = 0

        @property
        def page_source(self):
            bottom = '[10,100][300,150]' if self.viewport else '[10,750][300,800]'
            return ('<hierarchy><node class="android.widget.ScrollView" content-desc="Home-screen" '
                    'scrollable="true" bounds="[0,0][500,600]">'
                    '<node class="android.widget.TextView" text="Heading" bounds="[10,10][300,40]"/>'
                    '<node class="android.widget.Button" content-desc="Bottom" clickable="true" bounds="' + bottom + '"/>'
                    '</node></hierarchy>')

        def find_elements(self, by, value):
            return [Element(self, value)] if by == 'accessibility id' and value in {'Home-screen', 'Bottom'} else []

        def execute_script(self, name, args):
            assert name == 'mobile: scrollGesture' and args['elementId'] == 'Home-screen'
            self.viewport = 1 if args['direction'] == 'down' else 0
            return False

        def save_screenshot(self, _):
            return False

    driver = Driver()
    config = {'package_name': PACKAGE, 'device_id': 'emulator-5554', 'max_scroll_actions': 4}
    screen = extract_screen(driver.page_source, PACKAGE, config['device_id'], '.Main')
    normalize_screens([screen])
    budget = {}
    assert not discover_viewports(driver, screen, config, budget, time.monotonic() + 10, tmp_path)
    bottom = next(e for e in screen['elements'] if e['accessibility_id'] == 'Bottom')
    assert bottom['visible'] and bottom['requires_scroll'] and driver.viewport == 0
    selected, locator, attempts = seek_observed(driver, screen, bottom, config)
    assert selected.name == 'Bottom' and locator['value'] == 'Bottom' and attempts == 1
    assert budget == {'scroll': 1, 'scroll_recovery': 1}


def test_visibility_does_not_count_as_functionality_and_zero_assertions_do_not_pass():
    from backend.android_features import feature_matrix

    element = {'id': 'e1', 'type': 'button', 'class_name': 'Button', 'accessibility_id': 'Save',
               'clickable': True, 'visible': True, 'locators': [{'strategy': 'accessibility_id', 'value': 'Save'}]}
    state = {'screens': [{'id': 's1', 'screen_name': 'Home', 'elements': [element]}],
             'test_cases': [{'id': 'ui', 'element_ids': ['e1']}], 'results': [{'id': 'ui', 'outcome': 'passed', 'checks': 1}]}
    matrix = feature_matrix(state)
    assert matrix['ui_checks']['passed'] == 1 and matrix['functional_checks']['passed'] == 0
    assert matrix['controls_needing_functional_checks_count'] == 1
    assert [row['name'] for row in matrix['controls_needing_functional_checks']] == ['Save']  # a list, not a count
    state['config'] = {'qa_contract': {'test_environment': True, 'flows': [{'id': 'save', 'title': 'Save test data',
        'approved': True, 'steps': [{'action': 'assert_visible', 'locator': element['locators'][0]}]}]}}
    state['test_cases'].append({'id': 'contract_save', 'contract_id': 'save', 'title': 'Save test data'})
    state['results'].append({'id': 'contract_save', 'outcome': 'passed', 'checks': 0})
    assert feature_matrix(state)['functional_checks']['inconclusive'] == 1
    state['results'][-1]['checks'] = 1
    matrix = feature_matrix(state)
    assert matrix['functional_checks']['passed'] == 1 and matrix['controls_needing_functional_checks'] == []


def test_example_library_is_app_bound_and_permissions_start_blocked():
    from backend import server

    with TestClient(server.app, base_url='http://127.0.0.1') as client:
        catalog = client.get('/api/contracts/examples').json()['examples']
        assert any(row['id'] == 'wdio-complete' for row in catalog)
        data = client.get('/api/contracts/examples/wdio-complete').json()
        contract = parse_contract(data['contract'])
        assert contract.android_package == 'com.wdiodemoapp' and len(contract.flows) == 33
        cases = contract_cases(contract)
        assert sum(c['blocked'] for c in cases) == 7
        assert not contract.android_permissions.approved
        assert client.get('/api/contracts/examples/unknown').status_code == 404


def test_private_input_preflight_rejects_missing_references_before_starting_worker(tmp_path, monkeypatch):
    from backend import android, server
    from tests.test_android_api import DEVICE_ENVIRONMENT

    reference = 'BLOWAI_SECRET_MISSING_PREFLIGHT'
    monkeypatch.delenv(reference, raising=False)
    monkeypatch.setattr(server, 'RUNS', tmp_path)
    monkeypatch.setattr(server, 'jobs', {})
    monkeypatch.setattr(android, 'android_environment', lambda *_: DEVICE_ENVIRONMENT)
    monkeypatch.setattr(server.subprocess, 'Popen', lambda *_args, **_kwargs: pytest.fail('Missing credentials must not start a worker'))
    contract = {'test_environment': True, 'flows': [{'id': 'login', 'title': 'Login', 'approved': True, 'steps': [
        {'action': 'fill', 'locator': {'strategy': 'accessibility_id', 'value': 'Password'}, 'secret_ref': reference},
        {'action': 'assert_screen', 'value': 'Dashboard'}]}]}
    with TestClient(server.app, base_url='http://127.0.0.1') as client:
        response = client.post('/api/mobile/runs', headers={'X-Agentic-QA': '1'}, data={
            'app_mode': 'installed', 'package_name': PACKAGE, 'device_id': 'emulator-5554',
            'authorized': 'true', 'llm_provider': 'none', 'qa_contract': json.dumps(contract)})
    assert response.status_code == 400 and reference in response.json()['detail']
    assert not list(tmp_path.iterdir())


def test_native_examples_cannot_target_a_different_app_and_secrets_cannot_enter_saved_config():
    from backend.android import AndroidEnvironmentError, validate_mobile_config

    config = {'app_mode': 'installed', 'device_id': 'emulator-5554', 'package_name': PACKAGE}
    with pytest.raises(AndroidEnvironmentError, match='different native Android app'):
        validate_mobile_config({**config, 'qa_contract': {'android_package': 'com.different.app'}})
    with pytest.raises(AndroidEnvironmentError, match='private inputs'):
        validate_mobile_config({**config, 'test_password': 'private-test-marker'})
