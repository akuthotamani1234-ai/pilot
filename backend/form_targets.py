"""Container-scoped interaction helpers, also embedded in generated tests."""
import inspect


def unique_control(scope, field):
    """An unresolved target is an automation error, never a choice of the first match."""
    name = field.get("label") or field.get("name") or ""
    if name:
        labelled = scope.get_by_label(name, exact=True)
        if labelled.count() == 1:
            if labelled.evaluate("e => !!e.closest('nav,aside,[role=navigation],[role=search]')"):
                raise AssertionError("Automation form target resolved inside global navigation/search")
            return labelled
        if labelled.count() > 1:
            raise AssertionError(f"Automation target ambiguous within its container: {name!r}")
    selector = field.get("local_selector") or field.get("selector")
    if not selector:
        raise AssertionError(f"Automation target has no observed selector: {name!r}")
    target = scope.locator(selector)
    if name and target.count() > 1:
        matches = []
        for candidate in target.all():
            label = candidate.evaluate("""e => {
              if (e.labels?.length) return e.labels[0].innerText.trim();
              let n = e;
              for (let k=0; k<3 && n; k++, n=n.parentElement) {
                const labels = n.querySelectorAll('label');
                if (labels.length === 1) return labels[0].innerText.trim();
              }
              return e.getAttribute('aria-label') || e.getAttribute('placeholder') || '';
            }""")
            if label.strip().rstrip("* :").casefold() == name.strip().rstrip("* :").casefold():
                matches.append(candidate)
        if len(matches) == 1:
            return matches[0]
    if target.count() != 1:
        raise AssertionError(f"Automation target must resolve once within its container: {name or selector!r}; "
                             f"found {target.count()}")
    if target.evaluate("e => !!e.closest('nav,aside,[role=navigation],[role=search]')"):
        raise AssertionError("Automation form target resolved inside global navigation/search")
    return target


def form_scope(page, selector):
    scope = page.locator(selector) if selector else page.locator('form,[role=form],[role=dialog]')
    if scope.count() != 1:
        raise AssertionError(f"Automation form container must resolve once; found {scope.count()}")
    return scope


def set_user_checked(el, value, scope=None):
    """Use the associated label for custom checkboxes; never force clicks or mutate checked."""
    import json

    from playwright.sync_api import expect

    expect(el, "Automation target must be unique before changing its checked state").to_have_count(1)
    if scope is None:
        ancestor = el.locator("xpath=ancestor::*[self::form or @role='dialog'][1]")
        scope = ancestor if ancestor.count() == 1 else el.page
    try:
        if value:
            el.check(timeout=2500)
        else:
            el.uncheck(timeout=2500)
    except Exception:
        label_id = el.get_attribute("id")
        labels = scope.locator('label[for=' + json.dumps(label_id) + ']') if label_id else el.locator('xpath=ancestor::label')
        if labels.count() != 1 or el.is_checked() == value:
            raise
        labels.click(timeout=2500)
    expect(el).to_be_checked(checked=value)


def check_user_control(scope, field, value):
    set_user_checked(unique_control(scope, field), value, scope)


def fill_input_check(page, spec):
    """Check all recorded fields without submitting; no business-verification claim."""
    import json

    from playwright.sync_api import expect

    scope = form_scope(page, spec.get("form"))
    expect(scope).to_be_visible()
    verified = []
    for field in spec["fields"]:
        if field.get("conditional_reason") and not field.get("required"):
            print('[qa-note] Optional field omitted: ' + field["conditional_reason"])
            continue
        el = unique_control(scope, field)
        kind, value = field["kind"], field.get("value", "")
        if kind == "unsupported":
            raise AssertionError("Automation cannot supply a grounded value/control interaction for " + field["name"])
        if kind in {"checkbox", "radio"}:
            check_user_control(scope, field, True)
        elif kind == "select":
            el.select_option(value, timeout=5000)
            expect(unique_control(scope, field)).to_have_value(value)
        elif kind == "combobox":
            el.click(timeout=5000)
            option = page.get_by_role("option", name=field["shown"], exact=True)
            expect(option).to_have_count(1)
            option.click(timeout=5000)
            expect(unique_control(scope, field)).to_contain_text(field["shown"])
        else:
            expect(el).to_be_visible()
            expect(el).to_be_editable()
            el.fill(value, timeout=5000)
            el.press("Tab")
            expect(unique_control(scope, field)).to_have_value(value)
        el = unique_control(scope, field)
        assert el.evaluate("e => !e.checkValidity || e.checkValidity()"), field["name"] + " rejects the intended value"
        assert el.get_attribute("aria-invalid") != "true", field["name"] + " has application validation errors"
        verified.append(field["name"])
        print('[qa-step] Input retained: ' + field["name"])
    assert len(verified) == len([f for f in spec["fields"] if not (f.get("conditional_reason") and not f.get("required"))])
    print('[qa-note] Input interaction only; form not submitted and persistence not verified')
    print('[qa-fields] ' + json.dumps({"intended": len(spec["fields"]), "verified": verified}))


FORM_TARGET_HELPER = "\n\n".join(inspect.getsource(f) for f in (
    unique_control, form_scope, set_user_checked, check_user_control, fill_input_check))
