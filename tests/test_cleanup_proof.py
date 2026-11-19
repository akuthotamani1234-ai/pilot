"""Gate C: a sign-in page is not proof that cleanup deleted the record."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from backend.data_lifecycle import admin_portal_delete, demo_store_cart_delete


def _serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class _Quiet:
    def log_message(self, *_args):
        return


def test_a_login_redirect_is_not_proof_the_user_was_deleted():
    class Handler(_Quiet, BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()

        def do_GET(self):
            body = b"<html>Sign in</html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = _serve(Handler)
    try:
        out = admin_portal_delete(f"http://127.0.0.1:{server.server_address[1]}")(
            {"remote_id": "9", "tag": "user:9", "source": "admin_portal"}
        )
        assert out["deleted"] is False
    finally:
        server.shutdown()


def test_a_delete_redirect_still_counts_as_removed():
    class Handler(_Quiet, BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(303)
            self.send_header("Location", "/users?deleted=1")
            self.end_headers()

        def do_GET(self):
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = _serve(Handler)
    try:
        out = admin_portal_delete(f"http://127.0.0.1:{server.server_address[1]}")(
            {"remote_id": "9", "tag": "user:9", "source": "admin_portal"}
        )
        assert out["deleted"] is True
    finally:
        server.shutdown()


def test_a_login_page_is_not_proof_the_cart_line_was_removed():
    class Handler(_Quiet, BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()

        def do_GET(self):
            body = b"<html>Sign in</html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = _serve(Handler)
    try:
        out = demo_store_cart_delete(
            f"http://127.0.0.1:{server.server_address[1]}", "sid=abc"
        )({"line": 0, "tag": "cart:0", "source": "demo"})
        assert out["deleted"] is False
    finally:
        server.shutdown()


def test_the_cart_remove_message_still_counts_as_removed():
    class Handler(_Quiet, BaseHTTPRequestHandler):
        def do_POST(self):
            body = b'{"message": "Removed from your cart", "cart": 0}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = _serve(Handler)
    try:
        out = demo_store_cart_delete(
            f"http://127.0.0.1:{server.server_address[1]}", "sid=abc"
        )({"line": 0, "tag": "cart:0", "source": "demo"})
        assert out["deleted"] is True
    finally:
        server.shutdown()
