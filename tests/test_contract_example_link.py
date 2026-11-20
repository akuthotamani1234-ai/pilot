"""Demo test flows stay in demo-apps. A link is not that flow."""
import json

from fastapi.testclient import TestClient

from backend import server


def test_a_demo_test_flow_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-contract"
    other = tmp_path / "other"
    other.mkdir()
    (other / "sauce-cart-checks.json").write_text(secret, encoding="utf-8")
    before = sorted(path.name for path in other.iterdir())
    root = tmp_path / "repo"
    demo = root / "demo-apps"
    demo.mkdir(parents=True)
    (demo / "sauce-cart-checks.json").symlink_to(other / "sauce-cart-checks.json")
    monkeypatch.setattr(server, "ROOT", root)
    client = TestClient(server.app, base_url="http://127.0.0.1")

    listed = client.get("/api/contracts/examples")
    assert listed.status_code == 200
    assert "sauce-cart" not in {row["id"] for row in listed.json()["examples"]}
    refused = client.get("/api/contracts/examples/sauce-cart")
    assert refused.status_code == 404
    assert secret not in refused.text
    assert (other / "sauce-cart-checks.json").read_text(encoding="utf-8") == secret
    assert sorted(path.name for path in other.iterdir()) == before

    (demo / "sauce-cart-checks.json").unlink()
    own = {
        "version": 1,
        "flows": [{
            "id": "home_own",
            "title": "home-own flow",
            "steps": [{
                "action": "assert_text",
                "locator": {"strategy": "css", "value": "h1"},
                "value": "home-own-marker",
            }],
        }],
    }
    (demo / "sauce-cart-checks.json").write_text(json.dumps(own), encoding="utf-8")
    listed = client.get("/api/contracts/examples")
    assert "sauce-cart" in {row["id"] for row in listed.json()["examples"]}
    served = client.get("/api/contracts/examples/sauce-cart")
    assert served.status_code == 200
    body = served.json()
    assert body["contract"]["flows"][0]["id"] == "home_own"
    assert "home-own-marker" in served.text
    assert secret not in served.text
    assert (other / "sauce-cart-checks.json").read_text(encoding="utf-8") == secret
