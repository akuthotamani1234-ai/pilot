"""Regression: Studio "Run the same tests again" must prefer that run's scripts."""
from __future__ import annotations

import json
import sys

import pytest

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


def test_a_saved_baseline_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-script"
    baseline = tmp_path / "baseline"
    monkeypatch.setattr(settings, "runs_dir", tmp_path / "runs")
    monkeypatch.setattr(settings, "baseline_dir", baseline)
    other = baseline / "other"
    (other / "tests").mkdir(parents=True)
    (other / "tests" / "test_secret.py").write_text(f"SECRET = {secret!r}\n", encoding="utf-8")
    (other / "test_cases.json").write_text(json.dumps([{"id": secret}]), encoding="utf-8")
    (other / "meta.json").write_text(json.dumps({"origin": secret}), encoding="utf-8")
    (other / "keep.txt").write_text(secret, encoding="utf-8")
    site = baseline / "shop.test"
    site.mkdir()
    (site / "tests").symlink_to(other / "tests", target_is_directory=True)
    (site / "test_cases.json").write_text(json.dumps([{"id": "home-own"}]), encoding="utf-8")
    refused = saved_tests("shop.test")
    assert refused is None
    assert (other / "tests" / "test_secret.py").read_text(encoding="utf-8") == f"SECRET = {secret!r}\n"
    assert not (other / "tests" / "test_new.py").exists()
    assert (other / "keep.txt").read_text(encoding="utf-8") == secret

    (site / "tests").unlink()
    (site / "tests").mkdir()
    (site / "tests" / "test_home.py").write_text("MARKER = 'home-own'\n", encoding="utf-8")
    (site / "test_cases.json").unlink()
    (site / "test_cases.json").symlink_to(other / "test_cases.json")
    refused_cases = saved_tests("shop.test")
    assert refused_cases is None
    assert (other / "test_cases.json").read_text(encoding="utf-8") == json.dumps([{"id": secret}])
    assert not (site / "fresh").exists()

    (site / "test_cases.json").unlink()
    (site / "test_cases.json").write_text(json.dumps([{"id": "home-own"}]), encoding="utf-8")
    (site / "meta.json").symlink_to(other / "meta.json")
    (site / "tests" / "test_secret.py").symlink_to(other / "tests" / "test_secret.py")
    got = saved_tests("shop.test")
    assert got is not None
    assert got["cases"] == [{"id": "home-own"}]
    assert {f.name for f in got["files"]} == {"test_home.py"}
    assert "home-own" in got["files"][0].read_text(encoding="utf-8")
    assert got["meta"] == {}
    assert secret not in got["files"][0].read_text(encoding="utf-8")
    assert (other / "meta.json").read_text(encoding="utf-8") == json.dumps({"origin": secret})
    assert (other / "keep.txt").read_text(encoding="utf-8") == secret


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


def _index(monkeypatch, tmp_path):
    import backend.tenancy_store as tenancy
    db = tmp_path / "tenancy.sqlite"
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    tenancy.upsert_tenant("t1", "One", db_path=db)
    tenancy.upsert_tenant("t2", "Two", db_path=db)
    tenancy.index_run("run-a", "t1", source="https://shop.test", verdict="Ready", db_path=db)
    tenancy.index_run("run-b", "t2", source="https://shop.test", verdict="Ready", db_path=db)
    return tenancy


def test_a_recheck_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    from backend.recheck import recheck

    secret = b"tenant-b-only-recheck"
    other = tmp_path / "other"
    nested = other / "run"
    (nested / "generated_tests").mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    (nested / "recheck.json").write_bytes(secret)
    (nested / ".private").mkdir()
    (nested / ".private" / "auth.json").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    refused = recheck(linked / "run", ["test_home.py::test_home"])
    assert "link" in refused["note"]
    assert refused["results"] == {}
    assert (nested / "recheck.json").read_bytes() == secret
    assert (nested / ".private" / "auth.json").read_bytes() == secret
    assert (nested / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    (real / "generated_tests").mkdir(parents=True)
    monkeypatch.setattr("backend.agents.executor._run_pytest", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "backend.agents.executor._read",
        lambda _out: [{"nodeid": "test_home.py::test_home", "outcome": "passed"}],
    )
    own = recheck(real, ["test_home.py::test_home"])
    written = (real / "recheck.json").read_bytes()
    assert b"test_home.py::test_home" in written and b"fixed" in written and secret not in written
    assert own["results"]["test_home.py::test_home"]["verdict"] == "fixed"
    assert (nested / "keep.txt").read_bytes() == secret
    assert (nested / ".private" / "auth.json").read_bytes() == secret


def test_recheck_does_not_follow_a_link_or_another_tenant(monkeypatch, tmp_path, capsys):
    import main as cli
    from backend.recheck import recheck

    runs = tmp_path / "runs"
    monkeypatch.setattr(settings, "runs_dir", runs)
    _index(monkeypatch, tmp_path)
    other = runs / "run-b"
    (other / "generated_tests").mkdir(parents=True)
    (other / "generated_tests" / "test_secret.py").write_text("def test_secret():\n    assert True\n", encoding="utf-8")
    secret = "tenant-b-only-failure"
    (other / "failures.json").write_text(json.dumps([
        {"id": 1, "nodeid": "test_secret.py::test_secret", "category": "product_defect", "note": secret},
    ]), encoding="utf-8")
    (other / "recheck.json").write_text("{}\n", encoding="utf-8")
    link = runs / "run-link"
    link.symlink_to(other, target_is_directory=True)

    out = recheck(link, ["test_secret.py::test_secret"])
    assert out["results"] == {}
    assert "link" in out["note"]
    assert (other / "recheck.json").read_text(encoding="utf-8") == "{}\n"

    linked_file = runs / "run-a"
    (linked_file / "generated_tests").mkdir(parents=True)
    target = tmp_path / "recheck-target.json"
    payload = json.dumps({"secret": secret}) + "\n"
    target.write_text(payload, encoding="utf-8")
    (linked_file / "recheck.json").symlink_to(target)
    out = recheck(linked_file, ["test_secret.py::test_secret"])
    assert out["results"] == {}
    assert target.read_text(encoding="utf-8") == payload

    monkeypatch.setenv("QPILOT_TENANT_ID", "t1")
    monkeypatch.setattr(sys, "argv", ["main.py", "--recheck", "run-b", "test_secret.py::test_secret"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    printed = capsys.readouterr().out
    assert secret not in printed
    assert "another tenant" in printed
    assert (other / "recheck.json").read_text(encoding="utf-8") == "{}\n"


def test_merge_does_not_read_another_tenants_summary(monkeypatch, tmp_path, capsys):
    from backend.merge import merge_runs

    runs = tmp_path / "runs"
    monkeypatch.setattr(settings, "runs_dir", runs)
    _index(monkeypatch, tmp_path)
    secret = "tenant-b-only-verdict"
    for name, verdict in (("run-a", "Ready"), ("run-b", secret)):
        folder = runs / name
        folder.mkdir(parents=True)
        (folder / "summary.json").write_text(json.dumps({
            "verdict": verdict, "pages": 3, "reasons": ["x"],
            "coverage_card": {"pages": {"found": 3}},
        }), encoding="utf-8")
    linked = runs / "run-link"
    linked.symlink_to(runs / "run-b", target_is_directory=True)

    monkeypatch.setenv("QPILOT_TENANT_ID", "t1")
    out = merge_runs([runs / "run-a", runs / "run-b", linked], runs)
    summary = (out / "summary.json").read_text(encoding="utf-8")
    assert "run-a" in summary
    assert secret not in summary
    assert "run-b" not in summary
    assert "run-link" not in summary
    printed = capsys.readouterr().out
    assert secret not in printed


def test_approve_and_replay_do_not_follow_a_link(tmp_path, monkeypatch):
    from backend.replay_pack import saved_replays
    from backend.visual import approve, keep_new_looks

    runs = tmp_path / "runs"
    monkeypatch.setattr(settings, "runs_dir", runs)
    monkeypatch.setattr(settings, "baseline_dir", tmp_path / "baseline")
    secret = "tenant-b-only-look"
    other = runs / "run-b"
    other.mkdir(parents=True)
    visual = other / "visual.json"
    visual.write_text(json.dumps({
        "pages": [{"status": "changed", "key": "home", "title": "Home", "capture": "cap.json"}],
        "counts": {"changed": 1},
        "secret": secret,
    }), encoding="utf-8")
    (other / "run_args.json").write_text(json.dumps({"site_key": "shop.test"}), encoding="utf-8")
    own = runs / "run-a"
    own.mkdir()
    (own / "visual.json").symlink_to(visual)
    (own / "run_args.json").write_text(json.dumps({"site_key": "shop.test"}), encoding="utf-8")
    before = visual.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="link"):
        approve(own)
    assert visual.read_text(encoding="utf-8") == before
    assert keep_new_looks(own, "shop.test") == 0
    assert visual.read_text(encoding="utf-8") == before

    replay = other / "qx_replay.json"
    replay.write_text(json.dumps({"packages": [{"id": secret, "replay": {"ran": True}}]}), encoding="utf-8")
    (own / "qx_replay.json").symlink_to(replay)
    assert saved_replays(own) == []
    rows = saved_replays(other)
    assert rows and rows[0]["id"] == secret


def test_resume_does_not_read_another_tenants_run(monkeypatch, tmp_path, capsys):
    import main as cli

    runs = tmp_path / "runs"
    monkeypatch.setattr(settings, "runs_dir", runs)
    _index(monkeypatch, tmp_path)
    secret = "https://tenant-b-only.example/secret"
    other = runs / "run-b"
    other.mkdir(parents=True)
    (other / "run_args.json").write_text(json.dumps({
        "source": secret, "url": secret, "settings": {}, "code_project": False,
    }), encoding="utf-8")
    link = runs / "run-link"
    link.symlink_to(other, target_is_directory=True)
    monkeypatch.setattr(cli, "run_pipeline", lambda *a, **k: (_ for _ in ()).throw(AssertionError("resumed")))

    monkeypatch.setattr(sys, "argv", ["main.py", "--resume", "run-link"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert secret not in capsys.readouterr().out

    monkeypatch.setenv("QPILOT_TENANT_ID", "t1")
    monkeypatch.setattr(sys, "argv", ["main.py", "--resume", "run-b"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    printed = capsys.readouterr().out
    assert secret not in printed
    assert "another tenant" in printed
