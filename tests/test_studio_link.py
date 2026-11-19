"""Studio pages stay in the frontend folder. A link is not that page."""
import hashlib
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from backend import server


def test_a_studio_page_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = b"tenant-b-only-studio"
    other = tmp_path / "other"
    other.mkdir()
    (other / "chat.js").write_bytes(secret)
    (other / "chat.html").write_bytes(b"<html>" + secret)
    (other / "qa-lab.html").write_bytes(secret)
    (other / "index.html").write_bytes(secret)
    before = sorted(path.name for path in other.iterdir())
    static = tmp_path / "frontend"
    static.mkdir()
    (static / "chat.js").symlink_to(other / "chat.js")
    (static / "chat.html").symlink_to(other / "chat.html")
    (static / "qa-lab.html").symlink_to(other / "qa-lab.html")
    dist = static / "dashboard" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").symlink_to(other / "index.html")
    monkeypatch.setattr(server, "STATIC", static)
    monkeypatch.setattr(server, "DASHBOARD_DIST", dist)

    assert server._ui_asset_digests() == {}
    with pytest.raises(HTTPException) as home_error:
        server.home()
    assert home_error.value.status_code == 404
    with pytest.raises(HTTPException) as lab_error:
        server.qa_lab()
    assert lab_error.value.status_code == 404
    placeholder = server.dashboard_home()
    assert isinstance(placeholder, HTMLResponse)
    assert secret not in placeholder.body
    assert (other / "chat.html").read_bytes() == b"<html>" + secret
    assert sorted(path.name for path in other.iterdir()) == before

    (static / "chat.js").unlink()
    (static / "chat.html").unlink()
    (static / "qa-lab.html").unlink()
    (dist / "index.html").unlink()
    (static / "chat.js").write_bytes(b"home-own-script")
    (static / "chat.html").write_text("home-own-page <!--UI_BUILD-->", encoding="utf-8")
    (static / "qa-lab.html").write_text("home-own-lab", encoding="utf-8")
    (dist / "index.html").write_text("home-own-dashboard", encoding="utf-8")

    digests = server._ui_asset_digests()
    assert digests["chat.js"] == hashlib.sha256(b"home-own-script").hexdigest()[:12]
    assert secret.decode() not in digests["chat.js"]
    home = server.home()
    assert isinstance(home, HTMLResponse)
    assert b"home-own-page" in home.body and secret not in home.body
    lab = server.qa_lab()
    dashboard = server.dashboard_home()
    assert isinstance(lab, FileResponse) and isinstance(dashboard, FileResponse)
    assert Path(lab.path).read_text(encoding="utf-8") == "home-own-lab"
    assert Path(dashboard.path).read_text(encoding="utf-8") == "home-own-dashboard"
    assert secret not in Path(lab.path).read_bytes()
    assert (other / "chat.js").read_bytes() == secret
