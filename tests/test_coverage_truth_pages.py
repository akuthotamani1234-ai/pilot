"""Phase 2: independent coverage verifier against owned truth page manifests."""
import json
from pathlib import Path

from backend.coverage_verify import verify_truth_pages


def test_verify_truth_pages_marks_missing_and_unknown_without_passing():
    truth = json.loads(Path("tests/demo_store_truth.json").read_text(encoding="utf-8"))
    discovered = ["/", "/shop", "/cart", "/product/1", "/admin"]
    verdict = verify_truth_pages(
        discovered=discovered,
        truth_pages=truth["pages"],
        inaccessible=truth.get("inaccessible"),
    )
    assert verdict["complete"] is False
    assert "/shop" in verdict["covered"]
    assert "/signin" in verdict["missed"] or "/signin" in verdict["unknown"]
    assert any(row["url"] == "/admin" for row in verdict["blocked"]) or "/admin" not in verdict["covered"]
    assert verdict["coverage_ratio"] < 1.0
    assert verdict["denominator"] == len(truth["pages"])


def test_verify_truth_pages_is_complete_when_all_in_scope_paths_found():
    pages = [{"path": "/"}, {"path": "/shop"}, {"path": "/product/{id}"}]
    verdict = verify_truth_pages(
        discovered=["/", "/shop", "/product/12"],
        truth_pages=pages,
        inaccessible=[{"path": "/admin"}],
    )
    assert verdict["complete"] is True
    assert verdict["missed"] == []
    assert verdict["unknown"] == []
    assert verdict["covered"] == ["/", "/shop", "/product/{id}"]
