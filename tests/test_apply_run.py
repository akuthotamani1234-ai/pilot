"""The blueprint rules run against a finished run, and the listing sample stays put."""
import json

from backend.apply_run import apply_run, write_applied
from backend.swarm import choose_listing


def test_the_listing_sample_is_not_changed_by_applying_the_rules():
    chosen, skipped = choose_listing(
        ["https://shop.example/checkout", "https://shop.example/one", "https://shop.example/two"],
        2,
    )
    assert chosen == ["https://shop.example/one", "https://shop.example/two"]
    assert skipped[0][0].endswith("/checkout")


def test_a_finished_run_applies_every_rule_and_keeps_its_verdict(tmp_path):
    (tmp_path / "planted.json").write_text(json.dumps([{"id": "price"}, {"id": "tax"}]), encoding="utf-8")
    (tmp_path / "locale.json").write_text(json.dumps({
        "observed": {"language": "en", "currency": "INR", "date_format": "dd/mm/yyyy", "tax": "5", "offered": True},
        "expected": {"language": "en", "currency": "INR", "date_format": "dd/mm/yyyy", "tax": "5", "offered": True},
    }), encoding="utf-8")
    (tmp_path / "journeys.json").write_text(json.dumps([{
        "id": "find-saree", "must_match": False,
        "steps": {"web": ["search", "open"], "android": ["search", "filter"]},
    }]), encoding="utf-8")
    (tmp_path / "api_spec.json").write_text(json.dumps(
        {"operations": [{"method": "GET", "path": "/cart", "workflow": "cart", "fields": ["id"]}]}), encoding="utf-8")
    (tmp_path / "api_spec_previous.json").write_text(json.dumps(
        {"operations": [{"method": "GET", "path": "/cart", "workflow": "cart", "fields": ["id", "total"]}]}),
        encoding="utf-8")
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "note.json").write_text(json.dumps({"version": "1", "notes": ["saree copy"]}), encoding="utf-8")
    (plugins / "bad.json").write_text(json.dumps({"version": "1", "disable": ["pay"]}), encoding="utf-8")
    state = {
        "run_dir": str(tmp_path),
        "run_id": "run-1",
        "environment": "staging",
        "verdict": "Ready with Risks",
        "dependency_fault": "inventory",
        "dependency_permitted": True,
        "requirements": "https://shop.example/wishlist",
        "crawl": {"swarm": {"sample": 3}, "not_visited": ["https://shop.example/missed"], "blocked_requests": []},
        "app_map": [{"url": "https://shop.example/saree", "status": 200, "depth": 1,
                     "mobile_only": [], "itemLinks": {"links": [{}, {}, {}]}}],
        "roles": {"shopper": {"pages": {"https://shop.example/orders": "denied"}, "login": "session_expired"}},
        "failures": [{"id": "price", "nodeid": "t::one", "test": "test_cart", "file": "test_cart.py",
                      "page_url": "https://shop.example/saree", "error": "price changed", "category": "product_defect"}],
        "results": [{"nodeid": "t::one", "status": "failed", "screenshot": "cart.png"}],
        "test_cases": [{"tc_id": "cart-1", "title": "Add to cart", "oracle": "ai", "spec": {"item": "saree"}}],
        "healing_log": [{"proposal": True, "nodeid": "t::one", "original_error": "price changed"}],
        "changes": {"incremental": {"reopen": ["https://shop.example/saree"], "smoke": []}},
    }
    applied = apply_run(state, root=tmp_path)
    assert applied["sample_unchanged"] is True and applied["sample"] == 3
    assert applied["locale"]["sample"] == 3 and applied["locale"]["checked"] is True
    assert applied["explore"]["next"][0]["url"].endswith("/saree")
    assert applied["coverage"]["unknown"] == ["https://shop.example/wishlist"]
    assert applied["oracle"][0]["ok"] is False
    assert applied["oracle"][0]["assertion"]["accepted"] is False
    assert applied["oracle"][0]["decision"]["verdict"] == "needs_review"
    assert applied["lifecycle"]["cleanup"]["complete"] is True
    assert applied["healing_policy"]["gate_e_complete"] is False
    assert applied["device_matrix"]["complete"] is False
    assert "web.desktop" in applied["device_matrix"]["verified"]
    assert "web.phone" in applied["device_matrix"]["verified"]
    assert "android.emulator" in applied["device_matrix"]["unverified"]
    assert applied["swarm"]["gate_b_complete"] is False
    assert applied["swarm"]["ran"] is True
    assert (tmp_path / "swarm_evidence.json").is_file()
    assert (tmp_path / "device_matrix.json").is_file()
    assert (tmp_path / "device_matrix_evidence.json").is_file()
    assert applied["portfolios"]["complete"] is False
    assert "locale" in applied["portfolios"]["passed"]
    assert applied["enterprise"]["gate_g_complete"] is False
    assert applied["ops"]["gate_h_complete"] is False
    assert applied["discovery_graph"]["gate_a_complete"] is False
    assert applied["discovery_graph"]["counts"]["nodes"] >= 1
    assert (tmp_path / "discovery_graph.json").is_file()
    assert (tmp_path / "portfolio_gates.json").is_file()
    assert (tmp_path / "surface_coverage.json").is_file()
    assert (tmp_path / "oracle_decisions.json").is_file()
    assert (tmp_path / "lifecycle.json").is_file()
    assert (tmp_path / "healing_policy.json").is_file()
    assert (tmp_path / "visual.json").is_file()
    assert applied["surfaces"]["gate_a_surfaces_complete"] is False
    assert applied["sessions"]["roles"]["shopper"]["state"] == "session_expired"
    assert "password" not in json.dumps(applied["sessions"])
    assert applied["environment"]["payment_blocked"] is True
    assert applied["environment"]["controls"]["fixed_clock"] is True
    assert applied["replay"][0]["replay"]["ran"] is True
    assert applied["mutation"]["missed"] == ["tax"]
    assert applied["journeys"][0]["status"] == "reported"
    assert applied["schema"]["trust_broken"] is True
    assert applied["dependency"]["injected"] is True
    assert applied["review"][0]["apply"] is False
    assert applied["trends"]["verdict"] == "Ready with Risks"
    assert applied["evaluation"]["model_change_allowed"] is True
    names = {row["file"]: row["accepted"] for row in applied["plugins"]}
    assert names["note.json"] is True and names["bad.json"] is False
    assert applied["incremental"]["reopen"] == ["https://shop.example/saree"]


def test_apply_run_refreshes_a_blocked_oracle_after_contract_design(tmp_path):
    url = "https://shop.example/quote"
    (tmp_path / "swarm_work.json").write_text(json.dumps([{
        "url": url, "status": 200, "summary": "Quote total displayed",
    }]), encoding="utf-8")
    (tmp_path / "test_cases.json").write_text(json.dumps([{
        "tc_id": "quote-total",
        "kind": "contract",
        "generation_source": "contract",
        "url": url,
        "expected": "Displayed total equals quantity times price",
    }]), encoding="utf-8")
    (tmp_path / "swarm_evidence.json").write_text(json.dumps({
        "ran": True,
        "run_id": "run-oracle",
        "tasks": [{"role": "oracle", "url": url, "status": "blocked", "error_class": "oracle_missing"}],
    }), encoding="utf-8")

    applied = apply_run({
        "run_dir": str(tmp_path), "run_id": "run-oracle", "environment": "test", "verdict": "Ready",
        "crawl": {}, "app_map": [{"url": url, "status": 200, "depth": 0}], "failures": [], "results": [],
        "test_cases": [], "healing_log": [], "changes": {},
    }, root=tmp_path)

    oracle = next(task for task in applied["swarm"]["tasks"] if task["role"] == "oracle")
    assert applied["swarm"]["run_id"] == "run-oracle"
    assert oracle["status"] == "blocked"
    assert applied["swarm"]["report_oracle"]["assertion"]["requirement_id"] == "quote-total"
    assert not (tmp_path / "swarm_queue.sqlite").exists()


def test_apply_run_indexes_tenant_when_env_set(tmp_path, monkeypatch):
    import backend.tenancy_store as ts

    monkeypatch.setenv("QPILOT_TENANT_ID", "t-apply")
    monkeypatch.setattr(ts, "DEFAULT_DB", tmp_path / "tenancy.sqlite")
    state = {
        "run_dir": str(tmp_path / "run-tenant"),
        "source": "https://shop.example/",
        "verdict": "Ready",
        "crawl": {},
        "app_map": [],
        "failures": [],
        "results": [],
        "test_cases": [],
        "healing_log": [],
        "changes": {},
    }
    (tmp_path / "run-tenant").mkdir()
    applied = apply_run(state, root=tmp_path)
    assert applied["tenancy"]["tenant_id"] == "t-apply"
    assert applied["tenancy"]["gate_g_complete"] is False
    assert (tmp_path / "run-tenant" / "tenancy_index.json").is_file()
    assert [r["run_id"] for r in ts.list_runs_for_tenant("t-apply", db_path=tmp_path / "tenancy.sqlite")] == [
        "run-tenant"
    ]


def test_applied_rules_do_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("QPILOT_REDIS_URL", raising=False)
    monkeypatch.delenv("QPILOT_TENANT_ID", raising=False)
    secret = b"tenant-b-only-rules"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    (nested / "qx_applied.json").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    state = {"run_id": "linked", "verdict": "Ready", "app_map": [], "failures": [], "results": [],
             "test_cases": [], "healing_log": [], "crawl": {}, "changes": {}, "log": []}
    applied = write_applied(dict(state, run_dir=str(linked / "run")))
    missing = write_applied(dict(state, run_dir=str(linked / "fresh")))
    assert applied["trends"]["verdict"] == "Ready"
    assert missing["trends"]["verdict"] == "Ready"
    assert not (other / "fresh").exists()
    assert not (nested / "portfolio_gates.json").exists()
    assert (nested / "qx_applied.json").read_bytes() == secret
    assert (nested / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    real.mkdir()
    written = write_applied(dict(state, run_dir=str(real), run_id="real"))
    saved = real / "qx_applied.json"
    assert saved.is_file() and not saved.is_symlink()
    assert secret not in saved.read_bytes()
    assert written["trends"]["verdict"] == "Ready"
    assert (nested / "keep.txt").read_bytes() == secret


def test_applied_rules_do_not_follow_a_link_into_another_run(tmp_path):
    secret = "tenant-b-only-rules"
    other = tmp_path / "other"
    other.mkdir()
    names = ("qx_applied.json", "portfolio_gates.json", "swarm_evidence.json", "a11y_page.json",
             "lifecycle.json", "oracle_decisions.json", "summary.json")
    for name in names:
        (other / name).write_text(json.dumps({"secret": secret}), encoding="utf-8")
    state = {"run_id": "linked", "verdict": "Ready", "app_map": [], "failures": [], "results": [],
             "test_cases": [], "healing_log": [], "crawl": {}, "changes": {}}

    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    applied = write_applied(dict(state, run_dir=str(linked)))
    assert applied["trends"]["verdict"] == "Ready"
    for name in names:
        assert json.loads((other / name).read_text(encoding="utf-8"))["secret"] == secret
    assert not (other / "swarm_queue.sqlite").exists()

    real = tmp_path / "real"
    real.mkdir()
    for name in ("qx_applied.json", "portfolio_gates.json", "swarm_evidence.json", "a11y_page.json", "lifecycle.json"):
        (real / name).symlink_to(other / name)
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    (sibling / "summary.json").symlink_to(other / "summary.json")
    written = write_applied(dict(state, run_dir=str(real), run_id="real"))
    assert written["trends"]["verdict"] == "Ready"
    for name in ("qx_applied.json", "portfolio_gates.json", "swarm_evidence.json", "a11y_page.json", "lifecycle.json", "summary.json"):
        assert json.loads((other / name).read_text(encoding="utf-8"))["secret"] == secret
    saved = json.loads((real / "oracle_decisions.json").read_text(encoding="utf-8"))
    assert secret not in json.dumps(saved)
    assert (real / "oracle_decisions.json").is_file() and not (real / "oracle_decisions.json").is_symlink()
