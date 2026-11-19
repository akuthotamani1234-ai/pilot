"""Gate C: durable lifecycle + created.jsonl cleanup confirmation."""
import json

from backend.data_lifecycle import (
    created_jsonl_delete,
    ingest_created,
    load_lifecycle,
    save_lifecycle,
)
from backend.run_rules import lifecycle_for


def test_lifecycle_persists_between_prepare_and_finish(tmp_path):
    state = {"run_dir": str(tmp_path), "environment": "test", "crawl": {"swarm": {"workers": 1}}}
    first = lifecycle_for(state, finish=False)
    assert first["durable"] is True
    assert (tmp_path / "qx_lifecycle_state.json").is_file()
    tag = first["prepared"][0][0]["tag"]

    # Staging test created then deleted a real fixture tag derived from the synthetic plan.
    with (tmp_path / "created.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"what": "account", "tag": f"{tag}-1", "where": "/users", "status": "created"}) + "\n")
        fh.write(json.dumps({"what": "account", "tag": f"{tag}-1", "where": "/users", "status": "deleted"}) + "\n")

    finished = lifecycle_for(state, finish=True)
    assert finished["cleanup"]["complete"] is True
    proofs = [str(row.get("cleanup_proof") or "") for row in finished["cleaned"]]
    assert any(p.startswith("synthetic_unused:") for p in proofs)
    assert any("created.jsonl:deleted:" in p for p in proofs)


def test_a_cleanup_record_does_not_follow_a_link_into_another_run(tmp_path, monkeypatch):
    from backend.agents.executor import _clean_up_again
    from backend.agents.reporter import created_records
    from backend.data_lifecycle import ingest_created, latest_created, load_lifecycle, save_lifecycle

    secret = "tenant-b-only-order"
    other = tmp_path / "other"
    other.mkdir()
    (other / "created.jsonl").write_text(
        json.dumps({"what": "order", "tag": secret, "where": "/orders", "status": "created"}) + "\n",
        encoding="utf-8")
    (other / "qx_lifecycle_state.json").write_text(
        json.dumps({"run_id": "run-b", "environment": "test", "workers": {}, "cases": {}}),
        encoding="utf-8")
    before_summary = json.dumps({"secret": secret})
    (other / "created.json").write_text(before_summary, encoding="utf-8")
    run = tmp_path / "run-a"
    run.mkdir()
    (run / "created.jsonl").symlink_to(other / "created.jsonl")
    (run / "qx_lifecycle_state.json").symlink_to(other / "qx_lifecycle_state.json")
    (run / "created.json").symlink_to(other / "created.json")
    assert latest_created(run) == {}
    life = load_lifecycle(run, run_id="run-a", environment="test")
    assert life.run_id == "run-a"
    assert ingest_created(life, run) == []
    assert secret not in json.dumps(created_records(run))
    assert (other / "created.json").read_text(encoding="utf-8") == before_summary
    save_lifecycle(run, life)
    assert json.loads((other / "qx_lifecycle_state.json").read_text(encoding="utf-8"))["run_id"] == "run-b"
    calls = []
    monkeypatch.setattr("backend.agents.executor._run_pytest", lambda *a, **k: calls.append(a))
    (run / "generated").mkdir()
    (run / "generated" / "test_cleanup.py").write_text("def test_cleanup():\n    pass\n", encoding="utf-8")
    _clean_up_again({"log": []}, run, run / "generated", run / "shots")
    assert calls == []
    assert secret in (other / "created.jsonl").read_text(encoding="utf-8")


def test_a_cleanup_record_does_not_follow_a_link_into_another_folder(tmp_path):
    from backend.agents.discovery import record_created
    from backend.agents.reporter import created_records
    from backend.data_lifecycle import Lifecycle, latest_created, load_lifecycle, save_lifecycle

    secret = b"tenant-b-only-lifecycle"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    (nested / "qx_lifecycle_state.json").write_text(
        json.dumps({"run_id": "run-b", "environment": "test", "workers": {}, "cases": {}}),
        encoding="utf-8")
    (nested / "created.jsonl").write_bytes(
        secret + b"\n")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    save_lifecycle(linked / "run", Lifecycle("run-a", "test"))
    loaded = load_lifecycle(linked / "run", run_id="run-a", environment="test")
    assert loaded.run_id == "run-a"
    assert latest_created(linked / "run") == {}
    assert record_created(linked / "run", "order", "ours", "/orders") is False
    assert created_records(linked / "run")["records"] == []
    assert json.loads((nested / "qx_lifecycle_state.json").read_text(encoding="utf-8"))["run_id"] == "run-b"
    assert (nested / "created.jsonl").read_bytes() == secret + b"\n"
    assert not (nested / "created.json").exists()
    assert (nested / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    real.mkdir()
    saved = save_lifecycle(real, Lifecycle("run-real", "test"))
    assert saved == real / "qx_lifecycle_state.json"
    assert json.loads(saved.read_text(encoding="utf-8"))["run_id"] == "run-real"
    assert secret not in saved.read_bytes()
    assert record_created(real, "account", "ours", "/users") is True
    summary = created_records(real)
    assert summary["created"] == 1
    assert (real / "created.json").is_file() and not (real / "created.json").is_symlink()
    assert secret not in (real / "created.json").read_bytes()
    assert (nested / "keep.txt").read_bytes() == secret


def test_created_jsonl_delete_refuses_uncleared_records(tmp_path):
    with (tmp_path / "created.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"what": "order", "tag": "qa-run-order", "where": "/orders", "status": "created"}) + "\n")
    life = load_lifecycle(tmp_path, run_id="run", environment="test")
    ingest_created(life, tmp_path)
    out = life.cleanup_confirmed(remote_delete=created_jsonl_delete(tmp_path))
    assert out["complete"] is False
    assert out["failed"][0]["reason"].startswith("created.jsonl still created")
    save_lifecycle(tmp_path, life)


def test_an_android_event_does_not_follow_a_link_into_another_folder(tmp_path):
    from backend.android_events import Timeline

    secret = b"tenant-b-only-event"
    other = tmp_path / "other"
    nested = other / "runs" / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    refused = Timeline(linked / "runs" / "run", {"id": "home", "title": "Home"})
    refused.emit("info", "pressed the shop button")
    refused.close()
    missing = Timeline(linked / "runs" / "fresh", {"id": "home", "title": "Home"})
    missing.emit("info", "pressed the shop button")
    missing.close()
    assert not (other / "runs" / "fresh").exists()
    assert list(nested.glob("events.android-*.jsonl")) == []
    assert (nested / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    real.mkdir()
    own = Timeline(real, {"id": "home", "title": "Home"})
    own.emit("info", "pressed the shop button")
    own.close()
    event = next(real.glob("events.android-*.jsonl"))
    text = event.read_bytes()
    assert b"pressed the shop button" in text and secret not in text
    assert (nested / "keep.txt").read_bytes() == secret


def test_a_phase_record_does_not_follow_a_link_into_another_folder(tmp_path):
    from backend.agents.discovery import record_created
    from backend.scheduling import record_phase

    secret = b"tenant-b-only-phase"
    other = tmp_path / "other"
    nested = other / "runs" / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    (nested / "phase_timings.jsonl").write_bytes(secret)
    (nested / "created.jsonl").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    run = linked / "runs" / "run"
    record_phase(run, "discovery", 0, "done")
    assert record_created(run, "order", "shop", "/orders") is False
    record_phase(linked / "runs" / "fresh", "discovery", 0, "done")
    assert record_created(linked / "runs" / "fresh", "order", "shop", "/orders") is False
    assert not (other / "runs" / "fresh").exists()
    assert (nested / "phase_timings.jsonl").read_bytes() == secret
    assert (nested / "created.jsonl").read_bytes() == secret
    assert (nested / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    real.mkdir()
    record_phase(real, "discovery", 0, "done")
    assert record_created(real, "order", "shop-tag", "/orders") is True
    timings = (real / "phase_timings.jsonl").read_bytes()
    created = (real / "created.jsonl").read_bytes()
    assert b"discovery" in timings and secret not in timings
    assert b"shop-tag" in created and secret not in created
    assert (nested / "keep.txt").read_bytes() == secret


def test_a_live_log_does_not_follow_a_link_into_another_run(tmp_path, monkeypatch):
    import os

    from backend import server
    from backend.agents.discovery import record_created
    from backend.android_dynamic import note, reset_notes, set_progress_log
    from backend.android_events import Timeline
    from backend.jscov import append, summary
    from backend.scheduling import record_phase

    secret = "tenant-b-only-live"
    other = tmp_path / "other"
    other.mkdir()
    (other / "jscov").mkdir()
    files = {
        "created.jsonl": secret + "\n",
        "phase_timings.jsonl": secret + "\n",
        "progress.log": secret + "\n",
        "audit.jsonl": secret + "\n",
        "android_results.jsonl": secret + "\n",
        "jscov.json": json.dumps({"secret": secret}),
    }
    for name, text in files.items():
        (other / name).write_text(text, encoding="utf-8")
    (other / "jscov" / "crawl.jsonl").write_text(secret + "\n", encoding="utf-8")
    event_name = f"events.android-{os.getpid()}.jsonl"
    (other / event_name).write_text(secret + "\n", encoding="utf-8")
    monkeypatch.setattr("backend.audit_store.record_audit", lambda **_k: {})
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "main")

    def unchanged():
        for name, text in files.items():
            assert (other / name).read_text(encoding="utf-8") == text
        assert (other / "jscov" / "crawl.jsonl").read_text(encoding="utf-8") == secret + "\n"
        assert (other / event_name).read_text(encoding="utf-8") == secret + "\n"

    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    assert record_created(linked, "order", "tag", "/orders") is False
    append(linked, "crawl", {"https://shop.example/app.js": {"length": 4, "covered": [[0, 1]]}})
    record_phase(linked, "discovery", 0, "done")
    reset_notes()
    set_progress_log(linked / "progress.log")
    note("started the crawl")
    timeline = Timeline(linked, {"id": "c1", "title": "Catalog"})
    timeline.emit("info", "pressed")
    timeline.close()
    monkeypatch.setattr(server, "AUDIT", linked / "audit.jsonl")
    server._audit("start_test", run="linked")
    assert summary(linked, "shop.example") is None
    unchanged()

    real = tmp_path / "real"
    real.mkdir()
    for name in ("created.jsonl", "phase_timings.jsonl", "progress.log", "jscov.json", "android_results.jsonl"):
        (real / name).symlink_to(other / name)
    (real / "jscov").symlink_to(other / "jscov", target_is_directory=True)
    (real / event_name).symlink_to(other / event_name)
    assert record_created(real, "order", "tag", "/orders") is False
    append(real, "crawl", {"https://shop.example/app.js": {"length": 4, "covered": [[0, 1]]}})
    append(real, "../created", {"left": True})
    record_phase(real, "discovery", 0, "done")
    set_progress_log(real / "progress.log")
    note("another line")
    assert summary(real, "shop.example") is None
    timeline = Timeline(real, {"id": "c1", "title": "Catalog"})
    timeline.emit("info", "pressed")
    timeline.close()
    _append = _load_append()
    _append(real, "android_results.jsonl", {"id": "c1"})
    _save = _load_cov_save()
    _save(real, _coverage())
    unchanged()

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    assert record_created(fresh, "order", "qa-1", "/orders") is True
    assert "qa-1" in (fresh / "created.jsonl").read_text(encoding="utf-8")
    append(fresh, "crawl", {"https://shop.example/app.js": {"length": 4, "covered": [[0, 1]]}})
    saved = (fresh / "jscov" / "crawl.jsonl").read_text(encoding="utf-8")
    assert "shop.example" in saved and secret not in saved
    record_phase(fresh, "discovery", 0, "done")
    assert "discovery" in (fresh / "phase_timings.jsonl").read_text(encoding="utf-8")
    set_progress_log(fresh / "progress.log")
    note("fresh line")
    assert "fresh line" in (fresh / "progress.log").read_text(encoding="utf-8")
    timeline = Timeline(fresh, {"id": "c1", "title": "Catalog"})
    timeline.emit("info", "pressed catalog")
    timeline.close()
    event = next(fresh.glob("events.android-*.jsonl"))
    assert event.is_file() and not event.is_symlink()
    assert "pressed catalog" in event.read_text(encoding="utf-8")
    assert secret not in event.read_text(encoding="utf-8")
    monkeypatch.setattr(server, "AUDIT", fresh / "audit.jsonl")
    server._audit("start_test", run="fresh")
    assert "start_test" in (fresh / "audit.jsonl").read_text(encoding="utf-8")
    assert secret not in (fresh / "audit.jsonl").read_text(encoding="utf-8")
    _append(fresh, "android_results.jsonl", {"id": "kept"})
    assert "kept" in (fresh / "android_results.jsonl").read_text(encoding="utf-8")
    _save(fresh, _coverage())
    coverage = (fresh / "jscov" / "tests_main.jsonl").read_text(encoding="utf-8")
    assert "shop.example" in coverage and secret not in coverage


def test_javascript_coverage_does_not_follow_a_link_into_another_folder(tmp_path):
    from backend.jscov import append, summary

    secret = b"tenant-b-only-jscov"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    (nested / "jscov.json").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    sample = {"https://shop.example/app.js": {"length": 8, "covered": [[0, 4]]}}
    append(linked / "run", "crawl", sample)
    assert summary(linked / "run", "shop.example") is None
    assert not (nested / "jscov").exists()
    assert (nested / "jscov.json").read_bytes() == secret
    assert (nested / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    real.mkdir()
    append(real, "crawl", sample)
    saved = summary(real, "shop.example")
    assert saved is not None and saved["own_scripts"] == 1
    assert secret not in (real / "jscov.json").read_bytes()
    assert secret not in (real / "jscov" / "crawl.jsonl").read_bytes()
    assert (nested / "keep.txt").read_bytes() == secret


def _coverage():
    class _CDP:
        def send(self, method):
            if method == "Profiler.takePreciseCoverage":
                return {"result": [{"url": "https://shop.example/app.js", "functions": [
                    {"ranges": [{"startOffset": 0, "endOffset": 4, "count": 1}]}]}]}
            return {}

        def detach(self):
            return None

    return _CDP()


def test_a_test_coverage_note_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "main")
    secret = b"tenant-b-only-coverage"
    other = tmp_path / "other"
    nested = other / "runs" / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    save = _load_cov_save()
    save(linked / "runs" / "run", _coverage())
    assert not (nested / "jscov").exists()
    assert (nested / "keep.txt").read_bytes() == secret
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    save(real, _coverage())
    written = (real / "jscov" / "tests_main.jsonl").read_bytes()
    assert b"shop.example" in written and secret not in written
    assert (nested / "keep.txt").read_bytes() == secret


def test_an_android_result_line_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = b'{"id":"tenant-b-only"}\n'
    other = tmp_path / "other"
    nested = other / "runs" / "run"
    nested.mkdir(parents=True)
    (nested / "android_results.jsonl").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    append = _load_append()
    append(linked / "runs" / "run", "android_results.jsonl", {"id": "sneak"})
    assert (nested / "android_results.jsonl").read_bytes() == secret
    assert not (nested / "fresh").exists()
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    append(real, "android_results.jsonl", {"id": "kept-home"})
    written = (real / "android_results.jsonl").read_text(encoding="utf-8")
    assert "kept-home" in written and "tenant-b-only" not in written
    assert (nested / "android_results.jsonl").read_bytes() == secret


def test_an_android_case_file_does_not_follow_a_link_into_another_folder(tmp_path):
    import ast
    from pathlib import Path

    tree = ast.parse(Path("backend/templates/android_mobile_test.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_load_mobile_json")
    ns = {"Path": Path, "json": json}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "android_mobile_test.py", "exec"), ns)
    load = ns["_load_mobile_json"]
    secret = "tenant-b-only-case"
    other = tmp_path / "other"
    nested = other / "runs" / "run"
    nested.mkdir(parents=True)
    case_file = nested / "android_test_cases.json"
    case_file.write_text(json.dumps({"id": secret, "title": secret}), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    try:
        load(linked / "runs" / "run" / "android_test_cases.json")
    except RuntimeError as exc:
        assert "link" in str(exc)
    else:
        raise AssertionError("a linked Android case file was read")
    assert secret in case_file.read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    own = real / "android_test_cases.json"
    own.write_text(json.dumps({"id": "home-own", "title": "Home"}), encoding="utf-8")
    loaded = load(own)
    assert loaded["id"] == "home-own"
    assert secret not in json.dumps(loaded)
    assert secret in case_file.read_text(encoding="utf-8")


def _load_append():
    import ast
    from pathlib import Path
    tree = ast.parse(Path("backend/templates/android_conftest.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_append")
    ns = {"json": json, "redact": lambda text: text}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "android_conftest.py", "exec"), ns)

    def append(run, name, record):
        ns["RUN"] = run
        ns["_append"](name, record)

    return append


def _load_cov_save():
    import ast
    import os
    from pathlib import Path
    tree = ast.parse(Path("backend/templates/conftest.py").read_text(encoding="utf-8"))
    want = {"_output_is_linked", "_cov_save"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
    ns = {"Path": Path, "json": json, "os": os}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "conftest.py", "exec"), ns)

    def save(run, cdp):
        ns["RUN_DIR"] = run
        ns["_cov_save"](cdp)

    return save


def test_a_recheck_list_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    from backend.agents.change_detection import run_read_block
    from backend.recheck import tests_of

    monkeypatch.delenv("QPILOT_TENANT_ID", raising=False)

    secret = "tenant-b-only-recheck"
    other = tmp_path / "other"
    nested = other / "runs" / "run"
    nested.mkdir(parents=True)
    findings = nested / "failures.json"
    findings.write_text(json.dumps([
        {"id": 0, "nodeid": secret, "category": "product_defect"},
    ]), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    assert tests_of(linked / "runs" / "run", [0]) == []
    assert run_read_block(linked / "runs" / "run", "failures.json")
    assert secret in findings.read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    (real / "failures.json").write_text(json.dumps([
        {"id": 0, "nodeid": "test_home.py::test_home_own", "category": "product_defect"},
    ]), encoding="utf-8")
    assert tests_of(real, [0]) == ["test_home.py::test_home_own"]
    assert run_read_block(real, "failures.json") == ""
    assert secret not in json.dumps(tests_of(real, [0]))
    assert secret in findings.read_text(encoding="utf-8")


def test_an_account_tag_is_not_read_through_a_link_into_another_folder(tmp_path, monkeypatch):
    import ast
    import os
    import re
    from pathlib import Path

    monkeypatch.setenv("PYTEST_XDIST_WORKER", "")
    secret = "tenant-b-only-tag"
    other = tmp_path / "other"
    nested = other / "runs" / "run"
    nested.mkdir(parents=True)
    life = nested / "qx_lifecycle.json"
    life.write_text(json.dumps({"prepared": [[
        {"kind": "account", "state": "ready", "worker": 1, "tag": secret},
    ]]}), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    tree = ast.parse(Path("backend/templates/conftest.py").read_text(encoding="utf-8"))
    want = {"_output_is_linked", "_worker_account_tag"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
    ns = {"Path": Path, "json": json, "os": os, "re": re, "RUN_DIR": linked / "runs" / "run"}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "conftest.py", "exec"), ns)
    assert ns["_worker_account_tag"]() == ""
    assert secret in life.read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    (real / "qx_lifecycle.json").write_text(json.dumps({"prepared": [[
        {"kind": "account", "state": "ready", "worker": 1, "tag": "home-own"},
    ]]}), encoding="utf-8")
    ns["RUN_DIR"] = real
    assert ns["_worker_account_tag"]() == "home-own"
    assert secret not in ns["_worker_account_tag"]()
    assert secret in life.read_text(encoding="utf-8")


def test_an_android_case_list_is_not_read_through_a_link_into_another_folder(tmp_path):
    import ast
    from pathlib import Path

    import pytest

    from backend.android import AndroidEnvironmentError

    secret = "tenant-b-only-case"
    other = tmp_path / "other"
    nested = other / "runs" / "run"
    nested.mkdir(parents=True)
    cases = nested / "android_test_cases.json"
    cases.write_text(json.dumps([{"id": secret}]), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    tree = ast.parse(Path("backend/templates/android_conftest.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_load_mobile_json")
    ns = {"Path": Path, "json": json, "AndroidEnvironmentError": AndroidEnvironmentError}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "android_conftest.py", "exec"), ns)
    with pytest.raises(AndroidEnvironmentError, match="link"):
        ns["_load_mobile_json"](linked / "runs" / "run" / "android_test_cases.json")
    assert secret in cases.read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    (real / "cases.json").write_text(json.dumps([{"id": "home-own"}]), encoding="utf-8")
    loaded = ns["_load_mobile_json"](real / "cases.json")
    assert loaded[0]["id"] == "home-own"
    assert secret not in json.dumps(loaded)
    assert secret in cases.read_text(encoding="utf-8")
