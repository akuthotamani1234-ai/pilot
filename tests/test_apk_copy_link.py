"""A repeated Android run copies this run's APK. A link is not copied."""
import json
from pathlib import Path
from types import SimpleNamespace

from backend.blueprint_progress import progress


def test_a_repeated_android_apk_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import pytest

    from backend.qa_benchmark import repeat_android

    secret = b"tenant-b-only-apk"
    other = tmp_path / "other"
    other.mkdir()
    (other / "app.apk").write_bytes(secret)
    (other / "keep.txt").write_bytes(secret)
    linked = tmp_path / "linked.apk"
    linked.symlink_to(other / "app.apk")
    runs = tmp_path / "runs"
    runs.mkdir()
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")

    def read_linked(_path):
        return {"app_mode": "apk", "apk_path": str(linked)}, Path(".")

    monkeypatch.setattr("backend.android_runner._read_config", read_linked)

    def started(*_args, **_kwargs):
        raise AssertionError("started")

    monkeypatch.setattr("backend.android_pipeline._run_mobile_process", started)
    with pytest.raises(ValueError, match="link"):
        repeat_android(config, 1, runs)
    copied = list(runs.glob("repeat_*/.private/app.apk"))
    assert copied == []
    assert (other / "app.apk").read_bytes() == secret
    assert (other / "keep.txt").read_bytes() == secret

    real_apk = tmp_path / "home.apk"
    real_apk.write_bytes(b"home-own-apk")
    real_runs = tmp_path / "real-runs"
    real_runs.mkdir()

    def read_real(_path):
        return {"app_mode": "apk", "apk_path": str(real_apk)}, Path(".")

    monkeypatch.setattr("backend.android_runner._read_config", read_real)

    def execute(command, _env, _timeout):
        run = Path(command[-1]).parent.parent
        (run / "results.json").write_text("{}", encoding="utf-8")
        return SimpleNamespace(stdout="home-own-repeat", stderr=""), False

    monkeypatch.setattr("backend.android_pipeline._run_mobile_process", execute)
    ids = repeat_android(config, 1, real_runs)
    assert len(ids) == 1
    saved = real_runs / ids[0] / ".private" / "app.apk"
    assert saved.is_file() and not saved.is_symlink()
    assert saved.read_bytes() == b"home-own-apk"
    assert secret not in saved.read_bytes()
    assert (other / "keep.txt").read_bytes() == secret
    written = json.loads((real_runs / ids[0] / ".private" / "android_config.json").read_text(encoding="utf-8"))
    assert written["apk_path"] == str(saved.absolute())


def test_apk_copy_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-apk-copy-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
