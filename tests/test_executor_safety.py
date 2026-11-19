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
