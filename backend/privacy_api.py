"""Studio-only privacy controls and truthful, expiring MCP presence."""
import re
import threading
import time

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from .privacy import PrivacyPolicy, load_policy, public_policy, save_policy


class MCPPresence:
    def __init__(self):
        self._clients = {}
        self._lock = threading.Lock()

    def touch(self, client_id: str, active=False, online=True):
        if not re.fullmatch(r"[a-f0-9]{32}", client_id or ""):
            return
        now = time.time()
        with self._lock:
            # Expire stale IDs and cap process-local metadata.
            self._clients = {k: v for k, v in self._clients.items() if now - v["last_seen"] < 60}
            if online:
                self._clients[client_id] = {"last_seen": now, "active": bool(active)}
                if len(self._clients) > 32:
                    oldest = min(self._clients, key=lambda k: self._clients[k]["last_seen"])
                    self._clients.pop(oldest, None)
            else:
                self._clients.pop(client_id, None)

    def status(self):
        now = time.time()
        with self._lock:
            recent = [v for v in self._clients.values() if now - v["last_seen"] <= 35]
        active = any(v["active"] for v in recent)
        allowed = load_policy().allow_mcp
        return {"server_online": bool(recent), "assistant_active": active, "mcp_allowed": allowed,
                "server_count": len(recent),
                "status": "offline" if not recent else "blocked" if not allowed else "active" if active else "online",
                "last_seen_seconds": int(min(now - v["last_seen"] for v in recent)) if recent else None,
                "location_verified": False}


class Heartbeat(BaseModel):
    client_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    active: bool = False
    online: bool = True


def register_privacy_api(app, jobs, lock, presence: MCPPresence, busy_rechecks=lambda: False):
    @app.get("/api/settings/privacy")
    def get_privacy():
        return public_policy()

    @app.put("/api/settings/privacy")
    def set_privacy(body: PrivacyPolicy):
        # No MCP tool exposes this endpoint; middleware additionally rejects MCP callers.
        with lock:
            if any(job.get("status") == "running" for job in jobs.values()) or busy_rechecks():
                raise HTTPException(409, "Privacy is locked while a test or re-check is running. Stop it or wait.")
            save_policy(body)
        return public_policy(body)

    @app.get("/api/mcp/connection")
    def connection_status():
        return presence.status()

    @app.post("/api/mcp/heartbeat")
    def heartbeat(body: Heartbeat):
        presence.touch(body.client_id, body.active, body.online)
        return {"ok": True}

    @app.get("/api/mcp/config")
    def client_config(request: Request):
        from setup.mcp_config import configuration

        from .privacy import ROOT
        data = configuration(ROOT)
        # Match the actual UI port, including the fallback port selected by ui.bat.
        data["mcpServers"]["blow-ai"]["env"]["BLOWAI_UI_URL"] = str(request.base_url).rstrip("/")
        return data
