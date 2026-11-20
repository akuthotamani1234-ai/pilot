"""A MinIO object drill stays in this install. A link does not open the store."""
from backend.blueprint_progress import progress
from backend.minio_drill import object_store_drill


def test_a_minio_object_drill_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.object_store as stores

    calls = {"n": 0}

    class _Store:
        def __init__(self):
            self.data = {}

        def put(self, key, body):
            self.data[key] = body

        def get(self, key):
            if key not in self.data:
                raise KeyError(key)
            return self.data[key]

        def list_keys(self, prefix):
            return [key for key in self.data if key.startswith(prefix)]

        def delete(self, key):
            return self.data.pop(key, None) is not None

    def _open(*_args, **_kwargs):
        calls["n"] += 1
        return {"ready": True, "backend": "minio", "store": _Store(), "reason": ""}

    monkeypatch.setattr(stores, "open_object_store", _open)

    secret = "tenant-b-minio-store"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "minio_object_store_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = object_store_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_g_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = object_store_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    planted.unlink()

    saved = object_store_drill(ops_dir=real, uri="minio://127.0.0.1:9000/qpilot-evidence")
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_g_complete"] is False
    assert saved["ok"] is True
    assert saved["backend"] == "minio"
    assert calls["n"] == 1
    assert "put/get" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_minio_store_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-minio-store-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-minio-store-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
