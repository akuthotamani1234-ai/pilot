"""DemoStore - a small local online shop to show (and test) deep testing behind a login. No internet needed.

  public:            /  /about  /register            (the home page only has a "Sign in" link - no login form)
                     /deals (more deals load when you scroll down - one of them links to /weekend; an "Open help"
                     panel with controls that only appear after opening it; "Add to favourites" asks a visitor to
                     sign in; "Notify me" shows a message)
  two-step login:    /signin   email "demo@store.test" -> Continue -> password "Store#2024" -> Sign in
  behind the login:  /dashboard  /shop (search + suggestions, category filters, sort, 5 result pages)
                     /product/1 ... /product/40 (size option, quantity - / +, Add to cart, Add to wishlist,
                     Add to compare -> a "Compare" link appears -> /compare, Buy now)
                     /cart (price, quantity - / +, line totals, cart total, Remove)  /wishlist
                     /checkout (ends in "Place order")  /orders  /orders/<id>  /orders/<id>/tracking
                     /account (profile form)  /addresses (add-address form)  /admin (403: not for this account)
  never to use:      Place order, Buy now, Log out  (the tester must not; every request is recorded)

DemoStore(bugs=True) has 6 PLANTED BUGS (to prove the tests catch real failures, see demo_store_truth.json):
  sort "Price: low to high" is not sorted · the cart total ignores the quantity · search also shows items that don't
  match · the product's "-" goes below 1 · "Add to wishlist" fails with an error message · "Notify me" does nothing

DemoStore(renamed=True) is the same shop after a "frontend update": the same buttons with the same words, but new
element ids ("Notify me": #notify -> #notify-me) - the scripts of an earlier run break the way they do after a real
redesign, so self-healing has something to repair (tests/test_end_to_end.py).

Start by hand:  python tests/demo_store.py 8766 [bugs] [renamed]      then open http://127.0.0.1:8766
In tests:       store = DemoStore().start(); ...; store.stop()
"""
import html
import http.server
import json
import secrets
import sys
import threading
from urllib.parse import parse_qs, urlencode, urlparse

EMAIL, PASSWORD = "demo@store.test", "Store#2024"
CATEGORIES = ["fruit", "vegetable", "drink"]
NAMES = ["Red Apple", "Green Pear", "Sweet Mango", "Ripe Banana", "Fresh Carrot", "Green Beans", "Orange Juice",
         "Mint Tea", "Black Grapes", "Yellow Lemon", "Baby Spinach", "Sweet Corn", "Apple Cider", "Cold Coffee"]
PRODUCTS = [{"id": n, "name": f"{NAMES[(n - 1) % len(NAMES)]} {n}", "category": CATEGORIES[(n - 1) % 3],
             "price": 20 + (n * 37) % 180} for n in range(1, 41)]
PER_PAGE = 8

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title} - DemoStore</title>
<style>body{{font-family:system-ui;margin:0}} header{{background:#1f2937;padding:10px}} header a{{color:#fff;margin-right:14px}}
main{{padding:16px}} .product-card{{display:inline-block;width:200px;border:1px solid #ddd;margin:6px;padding:8px}}
.msg{{color:green}} .msg.error{{color:#b91c1c}} .field-error{{color:#b91c1c}}
.deal-card{{display:block;height:260px;border:1px solid #ddd;margin:8px 0;padding:8px}}</style></head>
<body><header><nav>{nav}</nav></header><main><h1>{title}</h1>{body}</main></body></html>"""
PUBLIC_NAV = '<a href="/">Home</a><a href="/about">About</a><a href="/deals">Deals</a><a href="/signin">Sign in</a>'
DEALS = [f"{NAMES[n]} - {10 + n * 5}% off" for n in range(8)]
POST_JS = """async function post(url, body, out) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body});
  const d = await r.json(); const m = document.getElementById(out);
  m.textContent = d.message; m.className = d.ok === false ? 'msg error' : 'msg';
  m.setAttribute('role', d.ok === false ? 'alert' : 'status'); return d; }"""


def user_nav(s):
    return ('<a href="/dashboard">Dashboard</a><a href="/shop">Shop</a>'
            f'<a href="/wishlist">Wishlist ({len(s["wish"])})</a><a href="/cart">Cart (<span id="cart-count">'
            f'{sum(i["qty"] for i in s["cart"])}</span>)</a><a href="/orders">Orders</a><a href="/account">Account</a>'
            '<a href="/addresses">Addresses</a><a href="/admin">Admin</a><a href="/logout">Log out</a>')


SIGNIN_1 = """<p>Sign in to your DemoStore account.</p>
<form method="post" action="/signin"><label for="email">Email</label>
<input id="email" name="email" type="email" autocomplete="username">
<button type="submit" id="continue">Continue</button></form>{message}
<p>New here? <a href="/register">Create your account</a></p>"""
SIGNIN_2 = """<p>Signing in as {email}</p>
<form method="post" action="/signin/password"><input type="hidden" name="email" value="{email}">
<label for="password">Password</label> <input id="password" name="password" type="password" autocomplete="current-password">
<button type="submit" id="signin">Sign in</button></form>"""
FORM_JS = """<script>document.querySelectorAll('form[data-check]').forEach(f => f.addEventListener('submit', e => {
  let bad = false;
  f.querySelectorAll('[required]').forEach(i => { const err = document.getElementById(i.id + '-err');
    const msg = !i.value.trim() ? 'This field is required'
      : (i.type === 'email' && !/^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(i.value) ? 'Enter a valid email address' : '');
    if (err) err.textContent = msg; if (msg) bad = true; });
  if (bad) e.preventDefault(); }));</script>"""


class DemoStore:
    def __init__(self, port: int = 0, bugs: bool = False, renamed: bool = False):
        self.bugs = bugs  # the 6 planted bugs (see the top of this file)
        self.renamed = renamed  # new element ids, same words (a frontend update)
        self.sessions: dict[str, dict] = {}
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.visited: list[str] = []  # every request ("GET /shop", "POST /cart/add" ...)

    def start(self) -> "DemoStore":
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _total(self, s: dict) -> int:
        """The cart total: price x quantity of every line (planted bug: the quantity is ignored)."""
        return sum(i["price"] * (1 if self.bugs else i["qty"]) for i in s["cart"])

    def _handler(self):
        store = self

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

            def _session(self):
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "sid" and v in store.sessions:
                        return store.sessions[v]
                return None

            def _page(self, title, body, s=None, status=200):
                self._send(status, PAGE.format(title=title, body=body, nav=user_nav(s) if s else PUBLIC_NAV))

            def _go(self, to, headers=None):
                self._send(303, "", dict({"Location": to}, **(headers or {})))

            def _form(self):
                n = int(self.headers.get("Content-Length") or 0)
                return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8")).items()}

            def do_GET(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                path = u.path.rstrip("/") or "/"
                store.visited.append("GET " + path)
                s = self._session()
                public = path in ("/", "/about", "/register", "/signin", "/deals", "/weekend")
                if not public and not s and path != "/logout":
                    return self._go(f"/signin?next={path}")
                if path == "/":
                    return self._page("Welcome to DemoStore", '<p>Fresh food, delivered.</p><p><a href="/about">About us</a>'
                                      ' · <a href="/signin">Sign in</a> to shop · <a href="/deals">Today\'s deals</a></p>', s)
                if path == "/about":
                    return self._page("About", "<p>DemoStore is a practice shop for automated testing.</p>", s)
                if path == "/deals":
                    return self._deals(s)
                if path == "/weekend":  # only linked from the deals that load when you scroll down
                    return self._page("Weekend special", "<p>Every weekend: free delivery on all fruit.</p>", s)
                if path == "/register":
                    return self._page("Create your account", """<form id="register" data-check method="post" action="/register" novalidate>
<label for="r-name">Your name</label> <input id="r-name" name="name" required><span class="field-error" id="r-name-err"></span>
<label for="r-email">Email</label> <input id="r-email" name="email" type="email" required><span class="field-error" id="r-email-err"></span>
<label for="r-pw">Password</label> <input id="r-pw" name="password" type="password" required><span class="field-error" id="r-pw-err"></span>
<label for="r-pw2">Repeat password</label> <input id="r-pw2" name="password2" type="password" required><span class="field-error" id="r-pw2-err"></span>
<button type="submit">Create account</button></form>""" + FORM_JS)
                if path == "/signin":
                    return self._page("Sign in", SIGNIN_1.format(message=""))
                if path == "/dashboard":
                    return self._page("Dashboard", '<p>Welcome back! What would you like to do?</p><ul>'
                                      '<li><a href="/shop">Browse the shop</a></li><li><a href="/orders">Your orders</a>'
                                      '</li><li><a href="/account">Your account</a></li></ul>', s)
                if path == "/shop":
                    return self._shop(q, s)
                if path.startswith("/product/"):
                    p = next((x for x in PRODUCTS if str(x["id"]) == path.split("/")[2]), None)
                    if not p:
                        return self._page("Not found", "<p>No such product.</p>", s, 404)
                    # the "-" button: never below 1 (planted bug: it goes on to 0, -1 ...)
                    floor = "" if store.bugs else "v = Math.max(1, v); "
                    return self._page(p["name"], f"""<p class="price">₹{p['price']}</p><p>Category: {p['category']}</p>
<label for="size">Size</label> <select id="size" name="size"><option value="S">Small</option><option value="M">Medium</option>
<option value="L">Large</option></select>
<p><label for="qty">Quantity</label>
<button type="button" id="qty-minus" aria-label="Decrease quantity" onclick="step(-1)">−</button>
<input id="qty" name="qty" type="number" value="1" min="1" max="10">
<button type="button" id="qty-plus" aria-label="Increase quantity" onclick="step(1)">+</button></p>
<button type="button" id="add-to-cart" onclick="add('/cart/add')">Add to cart</button>
<button type="button" id="add-wish" onclick="add('/wishlist/add')">Add to wishlist</button>
<button type="button" id="add-compare" onclick="add('/compare/add')">Add to compare</button>
<button type="button" id="buy-now" onclick="location='/buy?id={p['id']}'">Buy now</button>
<p id="msg" class="msg"></p><p id="compare-slot"></p><p><a href="/shop">Back to the shop</a></p>
<script>{POST_JS}
function step(d) {{ const q = document.getElementById('qty'); let v = (+q.value || 1) + d;
  v = Math.min(10, v); {floor}q.value = v; }}
async function add(url) {{
  const d = await post(url, 'id={p['id']}&size=' + document.getElementById('size').value
                            + '&qty=' + document.getElementById('qty').value, 'msg');
  if (d.cart !== undefined) document.getElementById('cart-count').textContent = d.cart;
  if (d.compare) document.getElementById('compare-slot').innerHTML = '<a href="/compare">Compare (' + d.compare + ')</a>'; }}
</script>""", s)
                if path == "/cart":
                    if not s["cart"]:
                        return self._page("Your cart", "<p>Your cart is empty.</p>", s)
                    rows = "".join(
                        f"<tr><td class='item-name'>{html.escape(i['name'])}</td><td>{i['size']}</td>"
                        f"<td class='unit-price'>₹{i['price']}</td><td>"
                        f"<button type='button' class='q-minus' aria-label='Decrease quantity' onclick='upd({n}, -1)'>−</button>"
                        f"<input class='line-qty' type='number' min='1' max='10' value='{i['qty']}' aria-label='Quantity'"
                        f" onchange='upd({n}, 0)'>"
                        f"<button type='button' class='q-plus' aria-label='Increase quantity' onclick='upd({n}, 1)'>+</button>"
                        f"</td><td class='line-total'>₹{i['qty'] * i['price']}</td>"
                        f"<td><button type='button' class='remove' onclick='rm({n})'>Remove</button></td></tr>"
                        for n, i in enumerate(s["cart"]))
                    return self._page("Your cart", f"""<table><tr><th>Item</th><th>Size</th><th>Price</th><th>Quantity</th>
<th>Total</th><th></th></tr>{rows}</table><p>Cart total: <b id="cart-total">₹{store._total(s)}</b></p>
<p id="msg" class="msg"></p><p><a href="/checkout">Proceed to checkout</a></p>
<script>{POST_JS}
async function upd(n, d) {{
  const box = document.querySelectorAll('.line-qty')[n]; const v = Math.max(1, Math.min(10, (+box.value || 1) + d));
  box.value = v; const r = await post('/cart/update', 'line=' + n + '&qty=' + v, 'msg');
  document.querySelectorAll('.line-total')[n].textContent = '₹' + r.line; document.getElementById('cart-total').textContent = '₹' + r.total;
  document.getElementById('cart-count').textContent = r.cart; }}
async function rm(n) {{ await post('/cart/remove', 'line=' + n, 'msg'); location.reload(); }}
</script>""", s)
                if path == "/compare":
                    rows = "".join(f"<tr><td>{html.escape(c['name'])}</td><td>₹{c['price']}</td><td>{c['category']}</td></tr>"
                                   for c in s["compare"])
                    return self._page("Compare products", f"<table><tr><th>Product</th><th>Price</th><th>Category</th></tr>"
                                                          f"{rows}</table>" if rows else "<p>Nothing to compare yet.</p>", s)
                if path == "/wishlist":
                    items = "".join(f"<li>{html.escape(n)}</li>" for n in s["wish"])
                    return self._page("Your wishlist", f"<ul>{items}</ul>" if items else "<p>Nothing saved yet.</p>", s)
                if path == "/checkout":
                    return self._page("Checkout", """<form method="post" action="/order"><label for="addr">Deliver to</label>
<select id="addr" name="addr"><option value="home">Home</option><option value="work">Work</option></select>
<label><input type="radio" name="pay" value="card" checked> Card</label><label><input type="radio" name="pay" value="cash"> Cash</label>
<button type="submit" id="place-order">Place order</button></form>""", s)
                if path == "/orders":
                    return self._page("Your orders", "<table><tr><th>Order</th><th>Status</th></tr>"
                                      '<tr><td><a href="/orders/1001">Order #1001</a></td><td>Delivered</td></tr>'
                                      '<tr><td><a href="/orders/1002">Order #1002</a></td><td>On the way</td></tr></table>', s)
                if path.startswith("/orders/") and path.endswith("/tracking"):
                    return self._page("Shipment tracking", "<p>Packed → Shipped → Out for delivery</p>", s)
                if path.startswith("/orders/"):
                    oid = path.split("/")[2]
                    return self._page(f"Order #{oid}", f"<p>2 items · ₹240</p><p><a href='/orders/{oid}/tracking'>"
                                      "Track shipment</a></p>", s)
                if path == "/account":
                    return self._page("Your account", """<form data-check method="post" action="/account" novalidate>
<label for="a-name">Name</label> <input id="a-name" name="name" required value="Demo User"><span class="field-error" id="a-name-err"></span>
<label for="a-email">Email</label> <input id="a-email" name="email" type="email" required value="demo@store.test"><span class="field-error" id="a-email-err"></span>
<label for="a-phone">Phone</label> <input id="a-phone" name="phone" type="tel" maxlength="15">
<button type="submit">Save changes</button></form>""" + FORM_JS, s)
                if path == "/addresses":
                    return self._page("Your addresses", """<p>Home: 12 Lake Road, Hyderabad 500001</p><h2>Add an address</h2>
<form data-check method="post" action="/addresses" novalidate>
<label for="ad-street">Street</label> <input id="ad-street" name="street" required><span class="field-error" id="ad-street-err"></span>
<label for="ad-city">City</label> <input id="ad-city" name="city" required><span class="field-error" id="ad-city-err"></span>
<label for="ad-pin">PIN code</label> <input id="ad-pin" name="pin" maxlength="6">
<button type="submit">Save address</button></form>""" + FORM_JS, s)
                if path == "/admin":
                    return self._page("Access denied", "<p>You are not allowed to see this page.</p>", s, 403)
                if path == "/logout":
                    return self._go("/", {"Set-Cookie": "sid=; Path=/; Max-Age=0"})
                return self._page("Not found", "<p>This page does not exist.</p>", s, 404)

            def _shop(self, q, s):
                items = [p for p in PRODUCTS if (not q.get("q") or q["q"].lower() in p["name"].lower())
                         and (not q.get("category") or p["category"] == q["category"])]
                if store.bugs and q.get("q"):  # planted bug: the search also shows 2 items that don't match
                    items += [p for p in PRODUCTS if q["q"].lower() not in p["name"].lower()][:2]
                items.sort(key={"price_asc": lambda p: p["price"], "price_desc": lambda p: -p["price"],
                                "name": lambda p: p["name"]}.get(q.get("sort", ""), lambda p: p["id"]))
                if store.bugs and q.get("sort") == "price_asc" and len(items) > 2:  # planted bug: not sorted
                    items[0], items[2] = items[2], items[0]
                page = max(1, int(q.get("page", "1") or 1))
                shown = items[(page - 1) * PER_PAGE: page * PER_PAGE]
                pages = (len(items) + PER_PAGE - 1) // PER_PAGE
                keep = {k: v for k, v in q.items() if k in ("q", "category", "sort")}
                opts = "".join(f'<option value="{v}" {"selected" if q.get("sort", "") == v else ""}>{t}</option>'
                               for v, t in (("", "Relevance"), ("price_asc", "Price: low to high"),
                                            ("price_desc", "Price: high to low"), ("name", "Name")))
                cards = "".join(f'<div class="product-card"><h3 class="product-name"><a href="/product/{p["id"]}">'
                                f'{html.escape(p["name"])}</a></h3><span class="price">₹{p["price"]}</span></div>'
                                for p in shown) or "<p>No products found</p>"
                nav = "".join(f'<a href="/shop?{urlencode(dict(keep, page=n))}">{n}</a> ' for n in range(1, pages + 1))
                if page < pages:
                    nav += f'<a href="/shop?{urlencode(dict(keep, page=page + 1))}" rel="next">Next</a>'
                datalist = "".join(f'<option value="{html.escape(n)}">' for n in NAMES)
                body = f"""<form method="get" action="/shop"><input type="search" name="q" list="names" placeholder="Search products"
 value="{html.escape(q.get('q', ''))}"><datalist id="names">{datalist}</datalist>
<label for="sort">Sort by</label> <select id="sort" name="sort" onchange="this.form.submit()">{opts}</select>
<button type="submit">Search</button></form>
<aside><h2>Category</h2><ul class="filters">{"".join(f'<li><a href="/shop?category={c}">{c.title()}</a></li>' for c in CATEGORIES)}</ul></aside>
<section>{cards}</section><div class="pagination">{nav}</div>"""
                return self._page("Shop", body, s)

            def _deals(self, s):
                """Deals: 4 shown, 4 more load when you scroll down (one links to /weekend); a help panel whose
                controls only appear after opening it; favourites need an account; 'Notify me' shows a message."""
                card = lambda d: f'<div class="deal-card"><h3>{html.escape(d)}</h3></div>'  # noqa: E731
                later = "".join(card(d) for d in DEALS[4:]) + ('<div class="deal-card"><h3><a href="/weekend">'
                                                              'Weekend special</a></h3></div>')
                notify = "" if store.bugs else (  # planted bug: the button does nothing
                    "const m = document.getElementById('deal-msg'); m.textContent = 'We will email you when new "
                    "deals arrive'; m.setAttribute('role', 'status');")
                return self._page("Today's deals", f"""<p>Fresh offers every day.</p>
<button type="button" id="open-help" aria-expanded="false" aria-controls="help" onclick="help()">Open help</button>
<div id="help" hidden><p id="tip">Tip 1: the search finds products by name.</p>
<button type="button" id="next-tip" onclick="tip()">Next tip</button>
<label><input type="checkbox" id="tip-read"> Mark as read</label></div>
<button type="button" id="{'notify-me' if store.renamed else 'notify'}" onclick="notifyMe()">Notify me</button>
<button type="button" id="fav-deal" onclick="post('/favourites/add', 'deal=1', 'deal-msg')">Add to favourites</button>
<p id="deal-msg" class="msg"></p>
<section id="deal-list">{"".join(card(d) for d in DEALS[:4])}</section><div id="more">Loading more deals…</div>
<script>{POST_JS}
const TIPS = ['Tip 1: the search finds products by name.', 'Tip 2: sort by price to find bargains.',
              'Tip 3: your cart keeps items for 7 days.'];
let t = 0;
function help() {{ const h = document.getElementById('help'), b = document.getElementById('open-help');
  h.hidden = !h.hidden; b.setAttribute('aria-expanded', String(!h.hidden)); }}
function tip() {{ t = (t + 1) % TIPS.length; document.getElementById('tip').textContent = TIPS[t]; }}
function notifyMe() {{ {notify} }}
new IntersectionObserver((es, o) => {{ if (es.some(e => e.isIntersecting)) {{
  document.getElementById('deal-list').insertAdjacentHTML('beforeend', {json.dumps(later)});
  document.getElementById('more').remove(); o.disconnect(); }} }}).observe(document.getElementById('more'));
</script>""", s)

            def _json(self, data, status=200):
                self._send(status, json.dumps(data), ctype="application/json")

            def do_POST(self):
                u = urlparse(self.path)
                store.visited.append("POST " + u.path)
                f = self._form()
                s = self._session()
                if u.path == "/favourites/add":  # (on the public deals page: a visitor is asked to sign in)
                    if not s:
                        return self._json({"message": "Please sign in to save favourites", "ok": False}, 401)
                    return self._json({"message": "Saved to your favourites"})
                if u.path == "/signin":
                    if f.get("email") != EMAIL:
                        return self._page("Sign in", SIGNIN_1.format(
                            message='<p class="field-error">We cannot find an account with that email</p>'))
                    return self._page("Sign in", SIGNIN_2.format(email=html.escape(f["email"])))
                if u.path == "/signin/password":
                    if f.get("email") != EMAIL or f.get("password") != PASSWORD:
                        return self._page("Sign in", SIGNIN_1.format(
                            message='<p class="field-error">Invalid email or password</p>'))
                    sid = secrets.token_hex(16)
                    store.sessions[sid] = {"cart": [], "wish": [], "compare": []}
                    return self._go("/dashboard", {"Set-Cookie": f"sid={sid}; Path=/; HttpOnly"})
                if not s:
                    return self._json({"message": "Please sign in", "ok": False}, 401)
                p = next((x for x in PRODUCTS if str(x["id"]) == f.get("id")), None)
                cart = s["cart"]
                count = lambda: sum(i["qty"] for i in cart)  # noqa: E731
                qty = max(1, min(10, int(f.get("qty") or 1))) if (f.get("qty") or "1").lstrip("-").isdigit() else 1
                line = int(f.get("line") or -1) if (f.get("line") or "").isdigit() else -1
                if u.path == "/cart/add" and p:
                    same = next((i for i in cart if i["id"] == p["id"] and i["size"] == f.get("size", "M")), None)
                    if same:
                        same["qty"] = min(10, same["qty"] + qty)
                    else:
                        cart.append({"id": p["id"], "name": p["name"], "size": f.get("size", "M"), "qty": qty,
                                     "price": p["price"]})
                    return self._json({"message": f"Added {p['name']} to your cart", "cart": count()})
                if u.path == "/wishlist/add" and p:
                    if store.bugs:  # planted bug: saving fails with an error message
                        return self._json({"message": "Something went wrong - the item could not be saved",
                                           "ok": False, "cart": count()})
                    s["wish"].append(p["name"])
                    return self._json({"message": "Saved to your wishlist", "cart": count()})
                if u.path == "/compare/add" and p:
                    if p["name"] not in [c["name"] for c in s["compare"]]:
                        s["compare"].append({"name": p["name"], "price": p["price"], "category": p["category"]})
                    return self._json({"message": f"Added {p['name']} to compare", "compare": len(s["compare"]),
                                       "cart": count()})
                if u.path == "/cart/update" and 0 <= line < len(cart):
                    cart[line]["qty"] = qty
                    return self._json({"message": "Cart updated", "line": qty * cart[line]["price"],
                                       "total": store._total(s), "cart": count()})
                if u.path == "/cart/remove" and 0 <= line < len(cart):
                    del cart[line]
                    return self._json({"message": "Removed from your cart", "cart": count()})
                return self._page("Not allowed", "<p>This action is not available.</p>", s, 405)

        return Handler


if __name__ == "__main__":
    demo = DemoStore(int(sys.argv[1]) if len(sys.argv) > 1 else 8766, bugs="bugs" in sys.argv[2:],
                     renamed="renamed" in sys.argv[2:]).start()
    print(f"DemoStore{' WITH PLANTED BUGS' if demo.bugs else ''} running at {demo.url}  "
          f"(email '{EMAIL}', password '{PASSWORD}') - press Ctrl+C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        demo.stop()
