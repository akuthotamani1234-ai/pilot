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
