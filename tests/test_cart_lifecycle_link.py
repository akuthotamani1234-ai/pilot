"""A cart cleanup stays in this install. A link is left unwritten."""
from backend.blueprint_progress import progress
from backend.demo_store_cart_lifecycle_drill import run_demo_store_cart_lifecycle_drill


def test_a_cart_cleanup_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-cart"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "demo_store_cart_lifecycle_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_demo_store_cart_lifecycle_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_c_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_demo_store_cart_lifecycle_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    assert not (real / "demo_store_cart_lifecycle_work").exists()

    planted.unlink()
    saved = run_demo_store_cart_lifecycle_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_c_complete"] is False
    assert saved["ok"] is True
    assert saved["cart_empty"] is True
    assert "DemoStore cart add" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_cart_lifecycle_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-cart-lifecycle-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-cart-lifecycle-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "C")["status"] != "done"
    assert snap["complete"] is False
