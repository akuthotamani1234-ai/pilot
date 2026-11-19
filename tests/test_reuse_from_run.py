"""Regression: Studio "Run the same tests again" must prefer that run's scripts."""
from __future__ import annotations

import json

from backend.agents.change_detection import saved_tests
from backend.config import settings


def test_saved_tests_prefers_from_run(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    baseline = tmp_path / "baseline"
    monkeypatch.setattr(settings, "runs_dir", runs)
    monkeypatch.setattr(settings, "baseline_dir", baseline)

    site = "example.com"
    # baseline has older scripts
    btests = baseline / site / "tests"
    btests.mkdir(parents=True)
    (btests / "test_old.py").write_text("def test_old():\n    assert True\n", encoding="utf-8")
    (baseline / site / "test_cases.json").write_text("[]", encoding="utf-8")
    (baseline / site / "meta.json").write_text(json.dumps({"date": "old", "origin": "http://example.com"}), encoding="utf-8")

    run = "run-20260101-abc"
    g = runs / run / "generated_tests"
    g.mkdir(parents=True)
    (g / "test_login.py").write_text("def test_login():\n    assert True\n", encoding="utf-8")
    (g / "helpers.py").write_text("X = 1\n", encoding="utf-8")
    (runs / run / "test_cases.json").write_text(json.dumps([{"id": "c1"}]), encoding="utf-8")
    (runs / run / "summary.json").write_text(json.dumps({"url": "http://example.com/app"}), encoding="utf-8")

    got = saved_tests(site, from_run=run)
    assert got is not None
    names = {f.name for f in got["files"]}
    assert "test_login.py" in names
    assert "helpers.py" in names
    assert "test_old.py" not in names
    assert got["meta"]["source_run"] == run
    assert got["meta"]["origin"] == "http://example.com/app"
    assert got["cases"] == [{"id": "c1"}]


def test_saved_tests_falls_back_to_baseline(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    baseline = tmp_path / "baseline"
    monkeypatch.setattr(settings, "runs_dir", runs)
    monkeypatch.setattr(settings, "baseline_dir", baseline)
    site = "example.com"
    btests = baseline / site / "tests"
    btests.mkdir(parents=True)
    (btests / "test_old.py").write_text("def test_old():\n    assert True\n", encoding="utf-8")
    (baseline / site / "test_cases.json").write_text("[]", encoding="utf-8")
    (baseline / site / "meta.json").write_text(json.dumps({"date": "old", "origin": "http://example.com"}), encoding="utf-8")

    got = saved_tests(site, from_run="missing-run")
    assert got is not None
    assert got["files"][0].name == "test_old.py"


def test_saved_tests_does_not_follow_a_link_into_another_run(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    monkeypatch.setattr(settings, "runs_dir", runs)
    monkeypatch.setattr(settings, "baseline_dir", tmp_path / "baseline")
    real = runs / "run-b"
    tests = real / "generated_tests"
    tests.mkdir(parents=True)
    (tests / "test_secret.py").write_text("SECRET = 'tenant-b'\n", encoding="utf-8")
    (tests / "helpers.py").write_text("SECRET = 'helper'\n", encoding="utf-8")
    (real / "test_cases.json").write_text(json.dumps([{"id": "secret"}]), encoding="utf-8")
    (real / "summary.json").write_text(json.dumps({"url": "https://b.test/secret"}), encoding="utf-8")
    (runs / "run-a").symlink_to(real, target_is_directory=True)
    assert saved_tests("shop.test", from_run="run-a") is None
    assert saved_tests("shop.test", from_run="..") is None

    own = runs / "run-own"
    own.mkdir()
    (own / "generated_tests").symlink_to(tests, target_is_directory=True)
    (own / "test_cases.json").write_text("[]", encoding="utf-8")
    assert saved_tests("shop.test", from_run="run-own") is None

    mixed = runs / "run-mix"
    mixed_tests = mixed / "generated_tests"
    mixed_tests.mkdir(parents=True)
    (mixed_tests / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (mixed_tests / "test_secret.py").symlink_to(tests / "test_secret.py")
    (mixed_tests / "helpers.py").symlink_to(tests / "helpers.py")
    (mixed / "test_cases.json").write_text(json.dumps([{"id": "ok"}]), encoding="utf-8")
    (mixed / "summary.json").symlink_to(real / "summary.json")
    got = saved_tests("shop.test", from_run="run-mix")
    assert got is not None
    assert {f.name for f in got["files"]} == {"test_ok.py"}
    assert "SECRET" not in got["files"][0].read_text(encoding="utf-8")
    assert got["cases"] == [{"id": "ok"}]
    assert got["meta"]["origin"] == ""


def test_saved_tests_does_not_copy_another_tenants_run(tmp_path, monkeypatch):
    import backend.tenancy_store as tenancy

    runs = tmp_path / "runs"
    db = tmp_path / "tenancy.sqlite"
    monkeypatch.setattr(settings, "runs_dir", runs)
    monkeypatch.setattr(settings, "baseline_dir", tmp_path / "baseline")
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    monkeypatch.setenv("QPILOT_TENANT_ID", "t1")

    def write_run(name, marker):
        folder = runs / name / "generated_tests"
        folder.mkdir(parents=True)
        (folder / "test_case.py").write_text(f"MARKER = {marker!r}\n", encoding="utf-8")
        (runs / name / "test_cases.json").write_text(json.dumps([{"id": marker}]), encoding="utf-8")

    write_run("run-a", "mine")
    write_run("run-b", "theirs")
    tenancy.upsert_tenant("t1", "One", db_path=db)
    tenancy.upsert_tenant("t2", "Two", db_path=db)
    tenancy.index_run("run-a", "t1", source="https://shop.test", verdict="Ready", db_path=db)
    tenancy.index_run("run-b", "t2", source="https://shop.test", verdict="Ready", db_path=db)

    stolen = saved_tests("shop.test", from_run="run-b")
    assert stolen is None
    own = saved_tests("shop.test", from_run="run-a")
    assert own is not None
    assert own["cases"] == [{"id": "mine"}]
    assert "theirs" not in own["files"][0].read_text(encoding="utf-8")


def test_a_launch_does_not_reuse_another_tenants_run(monkeypatch, tmp_path):
    import backend.tenancy_store as tenancy
    from backend import server

    db = tmp_path / "tenancy.sqlite"
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    monkeypatch.setattr(server, "check_target", lambda url, resolve=True: url)
    tenancy.upsert_tenant("t1", "One", db_path=db)
    tenancy.upsert_tenant("t2", "Two", db_path=db)
    tenancy.upsert_principal("admin-1", "t1", "a@ex.test", "admin", db_path=db)
    tenancy.index_run("run-a", "t1", source="https://shop.test", verdict="Ready", db_path=db)
    tenancy.index_run("run-b", "t2", source="https://shop.test", verdict="Ready", db_path=db)
    captured = {}

    class Proc:
        pid = 7
        returncode = 0
        stdout = iter(())

        def poll(self):
            return 0

        def wait(self):
            return 0

    def fake_popen(_cmd, **kwargs):
        captured["reuse"] = kwargs["env"].get("REUSE_FROM_RUN")
        captured["tenant"] = kwargs["env"].get("QPILOT_TENANT_ID")
        return Proc()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)
    kept = dict(server.jobs)
    server.jobs.clear()
    try:
        server._launch_run(server.RunRequest(
            source="https://shop.test/", authorized=True, llm_provider="none",
            reuse_tests=True, reuse_from_run="run-b",
        ), "admin-1")
        assert captured["tenant"] == "t1"
        assert captured.get("reuse") in (None, "")
        server.jobs.clear()
        server._launch_run(server.RunRequest(
            source="https://shop.test/", authorized=True, llm_provider="none",
            reuse_tests=True, reuse_from_run="run-a",
        ), "admin-1")
        assert captured["reuse"] == "run-a"
    finally:
        server.jobs.clear()
        server.jobs.update(kept)
