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
    assert executed["lifecycle"]["prepared"][0][0]["state"] == "ready"
    assert executed["lifecycle"]["cleaned"] == []
    finished = apply_execution(state, finish=True)
    assert finished["lifecycle"]["prepared"][0][0]["state"] == "cleaned"
    assert finished["lifecycle"]["cleaned"]
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


def test_an_excel_workbook_does_not_follow_a_link_into_another_folder(tmp_path):
    from openpyxl import load_workbook

    from backend.excel import write_workbook

    secret = b"tenant-b-only-excel"
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_bytes(secret)
    (other / "test_cases.xlsx").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    assert write_workbook(linked / "run", [{"id": "see-price", "title": "Price is shown", "page": "home"}]) is None
    assert not (other / "run").exists()
    assert (other / "test_cases.xlsx").read_bytes() == secret
    assert (other / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    real.mkdir()
    saved = write_workbook(real, [{"id": "see-price", "title": "Price is shown", "page": "home"}])
    assert saved == real / "test_cases.xlsx"
    assert saved.is_file() and not saved.is_symlink()
    book = load_workbook(saved, read_only=True)
    rows = list(book.active.iter_rows(values_only=True))
    book.close()
    assert rows[1][rows[0].index("Test Case")] == "Price is shown"
    assert secret not in saved.read_bytes()
    assert (other / "keep.txt").read_bytes() == secret


def test_generated_scripts_do_not_follow_a_link_into_another_folder(tmp_path):
    from backend.agents.script_generator import script_generator_agent

    secret = b"tenant-b-only-script"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    state = {"run_dir": str(linked / "run"), "app_map": [], "test_cases": [], "url": "https://shop.test", "log": []}
    refused = script_generator_agent(state)
    assert refused["scripts"] == [] and "link" in refused["log"][-1]
    assert not (nested / "generated_tests").exists()
    assert (nested / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    real.mkdir()
    saved = script_generator_agent({**state, "run_dir": str(real), "log": []})
    script = real / "generated_tests" / "conftest.py"
    assert script.is_file() and not script.is_symlink()
    assert secret not in script.read_bytes()
    assert saved["scripts"] == []
    assert (nested / "keep.txt").read_bytes() == secret


def test_a_live_rule_file_does_not_follow_a_link_into_another_folder(tmp_path):
    from backend.run_rules import _store

    secret = b"tenant-b-only-rules"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    (nested / "qx_live.json").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    _store(linked / "run", "environment", {"ok": True})
    _store(linked / "fresh", "environment", {"ok": True})
    assert not (other / "fresh").exists()
    assert not (nested / "qx_environment.json").exists()
    assert (nested / "qx_live.json").read_bytes() == secret
    assert (nested / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    real.mkdir()
    _store(real, "environment", {"ok": True})
    live = json.loads((real / "qx_live.json").read_text(encoding="utf-8"))
    assert live["environment"]["ok"] is True
    assert secret not in (real / "qx_live.json").read_bytes()
    assert secret not in (real / "qx_environment.json").read_bytes()
    assert (nested / "keep.txt").read_bytes() == secret


def test_a_generated_script_does_not_follow_a_link_into_another_run(tmp_path, monkeypatch):
    import backend.tenancy_store as tenancy
    from backend.agents.script_generator import script_generator_agent
    from backend.config import settings
    from backend.excel import write_workbook
    from backend.page_inventory import save_inventory
    from backend.run_rules import _store, trends_for

    monkeypatch.setattr(settings, "reuse_tests", False)
    secret = "tenant-b-only-script"
    other = tmp_path / "other-tests"
    other.mkdir()
    (other / "test_keep.py").write_text(secret, encoding="utf-8")
    (other / "conftest.py").write_text(secret, encoding="utf-8")
    cov = tmp_path / "cov.json"
    cov.write_text(json.dumps({"secret": secret}), encoding="utf-8")
    live = tmp_path / "live.json"
    live.write_text(json.dumps({"secret": secret}), encoding="utf-8")
    book = tmp_path / "book.xlsx"
    book.write_bytes(b"tenant-b-only-script")
    components = tmp_path / "components.json"
    components.write_text(json.dumps({"secret": secret}), encoding="utf-8")

    run = tmp_path / "run-a"
    run.mkdir()
    (run / "generated_tests").symlink_to(other, target_is_directory=True)
    out = script_generator_agent({
        "run_dir": str(run), "app_map": [], "test_cases": [], "url": "https://shop.test", "log": [],
    })
    assert out["scripts"] == []
    assert (other / "test_keep.py").read_text(encoding="utf-8") == secret
    assert (other / "conftest.py").read_text(encoding="utf-8") == secret

    target = tmp_path / "target.py"
    target.write_text(secret, encoding="utf-8")
    own = tmp_path / "own"
    tests = own / "generated_tests"
    tests.mkdir(parents=True)
    (tests / "test_keep.py").symlink_to(target)
    (own / "coverage.json").symlink_to(cov)
    (own / "test_cases.xlsx").symlink_to(book)
    (own / "components.json").symlink_to(components)
    (own / "qx_live.json").symlink_to(live)
    script_generator_agent({
        "run_dir": str(own), "app_map": [], "test_cases": [], "url": "https://shop.test", "log": [],
    })
    assert target.read_text(encoding="utf-8") == secret
    assert json.loads(cov.read_text(encoding="utf-8"))["secret"] == secret
    assert (tests / "conftest.py").is_file() and not (tests / "conftest.py").is_symlink()
    write_workbook(own, [])
    save_inventory(own, [])
    assert book.read_bytes() == b"tenant-b-only-script"
    assert json.loads(components.read_text(encoding="utf-8"))["secret"] == secret
    _store(own, "environment", {"ok": True})
    assert json.loads(live.read_text(encoding="utf-8"))["secret"] == secret

    runs = tmp_path / "runs"
    runs.mkdir()
    linked = runs / "shop.test_20260101_100000"
    linked.mkdir()
    (linked / "summary.json").symlink_to(cov)
    theirs = runs / "shop.test_20260101_110000"
    theirs.mkdir()
    (theirs / "summary.json").write_text(json.dumps({
        "verdict": secret, "qx_areas": [secret],
    }), encoding="utf-8")
    now = runs / "shop.test_20260102_100000"
    now.mkdir()
    db = tmp_path / "tenancy.sqlite"
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    monkeypatch.setenv("QPILOT_TENANT_ID", "t1")
    tenancy.upsert_tenant("t1", "One", db_path=db)
    tenancy.upsert_tenant("t2", "Two", db_path=db)
    tenancy.index_run(now.name, "t1", source="https://shop.test", verdict="Ready", db_path=db)
    tenancy.index_run(theirs.name, "t2", source="https://shop.test", verdict=secret, db_path=db)
    trends = trends_for(
        {"run_dir": str(now), "site_key": ""}, "pass", [], [])
    assert secret not in json.dumps(trends)
