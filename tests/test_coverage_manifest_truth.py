"""Independent discovery coverage must fail closed when no truth exists."""
from backend.coverage_verify import verify_truth_pages


def test_empty_truth_manifest_is_not_complete():
    result = verify_truth_pages(discovered=["https://example.test/"], truth_pages=[])
    assert result["complete"] is False
    assert result["denominator"] == 0
    assert result["coverage_ratio"] == 0.0
    assert "truth_manifest_missing" in result["unknown"]


def test_known_pages_can_be_complete():
    result = verify_truth_pages(
        discovered=["https://example.test/shop", "https://example.test/product/42"],
        truth_pages=[{"path": "/shop"}, {"path": "/product/{id}"}],
    )
    assert result["complete"] is True
    assert result["coverage_ratio"] == 1.0


def test_unvisited_page_is_not_complete():
    result = verify_truth_pages(
        discovered=["https://example.test/shop"],
        truth_pages=[{"path": "/shop"}, {"path": "/cart"}],
    )
    assert result["complete"] is False
    assert "/cart" in result["missed"]


def test_inaccessible_page_is_explicitly_blocked():
    result = verify_truth_pages(
        discovered=["https://example.test/shop"],
        truth_pages=[{"path": "/shop"}, {"path": "/admin"}],
        inaccessible=[{"path": "/admin"}],
    )
    assert result["complete"] is True
    assert result["coverage_ratio"] == 0.5
    assert result["blocked"][0]["url"] == "/admin"


def test_optional_unvisited_page_is_unknown_not_pass():
    result = verify_truth_pages(
        discovered=["https://example.test/shop"],
        truth_pages=[{"path": "/shop"}, {"path": "/secret", "how": "requires permission"}],
    )
    assert result["complete"] is False
    assert "/secret" in result["unknown"]
