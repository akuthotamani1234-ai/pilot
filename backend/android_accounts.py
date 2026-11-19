"""An explicit account policy and one private identity for each Android run."""

import json
from pathlib import Path

from .android import AndroidEnvironmentError

MODES = {"legacy", "none", "existing", "create"}


def validate_credentials(mode: str, username: str, password: str) -> None:
    if mode == "existing" and (not username.strip() or not password):
        raise AndroidEnvironmentError("Enter both test-account username/email and password, or choose another account option.")


def preserves_account(config: dict) -> bool:
    return config.get("account_mode") in {"existing", "create"}


def reset_for_check(driver, config: dict, package: str) -> None:
    from .android import reset_app_data

    if preserves_account(config):
        # Clearing data deletes locally registered users and supplied local accounts.
        driver.terminate_app(package)
        driver.activate_app(package)
    else:
        reset_app_data(driver, package)


def initialize(session) -> None:
    from .android_interact import ACCOUNT_PASSWORD, ACCOUNT_USERNAME

    session.account_mode = session.device.config.get("account_mode", "legacy")
    session.account_setup = {"mode": session.account_mode, "status": "not_started", "registrations_attempted": 0}
    if session.account_mode == "none":
        session.account = None
        session.given_account = False
    if session.account_mode != "create":
        return
    session.account = None
    session.given_account = False
    root = session.device.stop_path.parent
    public, private = root / "account_setup.json", root / ".private" / "auto_secrets.json"
    if (root.is_symlink() or public.is_symlink() or private.is_symlink() or (root / ".private").is_symlink()):
        return
    if public.is_file():
        saved = json.loads(public.read_text(encoding="utf-8"))
        if saved.get("mode") != "create":
            raise AndroidEnvironmentError("This run's account policy changed; start a new run.")
        session.account_setup = saved
        values = json.loads(private.read_text(encoding="utf-8")) if private.is_file() else {}
        session.secrets.update({key: value for key, value in values.items() if key in session.secrets
                                or key in {ACCOUNT_USERNAME, ACCOUNT_PASSWORD}})
        if saved.get("status") in {"created", "verified"} and all(values.get(k) for k in (ACCOUNT_USERNAME, ACCOUNT_PASSWORD)):
            session.account = (ACCOUNT_USERNAME, ACCOUNT_PASSWORD)


def persist(session) -> None:
    from .android_interact import ACCOUNT_PASSWORD, ACCOUNT_USERNAME, SIGNUP_EMAIL, SIGNUP_USERNAME, STRONG_PASSWORD

    if session.account_mode != "create":
        return
    from .finalization import private_file, write_text_unless_linked
    root = Path(session.device.stop_path.parent)
    if not root.is_symlink():
        root.mkdir(parents=True, exist_ok=True)
    secret_path = private_file(root, "auto_secrets.json")
    public = json.dumps(session.account_setup)
    if secret_path is None or not write_text_unless_linked(root, "account_setup.json", public):
        return
    refs = (ACCOUNT_USERNAME, ACCOUNT_PASSWORD, SIGNUP_EMAIL, SIGNUP_USERNAME, STRONG_PASSWORD)
    secret_path.write_text(json.dumps({key: session.secrets[key] for key in refs
                                       if key in session.secrets}), encoding="utf-8")


def begin_registration(session) -> bool:
    if session.account_setup.get("registrations_attempted"):
        return False
    session.account_setup.update(status="attempted", registrations_attempted=1,
                                 detail="Registration outcome is not confirmed. No replacement account will be created.")
    # Persist before submitting so interruption/resume never blindly registers again.
    persist(session)
    return True


def registered(session, actions: list[dict]) -> None:
    session.remember_account(actions)
    if not session.has_account:
        session.account_setup.update(status="unverified", detail="Registration did not expose reusable login references.")
    else:
        session.account_setup.update(status="created", detail="One account was created for this run; login must still be verified.")
    persist(session)


def authenticated(session) -> None:
    if session.account_mode in {"create", "existing"}:
        session.account_setup.update(status="verified", authentication_verified=True,
                                     detail="The selected test account passed login and is reused for this run.")
        persist(session)


def prepare_account(session) -> None:
    """Register once before planning login and protected-screen checks."""
    if session.account_mode != "create" or session.has_account or session.account_setup.get("registrations_attempted"):
        return
    from .android_interact import find_form

    for screen in list(session.screens):
        form = find_form(screen, session.native)
        if form and form["kind"] == "signup" and form.get("submit"):
            session.form_checks(screen, form)
            return
    session.account_setup.update(status="unavailable", detail="No unambiguous registration form was discovered; provide a test account instead.")
    persist(session)


def guard_registration(session, step: dict) -> None:
    if session.account_mode == "legacy" or getattr(session, "_account_registration_active", False) or step.get("action") != "tap":
        return
    from .android_interact import find_form

    for screen in session.screens:
        form = find_form(screen, session.native)
        if form and form["kind"] == "signup" and form.get("submit") and step.get("locator") in form["submit"].get("locators", []):
            raise ValueError("Account policy blocks another registration; use the one selected account for this run.")
