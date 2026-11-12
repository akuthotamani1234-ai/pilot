"""Regression cases from the broad WDIO discovery/execution failure."""
import pytest
from selenium.common.exceptions import NoSuchElementException, WebDriverException

from backend import android_design, android_runtime
from backend.android import AndroidEnvironmentError, extract_screen, recover_system_ui, safe_navigation_elements


def screen(body, name="Home-screen"):
    return extract_screen('<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][500,900]">'
                          f'<node class="android.widget.ScrollView" content-desc="{name}" bounds="[0,0][500,800]">'
                          + body + '</node></node></hierarchy>', "com.example", "fixture", ".MainActivity")


def text(label, **attrs):
    attributes = ' '.join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f'<node class="android.widget.TextView" text="{label}" {attributes}/>'


def test_offscreen_and_hidden_ancestor_nodes_are_not_visible():
    result = screen(text("Visible", bounds="[0,20][150,50]")
                    + text("Outside", bounds="[0,950][150,980]")
                    + '<node class="android.view.ViewGroup" displayed="false">'
                    + text("Hidden") + '</node>')
    labels = {e['text']: e['visible'] for e in result['elements'] if e['type'] == 'text'}
    assert labels == {"Visible": True, "Outside": False, "Hidden": False}


def test_long_text_is_never_used_as_a_truncated_exact_locator_or_assertion():
    label = "Long heading " * 20
    result = screen(text(label, resource_id="com.example:id/heading"))
    node = next(e for e in result['elements'] if e['resource_id'])
    assert not node['text_comparable']
    assert not any(loc['strategy'] == 'text' for loc in node['locators'])
    assert node['locator_unique']


def test_shared_navigation_does_not_make_different_screen_containers_equal():
    home = screen(text("Welcome", resource_id="com.example:id/title"))
    forms = screen(text("Welcome", resource_id="com.example:id/title"), "Forms-screen")
    assert not android_runtime.same_screen(home, forms)


def test_webview_banner_changes_do_not_create_new_native_routes():
    def web(label):
        return extract_screen('<hierarchy><node class="android.webkit.WebView" bounds="[0,0][500,800]">'
                              + text(label) + '<node class="android.widget.Button" text="About" clickable="true"/>'
                              '</node><node class="android.widget.Button" text="Home" clickable="true"/></hierarchy>',
                              "com.example", "fixture", ".MainActivity")
    before, after = web("Temporary banner"), web("Actual page heading")
    assert android_runtime.same_screen(before, after)
    assert android_runtime.screen_key(before) == android_runtime.screen_key(after)
    assert [e['text'] for e in safe_navigation_elements(after)] == ["Home"]


def test_distinct_native_webview_containers_remain_distinct_routes():
    body = '<node class="android.webkit.WebView" bounds="[0,0][500,700]">' + text('Embedded content') + '</node>'
    offers = screen(body, 'Offers-screen')
    profile = screen(body, 'Profile-screen')
    assert not android_runtime.same_screen(offers, profile)


def test_menu_prefixed_preference_toggles_are_not_automatic_navigation():
    result = screen('<node class="android.widget.Button" content-desc="side-menu-star-forms" clickable="true"/>'
                    '<node class="android.widget.Button" content-desc="side-menu-item-forms" clickable="true"/>')
    assert [e['accessibility_id'] for e in safe_navigation_elements(result)] == ['side-menu-item-forms']


def test_loading_webview_is_waited_out_before_recording(monkeypatch):
    loading = screen(text("LOADING..."), "Web-screen")
    loaded = screen(text("Loaded page"), "Web-screen")
    sequence = iter([loading, loading, loaded, loaded])
    monkeypatch.setattr(android_runtime.time, 'sleep', lambda _: None)
    assert android_runtime.settled_screen(lambda: next(sequence)) is loaded


def test_font_glyphs_do_not_become_generated_ui_scenarios(monkeypatch):
    result = screen(text("\ue001") + text("Actual heading"))
    monkeypatch.setattr(android_design.llm, 'llm_enabled', lambda: False)
    state = {'screens': [result], 'config': {}, 'actions': [], 'log': []}
    designed = android_design.design_cases(state)
    glyph = next(e for e in result['elements'] if e['text'] == '\ue001')
    assert not any(glyph['id'] in c.get('element_ids', []) for c in designed['test_cases'] if c['kind'] == 'ui')


def test_navigation_replay_waits_for_the_destination_after_each_hop(monkeypatch, tmp_path):
    home = screen(text('Home'))
    forms = screen(text('Forms'), 'Forms-screen')
    android_design.normalize_screens([home, forms])
    link = {'id': 'open-forms', 'locators': [], 'visible': True}
    home['elements'].append(link)
    forms['path'] = ['open-forms']
    runtime = android_runtime.MobileRuntime(None, {}, [home, forms], {}, tmp_path)
    state = {'clicked': False, 'pending': 0, 'reads': 0}

    def inspect():
        state['reads'] += 1
        if state['pending']:
            state['pending'] -= 1
            return home
        return forms if state['clicked'] else home

    def tap(_):
        state.update(clicked=True, pending=2)

    monkeypatch.setattr(runtime, '_inspect', inspect)
    monkeypatch.setattr(runtime, 'tap', tap)
    monkeypatch.setattr(android_runtime.time, 'sleep', lambda _: None)
    runtime.open_screen(forms['id'])
    # It waited past the two frames still showing Home; the destination itself is settled on its first frame once
    # its stable identity matches (run android_20261110_110821_90cd6d)
    assert state['clicked'] and state['pending'] == 0 and state['reads'] >= 6


def test_device_loss_is_not_confused_with_an_app_assertion_or_missing_locator():
    message = "adb.exe: device 'emulator-5554' not found"
    assert android_runtime.device_unavailable(WebDriverException(message))
    assert not android_runtime.device_unavailable(AssertionError(message))
    assert not android_runtime.device_unavailable(NoSuchElementException(message))


def test_short_inspection_error_keeps_the_original_device_loss_cause():
    try:
        try:
            raise WebDriverException('Long driver metadata ' * 30 + "device 'emulator-5554' not found")
        except WebDriverException as error:
            raise AndroidEnvironmentError(str(error)[:300]) from error
    except AndroidEnvironmentError as wrapper:
        assert 'not found' not in str(wrapper)
        assert android_runtime.device_unavailable(wrapper)


def test_read_only_reuse_rejects_any_mutating_plan():
    assert android_runtime.read_only_case({'plan': [['open_screen', ['home']], ['assert_visible', ['title']]]})
    assert not android_runtime.read_only_case({'plan': [['open_screen', ['home']], ['tap', ['save']]]})
    assert not android_runtime.read_only_case({'plan': [['assert_contract', ['login']]]})


def test_system_process_anr_is_reported_without_clicking_platform_controls():
    xml = '<hierarchy><node package="android" text="Process system isn\'t responding"/></hierarchy>'
    with pytest.raises(AndroidEnvironmentError, match="system process is not responding"):
        recover_system_ui(None, xml)


def test_system_navigation_window_does_not_clip_the_application_inventory():
    xml = '''<hierarchy>
      <node package="com.android.systemui" class="android.widget.FrameLayout" bounds="[0,850][500,900]"/>
      <node package="com.example" class="android.widget.FrameLayout" bounds="[0,0][500,850]">
        <node package="com.example" class="android.widget.TextView" text="Actual app" bounds="[10,100][300,150]"/>
      </node>
    </hierarchy>'''
    result = extract_screen(xml, "com.example", "fixture", ".MainActivity")
    assert result['screen_name'] == 'Actual app'
    assert next(e for e in result['elements'] if e['text'] == 'Actual app')['visible']


def test_launch_handoff_waits_without_inspecting_the_launcher(monkeypatch, tmp_path):
    home = screen(text('Ready'))
    android_design.normalize_screens([home])
    packages = iter(['com.android.launcher', 'com.example', 'com.example'])

    class Driver:
        @property
        def current_package(self):
            return next(packages)

    runtime = android_runtime.MobileRuntime(Driver(), {}, [home], {}, tmp_path)
    inspected = []
    monkeypatch.setattr(runtime, '_inspect', lambda: inspected.append(True) or home)
    monkeypatch.setattr(android_runtime.time, 'sleep', lambda _: None)
    runtime.wait_for_start()
    assert 1 <= len(inspected) <= 2  # never the launcher; the app's stable screen is settled at once


def test_device_loss_during_fill_keeps_fatal_classification_without_input_values(monkeypatch):
    from backend.qa_runtime import AndroidContractAdapter, ContractRuntime

    adapter = AndroidContractAdapter(None, {}, None)
    monkeypatch.setattr(adapter, 'guard', lambda: None)
    monkeypatch.setattr(adapter, 'find', lambda _: object())
    monkeypatch.setattr(adapter, 'context', lambda _: None)

    def disconnect(*_):
        raise WebDriverException("device 'emulator-5554' not found; command included private-input")

    monkeypatch.setattr(adapter, 'fill', disconnect)
    contract = {'test_environment': True, 'flows': [{'id': 'input', 'title': 'Input', 'approved': True, 'steps': [
        {'action': 'fill', 'locator': {'strategy': 'accessibility_id', 'value': 'name'}, 'value': 'private-input'},
        {'action': 'assert_visible', 'locator': {'strategy': 'accessibility_id', 'value': 'result'}}]}]}
    with pytest.raises(RuntimeError) as caught:
        ContractRuntime(adapter, contract).execute('input')
    assert android_runtime.device_unavailable(caught.value)
    assert 'private-input' not in str(caught.value)


def test_empty_input_clears_without_sending_an_invalid_empty_keys_command():
    from backend.qa_runtime import AndroidContractAdapter

    class Element:
        text = 'Previous value'

        def clear(self):
            self.text = ''

        def send_keys(self, value):
            raise AssertionError('Empty input must be tested by clearing the field')

        def get_attribute(self, name):
            return 'false'

    class Driver:
        def is_keyboard_shown(self):
            return False

    element = Element()
    AndroidContractAdapter(Driver(), {}, None).fill(element, '')
    assert element.text == ''


@pytest.mark.parametrize('hint_visible', [True, False])
def test_empty_input_readback_distinguishes_a_hint_from_uncleared_text(hint_visible):
    from backend.qa_runtime import AndroidContractAdapter

    class Element:
        text = 'Required name'

        def clear(self):
            pass

        def get_attribute(self, name):
            return str(hint_visible).lower() if name == 'showing-hint' else 'false'

    class Driver:
        def is_keyboard_shown(self):
            return False

    adapter = AndroidContractAdapter(Driver(), {}, None)
    if hint_visible:
        adapter.fill(Element(), '')
    else:
        with pytest.raises(AssertionError, match='did not retain'):
            adapter.fill(Element(), '')
