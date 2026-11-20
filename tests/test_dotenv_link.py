"""Settings load from this install's file. A link is left unread."""
import os

from backend.blueprint_progress import progress
from backend.config import _load_dotenv


def test_a_settings_file_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-dotenv"
    other = tmp_path / "other"
    other.mkdir()
    stolen = other / "secret.env"
    stolen.write_text(f"TENANT_B_SECRET={secret}\n", encoding="utf-8")
    original = stolen.read_bytes()
    linked = tmp_path / "linked.env"
    linked.symlink_to(stolen)
    monkeypatch.delenv("TENANT_B_SECRET", raising=False)
    monkeypatch.delenv("HOME_OWN_DOTENV", raising=False)
    try:
        _load_dotenv(linked)
        assert os.environ.get("TENANT_B_SECRET") is None
        assert secret not in os.environ.get("HOME_OWN_DOTENV", "")
        assert stolen.read_bytes() == original

        real = tmp_path / "home.env"
        real.write_text("HOME_OWN_DOTENV=home-own-dotenv\n", encoding="utf-8")
        _load_dotenv(real)
        assert os.environ.get("HOME_OWN_DOTENV") == "home-own-dotenv"
        assert os.environ.get("TENANT_B_SECRET") is None
        assert secret not in os.environ["HOME_OWN_DOTENV"]
        assert stolen.read_bytes() == original
    finally:
        os.environ.pop("TENANT_B_SECRET", None)
        os.environ.pop("HOME_OWN_DOTENV", None)


def test_dotenv_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-dotenv-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
