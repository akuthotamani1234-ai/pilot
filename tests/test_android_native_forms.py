"""Regressions for the supplied General Store video: unknown CTA, Spinner/form grouping and lost ADB."""
import copy
import json
from types import SimpleNamespace

import pytest
from selenium.common.exceptions import NoSuchElementException, WebDriverException

from backend.android import extract_screen
from backend.android_design import normalize_screens
from backend.android_forms import destination_check, prepare_choices
from backend.android_interact import assertion_steps, find_form, reversible_candidates, screen_diff
from backend.android_runtime import device_unavailable, settled_screen_with_toasts
from backend.qa_contracts import parse_contract
from backend.qa_runtime import AndroidContractAdapter, ContractRuntime
from tests.android_form_fixture import FormApp, session
from tests.test_android_site import VirtualClock


@pytest.mark.parametrize('label', ["Let's  Shop",'Begin shopping','Proceed to catalog'])
def test_unknown_safe_primary_button_is_a_form_submit(tmp_path,label):
    _, launch, _ = session(tmp_path,FormApp(submit=label))
    form = find_form(launch)
    assert form and form['submit']['text'] == label
    assert len(form['dropdowns']) == 1 and len(form['radios']) == 2
    assert not reversible_candidates(launch)  # form controls are exercised together, not country-by-country


@pytest.mark.parametrize('label', ['Pay now','Delete account','Change password','Cancel','Reset App State'])
def test_unknown_submit_fallback_does_not_enable_protected_or_cancel_actions(tmp_path,label):
    _, launch, _ = session(tmp_path,FormApp(submit=label))
    assert find_form(launch) is None


def test_multiple_primary_buttons_require_explicit_scoping(tmp_path):
    _, launch, _ = session(tmp_path)
    other = copy.deepcopy(launch['elements'][-1])
    other.update(id='another',text='Another action',resource_id='another',locators=[{'strategy':'resource_id','value':'another'}])
    launch['elements'].append(other)
    assert find_form(launch) is None


def test_nested_login_scope_keeps_both_credentials_and_excludes_sidebar_search():
    xml = '''<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1080,2000]">
      <node class="android.widget.EditText" resource-id="sidebarSearch" hint="Search" bounds="[0,0][200,100]"/>
      <node class="android.widget.LinearLayout" resource-id="loginForm" bounds="[100,100][1000,1200]">
        <node class="android.widget.EditText" resource-id="username" hint="Username" bounds="[150,150][900,250]"/>
        <node class="android.widget.LinearLayout" resource-id="credentials" bounds="[150,300][900,700]">
          <node class="android.widget.EditText" resource-id="password" hint="Password" password="true" bounds="[150,300][900,400]"/>
          <node class="android.widget.Button" resource-id="submit" text="Log in" clickable="true" bounds="[150,500][900,600]"/>
        </node>
      </node></node></hierarchy>'''

    form = find_form(extract_screen(xml, 'com.example.login', 'emulator-5554', '.MainActivity'))

    assert form and form['kind'] == 'login'
    assert [element['resource_id'] for element in form['inputs']] == ['username', 'password']


@pytest.mark.parametrize('required_attribute', ['', 'required="true"'])
def test_required_consent_checkbox_is_not_auto_accepted_or_tested_as_a_separate_button(required_attribute):
    xml = f'''<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1080,2000]">
      <node class="android.widget.EditText" resource-id="email" hint="Email" bounds="[0,100][900,200]"/>
      <node class="android.widget.CheckBox" resource-id="terms" content-desc="I agree to the terms" {required_attribute}
        clickable="true" checkable="true" checked="false" bounds="[0,250][900,350]"/>
      <node class="android.widget.Button" resource-id="submit" text="Create account" clickable="true" bounds="[0,400][900,500]"/>
    </node></hierarchy>'''
    screen = extract_screen(xml, 'com.example.signup', 'emulator-5554', '.MainActivity')
    normalize_screens([screen])
    form = find_form(screen)

    assert form and len(form['required_checkboxes']) == 1
    assert form['required_checkboxes'][0]['required'] is bool(required_attribute)
    assert form['required_checkboxes'][0]['id'] in form['control_ids']
    prepare_choices(None, screen, form)
    assert form['choice_error'] and 'will not accept it automatically' in form['choice_error']
    assert form['choices'] == []
    assert not reversible_candidates(screen)


def test_multiple_ungrouped_radio_buttons_are_not_guessed_as_one_group():
    xml = '''<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1080,2000]">
      <node class="android.widget.EditText" resource-id="name" hint="Name" bounds="[0,100][900,200]"/>
      <node class="android.widget.RadioButton" resource-id="first" text="Option one" clickable="true" checkable="true" bounds="[0,250][900,350]"/>
      <node class="android.widget.RadioButton" resource-id="second" text="Option two" clickable="true" checkable="true" bounds="[0,350][900,450]"/>
      <node class="android.widget.Button" resource-id="submit" text="Continue" clickable="true" bounds="[0,500][900,600]"/>
    </node></hierarchy>'''
    screen = extract_screen(xml, 'com.example.form', 'emulator-5554', '.MainActivity')
    normalize_screens([screen])
    form = find_form(screen)

    assert form and len(form['radios']) == 2
    assert all(not element.get('choice_group') for element in form['radios'])
    prepare_choices(None, screen, form)
    assert 'no exposed native group' in form['choice_error']
    assert form['choices'] == []


@pytest.mark.parametrize('text_options', [False,True])
def test_real_native_form_path_is_grouped_replayed_and_reaches_products(tmp_path,text_options):
    with VirtualClock():
        runner, launch, app = session(tmp_path,FormApp(text_options=text_options))
        runner.form_checks(launch,find_form(launch))
    assert app.submissions and any(not name for name,_,_ in app.submissions)
    assert any(name and country == 'Beta' and gender == 'Male' for name,country,gender in app.submissions)
    positive = next(item for item in runner.flows if 'Form submission with valid details' in item['flow']['title'])
    steps = positive['flow']['steps']
    assert any(s['action'] == 'select' and s['value'] == 'Beta' for s in steps)
    assert any(s['action'] in ('assert_text','assert_screen') and s['value'] in ('Products','Widget') for s in steps)
    assert any(state['screen_name'] == 'Products' for state in runner.states)
    assert len(runner.flows) == 2  # empty-field validation and complete submission; no country option cases
    assert all(item['meta']['discovery_replay'] == 'passed' for item in runner.flows)
    empty = next(item['flow'] for item in runner.flows if 'Submitting the form empty' in item['flow']['title'])
    assert 'required' in empty['title'].casefold()
    assert 'text1' not in empty['title']
    assert any(step['action'] == 'assert_text' and 'required' in step['value'].casefold()
               for step in empty['steps'])
    validation_index=next(index for index,step in enumerate(empty['steps'])
                          if step['action']=='assert_text' and 'required' in step['value'].casefold())
    form_index=next(index for index,step in enumerate(empty['steps'])
                    if step['action']=='assert_visible' and step.get('locator',{}).get('value','').endswith('/name'))
    assert validation_index < form_index  # assert the short-lived message before spending time on other checks


def test_disappearing_form_without_a_destination_is_not_success(tmp_path):
    runner, launch, _ = session(tmp_path)
    after = {**launch,'screen_name':'Blank','identity':['blank'],'fingerprint':'blank','elements':[]}
    assert not destination_check(runner,launch,after,find_form(launch))


def test_configured_destination_is_preserved_even_when_application_disagrees(tmp_path):
    runner, launch, _ = session(tmp_path,expected_destinations={'Begin shopping':'Expected products'})
    assert destination_check(runner,launch,launch,find_form(launch)) == [
        {'action':'assert_screen','value':'Expected products'}]


@pytest.mark.parametrize('message', [
    'Could not proxy command to the remote server. Original error: socket hang up',
    'Error executing adbExec. Command output: error: closed',
    'adb.exe: transport error: closed',
])
def test_recorded_transport_losses_are_recognized_without_misclassifying_assertions(message):
    assert device_unavailable(WebDriverException(message))
    assert not device_unavailable(AssertionError(message))
    assert not device_unavailable(NoSuchElementException(message))


def test_native_select_requires_explicit_form_permission(tmp_path):
    runner, _, app = session(tmp_path)
    raw = {'test_environment':True,'test_mode':True,'android_package':app.current_package,'flows':[
        {'id':'choice','title':'Choice','approved':True,'steps':[
            {'action':'select','locator':{'strategy':'resource_id','value':app.current_package+':id/country'},'value':'Beta'},
            {'action':'assert_visible','locator':{'strategy':'resource_id','value':app.current_package+':id/country'}}]}]}
    contract = parse_contract(raw)
    with pytest.raises(RuntimeError,match='explicitly marked test_form'):
        ContractRuntime(AndroidContractAdapter(app,runner.device.config,contract),raw,{'secrets':{},'databases':{}}).execute('choice')
    assert not app.opened and app.country == 'Alpha'


def test_form_actions_do_not_expose_typed_values_in_live_events(tmp_path):
    with VirtualClock():
        runner, launch, app = session(tmp_path)
        runner.form_checks(launch,find_form(launch))
    text = ''.join(p.read_text(encoding='utf-8') for p in tmp_path.glob('events.android-*.jsonl'))
    names = {name for name,_,_ in app.submissions if name}
    assert names and all(name not in text for name in names)
    assert all(json.loads(line)['text'] for line in text.splitlines())


def test_wrong_native_selection_blocks_positive_submit_but_keeps_negative_validation(tmp_path):
    with VirtualClock():
        runner, launch, app = session(tmp_path,FormApp(bad_readback=True))
        runner.form_checks(launch,find_form(launch))
    assert app.submissions and all(not name for name,_,_ in app.submissions)
    assert any('Submitting the form empty' in item['flow']['title'] for item in runner.flows)
    assert not any('with valid details' in item['flow']['title'] for item in runner.flows)
    assert any(item['outcome'] == 'inconclusive' for item in runner.tried)


def test_choice_failure_does_not_skip_empty_field_validation(tmp_path):
    with VirtualClock():
        runner, launch, app = session(tmp_path, FormApp(bad_readback=True))
        runner.form_checks(launch, find_form(launch))

    assert any(not name for name, _, _ in app.submissions)
    assert not any(name for name, _, _ in app.submissions)
    assert any('Form choices' in item['check'] and item['outcome'] == 'inconclusive' for item in runner.tried)
    assert any('Submitting the form empty' in item['flow']['title'] for item in runner.flows)
    assert not any('with valid details' in item['flow']['title'] for item in runner.flows)


def test_error_destination_and_negated_success_are_not_success(tmp_path,monkeypatch):
    runner, launch, app = session(tmp_path)
    app.view = 'products'
    after = app.observe()
    after['elements'][1]['text'] = 'Error: not saved'
    after['screen_name'] = 'Error: not saved'
    form = find_form(launch)
    assert not destination_check(runner,launch,after,form)
    monkeypatch.setattr(runner,'observe_after',lambda *args,**kwargs: (launch,after))
    runner._positive_form_check(launch,form,'Form submission')
    assert not runner.flows and runner.tried[-1]['outcome'] == 'inconclusive'


def test_accessibility_only_error_label_cannot_become_a_success_destination(tmp_path, monkeypatch):
    runner, launch, _ = session(tmp_path)
    error = extract_screen('''<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1080,2000]">
      <node class="android.widget.TextView" content-desc="Login failed: invalid credentials" bounds="[0,100][900,200]"/>
    </node></hierarchy>''', 'com.example.nativeform', 'emulator-5554', '.MainActivity')
    form = find_form(launch)

    assert destination_check(runner, launch, error, form) == []
    monkeypatch.setattr(runner, 'observe_after', lambda *args, **kwargs: (launch, error))
    runner._positive_form_check(launch, form, 'Form submission')
    assert not runner.flows and runner.tried[-1]['outcome'] == 'inconclusive'


def test_form_fields_are_scoped_away_from_a_sidebar_search():
    xml = '''<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1080,2000]">
      <node class="android.widget.EditText" resource-id="sidebarSearch" hint="Search" bounds="[0,0][200,100]"/>
      <node class="android.widget.LinearLayout" bounds="[200,100][1080,1800]">
        <node class="android.widget.EditText" resource-id="name" hint="Your Name" bounds="[200,100][800,200]"/>
        <node class="android.widget.Button" resource-id="submit" text="Begin shopping" clickable="true" bounds="[200,300][800,400]"/>
      </node></node></hierarchy>'''
    form = find_form(extract_screen(xml,'com.example','emulator-5554','.Main'))
    assert [e['resource_id'] for e in form['inputs']] == ['name']


def test_android_toast_validation_is_captured_without_reading_other_system_ui():
    app='com.example.nativeform'
    before_xml=f'''<hierarchy><node class="android.widget.FrameLayout" package="{app}" bounds="[0,0][1080,2000]">
      <node class="android.widget.TextView" package="{app}" resource-id="{app}:id/title" text="General Store" bounds="[0,0][1080,100]"/>
      <node class="android.widget.EditText" package="{app}" resource-id="{app}:id/name" hint="Your Name" bounds="[0,100][900,200]"/>
      <node class="android.widget.Button" package="{app}" resource-id="{app}:id/submit" text="Let's Shop" clickable="true" bounds="[0,300][900,400]"/>
    </node></hierarchy>'''
    after_xml=before_xml.replace('</hierarchy>', '''
      <android.widget.Toast class="android.widget.Toast" package="com.android.settings" text="Please enter your name" displayed="true"/>
      <android.widget.Toast class="android.widget.Toast" package="com.android.settings" text="Toast message" displayed="true"/>
      <node class="android.widget.Button" package="com.android.settings" text="System Settings" displayed="true"/>
    </hierarchy>''')
    before=extract_screen(before_xml,app,'emulator-5554','.MainActivity')
    after=extract_screen(after_xml,app,'emulator-5554','.MainActivity')
    toast=next(element for element in after['elements'] if element.get('android_toast'))
    assert toast['text']=='Please enter your name' and toast['visible']
    assert toast['locators'][0]['strategy']=='xpath' and 'Please enter your name' in toast['locators'][0]['value']
    assert not any(element.get('text','').casefold()=='toast message' for element in after['elements'])
    assert after['screen_name']==before['screen_name']=='General Store'
    assert not any(element.get('text')=='System Settings' for element in after['elements'])
    changes=screen_diff(before,after)
    assert any(change['kind']=='message' and change['element']['text']=='Please enter your name' for change in changes)
    assert {'action':'assert_toast','value':'Please enter your name'} in assertion_steps(changes)


def test_native_toast_assertion_reads_live_hierarchy_without_a_stale_element(tmp_path):
    runner, _, app = session(tmp_path)
    toast_xml='''<hierarchy><node class="android.widget.FrameLayout" package="com.example.nativeform">
      <android.widget.Toast class="android.widget.Toast" package="com.android.settings"
        text="Name is required" displayed="true"/></node></hierarchy>'''

    class Driver:
        current_context = app.current_context
        current_package = app.current_package
        current_activity = app.current_activity
        capabilities = app.capabilities
        switch_to = app.switch_to
        page_source = toast_xml

        def find_elements(self, *_):
            raise AssertionError('Toast assertions must query the hierarchy, not a short-lived element')

        def __getattr__(self, name):
            return getattr(app, name)

    raw={'test_environment':True,'test_mode':True,'android_package':app.current_package,'flows':[
        {'id':'toast','title':'Name validation','approved':True,'steps':[
            {'action':'assert_toast','value':'Name is required'}]}]}
    contract=parse_contract(raw)
    runtime=ContractRuntime(AndroidContractAdapter(Driver(),runner.device.config,contract),raw,
                            {'secrets':{},'databases':{}})
    runtime.execute('toast')
    assert runtime.checks == 1


def test_native_toast_assertion_requires_the_exact_visible_message(tmp_path):
    runner, _, app = session(tmp_path)
    xml='''<hierarchy><android.widget.Toast class="android.widget.Toast" text="Different message"
      displayed="true"/></hierarchy>'''

    class Driver:
        current_context=app.current_context
        current_package=app.current_package
        page_source=xml
        switch_to=app.switch_to

        def __getattr__(self,name):
            return getattr(app,name)

    adapter=AndroidContractAdapter(Driver(),runner.device.config,None)
    with pytest.raises(AssertionError,match='was not visible'):
        adapter.assert_toast('Name is required',wait_s=0)


def test_stable_observation_keeps_immediate_toast_after_it_dismisses():
    app='com.example.nativeform'
    screen='''<hierarchy><node class="android.widget.FrameLayout" package="com.example.nativeform" bounds="[0,0][1080,2000]">
      <node class="android.widget.TextView" package="com.example.nativeform" resource-id="com.example.nativeform:id/title" text="General Store" bounds="[0,0][1080,100]"/>
    </node></hierarchy>'''
    toast=screen.replace('</hierarchy>', '<node class="android.widget.Toast" package="com.android.settings" text="Name is required" displayed="true"/></hierarchy>')
    snapshots=iter([extract_screen(toast,app,'emulator-5554','.MainActivity'),
                    extract_screen(screen,app,'emulator-5554','.MainActivity'),
                    extract_screen(screen,app,'emulator-5554','.MainActivity')])
    result=settled_screen_with_toasts(lambda:next(snapshots),timeout=1)
    assert result['screen_name']=='General Store'
    assert any(element.get('android_toast') and element['text']=='Name is required' for element in result['elements'])


def test_discovery_enters_a_list_screen_reached_after_form_submission(tmp_path):
    runner, launch, _ = session(tmp_path)
    listing=extract_screen('''<hierarchy><node class="android.widget.FrameLayout" package="com.example.nativeform" bounds="[0,0][1080,2000]">
      <node class="android.widget.TextView" package="com.example.nativeform" resource-id="com.example.nativeform:id/title" text="Products" bounds="[0,0][1080,100]"/>
      <node class="android.widget.TextView" package="com.example.nativeform" resource-id="com.example.nativeform:id/productName" text="Alpha product" clickable="true" bounds="[0,200][900,300]"/>
      <node class="android.widget.TextView" package="com.example.nativeform" resource-id="com.example.nativeform:id/productName" text="Beta product" clickable="true" bounds="[0,400][900,500]"/>
    </node></hierarchy>''','com.example.nativeform','emulator-5554','.ProductsActivity')
    normalize_screens([listing])
    listing['site_role']='screen'
    runner.states.append(listing)
    items=[item for item in runner.feature_items() if item['where']=='Products' and item['area']=='screen']
    assert len(items)==1 and items[0]['name']=="Open the first 'Alpha product' on Products"


def test_ai_journey_cannot_call_a_form_submission_without_input_setup(tmp_path):
    runner, launch, _ = session(tmp_path)
    button = find_form(launch)['submit']
    journey = SimpleNamespace(start='entry',title='Tap submit',steps=[
        SimpleNamespace(action='tap',element='submit'),
        SimpleNamespace(action='assert_visible',element='submit')])
    runner._journey(journey,{'entry':launch},{'submit':(launch,button)})
    assert not runner.flows and runner.tried[-1]['outcome'] == 'rejected'


def test_session_loss_during_fill_is_not_retried_and_omits_input_values(tmp_path,monkeypatch):
    from tests.android_form_fixture import Element
    runner, _, app = session(tmp_path)
    attempts = []
    def lost(self,value):
        attempts.append(value)
        raise WebDriverException('Could not proxy command to the remote server. Original error: socket hang up '+value)
    monkeypatch.setattr(Element,'send_keys',lost)
    raw={'test_environment':True,'test_mode':True,'android_package':app.current_package,'flows':[
        {'id':'fill','title':'Fill','approved':True,'steps':[
            {'action':'fill','locator':{'strategy':'resource_id','value':app.current_package+':id/name'},'value':'private-name'},
            {'action':'assert_visible','locator':{'strategy':'resource_id','value':app.current_package+':id/submit'}}]}]}
    contract=parse_contract(raw)
    with pytest.raises(RuntimeError) as caught:
        ContractRuntime(AndroidContractAdapter(app,runner.device.config,contract),raw,{'secrets':{},'databases':{}}).execute('fill')
    assert device_unavailable(caught.value) and 'private-name' not in str(caught.value)
    assert len(attempts) == 1 and not app.submissions
