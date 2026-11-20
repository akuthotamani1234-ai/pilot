"""An SSO contract stays in this install. A link does not read the env snapshot."""
from backend.blueprint_progress import progress
from backend.sso_contract_drill import run_sso_contract_drill


def test_an_sso_contract_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.sso_contract_drill as mod

    calls = {"n": 0}

    def _snapshot():
        calls["n"] += 1
        return {
            "gate_i_complete": False,
            "ready": False,
            "configured": False,
            "jwt_helper": "backend.oidc_jwt.validate_bearer",
            "reason": "SSO/OIDC contract snapshot recorded; live hosted IdP SSO still open",
        }

    monkeypatch.setattr(mod, "snapshot", _snapshot)
    secret = "tenant-b-sso"
    monkeypatch.setenv("QPILOT_OIDC_ISSUER", secret)

    other = tmp_path / "other"
    other.mkdir()
    kept = other / "sso_contract_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_sso_contract_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_i_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_sso_contract_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_sso_contract_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_i_complete"] is False
    assert saved["ready"] is False
    assert saved["ok"] is True
    assert saved["jwt_helper"]
    assert calls["n"] == 1
    assert "SSO/OIDC" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_sso_contract_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-sso-contract-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-sso-contract-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "I")["status"] != "done"
    assert snap["complete"] is False
