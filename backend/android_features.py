"""Separate configured functionality evidence from observed UI visibility."""
import json

from .qa_contracts import flow_chain, parse_contract


def feature_matrix(state):
    cases = state.get('test_cases', [])
    results = {r['id']: r for r in state.get('results', [])}
    contract = parse_contract(state.get('config', {}).get('qa_contract'))
    flows = {flow.id: flow for flow in contract.flows}
    rules = {rule.id: rule for rule in contract.rules}
    checks = {check.id: check for check in contract.checks}
    # Test-build mode: replay-verified user-like flows are functional checks too (source: interaction / ai).
    auto = {}
    if state.get('auto_flows'):
        # Test-mode flows may press undoable actions (a cart's Remove, Log out, Sort): parse them with those rules.
        auto_contract = parse_contract({'version': 1, 'test_environment': True, 'test_mode': True,
                                        'flows': [item['flow'] for item in state['auto_flows']]})
        auto = {flow.id: flow for flow in auto_contract.flows}
    bindings = {}
    configured = []
    ui_bindings = {}

    def functional(case):
        return case.get('contract_id') or case.get('auto_flow_id')
    for case in cases:
        if not functional(case):
            for identifier in case.get('element_ids', []):
                ui_bindings.setdefault(identifier, []).append(case['id'])

    def passed(identifier):
        result = results.get(identifier, {})
        return result.get('outcome') == 'passed' and result.get('checks', 0) > 0
    for case in cases:
        identifier = functional(case)
        if not identifier:
            continue
        result = results.get(case['id'], {})
        outcome = result.get('outcome', 'blocked' if case.get('blocked') else 'not_run')
        if outcome == 'passed' and not passed(case['id']):
            outcome = 'inconclusive'
        configured.append({'id': case['id'], 'title': case['title'], 'expected': case.get('expected', ''), 'outcome': outcome,
                           'source': 'test_build' if case.get('auto_flow_id') else 'configured'})
        locators = []
        if case.get('auto_flow_id'):
            selected_flows = [auto[identifier]] if identifier in auto else []
        elif identifier in flows:
            selected_flows = flow_chain(contract, identifier)
        else:
            item = rules.get(identifier) or checks.get(identifier)
            selected_flows = flow_chain(contract, item.setup_flow) if item and item.setup_flow else []
            if identifier in rules:
                locators = [rules[identifier].actual, *[v.locator for v in rules[identifier].variables.values() if v.locator]]
        for flow in selected_flows:
            for step in flow.steps:
                locators.extend(locator for locator in (step.locator, step.target) if locator)
        for locator in locators:
            bindings.setdefault((locator.strategy, locator.value), set()).add(case['id'])
    components = {}
    for screen in state.get('screens', []):
        for element in screen.get('elements', []):
            if not (element.get('input_capable') or element.get('clickable') or element.get('resource_id')
                    or element.get('accessibility_id') or element.get('type') == 'text' and element.get('text')):
                continue
            key = (screen['id'], json.dumps(element.get('locators', [])[:1], sort_keys=True)
                   if element.get('locators') else element.get('id') or element.get('text'), element.get('class_name'))
            if key in components and not element.get('visible'):
                continue
            linked = set().union(*(bindings.get((loc['strategy'], loc['value']), set()) for loc in element.get('locators', [])))
            ui_cases = ui_bindings.get(element.get('id'), [])
            passing = [cid for cid in linked if passed(cid)]
            observed = bool(element.get('visible') or element.get('requires_scroll'))
            components[key] = {
                'screen_id': screen['id'], 'screen': screen.get('screen_name') or screen.get('activity') or screen['id'], 'element_id': element.get('id'),
                'name': element.get('accessibility_id') or element.get('text') or element.get('resource_id'),
                'type': element.get('type'), 'observed_rendered': observed, 'observed_after_scroll': bool(element.get('requires_scroll')),
                'configured_checks': sorted(linked), 'passing_configured_checks': passing,
                'visibility_checked': any(passed(cid) for cid in ui_cases),
                'interactive': bool(element.get('clickable') or element.get('input_capable')),
                'needs_functional_check': bool(element.get('clickable') or element.get('input_capable')) and not passing,
                'functional_status': 'covered_by_passing_configured_check' if passing else 'not_verified',
            }
    items = list(components.values())
    functional_counts = {outcome: sum(row['outcome'] == outcome for row in configured)
                         for outcome in ('passed', 'failed', 'error', 'blocked', 'inconclusive', 'not_run')}
    ui_results = [results[c['id']] for c in cases if not functional(c) and c['id'] in results]
    return {'configured_features': configured, 'components': items,
            'functional_checks': {'configured': len(configured), **functional_counts},
            'ui_checks': {'passed': sum(r['outcome'] == 'passed' and r.get('checks', 0) > 0 for r in ui_results)},
            # Every observed control without a passing functional check, by name: no count without the list
            'controls_needing_functional_checks': [{'screen': c['screen'], 'name': c['name'], 'type': c['type'],
                                                    'element_id': c['element_id']}
                                                   for c in items if c['needs_functional_check']],
            'controls_needing_functional_checks_count': sum(c['needs_functional_check'] for c in items),
            'limitation': 'Only observed controls and configured expectations are represented. Visibility alone does not verify functionality; undiscovered screens and states remain outside this inventory.'}
