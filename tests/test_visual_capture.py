"""Gate F: visual evidence from discovery screenshots without inventing diffs."""
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
