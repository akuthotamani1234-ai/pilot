"""A local account survives one signup, login replays, and protected feature checks."""

import json
import time
from types import SimpleNamespace

import pytest

from backend.android import AndroidEnvironmentError, extract_screen, validate_mobile_config
from backend.android_accounts import prepare_account, reset_for_check, validate_credentials
from backend.android_app import AppSession
from backend.android_design import normalize_screens
from backend.android_interact import ACCOUNT_USERNAME, TEST_PASSWORD, TEST_USERNAME, find_form, flow_secrets
from tests.test_android_real_tester import PACKAGE, FakeApp, FakeDriver
from tests.test_android_site import VirtualClock


class AccountApp(FakeApp):
    def __init__(self):
        self.accounts, self.registrations, self.logins = {}, [], []
        self.view = "login"
        super().__init__("login")

    def reset(self):
        super().reset()
        self.view, self.profile = "login", False

    def nodes(self):
        if self.logged_in:
            return [{"key": "welcome", "text": "Dashboard", "cls": "TextView"},
                    {"key": "profile", "text": "Show profile", "click": True},
                    *([{"key": "profile_result", "text": "Profile details", "cls": "TextView"}] if self.profile else [])]
        if self.view == "signup":
            return [{"key": "heading", "text": "Create an account", "cls": "TextView"},
                    {"key": "email", "input": True, "hint": "Email"},
                    {"key": "password", "input": True, "password": True, "hint": "Password"},
                    {"key": "register", "text": "Register", "click": True}]
        rows = super().nodes()
        rows.append({"key": "signup_link", "text": "New user? Register now", "click": True, "cls": "TextView"})
        return rows

    def click(self, key):
        if key == "register":
            username, password = self.fields.get("email", ""), self.fields.get("password", "")
            self.registrations.append((username, password))
            if not username or not password or username in self.accounts:
                self.error = "Invalid registration"
            else:
                self.accounts[username] = password
                self.view, self.error = "login", "Registration successful"
        elif key == "signup_link":
            self.view, self.error, self.fields = "signup", "", {}
        elif key == "login":
            user, password = self.fields.get("username", ""), self.fields.get("password", "")
            if not user or not password:
                self.error = "Username and password are required"
            elif self.accounts.get(user) == password:
                self.logins.append(user)
                self.logged_in, self.error = True, ""
            else:
                self.error = "Wrong username or password"
        elif key == "profile":
            self.profile = True


class AccountDriver(FakeDriver):
    def terminate_app(self, _package):
        pass

    def activate_app(self, _package):
        self.app.reset()

    def execute_script(self, name, args=None):
        if name == "mobile: clearApp" or name == "mobile: shell" and (args or {}).get("command") == "pm":
            self.app.accounts.clear()
        return super().execute_script(name, args)


def account_session(root, mode="create", app=None):
    app = app or AccountApp()
    driver = AccountDriver(app)
    def observe():
        return normalize_screens([extract_screen(app.xml(), PACKAGE, "emulator-5554", ".Main")])[0]
    login = observe()
    app.view = "signup"
    signup = observe()
    app.reset()
    config = {"account_mode": mode, "app_mode": "installed", "package_name": PACKAGE, "interaction_testing": True}
    def fresh():
        reset_for_check(driver, config, PACKAGE)
        return observe()
    def go_to(screen):
        fresh()
        if screen["id"] == signup["id"]:
            app.view = "signup"
        return observe()
    device = SimpleNamespace(driver=driver, config=config, screens=[login, signup], stop_path=root / "STOP",
                             max_tries=200, deadline=time.monotonic() + 3600, fresh_start=fresh,
                             go_to=go_to, observe=observe)
    return AppSession(device, environment={}), app, login, signup


def test_create_once_then_login_and_replay_protected_feature_with_same_account(tmp_path):
    with VirtualClock():
        session, app, login, _ = account_session(tmp_path)
        prepare_account(session)
        assert len(app.registrations) == 1
        assert session.has_account, session.tried
        user = session.secrets[ACCOUNT_USERNAME]
        prepare_account(session)
        session.form_checks(login, find_form(login))
        assert session.account_setup["authentication_verified"], session.tried
        assert app.logins and set(app.logins) == {user}
        assert len(app.registrations) == 1
        # The final execution process reloads the same private references, rather than generating another identity.
        saved = json.loads((tmp_path / ".private" / "auto_secrets.json").read_text(encoding="utf-8"))
        assert flow_secrets({}, saved)[ACCOUNT_USERNAME] == user
        login_flow = next(item["flow"] for item in session.flows if item["flow"].get("authentication"))
        assert session.replay(login_flow) == ""
        profile_flow = session.build("feature", "Protected profile opens after login", [
            *login_flow["steps"],
            {"action": "tap", "locator": {"strategy": "resource_id", "value": PACKAGE + ":id/profile"}, "purpose": "navigation"},
            {"action": "assert_text", "locator": {"strategy": "resource_id", "value": PACKAGE + ":id/profile_result"}, "value": "Profile details"},
        ])
        assert session.replay(profile_flow) == ""
        assert session.replay(profile_flow) == ""
        assert app.profile and set(app.logins) == {user}
        assert app.accounts[user] == app.registrations[0][1]
        assert len(app.registrations) == 1
        public = (tmp_path / "account_setup.json").read_text(encoding="utf-8")
        assert user not in public and app.registrations[0][1] not in public


def test_new_run_gets_new_identity_but_resuming_same_run_never_registers_again(tmp_path):
    with VirtualClock():
        session, app, _, _ = account_session(tmp_path / "first")
        prepare_account(session)
        resumed, _, _, _ = account_session(tmp_path / "first", app=app)
        prepare_account(resumed)
        assert len(app.registrations) == 1
        other, other_app, _, _ = account_session(tmp_path / "second")
        prepare_account(other)
        assert other_app.registrations[0][0] != app.registrations[0][0]


def test_supplied_account_logs_in_without_registering_or_erasing_local_users(tmp_path):
    with VirtualClock():
        app = AccountApp()
        app.accounts["existing-fixture@example.com"] = "existing-fixture-password"
        previous, _, login, _ = account_session(tmp_path, "existing", app)
        session = AppSession(previous.device, environment={TEST_USERNAME: "existing-fixture@example.com",
                                                          TEST_PASSWORD: "existing-fixture-password"})
        prepare_account(session)
        session.form_checks(login, find_form(login))
        assert session.account_setup["authentication_verified"], session.tried
        assert set(app.logins) == {"existing-fixture@example.com"}
        assert len(app.accounts) == 1 and not app.registrations


@pytest.mark.parametrize("mode", ["none", "existing"])
def test_other_account_choices_never_register(mode, tmp_path):
    session, app, _, signup = account_session(tmp_path, mode)
    session.form_checks(signup, find_form(signup))
    assert not app.registrations
    assert session.coverage[-1]["status"] == "not tested"


def test_existing_account_validation_and_creation_permission():
    with pytest.raises(AndroidEnvironmentError, match="both"):
        validate_credentials("existing", "qa-user", "")
    with pytest.raises(AndroidEnvironmentError, match="authorized test build"):
        validate_mobile_config({"app_mode": "installed", "package_name": PACKAGE,
                                "device_id": "emulator-5554", "account_mode": "create"})


def test_a_private_account_does_not_follow_a_link_into_another_folder(tmp_path):
    from pathlib import Path
    from types import SimpleNamespace

    from backend.android_accounts import persist
    from backend.android_interact import ACCOUNT_USERNAME
    from backend.finalization import save_login_state

    secret = b"tenant-b-only-account"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    (nested / "account_setup.json").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    session = SimpleNamespace(
        account_mode="create",
        account_setup={"mode": "create", "status": "created"},
        secrets={ACCOUNT_USERNAME: "ours@example.com"},
        device=SimpleNamespace(stop_path=(linked / "run") / "STOP", config={"account_mode": "create"}),
    )
    persist(session)
    assert save_login_state(linked / "run", lambda path: Path(path).write_text("ours", encoding="utf-8")) is False
    assert save_login_state(linked / "fresh", lambda path: Path(path).write_text("ours", encoding="utf-8")) is False
    assert not (other / "fresh").exists()
    assert not (nested / ".private").exists()
    assert (nested / "account_setup.json").read_bytes() == secret
    assert (nested / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    session.device = SimpleNamespace(stop_path=real / "STOP", config={"account_mode": "create"})
    persist(session)
    public = real / "account_setup.json"
    private = real / ".private" / "auto_secrets.json"
    assert public.is_file() and not public.is_symlink()
    assert b"created" in public.read_bytes() and secret not in public.read_bytes()
    assert private.is_file() and b"ours@example.com" in private.read_bytes()
    assert secret not in private.read_bytes()
    assert save_login_state(real, lambda path: Path(path).write_text("ours", encoding="utf-8")) is True
    assert (real / ".private" / "auth.json").read_text(encoding="utf-8") == "ours"
    assert (nested / "keep.txt").read_bytes() == secret


def test_a_private_account_does_not_follow_a_link_into_another_run(tmp_path):
    from types import SimpleNamespace

    from backend.android_accounts import initialize, persist

    secret = "tenant-b-only-account"
    other = tmp_path / "other"
    other.mkdir()
    (other / "auto_secrets.json").write_text(json.dumps({"password": secret}), encoding="utf-8")
    (other / "account_setup.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    (run / ".private").symlink_to(other, target_is_directory=True)
    (run / "account_setup.json").symlink_to(other / "account_setup.json")
    session = SimpleNamespace(
        account_mode="create",
        account_setup={"mode": "create", "status": "created"},
        secrets={"username": "ours"},
        device=SimpleNamespace(stop_path=run / "STOP", config={"account_mode": "create"}),
        account=None,
        given_account=False,
    )
    persist(session)
    initialize(session)
    assert json.loads((other / "auto_secrets.json").read_text(encoding="utf-8"))["password"] == secret
    assert (other / "account_setup.json").read_text(encoding="utf-8") == json.dumps({"secret": secret})
    assert secret not in json.dumps(session.secrets)


def test_unconfirmed_registration_is_not_repeated_after_resume(tmp_path):
    from backend.android_accounts import begin_registration
    session, app, _, _ = account_session(tmp_path)
    assert begin_registration(session)
    resumed, _, _, _ = account_session(tmp_path, app=app)
    prepare_account(resumed)
    assert resumed.account_setup["status"] == "attempted" and not app.registrations


def test_selected_policy_blocks_signup_replay_and_ai_submission(tmp_path):
    session, app, _, signup = account_session(tmp_path)
    submit = find_form(signup)["submit"]
    with pytest.raises(ValueError, match="Account policy"):
        session.perform([{"action": "tap", "locator": submit["locators"][0], "purpose": "test_form"}])
    assert not app.registrations


def test_ai_journeys_cannot_choose_another_login_or_signup_identity(tmp_path):
    session, _, _, _ = account_session(tmp_path)
    prompts = []
    def ask(prompt, shape):
        prompts.append(prompt)
        return shape.model_validate({"journeys": []})
    session.ai_journeys(ask)
    assert prompts
    for label in ("Username", "Password", "Register", "Email", "Login"):
        assert '"label": "' + label + '"' not in prompts[0]
