"""Bounded native viewport discovery and replay of actually observed offscreen controls."""
import hashlib
import json
import time

from selenium.common.exceptions import NoSuchElementException

from .android import AndroidEnvironmentError, capture_screenshot, find_unique, inspect_driver


def _key(element):
    if not element.get('locators') or not element.get('locator_unique'):
        return None
    return json.dumps(element['locators'][0], sort_keys=True)


def _guard(screen, current):
    from .android_runtime import same_screen

    if not same_screen(current, screen):
        raise AndroidEnvironmentError('Scrolling left the verified native screen; remaining controls were not touched')


def seek_observed(driver, screen, element, config, stop_path=None, limit=8):
    hint = element.get('scroll_hint')
    if not hint or not screen.get('identity'):
        raise NoSuchElementException('The observed control is absent and has no safe recorded scroll path')
    deadline = time.monotonic() + 45
    directions = [hint['direction'], {'down': 'up', 'up': 'down'}.get(hint['direction'], 'up')]
    total_attempts = 0
    for direction in directions:
        for _ in range(limit + 1):
            if stop_path and stop_path.exists():
                raise AndroidEnvironmentError('The Android run was stopped by the user')
            _guard(screen, inspect_driver(driver, config))
            for locator in element['locators']:
                try:
                    return find_unique(driver, locator), locator, total_attempts
                except NoSuchElementException:
                    pass
            if total_attempts >= limit * len(directions) or time.monotonic() >= deadline:
                break
            container = find_unique(driver, hint['container'])
            more = driver.execute_script('mobile: scrollGesture', {
                'elementId': container.id, 'direction': direction, 'percent': .7,
            })
            total_attempts += 1
            time.sleep(.2)
            if more is False:
                # Check the final viewport before reversing the scan direction.
                _guard(screen, inspect_driver(driver, config))
                for locator in element['locators']:
                    try:
                        return find_unique(driver, locator), locator, total_attempts
                    except NoSuchElementException:
                        pass
                break
    raise NoSuchElementException('The observed offscreen control was not reached within bounded scroll gestures in either direction')


def discover_viewports(driver, screen, config, budget, deadline, run_dir):
    """Merge only controls actually rendered while scrolling, then restore the top."""
    if config.get('app_mode') == 'web' or config.get('contract_only') or screen.get('identity', [])[:1] == ['embedded_webview']:
        return []
    containers = [e for e in screen['elements'] if e.get('visible') and e.get('scrollable')
                  and e.get('locator_unique') and not e.get('within_webview')
                  and e.get('class_name', '').endswith(('ScrollView', 'RecyclerView'))
                  and 'Horizontal' not in e.get('class_name', '')]
    if not containers:
        return []
    if not screen.get('identity'):
        return [{'reason': 'Offscreen discovery needs a stable native screen identity and scroll container'}]
    maximum = min(config.get('max_scroll_actions', 12),
                  budget.get('scroll', 0) + config.get('max_scrolls_per_screen', 2))
    if maximum <= budget.get('scroll', 0):
        return [{'reason': 'Automatic discovery scrolling is disabled'}]
    gaps = []
    stop_path = run_dir / 'STOP'
    seen = {_key(e) for e in screen['elements'] if e.get('visible')}
    seen.discard(None)
    screen.setdefault('viewports', [])
    for container in containers:
        if budget.get('scroll', 0) >= maximum:
            gaps.append({'label': container.get('accessibility_id') or container.get('resource_id'),
                         'reason': 'Discovery scroll limit reached'})
            break
        locator = container['locators'][0]
        steps = 0
        previous = inspect_driver(driver, config)['fingerprint']
        try:
            while budget.get('scroll', 0) < maximum and time.monotonic() < deadline:
                if stop_path.exists():
                    raise AndroidEnvironmentError('Stop requested during viewport discovery')
                live = find_unique(driver, locator)
                more = driver.execute_script('mobile: scrollGesture', {
                    'elementId': live.id, 'direction': 'down', 'percent': .7,
                })
                budget['scroll'] = budget.get('scroll', 0) + 1
                steps += 1
                time.sleep(.2)
                current = inspect_driver(driver, config)
                _guard(screen, current)
                if current['fingerprint'] == previous:
                    if more is True:
                        gaps.append({'label': container.get('accessibility_id') or 'scrollable region',
                                     'reason': 'The scroll control did not expose another observable viewport'})
                    break
                previous = current['fingerprint']
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
                                'scroll_hint': {'container': locator, 'direction': 'down'}}
                    if len(candidates) == 1:
                        identifier = candidates[0].get('id')
                        candidates[0].update(observed)
                        if identifier:
                            candidates[0]['id'] = identifier
                    else:
                        screen['elements'].append(observed)
                    added += 1
                fingerprint = hashlib.sha256(current['fingerprint'].encode()).hexdigest()[:12]
                image = capture_screenshot(driver, run_dir, screen['id'] + '-viewport-' + str(len(screen['viewports'])), config['package_name'])
                screen['viewports'].append({'fingerprint': fingerprint, 'container': locator,
                                           'new_controls': added, 'screenshot': image})
                if more is False:
                    break
            else:
                gaps.append({'label': container.get('accessibility_id') or 'scrollable region',
                             'reason': 'Discovery scroll or time limit reached'})
        finally:
            # At most the same number of reverse gestures plus one boundary check.
            # Respect Stop/time limits instead of continuing gestures after cancellation.
            for _ in range(steps + 1):
                if not steps or stop_path.exists() or time.monotonic() >= deadline:
                    break
                _guard(screen, inspect_driver(driver, config))
                live = find_unique(driver, locator)
                more = driver.execute_script('mobile: scrollGesture', {
                    'elementId': live.id, 'direction': 'up', 'percent': .7,
                })
                budget['scroll_recovery'] = budget.get('scroll_recovery', 0) + 1
                _guard(screen, inspect_driver(driver, config))
                if more is False:
                    break
    return gaps
