"""TravelSite - a small local flight-booking website (no internet needed), to prove the tester is not only for shops:
the rules between fields a real tester checks, a filtered and sorted results list, detail pages, and a sign-up form.

  /                     flight search: From / To (the same airports), One way / Round trip (Round trip enables the
                        return date), departure + return dates, passengers 1-9 with "Estimated total: $<fare x pax>"
                        -> GET /search
  /search?...           the results: flight cards (number, route, stops, price) with a "Non-stop only" filter and a
                        price sort; each card links to /flight/<code>
  /flight/<code>        the flight's page: its number, route, stops and price; "Select this flight" says it is
                        selected (no booking)
  /signup               name, e-mail, password, confirm password -> POST /signup

TravelSite(bugs=True) has 6 PLANTED BUGS (tests/truth/travel_site.json):
  T1 a return date before the departure date is accepted     T2 From = To is accepted
  T3 2 passengers show the same total as 1                   T4 the non-stop filter shows a 1-stop flight
  T5 the flight's page shows another price than the list     T6 a confirm-password mismatch is accepted

    python tests/travel_site.py 8769 [bugs]      then open http://127.0.0.1:8769
"""
import html
import http.server
import sys
import threading
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

AIRPORTS = [("LHR", "London Heathrow"), ("JFK", "New York JFK"), ("DXB", "Dubai"), ("SIN", "Singapore"),
            ("BOM", "Mumbai")]
FARE = 120
FLIGHTS = [  # (code, stops, price per passenger)
    ("QA101", 0, 410), ("QA205", 1, 320), ("QA330", 0, 455), ("QA412", 2, 290), ("QA518", 0, 380), ("QA640", 1, 345)]

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title} - TravelSite</title>
<style>body{{font-family:sans-serif;margin:0}} nav a{{margin-right:12px}} main{{padding:16px}}
.err{{color:#b00}} .flight{{border:1px solid #ccc;padding:8px;margin:6px 0}}</style></head>
<body><header><nav class="main-nav"><a href="/">Search flights</a><a href="/signup">Sign up</a></nav></header>
<main><h1>{title}</h1>{body}</main><footer><p>TravelSite demo</p></footer></body></html>"""


def _options(selected: str = "") -> str:
    return "".join(f'<option value="{c}"{" selected" if c == selected else ""}>{n} ({c})</option>' for c, n in AIRPORTS)


SEARCH = """<form id="search" method="get" action="/search">
<p><label for="from">From</label> <select id="from" name="from">{from_opts}</select>
<label for="to">To</label> <select id="to" name="to">{to_opts}</select></p>
<p><label><input type="radio" name="trip" value="oneway" id="oneway"> One way</label>
<label><input type="radio" name="trip" value="round" id="round" checked> Round trip</label></p>
<p><label for="depart">Departure date</label> <input type="date" id="depart" name="depart" min="{today}" value="{d1}" required>
<label for="return">Return date</label> <input type="date" id="return" name="return" value="{d2}"></p>
<p><label for="passengers">Passengers</label> <input type="number" id="passengers" name="pax" min="1" max="9" value="1"></p>
<p>Estimated total: <span id="total">${fare}</span> (<span id="unit">${fare}</span> per passenger)</p>
<p id="search-error" class="err" role="alert"></p>
<button type="submit" id="go">Search flights</button></form>
<script>
const BUGS = {bugs}, FARE = {fare};
const trip = () => document.querySelector('input[name=trip]:checked').value;
function syncReturn() {{ document.getElementById('return').disabled = trip() !== 'round'; }}
document.querySelectorAll('input[name=trip]').forEach(r => r.onchange = syncReturn);
document.getElementById('passengers').oninput = e => {{
  const n = Math.max(1, +e.target.value || 1);
  document.getElementById('total').textContent = '$' + (BUGS ? FARE : FARE * n); }};
document.getElementById('search').onsubmit = e => {{
  const f = document.getElementById('from').value, t = document.getElementById('to').value;
  const d1 = document.getElementById('depart').value, d2 = document.getElementById('return').value;
  const problems = [];
  if (!BUGS && f === t) problems.push('From and To must be different airports');
  if (!BUGS && trip() === 'round' && d2 && d1 && d2 < d1) problems.push('The return date must be after the departure date');
  if (d1 && d1 < '{today}') problems.push("The departure date can't be in the past");
  if (problems.length) {{ e.preventDefault(); document.getElementById('search-error').textContent = problems.join('. '); }}
}};
syncReturn();
</script>"""

SIGNUP = """{message}<form id="signup" method="post" action="/signup">
<p><label for="fullname">Full name</label> <input id="fullname" name="name" required></p>
<p><label for="mail">E-mail</label> <input id="mail" name="email" type="email" required></p>
<p><label for="pw">Password</label> <input id="pw" name="password" type="password" required minlength="8"></p>
<p><label for="pw2">Confirm password</label> <input id="pw2" name="confirm" type="password" required></p>
<p id="signup-error" class="err" role="alert"></p>
<button type="submit">Create account</button></form>
<script>
const BUGS = {bugs};
document.getElementById('signup').onsubmit = e => {{
  if (!BUGS && document.getElementById('pw').value !== document.getElementById('pw2').value) {{
    e.preventDefault(); document.getElementById('signup-error').textContent = 'The passwords do not match'; }} }};
</script>"""


class TravelSite:
    def __init__(self, port: int = 0, bugs: bool = False):
        self.bugs = bugs
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.visited: list[str] = []
        self.posts: list[dict] = []
        self.accounts: list[str] = []

    def start(self) -> "TravelSite":
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _results(self, q: dict) -> str:
        get = lambda k: (q.get(k) or [""])[0]  # noqa: E731
        f, t, d1, d2, trip = get("from"), get("to"), get("depart"), get("return"), get("trip") or "round"
        pax = max(1, int(get("pax") or 1)) if (get("pax") or "1").isdigit() else 1
        problems = []
        if not self.bugs and f == t:
            problems.append("From and To must be different airports")
        if not self.bugs and trip == "round" and d1 and d2 and d2 < d1:
            problems.append("The return date must be after the departure date")
        if d1 and d1 < date.today().isoformat():
            problems.append("The departure date can't be in the past")
        if problems:
            return f'<p class="err" role="alert">{html.escape(". ".join(problems))}</p><p><a href="/">Change the search</a></p>'
        nonstop = get("nonstop") == "1"
        flights = [x for x in FLIGHTS if not nonstop or x[1] == 0 or (self.bugs and x[0] == "QA205")]
        if get("sort") == "price":
            flights.sort(key=lambda x: x[2])
        base = f"/search?from={f}&to={t}&depart={d1}&return={d2}&trip={trip}&pax={pax}"
        cards = "".join(
            f'<div class="flight"><h3><a href="/flight/{c}?pax={pax}">{c} {f} → {t}</a></h3>'
            f'<p class="stops">{"Non-stop" if s == 0 else f"{s} stop" + ("s" if s > 1 else "")}</p>'
            f'<p class="price">${p}</p></div>' for c, s, p in flights)
        return (f'<p>{len(flights)} flights from {f} to {t} on {d1}' + (f", back {d2}" if trip == "round" and d2 else "")
                + f' for {pax} passenger(s).</p>'
                f'<form method="get" action="/search">'
                + "".join(f'<input type="hidden" name="{k}" value="{html.escape(v)}">' for k, v in
                          (("from", f), ("to", t), ("depart", d1), ("return", d2), ("trip", trip), ("pax", str(pax))))
                + f'<label><input type="checkbox" name="nonstop" value="1"{" checked" if nonstop else ""} '
                  'onchange="this.form.submit()"> Non-stop only</label> '
                  '<label for="sort">Sort by</label> <select id="sort" name="sort" onchange="this.form.submit()">'
                  f'<option value="">Recommended</option><option value="price"{" selected" if get("sort") == "price" else ""}>'
                  'Price: low to high</option></select></form>'
                f'<section id="results">{cards}</section><p><a href="{base}&sort=price">Cheapest first</a></p>')

    def _handler(self):
        app = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _page(self, title, body, status=200):
                self._send(status, PAGE.format(title=title, body=body))

            def do_GET(self):
                u = urlparse(self.path)
                path, q = u.path.rstrip("/") or "/", parse_qs(u.query)
                app.visited.append(path)
                bugs = "true" if app.bugs else "false"
                today = date.today()
                if path == "/":
                    return self._page("Search flights", SEARCH.format(
                        from_opts=_options("LHR"), to_opts=_options("JFK"), today=today.isoformat(),
                        d1=(today + timedelta(days=14)).isoformat(), d2=(today + timedelta(days=21)).isoformat(),
                        fare=FARE, bugs=bugs))
                if path == "/search":
                    return self._page("Flights", app._results(q))
                if path.startswith("/flight/"):
                    code = path.split("/")[2]
                    hit = next((x for x in FLIGHTS if x[0] == code), None)
                    if not hit:
                        return self._page("Not found", "<p>No such flight.</p>", 404)
                    price = hit[2] + (15 if app.bugs and code == "QA101" else 0)  # (T5: another price than the list)
                    stops = "Non-stop" if hit[1] == 0 else f"{hit[1]} stop" + ("s" if hit[1] > 1 else "")
                    return self._page(f"Flight {code}", f'<h2 class="flight-name">{code}</h2><p class="stops">{stops}</p>'
                                                        f'<p class="price">${price}</p>'
                                                        f'<button type="button" id="select" onclick="document.getElementById'
                                                        f'(`picked`).textContent = `Flight {code} selected - booking is '
                                                        f'not part of this demo`">Select this flight</button>'
                                                        '<p id="picked" role="status"></p>'
                                                        '<p><a href="javascript:history.back()">Back to the results</a></p>')
                if path == "/signup":
                    return self._page("Sign up", SIGNUP.format(message="", bugs=bugs))
                return self._page("Not found", "<p>This page does not exist.</p>", 404)

            def do_POST(self):
                u = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8")).items()}
                app.posts.append({"path": u.path, "fields": sorted(form)})
                if u.path == "/signup":
                    if not app.bugs and form.get("password") != form.get("confirm"):
                        return self._page("Sign up", SIGNUP.format(
                            message='<p class="err" role="alert">The passwords do not match</p>',
                            bugs="false"), 400)
                    app.accounts.append(form.get("email", ""))
                    return self._page("Welcome", '<p class="ok" role="status">Account created</p>')
                return self._send(405, "method not allowed")

        return Handler


if __name__ == "__main__":
    site = TravelSite(int(sys.argv[1]) if len(sys.argv) > 1 else 8769, bugs="bugs" in sys.argv[2:]).start()
    print(f"TravelSite running at {site.url}{' (with its 6 planted bugs)' if site.bugs else ''} - Ctrl+C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        site.stop()
