"""Local controlled backend/browser fixture; separate from customer automation."""

import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class ContractFixture:
    def __init__(self, database, broken=False):
        self.database, self.broken, self.requests = database, broken, []
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE quotes (id INTEGER PRIMARY KEY, total INTEGER)")
            connection.execute("INSERT INTO quotes VALUES (1, ?)", (7 if broken else 0,))
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                fixture.requests.append(self.path)
                path = urlsplit(self.path).path
                if path == "/api/state":
                    body = json.dumps({"total": 7 if fixture.broken else 0}).encode()
                    content_type = "application/json"
                elif path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
                    self.end_headers()
                    return
                elif path == "/hybrid":
                    body = (
                        '<!doctype html><title>Hybrid quote</title><h1 id="heading">Embedded quote</h1>'
                        '<p>Quantity <span id="quantity">2</span></p><p>Unit price <span id="price">$10.00</span></p>'
                        '<p>Total <span id="total">$' + ("27" if fixture.broken else "20") + ".00</span></p>"
                        "<button id=\"webConfirm\" onclick=\"document.getElementById('message').textContent='Quote checked'\">Check quote</button>"
                        '<p id="message">Quote ready</p>'
                    ).encode()
                    content_type = "text/html; charset=utf-8"
                else:
                    body = (
                        (
                            """<!doctype html><title>Contract fixture</title><h1 id="heading">Login</h1>
<form id="login"><input id="user" aria-label="Username"><input id="password" type="password" aria-label="Password"><button id="submit">Login</button></form><p id="loginMessage">Enter the local test account</p>
<form id="validation"><input id="name" aria-label="Required name"><button id="validate">Submit</button></form><p id="validationMessage">Name is required</p>
<p>Quantity <span id="quantity">2</span></p><p>Unit price <span id="price">$10.00</span></p><p>Total <span id="total">TOTAL</span></p>
<script>document.getElementById('login').addEventListener('submit',e=>{e.preventDefault(); const valid=document.getElementById('user').value==='demo'&&document.getElementById('password').value==='demo123';document.getElementById('heading').textContent=valid?'Dashboard':'Login';document.getElementById('loginMessage').textContent=valid?'Welcome demo user':'Invalid credentials';});
document.getElementById('validation').addEventListener('submit',e=>{e.preventDefault();document.getElementById('validationMessage').textContent=(!document.getElementById('name').value.trim()&&!BROKEN)?'Name is required':'Local form accepted';});</script>"""
                        )
                        .replace("TOTAL", "$27.00" if fixture.broken else "$20.00")
                        .replace("BROKEN", "true" if fixture.broken else "false")
                        .encode()
                    )
                    content_type = "text/html; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
