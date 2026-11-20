"""A Postgres restore stays in this install. A link does not start pg_dump or psql."""
import subprocess
from pathlib import Path

from backend.blueprint_progress import progress
from backend.postgres_dr_drill import run_postgres_dr_drill


def test_a_postgres_restore_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.postgres_dr_drill as mod

    calls = {"n": 0}

    def _run(cmd, **_kwargs):
        calls["n"] += 1
        stdout = ""
        if cmd and cmd[0] == "pg_dump" and "-f" in cmd:
            Path(cmd[cmd.index("-f") + 1]).write_text("dump", encoding="utf-8")
        elif "-tAc" in cmd:
            stdout = "3\n"
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(mod.subprocess, "run", _run)
    monkeypatch.setattr(mod, "_dsn", lambda: "postgresql://example.invalid/qpilot")
    root = tmp_path / "root"
    monkeypatch.setattr(mod, "ROOT", root)

    secret = "tenant-b-pg-dr"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "postgres_dr_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_postgres_dr_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_h_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_postgres_dr_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    foreign_dump = other / "qpilot.dump.sql"
    foreign_dump.write_text(secret, encoding="utf-8")
    dump_parent = root / "artifacts" / "ops"
    dump_parent.mkdir(parents=True)
    dump_link = dump_parent / "postgres_dr"
    dump_link.symlink_to(other, target_is_directory=True)
    unread = run_postgres_dr_drill(ops_dir=real)
    assert unread["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(unread)
    assert foreign_dump.read_text(encoding="utf-8") == secret
    dump_link.unlink()

    saved = run_postgres_dr_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_h_complete"] is False
    assert saved["ok"] is True
    assert saved["isolated_db"] == "qpilot_dr_restore"
    assert calls["n"] == 6
    assert "isolated DB" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original
    assert foreign_dump.read_text(encoding="utf-8") == secret


def test_pg_dr_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-pg-dr-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-pg-dr-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "H")["status"] != "done"
    assert snap["complete"] is False
