"""Ecommerce web QA contract example stays a valid, unapproved template."""
from pathlib import Path

from backend.qa_contracts import parse_contract

EXAMPLE = Path(__file__).resolve().parent.parent / "project-docs" / "examples" / "ecommerce-web-contract.json"


def test_ecommerce_web_contract_example_parses_and_stays_unapproved():
    contract = parse_contract(EXAMPLE.read_text(encoding="utf-8"))
    assert contract.version == 1
    assert contract.test_environment is False
    assert {flow.id for flow in contract.flows} == {"search_product", "open_product_add_to_cart"}
    assert all(flow.approved is False for flow in contract.flows)
    search = next(flow for flow in contract.flows if flow.id == "search_product")
    cart = next(flow for flow in contract.flows if flow.id == "open_product_add_to_cart")
    assert any(step.action == "fill" for step in search.steps)
    assert any(step.action.startswith("assert_") for step in search.steps)
    assert cart.setup_flow == "search_product"
    assert any(
        step.action == "tap" and "add-to-cart" in (step.locator.value if step.locator else "")
        for step in cart.steps
    )
    assert any(step.action == "assert_text" for step in cart.steps)
