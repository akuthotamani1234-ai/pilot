"""A Studio OIDC callback stays in this install. A link does not start the issuer."""
import http.server

import pytest

pytest.importorskip("jwt")

from backend.blueprint_progress import progress
from backend.studio_oidc_callback_drill import run_studio_oidc_callback_drill


def test_a_studio_oidc_callback_does_not_follow_a_link(tmp_path, monkeypatch):
    calls = {"n": 0}
    real = http.server.HTTPServer

    def _server(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(http.server, "HTTPServer", _server)

    secret = "tenant-b-oidc"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "studio_oidc_callback_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_studio_oidc_callback_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_i_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    planted = real_dir / kept.name
    planted.symlink_to(kept)
    skipped = run_studio_oidc_callback_drill(ops_dir=real_dir)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_studio_oidc_callback_drill(ops_dir=real_dir)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_i_complete"] is False
    assert saved["ok"] is True
    assert saved["callback"]["signature_verified"] is True
    assert calls["n"] == 2
    assert "OIDC callback" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_oidc_callback_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-oidc-callback-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-oidc-callback-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "I")["status"] != "done"
    assert snap["complete"] is False
