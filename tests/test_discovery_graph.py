"""Gate A: discovery graph persists nodes/edges with provenance."""
from pathlib import Path

from backend.discovery_graph import build_graph, write_graph


def test_build_graph_attaches_provenance_and_never_claims_gate_a_complete():
    pages = [
        {
            "url": "http://shop.test/",
            "slug": "home",
            "page_type": "home",
            "auth": False,
            "title": "Home",
            "status": 200,
            "buttons": [{"text": "Shop", "selector": "#shop", "count": 1}],
            "links": [{"href": "http://shop.test/shop", "text": "Shop"}],
            "inputs": [],
            "forms": [],
            "itemLinks": {"links": [], "selector": ""},
        },
        {
            "url": "http://shop.test/shop",
            "slug": "shop",
            "page_type": "listing",
            "auth": False,
            "title": "Shop",
            "status": 200,
            "buttons": [],
            "links": [],
            "inputs": [],
            "forms": [],
            "itemLinks": {"links": [{"href": "http://shop.test/p/1", "text": "Item"}], "selector": ".card a", "count": 3},
        },
    ]
    graph = build_graph(pages, {})
    assert graph["gate_a_complete"] is False
    assert graph["schema_version"] == 1
    assert graph["counts"]["pages"] >= 1
    assert all("provenance" in node and node["provenance"]["source"] == "discovery" for node in graph["nodes"])
    assert all("provenance" in edge for edge in graph["edges"])


def test_write_graph_creates_discovery_graph_json(tmp_path: Path):
    graph = write_graph(tmp_path, [{
        "url": "http://shop.test/", "slug": "home", "page_type": "home", "auth": False,
        "title": "Home", "status": 200, "buttons": [], "links": [], "inputs": [], "forms": [],
        "itemLinks": {"links": [], "selector": ""},
    }], {})
    path = tmp_path / "discovery_graph.json"
    assert path.is_file()
    assert graph["counts"]["nodes"] >= 1
