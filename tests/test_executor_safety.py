import json
import time

import pytest


@pytest.mark.parametrize("failure", ["create", "assign"])
def test_windows_job_object_failure_stops_generated_pytest(tmp_path, monkeypatch, failure):
    from backend.agents import executor

    class FakeProcess:
        pid = 4321
        returncode = None

        def __init__(self):
            self.killed = False
            self.waited = False

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9

        def wait(self, timeout=None):
            self.waited = True
            return self.returncode

    process = FakeProcess()
    taskkill = []
    monkeypatch.setattr(executor, "IS_WINDOWS", True)
    monkeypatch.setattr(executor.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(executor.subprocess, "run", lambda *a, **k: taskkill.append(a[0]))
    monkeypatch.setattr(executor, "_env", lambda *a, **k: {})

    class FakeJob:
        closed = False

        def __init__(self, *args):
            if failure == "create":
                raise OSError("job creation denied")

        def add(self, proc):
            raise OSError("process assignment denied")

        def close(self):
            self.closed = True

    job = None
    if failure == "assign":
        class AssignFailJob(FakeJob):
            def __init__(self, *args):
                super().__init__(*args)
                nonlocal job
                job = self
        monkeypatch.setattr(executor, "_Job", AssignFailJob)
    else:
        monkeypatch.setattr(executor, "_Job", FakeJob)

    run = tmp_path / "run"
    test_dir = run / "generated_tests"
    test_dir.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="Job Object limits could not be established"):
        executor._run_pytest({"url": "http://127.0.0.1:8000", "crawl": {}, "app_map": [], "login": {}},
                             test_dir, run / "results.jsonl", run / "shots")

    assert process.killed and process.waited
    assert taskkill == [["taskkill", "/F", "/T", "/PID", "4321"]]
    if job is not None:
        assert job.closed


def test_a_test_result_does_not_follow_a_link_into_another_folder(tmp_path):
    from backend.agents.executor import _run_pytest, _write_run_json

    secret = b"tenant-b-only-result"
    other = tmp_path / "other"
    nested = other / "run"
    (nested / "generated_tests").mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    (nested / "results.json").write_bytes(secret)
    (nested / "results.jsonl").write_bytes(secret)
    (nested / "results_pytest_output.txt").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    run = linked / "run"
    _write_run_json(run, "results.json", [{"nodeid": "test_home.py::test_home", "outcome": "passed"}])
    info = _run_pytest({}, run / "generated_tests", run / "results.jsonl", run / "shots")
    assert info["stopped"] is True
    assert (nested / "results.json").read_bytes() == secret
    assert (nested / "results.jsonl").read_bytes() == secret
    assert (nested / "results_pytest_output.txt").read_bytes() == secret
    assert (nested / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    real.mkdir()
    _write_run_json(real, "results.json", [{
        "nodeid": "test_home.py::test_home", "outcome": "passed", "url": "https://shop.test/home",
    }])
    written = (real / "results.json").read_bytes()
    assert b"https://shop.test/home" in written and secret not in written
    assert (nested / "keep.txt").read_bytes() == secret


def test_an_undone_repair_does_not_follow_a_link_into_another_folder(tmp_path):
    from backend.agents.executor import _undo

    secret = b"click('new')\nSECRET-TENANT-B"
    other = tmp_path / "other"
    nested = other / "run" / "generated_tests"
    nested.mkdir(parents=True)
    (nested / "test_home.py").write_bytes(secret)
    names = sorted(path.name for path in nested.iterdir())
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    run = linked / "run"
    entries = [
        {"status": "reverted", "method": "selector-match", "from": "old", "to": "new", "why": "still failing"},
        {"status": "healed", "method": "selector-match", "from": "keep", "to": "kept", "why": ""},
    ]
    _undo(run / "generated_tests", run, "test_home.py", entries)
    assert (nested / "test_home.py").read_bytes() == secret
    assert sorted(path.name for path in nested.iterdir()) == names
    assert not (other / "fresh").exists()

    real = tmp_path / "real" / "generated_tests"
    real.mkdir(parents=True)
    (real / "test_home.py").write_text("click('new')\n", encoding="utf-8")
    _undo(real, tmp_path / "real", "test_home.py", entries)
    written = (real / "test_home.py").read_text(encoding="utf-8")
    assert written == "click('old')\n"
    assert b"SECRET-TENANT-B" not in written.encode()
    assert (nested / "test_home.py").read_bytes() == secret


def test_an_undone_repair_does_not_restore_a_backup_through_a_link(tmp_path):
    from backend.agents.executor import _undo

    secret = b"tenant-b-only-backup"
    other = tmp_path / "other"
    other.mkdir()
    target = other / "test_home.round1.before.py"
    target.write_bytes(secret)
    run = tmp_path / "linked-backup"
    tests = run / "generated_tests"
    tests.mkdir(parents=True)
    script = tests / "test_home.py"
    script.write_text("click('ours')\n", encoding="utf-8")
    (run / "healing").symlink_to(other, target_is_directory=True)
    entries = [{"status": "reverted", "method": "llm", "backup": "healing/test_home.round1.before.py", "why": "broke"}]
    _undo(tests, run, "test_home.py", entries)
    file_run = tmp_path / "file-link"
    file_tests = file_run / "generated_tests"
    file_tests.mkdir(parents=True)
    file_script = file_tests / "test_home.py"
    file_script.write_text("click('ours')\n", encoding="utf-8")
    (file_run / "healing").mkdir()
    (file_run / "healing" / "test_home.round1.before.py").symlink_to(target)
    _undo(file_tests, file_run, "test_home.py", entries)
    assert script.read_text(encoding="utf-8") == "click('ours')\n"
    assert file_script.read_text(encoding="utf-8") == "click('ours')\n"
    assert target.read_bytes() == secret
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real_tests = real / "generated_tests"
    real_tests.mkdir(parents=True)
    real_script = real_tests / "test_home.py"
    real_script.write_text("click('changed')\n", encoding="utf-8")
    (real / "healing").mkdir()
    (real / "healing" / "test_home.round1.before.py").write_text("click('home-own')\n", encoding="utf-8")
    _undo(real_tests, real, "test_home.py", entries)
    restored = real_script.read_bytes()
    assert restored == b"click('home-own')\n"
    assert secret not in restored
    assert target.read_bytes() == secret


def test_a_live_test_status_does_not_follow_a_link_into_another_file(tmp_path):
    from backend.agents.executor import _running_status

    secret = "tenant-b-only-step"
    other = tmp_path / "other"
    other.mkdir()
    target = other / "running.results.main.json"
    target.write_text(json.dumps({
        "file": "secret.py", "test": secret, "since": 1, "steps": [{"text": secret}],
    }), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    assert _running_status(linked / "results.jsonl") == "between tests"
    real = tmp_path / "file-link"
    real.mkdir()
    (real / "running.results.main.json").symlink_to(target)
    assert _running_status(real / "results.jsonl") == "between tests"
    assert secret in target.read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    own = tmp_path / "own"
    own.mkdir()
    (own / "running.results.main.json").write_text(json.dumps({
        "file": "home.py", "test": "home-own", "since": time.time(), "steps": [{"text": "home-own"}],
    }), encoding="utf-8")
    status = _running_status(own / "results.jsonl")
    assert "home.py::home-own" in status
    assert "home-own" in status
    assert secret not in status
    assert secret in target.read_text(encoding="utf-8")


def test_a_failure_screenshot_folder_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    from backend.agents.executor import execution_agent

    secret = b"tenant-b-only-shots"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    names = sorted(path.name for path in nested.iterdir())
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    started = []

    def refuse_suite(*_args, **_kwargs):
        started.append(True)
        raise AssertionError("the suite must not start through a link")

    monkeypatch.setattr("backend.agents.executor._run_pytest", refuse_suite)
    out = execution_agent({"run_dir": str(linked / "run"), "test_cases": [], "results": [], "log": []})
    assert started == []
    assert "failure screenshots folder is a link" in out["log"][-1]
    assert sorted(path.name for path in nested.iterdir()) == names
    assert (nested / "keep.txt").read_bytes() == secret
    assert not (nested / "failure_screenshots").exists()
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()

    def keep_suite(*_args, **_kwargs):
        return {"timed_out": False, "stopped": False, "returncode": 0, "sandbox": "test"}

    monkeypatch.setattr("backend.agents.executor._run_pytest", keep_suite)
    execution_agent({
        "run_dir": str(real),
        "test_cases": [{"tc_id": "home-own", "expected_source": "The home page loads for this shop."}],
        "results": [],
        "log": [],
    })
    assert (real / "failure_screenshots").is_dir()
    assert secret not in (real / "row.json").read_bytes()
    assert b"home-own" in (real / "row.json").read_bytes()
    assert (nested / "keep.txt").read_bytes() == secret


def test_a_collected_suite_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    from backend.agents.executor import _collect_nodeids

    secret = "tenant-b-only-node"
    other = tmp_path / "other"
    suite = other / "generated_tests"
    suite.mkdir(parents=True)
    (suite / "test_secret.py").write_text(
        f"def test_secret():\n    assert {secret!r}\n", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    started = []

    def refuse(*_args, **kwargs):
        started.append(kwargs.get("cwd"))
        raise AssertionError("pytest started in a linked folder")

    monkeypatch.setattr("backend.agents.executor.subprocess.run", refuse)
    assert _collect_nodeids(linked / "generated_tests") == []
    assert started == []
    assert secret in (suite / "test_secret.py").read_text(encoding="utf-8")
    assert not (other / "fresh").exists()
    monkeypatch.undo()

    real = tmp_path / "real" / "generated_tests"
    real.mkdir(parents=True)
    (real / "test_home.py").write_text("def test_home_own():\n    assert True\n", encoding="utf-8")
    ids = _collect_nodeids(real)
    assert any("test_home_own" in item for item in ids)
    assert secret not in "\n".join(ids)
    assert secret in (suite / "test_secret.py").read_text(encoding="utf-8")


def test_a_saved_result_line_does_not_follow_a_link_into_another_folder(tmp_path):
    import json

    from backend.agents.executor import _read, _result_count

    secret = "tenant-b-only-result"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "results.jsonl").write_text(
        json.dumps({"nodeid": secret, "outcome": "failed"}) + "\n", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    assert _read(linked / "run" / "results.jsonl") == []
    assert _result_count(linked / "run" / "results.jsonl") == 0
    assert secret in (nested / "results.jsonl").read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    (real / "results.jsonl").write_text(
        json.dumps({"nodeid": "home-own", "outcome": "passed"}) + "\n", encoding="utf-8")
    rows = _read(real / "results.jsonl")
    assert rows == [{"nodeid": "home-own", "outcome": "passed"}]
    assert _result_count(real / "results.jsonl") == 1
    assert secret not in json.dumps(rows)
    assert secret in (nested / "results.jsonl").read_text(encoding="utf-8")


def test_a_proof_reading_does_not_follow_a_link_into_another_folder(tmp_path):
    import json

    from backend.assert_strength import analyse

    secret = "tenant-b-only-proof"
    other = tmp_path / "other"
    suite = other / "runs" / "run" / "generated_tests"
    suite.mkdir(parents=True)
    script = suite / "test_secret.py"
    script.write_text(f"def test_secret():\n    assert {secret!r}\n", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    assert analyse(linked / "runs" / "run" / "generated_tests") == {}
    assert secret in script.read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    (real / "test_home.py").write_text("def test_home_own():\n    assert True\n", encoding="utf-8")
    scores = analyse(real)
    assert scores.get("test_home.py::test_home_own")
    assert secret not in json.dumps(scores)
    assert secret in script.read_text(encoding="utf-8")


def test_an_accuracy_count_does_not_follow_a_link_into_another_folder(tmp_path):
    import json

    from backend.accuracy import measure

    secret = "tenant-b-only-page"
    truth = {"pages": [], "features": []}
    other = tmp_path / "other"
    nested = other / "runs" / "run"
    nested.mkdir(parents=True)
    (nested / "app_map.json").write_text(json.dumps([{"slug": secret, "url": "https://other.test/"}]), encoding="utf-8")
    (nested / "test_cases.json").write_text(json.dumps([{
        "tc_id": "other", "title": secret, "execution_status": "Failed",
    }]), encoding="utf-8")
    (nested / "failures.json").write_text(json.dumps([{
        "tc_id": "other", "category": "rule_violation", "title": secret,
    }]), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    refused = measure(linked / "runs" / "run", truth)
    assert refused["pages"]["discovered"] == 0
    assert refused["truth"]["questions"] == []
    assert secret not in json.dumps(refused)
    assert secret in (nested / "app_map.json").read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    (real / "app_map.json").write_text(json.dumps([{"slug": "home-own", "url": "https://home.test/"}]), encoding="utf-8")
    (real / "test_cases.json").write_text(json.dumps([{
        "tc_id": "home-own", "title": "home-own question", "execution_status": "Failed",
    }]), encoding="utf-8")
    (real / "failures.json").write_text(json.dumps([{
        "tc_id": "home-own", "category": "rule_violation",
    }]), encoding="utf-8")
    counted = measure(real, truth)
    assert counted["pages"]["discovered"] == 1
    assert counted["truth"]["questions"][0]["tc_id"] == "home-own"
    assert secret not in json.dumps(counted)
    assert secret in (nested / "failures.json").read_text(encoding="utf-8")
