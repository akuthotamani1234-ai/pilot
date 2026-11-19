"""Bounded native viewport discovery and replay of actually observed offscreen controls."""
import hashlib
import json
import re
import time

from selenium.common.exceptions import NoSuchElementException

from .android import AndroidEnvironmentError, capture_screenshot, find_unique, inspect_driver

# A zero user limit means explore until exhausted. These hard ceilings protect
# long feeds while still allowing a full 100-gesture scan on a single screen.
HARD_SCROLL_ACTIONS = 100
HARD_SCROLLS_PER_SCREEN = 100
_REQUEST_ID = re.compile(r"(?i)(request[_\s-]?id\s*[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9._-]+")
_UUID = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_LOADING_REQUEST_ID = re.compile(
    r"(?i)(\bloading\s+)(?=[A-Za-z0-9._-]{5,}\b)(?=[A-Za-z0-9._-]*[-_][A-Za-z0-9._-]*\d)[A-Za-z0-9][A-Za-z0-9._-]*"
)


def _bounds(value):
    match = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", value or "")
    return tuple(map(int, match.groups())) if match else None


def _key(element):
    if not element.get('locators') or not element.get('locator_unique'):
        return None
    return json.dumps(element['locators'][0], sort_keys=True)


def _stable_view_label(value):
    """Remove request-specific identifiers so backend noise cannot fake scroll movement."""
    label = str(value or '')
    label = _REQUEST_ID.sub(r'\1<request-id>', label)
    label = _LOADING_REQUEST_ID.sub(r'\1<id>', label)
    return _UUID.sub('<id>', label)


def _stable_route(screen):
    if screen.get('identity'):
        return True
    anchors = {e.get('resource_id') or e.get('accessibility_id') for e in screen.get('elements', [])
               if e.get('visible') and e.get('navigation_role') not in ('tab', 'menu_item')}
    return len({a for a in anchors if a and not a.casefold().startswith('android:')}) >= 2


def _viewport_signature(screen, container):
    """Compare rendered controls inside a scroll viewport, including their relative positions."""
    region = _bounds(container.get('bounds'))
    if not region:
        locators = container.get('locators') or []
        unique_locator = locators[0] if container.get('locator_unique') and locators else None
        container_labels = {container.get('accessibility_id'), container.get('resource_id'),
                            container.get('class_name')} - {None, ''}
        return tuple(sorted((element.get('class_name', ''), element.get('resource_id', ''),
                             _stable_view_label(element.get('accessibility_id', '')),
                             _stable_view_label(element.get('text', '')), element.get('bounds', ''))
                            for element in screen.get('elements', []) if element.get('visible')
                            and element.get('id') != container.get('id')
                            and (element.get('scroll_container_locator') == unique_locator if unique_locator else
                                 element.get('in_scroller') in container_labels)))
    left, top, right, bottom = region
    rows = []
    for element in screen.get('elements', []):
        if element.get('id') == container.get('id') or not element.get('visible'):
            continue
        rect = _bounds(element.get('bounds'))
        if not rect:
            continue
        x1, y1, x2, y2 = rect
        if x2 <= left or x1 >= right or y2 <= top or y1 >= bottom:
            continue
        rows.append((element.get('class_name', ''), element.get('resource_id', ''),
                     _stable_view_label(element.get('accessibility_id', '')),
                     _stable_view_label(element.get('text', '')),
                     max(x1, left) - left, max(y1, top) - top,
                     min(x2, right) - left, min(y2, bottom) - top))
    return tuple(sorted(rows))


def _target(container):
    if container.get('locator_unique') and container.get('locators'):
        return {'container': container['locators'][0]}
    return {'bounds': container.get('bounds')} if _bounds(container.get('bounds')) else None


def _scroll(driver, target, direction):
    args = {'direction': direction, 'percent': .7}
    if target.get('container'):
        args['elementId'] = find_unique(driver, target['container']).id
    else:
        rect = _bounds(target.get('bounds'))
        if not rect:
            raise AndroidEnvironmentError('The observed scrollable control has no safe locator or bounds.')
        left, top, right, bottom = rect
        if right <= left or bottom <= top:
            raise AndroidEnvironmentError('The observed scrollable control has invalid bounds.')
        args.update(left=left, top=top, width=right - left, height=bottom - top)
    return driver.execute_script('mobile: scrollGesture', args)


def _axis(container):
    axis = container.get('scroll_axis')
    if axis in ('horizontal', 'vertical'):
        return axis
    class_name = container.get('class_name', '')
    if 'Horizontal' in class_name or 'ViewPager' in class_name:
        return 'horizontal'
    if 'Vertical' in class_name or class_name.endswith('ScrollView'):
        return 'vertical'
    return ''


def _guard(screen, current):
    from .android_runtime import same_screen

    if not same_screen(current, screen):
        raise AndroidEnvironmentError('Scrolling left the verified native screen; remaining controls were not touched')


def _user_stopped(stop_path):
    """True when the user wrote a real stop file. A link is refused."""
    if not stop_path:
        return False
    from .android_runtime import stop_file_note
    note = stop_file_note(stop_path)
    if "link" in note:
        raise AndroidEnvironmentError(note)
    return bool(note)


def seek_observed(driver, screen, element, config, stop_path=None, limit=8):
    hint = element.get('scroll_hint')
    if not hint or not _stable_route(screen):
        raise NoSuchElementException('The observed control is absent and has no safe recorded scroll path')
    deadline = time.monotonic() + 45
    reverse = {'down': 'up', 'up': 'down', 'right': 'left', 'left': 'right'}.get(hint['direction'], 'up')
    directions = [hint['direction'], reverse]
    total_attempts = 0
    for direction in directions:
        for _ in range(limit + 1):
            if _user_stopped(stop_path):
                raise AndroidEnvironmentError('The Android run was stopped by the user')
            _guard(screen, inspect_driver(driver, config))
            for locator in element['locators']:
                try:
                    return find_unique(driver, locator), locator, total_attempts
                except NoSuchElementException:
                    pass
            if total_attempts >= limit * len(directions) or time.monotonic() >= deadline:
                break
            more = _scroll(driver, hint, direction)
            total_attempts += 1
            time.sleep(.2)
            if more is False:
                _guard(screen, inspect_driver(driver, config))
                for locator in element['locators']:
                    try:
                        return find_unique(driver, locator), locator, total_attempts
                    except NoSuchElementException:
                        pass
                break
    raise NoSuchElementException('The observed offscreen control was not reached within bounded scroll gestures in either direction')


def discover_viewports(driver, screen, config, budget, deadline, run_dir):
    """Explore rendered scroll containers with reversible, observable, bounded gestures."""
    from pathlib import Path
    _user_stopped(Path(run_dir) / "STOP")
    if config.get('app_mode') == 'web' or config.get('contract_only') or screen.get('identity', [])[:1] == ['embedded_webview']:
        return []
    scrollables = [e for e in screen['elements'] if e.get('visible') and e.get('scrollable')
                   and not e.get('within_webview')]
    def label_of(element):
        return (element.get('accessibility_id') or element.get('resource_id') or
                element.get('class_name') or 'scrollable region')

    unaddressable = [{'label': label_of(element),
                      'reason': 'Scrollable container has no unique locator or readable bounds; offscreen content was not explored'}
                     for element in scrollables if not _target(element)]
    containers = [element for element in scrollables if _target(element)]
    if not containers:
        return unaddressable
    if not _stable_route(screen):
        return [*unaddressable, {'reason': 'Offscreen discovery needs a stable native screen identity and scroll container'}]

    max_total = config.get('max_scroll_actions') or HARD_SCROLL_ACTIONS
    max_per_screen = config.get('max_scrolls_per_screen') or HARD_SCROLLS_PER_SCREEN
    maximum = min(max_total, budget.get('scroll', 0) + max_per_screen)
    if maximum <= budget.get('scroll', 0):
        return [{'reason': 'The global discovery scroll limit was already reached'}]

    gaps, seen = list(unaddressable), {_key(e) for e in screen['elements'] if e.get('visible')}
    seen.discard(None)
    stop_path = run_dir / 'STOP'
    screen.setdefault('viewports', [])

    def add_gap(label, reason):
        row = {'label': label, 'reason': reason}
        if row not in gaps:
            gaps.append(row)

    def collect(current, container, target, direction, axis):
        added = 0
        for element in current['elements']:
            key = _key(element)
            if (not key or key in seen or not element.get('visible') or element.get('within_webview')
                    or not (element.get('accessibility_id') or element.get('resource_id') or element.get('input_capable')
                            or any(c.isalnum() for c in element.get('text', '')))):
                continue
            seen.add(key)
            candidates = [e for e in screen['elements'] if not e.get('visible')
                          and e.get('class_name') == element.get('class_name')
                          and (e.get('accessibility_id') and e['accessibility_id'] == element.get('accessibility_id')
                               or e.get('resource_id') and e['resource_id'] == element.get('resource_id')
                               and e.get('text') == element.get('text'))]
            observed = {**element, 'requires_scroll': True,
                        'scroll_hint': {**target, 'direction': direction, 'axis': axis}}
            if len(candidates) == 1:
                identifier = candidates[0].get('id')
                candidates[0].update(observed)
                if identifier:
                    candidates[0]['id'] = identifier
            else:
                screen['elements'].append(observed)
            added += 1
        fingerprint = hashlib.sha256(current['fingerprint'].encode()).hexdigest()[:12]
        image = capture_screenshot(driver, run_dir, screen['id'] + '-viewport-' + str(len(screen['viewports'])),
                                   config['package_name'])
        screen['viewports'].append({'fingerprint': fingerprint,
                                   'container': target.get('container') or {'bounds': target.get('bounds')},
                                   'new_controls': added, 'screenshot': image})

    for container in containers:
        label = label_of(container)
        target = _target(container)
        axis = _axis(container)
        axes = [axis] if axis else ['vertical', 'horizontal']
        moved_any = False
        abort_screen = False

        for candidate_axis in axes:
            candidate_moved = False
            axis_inconclusive = False
            directions = [('down', 'up'), ('up', 'down')] if candidate_axis == 'vertical' else [
                ('right', 'left'), ('left', 'right')
            ]
            for forward, reverse in directions:
                if budget.get('scroll', 0) >= maximum or time.monotonic() >= deadline or _user_stopped(stop_path):
                    reason = ('Stop requested during viewport discovery' if _user_stopped(stop_path) else
                              'Discovery time limit reached; more content may remain' if time.monotonic() >= deadline else
                              'The per-screen or global discovery scroll limit was reached; more content may remain')
                    add_gap(label, reason)
                    abort_screen = True
                    break

                start_screen = inspect_driver(driver, config)
                _guard(screen, start_screen)
                start_signature = _viewport_signature(start_screen, container)
                current_signature = start_signature
                steps, inconclusive = 0, False

                while time.monotonic() < deadline:
                    if _user_stopped(stop_path):
                        add_gap(label, 'Stop requested during viewport discovery')
                        abort_screen = True
                        break
                    # Reserve one reverse gesture for every possible forward movement so a
                    # hard budget never strands the app away from its starting viewport.
                    restore_reserve = steps + 1
                    if budget.get('scroll', 0) + 1 + restore_reserve > maximum:
                        add_gap(label, 'The per-screen or global discovery scroll limit was reached; more content may remain')
                        abort_screen = True
                        break
                    before_signature = current_signature
                    more = _scroll(driver, target, forward)
                    budget['scroll'] = budget.get('scroll', 0) + 1
                    time.sleep(.2)
                    current = inspect_driver(driver, config)
                    _guard(screen, current)
                    current_signature = _viewport_signature(current, container)
                    changed = current_signature != before_signature
                    if changed:
                        steps += 1
                        moved_any = True
                        candidate_moved = True
                        collect(current, container, target, forward, candidate_axis)
                    if more is False:
                        break
                    if not changed:
                        inconclusive = True
                        break
                if budget.get('scroll', 0) >= maximum and current_signature != start_signature:
                    add_gap(label, 'The per-screen or global discovery scroll limit was reached; more content may remain')
                elif time.monotonic() >= deadline:
                    add_gap(label, 'Discovery time limit reached; more content may remain')

                # Restore the exact starting viewport before trying another direction or container.
                attempts = 0
                while current_signature != start_signature and attempts < max(2, steps + 2):
                    if _user_stopped(stop_path) or time.monotonic() >= deadline or budget.get('scroll', 0) >= maximum:
                        break
                    before_signature = current_signature
                    more = _scroll(driver, target, reverse)
                    budget['scroll'] = budget.get('scroll', 0) + 1
                    budget['scroll_recovery'] = budget.get('scroll_recovery', 0) + 1
                    attempts += 1
                    time.sleep(.2)
                    restored_screen = inspect_driver(driver, config)
                    _guard(screen, restored_screen)
                    current_signature = _viewport_signature(restored_screen, container)
                    if current_signature == before_signature and more is False:
                        break
                if current_signature != start_signature:
                    add_gap(label, 'Could not verify restoration to the starting viewport; remaining controls were not explored')
                    abort_screen = True
                    break
                if inconclusive:
                    axis_inconclusive = True
                if abort_screen:
                    break
            if axis_inconclusive and not candidate_moved:
                add_gap(label, f'{candidate_axis.title()} scroll reported more content, but no readable viewport change was observed')
            if abort_screen:
                break
        if abort_screen:
            break
        if not moved_any and not axis:
            add_gap(label, 'Scrollable container orientation/content could not be confirmed by bounded vertical or horizontal probes')
    return gaps
