"""Gate A: surface coverage summarizes iframe/shadow/API without inventing completeness."""
from backend.surface_coverage import summarize_surfaces


def test_empty_app_map_stays_incomplete_with_unknowns():
    out = summarize_surfaces([], {})
    assert out["gate_a_surfaces_complete"] is False
    assert out["unknown"]


def test_summarize_counts_frames_shadow_and_api_seeds():
    pages = [{
        "url": "http://shop.test/",
        "title": "Shop",
        "locale": {"language": "en"},
        "lazy": {"new_links": ["http://shop.test/p/9"]},
        "mobile_checked": True,
        "iframes": ["help"],
        "frames": [
            {"status": "testable", "name": "help"},
            {"status": "external", "name": "ads"},
            {"status": "unreachable", "name": "broken"},
        ],
        "shadowRoots": 2,
        "unsupported": [{"reason": "unsupported: possibly a closed shadow root"}],
    }]
    crawl = {"found_by": {"http://shop.test/api/cart": "network", "http://shop.test/openapi.json": "scrape"},
             "blocked_requests": [{"url": "http://169.254.169.254/"}]}
    out = summarize_surfaces(pages, crawl)
    assert out["evidence"]["frames"]["testable"] == 1
    assert out["evidence"]["frames"]["external"] == 1
    assert out["evidence"]["frames"]["unreachable"] == 1
    assert out["evidence"]["shadow"]["open_roots_seen"] == 2
    assert out["evidence"]["shadow"]["closed_unsupported"] == 1
    assert out["evidence"]["api"]["network_seeded"] == 1
    assert out["evidence"]["lazy"]["pages_with_lazy"] == 1
    assert out["evidence"]["metadata"]["pages_with_locale"] == 1
    assert out["evidence"]["viewports"]["mobile_checked"] == 1
    assert out["pages"] == 1
    assert out["gate_a_surfaces_complete"] is False
