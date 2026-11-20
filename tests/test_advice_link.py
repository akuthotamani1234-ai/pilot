"""Fix advice stays in this run. A linked folder is not another tenant's advice file."""
import json


def test_fix_advice_does_not_follow_a_link_into_another_folder(tmp_path):
    from backend.advice import build_fixes

    secret = "tenant-b-only-advice"
    own = "https://home.example/own-page"
    other = tmp_path / "other"
    other.mkdir()
    (other / "fixes.json").write_text(json.dumps([{"title": secret}]), encoding="utf-8")
    before = sorted(path.name for path in other.iterdir())
    linked = tmp_path / "linked-run"
    linked.symlink_to(other, target_is_directory=True)
    run = tmp_path / "run"
    run.mkdir()
    (run / "fixes.json").symlink_to(other / "fixes.json")
    failure = {
        "test": "page_failed", "source": "crawler", "error": "HTTP 500",
        "category": "product_defect", "severity": "high", "page_url": own,
    }
    state = {"failures": [failure], "app_map": [], "test_cases": [], "results": []}

    linked_fixes = build_fixes({**state, "run_dir": str(linked)}, enrich=False)
    file_fixes = build_fixes({**state, "run_dir": str(run)}, enrich=False)
    assert linked_fixes and file_fixes
    assert secret not in json.dumps(linked_fixes)
    assert secret not in json.dumps(file_fixes)
    assert own in json.dumps(file_fixes)
    assert (other / "fixes.json").read_text(encoding="utf-8") == json.dumps([{"title": secret}])
    assert sorted(path.name for path in other.iterdir()) == before

    (run / "fixes.json").unlink()
    written = build_fixes({**state, "run_dir": str(run)}, enrich=False)
    saved = json.loads((run / "fixes.json").read_text(encoding="utf-8"))
    assert saved[0]["where"] == own
    assert secret not in json.dumps(saved)
    assert written[0]["where"] == own
    assert (other / "fixes.json").read_text(encoding="utf-8") == json.dumps([{"title": secret}])
