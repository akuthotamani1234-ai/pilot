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


def test_a_discovery_graph_does_not_follow_a_link_into_another_folder(tmp_path):
    from backend.discovery_report import discovery_report
    from backend.locale_check import write_locale

    secret = b"tenant-b-only-graph"
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_bytes(secret)
    (other / "discovery_graph.json").write_bytes(secret)
    (other / "locale.json").write_bytes(secret)
    (other / "summary.json").write_bytes(secret)
    (other / "report.html").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    page = {
        "url": "http://shop.test/", "slug": "home", "page_type": "home", "auth": False,
        "title": "Home", "status": 200, "buttons": [], "links": [], "inputs": [], "forms": [],
        "itemLinks": {"links": [], "selector": ""},
    }
    write_graph(linked / "run", [page])
    write_locale(linked / "run", {"currency": "USD"})
    discovery_report({"run_id": "linked", "run_dir": str(linked / "run"), "url": "https://shop.test",
                      "app_map": [page], "crawl": {}, "log": []})
    assert (other / "keep.txt").read_bytes() == secret
    assert (other / "discovery_graph.json").read_bytes() == secret
    assert (other / "locale.json").read_bytes() == secret
    assert (other / "summary.json").read_bytes() == secret
    assert (other / "report.html").read_bytes() == secret
    assert not (other / "run").exists()

    real = tmp_path / "real"
    real.mkdir()
    write_graph(real, [page])
    assert b"shop.test" in (real / "discovery_graph.json").read_bytes()
    assert secret not in (real / "discovery_graph.json").read_bytes()
    assert write_locale(real, {"currency": "USD"})["observed"]["currency"] == "USD"
    assert secret not in (real / "locale.json").read_bytes()
    discovery_report({"run_id": "real", "run_dir": str(real), "url": "https://shop.test",
                      "app_map": [page], "crawl": {}, "log": []})
    assert "Component discovery" in (real / "report.html").read_text(encoding="utf-8")
    assert secret not in (real / "summary.json").read_bytes()
    assert (other / "keep.txt").read_bytes() == secret


def test_write_graph_creates_discovery_graph_json(tmp_path: Path):
    graph = write_graph(tmp_path, [{
        "url": "http://shop.test/", "slug": "home", "page_type": "home", "auth": False,
        "title": "Home", "status": 200, "buttons": [], "links": [], "inputs": [], "forms": [],
        "itemLinks": {"links": [], "selector": ""},
    }], {})
    path = tmp_path / "discovery_graph.json"
    assert path.is_file()
    assert graph["counts"]["nodes"] >= 1


def test_a_saved_page_does_not_follow_a_link_into_another_run(tmp_path):
    import json

    from backend.finalization import path_unless_linked, write_text_unless_linked
    from backend.locale_check import write_locale

    secret = "tenant-b-only-page"
    other = tmp_path / "other"
    other.mkdir()
    (other / "home.html").write_text(secret, encoding="utf-8")
    (other / "01_home.png").write_bytes(b"tenant-b-only-page")
    (other / "discovery_graph.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")
    (other / "locale.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")

    run = tmp_path / "run"
    run.mkdir()
    (run / "html").symlink_to(other, target_is_directory=True)
    (run / "screenshots").symlink_to(other, target_is_directory=True)
    (run / "discovery_graph.json").symlink_to(other / "discovery_graph.json")
    (run / "locale.json").symlink_to(other / "locale.json")

    assert path_unless_linked(run, "html") is None
    assert path_unless_linked(run / "screenshots", "01_home.png") is None
    assert write_text_unless_linked(run / "html", "home.html", "<p>ours</p>") is False
    write_graph(run, [{
        "url": "http://shop.test/", "slug": "home", "page_type": "home", "auth": False,
        "title": "Home", "status": 200, "buttons": [], "links": [], "inputs": [], "forms": [],
        "itemLinks": {"links": [], "selector": ""},
    }])
    write_locale(run, {"currency": "USD"})
    assert (other / "home.html").read_text(encoding="utf-8") == secret
    assert (other / "01_home.png").read_bytes() == b"tenant-b-only-page"
    assert json.loads((other / "discovery_graph.json").read_text(encoding="utf-8"))["secret"] == secret
    assert json.loads((other / "locale.json").read_text(encoding="utf-8"))["secret"] == secret

    own = tmp_path / "own"
    own.mkdir()
    saved = path_unless_linked(own, "note.txt")
    assert saved == own / "note.txt"
    assert write_text_unless_linked(own, "note.txt", "ours") is True
    assert (own / "note.txt").read_text(encoding="utf-8") == "ours"


def test_a_crawl_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.agents.discovery as discovery

    secret = b"tenant-b-only-crawl"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)

    def explode(*_args, **_kwargs):
        raise AssertionError("the browser started")

    monkeypatch.setattr(discovery, "sync_playwright", explode)
    monkeypatch.setattr(discovery.settings, "discovery_only", True)
    refused = discovery.discovery_agent({
        "url": "https://shop.test/", "run_dir": str(linked / "run"), "site_key": "shop", "log": [],
    })
    assert refused["app_map"] == [] and "link" in refused["log"][-1]
    assert not (nested / "screenshots").exists()
    assert (nested / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    real.mkdir()
    try:
        discovery.discovery_agent({
            "url": "https://shop.test/", "run_dir": str(real), "site_key": "shop", "log": [],
        })
    except AssertionError as exc:
        assert str(exc) == "the browser started"
    else:
        raise AssertionError("the real crawl did not reach the browser")
    shots = real / "screenshots"
    assert shots.is_dir() and not shots.is_symlink()
    assert list(shots.iterdir()) == []
    assert (nested / "keep.txt").read_bytes() == secret
