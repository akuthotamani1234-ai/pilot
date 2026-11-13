"""Behavior, read-only enforcement, secret handling and truthful QA measurements."""

import json
import sqlite3
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend import qa_benchmark, server
from backend.qa_contracts import BackendCheck, contract_cases, evaluate, parse_contract
from backend.qa_oracles import check_http, check_sqlite
from backend.qa_web import run_contracts
from backend.safety import clean_env, redact
from tests.qa_contract_fixture import ContractFixture


def loc(value, strategy="css"):
    return {"strategy": strategy, "value": value}


def web_contract(url):
    return {
        "version": 1,
        "test_environment": True,
        "allowed_origins": [url],
        "flows": [
            {
                "id": "valid_login",
                "title": "Approved local login reaches Dashboard",
                "approved": True,
                "authentication": True,
                "steps": [
                    {"action": "fill", "locator": loc("#user"), "value": "demo"},
                    {"action": "fill", "locator": loc("#password"), "secret_ref": "BLOWAI_SECRET_DEMO_PASSWORD"},
                    {"action": "tap", "locator": loc("#submit"), "purpose": "test_form"},
                    {"action": "assert_text", "locator": loc("#heading"), "value": "Dashboard"},
                ],
            },
            {
                "id": "required_name",
                "title": "An empty required name is rejected",
                "approved": True,
                "steps": [
                    {"action": "tap", "locator": loc("#validate"), "purpose": "test_form"},
                    {"action": "assert_text", "locator": loc("#validationMessage"), "value": "Name is required"},
                ],
            },
        ],
        "rules": [
            {
                "id": "quote_total",
                "title": "Quantity times unit price",
                "actual": loc("#total"),
                "variables": {"quantity": {"locator": loc("#quantity")}, "price": {"locator": loc("#price")}},
                "expression": "quantity * price",
            }
        ],
        "checks": [
            {
                "id": "api_total",
                "title": "API confirms zero-quantity total",
                "kind": "http",
                "url": url + "/api/state",
                "json_pointer": "/total",
                "expected": 0,
            },
            {
                "id": "database_total",
                "title": "Read-only database total",
                "kind": "sqlite",
                "database_ref": "BLOWAI_DB_DEMO",
                "query": "SELECT total FROM quotes WHERE id = ?",
                "parameters": [1],
                "expected": 0,
            },
        ],
    }


@pytest.mark.parametrize(
    "expression",
    ["__import__('os').getcwd()", "value.__class__", "value ** 9", "[value][0]", "sum(value)", "unknown + 1"],
)
def test_calculations_reject_python_execution(expression):
    with pytest.raises(ValueError):
        evaluate(expression, {"value": Decimal(2)})


def test_decimal_calculations_do_not_round_like_binary_float():
    assert evaluate(
        "price * quantity - discount", {"price": Decimal("0.1"), "quantity": Decimal(3), "discount": Decimal("0.2")}
    ) == Decimal("0.1")


def test_contract_rejects_inline_password_and_does_not_echo_its_value():
    contract = web_contract("http://127.0.0.1:9999")
    step = contract["flows"][0]["steps"][1]
    step.pop("secret_ref")
    step["value"] = "do-not-echo-sensitive-password"
    with pytest.raises(ValueError) as caught:
        parse_contract(contract)
    assert step["value"] not in str(caught.value)


@pytest.mark.parametrize("label", ["Pay Now", "Checkout", "Place order", "Buy now"])
def test_checkout_payment_remain_blocked_even_in_approved_contract(label):
    with pytest.raises(ValueError):
        parse_contract(
            {
                "test_environment": True,
                "flows": [
                    {
                        "id": "unsafe",
                        "title": "Unsafe",
                        "approved": True,
                        "steps": [
                            {"action": "tap", "locator": loc(label, "accessibility_id"), "purpose": "test_form"},
                            {"action": "assert_screen", "value": "Home"},
                        ],
                    }
                ],
            }
        )


@pytest.mark.parametrize("label", ["Delete account", "resetDevice", "send_message"])
def test_non_payment_labels_may_be_approved_in_contract(label):
    parse_contract(
        {
            "test_environment": True,
            "test_mode": True,
            "flows": [
                {
                    "id": "ok",
                    "title": "Ok",
                    "approved": True,
                    "steps": [
                        {"action": "tap", "locator": loc(label, "accessibility_id"), "purpose": "test_form"},
                        {"action": "assert_screen", "value": "Home"},
                    ],
                }
            ],
        }
    )


def test_unapproved_flows_are_blocked_not_passes():
    contract = parse_contract(
        {"flows": [{"id": "unapproved", "title": "Review", "steps": [{"action": "assert_screen", "value": "Home"}]}]}
    )
    assert contract_cases(contract)[0]["blocked"] is True


def test_authentication_requires_post_submission_result_evidence():
    with pytest.raises(ValueError, match="Authentication needs"):
        parse_contract(
            {
                "flows": [
                    {
                        "id": "auth",
                        "title": "Auth",
                        "authentication": True,
                        "steps": [{"action": "assert_visible", "locator": loc("#password")}],
                    }
                ]
            }
        )


def test_contract_secrets_are_redacted_and_removed_from_generated_worker_env(monkeypatch):
    monkeypatch.setenv("BLOWAI_SECRET_DEMO_PASSWORD", "private-contract-value")
    assert "private-contract-value" not in redact("password private-contract-value")
    assert "BLOWAI_SECRET_DEMO_PASSWORD" not in clean_env({"BLOWAI_SECRET_DEMO_PASSWORD": "private-contract-value"})


def test_sqlite_oracle_is_read_only_and_denies_attachment_and_file_functions(tmp_path):
    path = tmp_path / "data.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE evidence(value INTEGER)")
        connection.execute("INSERT INTO evidence VALUES (3)")
    check = BackendCheck(
        id="db",
        title="Read-only evidence",
        kind="sqlite",
        database_ref="BLOWAI_DB_TEST",
        query="SELECT value FROM evidence",
        expected=3,
    )
    assert check_sqlite(check, {"BLOWAI_DB_TEST": str(path)})["read_only"]
    for query in ("DELETE FROM evidence", "SELECT value FROM evidence; DELETE FROM evidence"):
        with pytest.raises(ValueError):
            BackendCheck(
                id="db", title="Unsafe query", kind="sqlite", database_ref="BLOWAI_DB_TEST", query=query, expected=3
            )
    check.query = "SELECT load_extension('no-extension')"
    with pytest.raises(sqlite3.DatabaseError):
        check_sqlite(check, {"BLOWAI_DB_TEST": str(path)})
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM evidence").fetchone() == (3,)


def test_http_oracle_never_follows_redirects_and_rejects_unapproved_origins(tmp_path):
    with ContractFixture(tmp_path / "api.sqlite") as fixture:
        check = BackendCheck(id="api", title="Read API", kind="http", url=fixture.url + "/redirect", expected=0)
        with pytest.raises(AssertionError, match="HTTP"):
            check_http(check, [fixture.url], {})
        assert fixture.requests == ["/redirect"]
        with pytest.raises(ValueError, match="approved scope"):
            check_http(check, ["http://example.test"], {})


@pytest.mark.parametrize("broken", [False, True])
def test_real_browser_contracts_detect_login_form_business_api_and_database_results(tmp_path, monkeypatch, broken):
    monkeypatch.setenv("BLOWAI_SECRET_DEMO_PASSWORD", "demo123")
    database = tmp_path / "fixture.sqlite"
    monkeypatch.setenv("BLOWAI_DB_DEMO", str(database))
    with ContractFixture(database, broken=broken) as fixture:
        result = run_contracts(tmp_path, fixture.url, web_contract(fixture.url))
    by_id = {r["id"]: r for r in result["results"]}
    assert by_id["contract_valid_login"]["outcome"] == "passed"
    assert by_id["contract_valid_login"]["authentication_verified"] is True
    for case_id in ("contract_required_name", "contract_quote_total", "contract_api_total", "contract_database_total"):
        assert by_id[case_id]["outcome"] == ("failed" if broken else "passed"), by_id[case_id]
        if broken:
            assert by_id[case_id]["exception_type"] == "AssertionError"
    assert "demo123" not in (tmp_path / "contract_results.json").read_text(encoding="utf-8")


def test_benchmark_does_not_count_infrastructure_as_detected_defect_and_measures_instability(tmp_path):
    fixtures = {
        "clean": [{"id": "rule", "outcome": "passed"}],
        "defect": [{"id": "rule", "outcome": "failed", "exception_type": "AssertionError"}],
        "error": [{"id": "rule", "outcome": "error", "exception_type": "ConnectionError"}],
    }
    for name, rows in fixtures.items():
        (tmp_path / name).mkdir()
        (tmp_path / name / "results.json").write_text(json.dumps(rows), encoding="utf-8")
    result = qa_benchmark.measure(
        tmp_path,
        {
            "groups": [
                {"name": "clean", "runs": ["clean"], "expected": {"rule": "passed"}},
                {"name": "known defect", "runs": ["defect", "error"], "expected": {"rule": "failed"}},
            ]
        },
    )
    assert result["counts"] == {"tp": 1, "fp": 0, "tn": 1, "fn": 0, "unanswered_positive": 1, "unanswered_negative": 0}
    assert result["recall"] == 0.5
    assert result["precision"] == 1
    assert len(result["unstable_cases"]) == 1
    with pytest.raises(ValueError):
        qa_benchmark.run_path(tmp_path, "../outside")


def test_contract_schema_lab_and_invalid_contract_api_are_available():
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    assert client.get("/qa-lab").status_code == 200
    assert "flows" in client.get("/api/contracts/schema").json()["properties"]
    response = client.post(
        "/api/mobile/runs",
        headers={"X-Agentic-QA": "1"},
        data={
            "app_mode": "installed",
            "device_id": "test",
            "package_name": "com.example",
            "authorized": "true",
            "qa_contract": "{bad-json",
        },
    )
    assert response.status_code == 400


def test_opening_a_login_screen_is_navigation_and_does_not_submit_credentials():
    from backend.qa_runtime import ContractRuntime

    events = []

    class Adapter:
        def guard(self):
            pass

        def context(self, value):
            events.append(value)

        def find(self, locator):
            return object()

        def identity(self, element):
            return "Open login screen"

        def enabled(self, element):
            return True

        def tap(self, element):
            events.append("opened")

        def assert_screen(self, expected):
            assert expected == "Login"

    contract = {
        "test_environment": True,
        "flows": [
            {
                "id": "open_login",
                "title": "Open login",
                "approved": True,
                "steps": [
                    {"action": "tap", "locator": {"strategy": "accessibility_id", "value": "Open login screen"}},
                    {"action": "assert_screen", "value": "Login"},
                ],
            }
        ],
    }
    runtime = ContractRuntime(Adapter(), contract)
    runtime.execute("open_login")
    assert events == ["opened", "native"]
    assert runtime.checks == 1


def test_mobile_contract_runtime_errors_are_infrastructure_not_application_defects():
    from backend.android_reporting import classify_failure

    assert (
        classify_failure({"outcome": "failed", "exception_type": "RuntimeError", "error": "Policy blocked a control"})
        == "infrastructure"
    )
