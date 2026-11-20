"""Phase 1 lesson: quantity feature tests must clear leftover cart lines before measuring delta."""
from backend.agents.script_generator import FEATURE_BODY


def test_quantity_feature_clears_existing_cart_line_before_measuring():
    body = "\n".join(FEATURE_BODY["quantity"])
    assert "while _cart_row(page, name[:40]) is not None:" in body
    assert "assert start == 0" in body
    assert "box.fill('')" in body
    assert body.count("_remove_own(page, name[:40])") >= 2  # cleanup loop + final cleanup
