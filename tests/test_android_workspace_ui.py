"""Review Android coverage and configuration without starting a device or AI call."""
import json
import re

from playwright.sync_api import expect

from tests import test_qpilot_ui

ROOT = test_qpilot_ui.ROOT
ui = test_qpilot_ui.ui


def test_android_coverage_shows_gaps_and_resume_only_when_safe(ui):
    page, requests, errors = ui
    data = {"scope": "Observed scenarios only", "counts": {"passed": 1, "blocked": 1},
            "cases": [{"id": "login", "title": "Login result", "status": "passed", "checks": 2,
                       "functional": True, "expected": "Account opens", "reason": "Assertions verified"},
                      {"id": "write", "title": "Interrupted signup", "status": "blocked", "checks": 0,
                       "functional": True, "expected": "Account created", "reason": "Reconcile data"}],
            "controls": [{"name": "Submit <img src=x>", "status": "not tested", "reason": "Not exercised"}],
            "gaps": [], "unvisited": [],
            "resume": {"can_resume": True, "uncertain": [{"id": "write"}]}}
    page.route("**/api/android/runs/android_test/coverage", lambda route: route.fulfill(json=data))
    page.evaluate("""() => {
      document.body.dataset.setupState='results';
      QpilotAndroid.update({id:7,run:'android_test',status:'done',target_type:'android'});
      QpilotLive.update({id:7,status:'done',target_type:'android'});
    }""")
    expect(page.locator('#androidCoverage .coverage-cases li')).to_have_count(2)
    expect(page.locator('.coverage-resume')).to_be_visible()
    page.locator('.coverage-filter').select_option('blocked')
    expect(page.locator('.coverage-cases li')).to_have_count(1)
    expect(page.locator('.coverage-cases')).to_contain_text('Interrupted signup')
    expect(page.locator('#liveMode')).to_contain_text('input values are hidden')
    assert page.locator('#androidCoverage img').count() == 0
    page.screenshot(path=str(ROOT / '.snapshots/qpilot_review/android-coverage.png'), full_page=True)
    assert not requests and not errors


def test_backend_check_attaches_to_workflow_without_adding_another_ui_flow(ui):
    page, requests, errors = ui
    captured = []
    def validate(route):
        contract = route.request.post_data_json['contract']
        captured.append(contract)
        route.fulfill(json={"compact_contract": contract})
    page.route('**/api/contracts/validate', validate)
    page.evaluate("""() => {
      document.getElementById('androidContract').value=JSON.stringify({version:1,flows:[{
        id:'signup',title:'Signup result',approved:true,steps:[{action:'assert_visible',locator:{strategy:'text',value:'Account'}}]
      }]});
      document.querySelector('[data-flow-tools="androidContract"] .backend-open').click();
    }""")
    # The heading names the dialog visually; select the active native dialog for accessibility-independent checks.
    dialog = page.locator('dialog[open]')
    dialog.locator('[name=title]').fill('Stored account status')
    dialog.locator('[name=flow]').select_option('signup')
    dialog.locator('[name=kind]').select_option('sqlite')
    dialog.locator('[name=database]').fill('BLOWAI_DB_TEST')
    dialog.locator('[name=query]').fill('SELECT status FROM accounts WHERE id = ?')
    dialog.locator('[name=parameters]').fill('[1]')
    dialog.locator('[name=expected]').fill('"active"')
    dialog.locator('[name=approved]').check()
    dialog.get_by_role('button', name='Add check', exact=True).click()
    expect(dialog).to_have_count(0)
    assert len(captured) == 1 and len(captured[0]['flows']) == 1
    check = captured[0]['checks'][0]
    assert captured[0]['flows'][0]['backend_checks'] == [check['id']]
    assert check['parameters'] == [1] and check['expected'] == 'active'
    assert not errors


def test_ai_draft_requires_review_before_it_can_be_added(ui):
    page, requests, errors = ui
    page.route('**/api/android/runs/android_test/scenario-draft', lambda route: route.fulfill(json={
        "contract": {"version": 1, "android_package": "com.example.app", "flows": [{"id": "draft_scenario",
                     "title": "Account appears", "approved": False,
                     "steps": [{"action": "assert_visible", "locator": {"strategy": "text", "value": "Account"}}]}]},
        "expected_basis": "User requirement", "note": "Draft only; nothing executed."}))
    page.route('**/api/contracts/validate', lambda route: route.fulfill(json={"compact_contract": route.request.post_data_json['contract']}))
    page.evaluate("QpilotScenarios.open('android_test')")
    page.locator('#scenarioRequest').fill('Verify Account is visible')
    page.get_by_role('button', name='Generate draft', exact=True).click()
    expect(page.locator('#scenarioReview')).to_have_value(re.compile('Account appears'))
    page.get_by_role('button', name='Add reviewed scenario').click()
    expect(page.locator('.scenario-message')).to_contain_text('Review and approve')
    page.locator('#scenarioApprove').check()
    page.get_by_role('button', name='Add reviewed scenario').click()
    expect(page.locator('dialog[open]')).to_have_count(0)
    result = json.loads(page.locator('#androidContract').input_value())
    assert result['flows'][0]['approved'] and result['test_environment']
    assert not errors


def test_benchmark_picker_never_copies_actual_results_as_known_truth(ui):
    page, requests, errors = ui
    page.route('**/qa-lab', lambda route: route.fulfill(content_type='text/html',
               body=(ROOT / 'frontend/qa-lab.html').read_text(encoding='utf-8')))
    page.route('**/api/history', lambda route: route.fulfill(json=[{'run':'android_fixture','verdict':'Risk'}]))
    page.route('**/api/cases/android_fixture/download', lambda route: route.fulfill(json=[
        {'id':'crash','title':'Known seeded crash','execution_status':'Failed'},
        {'id':'unknown','title':'Unknown behavior','execution_status':'Passed'}]))
    page.goto('http://qpilot.fixture/qa-lab')
    page.locator('#runs').select_option('android_fixture')
    page.get_by_text('Choose known-truth cases from a run',exact=True).click()
    expect(page.locator('.truth-cases select')).to_have_count(2)
    assert page.locator('[data-case-id=crash]').input_value() == ''
    page.locator('[data-case-id=crash]').select_option('failed')
    page.get_by_role('button',name='Use selected expectations').click()
    assert json.loads(page.locator('#expected').input_value()) == {'crash':'failed'}
    assert not requests and not errors
