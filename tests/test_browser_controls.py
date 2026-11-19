"""The test browser reads the run's control files. No browser is started here."""
import json
from pathlib import Path

from backend.browser_controls import FIXED_CLOCK_ISO, clock_script, load_controls, request_blocked
from backend.run_rules import environment_for

_NETWORK_WORDS = ("fetch", "xmlhttprequest", "websocket", "http://", "https://", "sendbeacon")


def _write_environment(folder: Path, environment: str, **flags: bool) -> None:
    controls = {
        name: {"enabled": bool(flags.get(name, False)), "reason": name}
        for name in ("stub_api", "fixed_clock", "network_fault")
    }
    payload = {
        "environment": environment,
        "controls": controls,
        "blocked": {"pay": {"blocked": False}, "delete": {"blocked": False}, "logout": {"blocked": False}},
    }
    (folder / "qx_environment.json").write_text(json.dumps(payload), encoding="utf-8")


def test_controls_are_off_when_the_files_are_missing(tmp_path):
    controls = load_controls(str(tmp_path))
    assert controls["stub_api"] is False
    assert controls["fixed_clock"] is False
    assert controls["network_fault"] is False
    assert controls["injected"] is False
    assert controls["service"] == ""
    assert clock_script() == ""
    assert clock_script(controls) == ""
    assert request_blocked("https://shop.example/saree", controls) is False


def test_a_broken_control_file_is_treated_as_missing(tmp_path):
    (tmp_path / "qx_environment.json").write_text("{", encoding="utf-8")
    (tmp_path / "qx_dependency.json").write_text("[", encoding="utf-8")
    controls = load_controls(tmp_path)
    assert controls["fixed_clock"] is False
    assert controls["network_fault"] is False
    assert controls["injected"] is False


def test_the_fixed_clock_script_is_present_only_when_that_control_is_enabled(tmp_path):
    assert clock_script(load_controls(tmp_path)) == ""
    _write_environment(tmp_path, "staging", fixed_clock=True)
    script = clock_script(load_controls(tmp_path))
    assert FIXED_CLOCK_ISO in script and "Date" in script
    lowered = script.lower()
    assert all(word not in lowered for word in _NETWORK_WORDS)
    _write_environment(tmp_path, "test", fixed_clock=False, network_fault=True)
    assert clock_script(load_controls(tmp_path)) == ""


def test_production_files_that_say_enabled_are_ignored(tmp_path):
    _write_environment(tmp_path, "production", stub_api=True, fixed_clock=True, network_fault=True)
    (tmp_path / "qx_dependency.json").write_text(
        json.dumps({"injected": True, "service": "inventory"}), encoding="utf-8")
    controls = load_controls(tmp_path)
    assert controls["environment"] == "production"
    assert controls["stub_api"] is False
    assert controls["fixed_clock"] is False
    assert controls["network_fault"] is False
    assert controls["injected"] is False
    assert controls["service"] == ""
    assert clock_script(controls) == ""
    assert request_blocked("https://inventory.example/stock", controls) is False
    assert request_blocked("https://shop.example/checkout", controls) is True


def test_a_dependency_fault_blocks_only_that_service_host(tmp_path):
    _write_environment(tmp_path, "staging")
    (tmp_path / "qx_dependency.json").write_text(
        json.dumps({"injected": True, "service": "inventory", "reason": "inventory was made unavailable"}),
        encoding="utf-8")
    controls = load_controls(tmp_path)
    assert controls["injected"] is True and controls["service"] == "inventory"
    assert controls["network_fault"] is False
    assert request_blocked("https://inventory.shop.test/stock", controls) is True
    assert request_blocked("https://Inventory.Example/health", controls) is True
    assert request_blocked("wss://api.inventory.example/socket", controls) is True
    assert request_blocked("https://shop.example/saree", controls) is False
    assert request_blocked("https://shop.example/inventory", controls) is False
    home = dict(controls, start_url="https://inventory.shop.test/", navigation=True)
    assert request_blocked("https://inventory.shop.test/", home) is False
    assert request_blocked("https://inventory.shop.test/stock", dict(home, navigation=False)) is True


def test_payment_urls_stay_blocked_even_when_no_fault_is_injected(tmp_path):
    _write_environment(tmp_path, "test")
    (tmp_path / "qx_dependency.json").write_text(json.dumps({"injected": False, "reason": "none"}), encoding="utf-8")
    controls = load_controls(tmp_path)
    assert controls["injected"] is False and controls["network_fault"] is False
    for url in ("https://shop.example/checkout", "https://shop.example/pay", "https://shop.example/payment",
                "https://shop.example/logout", "https://shop.example/sign-out", "https://shop.example/account/delete"):
        assert request_blocked(url, controls) is True, url
    assert request_blocked("https://shop.example/saree", controls) is False
    # The cart page on a one-script shop, and an admin pay-grade screen, are not the payment.
    assert request_blocked("https://shop.example/index.php?rt=checkout/cart", controls) is False
    assert request_blocked("https://hr.example/admin/pay-grades", controls) is False
    assert request_blocked("https://www.paypal.com/cgi-bin/webscr", controls) is True
    assert request_blocked("https://shop.example/checkout.html", controls) is True
    assert request_blocked("https://shop.example/cart/checkout%2Ehtml", controls) is True
    # A fault must not open the payment, even when that address is the document being opened.
    opened = dict(controls, start_url="https://shop.example/checkout", navigation=True)
    assert request_blocked("https://shop.example/checkout", opened) is True


def test_a_network_fault_fails_requests_except_the_start_document(tmp_path):
    _write_environment(tmp_path, "staging", network_fault=True)
    controls = load_controls(tmp_path)
    assert controls["network_fault"] is True
    start = dict(controls, start_url="https://shop.example/", navigation=True)
    assert request_blocked("https://shop.example/", start) is False
    assert request_blocked("https://shop.example", start) is False
    assert request_blocked("https://shop.example/app.js", dict(start, navigation=False)) is True
    assert request_blocked("https://cdn.example/app.js", start) is True
    assert request_blocked("about:blank", start) is False
    assert request_blocked("https://shop.example/checkout", start) is True
    assert request_blocked("https://shop.example/logout", start) is True


def test_the_file_discovery_writes_is_what_the_browser_reads(tmp_path, monkeypatch):
    (tmp_path / "qx_environment.json").write_text(json.dumps(environment_for("staging")), encoding="utf-8")
    quiet = load_controls(tmp_path)
    assert quiet["fixed_clock"] is False and quiet["network_fault"] is False and quiet["stub_api"] is False
    assert quiet["environment"] == "staging"
    monkeypatch.setenv("FIXED_CLOCK", "1")
    monkeypatch.setenv("NETWORK_FAULT", "1")
    monkeypatch.setenv("STUB_API", "1")
    (tmp_path / "qx_environment.json").write_text(json.dumps(environment_for("staging")), encoding="utf-8")
    controls = load_controls(tmp_path)
    assert controls["fixed_clock"] is True
    assert controls["network_fault"] is True
    assert controls["stub_api"] is True
    assert FIXED_CLOCK_ISO in clock_script(controls)
    (tmp_path / "qx_environment.json").write_text(json.dumps(environment_for("production")), encoding="utf-8")
    off = load_controls(tmp_path)
    assert off["fixed_clock"] is False and off["network_fault"] is False
    assert clock_script(off) == ""


def test_a_dependency_fault_is_written_before_the_browser_starts(tmp_path, monkeypatch):
    """Pytest must see qx_dependency.json when it starts, or the fault never reaches the browser."""
    from backend import runctl
    from backend.agents import executor

    runctl.reset()
    test_dir = tmp_path / "generated_tests"
    test_dir.mkdir()
    monkeypatch.setattr(executor, "IS_WINDOWS", False)
    monkeypatch.setattr(executor.settings, "environment", "staging")
    monkeypatch.setattr(executor.settings, "suite_timeout_s", 30)
    monkeypatch.setenv("DEPENDENCY_FAULT", "inventory")
    monkeypatch.setenv("DEPENDENCY_PERMITTED", "true")
    seen = {}

    class _Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return "", None

    def _popen(*_args, **_kwargs):
        seen["payload"] = json.loads((tmp_path / "qx_dependency.json").read_text(encoding="utf-8"))
        return _Proc()

    monkeypatch.setattr(executor.subprocess, "Popen", _popen)
    executor._run_pytest(
        {"url": "http://127.0.0.1/", "crawl": {"approved_hosts": ["127.0.0.1"]}},
        test_dir, tmp_path / "results.jsonl", tmp_path / "shots",
    )
    assert seen["payload"]["injected"] is True
    assert seen["payload"]["service"] == "inventory"


def test_the_suite_template_applies_the_controls_in_the_browser():
    text = Path("backend/templates/conftest.py").read_text(encoding="utf-8")
    assert "load_controls" in text
    assert "clock_script" in text
    assert "request_blocked" in text
    assert "_CLOCK_SCRIPT" in text
    assert 'else "failed"' in text
    assert 'abort("blockedbyclient")' in text


def test_a_test_result_does_not_follow_a_link_into_another_run(tmp_path):
    import ast

    from backend.finalization import save_login_state, write_text_unless_linked

    secret = "tenant-b-only-result"
    other = tmp_path / "other"
    other.mkdir()
    (other / "results.jsonl").write_text(secret + "\n", encoding="utf-8")
    (other / "running.json").write_text(secret, encoding="utf-8")
    (other / "events.jsonl").write_text(secret + "\n", encoding="utf-8")
    (other / "crawl.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")
    (other / "auth.json").write_text(secret, encoding="utf-8")
    private = other / "private"
    private.mkdir()

    run = tmp_path / "run-a"
    run.mkdir()
    (run / "results.jsonl").symlink_to(other / "results.jsonl")
    (run / "running.json").symlink_to(other / "running.json")
    (run / "events.jsonl").symlink_to(other / "events.jsonl")
    (run / "crawl.json").symlink_to(other / "crawl.json")
    (run / ".private").symlink_to(private, target_is_directory=True)

    tree = ast.parse(Path("backend/templates/conftest.py").read_text(encoding="utf-8"))
    want = {"_output_is_linked", "_record", "_running", "_event"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]

    class _Item:
        name = "test_secret"
        nodeid = "test_secret"
        _qa_t0 = 0
        _qa_page = None

    ns = {
        "Path": Path, "json": json, "os": __import__("os"), "time": __import__("time"),
        "RESULTS_FILE": run / "results.jsonl",
        "RUNNING_FILE": run / "running.json",
        "EVENT_FILE": run / "events.jsonl",
        "EVENT_SESSION": "s",
        "TEST_TIMEOUT_S": 1, "MAX_STEPS": 5,
        "_CURRENT": {"item": _Item()}, "_EVENT_SEQUENCE": 0,
        "_redact": lambda value: value,
    }
    exec(compile(ast.Module(nodes, []), "conftest.py", "exec"), ns)
    ns["_record"]({"nodeid": "test_ok", "outcome": "passed", "error": "ours"})
    ns["_running"](None)
    ns["_event"]("finished", "passed")
    assert (other / "results.jsonl").read_text(encoding="utf-8") == secret + "\n"
    assert (other / "running.json").read_text(encoding="utf-8") == secret
    assert (other / "events.jsonl").read_text(encoding="utf-8") == secret + "\n"

    own = tmp_path / "own"
    own.mkdir()
    ns["RESULTS_FILE"] = own / "results.jsonl"
    ns["_record"]({"nodeid": "test_ok", "outcome": "passed"})
    assert "test_ok" in (own / "results.jsonl").read_text(encoding="utf-8")

    assert write_text_unless_linked(run, "crawl.json", json.dumps({"visited": 1})) is False
    assert json.loads((other / "crawl.json").read_text(encoding="utf-8"))["secret"] == secret
    assert write_text_unless_linked(own, "crawl.json", json.dumps({"visited": 1})) is True
    assert json.loads((own / "crawl.json").read_text(encoding="utf-8"))["visited"] == 1

    written = []
    assert save_login_state(run, written.append) is False
    assert written == []
    assert (other / "auth.json").read_text(encoding="utf-8") == secret
    assert save_login_state(own, written.append) is True
    assert written == [str(own / ".private" / "auth.json")]


def test_a_saved_login_does_not_follow_a_link_into_another_run(tmp_path):
    from backend.finalization import private_file, save_login_state

    secret = "tenant-b-only-login"
    other = tmp_path / "other"
    other.mkdir()
    (other / "auth.json").write_text(secret, encoding="utf-8")
    (other / "auth_admin.json").write_text(secret, encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    (run / ".private").symlink_to(other, target_is_directory=True)
    assert private_file(run, "auth_admin.json") is None
    assert private_file(run, "auth.json") is None
    assert save_login_state(run, lambda path: Path(path).write_text("ours", encoding="utf-8")) is False
    assert (other / "auth.json").read_text(encoding="utf-8") == secret
    assert (other / "auth_admin.json").read_text(encoding="utf-8") == secret

    own = tmp_path / "own"
    own.mkdir()
    (own / ".private").mkdir()
    (own / ".private" / "auth_admin.json").symlink_to(other / "auth_admin.json")
    assert private_file(own, "auth_admin.json") is None
    assert (other / "auth_admin.json").read_text(encoding="utf-8") == secret
    saved = private_file(own, "auth.json")
    assert saved == own / ".private" / "auth.json"
    saved.write_text("ours", encoding="utf-8")
    assert saved.read_text(encoding="utf-8") == "ours"
    assert private_file(own, "../auth.json") is None


def test_a_generated_test_cannot_read_through_a_link_out_of_its_run(tmp_path, monkeypatch):
    import ast
    import os
    import re
    import threading

    import pytest

    tree = ast.parse(Path("backend/templates/conftest.py").read_text(encoding="utf-8"))
    want = {"_inside_run", "_link_escapes", "_audit"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
    run = tmp_path / "run"
    run.mkdir()
    (run / "own.txt").write_text("ours", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("tenant-b-only-secret", encoding="utf-8")
    (run / "note.txt").symlink_to(secret)
    library = tmp_path / "library.txt"
    library.write_text("library", encoding="utf-8")
    ns = {
        "Path": Path, "os": os, "threading": threading,
        "RUN_DIR": run.resolve(),
        "_SANDBOX": {"thread": threading.get_ident()},
        "SENSITIVE": re.compile(
            r"(^|[\\/])(\.env|accounts|\.private|auth\.json|id_rsa|\.ssh|\.aws|\.git-credentials)([\\/]|$)",
            re.I),
        "_PROCESS_EVENTS": (), "_NET_EVENTS": (), "_FILE_EVENTS": (),
    }
    exec(compile(ast.Module(nodes, []), "conftest.py", "exec"), ns)
    ns["_audit"]("open", (str(run / "own.txt"), "r"))
    ns["_audit"]("open", (str(library), "r"))
    with pytest.raises(PermissionError):
        ns["_audit"]("open", (str(run / "note.txt"), "r"))
    with pytest.raises(PermissionError):
        ns["_audit"]("open", (str(run / "note.txt"), "w"))
    monkeypatch.chdir(run)
    ns["_audit"]("open", ("own.txt", "r"))
    with pytest.raises(PermissionError):
        ns["_audit"]("open", ("../secret.txt", "r"))
    assert secret.read_text(encoding="utf-8") == "tenant-b-only-secret"
    assert not (tmp_path / "outside.txt").exists()


def test_browser_controls_are_not_read_through_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-only-service"
    other = tmp_path / "other"
    nested = other / "runs" / "run"
    nested.mkdir(parents=True)
    _write_environment(nested, "staging", fixed_clock=True, network_fault=True)
    (nested / "qx_dependency.json").write_text(json.dumps({
        "injected": True, "service": secret,
    }), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    refused = load_controls(linked / "runs" / "run")
    assert refused["fixed_clock"] is False
    assert refused["network_fault"] is False
    assert refused["injected"] is False
    assert refused["service"] == ""
    assert secret not in json.dumps(refused)
    assert secret in (nested / "qx_dependency.json").read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    _write_environment(real, "staging", fixed_clock=True)
    (real / "qx_dependency.json").write_text(json.dumps({
        "injected": True, "service": "home-own-api",
    }), encoding="utf-8")
    loaded = load_controls(real)
    assert loaded["fixed_clock"] is True
    assert loaded["service"] == "home-own-api"
    assert secret not in json.dumps(loaded)
    assert secret in (nested / "qx_dependency.json").read_text(encoding="utf-8")
