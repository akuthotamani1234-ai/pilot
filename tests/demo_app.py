"""DemoShop - a small local website used to test the tester itself (no internet needed, nothing to install).

  public:          /  /about  /contact  /products  /js-error  /docs?id=N  /missing (404)  /redirect-out
  login:           /login            user "demo", password "Demo#1234"  ->  /dashboard
                   /mfa/login        same account, then asks for a one-time code (2-step verification)
                   /captcha/login    shows a CAPTCHA
  behind a login:  /dashboard  /settings  /reports       (not logged in -> /login)
  never to visit:  /logout  /delete-all  (the crawler must skip them)

Start it by hand:   python tests/demo_app.py 8765      then open http://127.0.0.1:8765
In tests:           app = DemoApp().start(); ...; app.stop()
"""
import html
import http.server
import secrets
import sys
import threading
from urllib.parse import parse_qs, urlparse

USER, PASSWORD = "demo", "Demo#1234"
MFA_CODE = "246810"  # the one-time code of /mfa/login (in real life: sent to the person's phone)

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title} - DemoShop</title></head>
<body><header><nav>{nav}</nav></header><main><h1>{title}</h1>{body}</main></body></html>"""

PUBLIC_NAV = ('<a href="/">Home</a> <a href="/about">About</a> <a href="/contact">Contact</a> '
              '<a href="/products">Products</a> <a href="/login">Log in</a>')
USER_NAV = ('<a href="/dashboard">Dashboard</a> <a href="/settings">Settings</a> <a href="/reports">Reports</a> '
            '<a href="/logout">Log out</a>')

HOME = """<p>Welcome to DemoShop, a practice website.</p>
<ul>
  <li><a href="/about?utm_source=newsletter">About us (from the newsletter)</a></li>
  <li><a href="/about#team">Our team</a></li>
  <li><a href="/docs?id=1">Documentation</a></li>
  <li><a href="/js-error">A page with a coding error</a></li>
  <li><a href="/missing">An old page</a></li>
  <li><a href="/redirect-out">Partner site</a></li>
  <li><a href="/files/manual.pdf">Manual (PDF)</a></li>
  <li><a href="/delete-all">Delete all data</a></li>
  <li><a href="https://example.org/">Example (another website)</a></li>
</ul>"""

ABOUT = """<p>We sell fruit.</p>
<div role="tablist"><button role="tab" id="tab-story" aria-selected="true" onclick="show('story')">Our story</button>
<button role="tab" id="tab-team" aria-selected="false" onclick="show('team')">Team</button></div>
<section id="story">Founded in 2020.</section><section id="team" hidden>Ravi and Anna.</section>
<button id="open-details" aria-haspopup="dialog" onclick="document.getElementById('details').showModal()">Open details</button>
<dialog id="details"><p>Opening hours: 9-17</p><button onclick="this.closest('dialog').close()">Close</button></dialog>
<script>function show(id) { for (const t of ['story', 'team']) {
  document.getElementById(t).hidden = t !== id;
  document.getElementById('tab-' + t).setAttribute('aria-selected', String(t === id)); } }</script>"""

# the errors are shown in a <span class="field-error"> (not .error / .invalid-feedback): the tester must still see them
CONTACT = """<form id="contact" method="post" action="/contact" novalidate>
<label for="name">Your name</label> <input id="name" name="name" required>
<span class="field-error" id="name-err"></span><br>
<label for="email">Email</label> <input id="email" name="email" type="email" required>
<span class="field-error" id="email-err"></span><br>
<label for="message">Message</label> <textarea id="message" name="message" maxlength="200"></textarea><br>
<button type="submit" id="send">Send message</button></form>
<script>document.getElementById('contact').addEventListener('submit', e => {
  const n = document.getElementById('name'), m = document.getElementById('email');
  let bad = false;
  document.getElementById('name-err').textContent = n.value.trim() ? '' : (bad = true, 'This field is required');
  document.getElementById('email-err').textContent = !m.value.trim() ? (bad = true, 'This field is required')
    : (/^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(m.value) ? '' : (bad = true, 'Enter a valid email address'));
  if (bad) e.preventDefault();
});</script>"""

LOGIN = """<form id="login-form" method="post" action="{action}">
<label for="username">Username</label> <input id="username" name="username" autocomplete="username"><br>
<label for="password">Password</label> <input id="password" name="password" type="password"><br>
{extra}<button type="submit" id="sign-in">Sign in</button></form>{message}
<p><a href="/forgot-password">Forgot password?</a></p>"""

SETTINGS = """<label for="language">Language</label>
<select id="language"><option value="en">English</option><option value="de">Deutsch</option></select>
<label><input type="checkbox" id="news"> Email me news</label>
<label><input type="radio" name="theme" id="light" value="light" checked> Light</label>
<label><input type="radio" name="theme" id="dark" value="dark"> Dark</label>
<label for="display">Display name</label> <input id="display" name="display" maxlength="30">
<button type="button" id="save" onclick="document.getElementById('saved').textContent = 'Saved'">Save</button>
<span id="saved"></span>
<button type="button" id="delete" onclick="confirm('Really delete your account?')">Delete account</button>"""

REPORTS = """<table id="report"><thead><tr><th class="sortable" onclick="sortRows()">Name</th><th>Total</th></tr></thead>
<tbody><tr><td>Pear</td><td>3</td></tr><tr><td>Apple</td><td>5</td></tr><tr><td>Berry</td><td>1</td></tr></tbody></table>
<script>function sortRows() { const b = document.querySelector('#report tbody');
  [...b.rows].sort((x, y) => x.cells[0].innerText.localeCompare(y.cells[0].innerText)).forEach(r => b.appendChild(r)); }</script>"""

PRODUCTS = ["Red Apple", "Green Pear", "Blue Berry"]


class DemoApp:
    def __init__(self, port: int = 0):
        self.sessions: set[str] = set()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.visited: list[str] = []  # every path requested (to prove the crawler never opened /delete-all)

    def start(self) -> "DemoApp":
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def expire_sessions(self) -> None:
        """Every login ends now (like a session timeout on the server)."""
        self.sessions.clear()

    def _handler(self):
        app = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep test output quiet
                pass

            def _send(self, status: int, body: str = "", headers: dict | None = None, ctype="text/html; charset=utf-8"):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _page(self, title: str, body: str, logged_in=False, status=200, headers=None):
                self._send(status, PAGE.format(title=title, body=body, nav=USER_NAV if logged_in else PUBLIC_NAV),
                           headers)

            def _logged_in(self) -> bool:
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "sid" and v in app.sessions:
                        return True
                return False

            def _redirect(self, to: str, headers: dict | None = None):
                self._send(303, "", dict({"Location": to}, **(headers or {})))

            def do_GET(self):
                u = urlparse(self.path)
                app.visited.append(u.path)
                q = parse_qs(u.query)
                path = u.path.rstrip("/") or "/"
                if path in ("/dashboard", "/settings", "/reports") and not self._logged_in():
                    return self._redirect(f"/login?next={path}")
                if path == "/":
                    return self._page("Home", HOME)
                if path == "/about":
                    return self._page("About", ABOUT)
                if path == "/contact":
                    return self._page("Contact", CONTACT)
                if path == "/products":
                    term = (q.get("q") or [""])[0].lower()
                    items = [p for p in PRODUCTS if term in p.lower()]
                    body = ('<form action="/products"><input type="search" name="q" placeholder="Search products" '
                            f'value="{html.escape(term)}"><button>Search</button></form>'
                            + "".join(f'<div class="product"><h3>{p}</h3><button class="add" type="button" onclick="'
                                      "const c=document.getElementById('cart-count');c.textContent=+c.textContent+1"
                                      '">Add to cart</button></div>' for p in items)
                            + (("" if items else "<p>No products found</p>") + '<p>Cart: <span id="cart-count">0</span></p>'))
                    return self._page("Products", body)
                if path == "/js-error":
                    return self._page("Broken script", "<p>Something is wrong here.</p><script>undefinedFunction()</script>")
                if path == "/docs":
                    n = int((q.get("id") or ["1"])[0])
                    return self._page(f"Docs {n}", f'<p>Chapter {n}</p><a href="/docs?id={n + 1}">Next chapter</a>')
                if path == "/redirect-out":  # another host name: outside the approved scope
                    return self._redirect(f"http://localhost:{app.port}/about")
                if path == "/files/manual.pdf":
                    return self._send(200, "%PDF-1.4 demo", ctype="application/pdf")
                if path in ("/login", "/mfa/login", "/captcha/login"):
                    extra = '<div class="g-recaptcha" data-sitekey="demo"></div>' if path == "/captcha/login" else ""
                    return self._page("Log in", LOGIN.format(action=path, extra=extra, message=""))
                if path == "/forgot-password":
                    return self._page("Forgot password", "<p>Ask the shop owner.</p>")
                if path == "/dashboard":
                    return self._page("Dashboard", f"<p>Welcome back, {USER}!</p>", logged_in=True)
                if path == "/settings":
                    return self._page("Settings", SETTINGS, logged_in=True)
                if path == "/reports":
                    return self._page("Reports", REPORTS, logged_in=True)
                if path == "/logout":
                    return self._redirect("/", {"Set-Cookie": "sid=; Path=/; Max-Age=0"})
                if path == "/delete-all":
                    return self._page("Deleted", "<p>All data was deleted.</p>")
                return self._page("Not found", "<p>This page does not exist.</p>", status=404)

            def do_POST(self):
                u = urlparse(self.path)
                app.visited.append("POST " + u.path)
                length = int(self.headers.get("Content-Length") or 0)
                form = parse_qs(self.rfile.read(length).decode("utf-8"))
                field = lambda k: (form.get(k) or [""])[0]  # noqa: E731
                if u.path == "/contact":
                    return self._page("Contact", "<p>Thanks, we received your message.</p>")
                if u.path in ("/login", "/mfa/login", "/captcha/login"):
                    if field("username") != USER or field("password") != PASSWORD:
                        return self._page("Log in", LOGIN.format(
                            action=u.path, extra="", message='<p class="alert">Invalid username or password</p>'))
                    if u.path == "/mfa/login":  # (a PERSON types the code - the tester never does: tests prove it)
                        return self._page("Verify", '<p>Enter the verification code we sent to your phone.</p>'
                                                    '<form id="mfa" method="post" action="/mfa/verify">'
                                                    '<input name="otp" autocomplete="one-time-code"><button>Verify</button>'
                                                    '</form>')
                    sid = secrets.token_hex(16)
                    app.sessions.add(sid)
                    return self._redirect("/dashboard", {"Set-Cookie": f"sid={sid}; Path=/; HttpOnly"})
                if u.path == "/mfa/verify":
                    if field("otp") != MFA_CODE:
                        return self._page("Verify", '<p class="alert">Wrong code</p>')
                    sid = secrets.token_hex(16)
                    app.sessions.add(sid)
                    return self._redirect("/dashboard", {"Set-Cookie": f"sid={sid}; Path=/; HttpOnly"})
                return self._send(405, "method not allowed")

        return Handler


if __name__ == "__main__":
    demo = DemoApp(int(sys.argv[1]) if len(sys.argv) > 1 else 8765).start()
    print(f"DemoShop running at {demo.url}  (user '{USER}', password '{PASSWORD}') - press Ctrl+C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        demo.stop()
