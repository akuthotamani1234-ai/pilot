"""A browser window loads this run's saved login. A link is not loaded."""
import importlib.util
import json
import os

import pytest

from backend.blueprint_progress import progress

# (loading the template conftest patches Playwright: put it back after each test)
pytestmark = pytest.mark.usefixtures("restore_playwright")


def _load(tmp_path, monkeypatch, auth, roles):
    run = tmp_path / "harness"
    run.mkdir(exist_ok=True)
    monkeypatch.setenv("QA_RUN_DIR", str(run))
    monkeypatch.setenv("QA_SCREENSHOT_DIR", str(run / "shots"))
    monkeypatch.setenv("QA_TRACE_DIR", str(run / "traces"))
    monkeypatch.setenv("QA_TRACES", "false")
    monkeypatch.setenv("QA_AUTH_STATE", auth)
    monkeypatch.setenv("QA_ROLE_STATES", json.dumps(roles))
    spec = importlib.util.spec_from_file_location(
        "qa_conftest_login_link", "backend/templates/conftest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_browser_login_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-login"
    other = tmp_path / "other"
    other.mkdir()
    stolen = other / "auth.json"
    stolen.write_text(json.dumps({"cookies": [{"name": "session", "value": secret}]}), encoding="utf-8")
    (other / "keep.txt").write_text(secret, encoding="utf-8")
    linked = tmp_path / "linked-auth.json"
    linked.symlink_to(stolen)
    role_link = tmp_path / "linked-role.json"
    role_link.symlink_to(stolen)
    module = _load(tmp_path, monkeypatch, str(linked), {"viewer": str(role_link)})

    user = module._context_options("user")
    role = module._context_options("role:viewer")
    assert "storage_state" not in user and "storage_state" not in role
    assert secret not in json.dumps({"user": user, "role": role})
    assert module._login_file(str(linked)) == ""
    assert stolen.read_text(encoding="utf-8").count(secret) == 1
    assert (other / "keep.txt").read_text(encoding="utf-8") == secret

    real = tmp_path / "auth.json"
    real.write_text(json.dumps({"cookies": [{"name": "home-own-login", "value": "ours"}]}), encoding="utf-8")
    role_real = tmp_path / "viewer.json"
    role_real.write_text(json.dumps({"cookies": [{"name": "home-own-role", "value": "ours"}]}), encoding="utf-8")
    module.AUTH_STATE = str(real)
    module.ROLE_STATES = {"viewer": str(role_real)}
    saved_user = module._context_options("user")
    saved_role = module._context_options("role:viewer")
    assert saved_user["storage_state"] == str(real)
    assert saved_role["storage_state"] == str(role_real)
    assert secret not in json.dumps({"user": saved_user, "role": saved_role})
    assert "home-own-login" in real.read_text(encoding="utf-8")
    assert "home-own-role" in role_real.read_text(encoding="utf-8")
    assert stolen.read_text(encoding="utf-8").count(secret) == 1


def test_a_browser_video_folder_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-video"
    other = tmp_path / "other"
    videos = other / "videos"
    videos.mkdir(parents=True)
    (videos / "keep.txt").write_text(secret, encoding="utf-8")
    linked = tmp_path / "linked-videos"
    linked.symlink_to(videos, target_is_directory=True)
    module = _load(tmp_path, monkeypatch, "", {})
    module.VIDEO_DIR = str(linked)
    refused = module._context_options("guest")
    assert "record_video_dir" not in refused
    assert secret not in json.dumps(refused)
    assert (videos / "keep.txt").read_text(encoding="utf-8") == secret
    assert not (videos / "home.webm").exists()

    real = tmp_path / "videos"
    real.mkdir()
    module.VIDEO_DIR = str(real)
    saved = module._context_options("guest")
    assert saved["record_video_dir"] == str(real)
    assert secret not in json.dumps(saved)
    assert (videos / "keep.txt").read_text(encoding="utf-8") == secret


def test_a_saved_login_temp_file_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-login-temp"
    other = tmp_path / "other"
    other.mkdir()
    stolen = other / "stolen.json"
    stolen.write_text(json.dumps({"cookies": [{"name": "session", "value": secret}]}), encoding="utf-8")
    original = stolen.read_text(encoding="utf-8")
    real = tmp_path / "auth.json"
    real.write_text("{}", encoding="utf-8")
    module = _load(tmp_path, monkeypatch, str(real), {})
    linked = real.with_name(f"auth.{os.getpid()}.tmp")
    linked.symlink_to(stolen)

    class _Browser:
        def storage_state(self, path):
            from pathlib import Path
            Path(path).write_text(
                json.dumps({"cookies": [{"name": "home-own-login", "value": "ours"}]}),
                encoding="utf-8")

    module._save_login(_Browser())
    assert linked.is_symlink()
    assert stolen.read_text(encoding="utf-8") == original
    assert real.read_text(encoding="utf-8") == "{}"
    assert secret not in real.read_text(encoding="utf-8")

    linked.unlink()
    module._save_login(_Browser())
    saved = real.read_text(encoding="utf-8")
    assert "home-own-login" in saved
    assert secret not in saved
    assert stolen.read_text(encoding="utf-8") == original
    assert not linked.exists()


def test_browser_login_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-browser-login-link")
    video = next(item for item in snap["upcoming"] if item["id"] == "G-video-dir-link")
    temp = next(item for item in snap["upcoming"] if item["id"] == "G-login-temp-link")
    assert row["status"] == "done"
    assert video["status"] == "done"
    assert temp["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
