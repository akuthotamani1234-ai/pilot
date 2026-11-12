"""AdminPortal - a small local admin website (no internet, nothing to install) with the controls real admin apps have
and real testers check: a sortable / searchable / paged data table, a validated form that CREATES records that then
appear in a list (edit + delete), browser dialogs, a modal, a download, file upload, date / range boxes, open AND
closed shadow DOM, and an iframe with a nested iframe.

  /                  links to every page (in the content) + the same links in the header menu
  /users             23 users: sortable columns (Name, Email, Role, Score, Joined), a search box, 5 / 10 / 25 rows per
                     page, pages, row checkboxes + select all; each row: Edit, Delete
  /users/new         name (required), e-mail (required, valid), role, age 18-99 -> POST /users/new -> /users?created=<id>
  /users/<id>/edit   the same form -> POST /users/<id>/edit           /users/<id>/delete (POST) removes the user
  /widgets           alert, prompt (the page then greets the answer), a modal with a Close button, <a download>,
                     file upload, a disabled button, date + range boxes, details/summary, <user-card> (OPEN shadow
                     root: a nickname box + <pref-toggle> with its own open shadow root: a newsletter checkbox) and
                     <secret-widget> (a CLOSED shadow root - can't be tested from outside)
  /reports           <iframe "Totals"> with a "Load totals" button that shows "Total sales: 4560", and a nested
                     <iframe "Archive options"> with an "Include archived" checkbox ("Archived included")
  /help              a link to the user guide (/help/guide)

AdminPortal(bugs=True) has 7 PLANTED BUGS (tests/truth/admin_portal.json):
  B1 the Score column sorts as text (100 before 23)      B2 the table search is case-sensitive
  B3 the e-mail 'a@' is accepted and sent               B4 the modal can't be closed
  B5 the user guide link is a 404                       B6 the iframe's 'Load totals' does nothing
  B7 an edited user name is not saved
Every request is recorded (visited / posts), to prove what a run sent - e.g. 0 POSTs in production mode.

    python tests/admin_portal.py 8768 [bugs]      then open http://127.0.0.1:8768
"""
import html
import http.server
import json
import sys
import threading
from urllib.parse import parse_qs, urlparse

ROLES = ["Admin", "Editor", "Viewer"]
FIRST = ["Asha", "Ben", "Chen", "Dina", "Eli", "Farah", "Gopal", "Hana", "Ivan", "Jia", "Kofi", "Lena", "Mateo",
         "Nora", "Omar", "Priya", "Quinn", "Ravi", "Sara", "Tomas", "Uma", "Vik", "Wen"]
SCORES = [87, 5, 42, 100, 23, 64, 9, 77, 31, 58, 92, 14, 49, 70, 3, 81, 36, 66, 18, 95, 27, 53, 11]


def _users() -> list[dict]:
    return [{"id": n + 1, "name": f"{f} {'Patel Smith Garcia Kim Okafor Novak'.split()[n % 6]}",
             "email": f"{f.lower()}{n + 1}@example.com", "role": ROLES[n % 3], "score": SCORES[n],
             "joined": f"2024-{(n % 12) + 1:02d}-{(n * 7) % 27 + 1:02d}"} for n, f in enumerate(FIRST)]


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title} - AdminPortal</title>
<style>body{{font-family:sans-serif;margin:0}} header nav a{{margin-right:12px}} main{{padding:16px}}
.modal{{position:fixed;inset:20% 30%;background:#fff;border:2px solid #333;padding:20px}} .err{{color:#b00}}
.ok{{color:#070}} table{{border-collapse:collapse}} td,th{{border:1px solid #ccc;padding:4px 8px}}
th{{cursor:pointer}}</style></head>
<body><header><nav class="main-menu"><a href="/">Home</a><a href="/users">Users</a><a href="/users/new">New user</a>
<a href="/widgets">Widgets</a><a href="/reports">Reports</a><a href="/help">Help</a></nav></header>
<main><h1>{title}</h1>{body}</main><footer><p>AdminPortal demo</p></footer></body></html>"""

HOME = """<p>Manage the users of the portal.</p><ul>
<li><a href="/users">All users</a></li><li><a href="/users/new">Add a user</a></li>
<li><a href="/widgets">Widgets</a></li><li><a href="/reports">Reports</a></li><li><a href="/help">Help</a></li></ul>"""

USERS = """{message}
<p><label for="user-search">Search users</label> <input id="user-search" type="search" placeholder="Search users">
<label for="page-size">Rows per page</label> <select id="page-size"><option>5</option><option selected>10</option>
<option>25</option></select></p>
<table id="users"><thead><tr><th><input type="checkbox" id="select-all" aria-label="Select all"></th>
<th data-sort="name" class="sortable">Name</th><th data-sort="email" class="sortable">Email</th>
<th data-sort="role" class="sortable">Role</th><th data-sort="score" class="sortable">Score</th>
<th data-sort="joined" class="sortable">Joined</th><th>Actions</th></tr></thead><tbody></tbody></table>
<p><button type="button" id="prev">Previous</button> <span id="page-info"></span>
<button type="button" id="next">Next</button> <span id="selected-info">0 selected</span></p>
<script>
const USERS = {data}, BUGS = {bugs};
let key = 'name', dir = 1, page = 0, size = 10, term = '';
const cmp = (a, b) => {{
  let x = a[key], y = b[key];
  if (key === 'score' && !BUGS) {{ x = +x; y = +y; }} else {{ x = String(x).toLowerCase(); y = String(y).toLowerCase(); }}
  return x < y ? -dir : x > y ? dir : 0; }};
function rows() {{
  const t = BUGS ? term : term.toLowerCase();
  return USERS.filter(u => !t || Object.values(u).some(v => (BUGS ? String(v) : String(v).toLowerCase()).includes(t))).sort(cmp); }}
function draw() {{
  const all = rows(), pages = Math.max(1, Math.ceil(all.length / size)); page = Math.min(page, pages - 1);
  document.querySelector('#users tbody').innerHTML = all.slice(page * size, page * size + size).map(u =>
    `<tr><td><input type="checkbox" class="row-check" aria-label="Select ${{u.name}}"></td><td>${{u.name}}</td>
     <td>${{u.email}}</td><td>${{u.role}}</td><td>${{u.score}}</td><td>${{u.joined}}</td>
     <td><a href="/users/${{u.id}}/edit">Edit</a>
     <form method="post" action="/users/${{u.id}}/delete" style="display:inline"><button>Delete</button></form></td></tr>`).join('')
    || '<tr><td colspan="7">No users found</td></tr>';
  document.getElementById('page-info').textContent = `Page ${{page + 1}} of ${{pages}}`;
  document.getElementById('selected-info').textContent = '0 selected'; }}
document.querySelectorAll('th[data-sort]').forEach(th => th.onclick = () => {{
  dir = key === th.dataset.sort ? -dir : 1; key = th.dataset.sort; draw(); }});
document.getElementById('user-search').oninput = e => {{ term = e.target.value; page = 0; draw(); }};
document.getElementById('page-size').onchange = e => {{ size = +e.target.value; page = 0; draw(); }};
document.getElementById('prev').onclick = () => {{ page = Math.max(0, page - 1); draw(); }};
document.getElementById('next').onclick = () => {{ page++; draw(); }};
document.getElementById('select-all').onchange = e => {{
  const boxes = document.querySelectorAll('.row-check'); boxes.forEach(b => b.checked = e.target.checked);
  document.getElementById('selected-info').textContent = (e.target.checked ? boxes.length : 0) + ' selected'; }};
document.addEventListener('change', e => {{ if (e.target.classList.contains('row-check'))
  document.getElementById('selected-info').textContent = document.querySelectorAll('.row-check:checked').length + ' selected'; }});
draw();
</script>"""

FORM = """{message}<form id="user-form" method="post" action="{action}">
<p><label for="name">Full name</label><br><input id="name" name="name" required maxlength="60" value="{name}"></p>
<p><label for="email">E-mail</label><br><input id="email" name="email" type="{email_type}" required value="{email}"></p>
<p><label for="role">Role</label><br><select id="role" name="role">{roles}</select></p>
<p><label for="age">Age</label><br><input id="age" name="age" type="number" min="18" max="99" value="{age}"></p>
<p id="form-error" class="err" role="alert"></p>
<p><button type="submit" id="save">{button}</button></p></form>
<script>
const BUGS = {bugs};
document.getElementById('user-form').onsubmit = e => {{
  const name = document.getElementById('name'), mail = document.getElementById('email'), age = document.getElementById('age');
  const problems = [];
  if (!name.value.trim()) problems.push('Full name is required');
  const okMail = BUGS ? mail.value.includes('@') : /^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(mail.value);
  if (!okMail) problems.push('Enter a valid e-mail address');
  if (age.value && (+age.value < 18 || +age.value > 99)) problems.push('Age must be between 18 and 99');
  [name, mail, age].forEach(b => b.setAttribute('aria-invalid', 'false'));
  if (!name.value.trim()) name.setAttribute('aria-invalid', 'true');
  if (!okMail) mail.setAttribute('aria-invalid', 'true');
  if (problems.length) {{ e.preventDefault(); document.getElementById('form-error').textContent = problems.join('. '); }}
}};
</script>"""

WIDGETS = """<section><h2>Dialogs</h2>
<button type="button" id="alert-btn" onclick="alert('Settings saved')">Show alert</button>
<button type="button" id="prompt-btn" onclick="const n = prompt('What is your name?'); if (n) document.getElementById('prompt-out').textContent = 'Hello, ' + n + '!'">Ask my name</button>
<span id="prompt-out"></span>
<button type="button" id="open-modal" data-toggle="modal" aria-haspopup="dialog" onclick="document.getElementById('modal').hidden = false">Open settings</button>
<div id="modal" class="modal" role="dialog" aria-modal="true" hidden><h3>Settings</h3><p>Choose your theme.</p>
<button type="button" id="close-modal" onclick="{close}">Close</button></div></section>
<section><h2>Files</h2><a id="download" href="/files/users.csv" download>Download users (CSV)</a>
<p><label for="avatar">Avatar</label> <input id="avatar" name="avatar" type="file" accept="image/*"></p>
<button type="button" id="archive" disabled>Archive (no permission)</button></section>
<section><h2>Values</h2><p><label for="start-date">Start date</label> <input id="start-date" type="date"></p>
<p><label for="volume">Volume</label> <input id="volume" type="range" min="0" max="100" value="50"
 oninput="document.getElementById('volume-out').textContent = this.value"> <output id="volume-out">50</output></p>
<details><summary>More info</summary><p>Admins can change every setting.</p></details></section>
<section><h2>Components</h2><user-card id="profile-card"></user-card> <secret-widget id="secret"></secret-widget></section>
<script>
customElements.define('pref-toggle', class extends HTMLElement {
  constructor() { super(); const r = this.attachShadow({mode: 'open'});
    r.innerHTML = '<label for="newsletter">Newsletter</label> <input type="checkbox" id="newsletter"> <span id="nl-state">Not subscribed</span>';
    r.getElementById('newsletter').onchange = e => r.getElementById('nl-state').textContent = e.target.checked ? 'Subscribed' : 'Not subscribed'; } });
customElements.define('user-card', class extends HTMLElement {
  constructor() { super(); const r = this.attachShadow({mode: 'open'});
    r.innerHTML = '<p><label for="nickname">Nickname</label> <input id="nickname" placeholder="Nickname"></p><pref-toggle></pref-toggle>'; } });
customElements.define('secret-widget', class extends HTMLElement {
  constructor() { super(); const r = this.attachShadow({mode: 'closed'});
    r.innerHTML = '<button>Hidden action</button>'; } });
</script>"""

REPORTS = """<p>Monthly figures.</p><iframe id="totals-frame" title="Totals" src="/reports/frame" width="600" height="320"></iframe>"""
FRAME = """<!doctype html><html><head><meta charset="utf-8"><title>Totals</title></head><body>
<h2>Totals</h2><button type="button" id="load-totals" onclick="{load}">Load totals</button> <span id="total"></span>
<iframe name="archive" title="Archive options" src="/reports/inner" width="500" height="120"></iframe></body></html>"""
INNER = """<!doctype html><html><head><meta charset="utf-8"><title>Archive options</title></head><body>
<label for="include-archived">Include archived</label> <input type="checkbox" id="include-archived"
 onchange="document.getElementById('arch').textContent = this.checked ? 'Archived included' : ''"> <span id="arch"></span>
</body></html>"""
HELP = """<p>Read the <a href="/help/guide">user guide</a> to get started.</p>"""
GUIDE = """<p>1. Add users. 2. Give them a role.</p>"""


class AdminPortal:
    def __init__(self, port: int = 0, bugs: bool = False):
        self.bugs = bugs
        self.users = _users()
        self.next_id = len(self.users) + 1
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.visited: list[str] = []          # every GET path
        self.posts: list[dict] = []           # every POST (path + the fields sent)
        self.lock = threading.Lock()

    def start(self) -> "AdminPortal":
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def tagged(self, tag: str = "qa-") -> list[dict]:
        """Users whose name holds the tester's tag (what a run created and did not remove)."""
        return [u for u in self.users if tag in u["name"]]

    def _form(self, action: str, button: str, values: dict, message: str = "") -> str:
        roles = "".join(f'<option{" selected" if r == values.get("role") else ""}>{r}</option>' for r in ROLES)
        return FORM.format(action=action, button=button, message=message, roles=roles,
                           name=html.escape(values.get("name", "")), email=html.escape(values.get("email", "")),
                           age=html.escape(str(values.get("age", ""))), email_type="text" if self.bugs else "email",
                           bugs="true" if self.bugs else "false")

    def _valid(self, f: dict) -> list[str]:
        import re
        problems = []
        if not f.get("name", "").strip():
            problems.append("Full name is required")
        ok = "@" in f.get("email", "") if self.bugs else re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", f.get("email", ""))
        if not ok:
            problems.append("Enter a valid e-mail address")
        if f.get("age") and not (f["age"].isdigit() and 18 <= int(f["age"]) <= 99):
            problems.append("Age must be between 18 and 99")
        return problems

    def _handler(self):
        app = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body="", headers=None, ctype="text/html; charset=utf-8"):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _page(self, title, body, status=200):
                self._send(status, PAGE.format(title=title, body=body))

            def _user(self, path):
                try:
                    uid = int(path.split("/")[2])
                except (IndexError, ValueError):
                    return None
                return next((u for u in app.users if u["id"] == uid), None)

            def do_GET(self):
                u = urlparse(self.path)
                path = u.path.rstrip("/") or "/"
                q = parse_qs(u.query)
                app.visited.append(path)
                bugs = "true" if app.bugs else "false"
                if path == "/":
                    return self._page("Home", HOME)
                if path == "/users":
                    created = (q.get("created") or [""])[0]
                    msg = '<p class="ok" role="status">User created</p>' if created else \
                        '<p class="ok" role="status">User saved</p>' if q.get("saved") else \
                        '<p class="ok" role="status">User deleted</p>' if q.get("deleted") else ""
                    with app.lock:
                        data = json.dumps(app.users)
                    return self._page("Users", USERS.format(data=data, bugs=bugs, message=msg))
                if path == "/users/new":
                    return self._page("New user", app._form("/users/new", "Create user", {}))
                if path.startswith("/users/") and path.endswith("/edit"):
                    user = self._user(path)
                    if not user:
                        return self._page("Not found", "<p>No such user.</p>", 404)
                    return self._page("Edit user", app._form(f"/users/{user['id']}/edit", "Save changes", user))
                if path == "/widgets":
                    close = "" if app.bugs else "document.getElementById('modal').hidden = true"
                    return self._page("Widgets", WIDGETS.replace("{close}", close))
                if path == "/files/users.csv":
                    rows = "\n".join(f"{x['name']},{x['email']},{x['role']}" for x in app.users)
                    return self._send(200, "name,email,role\n" + rows, {"Content-Disposition":
                                      'attachment; filename="users.csv"'}, ctype="text/csv")
                if path == "/reports":
                    return self._page("Reports", REPORTS)
                if path == "/reports/frame":
                    load = "" if app.bugs else "document.getElementById('total').textContent = 'Total sales: 4560'"
                    return self._send(200, FRAME.replace("{load}", load))
                if path == "/reports/inner":
                    return self._send(200, INNER)
                if path == "/help":
                    return self._page("Help", HELP)
                if path == "/help/guide" and not app.bugs:
                    return self._page("User guide", GUIDE)
                return self._page("Not found", "<p>This page does not exist.</p>", 404)

            def do_POST(self):
                u = urlparse(self.path)
                path = u.path.rstrip("/")
                length = int(self.headers.get("Content-Length") or 0)
                form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8")).items()}
                app.posts.append({"path": path, "fields": sorted(form)})
                if path == "/users/new":
                    problems = app._valid(form)
                    if problems:
                        return self._page("New user", app._form("/users/new", "Create user", form,
                                          f'<p class="err" role="alert">{". ".join(problems)}</p>'), 400)
                    with app.lock:
                        user = {"id": app.next_id, "name": form["name"].strip(), "email": form["email"],
                                "role": form.get("role") or "Viewer", "score": 0, "joined": "2026-10-30"}
                        app.next_id += 1
                        app.users.append(user)
                    return self._send(303, "", {"Location": f"/users?created={user['id']}"})
                if path.startswith("/users/") and path.endswith("/edit"):
                    user = self._user(path)
                    if not user:
                        return self._page("Not found", "<p>No such user.</p>", 404)
                    problems = app._valid(form)
                    if problems:
                        return self._page("Edit user", app._form(path, "Save changes", form,
                                          f'<p class="err" role="alert">{". ".join(problems)}</p>'), 400)
                    with app.lock:
                        if not app.bugs:  # (B7: the new name is not saved)
                            user["name"] = form["name"].strip()
                        user["email"], user["role"] = form["email"], form.get("role") or user["role"]
                    return self._send(303, "", {"Location": "/users?saved=1"})
                if path.startswith("/users/") and path.endswith("/delete"):
                    user = self._user(path)
                    with app.lock:
                        if user:
                            app.users.remove(user)
                    return self._send(303, "", {"Location": "/users?deleted=1"})
                return self._send(405, "method not allowed")

        return Handler


if __name__ == "__main__":
    portal = AdminPortal(int(sys.argv[1]) if len(sys.argv) > 1 else 8768, bugs="bugs" in sys.argv[2:]).start()
    print(f"AdminPortal running at {portal.url}{' (with its 7 planted bugs)' if portal.bugs else ''} - Ctrl+C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        portal.stop()
