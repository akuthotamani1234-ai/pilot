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
