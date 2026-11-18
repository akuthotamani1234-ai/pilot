"""Studio sidebar blueprint progress never claims gates A–J complete."""
from backend.blueprint_progress import progress
from backend.enterprise import readiness


def test_blueprint_progress_lists_gates_and_stays_incomplete():
    snap = progress()
    assert snap["complete"] is False
    assert snap["active"]["id"] in {"A", "B", "C", "D", "E", "F", "G", "H", "I"}
    assert len(snap["gates"]) == 10
    assert {g["id"] for g in snap["gates"]} == set("ABCDEFGHIJ")
    assert all(g["status"] != "done" for g in snap["gates"])  # gates stay open/partial/strong/active
    assert snap["counts"]["gates_total"] == 10
    assert any(u["id"] == "sidebar" for u in snap["upcoming"])


def test_enterprise_readiness_includes_blueprint_todos(monkeypatch):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("QPILOT_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("QPILOT_REDIS_URL", raising=False)
    snap = readiness()
    assert snap["gate_g_complete"] is False
    assert "blueprint" in snap
    assert snap["blueprint"]["complete"] is False
    assert len(snap["blueprint"]["upcoming"]) >= 3
