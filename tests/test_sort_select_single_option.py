"""Sort-by selects whose empty placeholder was dropped still count as sort features."""
from backend.features import page_features


def test_sort_select_with_one_priced_option_is_detected():
    page = {
        "url": "http://127.0.0.1/search?from=LHR&to=JFK",
        "title": "Results",
        "slug": "search",
        "page_type": "listing",
        "inputs": [{
            "tag": "select",
            "id": "sort",
            "name": "sort",
            "label": "Sort by",
            "selector": "#sort",
            "options": [{"value": "price", "text": "Price: low to high"}],
        }],
        "itemLinks": {
            "selector": "#results a",
            "links": [{"href": "/flight/1", "text": "QA101"}, {"href": "/flight/2", "text": "QA205"},
                      {"href": "/flight/3", "text": "QA330"}],
            "count": 3,
        },
        "buttons": [],
        "links": [],
        "forms": [],
    }
    kinds = {f["kind"] for f in page_features(page)}
    assert "sort" in kinds
    assert "items" in kinds
