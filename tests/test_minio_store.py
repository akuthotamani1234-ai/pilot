"""Gate G MinIO object store (skips when credentials/URI unavailable)."""
import os

import pytest

from backend.minio_drill import object_store_drill
from backend.object_store import open_object_store


def test_minio_open_and_roundtrip_when_configured(monkeypatch):
    if not (os.getenv("MINIO_ACCESS_KEY") or os.getenv("MINIO_ROOT_USER")):
        pytest.skip("MinIO credentials not configured in this environment")
    monkeypatch.setenv(
        "OBJECT_STORE_URI",
        os.getenv("OBJECT_STORE_URI") or "minio://127.0.0.1:9000/qpilot-evidence",
    )
    opened = open_object_store()
    if not opened.get("ready"):
        pytest.skip(opened.get("reason") or "minio unavailable")
    store = opened["store"]
    key = "tests/roundtrip.txt"
    store.put(key, b"hello-minio")
    assert store.get(key) == b"hello-minio"
    assert key in store.list_keys("tests/")
    assert store.delete(key) is True
    evidence = object_store_drill()
    assert evidence["gate_g_complete"] is False
    assert evidence["ok"] is True
