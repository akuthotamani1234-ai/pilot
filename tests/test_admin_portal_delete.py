"""Gate C: AdminPortal remote_delete adapter confirms cleanup."""
import http.client
import urllib.parse

from backend.data_lifecycle import Lifecycle, admin_portal_delete
from tests.admin_portal import AdminPortal


def test_admin_portal_delete_adapter_removes_user():
    portal = AdminPortal().start()
    try:
        body = urllib.parse.urlencode({
            "name": "Drill User",
            "email": "drill@example.com",
            "role": "Viewer",
            "age": "30",
        }).encode()
        conn = http.client.HTTPConnection("127.0.0.1", portal.port, timeout=10)
        conn.request("POST", "/users/new", body=body,
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        resp = conn.getresponse()
        loc = resp.getheader("Location") or ""
        resp.read()
        conn.close()
        user_id = None
        if "created=" in loc:
            user_id = loc.split("created=")[-1].split("&")[0]
        if not user_id:
            user_id = str(portal.users[-1]["id"])
        assert int(user_id) in {u["id"] for u in portal.users}
        adapter = admin_portal_delete(portal.url)
        life = Lifecycle("portal-drill", "test")
        life.prepare(1)
        # Replace synthetic prepare rows with the AdminPortal user fixture only.
        life._by_worker[1] = [{
            "tag": f"user:{user_id}",
            "kind": "account",
            "state": "ready",
            "run_id": "portal-drill",
            "remote_id": user_id,
            "source": "admin_portal",
        }]
        out = life.cleanup_confirmed(1, remote_delete=adapter)
        assert out["failed"] == []
        assert out["confirmed"]
        assert all(u["id"] != int(user_id) for u in portal.users)
    finally:
        portal.stop()
