"""The live rules run in order and leave the product sample unchanged."""
import json

from backend.run_rules import apply_analysis, apply_discovery, apply_execution, apply_report, plugin_cases


def test_each_stage_stores_its_rules_and_a_plugin_can_add_an_assertion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / "price.json").write_text(json.dumps({
        "version": "1", "assertions": ["the price is shown"], "disable": [],
    }), encoding="utf-8")
    (tmp_path / "planted.json").write_text(json.dumps([{"id": "price"}]), encoding="utf-8")
    state = {
        "run_dir": str(tmp_path), "run_id": "shop", "site_key": "", "environment": "test",
        "roles": {"buyer": {"login": "success", "pages": {"https://shop.example/saree": "ok"}}},
        "app_map": [{"url": "https://shop.example/saree", "itemLinks": {"links": [{}, {}, {}]}}],
        "crawl": {"swarm": {"sample": 2, "workers": 1}},
    }
    found = apply_discovery(state)
    assert list(found) == ["sessions", "environment", "locale", "schema", "plugins"]
    assert found["sessions"]["roles"]["buyer"]["vault_ref"] == "vault:buyer"
    assert found["environment"]["blocked"]["pay"]["blocked"] is True
    assert found["locale"]["sample"] == 2
    assert found["plugins"][0]["accepted"] is True
    assert plugin_cases()[0]["expected"] == "the price is shown"
    executed = apply_execution(state)
    assert executed["lifecycle"]["prepared"][0][0]["source"] == "synthetic"
    assert executed["dependency"]["injected"] is False
    analyzed = apply_analysis(state, [{"id": "price", "test": "see the price", "error": "price changed",
                                       "screenshot": "price.png", "page_url": "https://shop.example/saree"}])
    assert analyzed["mutation"]["caught"] == ["price"]
    assert analyzed["replay"]["packages"][0]["replay"]["ran"] is True
    reported = apply_report(state, verdict="pass", failures=[], results=[{"outcome": "passed"}])
    assert reported["trends"]["verdict"] == "pass"
    assert reported["evaluation"]["model_change_allowed"] is True
    stored = json.loads((tmp_path / "qx_live.json").read_text(encoding="utf-8"))
    assert stored["order"][0] == "sessions"
    assert "trends" in stored
