"""Phase 6 Gate G/I foundations: RBAC, API versions, local object store, readiness."""
import pytest

from backend.api_versioning import resolve_path, versioned_path
from backend.enterprise import readiness
from backend.object_store import ObjectStoreError, open_object_store, reset_local_store
from backend.rbac import allow, audit_event


def test_a_missing_tenant_does_not_cross_the_boundary():
    actor_only = allow(role="admin", action="run.read", tenant_id="a")
    resource_only = allow(role="admin", action="run.read", resource_tenant="b")
    assert actor_only["allowed"] is False and resource_only["allowed"] is False
    assert "tenant" in actor_only["reason"] and "tenant" in resource_only["reason"]
    assert allow(role="operator", action="run.write")["allowed"] is True
    assert allow(role="operator", action="run.write", tenant_id="a", resource_tenant="a")["allowed"] is True


def test_rbac_denies_unknown_role_and_cross_tenant():
    assert allow(role="viewer", action="run.write")["allowed"] is False
    assert allow(role="operator", action="run.write", tenant_id="a", resource_tenant="a")["allowed"] is True
    denied = allow(role="admin", action="run.read", tenant_id="a", resource_tenant="b")
    assert denied["allowed"] is False and "tenant" in denied["reason"]
    event = audit_event(actor="op", action="run.write", allowed=True, tenant_id="a")
    assert event["actor"] == "op" and event["audit_id"]


def test_api_versioning_maps_legacy_and_rejects_unknown():
    legacy = resolve_path("/api/runs/latest")
    assert legacy == {"ok": True, "version": 1, "resource": "/runs/latest", "legacy": True, "reason": ""}
    v1 = resolve_path("/api/v1/runs/latest")
    assert v1["ok"] and v1["version"] == 1 and v1["resource"] == "/runs/latest" and not v1["legacy"]
    bad = resolve_path("/api/v9/runs")
    assert bad["ok"] is False and "not supported" in bad["reason"]
    assert versioned_path("runs/latest") == "/api/v1/runs/latest"


def test_local_object_store_roundtrip(tmp_path):
    root = tmp_path / "objs"
    opened = open_object_store(f"local:{root}")
    assert opened["ready"] is True
    store = opened["store"]
    store.put("runs/r1/report.html", b"<html>ok</html>")
    assert store.get("runs/r1/report.html") == b"<html>ok</html>"
    assert store.list_keys("runs/") == ["runs/r1/report.html"]
    assert store.delete("runs/r1/report.html") is True
    with pytest.raises(ObjectStoreError):
        store.get("runs/r1/report.html")
    reset_local_store(root)


def test_an_object_key_does_not_follow_a_link_out_of_the_store(tmp_path):
    secret = b"tenant-t1-only-object"
    root = tmp_path / "store"
    theirs = root / "t1" / "note.txt"
    theirs.parent.mkdir(parents=True)
    theirs.write_bytes(secret)
    sibling = tmp_path / "store-backup" / "note.txt"
    sibling.parent.mkdir()
    sibling.write_bytes(secret)
    (root / "t2").symlink_to(root / "t1", target_is_directory=True)
    (root / "link").symlink_to(sibling.parent, target_is_directory=True)
    store = open_object_store(f"local:{root}")["store"]
    assert store.list_keys("t1/") == ["t1/note.txt"]
    assert "t2/note.txt" not in store.list_keys()
    for key in ("t2/note.txt", "link/note.txt", "../store-backup/note.txt"):
        with pytest.raises(ObjectStoreError):
            store.get(key)
        with pytest.raises(ObjectStoreError):
            store.put(key, b"overwrite")
        with pytest.raises(ObjectStoreError):
            store.delete(key)
    assert theirs.read_bytes() == secret
    assert sibling.read_bytes() == secret


def test_remote_object_store_is_not_silently_ready():
    opened = open_object_store("minio://example.local/bucket")
    assert opened["ready"] is False
    assert opened["store"] is None


def test_enterprise_readiness_does_not_claim_gate_complete(monkeypatch):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("OBJECT_STORE_URI", raising=False)
    monkeypatch.delenv("MINIO_URL", raising=False)
    snap = readiness()
    assert snap["gate_g_complete"] is False
    assert snap["gate_i_complete"] is False
    assert "rbac" in snap["ready"]
    assert "postgres" in snap["missing"]
    assert snap["components"]["react_dashboard"]["configured"] is True
    # Built dist makes the component ready; Gate I still stays incomplete either way.
    if not snap["components"]["react_dashboard"]["ready"]:
        assert "react_dashboard" in snap["missing"]
