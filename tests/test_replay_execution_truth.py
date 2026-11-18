"""Regression checks for Qpilot X replay evidence versus actual execution."""
from backend import replay_pack


def test_replay_package_is_evidence_not_execution():
    package = replay_pack.make_package(
        environment="test", build="sha123", browser="chromium", seed=42,
        starting_state={"url": "https://example.test"}, test_data={"item": "A"},
        actions=[{"type": "click", "target": "cart"}],
        network=[{"url": "https://example.test/api/cart", "status": 200}],
        screenshots=["before.png"], assertion={"expected": "cart visible"},
    )
    assert package["complete"]
    result = replay_pack.replay(package)
    assert result["ran"] is True  # historical compatibility: package is replay-ready
    assert result["executed"] is False
    assert result["evidence_ready"] is True


def test_missing_evidence_blocks_replay():
    result = replay_pack.replay({"actions": [{"type": "click"}]})
    assert result["ran"] is False
    assert "assertion" in result["missing"]


def test_runner_with_no_results_is_not_reported_as_executed(tmp_path, monkeypatch):
    (tmp_path / "generated_tests").mkdir()
    monkeypatch.setattr(replay_pack, "replay_tests", lambda _p: ["test_shop.py::test_cart"])
    import backend.recheck
    monkeypatch.setattr(backend.recheck, "recheck", lambda _p, _n: {"results": {}, "note": "runner failed"})
    result = replay_pack.run_saved(tmp_path)
    assert result["ran"] is False
    assert "runner failed" in result["reason"]


def test_runner_with_not_run_results_is_not_reported_as_executed(tmp_path, monkeypatch):
    (tmp_path / "generated_tests").mkdir()
    monkeypatch.setattr(replay_pack, "replay_tests", lambda _p: ["test_shop.py::test_cart"])
    import backend.recheck
    monkeypatch.setattr(backend.recheck, "recheck", lambda _p, _n: {
        "results": {"test_shop.py::test_cart": {"outcome": "not run"}}
    })
    assert replay_pack.run_saved(tmp_path)["ran"] is False


def test_runner_with_actual_failure_counts_as_executed(tmp_path, monkeypatch):
    (tmp_path / "generated_tests").mkdir()
    monkeypatch.setattr(replay_pack, "replay_tests", lambda _p: ["test_shop.py::test_cart"])
    import backend.recheck
    monkeypatch.setattr(backend.recheck, "recheck", lambda _p, _n: {
        "results": {"test_shop.py::test_cart": {"outcome": "failed"}}
    })
    result = replay_pack.run_saved(tmp_path)
    assert result["ran"] is True
    assert result["results"]["test_shop.py::test_cart"]["outcome"] == "failed"
