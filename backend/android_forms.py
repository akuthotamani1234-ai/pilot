"""Native form controls and observed outcomes; no application-specific labels or locators."""
import re

from .qa_contracts import protected


def outcome_error(text: str) -> bool:
    return bool(re.search(r'\b(error|invalid|incorrect|required|denied|failed|failure|unsuccessful|unavailable|'
                          r'not (?:saved|created|accepted|registered|submitted|successful|allowed)|unable to)\b', text, re.I))


def is_spinner(element: dict) -> bool:
    return element.get('class_name', '').endswith('Spinner')


def submission_below_fields(inputs: list[dict], buttons: list[dict]) -> dict | None:
    """Separate a single form submission from mode selectors above all fields.

    Require complete geometry and a shared form ancestor; multiple actions below
    the fields or controls interleaved with inputs remain ambiguous.
    """
    def rect(element):
        match = re.fullmatch(r'\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]', element.get('bounds') or '')
        return tuple(map(int, match.groups())) if match else None

    fields = [rect(element) for element in inputs]
    actions = [(button, rect(button)) for button in buttons]
    if not fields or not all(fields) or not all(box for _, box in actions):
        return None
    top, bottom = min(box[1] for box in fields), max(box[3] for box in fields)
    below = [button for button, box in actions if box[1] >= bottom]
    if len(below) != 1 or any(box[3] > top for button, box in actions if button is not below[0]):
        return None
    common = set(below[0].get('form_ancestors', []))
    for field in inputs:
        common.intersection_update(field.get('form_ancestors', []))
    return below[0] if common else None


def fallback_submit(elements: list[dict], usable, label) -> dict | None:
    """Only an unambiguous primary button can substitute for an unfamiliar submit label."""
    buttons = [e for e in elements if usable(e) and e.get('clickable')
               and e.get('class_name', '').endswith(('.Button', '.MaterialButton', '.AppCompatButton'))
               and not e.get('navigation_role')]
    # Do not select Cancel beside Pay/Delete merely because the dangerous button was filtered out.
    if len(buttons) != 1:
        return None
    button = buttons[0]
    words = label(button)
    if not words or protected(words, True, True) or re.search(
            r'\b(cancel|close|back|menu|help|dismiss|skip)\b', words, re.I):
        return None
    return button


def attach_controls(form: dict, screen: dict, usable) -> dict:
    from .android_interact import label

    scope = form.get('scope')
    controls = [e for e in screen.get('elements', []) if scope and usable(e)
                and scope in e.get('form_ancestors', [])]
    form['dropdowns'] = [e for e in controls if is_spinner(e)]
    form['radios'] = [e for e in controls if e.get('class_name', '').endswith('RadioButton')]
    form['checkboxes'] = [e for e in controls if e.get('checkable')
                          and not e.get('class_name', '').endswith('RadioButton')]
    form['required_checkboxes'] = [e for e in form['checkboxes'] if e.get('required') or re.search(
        r'\b(terms?|conditions|consent|agree|accept)\b', label(e), re.I)]
    form['control_ids'] = [e['id'] for e in [*form['inputs'], form['submit'], *form['dropdowns'],
                                             *form['radios'], *form['checkboxes']] if e.get('id')]
    return form


def scope_inputs(inputs: list[dict], submit: dict) -> tuple[list[dict], str | None]:
    from .android_interact import LOGIN, SEARCH, label

    submit_label = label(submit)
    search_form = bool(SEARCH.search(submit_label))
    candidates = [e for e in inputs if bool(SEARCH.search(label(e))) == search_form]
    ancestors = submit.get('form_ancestors', [])
    if not candidates or not ancestors:
        return [], None
    candidates = [e for e in candidates if any(ancestor in e.get('form_ancestors', []) for ancestor in ancestors)]
    if not candidates:
        return [], None

    login_form = bool(LOGIN.search(submit_label))
    for ancestor in ancestors:
        scoped = [e for e in candidates if ancestor in e.get('form_ancestors', [])]
        if len(scoped) != len(candidates):
            continue
        if login_form and (not any(e.get('password') for e in scoped)
                           or not any(not e.get('password') for e in scoped)):
            continue
        return scoped, ancestor
    # A partial subtree must never become a complete form just because it contains one field.
    return [], None


def prepare_choices(session, screen: dict, form: dict) -> None:
    """Observe one safe visible alternative per Spinner, then replay it as a verified selection."""
    from .android_interact import family, reach, tap, usable
    from .android_runtime import device_unavailable

    choices = []
    if form.get('required_checkboxes'):
        form['choice_error'] = (
            'A required or consent checkbox needs an explicitly approved test flow; Qpilot will not accept it automatically.'
        )
        form['choices'] = choices
        return
    ungrouped_radios = [e for e in form.get('radios', []) if not e.get('choice_group')]
    if len(ungrouped_radios) > 1:
        form['choice_error'] = 'Multiple radio controls have no exposed native group; configure an approved flow.'
        form['choices'] = choices
        return
    if form.get('dropdowns'):
        session.spend()
        session.go_to(screen)
    try:
        for dropdown in form.get('dropdowns', []):
            current = dropdown.get('selected_text', '')
            session.perform(reach(dropdown) + [tap(dropdown)])
            opened = session.device.observe()
            options = [e for e in opened.get('elements', []) if usable(e)
                       and (e.get('class_name', '').endswith('CheckedTextView') or e.get('native_choice_option'))
                       and e.get('text') and not session.protected(e['text'])]
            options = [e for e in options if e['text'] != current] or options
            if not options:
                raise ValueError('No unique safe native dropdown option was observed')
            option = options[0]  # a representative observed option, never a guessed value
            session.perform([tap(option)])
            after = session.device.observe()
            live = next((e for e in after['elements'] if family(e) == family(dropdown)), None)
            if live is None or live.get('selected_text') != option['text']:
                raise AssertionError('The native dropdown did not retain its observed selection')
            choices.append({'action':'select','locator':dropdown['locators'][0],
                            'value':option['text'],'purpose':'test_form'})
        # Retain an existing radio selection, or select one observed option per native group.
        groups = {}
        for radio in form.get('radios', []):
            group = radio.get('choice_group') or f"ungrouped:{radio.get('id', id(radio))}"
            groups.setdefault(group, []).append(radio)
        for radios in groups.values():
            radio = next((e for e in radios if e.get('checked')), radios[0])
            choices += [tap(radio), {'action':'assert_checked','locator':radio['locators'][0],'value':'true'}]
    except Exception as error:
        if device_unavailable(error):
            raise
        form['choice_error'] = f'Native form choices could not be verified ({type(error).__name__}). Configure an approved flow.'
    form['choices'] = choices


def destination_check(session, before: dict, after: dict, form: dict) -> list[dict]:
    """A configured expectation wins; otherwise require an actual new screen anchor."""
    from .android_interact import anchor, anchor_checks, family, name, present, usable
    from .android_runtime import same_screen

    expected = session.device.config.get('expected_destinations') or {}
    words = ' '.join(name(form['submit']).split()).casefold()
    configured = next((value for key, value in expected.items() if ' '.join(key.split()).casefold() == words), None)
    if configured:
        form['configured_destination'] = True
        return [{'action':'assert_screen','value':configured}]
    def display_label(element):
        return element.get('text') or element.get('accessibility_id') or ''

    previous_texts = {display_label(e) for e in before.get('elements', []) if e.get('visible')}
    if any(outcome_error(display_label(e)) for e in after.get('elements', [])
           if e.get('visible') and display_label(e) not in previous_texts):
        return []
    if same_screen(before, after) or present(after, form['inputs'][0]):
        return []
    unchanged = {(family(e), e.get('text')) for e in after.get('elements', []) if usable(e)}
    common = {family(e) for e in before.get('elements', []) if usable(e) and (family(e), e.get('text')) in unchanged}
    mark = anchor(after, common)
    if mark is None or mark.get('clickable') or mark.get('checkable'):
        return []
    return anchor_checks(mark)


def select_native(adapter, element, value: str) -> None:
    """Select only a standard native Spinner's observed visible option and verify readback."""
    from .android import find_unique, inspect_driver
    from .qa_contracts import Locator

    adapter.guard()
    if not str(element.get_attribute('class') or '').endswith('Spinner'):
        raise ValueError('Native select requires a standard Spinner; custom controls need an approved tap flow')
    if protected(adapter.identity(element), adapter.test_mode, True) or protected(value, adapter.test_mode, True):
        raise ValueError('Blocked a protected native choice')
    resource = element.get_attribute('resource-id')
    if not resource:
        raise ValueError('Native Spinner selection requires a stable resource ID')
    locator = Locator(strategy='resource_id', value=resource)
    if not adapter.enabled(element):
        raise AssertionError('The native dropdown is disabled')
    element.click()
    adapter.guard()
    option = find_unique(adapter.driver, {'strategy':'text','value':value})
    checked = str(option.get_attribute('class') or '').endswith('CheckedTextView')
    text_option = False
    if not checked and option.get_attribute('resource-id') == 'android:id/text1':
        # UiAutomator2 may scope element XPath queries to descendants. Inspect
        # the guarded full hierarchy to prove list ancestry instead of guessing.
        screen = inspect_driver(adapter.driver, adapter.config)
        matches = [e for e in screen['elements'] if e.get('visible') and e.get('native_choice_option')
                   and e.get('text') == value and e.get('locator_unique')]
        text_option = len(matches) == 1
    if not checked and not text_option:
        raise ValueError('The requested value is not a visible native dropdown option')
    find_unique(adapter.driver, {'strategy':'text','value':value}).click()
    adapter.guard()
    selected = adapter.find(locator)
    # Spinner.text is empty on UiAutomator2; its selected TextView carries the label.
    children = selected.find_elements('class name', 'android.widget.TextView')
    texts = [child.text for child in children if child.is_displayed() and child.text]
    actual = selected.text or (texts[0] if len(texts) == 1 else '')
    if actual != value:
        raise AssertionError('Native dropdown selection was not retained')
