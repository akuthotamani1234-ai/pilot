"""Explicit emulator permission tests, scoped to one app and restored after each flow."""
import re
import time

from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

from .android import AndroidEnvironmentError, find_unique
from .qa_contracts import IRREVERSIBLE

CONTROLLERS = {'com.android.permissioncontroller', 'com.google.android.permissioncontroller'}
GROUP_TEXT = {
    'CAMERA': r'camera|take pictures',
    'RECORD_AUDIO': r'microphone|record audio',
    'ACCESS_FINE_LOCATION': r'location',
    'ACCESS_COARSE_LOCATION': r'location',
    'POST_NOTIFICATIONS': r'notifications',
    'READ_MEDIA_IMAGES': r'access.*photos|select.*photos',
    'READ_MEDIA_VIDEO': r'access.*videos|select.*videos',
    'READ_MEDIA_VISUAL_USER_SELECTED': r'access.*photos|select.*photos',
    'READ_EXTERNAL_STORAGE': r'photos|media|files',
    'READ_MEDIA_AUDIO': r'music|audio files|access.*audio',
}


class PermissionSession:
    def __init__(self, driver, config, policy, relaunch, stop_path=None):
        self.driver, self.config, self.policy, self.relaunch = driver, config, policy, relaunch
        self.package = config.get('package_name')
        self.original = None
        self.pending = None
        self.stop_path = stop_path

    def check_stop(self):
        if self.stop_path and self.stop_path.exists():
            raise InterruptedError('The Android permission test was stopped by the user')

    def require(self, permission):
        self.check_stop()
        if (not self.policy or not self.policy.approved or permission not in self.policy.allowed
                or not re.fullmatch(r'emulator-\d+', self.config.get('device_id', ''))
                or self.config.get('app_mode') == 'web' or self.driver.current_context != 'NATIVE_APP'):
            raise ValueError('Permission tests require an explicitly approved native emulator policy')

    def permissions(self, kind):
        result = self.driver.execute_script('mobile: getPermissions', {'appPackage': self.package, 'type': kind})
        if not isinstance(result, list) or not all(isinstance(p, str) for p in result):
            raise AndroidEnvironmentError('Appium did not return a valid Android permission list')
        return set(result)

    def capture(self, permission):
        self.require(permission)
        if permission not in self.permissions('requested'):
            raise ValueError('The selected app does not declare the configured permission')
        if self.original is None:
            self.original = self.permissions('granted')

    def change(self, permission, granted):
        if not re.fullmatch(r'android\.permission\.[A-Z_]+', permission):
            raise ValueError('Only a named Android runtime permission can be restored')
        self.driver.execute_script('mobile: changePermissions', {
            'appPackage': self.package, 'permissions': [permission], 'target': 'pm',
            'action': 'grant' if granted else 'revoke',
        })

    def set_state(self, permission, value):
        self.capture(permission)
        desired = value == 'granted'
        if (permission in self.permissions('granted')) != desired:
            self.change(permission, desired)
            self.relaunch()  # Revocation can kill the app; refresh its displayed state.
        if (permission in self.permissions('granted')) != desired:
            raise AssertionError('The configured Android permission state was not applied')

    def request(self, element, permission, identity, permissions=None):
        requested = set(permissions or [permission])
        for name in sorted(requested):
            self.capture(name)
        if self.driver.current_package != self.package:
            raise ValueError('Permission requests must start inside the selected application')
        words = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', identity).replace('_', ' ').replace('-', ' ')
        if {m.group().casefold() for m in IRREVERSIBLE.finditer(words)} - {'permission'}:
            raise ValueError('A permission request cannot invoke an irreversible action')
        if not re.search(r'permission|camera|microphone|location|photo|notification|media', words, re.I):
            raise ValueError('The live request control does not identify a permission feature')
        if requested & self.permissions('granted'):
            raise ValueError('Set every requested permission to denied before testing its request prompt')
        if not element.is_enabled():
            raise AssertionError('The permission request control is disabled')
        started = time.monotonic()
        self.pending = {'permission': permission, 'permissions': requested, 'started': started,
                        'deadline': started + min(60, 25 * len(requested))}
        element.click()

    def allows_foreground(self, package):
        return bool(self.pending and package in CONTROLLERS and time.monotonic() <= self.pending['deadline'])

    def before_step(self, action):
        if self.pending and action != 'handle_permission':
            raise ValueError('Handle the pending permission prompt before any other test step')

    def prompt_element(self, controller, names, deadline, namespace=None):
        # Google's controller uses com.android.permissioncontroller resource IDs
        # on stock API 36. Package ownership and resource namespace are distinct.
        namespaces = [namespace] if namespace else [controller, *sorted(CONTROLLERS - {controller})]
        while time.monotonic() < deadline:
            self.check_stop()
            if self.driver.current_package != controller:
                raise AndroidEnvironmentError('The approved permission controller is no longer in the foreground')
            for prefix in namespaces:
                for name in names:
                    try:
                        element = find_unique(self.driver, {'strategy': 'resource_id', 'value': prefix + ':id/' + name})
                        if element.get_attribute('package') != controller:
                            raise ValueError('The permission control does not belong to the active system controller')
                        return element, prefix
                    except (NoSuchElementException, StaleElementReferenceException):
                        continue
            time.sleep(.2)
        raise AndroidEnvironmentError('The approved Android permission control did not become visible')

    def handle(self, permission, choice):
        self.require(permission)
        if not self.pending or self.pending['permission'] != permission:
            raise ValueError('No matching permission request was initiated by this flow')
        requested = self.pending['permissions']
        if len(requested) > 1 and choice not in {'allow', 'deny'}:
            raise ValueError('Batch requests require allow or deny for every declared permission group')
        deadline = self.pending['deadline']
        buttons = {
            'allow_once': ['permission_allow_one_time_button'],
            'allow_while_using': ['permission_allow_foreground_only_button'],
            'allow': ['permission_allow_button', 'permission_allow_foreground_only_button', 'permission_allow_all_button'],
            'deny': ['permission_deny_button'],
        }
        handled = set()
        responses = []
        while time.monotonic() < deadline:
            self.check_stop()
            controller = self.driver.current_package
            if controller == self.package:
                if handled:
                    break
                time.sleep(.2)
                continue
            if controller not in CONTROLLERS:
                raise AndroidEnvironmentError('The permission request left the approved app/system controller')
            message_element, namespace = self.prompt_element(controller, ['permission_message'], deadline)
            normalized = ' '.join(message_element.text.casefold().split())
            matched = {p for p in requested if re.search(GROUP_TEXT[p.rsplit('.', 1)[-1]], normalized)}
            if ' '.join(self.policy.app_label.casefold().split()) not in normalized or not matched:
                raise ValueError('The permission prompt does not match the selected app and requested permission group')
            if matched <= handled:
                time.sleep(.2)  # Wait for an animated dismissal or the next declared prompt.
                continue
            selected, _ = self.prompt_element(controller, buttons[choice], deadline, namespace)
            selected.click()
            handled.update(matched)
            responses.append(sorted(matched))
            time.sleep(.2)
        else:
            raise AndroidEnvironmentError('Android did not finish the approved permission prompts within the bounded wait')
        self.pending = None
        granted = self.permissions('granted')
        if granted - self.original - set(self.policy.allowed):
            raise ValueError('Android changed a permission outside the approved list; restoring the original state')
        assert all((p in granted) == (choice != 'deny') for p in requested), 'The permission response did not produce the expected OS state'
        return {'permission': permission, 'response': choice, 'state': 'granted' if permission in granted else 'denied',
                'prompt_groups': responses, 'requested_permissions': sorted(requested)}

    def assert_state(self, permission, expected):
        self.require(permission)
        assert (permission in self.permissions('granted')) == (expected == 'granted'), 'Unexpected Android permission state'

    def restore(self):
        if self.original is None:
            return []
        if self.pending:
            self.driver.terminate_app(self.package)  # Close only the owner of a pending prompt.
            self.pending = None
        changed = self.permissions('granted') ^ self.original
        for permission in sorted(changed):
            self.change(permission, permission in self.original)
        if (self.permissions('granted') ^ self.original) & changed:
            raise AndroidEnvironmentError('The original Android permissions could not be restored')
        self.original = None
        return sorted(changed)
