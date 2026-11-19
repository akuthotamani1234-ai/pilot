"""Gate F: visual evidence from discovery screenshots without inventing diffs."""
import json

from backend.visual_capture import capture_visual


def test_capture_visual_records_first_run_screenshots(tmp_path):
    shot = tmp_path / "shots" / "01_home.png"
    shot.parent.mkdir()
    shot.write_bytes(b"png")
    report = capture_visual(tmp_path, [{"url": "https://shop.test/", "slug": "home",
                                        "screenshot": "shots/01_home.png"}])
    assert report["first_run"] is True
    assert report["pages"][0]["status"] == "new"
    assert (tmp_path / "visual.json").is_file()
    again = capture_visual(tmp_path, [])
    assert again["pages"][0]["key"] == "home"


def test_a_visual_capture_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = b"tenant-b-only-visual"
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_bytes(secret)
    (other / "visual.json").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    report = capture_visual(linked / "run", [{"url": "https://shop.test/", "slug": "home",
                                              "screenshot": "screenshots/01_home.png"}])
    assert report["pages"] == [] and "link" in report["note"]
    assert (other / "keep.txt").read_bytes() == secret
    assert (other / "visual.json").read_bytes() == secret
    assert not (other / "run").exists()

    real = tmp_path / "real"
    (real / "screenshots").mkdir(parents=True)
    (real / "screenshots" / "01_home.png").write_bytes(b"png")
    saved = capture_visual(real, [{"url": "https://shop.test/", "slug": "home",
                                   "screenshot": "screenshots/01_home.png"}])
    assert saved["pages"][0]["status"] == "new"
    text = (real / "visual.json").read_bytes()
    assert b"home" in text and secret not in text
    assert (other / "keep.txt").read_bytes() == secret


def test_a_saved_look_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.visual import save_capture, visual_check_agent

    secret = b"tenant-b-only-look"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    (nested / "visual.json").write_bytes(secret)
    (nested / "home.json").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    monkeypatch.setattr(settings, "visual_check", True)
    monkeypatch.setattr(settings, "baseline_dir", tmp_path / "baseline")
    assert save_capture(linked / "run", "home", "https://shop.test/", {"boxes": []}, None) == ""
    refused = visual_check_agent({"app_map": [], "run_dir": str(linked / "run"), "site_key": "shop", "log": []})
    assert "link" in refused["log"][-1]
    assert not (nested / "visual").exists()
    assert (nested / "visual.json").read_bytes() == secret
    assert (nested / "home.json").read_bytes() == secret
    assert (nested / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    real.mkdir()
    assert save_capture(real, "home", "https://shop.test/", {"boxes": []}, None) == "visual/home.json"
    saved = visual_check_agent({"app_map": [], "run_dir": str(real), "site_key": "shop", "log": []})
    look = real / "visual" / "home.json"
    assert look.is_file() and not look.is_symlink()
    assert secret not in look.read_bytes()
    assert (real / "visual.json").is_file() and secret not in (real / "visual.json").read_bytes()
    assert "link" not in saved["log"][-1]
    assert (nested / "keep.txt").read_bytes() == secret


def test_a_visual_report_does_not_follow_a_link_into_another_run(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.finalization import copy_unless_linked, write_bytes_unless_linked
    from backend.visual import _read_capture, save_capture, visual_check_agent

    secret = "tenant-b-only-look"
    other = tmp_path / "other"
    other.mkdir()
    (other / "visual.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")
    (other / "home.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")
    (other / "shot.png").write_bytes(b"tenant-b-only-look")
    (other / "diff.png").write_bytes(b"tenant-b-only-look")

    run = tmp_path / "run"
    run.mkdir()
    (run / "visual.json").symlink_to(other / "visual.json")
    (run / "visual").symlink_to(other, target_is_directory=True)
    (run / "screenshots").mkdir()
    (run / "screenshots" / "01_home.png").symlink_to(other / "shot.png")

    report = capture_visual(run, [{"url": "https://shop.test/", "slug": "home",
                                   "screenshot": "screenshots/01_home.png"}])
    assert secret not in json.dumps(report)
    assert save_capture(run, "home", "https://shop.test/", {"boxes": []}, None) == ""
    assert _read_capture(run, "visual/home.json") is None
    src = tmp_path / "src.png"
    src.write_bytes(b"ours")
    assert write_bytes_unless_linked(run / "visual" / "diff.png", b"ours") is False
    assert copy_unless_linked(src, run / "visual" / "approved.png") is False
    monkeypatch.setattr(settings, "visual_check", True)
    visual_check_agent({"app_map": [], "run_dir": str(run), "site_key": "shop", "log": []})
    assert json.loads((other / "visual.json").read_text(encoding="utf-8"))["secret"] == secret
    assert json.loads((other / "home.json").read_text(encoding="utf-8"))["secret"] == secret
    assert (other / "shot.png").read_bytes() == b"tenant-b-only-look"
    assert (other / "diff.png").read_bytes() == b"tenant-b-only-look"

    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "screenshots").mkdir()
    (shots / "screenshots" / "01_home.png").symlink_to(other / "shot.png")
    skipped = capture_visual(shots, [{"url": "https://shop.test/", "slug": "home",
                                      "screenshot": "screenshots/01_home.png"}])
    assert skipped["pages"] == []
    assert secret not in (shots / "visual.json").read_text(encoding="utf-8")

    own = tmp_path / "own"
    own.mkdir()
    (own / "screenshots").mkdir()
    (own / "screenshots" / "01_home.png").write_bytes(b"png")
    saved = capture_visual(own, [{"url": "https://shop.test/", "slug": "home",
                                  "screenshot": "screenshots/01_home.png"}])
    assert saved["pages"][0]["status"] == "new"
    assert (own / "visual.json").is_file() and not (own / "visual.json").is_symlink()
    assert save_capture(own, "home", "https://shop.test/", {"boxes": []}, None) == "visual/home.json"
    assert json.loads((own / "visual" / "home.json").read_text(encoding="utf-8"))["url"] == "https://shop.test/"
